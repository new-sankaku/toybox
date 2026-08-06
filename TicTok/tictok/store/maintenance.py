"""DB保守・schema migration。

境界の理由: live接続でしか正しく実行できない操作(WAL checkpoint / VACUUM /
integrity_check)と、起動時に1度だけ走るschema migration・backfillを1箇所へ集める。
どれも「操作者が明示的に起動する / 起動時に1回だけ走る」もので、収集中の通常経路から
呼ばれない点が他のmixinと違う。障害診断ctx(_db_space_ctx / _sqlite_error_ctx /
_is_fatal_sqlite)もここに置く: 退避・migration・batch writerのどのlogにも載る共通材料で、
特定domainの持ち物ではないため。

lock契約:
  _get_maintenance_locked / _set_maintenance_locked / _prune_ops_events_locked は
  self._lock 保持前提。呼び出し元は Storage.__init__ と _backup_before_migrations で、
  いずれも with self._lock: の内側から呼ぶ。
  _migrate も self._lock 保持前提(__init__ の with self._lock: 区間から呼ばれ、
  commit は __init__ が行う)。
"""
import json
import shutil
import time
from pathlib import Path

from tictok.core import dbmaint
from tictok.core.config import get_db_backup_before_migration

from tictok.store._common import (
    _MIGRATION_BACKUP_KEY,
    _SQLITE_FATAL_ERRORNAMES,
    _SQLITE_FATAL_MESSAGES,
    _migration_versions,
    _valid_owner_id,
    logger,
)


class MaintenanceMixin:
    """DB保守・schema migration。

    lockもDB接続も持たない。すべて Storage が所有する self._conn /
    self._lock / self._read_lock を借りる(mixinとして Storage に混ぜられる前提)。
    契約の詳細はmodule docstringを参照。
    """

    # ----- DB保守(退避・健全性check・VACUUM) --------------------------------------------
    # 退避fileの作成そのものは core.dbmaint が持つ(自前のread接続で行うのでingestを止めない)。
    # ここに置くのは、live接続でしか正しく実行できない操作(WAL checkpoint・VACUUM)と、
    # 起動時の退避hookである。

    def _get_maintenance_locked(self, key: str):
        row = self._conn.execute(
            "SELECT value FROM db_maintenance WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row is not None else None

    def _set_maintenance_locked(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO db_maintenance (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def _backup_before_migrations(self) -> dict:
        """破壊的migrationの直前の自動退避。__init__からのみ呼ぶ。

        起動の度に511MBを複製するのは無意味なので、退避はmigration版が上がった時だけ行う。
        判定はmigration側の選択条件を写さず、「今のmigration版のmigrationが完走済みか」という
        marker(db_maintenance表)で行う。migrationの選択SQLをここへ複製すると、片方だけ直った
        時に黙って退避されなくなる。markerはmigrationが完走した後に書くので、途中で落ちた起動は
        次回もう一度退避してからやり直す。

        退避に失敗したらmigrationは走らせず起動を止める。書き換えたrowの元の値はどこにも
        残らないため、「退避できなかったが先に進む」は取り返しのつかない選択肢になる。
        """
        if not get_db_backup_before_migration():
            return {"taken": False, "skipped": "disabled"}
        versions = _migration_versions()
        with self._lock:
            done = self._get_maintenance_locked(_MIGRATION_BACKUP_KEY)
            has_rows = self._conn.execute(
                "SELECT 1 WHERE EXISTS(SELECT 1 FROM battles)"
                " OR EXISTS(SELECT 1 FROM transcripts)").fetchone() is not None
        if done == versions:
            return {"taken": False, "skipped": "already_migrated", "versions": versions}
        if not has_rows:
            # migrationが書き換えるのはbattles表(glove/topo)とtranscripts表(timemap)だけ。
            # どちらも空なら守る対象が無い(新規DBの初回起動)。片方だけを見ていると、そちらが
            # 空のDBで退避されないまま、もう片方の書き換えが走る。
            return {"taken": False, "skipped": "no_rows", "versions": versions}
        try:
            result = dbmaint.create_backup(
                self._db_path, reason=dbmaint.REASON_PRE_MIGRATION
            )
        except Exception as exc:
            logger.error(
                "migration前のDB退避に失敗したため起動を中止します"
                "（退避なしで破壊的なmigrationを走らせません）（%s）", exc, exc_info=True,
                extra={"event": "storage.premigration_backup_failed",
                       "ctx": {"versions": versions,
                               "backup_dir": str(dbmaint.backup_dir()),
                               **self._db_space_ctx()}},
            )
            raise
        logger.info(
            "migration前のDB退避を %s に書き出しました", result["path"],
            extra={"event": "storage.premigration_backup_completed",
                   "ctx": {"versions": versions, **result}},
        )
        return {"taken": True, "versions": versions, **result}

    def db_file_status(self) -> dict:
        """DB fileとWALのsize、載っているvolumeの空き。画面が「今どれだけの物を退避するのか」
        を退避前に示すための材料。"""
        db = Path(self._db_path).resolve()
        status = {
            "path": str(db),
            "bytes": db.stat().st_size if db.is_file() else 0,
            "wal_bytes": 0,
        }
        wal = dbmaint.wal_path(db)
        if wal.is_file():
            status["wal_bytes"] = wal.stat().st_size
        status.update(self._db_space_ctx())
        return status

    def integrity_check(self) -> dict:
        """live DBのPRAGMA integrity_check。自前のread接続で走らせるので、数十秒かかっても
        収集側の書き込みは止まらない(WALのreaderはwriterを塞がない)。"""
        self.flush()
        started = time.monotonic()
        verdict = dbmaint.integrity_check_file(self._db_path)
        verdict["duration_ms"] = round((time.monotonic() - started) * 1000.0, 1)
        return verdict

    def wal_checkpoint(self) -> dict:
        """WALをDB本体へ書き戻してWAL fileを切り詰める。

        戻り値のbusyはSQLiteがそのまま返す値で、1は「readerが居て全部は書き戻せなかった」
        を意味する。成功に丸めない: WALが縮まなかったのに『完了』と表示されると、次に容量を
        疑う人が誤った前提から調べ始める。"""
        self.flush()
        started = time.monotonic()
        with self._lock:
            self._conn.commit()
            row = self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        busy, log_pages, checkpointed = (row[0], row[1], row[2]) if row else (None, None, None)
        return {
            "busy": busy,
            "log_pages": log_pages,
            "checkpointed_pages": checkpointed,
            "wal_bytes": self.db_file_status()["wal_bytes"],
            "duration_ms": round((time.monotonic() - started) * 1000.0, 1),
        }

    def vacuum(self) -> dict:
        """DB fileを作り直して断片化と削除跡の空き領域を回収する。手動実行専用。

        VACUUMはfile全体をexclusive lockで再構築するため、実行中は全ての書き込みが待たされ、
        一時的にDBとほぼ同じ大きさの作業fileも要る。自動では決して走らせない。

        WAL modeでは再構築の結果は一旦WALへ書かれ、DB file自体はcheckpointするまで1 byteも
        縮まない。checkpointまで含めて初めて「回収した」と言えるので、ここで続けて実行する
        (これを省くと必ず freed_bytes=0 と報告され、VACUUMが効いていないように見える)。"""
        self.flush()
        before = self.db_file_status()["bytes"]
        started = time.monotonic()
        with self._lock:
            # VACUUMはtransactionの中では実行できない。直前に必ずcommitして開いた暗黙の
            # transactionを閉じる。
            self._conn.commit()
            self._conn.execute("VACUUM")
            self._conn.commit()
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        after = self.db_file_status()["bytes"]
        return {
            "bytes_before": before,
            "bytes_after": after,
            "freed_bytes": before - after,
            "duration_ms": round((time.monotonic() - started) * 1000.0, 1),
        }

    # ----- 障害診断のための共通ctx ------------------------------------------------------

    def _db_space_ctx(self) -> dict:
        """DBが載るvolumeの空きとWALのsize。sqlite3.OperationalErrorの切り分けに必須で、
        『database is locked』と『database or disk is full』を後から区別する材料になる。"""
        try:
            db = Path(self._db_path).resolve()
            wal = db.with_name(db.name + "-wal")
            return {
                "free_bytes": shutil.disk_usage(db.parent).free,
                "wal_bytes": wal.stat().st_size if wal.exists() else 0,
            }
        except OSError as exc:
            # 空き容量が読めないこと自体も情報。ここで例外を投げると障害logが出せなくなる。
            return {"space_probe_error": str(exc)}

    def _sqlite_error_ctx(self, exc: BaseException) -> dict:
        """sqlite3例外の識別情報。exc_typeだけではlock/busyとdisk full/I-Oが同じ行になり、
        永久に切り分けられないため、messageとSQLiteのextended error名まで載せる。"""
        ctx = {
            "exc_type": type(exc).__name__,
            "error": str(exc),
            "sqlite_errorname": getattr(exc, "sqlite_errorname", None),
            "sqlite_errorcode": getattr(exc, "sqlite_errorcode", None),
        }
        ctx.update(self._db_space_ctx())
        return ctx

    def _is_fatal_sqlite(self, exc: BaseException) -> bool:
        """再試行では回復しない種別(disk full / I-O / 破損 / read-only)か。真なら劣化ではなく
        書き込みが恒久的に失われる障害なので、logはwarningではなくerrorで出す。"""
        name = getattr(exc, "sqlite_errorname", "") or ""
        if name.startswith(_SQLITE_FATAL_ERRORNAMES):
            return True
        message = str(exc).lower()
        return any(marker in message for marker in _SQLITE_FATAL_MESSAGES)

    def _migrate(self) -> None:
        # 転写時のmedia時間軸mapの版と実測drift。これが無いと、gapless復号由来のズレを
        # 含む既存transcript(=再転写対象)をqueryで母集団として抽出できない。
        transcript_columns = [
            row["name"] for row in self._conn.execute("PRAGMA table_info(transcripts)")
        ]
        for name, decl in (
            ("timemap_version", "INTEGER"),
            ("timemap_anchors", "INTEGER"),
            ("timemap_drift_seconds", "REAL"),
        ):
            if name not in transcript_columns:
                self._conn.execute(f"ALTER TABLE transcripts ADD COLUMN {name} {decl}")
                logger.info(
                    "transcripts表に %s columnを追加しました", name,
                    extra={"event": "storage.schema_migrated",
                           "ctx": {"table": "transcripts", "column": name}},
                )
        recording_columns = [
            row["name"] for row in self._conn.execute("PRAGMA table_info(recordings)")
        ]
        if "time_axis" not in recording_columns:
            self._conn.execute(
                "ALTER TABLE recordings ADD COLUMN time_axis TEXT NOT NULL DEFAULT 'pts'")
            logger.info(
                "recordings表にtime_axis columnを追加しました",
                extra={"event": "storage.schema_migrated",
                       "ctx": {"table": "recordings", "column": "time_axis"}},
            )
        columns = [row["name"] for row in self._conn.execute("PRAGMA table_info(events)")]
        if "comment" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN comment TEXT")
            logger.info("events表にcomment columnを追加しました")
        if "count" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN count INTEGER")
            logger.info("events表にcount columnを追加しました")
        if "user_avatar" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN user_avatar TEXT")
            logger.info("events表にuser_avatar columnを追加しました")
        if "gift_image" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN gift_image TEXT")
            logger.info("events表にgift_image columnを追加しました")
        if "gift_id" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN gift_id INTEGER")
            logger.info("events表にgift_id columnを追加しました")
        if "user_id" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN user_id TEXT")
            logger.info("events表にuser_id columnを追加しました")
        if "user_fans_level" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN user_fans_level INTEGER")
            logger.info("events表にuser_fans_level columnを追加しました")
        if "user_gifter_badge" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN user_gifter_badge TEXT")
            logger.info("events表にuser_gifter_badge columnを追加しました")
        if "user_member_badge" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN user_member_badge TEXT")
            logger.info("events表にuser_member_badge columnを追加しました")
        if "user_gifter_level" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN user_gifter_level INTEGER")
            logger.info("events表にuser_gifter_level columnを追加しました")
        for name, decl in (
            ("enter_source", "TEXT"),
            ("enter_type", "TEXT"),
            ("enter_reason", "TEXT"),
            ("follow_status", "TEXT"),
            ("follower_count", "INTEGER"),
            ("is_subscriber", "INTEGER"),
            ("is_moderator", "INTEGER"),
            ("is_gift_giver", "INTEGER"),
            # ShareEvent.share_type / share_target。生値のTEXT。share_targetは実配信で
            # '-1' と '112' の2値を観測しているが、何を指すかは未確定なので解釈を付けない。
            ("share_type", "TEXT"),
            ("share_target", "TEXT"),
            # CommentEvent.content_language(TikTok側の言語判定) / comment_tag(enum名のJSON list)。
            # どちらも後から追加されたfieldで、古い収集分では届かない。
            ("content_language", "TEXT"),
            ("comment_tag", "TEXT"),
        ):
            if name not in columns:
                # backfillはしない。既存行は「計装前で未計測」であって「不明と観測した」
                # ではないため、NULLのまま残すことが唯一正しい状態である。
                self._conn.execute(f"ALTER TABLE events ADD COLUMN {name} {decl}")
                logger.info(
                    "events表に %s columnを追加しました", name,
                    extra={"event": "storage.schema_migrated",
                           "ctx": {"table": "events", "column": name}},
                )
        if "emotes" not in columns:
            # JSON list of TikTok custom emotes carried by a comment (each a stable
            # emote_id + CDN image URL + insertion index) so the burn-in can render
            # them as inline images instead of the raw [shortcode] text.
            self._conn.execute("ALTER TABLE events ADD COLUMN emotes TEXT")
            logger.info("events表にemotes columnを追加しました")
        user_columns = [row["name"] for row in self._conn.execute("PRAGMA table_info(users)")]
        if "gifter_level" not in user_columns:
            self._conn.execute("ALTER TABLE users ADD COLUMN gifter_level INTEGER NOT NULL DEFAULT 0")
            logger.info("users表にgifter_level columnを追加しました")
        for name, decl in (
            # 視聴者が配信者でもあるかと、その配信者リーグ帯。既存行はNULL/空=未確認で、
            # backfillはしない(未確認と「確認して配信者ではなかった」は別物である)。
            ("broadcaster", "INTEGER"),
            ("broadcaster_room_id", "TEXT NOT NULL DEFAULT ''"),
            ("league", "TEXT NOT NULL DEFAULT ''"),
            ("league_checked_at", "REAL"),
        ):
            if name not in user_columns:
                self._conn.execute(f"ALTER TABLE users ADD COLUMN {name} {decl}")
                logger.info(
                    "users表に %s columnを追加しました", name,
                    extra={"event": "storage.schema_migrated",
                           "ctx": {"table": "users", "column": name}},
                )
        if "create_time" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN create_time REAL")
            logger.info("events表にcreate_time columnを追加しました")
        if "identity_key" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN identity_key TEXT")
            # 既存eventのidentity_keyを不変ID優先(user_id -> unique_id -> nickname)で確定。
            # TRIM込みでPython側の_identity_key(strip)と完全一致させる。
            self._conn.execute(
                "UPDATE events SET identity_key = COALESCE("
                " NULLIF(TRIM(user_id), ''), NULLIF(TRIM(user_unique_id), ''),"
                " TRIM(user_nickname))"
            )
            logger.info("events表にidentity_key columnを追加し既存行を埋めました")
        # 新規/既存いずれのDBでもindexを保証する(columnはSCHEMAまたは上のALTERで存在)。
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_identity ON events(identity_key)"
        )
        # kind単独絞り込み(全体解析のconcentration/gift単価表)用のcovering index。
        # events本体は1行が重く(text/json列)、これが無いとkind条件が全表scanになる。
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_kind_identity"
            " ON events(kind, identity_key, diamonds, session_id, time)"
        )
        # 逆引き補完 + users表再構成。identity_key列が既にある旧migration適用済みDBにも
        # 一度だけ効かせるため、column追加とは独立にsettings markerで管理する。
        if not self._migration_done("reverse_link_v1"):
            self._reverse_link_identities()
            self._conn.execute("DELETE FROM users")
            self._backfill_users()
            self._mark_migration("reverse_link_v1")
        session_columns = [row["name"] for row in self._conn.execute("PRAGMA table_info(sessions)")]
        if "owner_nickname" not in session_columns:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN owner_nickname TEXT")
            logger.info("sessions表にowner_nickname columnを追加しました")
        if "owner_avatar" not in session_columns:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN owner_avatar TEXT")
            logger.info("sessions表にowner_avatar columnを追加しました")
        if "owner_user_id" not in session_columns:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN owner_user_id TEXT")
            logger.info("sessions表にowner_user_id columnを追加しました")
        if "league" not in session_columns:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN league TEXT")
            logger.info("sessions表にleague columnを追加しました")
        if "live_create_time" not in session_columns:
            # room_infoが返す配信そのものの開始時刻(TikTok server権威値)。started_atは
            # collectorが接続した時刻でしかないため、収集開始遅延はこの2値の差でしか測れない。
            self._conn.execute("ALTER TABLE sessions ADD COLUMN live_create_time REAL")
            logger.info(
                "sessions表にlive_create_time columnを追加しました",
                extra={"event": "storage.schema_migrated",
                       "ctx": {"table": "sessions", "column": "live_create_time"}},
            )
        if "conn_instrumentation" not in session_columns:
            # 既存行はNULLのまま(=接続系markerの計装より前の収集)。遡って埋めてはいけない。
            self._conn.execute("ALTER TABLE sessions ADD COLUMN conn_instrumentation INTEGER")
            logger.info(
                "sessions表にconn_instrumentation columnを追加しました",
                extra={"event": "storage.schema_migrated",
                       "ctx": {"table": "sessions", "column": "conn_instrumentation"}},
            )
        recording_columns = [
            row["name"] for row in self._conn.execute("PRAGMA table_info(recordings)")
        ]
        if "protected" not in recording_columns:
            # 保持policyの自動削除から明示的に除外するflag。生録画は再取得不能なので、
            # 「消してよいか」の判断をoperatorが録画単位で固定できる手段が要る。
            self._conn.execute(
                "ALTER TABLE recordings ADD COLUMN protected INTEGER NOT NULL DEFAULT 0"
            )
            logger.info(
                "recordings表にprotected columnを追加しました",
                extra={"event": "storage.schema_migrated",
                       "ctx": {"table": "recordings", "column": "protected"}},
            )
        if "audio_normalized_at" not in recording_columns:
            # 既存録画はNULL(未適用)から始める。過去のmp4が正規化済みかどうかは、file
            # からは判別できない(loudnormは痕跡を残さない)ので推測で埋めてはいけない。
            self._conn.execute("ALTER TABLE recordings ADD COLUMN audio_normalized_at REAL")
            self._conn.execute("ALTER TABLE recordings ADD COLUMN audio_normalized_lufs REAL")
            logger.info(
                "recordings表に音量の正規化用columnを追加しました",
                extra={"event": "storage.schema_migrated",
                       "ctx": {"table": "recordings",
                               "column": "audio_normalized_at,audio_normalized_lufs"}},
            )
        if "reprocessed_at" not in recording_columns:
            # 再mp4化に「済み」の印が無かったため、一括投入は.tsが残っている録画を毎回
            # 全部作り直していた。同じ内容を作り直すたびに元mp4が_backupへ積まれ(実測で
            # 同一録画に3世代)、退避だけで307GBに達していた。作り直しは元動画を差し替える
            # 不可逆な操作なので、既定では一度で足りる。
            self._conn.execute("ALTER TABLE recordings ADD COLUMN reprocessed_at REAL")
            # 既存ぶんはjob台帳から埋める。完了した再mp4化の記録がそのまま「作り直した」
            # 事実で、fileからの推測ではない。台帳が消えている古い録画はNULLのまま残る。
            self._conn.execute(
                "UPDATE recordings SET reprocessed_at = ("
                "  SELECT MAX(q.finished_at) FROM media_job_queue q"
                "  WHERE q.recording_id = recordings.id AND q.kind = 'reprocess'"
                "    AND q.state = 'completed')"
            )
            backfilled = self._conn.execute(
                "SELECT COUNT(*) AS n FROM recordings WHERE reprocessed_at IS NOT NULL"
            ).fetchone()["n"]
            logger.info(
                "recordings表にreprocessed_at columnを追加しました（%d 行を埋めました）",
                backfilled,
                extra={"event": "storage.schema_migrated",
                       "ctx": {"table": "recordings", "column": "reprocessed_at",
                               "backfilled": backfilled}},
            )
        if "duration_seconds" not in recording_columns:
            # 尺の出所を壁時計(ended_at - started_at)から実測へ移す。既存行はNULL(未測定)
            # から始め、転写を持つ録画だけ転写側の実尺で埋める(転写はmp4そのものを読んで
            # 作られており、fileからの推測ではない)。残りは scripts/repair_recording_
            # durations.py がmp4/HLSを測って埋める。
            self._conn.execute("ALTER TABLE recordings ADD COLUMN duration_seconds REAL")
            self._conn.execute(
                "UPDATE recordings SET duration_seconds = ("
                "  SELECT t.duration FROM transcripts t"
                "  WHERE t.recording_id = recordings.id AND t.duration > 0)"
            )
            backfilled = self._conn.execute(
                "SELECT COUNT(*) AS n FROM recordings WHERE duration_seconds IS NOT NULL"
            ).fetchone()["n"]
            logger.info(
                "recordings表にduration_seconds columnを追加しました（%d 行を埋めました）",
                backfilled,
                extra={"event": "storage.schema_migrated",
                       "ctx": {"table": "recordings", "column": "duration_seconds",
                               "backfilled": backfilled}},
            )
        if "review_state" not in recording_columns:
            # 「観たかどうか」の印。既存録画はすべて未確認から始める: 観たか否かはDBのどの
            # 列からも導けないので、推測で確認済みを配ると印そのものが信用できなくなる。
            self._conn.execute(
                "ALTER TABLE recordings ADD COLUMN review_state TEXT NOT NULL"
                " DEFAULT 'unchecked'"
            )
            self._conn.execute("ALTER TABLE recordings ADD COLUMN review_updated_at REAL")
            logger.info(
                "recordings表に確認状態のcolumnを追加しました",
                extra={"event": "storage.schema_migrated",
                       "ctx": {"table": "recordings",
                               "column": "review_state,review_updated_at"}},
            )
        target_columns = [row["name"] for row in self._conn.execute("PRAGMA table_info(monitored_targets)")]
        if "record_video" not in target_columns:
            self._conn.execute(
                "ALTER TABLE monitored_targets ADD COLUMN record_video INTEGER NOT NULL DEFAULT 1"
            )
            logger.info("monitored_targets表にrecord_video columnを追加しました")
        # 配信者の不変数値IDをBattleのis_own participantから復元してsessionsへ補完し、
        # ゴミ(team_id混入等)のown-host user_idを実IDへ修復する。marker一度きり。
        if not self._migration_done("owner_user_id_v1"):
            self._backfill_owner_user_ids()
            self._mark_migration("owner_user_id_v1")
        self._migrate_ops_events()
        bookmark_columns = [
            row["name"] for row in self._conn.execute("PRAGMA table_info(bookmarks)")
        ]
        if "live_wall" not in bookmark_columns:
            # 既存行は/videosで動画時間から作られたもの。startは既にPTS軸なので
            # pts_mapped=1(既定)のままで正しく、live_wallはNULL(live押下ではない)。
            self._conn.execute("ALTER TABLE bookmarks ADD COLUMN live_wall REAL")
            self._conn.execute(
                "ALTER TABLE bookmarks ADD COLUMN pts_mapped INTEGER NOT NULL DEFAULT 1"
            )
            logger.info(
                "bookmarks表にlive_wall/pts_mapped columnを追加しました",
                extra={"event": "storage.schema_migrated",
                       "ctx": {"table": "bookmarks", "column": "live_wall,pts_mapped"}},
            )
        if "group_id" not in bookmark_columns:
            # 切り抜きグループ(clip_groups)への所属。既存行は未分類(NULL)から始める。
            self._conn.execute(
                "ALTER TABLE bookmarks ADD COLUMN group_id INTEGER REFERENCES clip_groups(id)"
            )
            logger.info(
                "bookmarks表にgroup_id columnを追加しました",
                extra={"event": "storage.schema_migrated",
                       "ctx": {"table": "bookmarks", "column": "group_id"}},
            )
        cut_columns = [
            row["name"] for row in self._conn.execute("PRAGMA table_info(cut_list)")
        ]
        if "group_id" not in cut_columns:
            # グループへの所属とグループ内の並び順(EDL/FCPXMLの書き出し順)。既存行は未分類(NULL)。
            self._conn.execute(
                "ALTER TABLE cut_list ADD COLUMN group_id INTEGER REFERENCES clip_groups(id)"
            )
            self._conn.execute("ALTER TABLE cut_list ADD COLUMN position INTEGER")
            logger.info(
                "cut_list表にgroup_id/position columnを追加しました",
                extra={"event": "storage.schema_migrated",
                       "ctx": {"table": "cut_list", "column": "group_id,position"}},
            )
        media_job_columns = [
            row["name"] for row in self._conn.execute("PRAGMA table_info(media_job_queue)")
        ]
        if "params_json" not in media_job_columns:
            # clip一括書き出しは「どの範囲を」という投入時の指定を実行時まで運ぶ必要がある。
            # 焼き込み/Up出力は録画idだけで再現できたためこの列が無かった。
            self._conn.execute(
                "ALTER TABLE media_job_queue ADD COLUMN params_json TEXT NOT NULL DEFAULT '{}'"
            )
            logger.info(
                "media_job_queue表にparams_json columnを追加しました",
                extra={"event": "storage.schema_migrated",
                       "ctx": {"table": "media_job_queue", "column": "params_json"}},
            )
        if "not_before" not in media_job_columns:
            # 保存先volumeの不在のような「待てば直る」前提不成立を、失敗ではなく待機で
            # 表すための列。not_before までworkerは拾わず、deferred_since で総待ち時間を
            # 打ち切る(待ち続けるqueueは、動いているように見えて何も進まない)。
            self._conn.execute("ALTER TABLE media_job_queue ADD COLUMN not_before REAL")
            self._conn.execute("ALTER TABLE media_job_queue ADD COLUMN deferred_since REAL")
            logger.info(
                "media_job_queue表にnot_before/deferred_since columnを追加しました",
                extra={"event": "storage.schema_migrated",
                       "ctx": {"table": "media_job_queue",
                               "column": "not_before,deferred_since"}},
            )
        if "stages_json" not in media_job_columns:
            # 段階の遷移履歴。既存行は空listで入る(過ぎた実行の段階は復元できない — log
            # にしか残っていないので、ここで推測して埋めると出所の無い記録になる)。
            self._conn.execute(
                "ALTER TABLE media_job_queue ADD COLUMN stages_json TEXT NOT NULL DEFAULT '[]'"
            )
            logger.info(
                "media_job_queue表にstages_json columnを追加しました",
                extra={"event": "storage.schema_migrated",
                       "ctx": {"table": "media_job_queue", "column": "stages_json"}},
            )
        if "sweep" not in media_job_columns:
            # 起動時sweepが自動で積んだ行の目印。既存行は人の投入として0で入る(実際、この列が
            # 無かった頃に積まれたsweep行はpackだけで、人の投入と同じ扱いで走っていた)。
            self._conn.execute(
                "ALTER TABLE media_job_queue ADD COLUMN sweep INTEGER NOT NULL DEFAULT 0"
            )
            logger.info(
                "media_job_queue表にsweep columnを追加しました",
                extra={"event": "storage.schema_migrated",
                       "ctx": {"table": "media_job_queue", "column": "sweep"}},
            )

    def _migrate_ops_events(self) -> None:
        """ops_eventsの列をSCHEMA定義へ揃える。CREATE TABLE IF NOT EXISTSは既存表の列を
        追加しないため、列を足す時はここに1行足すこと(events表と同じ流儀)。lock保持前提。"""
        columns = [row["name"] for row in self._conn.execute("PRAGMA table_info(ops_events)")]
        if "job_id" not in columns:
            # 焼き込みやupscaleはsub-process/worker threadを跨ぐため、Layer1のlog群と
            # ops_eventsを突き合わせる鍵がjob_id以外に無い。
            self._conn.execute("ALTER TABLE ops_events ADD COLUMN job_id TEXT")
            logger.info("ops_events表にjob_id columnを追加しました")
        if "duration_ms" not in columns:
            self._conn.execute("ALTER TABLE ops_events ADD COLUMN duration_ms REAL")
            logger.info("ops_events表にduration_ms columnを追加しました")

    def _migration_done(self, name: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM settings WHERE key = ?", (f"_migration:{name}",)
        ).fetchone()
        return row is not None

    def _mark_migration(self, name: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, '1')",
            (f"_migration:{name}",),
        )

    def _backfill_owner_user_ids(self) -> None:
        """配信者(owner)の不変数値IDをBattleのis_own participantから復元する。@handleごとに
        妥当な数値IDを多数決で1つ選び(ゴミIDは除外)、その@handleの全sessionへ補完。さらに
        battles.data_json内のown-hostのゴミuser_id(team_id混入等)を実IDへ修復する。lock保持前提。"""
        from collections import Counter
        battle_rows = self._conn.execute(
            "SELECT b.rowid AS rid, b.data_json AS d, s.unique_id AS handle"
            " FROM battles b JOIN sessions s ON s.id = b.session_id"
        ).fetchall()
        parsed = []
        votes: dict = {}
        for r in battle_rows:
            try:
                battle = json.loads(r["d"])
            except (ValueError, TypeError):
                continue
            parsed.append((r["rid"], r["handle"], battle))
            for p in battle.get("participants", []) or []:
                if p.get("is_own") and _valid_owner_id(p.get("user_id")):
                    votes.setdefault(r["handle"], Counter())[str(p["user_id"])] += 1
        handle_owner = {h: c.most_common(1)[0][0] for h, c in votes.items() if c}
        if not handle_owner:
            logger.info("owner_user_idの補完: 復元できる数値のowner idがありません")
            return
        # 各@handleの全sessionへ数値owner IDを補完(未設定のみ)。
        filled = 0
        for handle, owner_id in handle_owner.items():
            cur = self._conn.execute(
                "UPDATE sessions SET owner_user_id = ?"
                " WHERE unique_id = ? AND (owner_user_id IS NULL OR owner_user_id = '')",
                (owner_id, handle),
            )
            filled += cur.rowcount
        # battles内のown-hostゴミIDを実IDへ修復。
        repaired = 0
        for rid, handle, battle in parsed:
            owner_id = handle_owner.get(handle)
            if not owner_id:
                continue
            changed = False
            for p in battle.get("participants", []) or []:
                if p.get("is_own") and not _valid_owner_id(p.get("user_id")):
                    p["user_id"] = owner_id
                    changed = True
            if changed:
                self._conn.execute(
                    "UPDATE battles SET data_json = ? WHERE rowid = ?",
                    (json.dumps(battle, ensure_ascii=False), rid),
                )
                repaired += 1
        logger.info(
            "owner_user_idの補完: handle %d 件を解決、session %d 件を補完、battle %d 件を修復",
            len(handle_owner), filled, repaired,
        )

    def _reverse_link_identities(self) -> None:
        """@handle止まり(数値user_id空)の古いeventを、同じ@handleを持つ数値user_id付き
        eventから逆引きして数値IDへ名寄せし直す(events.identity_keyを数値IDへ更新)。
        1つの@handleが複数の数値user_idに対応する曖昧なケースは、handle使い回しによる
        誤結合を避けるため変更しない。migration一度きり。lock保持前提。"""
        # @handle -> 対応する数値user_idの集合。
        rows = self._conn.execute(
            "SELECT user_unique_id AS handle, user_id"
            " FROM events"
            " WHERE user_unique_id IS NOT NULL AND user_unique_id != ''"
            "   AND user_id IS NOT NULL AND user_id != ''"
            " GROUP BY user_unique_id, user_id"
        ).fetchall()
        handle_to_ids: dict = {}
        for row in rows:
            handle_to_ids.setdefault(row["handle"], set()).add(row["user_id"])
        unambiguous = [
            (uid_set.pop(), handle)
            for handle, uid_set in handle_to_ids.items()
            if len(uid_set) == 1
        ]
        if not unambiguous:
            return
        # user_unique_id検索を高速化(逆引きUPDATEのため)。
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_uhandle ON events(user_unique_id)"
        )
        updated = 0
        for numeric_id, handle in unambiguous:
            cur = self._conn.execute(
                "UPDATE events SET identity_key = ?"
                " WHERE (user_id IS NULL OR user_id = '') AND user_unique_id = ?"
                "   AND identity_key != ?",
                (numeric_id, handle, numeric_id),
            )
            updated += cur.rowcount
        logger.info(
            "@handleのみの event %d 件を数値のuser_idへ逆引きしました（一意なhandle %d 件）",
            updated,
            len(unambiguous),
        )

    def _backfill_users(self) -> None:
        """既存eventからusers表を再構成する(migration一度きり)。時系列順に同じupsert
        を適用するので、live取り込みと完全に同じ最新値上書きロジックになる。lock保持前提。"""
        rows = self._conn.execute(
            "SELECT identity_key, user_id, user_unique_id AS unique_id, user_nickname AS nickname,"
            " user_avatar AS avatar, user_fans_level AS fans_level,"
            " user_gifter_level AS gifter_level,"
            " user_gifter_badge AS gifter_badge, user_member_badge AS member_badge, time"
            " FROM events WHERE identity_key IS NOT NULL AND identity_key != ''"
            " ORDER BY time"
        ).fetchall()
        count = 0
        for row in rows:
            # events.identity_key(逆引き補完済み)を尊重。recomputeするとhandle止まりへ戻る。
            if self._upsert_user_locked(dict(row), row["time"] or 0, key=row["identity_key"]):
                count += 1
        logger.info("event %d 件からusers表を再構成しました", count)
