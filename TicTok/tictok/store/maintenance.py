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
from tictok.core.config import (
    get_db_analyze_enabled,
    get_db_analyze_growth_ratio,
    get_db_backup_before_migration,
    get_row_trash_keep_days,
)

from tictok.store import row_trash

from tictok.store._common import (
    _ANALYZE_STATE_KEY,
    _INTERN_MIGRATE_CHUNK_ROWS,
    _INTERN_PHASE_CONTRACT,
    _INTERN_PHASE_EXPAND,
    _INTERN_PHASE_KEY,
    _INTERN_PHASE_NONE,
    _INTERN_TARGET_PHASE,
    _INTERNED_CONTRIBUTOR_COLUMNS,
    _INTERN_STRIPPED_COLUMNS,
    _INTERN_STRIP_KEY,
    _INTERN_STRIP_VERSION,
    _INTERNED_EVENT_COLUMNS,
    _MIGRATION_BACKUP_KEY,
    _SEARCH_FOLD_KEY,
    _SQLITE_FATAL_ERRORNAMES,
    _SQLITE_FATAL_MESSAGES,
    _events_insert_sql,
    _migration_versions,
    _string_hash,
    _valid_owner_id,
    logger,
)


class MaintenanceMixin:
    """DB保守・schema migration。

    lockもDB接続も持たない。すべて Storage が所有する self._conn /
    self._lock / _read_connection() を借りる(mixinとして Storage に混ぜられる前提)。
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

    def get_maintenance_value(self, key: str):
        """``db_maintenance`` の値を1つ読む。無ければ None。

        ``_get_maintenance_locked`` と分けてあるのは、あちらが既にlockを取っている
        migration経路の中から呼ばれる前提だからである。こちらはlockを取る ―― 起動後の
        background taskが「どこまで退避したか」の印を読むための口で、他のkeyとは呼ばれる
        文脈が違う。

        ここに置いてよいのは**失っても困らない予定の記録**だけである。行数の見張りの台帳を
        DBの外(退避先)へ置いているのと対になる判断で、あちらはDBが壊れた瞬間に一緒に失われ
        ては困る。こちらは失っても、次の周期が同じ録画をもう一度退避するだけで済む。"""
        with self._lock:
            return self._get_maintenance_locked(key)

    def set_maintenance_value(self, key: str, value: str) -> None:
        """``db_maintenance`` の値を1つ書く。用途の制限は :meth:`get_maintenance_value`。"""
        with self._lock:
            self._set_maintenance_locked(key, value)
            self._conn.commit()

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
            # eventsを含めるのは、重複文字列のintern(migrate_event_interning)が**events表の
            # 旧列を落とす**ためである。これを入れないと、battlesとtranscriptsが空でeventsだけ
            # 在るDBが、退避を取らないまま旧列を落とすことになる ―― 落とした値はどこにも残らない。
            has_rows = self._conn.execute(
                "SELECT 1 WHERE EXISTS(SELECT 1 FROM battles)"
                " OR EXISTS(SELECT 1 FROM transcripts)"
                " OR EXISTS(SELECT 1 FROM events)").fetchone() is not None
            # cut_listの統合は表そのものを落とす。上の2表が空でも、畳む行が残っていれば
            # 守る対象は在る。
            if not has_rows and self._has_table("cut_list"):
                has_rows = self._conn.execute(
                    "SELECT 1 WHERE EXISTS(SELECT 1 FROM cut_list)").fetchone() is not None
        if done == versions:
            return {"taken": False, "skipped": "already_migrated", "versions": versions}
        if not has_rows:
            # migrationが書き換えるのはbattles表(glove/topo)・transcripts表(timemap)・
            # cut_list表(統合)だけ。どれも空なら守る対象が無い(新規DBの初回起動)。
            # 1つだけを見ていると、そちらが空のDBで退避されないまま他の書き換えが走る。
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

    # ----- plannerの統計(sqlite_stat1) --------------------------------------------------

    def _events_row_estimate_locked(self) -> int:
        """eventsの行数の当たり。lock保持前提。

        COUNT(*)ではなくMAX(rowid)で測る。eventsは実測120万行あり、COUNT(*)は毎起動で
        index 1本を頭から舐める。ここで欲しいのは「前回ANALYZEの時点からどれだけ伸びたか」
        という一桁の精度で、rowidはINTEGER PRIMARY KEY(=rowid)なのでB-treeの右端1回で済む。

        session削除でrowidが飛んでも過大評価になるだけで、ANALYZEが早めに走るという
        安全側へ倒れる。"""
        row = self._conn.execute("SELECT MAX(rowid) AS n FROM events").fetchone()
        return int(row["n"] or 0)

    def ensure_planner_stats(self) -> dict:
        """plannerの統計(sqlite_stat1)を採り直す。__init__からのみ呼ぶ(lockは自分で取る)。

        **なぜ要るのか。** 統計が無いとSQLiteは全てのindexを同じ経験則で見積もる。実データ
        では、Battleの貢献集計(battles.battle_gift_contributions)がその見積もりで
        ``idx_events_kind_identity`` を選び、Battle 1件ごとに全gift eventを走査していた。
        正しいのは ``idx_events_session_kind_time`` で、copy DBでの実測は1,417窓あたり
        4,596ms(統計なし)対 526ms(統計あり)、返る行は6,269行で完全一致。

        **なぜ起動時なのか。** ANALYZEは書き込みであり、実測2.3秒のあいだwrite lockを
        保持する。収集中に走らせるとcollectorのdrainがその間止まる。__init__のこの地点は
        writer threadを起こす前で、まだ誰もこの接続を待っていない唯一の窓である。

        **なぜ毎起動ではないのか。** 起動は実測1.65秒で、2.3秒を無条件に足すと倍以上になる。
        統計が動く要因は表の大きさとindexの選択性なので、eventsの行数の伸びで測る
        (閾値はTICTOK_DB_ANALYZE_GROWTH_RATIO)。統計そのものが無い起動は伸びに関わらず
        必ず採る — 無い状態は「古い」ではなく「plannerが誤選択する」状態である。

        **なぜ analysis_limit を掛けないのか。** 掛けると速いが効かない。同じcopy DBで
        ``analysis_limit=1000`` を測ると0.94秒で終わる代わりにplanは
        ``idx_events_kind_identity`` のまま変わらなかった(sampleが足りずindexの選択性を
        誤ったまま記録する)。速いが効かない統計は、無い統計より悪い — 「ANALYZE済み」と
        いうmarkerだけが残る。

        失敗は握り潰さない。ここで落ちるのはdisk full / I-O / 破損の類で、どのみち数秒後に
        writerが同じ壁に当たる。統計が採れないまま黙って起動すると、遅さの原因が
        「統計が無い」ことだと誰も辿れなくなる。"""
        if not get_db_analyze_enabled():
            return {"analyzed": False, "skipped": "disabled"}
        with self._lock:
            has_stats = self._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'sqlite_stat1'"
            ).fetchone() is not None
            rows = self._events_row_estimate_locked()
            state = self._get_maintenance_locked(_ANALYZE_STATE_KEY)
        baseline = None
        if state:
            try:
                baseline = int(json.loads(state)["rows"])
            except (ValueError, TypeError, KeyError):
                # markerが読めない = 前回いつ採ったか分からない。採り直す方へ倒す。
                baseline = None
        ratio = get_db_analyze_growth_ratio()
        if has_stats and baseline is not None:
            growth = rows - baseline
            if growth < baseline * ratio:
                return {"analyzed": False, "skipped": "fresh", "rows": rows,
                        "baseline_rows": baseline, "growth_rows": growth}
        started = time.monotonic()
        with self._lock:
            # ANALYZEの前に開いている暗黙のtransactionを閉じる。migrationの書き込みを
            # 巻き込んだまま数秒のtransactionを開くと、write lockの保持がそのぶん延びる。
            self._conn.commit()
            # 0 = 上限なし。値の根拠はdocstringを参照(1000では plan が変わらない)。
            self._conn.execute("PRAGMA analysis_limit=0")
            self._conn.execute("ANALYZE")
            self._set_maintenance_locked(
                _ANALYZE_STATE_KEY, json.dumps({"rows": rows, "at": time.time()})
            )
            self._conn.commit()
        duration_ms = round((time.monotonic() - started) * 1000.0, 1)
        result = {"analyzed": True, "rows": rows, "baseline_rows": baseline,
                  "had_stats": has_stats, "duration_ms": duration_ms}
        logger.info(
            "plannerの統計を採り直しました（events %d 行 / %.1f 秒）",
            rows, duration_ms / 1000.0,
            extra={"event": "storage.planner_stats_analyzed", "ctx": result},
        )
        return result

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
        # 文字起こし時のmedia時間軸mapの版と実測drift。これが無いと、gapless復号由来のズレを
        # 含む既存transcript(=再文字起こし対象)をqueryで母集団として抽出できない。
        transcript_columns = [
            row["name"] for row in self._conn.execute("PRAGMA table_info(transcripts)")
        ]
        for name, decl in (
            ("timemap_version", "INTEGER"),
            ("timemap_anchors", "INTEGER"),
            ("timemap_drift_seconds", "REAL"),
            # 語ごとの時刻を持つか。持たない文字起こしはcueを語の端で締められず、segmentの終端が
            # 次のsegmentの開始まで伸びたまま出る(実測: SRTがtimelineを覆う割合が中央値
            # 97.7%。実発話は約30%)。segments_jsonを毎回舐めずに「再文字起こしが要る母集団」を
            # queryで引けるよう、行に持たせる。
            ("word_times", "INTEGER"),
        ):
            if name not in transcript_columns:
                self._conn.execute(f"ALTER TABLE transcripts ADD COLUMN {name} {decl}")
                logger.info(
                    "transcripts表に %s columnを追加しました", name,
                    extra={"event": "storage.schema_migrated",
                           "ctx": {"table": "transcripts", "column": name}},
                )
        if "word_times" not in transcript_columns:
            # 既存行の埋め戻し。segments_jsonはJSONへ起こさず文字列のまま探す(1本800KB級を
            # 331本parseすると起動がそのぶん延びる)。語を持つ文字起こしは必ず ``"words":`` を含む。
            filled = self._conn.execute(
                "UPDATE transcripts SET word_times ="
                " CASE WHEN instr(segments_json, '\"words\"') > 0 THEN 1 ELSE 0 END"
            ).rowcount
            with_words = self._conn.execute(
                "SELECT COUNT(*) FROM transcripts WHERE word_times = 1").fetchone()[0]
            logger.info(
                "既存transcript %d 件のword_timesを判定しました（語の時刻あり %d 件）",
                filled, with_words,
                extra={"event": "storage.schema_backfilled",
                       "ctx": {"table": "transcripts", "column": "word_times",
                               "rows": filled, "with_word_times": with_words}},
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
        # 笑い声indexを最後に張った条件(rule版と共演の除外設定)。既存行はNULLのまま残す
        # ―― 過去のindexは共演中を外していないので、現行の条件で張ったと名乗らせては
        # ならない。一括処理の済み判定がこの列を見るため、NULLの録画は自動で対象へ戻る。
        if "laugh_index_json" not in recording_columns:
            self._conn.execute("ALTER TABLE recordings ADD COLUMN laugh_index_json TEXT")
            logger.info(
                "recordings表にlaugh_index_json columnを追加しました（既存indexは条件不明）",
                extra={"event": "storage.schema_migrated",
                       "ctx": {"table": "recordings", "column": "laugh_index_json"}},
            )
        # コラボ窓の判定rule版。既存行は旧rule(v1)の収集物なので1のまま残す。v1は窓を
        # finishでしか閉じず、間のソロ時間を丸ごとコラボに数えていた(録画照合で判明)。
        # 補正材料がDBに無いため、分析側は現行版の窓だけを使う。
        collab_columns = [
            row["name"] for row in self._conn.execute("PRAGMA table_info(collab_windows)")
        ]
        if "version" not in collab_columns:
            self._conn.execute(
                "ALTER TABLE collab_windows ADD COLUMN version INTEGER NOT NULL DEFAULT 1")
            logger.info(
                "collab_windows表にversion columnを追加しました（既存窓は旧rule=1）",
                extra={"event": "storage.schema_migrated",
                       "ctx": {"table": "collab_windows", "column": "version"}},
            )
        # cut_listは廃止した表で、この後の統合migrationがbookmarksへ畳んでDROPする。
        # 畳む前に列が揃っている必要があるので、表が残っているDBに限って旧migrationを通す。
        if self._has_table("cut_list"):
            cut_columns = [
                row["name"] for row in self._conn.execute("PRAGMA table_info(cut_list)")
            ]
            for name, decl in (
                # 最後にmp4を書き出した時刻と出力path。既存行はNULLのまま残す — 過去に
                # 書き出した行も在るが、どこへ出したかは記録が無く、backfillすれば捏造になる。
                ("exported_at", "REAL"),
                ("exported_path", "TEXT"),
            ):
                if name not in cut_columns:
                    self._conn.execute(f"ALTER TABLE cut_list ADD COLUMN {name} {decl}")
                    logger.info(
                        "cut_list表に %s columnを追加しました", name,
                        extra={"event": "storage.schema_migrated",
                               "ctx": {"table": "cut_list", "column": name}},
                    )
            # 元になった見どころ。追加時は範囲が一致するので既存行も辿れるが、切り出しの
            # IN/OUTは詰めるためにあるので、詰めた行は範囲では二度と辿れない。
            if "bookmark_id" not in cut_columns:
                self._conn.execute("ALTER TABLE cut_list ADD COLUMN bookmark_id INTEGER")
                logger.info(
                    "cut_list表にbookmark_id columnを追加しました",
                    extra={"event": "storage.schema_migrated",
                           "ctx": {"table": "cut_list", "column": "bookmark_id"}},
                )
                self._backfill_cut_bookmark_ids()
            # 見どころのメモと切り出しのラベルは昇格の時点で同じ物になるが、以後メモだけを
            # 直した分は切り出し側へ届いていない。列の有無とは独立の一度きりの反映なので、
            # settings markerで管理する(bookmark_id列は既に在るDBにも効かせる)。
            if not self._migration_done("cut_label_from_memo_v1"):
                self._sync_cut_labels_from_memo()
                self._mark_migration("cut_label_from_memo_v1")
        # 語を持たない行(笑い声)の強さ。既存行はNULLのまま残す — 本文の「強さ 0.78」から
        # 読み戻せば埋まるが、それは表示の書式を数値の出所にすることなので行わない。強さ順は
        # NULLを末尾へ落とし、笑い声分析を入れ直した録画から順に値が付く。
        hit_columns = [
            row["name"] for row in self._conn.execute("PRAGMA table_info(search_hits)")
        ]
        if "score" not in hit_columns:
            self._conn.execute("ALTER TABLE search_hits ADD COLUMN score REAL")
            logger.info(
                "search_hits表にscore columnを追加しました",
                extra={"event": "storage.schema_migrated",
                       "ctx": {"table": "search_hits", "column": "score"}},
            )
        # 焼く要素をcommentから分離した後に足した列。既存の型はDEFAULTのまま残す。
        preset_columns = [
            row["name"] for row in self._conn.execute("PRAGMA table_info(clip_presets)")
        ]
        for name, decl in (
            ("gifts", "INTEGER NOT NULL DEFAULT 0"),
            ("score_bar", "INTEGER NOT NULL DEFAULT 1"),
        ):
            if preset_columns and name not in preset_columns:
                self._conn.execute(f"ALTER TABLE clip_presets ADD COLUMN {name} {decl}")
                logger.info(
                    "clip_presets表に %s columnを追加しました", name,
                    extra={"event": "storage.schema_migrated",
                           "ctx": {"table": "clip_presets", "column": name}},
                )
        # shortの作り方一式(clip_presets)。表が空のときだけ初期の型を入れる。全部消した
        # 状態は尊重する(起動のたびに復活すると、消す操作が効かない)。
        seeded = self._seed_clip_presets_locked()
        if seeded:
            logger.info(
                "shortの型(clip_presets)を %s 件で初期化しました", seeded,
                extra={"event": "storage.schema_seeded",
                       "ctx": {"table": "clip_presets", "rows": seeded}},
            )
        # 新規/既存いずれのDBでもindexを保証する(sourceだけで絞る笑い声の一覧用)。
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_search_hits_source"
            " ON search_hits(source, started_at)"
        )
        columns = [row["name"] for row in self._conn.execute("PRAGMA table_info(events)")]
        # internで落とした列を足し直さないための判定。**目標(_INTERN_TARGET_PHASE)ではなく
        # DBが実際にどこまで進んだかで見る。** 目標だけを見ると、CONTRACT済みのDBに対して
        # 目標をEXPANDへ戻した起動が、空の旧列を復活させてしまう ―― 書き込みはid列だけへ
        # 行くので、旧列を読む箇所には黙ってNULLが並ぶ。段階は前へしか進まない。
        interned = self._intern_phase_locked() >= _INTERN_PHASE_CONTRACT
        if "comment" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN comment TEXT")
            logger.info("events表にcomment columnを追加しました")
        if "count" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN count INTEGER")
            logger.info("events表にcount columnを追加しました")
        if "user_avatar" not in columns and not interned:
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
        if "user_gifter_badge" not in columns and not interned:
            self._conn.execute("ALTER TABLE events ADD COLUMN user_gifter_badge TEXT")
            logger.info("events表にuser_gifter_badge columnを追加しました")
        if "user_member_badge" not in columns and not interned:
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
            # 専用の列を持たないfieldのJSON(collector._extra_payload)。TikTokが送って
            # いるのに読んでいなかった値を捨てないための受け皿で、意味が確定した項目は
            # 個別の列へ昇格させる。既存行はNULL=計装前の未計測。
            ("extra", "TEXT"),
            # TikTokがmessage 1件ごとに振る一意のid。接続のたびに届き直す遡り分を
            # 判別する鍵(tictok/collect/dedup.py)。既存行はNULL=計装前の未計測で、
            # 後から埋める手は無い(TikTokからしか得られない値である)。
            ("message_id", "INTEGER"),
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
        # 全体dashboardの「gift名ごと」「贈り主ごと」の集計用。gift行だけの部分indexなので
        # 全eventの2.4%(38,301行)しか持たず、covering なので行本体を読まない。実測(本番の
        # 複製): gift名の上位50が 112ms -> 3ms、贈り主の上位50が 118ms -> 数ms。
        # kind全体へ張る案は+70MBで見送った経緯がある(perf audit round3)ため gift 限定。
        # 列は集計が読むものを全て含めること(gift_count が抜けると表本体へ戻って効かない)。
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_gift_name"
            " ON events(gift_name, diamonds, gift_count) WHERE kind = 'gift'"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_gift_identity"
            " ON events(identity_key, diamonds, gift_count, session_id) WHERE kind = 'gift'"
        )
        # 接続時の遡りの二重記録を止める一意制約(_events_insert_sql の ON CONFLICT が
        # ここを指す)。部分indexにしてあるので、message_idを持たない行 — collector自身が
        # 書くsystem eventと、計装前の既存120万行 — は1件もindexへ載らない。
        #
        # kindを鍵に含めるのは、1つのmessageが複数のkindの行を生む形が将来現れても、
        # 片方を黙って捨てないためである(同じmessageから同じkindの行が2つ出るのは
        # 遡りの二重記録だけで、これが落としたい相手そのものである)。
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_events_message"
            " ON events(session_id, kind, message_id) WHERE message_id IS NOT NULL"
        )
        # 接続時の遡りで二重に記録された既存行の掃除。message_id列より前に入った行が
        # 対象なので、一度きりで済む(以後はdedupと一意制約が入口で止める)。
        if not self._migration_done("purge_connect_backlog_dupes_v1"):
            self._purge_connect_backlog_dupes()
            self._mark_migration("purge_connect_backlog_dupes_v1")
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
            # から始め、文字起こしを持つ録画だけ文字起こし側の実尺で埋める(文字起こしはmp4そのものを読んで
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
        if "memo" not in recording_columns:
            # 録画1本ぶんの覚え書き。既存行は空で始める(推測で何かを書くと、operatorが
            # 書いた文字と区別が付かなくなる)。
            self._conn.execute(
                "ALTER TABLE recordings ADD COLUMN memo TEXT NOT NULL DEFAULT ''"
            )
            logger.info(
                "recordings表にmemo columnを追加しました",
                extra={"event": "storage.schema_migrated",
                       "ctx": {"table": "recordings", "column": "memo"}},
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
        # 見どころが素材の候補も兼ねるようになった分の列。旧cut_listから畳む先でもある。
        for name, decl in (
            # グループ内の並び順(=mp4の書き出し順)。既存行はNULL(末尾扱い)から始める。
            ("position", "INTEGER"),
            # 人が付けた行(manual)か、shortの自動生成が書き戻した行(auto)か。
            ("origin", "TEXT NOT NULL DEFAULT 'manual'"),
            # 最後にmp4として書き出した時刻と出力path。既存行はNULLのまま残す。
            ("exported_at", "REAL"),
            ("exported_path", "TEXT"),
        ):
            if name not in bookmark_columns:
                self._conn.execute(f"ALTER TABLE bookmarks ADD COLUMN {name} {decl}")
                logger.info(
                    "bookmarks表に %s columnを追加しました", name,
                    extra={"event": "storage.schema_migrated",
                           "ctx": {"table": "bookmarks", "column": name}},
                )
        # グループ内の並びを引く索引。列を足した後でなければ張れないのでSCHEMA側には無い。
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_bookmarks_group"
            " ON bookmarks(group_id, position)")
        if self._has_table("cut_list"):
            cut_columns = [
                row["name"] for row in self._conn.execute("PRAGMA table_info(cut_list)")
            ]
            if "group_id" not in cut_columns:
                # グループへの所属とグループ内の並び順(mp4の書き出し順)。既存行は未分類(NULL)。
                self._conn.execute(
                    "ALTER TABLE cut_list ADD COLUMN group_id INTEGER"
                    " REFERENCES clip_groups(id)"
                )
                self._conn.execute("ALTER TABLE cut_list ADD COLUMN position INTEGER")
                logger.info(
                    "cut_list表にgroup_id/position columnを追加しました",
                    extra={"event": "storage.schema_migrated",
                           "ctx": {"table": "cut_list", "column": "group_id,position"}},
                )
        group_columns = [
            row["name"] for row in self._conn.execute("PRAGMA table_info(clip_groups)")
        ]
        if "position" not in group_columns:
            # 棚の表示順。既存行は作成順(今までの並び)をそのまま採番して、移行だけで
            # 並びが変わらないようにする。
            self._conn.execute("ALTER TABLE clip_groups ADD COLUMN position INTEGER")
            rows = self._conn.execute(
                "SELECT id FROM clip_groups ORDER BY created_at, id").fetchall()
            for position, row in enumerate(rows):
                self._conn.execute(
                    "UPDATE clip_groups SET position = ? WHERE id = ?", (position, row["id"]))
            logger.info(
                "clip_groups表にposition columnを追加しました",
                extra={"event": "storage.schema_migrated",
                       "ctx": {"table": "clip_groups", "column": "position"}},
            )
        preset_columns = [
            row["name"] for row in self._conn.execute("PRAGMA table_info(clip_presets)")
        ]
        if "sfx" not in preset_columns:
            # 効果音(作品のみ)。既存の型はoffのまま — 型を作った時点に無かった演出が、
            # 更新しただけで勝手に入ると、次に書き出した作品が別物になる。
            self._conn.execute(
                "ALTER TABLE clip_presets ADD COLUMN sfx INTEGER NOT NULL DEFAULT 0")
            logger.info(
                "clip_presets表にsfx columnを追加しました",
                extra={"event": "storage.schema_migrated",
                       "ctx": {"table": "clip_presets", "column": "sfx"}},
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
            # sweepが自動で積んだ行の目印。既存行は人の投入として0で入る(実際、この列が
            # 無かった頃に積まれたsweep行はpackだけで、人の投入と同じ扱いで走っていた)。
            self._conn.execute(
                "ALTER TABLE media_job_queue ADD COLUMN sweep INTEGER NOT NULL DEFAULT 0"
            )
            logger.info(
                "media_job_queue表にsweep columnを追加しました",
                extra={"event": "storage.schema_migrated",
                       "ctx": {"table": "media_job_queue", "column": "sweep"}},
            )
        self._migrate_media_job_recording_optional()
        self._migrate_highlight_segment_gifts()
        # giftごとの切り出し範囲。既存行はNULLのまま残す —— NULLが「gift演出の窓をそのまま
        # 使う」という意味そのものなので、gift演出の値で埋めると人が一度も触っていないgiftの
        # 窓が固定され、次の再照合でgift演出が動いても付いていかなくなる。
        if self._has_table("highlight_segment_gifts"):
            gift_columns = [
                row["name"]
                for row in self._conn.execute("PRAGMA table_info(highlight_segment_gifts)")
            ]
            # 見せ場(show_start/show_end)は**機械が測った値**で、cut_* とは持ち主が違う。
            # 1つのgift演出に順番待ちで並んだ演出のうち、そのgiftのものが映っている区間で
            # ある。既存行はNULLのまま残す —— NULLは「まだ割っていない」で、gift演出の窓と
            # 同じという意味ではない。次の照合で測り直される。
            for name in ("cut_start", "cut_end", "show_start", "show_end"):
                if gift_columns and name not in gift_columns:
                    self._conn.execute(
                        f"ALTER TABLE highlight_segment_gifts ADD COLUMN {name} REAL")
                    logger.info(
                        "highlight_segment_gifts表に %s columnを追加しました", name,
                        extra={"event": "storage.schema_migrated",
                               "ctx": {"table": "highlight_segment_gifts",
                                       "column": name}},
                    )
            # 人がこのgiftの当たりとして選んだ1本の印。既存行は0(誰も選んでいない)で入り、
            # そのgiftの代表は今までどおり機械の順位が決める。**0が「機械に任せる」の意味
            # そのもの**なので、機械の代表を書き写して埋めてはいけない —— 埋めると、次の
            # 再照合でよりよい当たりが出ても人が選んだ扱いで固定される。
            if gift_columns and "chosen" not in gift_columns:
                self._conn.execute(
                    "ALTER TABLE highlight_segment_gifts"
                    " ADD COLUMN chosen INTEGER NOT NULL DEFAULT 0")
                logger.info(
                    "highlight_segment_gifts表にchosen columnを追加しました",
                    extra={"event": "storage.schema_migrated",
                           "ctx": {"table": "highlight_segment_gifts",
                                   "column": "chosen"}},
                )
            # まとめ投げの個数。**既存行はeventから埋め直す** —— NULLのままだと1個扱いに
            # なり、「30💎を9個(270💎)」が単価270💎のgiftとして下限を通ってしまう。eventは
            # 消えていないので推測は要らず、gift_event_id で引き直せる。
            if gift_columns and "gift_count" not in gift_columns:
                self._conn.execute(
                    "ALTER TABLE highlight_segment_gifts ADD COLUMN gift_count INTEGER")
                filled = self._conn.execute(
                    "UPDATE highlight_segment_gifts SET gift_count ="
                    " (SELECT e.gift_count FROM events e"
                    "   WHERE e.id = highlight_segment_gifts.gift_event_id)"
                ).rowcount
                logger.info(
                    "highlight_segment_gifts表にgift_count columnを追加し、%d行をeventから"
                    "埋めました", filled,
                    extra={"event": "storage.schema_migrated",
                           "ctx": {"table": "highlight_segment_gifts",
                                   "column": "gift_count", "backfilled": filled}},
                )
        # 映像の切り替わり終わる点。既存行はNULL+未測定のまま残す —— gift演出の頭で埋めると
        # 「測った結果ずれが無かった」と区別が付かず、画面が「まだ測っていません」を
        # 言えなくなる。
        if self._has_table("highlight_segments"):
            segment_columns = [
                row["name"]
                for row in self._conn.execute("PRAGMA table_info(highlight_segments)")
            ]
            for name, ddl in (("video_start", "REAL"), ("video_end", "REAL"),
                              ("video_probed", "INTEGER NOT NULL DEFAULT 0")):
                if segment_columns and name not in segment_columns:
                    self._conn.execute(
                        f"ALTER TABLE highlight_segments ADD COLUMN {name} {ddl}")
                    logger.info(
                        "highlight_segments表に %s columnを追加しました", name,
                        extra={"event": "storage.schema_migrated",
                               "ctx": {"table": "highlight_segments", "column": name}},
                    )
                    if name == "video_end":
                        # 両端は1つの印(video_probed)で名乗る。頭だけを測っていた行は、
                        # **尻を測っていない**ので印を落とす —— 落とさないと画面が
                        # 「測ったが決まらなかった」と言い、押しても変わらない操作を
                        # 人に探させる。頭の値そのものは残す(測ったのは事実である)。
                        back = self._conn.execute(
                            "UPDATE highlight_segments SET video_probed = 0"
                            " WHERE video_probed <> 0").rowcount
                        logger.info(
                            "映像の尻が未測定のため、%d行の測定済み印を落としました", back,
                            extra={"event": "storage.schema_migrated",
                                   "ctx": {"table": "highlight_segments",
                                           "column": name, "unprobed": back}},
                        )
        # cut_listの統合はここでは行わない。表を1つ落とす破壊的な操作なので、退避
        # (_backup_before_migrations)を越えた後の区間から呼ぶ(__init__を参照)。
        self._migrate_search_index()
        self._migrate_row_trash()

    def _migrate_row_trash(self) -> None:
        """消えた行の退避(row単位のundo)triggerを揃え、保持日数を過ぎた退避を刈る。lock保持前提。

        triggerの作り直しは ``DROP TRIGGER`` を含むが、落ちるのはtrigger自身だけで行は1つも
        消えない。よって退避(_backup_before_migrations)の前のこの区間で構わない ——
        cut_listの統合(表そのものを落とす)とはそこが違う。

        刈り取りを起動時に置くのは ``_prune_ops_events_locked`` と同じ流儀である。定期の退避
        (``api/startup.py`` の scheduled backup)へぶら下げる形にもできるが、この表は実測でも
        数千行にしかならないので、周期を持たせる理由が無い。

        仕組みと対象表の線引き、費用の実測は :mod:`tictok.store.row_trash` を参照。"""
        row_trash.ensure_triggers(self._conn)
        row_trash.prune(self._conn, get_row_trash_keep_days())

    def prune_row_trash(self) -> int:
        """消えた行の退避を保持日数で刈る。起動後に呼べる口(lockは自分で取る)。

        起動時の刈り取り(:meth:`_migrate_row_trash`)と同じ処理で、こちらは長く動き続ける
        serverから明示的に呼ぶためにある。"""
        with self._lock:
            removed = row_trash.prune(self._conn, get_row_trash_keep_days())
            self._conn.commit()
        return removed

    def row_trash_summary(self) -> dict:
        """消えた行の退避(``row_trash``)の要約。表ごとの件数と最古・最新の時刻だけを返す。

        行の中身は載せない。退避に入るのは設定値・見どころのmemo・字幕の直しで、それを
        状況画面へ素で流す理由が無い —— 中身を見て戻す作業は
        ``scripts/restore_deleted_rows.py`` の担当である。ここが答えるのは
        「いま何行を抱えているか」「一番古いのはいつか」だけ。"""
        conn = self._read_connection()
        counts = [dict(row) for row in row_trash.counts_by_table(conn)]
        stamps = [row for row in counts if row.get("oldest") and row.get("newest")]
        return {
            "keep_days": get_row_trash_keep_days(),
            "tables": list(row_trash.ROW_TRASH_TABLES),
            "counts": counts,
            "rows": sum(int(row.get("rows") or 0) for row in counts),
            "oldest": min((float(row["oldest"]) for row in stamps), default=None),
            "newest": max((float(row["newest"]) for row in stamps), default=None),
        }

    def _migrate_media_job_recording_optional(self) -> None:
        """media_job_queue.recording_id の NOT NULL を外す。lock保持前提。冪等。

        台帳に載るjobは「録画1本に対する処理」ばかりだったので、この列はNOT NULLだった。
        highlightの突き合わせはその前提を満たさない —— **どの録画のどこから来たのかを
        求めるのがjob本体**なので、投入時点で書ける録画idが原理的に存在しない。

        埋め合わせにどれか1本の録画idを入れてはいけない。台帳は「この録画で何が走ったか」
        の記録でもあり(busy判定・削除の抑止・sweepの済み判定がこの列を読む)、無関係な録画を
        名乗らせるとその録画のmp4が削除から守られ、別のjobがその録画で走れなくなる。

        SQLiteは列の制約を後から緩められないので、表を作り直す(公式の12-step)。行はすべて
        写し、indexは張り直す。``PRAGMA foreign_keys`` は書き換えの間だけ落とす —— 付けたまま
        DROPすると、写し終える前に参照が切れたと見なされる。
        """
        info = list(self._conn.execute("PRAGMA table_info(media_job_queue)"))
        if not info:
            return
        recording = next((row for row in info if row["name"] == "recording_id"), None)
        if recording is None or not recording["notnull"]:
            return
        columns = ", ".join(row["name"] for row in info)
        # PRAGMAは transaction の中では効かない。ここまでの ALTER を確定させてから落とす。
        self._conn.commit()
        self._conn.execute("PRAGMA foreign_keys=OFF")
        try:
            self._conn.execute("""
                CREATE TABLE media_job_queue_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL,
                    recording_id INTEGER REFERENCES recordings(id) ON DELETE CASCADE,
                    session_id INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
                    group_id TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 0,
                    queued_at REAL NOT NULL,
                    started_at REAL,
                    finished_at REAL,
                    pct INTEGER NOT NULL DEFAULT 0,
                    stage TEXT NOT NULL DEFAULT '',
                    error TEXT,
                    result_json TEXT NOT NULL DEFAULT '{}',
                    params_json TEXT NOT NULL DEFAULT '{}',
                    stages_json TEXT NOT NULL DEFAULT '[]',
                    not_before REAL,
                    deferred_since REAL,
                    sweep INTEGER NOT NULL DEFAULT 0
                )
            """)
            moved = self._conn.execute(
                f"INSERT INTO media_job_queue_new ({columns})"
                f" SELECT {columns} FROM media_job_queue").rowcount
            with dbmaint.allow_schema_drops():
                self._conn.execute("DROP TABLE media_job_queue")
            self._conn.execute(
                "ALTER TABLE media_job_queue_new RENAME TO media_job_queue")
            # indexはDROPで一緒に消える。SCHEMAのCREATE INDEX IF NOT EXISTSは既に走った
            # 後なので、ここで張り直さないと次の起動まで1本も無い状態が続く。
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_media_job_queue_state"
                " ON media_job_queue(state, priority, queued_at)")
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_media_job_queue_rec"
                " ON media_job_queue(recording_id, state)")
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_media_job_queue_group"
                " ON media_job_queue(group_id, queued_at)")
            self._conn.commit()
        finally:
            self._conn.execute("PRAGMA foreign_keys=ON")
        logger.info(
            "media_job_queue表のrecording_idを任意にしました（%d 行を移しました）", moved,
            extra={"event": "storage.schema_migrated",
                   "ctx": {"table": "media_job_queue", "column": "recording_id",
                           "rows": moved}},
        )

    # gift演出からgiftの表へ写す列。旧 highlight_segments の列名と新 highlight_segment_gifts の
    # 列名が同じものだけを並べる(意味の変わる列は写さない —— 下のdocstringを参照)。
    _HIGHLIGHT_GIFT_MOVED_COLUMNS = (
        "gift_event_id", "gift_id", "gift_name", "diamonds", "gift_image",
        "user_unique_id", "user_nickname", "user_id", "identity_key", "gift_media_time",
    )
    # 旧 highlight_segments からgiftの表へ移す列。移した後のgift演出の表には残さない。
    _HIGHLIGHT_SEGMENT_DROPPED_COLUMNS = frozenset(_HIGHLIGHT_GIFT_MOVED_COLUMNS)

    def _migrate_highlight_segment_gifts(self) -> None:
        """gift演出1行が持っていたgift列を ``highlight_segment_gifts`` へ移す。lock保持前提。冪等。

        **1 segment 1 gift では持てないことが実測で判った。** segmentは最長8.3秒あり、その中に
        演出を持つgiftが複数入る —— 最後のgift演出(t=54–60)の Galaxy 1000💎 と Spartan Helmet
        399💎 がそれで、画面に映っていたのは後者なのに高額な前者が採られた。出力がgifterごと
        1本である以上、これは**別人の名前が付く**誤りになる。

        写すのは「同じ意味のまま置き場が変わる列」だけである。gift演出の属性(idx / votes / ratio /
        corr / confidence / media_start / effect_json / approved)はgift演出の表に残す ——
        gift行へ降ろすと意味が変わる(``approved`` は「このgift演出を確認した」であって
        「このgifterを確認した」ではない)。

        ``edited`` の扱いだけが判断を要する。旧 ``edited`` は「端を動かした」と「giftを
        差し替えた」の**両方**で立っていたので、どちらだったかは行からは戻せない。ここでは
        **giftの側を守る方(manual=1)** へ倒す —— 端だけを動かした行のgiftが1回ぶん機械の
        更新を免れるのは取り返せるが、人が差し替えたgifterが黙って上書きされるのは
        取り返せない。以後は ``edited``(gift演出の端)と ``manual``(giftの差し替え)に分かれるので、
        この曖昧さは1回きりである。

        SQLiteは列を後から落とせないので、gift演出の表は作り直す(公式の12-step)。
        """
        info = list(self._conn.execute("PRAGMA table_info(highlight_segments)"))
        if not info:
            return
        names = [row["name"] for row in info]
        if "gift_event_id" not in names:
            return                                    # 既に移し終えている
        moved = self._conn.execute(
            "INSERT OR IGNORE INTO highlight_segment_gifts"
            " (segment_id, highlight_id, idx, "
            + ", ".join(self._HIGHLIGHT_GIFT_MOVED_COLUMNS) +
            ", inside, is_primary, manual, excluded, dropped)"
            " SELECT s.id, s.highlight_id, 0, s."
            + ", s.".join(self._HIGHLIGHT_GIFT_MOVED_COLUMNS) +
            # 旧い行のgiftはgift演出の主(1件しか持てなかった)。inside はgift演出の範囲内として
            # 扱う —— 旧い形は範囲外のgiftも同じ列へ入れていたが、区別が行に残っていない。
            ", 1, 1, s.edited, s.excluded, s.dropped"
            " FROM highlight_segments s WHERE s.gift_event_id IS NOT NULL").rowcount
        keep = [name for name in names
                if name not in self._HIGHLIGHT_SEGMENT_DROPPED_COLUMNS]
        columns = ", ".join(keep)
        # PRAGMAは transaction の中では効かない。ここまでを確定させてから落とす。
        self._conn.commit()
        self._conn.execute("PRAGMA foreign_keys=OFF")
        try:
            self._conn.execute("""
                CREATE TABLE highlight_segments_new (
                    id INTEGER PRIMARY KEY,
                    highlight_id INTEGER NOT NULL
                        REFERENCES highlight_videos(id) ON DELETE CASCADE,
                    idx INTEGER NOT NULL,
                    start REAL NOT NULL,
                    end REAL NOT NULL,
                    recording_id INTEGER,
                    media_start REAL,
                    votes INTEGER,
                    ratio REAL,
                    corr REAL,
                    confidence TEXT,
                    effect_json TEXT,
                    approved INTEGER NOT NULL DEFAULT 0,
                    edited INTEGER NOT NULL DEFAULT 0,
                    excluded INTEGER NOT NULL DEFAULT 0,
                    dropped INTEGER NOT NULL DEFAULT 0,
                    memo TEXT
                )
            """)
            self._conn.execute(
                f"INSERT INTO highlight_segments_new ({columns})"
                f" SELECT {columns} FROM highlight_segments")
            with dbmaint.allow_schema_drops():
                self._conn.execute("DROP TABLE highlight_segments")
            self._conn.execute(
                "ALTER TABLE highlight_segments_new RENAME TO highlight_segments")
            # indexはDROPで一緒に消える。SCHEMAのCREATE INDEX IF NOT EXISTSは既に走った
            # 後なので、ここで張り直さないと次の起動まで1本も無い状態が続く。
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_highlight_segments_hl"
                " ON highlight_segments(highlight_id, idx)")
            self._conn.commit()
        finally:
            self._conn.execute("PRAGMA foreign_keys=ON")
        logger.info(
            "highlightのgift演出からgiftを別表へ移しました（%d 件）", moved,
            extra={"event": "storage.schema_migrated",
                   "ctx": {"table": "highlight_segments",
                           "moved_to": "highlight_segment_gifts", "rows": moved}},
        )

    def _has_table(self, name: str) -> bool:
        """その名前の表が在るか。lock保持前提。廃止した表に触るmigrationを、既に畳んだDBで
        素通りさせるために使う(PRAGMA table_infoは表が無くても空を返すだけで、区別が付かない)。"""
        row = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
        ).fetchone()
        return row is not None

    def merge_cut_list_into_bookmarks(self) -> None:
        """切り出し(cut_list)を見どころ(bookmarks)へ畳み、cut_listを落とす。lock保持前提。

        **退避を越えた後の区間から呼ぶこと。** 表そのものを落とすので、_migrate の中
        (退避より前)で走らせると、退避なしで取り返しの付かない操作をすることになる。

        2表に割れていた理由は「グループごとにIN/OUTの詰め方が変わるので所属を共有できない」
        だったが、実データでは切り出し21件のうち20件が元の見どころと範囲・グループ・
        ラベルまで一致し、詰め直しは一度も起きていなかった。写した先で別の値になるという
        前提が成立していないので、表を1つにする。

        畳み方は2通りで、**行を失わない方**へ倒す:

        * 元の見どころが在り、範囲もグループも一致する → その見どころへ書き出し順・
          書き出し記録を移し、切り出しの行は捨てる(同じ場面が2行にならない)。
        * それ以外(元が消えている・詰め直して範囲がずれた・1つの見どころから複数の切り出しを
          作った・再生画面から直接足した) → 切り出しを**新しい見どころ**として作る。
          ここで「元の見どころへ寄せる」と、詰めた範囲か元の範囲かのどちらかが黙って消える。

        新しく作る行の ``origin`` は 'manual' で入れる。shortの自動生成が書き戻した行だけを
        'auto' にしたいところだが、その行はlabelにAIの題名が入ることがあり、人が足した行と
        区別する手掛かりがDBに無い。推測で分けると、人が付けた見どころが既定で隠れる側へ
        落ちる。区別は列を持った後に書かれた行から始める。
        """
        from tictok.store._common import CUT_SAME_RANGE_TOLERANCE as tol

        cuts = self._conn.execute(
            "SELECT * FROM cut_list ORDER BY (position IS NULL), position, start, id"
        ).fetchall()
        folded = 0
        created = 0
        # 1つの見どころから複数の切り出しを作っていた場合、畳めるのは最初の1件だけである
        # (2件目を同じ行へ書くと、先に畳んだ書き出し順と記録を黙って上書きする)。
        taken: set = set()
        for cut in cuts:
            target = None
            if cut["bookmark_id"] is not None and cut["bookmark_id"] not in taken:
                row = self._conn.execute(
                    "SELECT * FROM bookmarks WHERE id = ?", (cut["bookmark_id"],)
                ).fetchone()
                if (row is not None and row["end"] is not None
                        and abs(row["start"] - cut["start"]) <= tol
                        and abs(row["end"] - cut["end"]) <= tol
                        and row["group_id"] == cut["group_id"]):
                    target = row
                    taken.add(row["id"])
            if target is not None:
                # ラベルは昇格の時点でメモと同じ物になっているが、メモが空のまま切り出し側に
                # だけ言葉が付いている行が在り得る。空のメモを優先すると書き出しfile名が消える。
                memo = target["memo"] or cut["label"] or ""
                self._conn.execute(
                    "UPDATE bookmarks SET memo = ?, position = ?, exported_at = ?,"
                    " exported_path = ? WHERE id = ?",
                    (memo, cut["position"], cut["exported_at"], cut["exported_path"],
                     target["id"]))
                folded += 1
                continue
            self._conn.execute(
                "INSERT INTO bookmarks (recording_id, unique_id, start, end, memo,"
                " source_hit_id, live_wall, pts_mapped, group_id, position, origin,"
                " exported_at, exported_path, created_at)"
                " VALUES (?, ?, ?, ?, ?, NULL, NULL, 1, ?, ?, 'manual', ?, ?, ?)",
                (cut["recording_id"], cut["unique_id"], cut["start"], cut["end"],
                 cut["label"] or "", cut["group_id"], cut["position"],
                 cut["exported_at"], cut["exported_path"], cut["created_at"]))
            created += 1
        with dbmaint.allow_schema_drops():
            self._conn.execute("DROP TABLE cut_list")
        logger.info(
            "切り出し %d 件を見どころへ統合しました（既存へ畳んだ %d 件・新しい行 %d 件）",
            len(cuts), folded, created,
            extra={"event": "storage.schema_migrated",
                   "ctx": {"table": "bookmarks", "merged_from": "cut_list",
                           "cuts": len(cuts), "folded": folded, "created": created}},
        )

    def _backfill_cut_bookmark_ids(self) -> None:
        """bookmark_id列を足した直後に、既存の切り出しへ元の見どころを結び直す。lock保持前提。

        列を足した時点では対応が範囲の一致でしか辿れないので、その一致が残っているうちに
        1度だけ固定する(以後IN/OUTを詰めても対応は切れない)。同じ範囲の見どころが複数
        並ぶ行は結ばない ―― どちらが元かはDBに無く、選べば捏造になる。"""
        from tictok.store._common import CUT_SAME_RANGE_TOLERANCE as tol

        pairs = self._conn.execute(
            "SELECT c.id AS cut_id, MIN(b.id) AS bookmark_id, COUNT(*) AS n"
            " FROM cut_list c JOIN bookmarks b ON b.recording_id = c.recording_id"
            " WHERE b.end IS NOT NULL"
            " AND ABS(b.start - c.start) <= ? AND ABS(b.end - c.end) <= ?"
            " GROUP BY c.id HAVING n = 1",
            (tol, tol),
        ).fetchall()
        if not pairs:
            return
        self._conn.executemany(
            "UPDATE cut_list SET bookmark_id = ? WHERE id = ?",
            [(row["bookmark_id"], row["cut_id"]) for row in pairs],
        )
        logger.info(
            "切り出し %d 件へ元の見どころを結び直しました", len(pairs),
            extra={"event": "storage.schema_migrated",
                   "ctx": {"table": "cut_list", "column": "bookmark_id",
                           "linked": len(pairs)}},
        )

    def _sync_cut_labels_from_memo(self) -> None:
        """既存の切り出しのラベルを、元になった見どころのメモへ揃える。lock保持前提。

        以後の更新は :meth:`update_bookmark_memo` が同時に行う。ここは、その仕組みが無かった
        間にメモだけが動いた分の遅れを取り戻す1度きりの反映である。

        メモが空の見どころは写さない。空で上書きすると、手で付けたラベル(=書き出しfile名)を
        消すことになり、『見どころを反映する』ではなく『消す』migrationになる。空のメモへ
        揃えたい行は、画面でメモを直せばその時に揃う。"""
        synced = self._conn.execute(
            "UPDATE cut_list SET label = ("
            "  SELECT b.memo FROM bookmarks b WHERE b.id = cut_list.bookmark_id)"
            " WHERE bookmark_id IS NOT NULL AND EXISTS ("
            "  SELECT 1 FROM bookmarks b WHERE b.id = cut_list.bookmark_id"
            "   AND b.memo <> '' AND b.memo <> cut_list.label)"
        ).rowcount
        if not synced:
            return
        logger.info(
            "切り出し %d 件のラベルを元の見どころのメモへ揃えました", synced,
            extra={"event": "storage.schema_migrated",
                   "ctx": {"table": "cut_list", "column": "label", "synced": synced}},
        )

    def _migrate_search_index(self) -> None:
        """検索の索引を畳んだ本文(body_norm)へ載せ替える。lock保持前提。

        「ウザ」で「うざ」が出ない取りこぼしを無くすため、索引もLIKEも
        tictok.search.normalize.fold を通した本文で照合する。既存行はここで畳み直し、
        FTSは索引語そのものが変わるので作り直す(external contentなので、content表さえ
        埋まっていればrebuildで再構築できる)。

        畳むruleを変えたときも同じ道を通す。索引だけが古いruleのまま残ると、queryは
        新しいruleで畳まれるので、その語だけ当たらないという形で静かに壊れる。

        索引へ載せる本文は返信の宛先(``@表示名``)を外した形(``index_fold``)。名前の切れ目は
        既知の表示名でしか決まらないので、ここで一度だけ台帳を読む。"""
        from tictok.search.normalize import FOLD_VERSION, index_fold
        from tictok.store._common import SEARCH_FTS_DDL

        columns = [row["name"] for row in self._conn.execute("PRAGMA table_info(search_hits)")]
        version = str(FOLD_VERSION)
        if "body_norm" in columns:
            if self._get_maintenance_locked(_SEARCH_FOLD_KEY) == version:
                return
        else:
            self._conn.execute(
                "ALTER TABLE search_hits ADD COLUMN body_norm TEXT NOT NULL DEFAULT ''")
        started = time.time()
        # self._lock 保持中なので、表示名の台帳も書き込み接続から読む。
        names = self._load_mention_names(self._conn)
        self._conn.create_function(
            "tictok_index_fold", 1, lambda body: index_fold(body, names), deterministic=True)
        self._conn.execute("UPDATE search_hits SET body_norm = tictok_index_fold(body)")
        rows = self._conn.execute("SELECT COUNT(*) AS n FROM search_hits").fetchone()["n"]
        # 旧FTSはbody列を索引している。索引する列の入れ替えはALTERできないので作り直す。
        with dbmaint.allow_schema_drops():
            self._conn.execute("DROP TABLE IF EXISTS search_fts")
        self._conn.executescript(SEARCH_FTS_DDL)
        self._conn.execute("INSERT INTO search_fts(search_fts) VALUES('rebuild')")
        self._set_maintenance_locked(_SEARCH_FOLD_KEY, version)
        elapsed = round(time.time() - started, 1)
        logger.info(
            "検索の索引を表記ゆれを畳んだ本文へ作り直しました"
            "（版%s / %d 行 / %.1f 秒 / 既知の表示名 %d 件）",
            version, rows, elapsed, len(names),
            extra={"event": "storage.schema_migrated",
                   "ctx": {"table": "search_hits", "column": "body_norm",
                           "fold_version": FOLD_VERSION, "rows": rows,
                           "mention_names": len(names),
                           "elapsed_seconds": elapsed}},
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

    # ----- eventsの重複文字列のintern ---------------------------------------------------
    # 段階を2つに分けてある理由は _common.py の _INTERN_PHASE_* を参照。要点は「旧列を残した
    # ままでは1 byteも減らないので途中で止まる形にできない」ことと、「落とした瞬間に、まだ
    # 書き換えていない読み出し箇所のavatarとbadgeが消える」ことの両立である。

    # 既存行のid埋めに使う一時的なUNIQUE index。valueで引くのはここだけで、常設にすると
    # 実測81.5MB(292k件 x 274 byte)を払い続けることになる ―― 回収する294MBの28%である。
    _INTERN_TEMP_INDEX = "tmp_event_strings_value"

    def _intern_targets(self) -> tuple:
        """(表名, 旧列名, id列名) の組。eventsとcontributor_samplesが同じ event_strings を
        共有する。対象を増やすときは _common.py の _INTERNED_* に足すだけでよい。"""
        targets = [("events", old, new) for old, new in _INTERNED_EVENT_COLUMNS]
        targets += [("contributor_samples", old, new)
                    for old, new in _INTERNED_CONTRIBUTOR_COLUMNS]
        return tuple(targets)

    def _intern_phase_locked(self) -> int:
        raw = self._get_maintenance_locked(_INTERN_PHASE_KEY)
        try:
            return int(raw)
        except (TypeError, ValueError):
            return _INTERN_PHASE_NONE

    def _apply_intern_phase(self, phase: int) -> None:
        """段階を storage の書き込み経路へ反映する。以後のINSERTはこのSQLで書かれる。"""
        self._intern_phase = phase
        self._events_insert_sql = _events_insert_sql(phase)

    def migrate_event_interning(self) -> dict:
        """eventsの重複文字列を event_strings のidへ畳む。__init__の退避後の区間から呼ぶ。

        **冪等で再開可能である。** 再開条件は「id列がNULLの行」という述語そのもので、
        chunkごとにcommitするので途中で落ちても続きから進む。旧列は §CONTRACT の全行
        突き合わせを通るまで残るため、どの時点で止まっても真実は旧列側に在る。

        破壊的(旧列を落とす)なので、呼び出しは必ず _backup_before_migrations の後に置く。
        """
        started = time.monotonic()
        phase = self._intern_phase_locked()
        target = _INTERN_TARGET_PHASE
        if phase >= target:
            self._apply_intern_phase(phase)
            return {"phase": phase, "skipped": "already_at_target"}
        summary: dict = {"phase_before": phase, "filled": {}, "interned_rows": 0}
        if phase < _INTERN_PHASE_EXPAND:
            summary.update(self._intern_expand_locked())
            phase = _INTERN_PHASE_EXPAND
            self._set_maintenance_locked(_INTERN_PHASE_KEY, str(phase))
            self._conn.commit()
        self._apply_intern_phase(phase)
        if target >= _INTERN_PHASE_CONTRACT and phase < _INTERN_PHASE_CONTRACT:
            contracted = self._intern_contract_locked()
            summary.update(contracted)
            if contracted.get("dropped"):
                phase = _INTERN_PHASE_CONTRACT
                self._set_maintenance_locked(_INTERN_PHASE_KEY, str(phase))
                self._conn.commit()
                self._apply_intern_phase(phase)
        summary["phase"] = phase
        summary["duration_ms"] = round((time.monotonic() - started) * 1000.0, 1)
        logger.info(
            "eventsの重複文字列のinternを進めました（段階 %d -> %d, %.1fs）",
            summary["phase_before"], phase, summary["duration_ms"] / 1000.0,
            extra={"event": "storage.intern_migrated", "ctx": summary},
        )
        return summary

    def _intern_expand_locked(self) -> dict:
        """id列を足し、intern表を作り、既存行のidを埋める。**旧列は残す。**

        旧列を残したこの段階を経由するのは、読み出し側(events のavatar/badgeを読む7箇所)の
        書き換えが1回では終わらないためである。両方の列が同じ真実を持っている間は、書き換え
        済みの箇所と未着手の箇所が同じ答えを返す。
        """
        for table, old, new in self._intern_targets():
            columns = [r["name"] for r in self._conn.execute(f"PRAGMA table_info({table})")]
            if old not in columns:
                continue  # 既に落とし済み(CONTRACT後にこの起動が来た)
            if new not in columns:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {new} INTEGER")
                logger.info(
                    "%s表に %s columnを追加しました", table, new,
                    extra={"event": "storage.schema_migrated",
                           "ctx": {"table": table, "column": new}},
                )
        self._conn.commit()
        # 前回が一時indexを張ったまま落ちていることがある。常設にしない約束なので必ず消す。
        with dbmaint.allow_schema_drops():
            self._conn.execute(f"DROP INDEX IF EXISTS {self._INTERN_TEMP_INDEX}")
        self._conn.execute(
            f"CREATE UNIQUE INDEX {self._INTERN_TEMP_INDEX} ON event_strings(value)")
        try:
            added = self._intern_collect_values_locked()
            filled = self._intern_fill_ids_locked()
        finally:
            # 一時indexは必ず落とす。例外で抜けても常設化させない。
            with dbmaint.allow_schema_drops():
                self._conn.execute(f"DROP INDEX IF EXISTS {self._INTERN_TEMP_INDEX}")
            self._conn.commit()
        return {"interned_rows": added, "filled": filled}

    def _intern_collect_values_locked(self) -> int:
        """対象列のdistinct値を event_strings へ入れる。一時UNIQUE index保持前提。

        distinct値を丸ごとmemoryへ載せない: user_avatarだけで実測292,114件 x 274 byte =
        80MBある。cursorを流しながら少しずつ入れる。既に在る値は ``INSERT OR IGNORE`` が
        弾くので、途中で落ちた前回の続きからでも同じ結果になる。
        """
        next_id = self._conn.execute(
            "SELECT COALESCE(MAX(id), 0) + 1 FROM event_strings").fetchone()[0]
        added = 0
        for table, old, _new in self._intern_targets():
            columns = [r["name"] for r in self._conn.execute(f"PRAGMA table_info({table})")]
            if old not in columns:
                continue
            cursor = self._conn.execute(
                f"SELECT DISTINCT {old} AS v FROM {table} WHERE {old} IS NOT NULL")
            while True:
                chunk = cursor.fetchmany(10000)
                if not chunk:
                    break
                rows = []
                for row in chunk:
                    rows.append((next_id, _string_hash(row["v"]), row["v"]))
                    next_id += 1
                cur = self._conn.executemany(
                    "INSERT OR IGNORE INTO event_strings (id, hash, value) VALUES (?, ?, ?)",
                    rows)
                added += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
                self._conn.commit()
        return added

    def _intern_fill_ids_locked(self) -> dict:
        """既存行のid列を埋める。一時UNIQUE index保持前提。

        chunkごとにcommitする。``{new} IS NULL`` が再開条件そのものなので、途中で落ちても
        次の起動が残りだけを進める(やり直しではない)。
        """
        filled: dict = {}
        for table, old, new in self._intern_targets():
            columns = [r["name"] for r in self._conn.execute(f"PRAGMA table_info({table})")]
            if old not in columns:
                continue
            done = 0
            while True:
                cur = self._conn.execute(
                    f"UPDATE {table} SET {new} ="
                    f" (SELECT s.id FROM event_strings s WHERE s.value = {table}.{old})"
                    f" WHERE rowid IN (SELECT rowid FROM {table}"
                    f"  WHERE {old} IS NOT NULL AND {new} IS NULL LIMIT ?)",
                    (_INTERN_MIGRATE_CHUNK_ROWS,),
                )
                self._conn.commit()
                if not cur.rowcount:
                    break
                done += cur.rowcount
            if done:
                filled[f"{table}.{new}"] = done
        return filled

    def _strip_avatar_signatures_locked(self) -> dict:
        """既存のavatar値から署名queryを落とし、idを付け替える。

        **self._lock保持前提**(_locked)。呼び出し元の __init__ が migration区間ごと lock を
        持っているので、ここで取り直すと自分自身で待って進まなくなる(この lock は再帰的では
        ない)。同じ区間に居る _intern_expand_locked / _intern_contract_locked と同じ約束。

        **これはinternとは別の判断である。** internは同じ文字列を1度だけ持つ変更で記録の
        中身を変えないが、こちらは保存する値そのものを変える。落としてよい根拠と、落として
        表示が壊れない理由は _common.py の _INTERN_STRIPPED_COLUMNS に書いてある。

        **行を書き換えず、idを付け替える。** event_strings は avatar と badge が相乗りする
        共有表で、実データに両方から参照されている行が1件ある。UPDATE event_strings SET
        value=... で潰すと、badge側が別の文字列を指し始める。

        付け替えた結果どこからも参照されなくなった行だけを消す。参照の判定は4つのid列
        (events 3列 + contributor_samples 1列)すべてに対して行う。

        冪等。2度目は付け替える行が無く、消す行も無い。
        """
        version = str(_INTERN_STRIP_VERSION)
        if self._get_maintenance_locked(_INTERN_STRIP_KEY) == version:
            return {"stripped": False, "skipped": "already_done"}
        started = time.monotonic()
        targets = [(t, new) for t, old, new in self._intern_targets()
                   if old in _INTERN_STRIPPED_COLUMNS]
        cols = [r["name"] for r in self._conn.execute("PRAGMA table_info(events)")]
        if "user_avatar_id" not in cols:
            # internがまだEXPANDへ到達していない起動。次の起動で揃う。
            return {"stripped": False, "skipped": "intern_not_ready"}
        remap: dict = {}
        for table, idcol in targets:
            rows = self._conn.execute(
                f"SELECT DISTINCT s.id AS id, s.value AS value FROM event_strings s"
                f" WHERE s.id IN (SELECT {idcol} FROM {table}"
                f"                WHERE {idcol} IS NOT NULL)").fetchall()
            for row in rows:
                head, sep, _ = row["value"].partition("?")
                if not sep:
                    continue
                remap[row["id"]] = head
        if not remap:
            self._set_maintenance_locked(_INTERN_STRIP_KEY, version)
            self._conn.commit()
            return {"stripped": True, "remapped_values": 0, "rows": 0, "deleted": 0}
        # 落とした後の値を intern する(既存行が在ればそれを使う)。
        wanted = sorted(set(remap.values()))
        self._intern_values_locked(set(wanted))
        new_ids = {value: self._string_cache[value] for value in wanted}
        pairs = [(old_id, new_ids[value]) for old_id, value in remap.items()
                 if new_ids[value] != old_id]
        # 対応表をtempへ置いて、表ごとに**1回のUPDATE**で付け替える。
        # 1値ずつ `WHERE user_avatar_id = ?` を投げてはいけない: この列にindexは無く、
        # 29万値それぞれが125万行の全走査になる(実測10分でも終わらなかった)。
        self._conn.execute("DROP TABLE IF EXISTS temp._avatar_strip_map")
        self._conn.execute(
            "CREATE TEMP TABLE _avatar_strip_map"
            " (old_id INTEGER PRIMARY KEY, new_id INTEGER NOT NULL)")
        self._conn.executemany(
            "INSERT INTO temp._avatar_strip_map (old_id, new_id) VALUES (?, ?)", pairs)
        moved = 0
        for table, idcol in targets:
            cur = self._conn.execute(
                f"UPDATE {table} SET {idcol} ="
                f" (SELECT m.new_id FROM temp._avatar_strip_map m WHERE m.old_id = {idcol})"
                f" WHERE {idcol} IN (SELECT old_id FROM temp._avatar_strip_map)")
            moved += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
            self._conn.commit()
        self._conn.execute("DROP TABLE temp._avatar_strip_map")
        # どこからも参照されなくなった行を消す。共有表なので4列すべてを見る。
        refs = " UNION ".join(
            f"SELECT {new} AS id FROM {table} WHERE {new} IS NOT NULL"
            for table, _, new in self._intern_targets())
        cur = self._conn.execute(
            f"DELETE FROM event_strings WHERE id NOT IN ({refs})")
        deleted = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        self._set_maintenance_locked(_INTERN_STRIP_KEY, version)
        self._conn.commit()
        result = {"stripped": True, "remapped_values": len(pairs), "rows": moved,
                  "deleted": deleted,
                  "duration_ms": round((time.monotonic() - started) * 1000.0, 1)}
        logger.warning(
            "avatarの署名を落として値をまとめました（%d値 -> 付け替え %d行 / 不要になった"
            "%d行を削除, %.1fs）。**VACUUMするまでfileは縮みません。**",
            len(pairs), moved, deleted, result["duration_ms"] / 1000.0,
            extra={"event": "storage.avatar_signatures_stripped", "ctx": result},
        )
        return result

    def _intern_contract_locked(self) -> dict:
        """全行の突き合わせを関門にして旧列を落とす。**唯一の安全弁なので外さないこと。**

        突き合わせは ``IS NOT`` で行う(``!=`` はNULL同士でNULLを返して素通りする)。NULLと
        空文字の区別もこれで保たれる: NULLの行はid列もNULLでJOIN先もNULL、空文字は
        event_stringsに1行を持つので、読み出し側の ``NULLIF(MAX(...), '')`` が旧と同じに働く。
        """
        mismatched: dict = {}
        for table, old, new in self._intern_targets():
            columns = [r["name"] for r in self._conn.execute(f"PRAGMA table_info({table})")]
            if old not in columns:
                continue
            bad = self._conn.execute(
                f"SELECT COUNT(*) FROM {table} t"
                f" LEFT JOIN event_strings s ON s.id = t.{new}"
                f" WHERE t.{old} IS NOT s.value"
            ).fetchone()[0]
            if bad:
                mismatched[f"{table}.{old}"] = bad
        if mismatched:
            # 落とせば元の値はどこにも残らない。1行でも食い違うなら進まない。
            logger.error(
                "internの突き合わせが一致しないため旧列を落としません: %s", mismatched,
                extra={"event": "storage.intern_verify_failed",
                       "ctx": {"mismatched": mismatched}},
            )
            return {"dropped": False, "mismatched": mismatched}
        dropped = []
        for table, old, _new in self._intern_targets():
            columns = [r["name"] for r in self._conn.execute(f"PRAGMA table_info({table})")]
            if old not in columns:
                continue
            self._conn.execute(f"ALTER TABLE {table} DROP COLUMN {old}")
            dropped.append(f"{table}.{old}")
        self._conn.commit()
        # **VACUUMするまでfileは縮まない。それどころか一時的に大きくなる。**
        # DROP COLUMNは行をその場で書き直すので、空いたのはpage内の隙間(断片化)であって
        # 空きpageではない。実測(1,256,138行): 1767.6MB -> 落とした直後2042.4MB(freelistは
        # 100.9MBしか載らない) -> VACUUM後1262.6MB(-505.0MB / -28.6%, VACUUM自体は16.8秒)。
        # 新しい行は小さくなるので**伸びる速さはここで落ちる**が、大きさが戻るのはVACUUMの後。
        # 自動では走らせない(vacuum()のdocstringの通り、全書き込みを止めるため)。
        logger.warning(
            "internの突き合わせが全行一致したので旧列を落としました: %s"
            "（DB fileはVACUUMするまで縮みません。実測では一時的に約275MB大きくなり、"
            "VACUUM後に約505MB小さくなります）", dropped,
            extra={"event": "storage.intern_contracted",
                   "ctx": {"dropped": dropped, "vacuum_required": True}},
        )
        return {"dropped": True, "dropped_columns": dropped, "vacuum_required": True}

    # 遡りの二重記録を判定する列。message_idを持たない既存行を畳む唯一の手であり、
    # **これはmessage_idの代わりではない。** 一致を要求するのは create_time —— TikTokが
    # そのmessageに打ったms精度の時刻 —— を含む組で、同じ人が同じ文を同じmilli秒に
    # 二度送ることは無い。text単独や「近い時刻」で畳むと、同じ人が同じ短文("おは"等)を
    # 続けて送った本物のCommentが消える。
    _BACKLOG_DUPE_KEY = ("session_id", "kind", "user_id", "text", "create_time")

    def _purge_connect_backlog_dupes(self) -> None:
        """接続時の遡りで二重に記録された既存行を、session内で最古の1件へ畳む。lock保持前提。

        TikTokは接続のたびにRoomの直近messageを送り直す。message_id列が入るまでは
        受け側にそれを判別する鍵が無く、配信の開始時と切断からの復帰時に同じ行が積まれて
        いた(実測: comment 202,654件中3,201件、1配信で同一commentが最大20行)。

        session内に限るのは、どの行を残すかが自明だからである。session跨ぎの重複(実測
        369件)は「どちらのsessionの出来事だったか」の判断を伴う —— 消せばもう一方の
        sessionの集計が動く —— ので、ここでは触れない。

        削った後のsessionは stats_json / buckets / 解析cacheが行数と食い違うため、
        journalからの復元と同じ順で作り直す。解析cacheだけは行を消すに留める:
        再計算はread専用接続を使う_ensure_analytics_cacheの仕事で、migrationの途中で
        commitを挟まずに済む。
        """
        keys = self._BACKLOG_DUPE_KEY
        # NULL同士を等しいと見るために比較は IS を使う(GROUP BY の畳み方と揃える)。
        join_on = " AND ".join(f"e.{col} IS d.{col}" for col in keys)
        dupes = (
            "SELECT e.id AS id, e.session_id AS session_id FROM events e"
            f" JOIN (SELECT {', '.join(keys)}, MIN(id) AS keep_id FROM events"
            "        WHERE create_time IS NOT NULL AND kind <> 'system'"
            f"       GROUP BY {', '.join(keys)} HAVING COUNT(*) > 1) d"
            f"  ON {join_on}"
            " WHERE e.id <> d.keep_id"
        )
        rows = self._conn.execute(dupes).fetchall()
        if not rows:
            return
        ids = [row["id"] for row in rows]
        sessions = sorted({row["session_id"] for row in rows})
        started = time.time()
        self._conn.executemany("DELETE FROM events WHERE id = ?", [(i,) for i in ids])
        self._conn.executemany(
            "DELETE FROM analytics_session_cache WHERE session_id = ?",
            [(sid,) for sid in sessions],
        )
        for sid in sessions:
            row = self._conn.execute(
                "SELECT bucket_seconds FROM sessions WHERE id = ?", (sid,)
            ).fetchone()
            if row is None:
                continue
            self._recompute_session_stats_locked(sid, provenance="deduplicated")
            self._rebuild_buckets_locked(sid, row["bucket_seconds"])
        logger.info(
            "接続時の遡りで二重に記録されていた event %d 行を削除し、session %d 件の"
            "集計・timeline・解析cacheを作り直しました（%.1f秒）",
            len(ids), len(sessions), time.time() - started,
            extra={"event": "storage.backlog_dupes_purged",
                   "ctx": {"rows": len(ids), "sessions": len(sessions)}},
        )

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
        # avatar/badgeは event_strings へinternする列だが、**この method は _migrate から
        # (= intern migrationより前に)呼ばれる**。そのときはまだ旧列しか埋まっていないので、
        # 今この瞬間に値を持っている側から読む。段階で分岐するのではなく実際の列で判断する
        # のは、_migrate の途中とintern後の両方から辿り着くためである。
        # 集約が無い(1行ずつ時系列にupsertする)ので、MAXの読み替えは要らない。
        columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(events)")}
        selects, joins = [], []
        for alias, (old, new) in zip(
            ("av", "gbv", "mbv"),
            (("user_avatar", "user_avatar_id"),
             ("user_gifter_badge", "user_gifter_badge_id"),
             ("user_member_badge", "user_member_badge_id")),
        ):
            label = {"user_avatar": "avatar", "user_gifter_badge": "gifter_badge",
                     "user_member_badge": "member_badge"}[old]
            if old in columns:
                selects.append(f"e.{old} AS {label}")
            else:
                selects.append(f"{alias}.value AS {label}")
                joins.append(f" LEFT JOIN event_strings {alias} ON {alias}.id = e.{new}")
        rows = self._conn.execute(
            "SELECT e.identity_key, e.user_id, e.user_unique_id AS unique_id,"
            " e.user_nickname AS nickname, e.user_fans_level AS fans_level,"
            " e.user_gifter_level AS gifter_level, e.time, "
            + ", ".join(selects)
            + " FROM events e" + "".join(joins)
            + " WHERE e.identity_key IS NOT NULL AND e.identity_key != ''"
            " ORDER BY e.time"
        ).fetchall()
        count = 0
        for row in rows:
            # events.identity_key(逆引き補完済み)を尊重。recomputeするとhandle止まりへ戻る。
            if self._upsert_user_locked(dict(row), row["time"] or 0, key=row["identity_key"]):
                count += 1
        logger.info("event %d 件からusers表を再構成しました", count)
