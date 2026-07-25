import gzip
import itertools
import json
import logging
import os
import shutil
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

from tictok import analytics, battle_migration, glove_migration
from tictok.core import dbmaint
from tictok.core.config import (
    get_db_backup_before_migration,
    get_journal_dir,
    get_journal_enabled,
    get_journal_retention_days,
    get_log_dir,
    get_log_progress_interval_seconds,
    get_ops_events_detail_max_chars,
    get_ops_events_query_limit,
    get_ops_events_retention_days,
    get_storage_backlog_warn_rows,
)
from tictok.core import spike
from tictok.core.battle import (
    BATTLE_TOPOLOGY_VERSION,
    GLOVE_EVENT_VERSION,
    annotate_result,
    gift_window_end,
    gift_window_fallback_duration,
)
from tictok.core.logctx import current_context
from tictok.core.logging_setup import progress_interval_seconds
from tictok.core.progress import IntervalGate

logger = logging.getLogger("tictok.storage")

# events / viewer_samples のINSERT。batch(executemany)と1行隔離(execute)で同一SQLを使うため
# 定数化する。列順はbuffer済みtupleおよびjournal記録のrowと厳密に一致させること。
_EVENTS_COLUMNS = (
    "session_id", "time", "create_time", "kind", "user_id", "user_unique_id",
    "user_nickname", "identity_key", "user_avatar", "text", "comment", "gift_name",
    "gift_count", "diamonds", "count", "gift_image", "gift_id", "user_fans_level",
    "user_gifter_level", "user_gifter_badge", "user_member_badge", "emotes",
    # 流入元/follow関係のpoint-in-time snapshot(F6)。NULLは「計装前で未計測」を意味し、
    # 「届いたが空だった」は enter_source='unknown' / follow_status='unknown' で表す。
    # 両者を同じNULLへ潰すと被覆率が出せなくなる。
    "enter_source", "enter_type", "enter_reason", "follow_status", "follower_count",
    "is_subscriber", "is_moderator", "is_gift_giver",
    # Share の行き先 / Comment の言語判定。上と同じ規約で、NULL=計装前の未計測、
    # 'unknown'=届いたが空。share_targetは意味が未確定なので生値をそのまま入れる。
    "share_type", "share_target", "content_language", "comment_tag",
)
_EVENTS_INSERT_SQL = (
    f"INSERT INTO events ({', '.join(_EVENTS_COLUMNS)})"
    f" VALUES ({', '.join('?' * len(_EVENTS_COLUMNS))})"
)
_VIEWERS_INSERT_SQL = (
    "INSERT INTO viewer_samples (session_id, time, create_time, viewers, total_viewers, anonymous)"
    " VALUES (?, ?, ?, ?, ?, ?)"
)

# 書き込みは単一writerスレッドでバッチ化する。add_event/add_viewer_sampleはキュー投入で
# 即returnし、writerがN件または一定間隔でexecutemany+1commitへまとめる。
_WRITE_BATCH_SIZE = 50
_WRITE_FLUSH_INTERVAL_SECONDS = 0.2
# 同一identity_keyの属性が変わらない限り、この秒数はusers表のupsertを間引く(live取り込みのみ)。
_USER_UPSERT_TTL_SECONDS = 60.0
# 1戦のBattle貢献者を「主力貢献者」とみなすcoin(diamond)下限。この閾値以上を投げた
# 貢献者を1戦ごとに数え、過去全Battleの平均人数を出す。
_BATTLE_KEY_CONTRIB_DIAMONDS = 100

# ops_events.severity の値域。DB側のCHECK制約は付けない: ops_eventsは障害時に記録を残す
# ための表で、制約違反で書き込みが失敗して本流を巻き込むのが最悪の失敗様式だからである。
# 値域はここで担保し、record_ops_eventが呼び出し時点で検証する。
# 「このmigration版のmigrationは完走済み」を示すmarker(db_maintenance表)。値はmigration版の
# 組で、片方でも上がれば不一致になり、次の起動が退避してからmigrationを走らせる。
# 「退避済み」ではなく「完走済み」であることに意味がある: 書き換える行が1つも無かった起動でも
# markerは進み、退避fileは作られない(守る対象が無いため)。
_MIGRATION_BACKUP_KEY = "premigration_backup_versions"


def _migration_versions() -> str:
    return f"glove={GLOVE_EVENT_VERSION},topo={BATTLE_TOPOLOGY_VERSION}"


OPS_INFO = "info"
OPS_WARNING = "warning"
OPS_ERROR = "error"
_OPS_LOG_LEVELS = {
    OPS_INFO: logging.INFO,
    OPS_WARNING: logging.WARNING,
    OPS_ERROR: logging.ERROR,
}
# 重大度の低い順。「warning以上」のような閾値の絞り込みはこの順序だけを根拠にする
# (severity列は文字列で、辞書順ではerror < info < warningになり大小比較ができない)。
OPS_SEVERITY_ORDER = (OPS_INFO, OPS_WARNING, OPS_ERROR)

# sqlite3.OperationalErrorは DB lock/busy と disk full/I-O障害/破損を同一例外型で運ぶ。
# 前者は再試行で回復する一時障害(warning)、後者は放置すると書き込みが恒久的に失われる
# 障害(error)なので、SQLite側のerror名で切り分ける。extended error nameはPython 3.11+の
# sqlite3例外が持つが、無い環境ではmessageの定型文で判定する(SQLite本体の文言)。
_SQLITE_FATAL_ERRORNAMES = ("SQLITE_FULL", "SQLITE_IOERR", "SQLITE_CORRUPT",
                            "SQLITE_NOTADB", "SQLITE_READONLY", "SQLITE_CANTOPEN")
_SQLITE_FATAL_MESSAGES = ("disk is full", "disk i/o error", "database disk image is malformed",
                          "file is not a database", "readonly database", "unable to open database")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    unique_id TEXT NOT NULL,
    room_id TEXT,
    status TEXT NOT NULL,
    started_at REAL NOT NULL,
    ended_at REAL,
    note TEXT NOT NULL DEFAULT '',
    bucket_seconds INTEGER NOT NULL,
    stats_json TEXT NOT NULL DEFAULT '{}',
    owner_nickname TEXT,
    owner_avatar TEXT,
    league TEXT,
    live_create_time REAL,
    conn_instrumentation INTEGER
);
CREATE INDEX IF NOT EXISTS idx_sessions_unique_id ON sessions(unique_id);
CREATE INDEX IF NOT EXISTS idx_sessions_started_at ON sessions(started_at);
-- 配信者1人の履歴は「unique_idで絞って新しい順」で引く。単独indexが2本あっても
-- SQLiteは片方しか使えず、絞り込み後に必ずsortが入る。複合にしてsortごと消す。
CREATE INDEX IF NOT EXISTS idx_sessions_unique_started ON sessions(unique_id, started_at);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    time REAL NOT NULL,
    create_time REAL,
    kind TEXT NOT NULL,
    user_id TEXT,
    user_unique_id TEXT,
    user_nickname TEXT,
    identity_key TEXT,
    text TEXT,
    gift_name TEXT,
    gift_count INTEGER,
    diamonds INTEGER,
    gift_image TEXT,
    gift_id INTEGER,
    enter_source TEXT,
    enter_type TEXT,
    enter_reason TEXT,
    follow_status TEXT,
    follower_count INTEGER,
    is_subscriber INTEGER,
    is_moderator INTEGER,
    is_gift_giver INTEGER
);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, kind);
CREATE INDEX IF NOT EXISTS idx_events_session_kind_time ON events(session_id, kind, time);
CREATE TABLE IF NOT EXISTS users (
    identity_key TEXT PRIMARY KEY,
    user_id TEXT,
    unique_id TEXT,
    nickname TEXT,
    avatar TEXT,
    fans_level INTEGER NOT NULL DEFAULT 0,
    gifter_level INTEGER NOT NULL DEFAULT 0,
    gifter_badge TEXT NOT NULL DEFAULT '',
    member_badge TEXT NOT NULL DEFAULT '',
    first_seen REAL,
    last_seen REAL
);
CREATE TABLE IF NOT EXISTS buckets (
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    start INTEGER NOT NULL,
    gifts INTEGER NOT NULL,
    diamonds INTEGER NOT NULL,
    comments INTEGER NOT NULL,
    likes INTEGER NOT NULL,
    joins INTEGER NOT NULL,
    follows INTEGER NOT NULL,
    shares INTEGER NOT NULL,
    viewers INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_buckets_session ON buckets(session_id);
CREATE TABLE IF NOT EXISTS markers (
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    time REAL NOT NULL,
    kind TEXT NOT NULL,
    label TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_markers_session ON markers(session_id);
CREATE TABLE IF NOT EXISTS battles (
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    battle_id INTEGER NOT NULL,
    data_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_battles_session ON battles(session_id);
CREATE TABLE IF NOT EXISTS collab_windows (
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    channel_id TEXT,
    start REAL NOT NULL,
    end REAL,
    guests_max INTEGER NOT NULL DEFAULT 0,
    data_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_collab_session ON collab_windows(session_id);
-- 宝箱(Treasure Box / Super Fan Box)とPortal。coinを投じて視聴者を集める施策なので、
-- markersだけでは効果測定ができない(markersはsession_id/time/kind/labelの4列で、投下額も
-- 定員も入らない)。
--
-- kindは 'envelope'(送信) と 'portal_closed'(Portal閉鎖時の実移動人数)の2種。
-- **この2つはidで結合できない**: 実測でPortal送信のenvelope_id(7661161260446092052)と
-- PortalEventのportal_info.id(7661135713622936341)は別値だった。結合するなら送信者と
-- 時刻で寄せるしかなく、それは解析側の判断なのでここでは行わない。
--
-- diamond_countはNULLになり得る。実測でbusiness_type=19(Super Fan Box)はdiamond_countを
-- 持たない。0を入れると「無料で配った」という実測していない事実になるのでNULLのままにする。
--
-- envelope_idは同一宝箱のNEW/HIDE通知で共通なので、重複除外のkeyに使う(実測で同じ
-- envelope_idがdisplay違いで2回届いた)。NULLの回は重複除外できない(既存のbattle_idと同じ扱い)。
CREATE TABLE IF NOT EXISTS envelopes (
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    envelope_id TEXT,
    time REAL NOT NULL,
    create_time REAL,
    business_type INTEGER,
    diamond_count INTEGER,
    people_count INTEGER,
    trans_count INTEGER,
    unpack_at REAL,
    sender_user_id TEXT,
    sender_unique_id TEXT,
    data_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_envelopes_session ON envelopes(session_id, time);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
-- 保守の内部状態。settings表とは分ける: あちらは設定画面が編集する項目の入れ物で、
-- operatorが触れない内部markerを混ぜると「見えないのに消せる設定」になる。
CREATE TABLE IF NOT EXISTS db_maintenance (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS recordings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES sessions(id) ON DELETE SET NULL,
    unique_id TEXT NOT NULL,
    path TEXT NOT NULL,
    filename TEXT NOT NULL,
    quality TEXT,
    status TEXT NOT NULL,
    error TEXT,
    started_at REAL NOT NULL,
    ended_at REAL,
    bytes INTEGER NOT NULL DEFAULT 0,
    protected INTEGER NOT NULL DEFAULT 0,
    -- 録画本体の音量正規化を適用した時刻と、そのときの目標LUFS。NULLは未適用。
    -- 一括画面の「処理済」判定はこの列だけを見る(全録画ぶんffprobeを回すのは非現実的)。
    -- mp4を作り直す操作(再mp4化)は、正規化せずに作り直したなら必ずNULLへ戻すこと。
    audio_normalized_at REAL,
    audio_normalized_lufs REAL,
    -- 保持している.tsから作り直した時刻。NULLは未実施。一括の「処理済」判定はこの列だけを
    -- 見る(作り直したmp4は元と同じ名前・場所の別内容で、fileからは見分けが付かない)。
    reprocessed_at REAL,
    -- 録画の実尺(秒)。ffprobeで測った値だけを入れ、測れなければNULL(未測定)のまま残す。
    -- ended_at - started_at は壁時計であって尺ではない: 捕捉が停滞した秒も、再接続の
    -- 待ちも、そのまま尺に化ける(実測で1.6倍)。画面と見積りが要るのは動画そのものの
    -- 長さなので、推測で埋めず測った値を持つ。
    duration_seconds REAL
);
CREATE INDEX IF NOT EXISTS idx_recordings_session ON recordings(session_id);
-- 録画一覧は常に新しい順の全件走査、配信者動画画面はunique_id絞り+新しい順、
-- 起動時の中断録画回収はstatus絞り。session_id単独indexはどれにも効かない。
CREATE INDEX IF NOT EXISTS idx_recordings_started_at ON recordings(started_at);
CREATE INDEX IF NOT EXISTS idx_recordings_uid_started ON recordings(unique_id, started_at);
CREATE INDEX IF NOT EXISTS idx_recordings_status ON recordings(status);
CREATE TABLE IF NOT EXISTS monitored_targets (
    unique_id TEXT PRIMARY KEY,
    added_at REAL NOT NULL,
    record_video INTEGER NOT NULL DEFAULT 1
);
-- 発見候補のうちoperatorが「監視しない」と判断した相手。候補listはbattle履歴から毎回
-- 導出するので、除外を記録しておかないと同じ相手が永久に上位へ出続ける。監視へ昇格した
-- 相手はmonitored_targetsに載るため、ここへ入れるのは明示的な却下だけである。
CREATE TABLE IF NOT EXISTS discovery_dismissed (
    unique_id TEXT PRIMARY KEY,
    dismissed_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS transcripts (
    recording_id INTEGER PRIMARY KEY REFERENCES recordings(id) ON DELETE CASCADE,
    language TEXT,
    model TEXT,
    text TEXT NOT NULL DEFAULT '',
    segments_json TEXT NOT NULL DEFAULT '[]',
    duration REAL,
    created_at REAL NOT NULL,
    timemap_version INTEGER,
    timemap_anchors INTEGER,
    timemap_drift_seconds REAL
);
-- 配信者動画画面の横断検索index。転写segmentとcommentを同じ行形式へ正規化し、
-- video_timeにmp4のPTS秒を持たせる。commentのwall-clock -> PTS変換はindex時に一度だけ
-- video_overlayと同じmapperで行うので、検索時は変換不要かつ焼き込み動画と位置が一致する。
CREATE TABLE IF NOT EXISTS search_hits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    recording_id INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    session_id INTEGER,
    unique_id TEXT NOT NULL,
    started_at REAL NOT NULL,
    video_time REAL NOT NULL,
    end_time REAL,
    nickname TEXT,
    body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_search_hits_rec ON search_hits(recording_id, source);
CREATE INDEX IF NOT EXISTS idx_search_hits_uid ON search_hits(unique_id, started_at);
-- 日本語は語境界が無いのでunicode61では部分一致にならない。trigramなら3文字以上の
-- 任意部分文字列が引ける(1-2文字のqueryはLIKEへ落とす)。
CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
    body, content='search_hits', content_rowid='id', tokenize='trigram'
);
-- 切り出し候補の蓄積。複数配信を横断して探す性質上、見つけた端から溜めて最後にまとめて
-- NLEへ渡すため、mp4出力とは独立に範囲だけを保持する。
CREATE TABLE IF NOT EXISTS cut_list (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    unique_id TEXT NOT NULL,
    start REAL NOT NULL,
    end REAL NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cut_list_rec ON cut_list(recording_id);
-- 見どころ(bookmark)。cut_listが「書き出す素材の候補」なのに対し、こちらは「後でまた
-- 見たい場所」の記憶で、書き出しの意思とは独立に溜まる。end IS NULLが点(コメント1件や
-- 現在位置)、endを持てば範囲。source_hit_idはメモ元のsearch_hits行(コメント由来のとき)。
-- live_wall/pts_mappedは配信を見ながら押した見どころのため。押した瞬間に判るのは
-- wall-clockだけで、mp4のPTS軸とはmux inflationぶんずれる(実測: 112分の録画で340秒)。
-- 押下時はwall-clockから出した暫定値をstartへ入れてpts_mapped=0とし、finalizeで
-- timing mapを使ってPTS軸へ再mapしてから1にする。再mapできなかった行は0のまま残し、
-- 「これは暫定値だ」と画面が言えるようにする(黙って確定値のふりをさせない)。
CREATE TABLE IF NOT EXISTS bookmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    unique_id TEXT NOT NULL,
    start REAL NOT NULL,
    end REAL,
    memo TEXT NOT NULL DEFAULT '',
    source_hit_id INTEGER,
    live_wall REAL,
    pts_mapped INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bookmarks_rec ON bookmarks(recording_id, start);
-- 一括転写のqueue。processが落ちても残るようDBに置き、起動時にrunningをpendingへ戻す。
CREATE TABLE IF NOT EXISTS transcribe_queue (
    recording_id INTEGER PRIMARY KEY REFERENCES recordings(id) ON DELETE CASCADE,
    unique_id TEXT NOT NULL,
    state TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    queued_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL,
    pct INTEGER NOT NULL DEFAULT 0,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_transcribe_queue_state ON transcribe_queue(state, priority, queued_at);
-- 映像job(焼き込み/Up出力/再mp4化)の永続queue。転写queueと同格の位置づけだが、1録画に対して
-- 種別違いのjobが同時に並ぶ(焼き込みとUp出力)ため、PKはrecording_idではなく独立のidにする。
-- job_idはJobRegistry(process内の進捗台帳)とops_events.job_idと同じ値を入れ、log・DB・画面を
-- 1つのIDで突き合わせられるようにする。
-- recording_id/session_idともCASCADE: 対象が消えたjobは投入意図ごと無意味になるため残さない
-- (孤児行を残すと、worker が存在しない録画を延々pickして失敗し続ける)。
CREATE TABLE IF NOT EXISTS media_job_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    recording_id INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
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
    -- 実行中に判明した後始末用の情報(再mp4化の_backup退避先など)と、完了時の成果物path。
    result_json TEXT NOT NULL DEFAULT '{}',
    -- 投入時の指定(clip一括書き出しの範囲list・素材版・正規化の有無など)。録画idだけでは
    -- 再現できない指定を持つ種別のためにある。
    params_json TEXT NOT NULL DEFAULT '{}',
    -- 待機へ戻したjobを、この時刻まで拾わない(保存先volumeの復帰待ちなど)。
    not_before REAL,
    -- 最初に待機へ戻した時刻。総待ち時間の打ち切り判定に使う。
    deferred_since REAL
);
CREATE INDEX IF NOT EXISTS idx_media_job_queue_state ON media_job_queue(state, priority, queued_at);
CREATE INDEX IF NOT EXISTS idx_media_job_queue_rec ON media_job_queue(recording_id, state);
CREATE TABLE IF NOT EXISTS viewer_samples (
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    time REAL NOT NULL,
    create_time REAL,
    viewers INTEGER NOT NULL,
    total_viewers INTEGER,
    anonymous INTEGER
);
CREATE INDEX IF NOT EXISTS idx_viewer_samples_session ON viewer_samples(session_id);
-- RoomUserSeqが毎回運んでくるTikTok公式の累積貢献ranking(上位N人)の時系列。
-- scoreはTikTok側が算出した累積値で、こちらのgift eventの積み上げとは独立の系列である。
-- 両者を突き合わせると「こちらが取りこぼしたgiftの量」が実測できる(自前集計の検算)ため、
-- 集計後の値ではなく届いたsnapshotのまま残す。scoreの単位はTikTokが公開していないので
-- coin/diamond等の意味づけをした列名は付けない(意味が確定するまではscoreのまま)。
-- 1 messageぶんの上位listは同一timeの複数行で表す(rankが1行1人)。
CREATE TABLE IF NOT EXISTS contributor_samples (
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    time REAL NOT NULL,
    create_time REAL,
    rank INTEGER,
    score INTEGER,
    identity_key TEXT,
    user_id TEXT,
    user_unique_id TEXT,
    user_nickname TEXT,
    user_avatar TEXT
);
CREATE INDEX IF NOT EXISTS idx_contributor_samples_session ON contributor_samples(session_id, time);
CREATE INDEX IF NOT EXISTS idx_contributor_samples_identity ON contributor_samples(session_id, identity_key);
-- FollowEventが運ぶ配信者のfollower総数の時系列。events.follows(event本数)とは別物で、
-- unfollowも切断中の増減もこちらには載る。TikTok側の値は結果整合で前後するため
-- (実観測: 81507の次に81465が届く)、単調化や補間はせず届いた値をそのまま残す。
CREATE TABLE IF NOT EXISTS follower_samples (
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    time REAL NOT NULL,
    create_time REAL,
    follower_count INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_follower_samples_session ON follower_samples(session_id, time);
-- 状態遷移の記録(Layer2)。session_id/recording_idは意図的にFKを張らない: この表は障害と
-- その後始末を後から再構成するためのもので、参照先sessionが消えていることこそ調べたい状況
-- である。FKにすると孤児行がFK違反で書けなくなり、記録すべき瞬間に限って記録が残らない。
-- 結果としてsession削除後も行は残る(ON DELETEの伝播無し)ので、画面表示はLEFT JOINで組む。
CREATE TABLE IF NOT EXISTS ops_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ops_id TEXT NOT NULL,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    unique_id TEXT,
    session_id INTEGER,
    recording_id INTEGER,
    job_id TEXT,
    duration_ms REAL,
    detail TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_ops_events_severity_ts ON ops_events(severity, ts);
CREATE INDEX IF NOT EXISTS idx_ops_events_session_ts ON ops_events(session_id, ts);
CREATE INDEX IF NOT EXISTS idx_ops_events_kind_ts ON ops_events(kind, ts);
CREATE INDEX IF NOT EXISTS idx_ops_events_job ON ops_events(job_id, ts);
-- 容量内訳のfilesystem走査結果cache。数TB規模のHDDでは1回の走査が分単位かかるため、
-- APIは常にこのcache(1行のみ)を返し、再走査はoperatorが明示的に実行する。参照先を持たない
-- 単独表なのでON DELETEの伝播は無く、走査のたびに全置換する。
CREATE TABLE IF NOT EXISTS storage_scan (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    scanned_at REAL NOT NULL,
    duration_ms REAL NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL DEFAULT '{}'
);
-- 容量の時系列。storage_scanとは役割が違うので別表にする: あちらは「最新の内訳」1行を
-- 全置換で持つcacheで、増減の履歴が原理的に残らない(予測が出せない)。こちらは追記のみで、
-- 1行が1時点のsnapshotである。1日1回程度なので行数は年365行規模にしかならない。
-- filesystem走査は伴わない: drive空きはO(1)、録画量とDB行数はDBから引ける(実測48ms)。
CREATE TABLE IF NOT EXISTS capacity_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sampled_at REAL NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_capacity_samples_at ON capacity_samples(sampled_at);
CREATE TABLE IF NOT EXISTS analytics_session_cache (
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    version INTEGER NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    computed_at REAL NOT NULL,
    PRIMARY KEY (session_id, kind)
);
-- ローカルLLMの分析結果。1回の推論が数十秒かかるので結果を残し、model・prompt版・入力の
-- 指紋のいずれかが変われば作り直す(analytics_session_cacheと同型のversion運用)。
-- analytics_session_cacheと決定的に違うのは「未計算をまとめて計算する経路を持たない」点で、
-- 再計算はoperatorの明示要求時のみ。session数ぶんのLLM実行を起動時や初回accessで走らせると
-- serverが事実上停止する。
-- session対象の行はsession_idを埋めてON DELETE CASCADEで孤児化を防ぐ。配信者対象の行は
-- session_idがNULLで、伝播対象を持たない(配信者は表ではなくunique_idの参照のため)。
CREATE TABLE IF NOT EXISTS ai_analysis (
    kind TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    session_id INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    prompt_version INTEGER NOT NULL,
    input_signature TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    computed_at REAL NOT NULL,
    PRIMARY KEY (kind, target_type, target_id)
);
"""

# メンバー限定/年齢制限で接続できず、event・録画・bucketを1件も持たないsession。
# 「なぜこのidが欠けているのか」を履歴で説明するため行は残すが、配信実績ではないので
# 回数集計・統計・全体解析cacheからは一貫して除外する(除外を忘れると配信回数が水増しされ、
# 0件sessionが全体解析の分母に入る)。
SESSION_STATUS_RESTRICTED = "restricted"
# sessionsに別名 s を付けたqueryへ差し込む除外句。別名なしのqueryでは _NO_ALIAS 版を使う。
_EXCLUDE_RESTRICTED = f" AND s.status != '{SESSION_STATUS_RESTRICTED}'"
_EXCLUDE_RESTRICTED_NO_ALIAS = f" AND status != '{SESSION_STATUS_RESTRICTED}'"

# collectorの接続系計装(connect/reconnect/disconnect/disconnect_unplanned markerの
# 中間永続化)の版。sessions.conn_instrumentationへ作成時に打ち、カバレッジ解析が
# 「切断が記録されていないのか、切断が無かったのか」を区別する唯一の根拠にする。
# これがNULLのsessionは計装以前の収集で、欠測秒数は0ではなく計測不能。
# marker種別やその発行条件を変えたら+1すること(以降のsessionだけが新ruleで測られる)。
CONN_INSTRUMENTATION_VERSION = 1


def _session_row_to_dict(row: sqlite3.Row) -> dict:
    item = dict(row)
    item["stats"] = json.loads(item.pop("stats_json"))
    if "bucket_peak_viewers" in item:
        # stats_jsonのviewersは最終値。最大同接は収集中に保持したviewers_peakを使い、
        # それが無い旧sessionはbucketsのMAXから復元する(それも無ければ最終値)。
        bucket_peak = item.pop("bucket_peak_viewers")
        item["stats"]["viewers_peak"] = (
            item["stats"].get("viewers_peak")
            or bucket_peak
            or item["stats"].get("viewers", 0)
            or 0
        )
    return item


def _identity_key(user_id, unique_id, nickname) -> str:
    """同一User判定の不変ID優先フォールバック: 数値user_id -> @unique_id -> nickname。
    events.identity_key(SQL側のCOALESCE)と完全に一致させること。"""
    return (str(user_id or "").strip()
            or (unique_id or "").strip()
            or (nickname or "").strip())


# 1人の視聴者を指さないidentity_key。'' は身元を採れなかったeventの現行表現。
# '(unknown)' は表示用リテラルを名寄せkeyに使っていた時期の畳み込み跡で(commit 022b2e0で
# 収集側は修正済み)、既存DBに残る行は別人が1 identityへ潰れたものである。分離に要る情報は
# 失われているため復元できない。Fan台帳はこれらを1人として並べてはならない。
NON_IDENTITY_KEYS = ("", "(unknown)")


def _valid_owner_id(user_id) -> bool:
    """配信者の数値アカウントIDとして妥当か。TikTokの実IDは長い数値で、team_id等の
    小さな値(例: '1','2')が誤ってown-host user_idに混入したゴミを弾く。"""
    s = str(user_id or "").strip()
    return s.isdigit() and len(s) >= 8


def _session_ids_of(*row_lists) -> list:
    """buffer済み行のsession_id一覧(先頭要素)。batch writerのlogに必ず添える: poison-pillや
    再キューの犯人がどのsessionかは、これが無いと件数だけ見ても永久に特定できない。"""
    ids = set()
    for rows in row_lists:
        ids.update(row[0] for row in rows if row)
    return sorted(ids)


def _to_int(value) -> int:
    """liveの生fieldは型が不確実(非数値文字列/None/float文字列等)。int()の素の呼び出しは
    ValueErrorでwriter batch全体を巻き込むため、変換不能値は0へ落として書き込みを止めない。"""
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0


class Storage:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        # 書き込みバッチ用のバッファ(DB lockとは別のlockで保護)。identity_key単位の
        # upsert間引きキャッシュもここで持つ(liveの高頻度取り込みのみ対象)。
        self._buf_lock = threading.Lock()
        self._flush_cond = threading.Condition(self._buf_lock)
        self._event_buffer: list = []
        self._viewer_buffer: list = []
        self._pending_users: list = []
        self._user_cache: dict = {}
        # 終了済みBattleの窓は固定なので貢献集計を1度だけ計算してキャッシュする。
        self._battle_contrib_cache: dict = {}
        self._closed = False
        # 追記型の耐久journal。batched SQLite writerとは独立に、取り込み時点でeventをdiskへ
        # 追記する最終防波堤。writer停滞やクラッシュでもここに残り、起動時recoverで復元できる。
        self._journal_enabled = get_journal_enabled()
        self._journal_lock = threading.Lock()
        self._journal_fh = None
        self._journal_day = None
        # ops_events(Layer2)。ops_idはprocess起動ごとのtokenと連番で組み、再起動をまたいでも
        # 衝突しない。DB書き込みが失敗してもLayer1のlogにはこのidが載るので、行が無いこと自体を
        # 後から追跡できる。itertools.countの__next__はCPythonでatomicなので追加lockは不要。
        self._ops_run_token = os.urandom(4).hex()
        self._ops_seq = itertools.count(1)
        self._ops_fail_lock = threading.Lock()
        self._ops_write_failures = 0
        self._ops_first_failure_logged = False
        # ops_eventsの観測者(通知機構)。ops_eventsは障害系・session lifecycleの単一の口なので、
        # 通知のために別の計装を各所へ足す代わりに、ここへ1本ぶら下げる。
        self._ops_observer = None
        # backlog警告の間隔gate(writerスレッド専用に触るのでlock不要)。
        self._backlog_logged_at = 0.0
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(SCHEMA)
            self._migrate()
            self._conn.commit()
        # 破壊的migrationの直前に退避する。glove/battleのmigrationはbattles.data_jsonを
        # in-placeで書き換え、元の値はどこにも残らない。lockの外なのは、退避が自分のread接続を
        # 開くためで、ここはまだwriter threadも起動していない起動直後の単独実行区間である。
        premigration_backup = self._backup_before_migrations()
        with self._lock:
            # 旧方式judgeのグローブcrit event(vマーカー無し)を新方式へ再判定する。
            # 冪等で、対象が無ければno-op。collectorはまだ動いていない起動時のみ安全。
            glove_stats = glove_migration.migrate_glove_events(self._conn, get_log_dir())
            if glove_stats["battles"]:
                logger.info("migrated glove events to v2: %s", glove_stats)
            # 旧ruleでチーム戦扱いされていた個人マルチ(1:1:1)のtype/opp_score/resultを
            # 現行ruleへ再判定する。冪等で、対象が無ければno-op。
            topo_stats = battle_migration.migrate_battle_topology(self._conn)
            if topo_stats["battles"]:
                logger.info("migrated battle topology to v2: %s", topo_stats)
            pruned_ops = self._prune_ops_events_locked()
            self._set_maintenance_locked(_MIGRATION_BACKUP_KEY, _migration_versions())
            self._conn.commit()
        self.premigration_backup = premigration_backup
        self._writer = threading.Thread(
            target=self._writer_loop, name="storage-writer", daemon=True
        )
        self._writer.start()
        logger.info(
            "storage initialized (db=%s)", db_path,
            extra={"event": "storage.initialized",
                   "ctx": {"path": str(Path(db_path).resolve()),
                           "ops_events_pruned": pruned_ops,
                           "journal_enabled": self._journal_enabled,
                           **self._db_space_ctx()}},
        )

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
            has_rows = self._conn.execute("SELECT 1 FROM battles LIMIT 1").fetchone() is not None
        if done == versions:
            return {"taken": False, "skipped": "already_migrated", "versions": versions}
        if not has_rows:
            # 両migrationが書き換えるのはbattles表だけ。空なら守る対象が無い(新規DBの初回起動)。
            return {"taken": False, "skipped": "no_rows", "versions": versions}
        try:
            result = dbmaint.create_backup(
                self._db_path, reason=dbmaint.REASON_PRE_MIGRATION
            )
        except Exception as exc:
            logger.error(
                "pre-migration database snapshot failed; startup is aborted so the "
                "destructive migration does not run without one (%s)", exc, exc_info=True,
                extra={"event": "storage.premigration_backup_failed",
                       "ctx": {"versions": versions,
                               "backup_dir": str(dbmaint.backup_dir()),
                               **self._db_space_ctx()}},
            )
            raise
        logger.info(
            "pre-migration database snapshot written to %s", result["path"],
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

    # ----- ops_events(Layer2: 状態遷移のDB記録) ----------------------------------------
    def record_ops_event(
        self,
        log: logging.Logger,
        kind: str,
        message: str,
        *,
        severity: str = OPS_INFO,
        unique_id=None,
        session_id=None,
        recording_id=None,
        job_id=None,
        duration_ms=None,
        detail: Optional[dict] = None,
        exc_info=False,
    ) -> str:
        """状態遷移をlog(Layer1)とops_events表(Layer2)へ1回の呼び出しで両方記録する。

        logger引数が必須なのは意図的である。この関数の中で getLogger("tictok.storage") を
        使うと、collectorやrecorderの状態遷移まで全てstorage名義のlogになり、module別に
        logを抽出する運用が壊れる。呼び出し元は自分のmodule loggerを渡すこと。

        Layer1のeventとLayer2のkindには同一文字列が入る(別名を作らない)。両者はops_idで
        結合でき、job_idは焼き込みやupscaleのようにsub-process/worker threadを跨ぐ処理の
        log群とops_eventsを突き合わせるための鍵になる。

        相関ID(unique_id/session_id/recording_id)はLayer1には自動注入されるが、DBの列には
        値そのものが要るのでcurrent_context()から補う。明示引数が渡された場合はそちらを優先
        する(contextの外、例えばworker threadから呼ぶ場合)。

        DB書き込みの失敗は本流を止めない。ただし無音にもせず、最初の1件をerrorで出した上で
        累計をcloseで必ず報告する。self._lockを取るので、lockを保持したまま呼ばないこと。
        """
        level = _OPS_LOG_LEVELS.get(severity)
        if level is None:
            raise ValueError(f"unknown ops severity: {severity!r}")
        ops_id = f"{self._ops_run_token}-{next(self._ops_seq)}"
        bound = current_context()
        unique_id = bound.get("unique_id") if unique_id is None else unique_id
        session_id = bound.get("session_id") if session_id is None else session_id
        recording_id = bound.get("recording_id") if recording_id is None else recording_id

        log_ctx = dict(detail or {})
        log_ctx["ops_id"] = ops_id
        if job_id is not None:
            log_ctx["job_id"] = job_id
        if duration_ms is not None:
            log_ctx["duration_ms"] = duration_ms
        log.log(level, message, extra={"event": kind, "ctx": log_ctx}, exc_info=exc_info)

        self._write_ops_event(
            ops_id, kind, severity, message, unique_id, session_id,
            recording_id, job_id, duration_ms, detail,
        )
        self._notify_ops_observer(kind, severity, message, unique_id, detail)
        return ops_id

    def set_ops_observer(self, observer) -> None:
        """ops_eventが記録されるたびに呼ばれるcallbackを1つ登録する(通知機構用)。

        DB書き込みの後に呼ぶ。順序を逆にすると、通知は届いたのに運用logにその行が無いという
        状態が起こり得る。
        """
        self._ops_observer = observer

    def _notify_ops_observer(self, kind, severity, message, unique_id, detail) -> None:
        """観測者へ配る。record_ops_eventはあらゆるthreadから、しばしば障害処理の最中に
        呼ばれるので、観測者側の失敗を呼び出し元へ返さない。通知が落ちても記録は残る。"""
        observer = self._ops_observer
        if observer is None:
            return
        try:
            observer(kind, severity, message, unique_id, detail)
        except Exception:
            logger.exception(
                "ops event observer failed; the event itself is recorded (kind=%s)", kind,
                extra={"event": "storage.ops_observer_failed", "ctx": {"kind": kind}},
            )

    def _write_ops_event(self, ops_id, kind, severity, message, unique_id,
                         session_id, recording_id, job_id, duration_ms, detail) -> None:
        """ops_events表への1行INSERT。障害の記録が障害を増やしてはならないので、あらゆる例外を
        捕まえて呼び出し元へ返さない。代わりに失敗数を数え、close()が必ず1行報告する。"""
        try:
            payload = self._ops_detail_json(detail)
            with self._lock:
                self._conn.execute(
                    "INSERT INTO ops_events (ops_id, ts, kind, severity, message, unique_id,"
                    " session_id, recording_id, job_id, duration_ms, detail)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (ops_id, time.time(), kind, severity, message,
                     str(unique_id) if unique_id is not None else None,
                     session_id, recording_id,
                     str(job_id) if job_id is not None else None,
                     duration_ms, payload),
                )
                self._conn.commit()
        except Exception:
            with self._ops_fail_lock:
                self._ops_write_failures += 1
                first = not self._ops_first_failure_logged
                self._ops_first_failure_logged = True
            if first:
                # 2件目以降は数えるだけにする。DBが落ちている間は全ops eventが失敗するため、
                # 毎回出すと本来診断したいlogを押し流す。累計はcloseで必ず出る。
                logger.error(
                    "ops event could not be persisted; logging continues (kind=%s)", kind,
                    exc_info=True,
                    extra={"event": "storage.ops_event_write_failed",
                           "ctx": {"ops_id": ops_id, "kind": kind, **self._db_space_ctx()}},
                )

    def _ops_detail_json(self, detail) -> str:
        """detailをJSON化する。想定外に大きなpayload(ffmpegのstderr全文等)でops_eventsが
        DB最大の表になるのを防ぐため上限で切るが、切ったこと自体を行に残して黙らせない。"""
        if not detail:
            return "{}"
        text = json.dumps(detail, ensure_ascii=False, default=str)
        limit = get_ops_events_detail_max_chars()
        if len(text) > limit:
            return json.dumps(
                {"truncated_chars": len(text) - limit, "detail": text[:limit]},
                ensure_ascii=False,
            )
        return text

    def _prune_ops_events_locked(self) -> int:
        """保持期間を過ぎたops_eventsを削除する(起動時1回)。lock保持前提、commitは呼び出し元。"""
        days = get_ops_events_retention_days()
        if days <= 0:
            return 0
        cursor = self._conn.execute(
            "DELETE FROM ops_events WHERE ts < ?", (time.time() - days * 86400,)
        )
        return max(cursor.rowcount, 0)

    @staticmethod
    def _like_prefix(text: str) -> str:
        """LIKEのmeta文字を無効化した前方一致pattern。ESCAPE句と対で使う。kindは
        'process.settings_updated' のように '_' を含むので、escapeしないと '_' が
        任意1文字として当たり、別kindを巻き込む。"""
        escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return escaped + "%"

    def _ops_events_filters(self, *, severity: Optional[str], kind: Optional[str],
                            kind_prefix: Optional[str], unique_id: Optional[str],
                            session_id: Optional[int], job_id: Optional[str],
                            since: Optional[float], until: Optional[float],
                            min_severity: Optional[str] = None) -> tuple:
        """list/countで同一の絞り込みを組む。両者で条件がずれるとbadgeの件数と一覧の
        件数が食い違うため、SQLの組み立ては1箇所に置く。"""
        clauses = []
        params: list = []
        if min_severity is not None:
            # 「warning以上」の閾値指定。severity列は文字列で大小比較ができないため、
            # 重大度の順序(OPS_SEVERITY_ORDER)から該当する値を並べてINで引く。
            if min_severity not in OPS_SEVERITY_ORDER:
                raise ValueError(f"unknown ops severity: {min_severity!r}")
            levels = OPS_SEVERITY_ORDER[OPS_SEVERITY_ORDER.index(min_severity):]
            clauses.append(f"o.severity IN ({','.join('?' * len(levels))})")
            params.extend(levels)
        for column, value in (("o.severity", severity), ("o.kind", kind),
                              ("o.unique_id", unique_id), ("o.session_id", session_id),
                              ("o.job_id", job_id)):
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)
        if kind_prefix:
            clauses.append("o.kind LIKE ? ESCAPE '\\'")
            params.append(self._like_prefix(kind_prefix))
        if since is not None:
            clauses.append("o.ts >= ?")
            params.append(since)
        if until is not None:
            clauses.append("o.ts <= ?")
            params.append(until)
        return clauses, params

    def list_ops_events(self, *, limit: Optional[int] = None, severity: Optional[str] = None,
                        kind: Optional[str] = None, kind_prefix: Optional[str] = None,
                        unique_id: Optional[str] = None, session_id: Optional[int] = None,
                        job_id: Optional[str] = None, since: Optional[float] = None,
                        until: Optional[float] = None, offset: int = 0,
                        before_ts: Optional[float] = None,
                        before_id: Optional[int] = None,
                        min_severity: Optional[str] = None) -> list:
        """画面表示用の一覧。sessions/recordingsはLEFT JOINで引く: ops_eventsはFKを張らず
        session削除後も残るため、INNER JOINだと障害当時の行が消えて見える。

        ページングはkeyset(before_ts + before_id)を既定にする。この表は末尾に行が増え続けるので、
        OFFSETだと読み込み中に新しい行が入るたび境界の行が重複・欠落する。offsetも受けるが、
        keysetを指定したときはそちらを優先する。

        limitはNoneのときだけ設定値の既定を使う。0以下は拒否する: SQLiteはLIMIT -1を
        「無制限」と解釈するため、素通しすると1requestでops_events全件を読み込んでしまう。
        全件取得はこの一覧の契約に無い。"""
        if limit is not None:
            limit = int(limit)
            if limit <= 0:
                raise ValueError(f"limitは1以上を指定してください: {limit}")
        clauses, params = self._ops_events_filters(
            severity=severity, kind=kind, kind_prefix=kind_prefix, unique_id=unique_id,
            session_id=session_id, job_id=job_id, since=since, until=until,
            min_severity=min_severity,
        )
        keyset = before_ts is not None and before_id is not None
        if keyset:
            # tsは同値が並び得る(同一ops_idの連続記録)ので、idを第2 keyにして順序を確定させる。
            clauses.append("(o.ts < ? OR (o.ts = ? AND o.id < ?))")
            params.extend([before_ts, before_ts, before_id])
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit if limit is not None else get_ops_events_query_limit())
        tail = " LIMIT ?"
        if not keyset and offset:
            tail += " OFFSET ?"
            params.append(int(offset))
        with self._lock:
            rows = self._conn.execute(
                "SELECT o.*, s.unique_id AS session_unique_id, s.started_at AS session_started_at,"
                " s.status AS session_status, r.filename AS recording_filename,"
                " r.status AS recording_status"
                " FROM ops_events o"
                " LEFT JOIN sessions s ON s.id = o.session_id"
                " LEFT JOIN recordings r ON r.id = o.recording_id"
                f"{where} ORDER BY o.ts DESC, o.id DESC{tail}",
                tuple(params),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            try:
                item["detail"] = json.loads(item.get("detail") or "{}")
            except ValueError:
                # 行を落とすより、読めなかった生文字列をそのまま見せる方が診断に足る。
                item["detail"] = {"unparsed": item.get("detail")}
            items.append(item)
        return items

    def count_ops_events_by_severity(self, *, since: Optional[float] = None,
                                     until: Optional[float] = None,
                                     kind_prefix: Optional[str] = None) -> dict:
        """severity別の件数。header badge用にCOUNT(*)だけを引く軽量query(一覧を取って
        数えると1画面ぶんの上限に切られて件数が嘘になる)。"""
        clauses, params = self._ops_events_filters(
            severity=None, kind=None, kind_prefix=kind_prefix, unique_id=None,
            session_id=None, job_id=None, since=since, until=until,
        )
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT o.severity AS severity, COUNT(*) AS n FROM ops_events o{where}"
                " GROUP BY o.severity",
                tuple(params),
            ).fetchall()
        return {row["severity"]: row["n"] for row in rows}

    def ops_event_kinds(self, *, since: Optional[float] = None) -> list:
        """記録されているkindの一覧(件数付き)。filterの候補をhard-codeせず実データから出す。"""
        clauses, params = self._ops_events_filters(
            severity=None, kind=None, kind_prefix=None, unique_id=None,
            session_id=None, job_id=None, since=since, until=None,
        )
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT o.kind AS kind, COUNT(*) AS n FROM ops_events o{where}"
                " GROUP BY o.kind ORDER BY o.kind",
                tuple(params),
            ).fetchall()
        return [{"kind": row["kind"], "count": row["n"]} for row in rows]

    def ops_event_unique_ids(self, *, since: Optional[float] = None) -> list:
        """記録に出てくる配信者の一覧(件数付き)。配信者filterの候補に使う。

        配信者一覧(streamer_index)ではなくops_events自身から引く。監視を外した配信者の
        障害記録は残り続けるので、一覧側から候補を作ると「表には居るのに選べない」行が出る。"""
        clauses, params = self._ops_events_filters(
            severity=None, kind=None, kind_prefix=None, unique_id=None,
            session_id=None, job_id=None, since=since, until=None,
        )
        clauses.append("o.unique_id IS NOT NULL AND o.unique_id <> ''")
        where = " WHERE " + " AND ".join(clauses)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT o.unique_id AS unique_id, COUNT(*) AS n FROM ops_events o{where}"
                " GROUP BY o.unique_id ORDER BY o.unique_id",
                tuple(params),
            ).fetchall()
        return [{"unique_id": row["unique_id"], "count": row["n"]} for row in rows]

    # ----- AI分析結果のcache -----------------------------------------------------------
    # LLM推論はここへ保存し、model・prompt版・入力指紋が一致する限り再実行しない。
    # 「未計算をまとめて計算する」経路は意図的に持たない(operatorの明示要求のみで走らせる)。

    def get_ai_analysis(self, kind: str, target_type: str, target_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM ai_analysis WHERE kind = ? AND target_type = ? AND target_id = ?",
                (kind, target_type, str(target_id)),
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        try:
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
        except ValueError:
            # 壊れた行を「未分析」に化けさせない。読めなかったことを呼び出し元へ伝える。
            item.pop("payload_json", None)
            item["payload"] = None
            item["payload_unreadable"] = True
        return item

    def save_ai_analysis(self, kind: str, target_type: str, target_id: str, *,
                         session_id: Optional[int], model: str, prompt_version: int,
                         input_signature: str, payload: dict) -> dict:
        computed_at = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO ai_analysis"
                " (kind, target_type, target_id, session_id, model, prompt_version,"
                "  input_signature, payload_json, computed_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (kind, target_type, str(target_id), session_id, model, int(prompt_version),
                 input_signature, json.dumps(payload, ensure_ascii=False), computed_at),
            )
            self._conn.commit()
        return {
            "kind": kind,
            "target_type": target_type,
            "target_id": str(target_id),
            "session_id": session_id,
            "model": model,
            "prompt_version": int(prompt_version),
            "input_signature": input_signature,
            "payload": payload,
            "computed_at": computed_at,
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

    def _writer_loop(self) -> None:
        while True:
            with self._flush_cond:
                self._flush_cond.wait(timeout=_WRITE_FLUSH_INTERVAL_SECONDS)
                closed = self._closed
            # drainの例外でwriterスレッドを死なせない(死ぬと以降の全書き込みが黙って
            # バッファに滞留したまま失われる)。失敗行は_drain側で再キューされ次周期で再試行。
            try:
                self._drain()
            except Exception as exc:
                # 詳細(件数・session_ids・sqlite error種別)は_drain側の失敗logが持つ。ここは
                # 「writerスレッドが生きたまま次周期へ進んだ」ことだけを1行残す。
                logger.warning(
                    "storage writer drain cycle failed; retrying next cycle",
                    exc_info=True,
                    extra={"event": "storage.writer_cycle_failed",
                           "ctx": {"exc_type": type(exc).__name__}},
                )
            if closed:
                return

    def _drain(self) -> None:
        """バッファ済みのevent/viewer sample/user upsertを1 transactionで書き出す。
        writerスレッドと同期flush()の双方から呼ばれるため、buffer入れ替えからcommitまで
        DB lockを保持し、flush()呼び出し時に進行中の書き込み完了を確実に待たせる。"""
        with self._lock:
            with self._buf_lock:
                events = self._event_buffer
                viewers = self._viewer_buffer
                users = self._pending_users
                if not (events or viewers or users):
                    return
                self._event_buffer = []
                self._viewer_buffer = []
                self._pending_users = []
                # backlogの測定はここでしか行わない。len(self._event_buffer)には_buf_lockが
                # 必要で、既にそれを保持しているこの地点なら新規のlock取得がゼロで済む。
                # 別の場所で測ると_lock -> _buf_lockの取得順を崩すdeadlock riskを新設する。
                backlog = len(events) + len(viewers) + len(users)
            self._log_backlog(backlog, events, viewers)
            # session削除とbuffer滞留の競合で、既に消えたsessionを参照する孤児行が残ることが
            # ある(events/viewer_samplesはsessions(id)へFK)。これを含めてexecutemanyすると
            # FK違反でbatchごと失敗し、下のexcept再キューで永久に詰まる(poison-pill)。孤児は
            # 再試行しても成功しない永続エラーなので、insert前にDB実在のsession_idで濾し取り除く。
            # delete_sessionはself._lockを取ってからDELETEするため、この判定〜commitの間に
            # 対象sessionが消えることはなく(TOCTOU無し)、判定は確定的。
            events, viewers = self._drop_orphan_rows(events, viewers)
            try:
                self._write_batch_locked(events, viewers, users)
                self._conn.commit()
            except sqlite3.OperationalError as exc:
                # 一時障害(DB lock/busy/disk full/I/O)。再試行で回復し得るので、rollbackの上で
                # 未確定分を先頭へ戻し次周期で再試行する。1行の永続不良ではないため隔離しない。
                self._rollback_and_requeue(events, viewers, users, exc)
                raise
            except sqlite3.IntegrityError as exc:
                # 制約違反(想定外の不正行)。executemanyは違反行でbatch全体を失敗させるので、
                # このまま再キューすると其の1行が後続すべてを永久に道連れにする(poison-pill)。
                # rollbackしてから1行ずつ入れ直し、違反行だけを隔離(dead-letterへ退避)して
                # 残りは確定させる。全体を止めない。
                logger.warning(
                    "storage batch hit an integrity violation; re-inserting row by row to isolate it",
                    exc_info=True,
                    extra={"event": "storage.integrity_isolation_started",
                           "ctx": {"events": len(events), "viewers": len(viewers),
                                   "users": len(users),
                                   "session_ids": _session_ids_of(events, viewers),
                                   "error": str(exc)}},
                )
                try:
                    self._conn.rollback()
                except Exception:
                    logger.exception(
                        "storage rollback failed",
                        extra={"event": "storage.rollback_failed",
                               "ctx": {"session_ids": _session_ids_of(events, viewers)}},
                    )
                try:
                    self._write_isolating_locked(events, viewers, users)
                    self._conn.commit()
                except sqlite3.OperationalError as inner:
                    # 隔離中に一時障害が出たら、全体をrollbackして次周期へ再キュー(再試行で回復)。
                    self._rollback_and_requeue(events, viewers, users, inner)
                    raise
            except Exception as exc:
                # 想定外(DB corruption等のDatabaseErrorや実装バグ)。bufferは既に空にしている
                # ため、ここで捨てるとevent/viewerが黙って失われる。判別不能な障害は一時障害と
                # 同様に扱い、rollbackの上で再キューして次周期に委ねる(誤って全損させない)。
                self._rollback_and_requeue(events, viewers, users, exc)
                raise

    def _log_backlog(self, backlog: int, events: list, viewers: list) -> None:
        """batch writerが遅れてbufferが積み上がっていることを報告する。writerスレッドは
        ContextVarを継承しない常駐threadなので、相関は自動注入されない。誰の書き込みが
        滞っているかを追えるようsession_idsをctxへ明示する。

        DEBUG時はprogress_interval_seconds()が0を返し毎周期出る(通常はgateで間引く)。"""
        if backlog < get_storage_backlog_warn_rows():
            return
        now = time.monotonic()
        interval = progress_interval_seconds(get_log_progress_interval_seconds())
        if now - self._backlog_logged_at < interval:
            return
        self._backlog_logged_at = now
        logger.warning(
            "storage write buffer is backlogged (%d rows in one batch)", backlog,
            extra={"event": "storage.write_backlogged",
                   "ctx": {"backlog_rows": backlog, "events": len(events),
                           "viewers": len(viewers),
                           "session_ids": _session_ids_of(events, viewers)}},
        )

    def _drop_orphan_rows(self, events: list, viewers: list) -> tuple:
        """buffer済みevent/viewer行のうち、参照先sessionが既にDBから消えている孤児を取り除く。
        両表ともsession_idは各tupleの先頭要素。呼び出し元(_drain)がself._lockを保持している間に
        呼ぶ前提で、判定に使うsessions実在チェックとその後のinsert/commitは同一lock区間内に収まる。"""
        session_ids = {row[0] for row in events} | {row[0] for row in viewers}
        if not session_ids:
            return events, viewers
        placeholders = ",".join("?" * len(session_ids))
        alive = {
            r["id"]
            for r in self._conn.execute(
                f"SELECT id FROM sessions WHERE id IN ({placeholders})",
                tuple(session_ids),
            )
        }
        if len(alive) == len(session_ids):
            return events, viewers
        kept_events = [row for row in events if row[0] in alive]
        kept_viewers = [row for row in viewers if row[0] in alive]
        logger.warning(
            "dropped %d events / %d viewers referencing deleted session(s) %s",
            len(events) - len(kept_events),
            len(viewers) - len(kept_viewers),
            sorted(session_ids - alive),
            extra={"event": "storage.orphan_rows_dropped",
                   "ctx": {"events": len(events) - len(kept_events),
                           "viewers": len(viewers) - len(kept_viewers),
                           "session_ids": sorted(session_ids - alive)}},
        )
        return kept_events, kept_viewers

    def _write_batch_locked(self, events: list, viewers: list, users: list) -> None:
        """高速経路: event/viewerをexecutemanyで一括INSERTし、userを1件ずつupsertする。
        self._lock保持前提。commitは呼び出し元(_drain)が行う。"""
        if events:
            self._conn.executemany(_EVENTS_INSERT_SQL, events)
        if viewers:
            self._conn.executemany(_VIEWERS_INSERT_SQL, viewers)
        self._upsert_users_locked(users)

    def _write_isolating_locked(self, events: list, viewers: list, users: list) -> None:
        """隔離経路: batch INSERTがIntegrityErrorで失敗した後、1行ずつINSERTし直す。
        呼び出し前にrollback済み(部分INSERTは巻き戻し済み)であること。IntegrityErrorの行だけ
        dead-letterへ退避してdropし、残りは確定させる。OperationalError(一時障害)は隔離せず
        上位へ送出して全体再キューさせる。"""
        bad_events = self._insert_rows_isolating(_EVENTS_INSERT_SQL, events)
        bad_viewers = self._insert_rows_isolating(_VIEWERS_INSERT_SQL, viewers)
        self._upsert_users_locked(users)
        if bad_events or bad_viewers:
            quarantine_path = self._quarantine(bad_events, bad_viewers)
            # data喪失(DBには二度と入らない行)なのでerror。dead-letterに退避してあるとはいえ
            # 自動で戻る経路は無く、人が見て手で復旧する以外に回復手段が無い。
            logger.error(
                "quarantined %d event / %d viewer rows that violate a DB constraint; "
                "they are not in the database and need manual recovery",
                len(bad_events), len(bad_viewers),
                extra={"event": "storage.rows_quarantined",
                       "ctx": {"events": len(bad_events), "viewers": len(bad_viewers),
                               "session_ids": _session_ids_of(bad_events, bad_viewers),
                               "path": quarantine_path}},
            )

    def _insert_rows_isolating(self, sql: str, rows: list) -> list:
        """rowsを1行ずつINSERTし、IntegrityErrorの行だけを返して隔離対象にする。
        OperationalError(一時障害)はそのまま送出し、上位で全体rollback+再キューさせる。"""
        bad: list = []
        for row in rows:
            try:
                self._conn.execute(sql, row)
            except sqlite3.IntegrityError:
                bad.append(row)
        return bad

    def _upsert_users_locked(self, users: list) -> None:
        for user, ts, key in users:
            # 1 userのupsert失敗(想定外の型/制約)で同バッチのevent/viewerごと巻き込まないよう
            # 個別に隔離する。userプロフィールはevents側にも冗長に残るため1件のskipは名寄せ精度の
            # 軽微な劣化に留まる。
            try:
                self._upsert_user_locked(user, ts, key=key, use_cache=True)
            except Exception:
                logger.exception("user upsert failed; skipping (key=%s)", key)

    def _quarantine(self, bad_events: list, bad_viewers: list) -> str:
        """制約違反でDBに入らなかった行をdead-letterファイルへ退避する。黙って捨てず、
        後から原因調査・手動復旧できるようにする(生journalとは別の最終防波堤)。退避先pathを
        返し、呼び出し元のlogが「どこを見ればよいか」を示せるようにする。"""
        path = Path(get_log_dir()) / "storage_quarantine.jsonl"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                for row in bad_events:
                    fh.write(json.dumps({"table": "events", "row": row}, ensure_ascii=False, default=str) + "\n")
                for row in bad_viewers:
                    fh.write(json.dumps({"table": "viewer_samples", "row": row}, ensure_ascii=False, default=str) + "\n")
        except Exception:
            # dead-letterにも書けない = 行が完全に失われた。最後の記録手段まで失った状態。
            logger.error(
                "failed to write the storage quarantine dead-letter; %d event / %d viewer rows are lost",
                len(bad_events), len(bad_viewers),
                exc_info=True,
                extra={"event": "storage.quarantine_write_failed",
                       "ctx": {"events": len(bad_events), "viewers": len(bad_viewers),
                               "path": str(path),
                               "session_ids": _session_ids_of(bad_events, bad_viewers),
                               **self._db_space_ctx()}},
            )
        return str(path)

    def _rollback_and_requeue(self, events: list, viewers: list, users: list,
                              exc: BaseException) -> None:
        """一時障害時: rollbackして未確定分をbuffer先頭へ戻し、次のdrain周期で再試行させる。

        levelは障害の性質で分ける。lock/busyは再試行で回復する遅延(warning)だが、disk full /
        I-O / 破損は再試行しても入らず書き込みが恒久的に失われる(error)。両者はsqlite3側では
        同じOperationalErrorなので、exc_typeだけでは永久に切り分けられない。"""
        fatal = self._is_fatal_sqlite(exc)
        session_ids = _session_ids_of(events, viewers)
        logger.log(
            logging.ERROR if fatal else logging.WARNING,
            "storage drain failed; rolling back and re-queueing %d events / %d viewers / %d users",
            len(events), len(viewers), len(users),
            exc_info=True,
            extra={"event": "storage.drain_requeued",
                   "ctx": {"events": len(events), "viewers": len(viewers),
                           "users": len(users), "session_ids": session_ids,
                           "retryable": not fatal, **self._sqlite_error_ctx(exc)}},
        )
        try:
            self._conn.rollback()
        except Exception:
            logger.exception(
                "storage rollback failed",
                extra={"event": "storage.rollback_failed",
                       "ctx": {"session_ids": session_ids}},
            )
        with self._buf_lock:
            self._event_buffer = events + self._event_buffer
            self._viewer_buffer = viewers + self._viewer_buffer
            self._pending_users = users + self._pending_users

    # ----- 耐久journal(取り込み時点でdiskへ追記する最終防波堤) --------------------------
    def _journal_append(self, kind: str, row: tuple) -> None:
        """1 event/viewer行を日次ローテートのNDJSONへ追記する。batched writerとは独立の経路で、
        best-effort(失敗しても本流は止めない)。flush()はOS page cacheまで(fsyncはしない、
        battle_rawと同水準)。プロセスクラッシュは耐えるが電源断は非対象。"""
        if not self._journal_enabled:
            return
        try:
            line = json.dumps({"t": kind, "r": list(row)}, ensure_ascii=False, default=str)
        except Exception:
            logger.exception(
                "failed to serialize journal record (kind=%s)", kind,
                extra={"event": "storage.journal_serialize_failed", "ctx": {"kind": kind}},
            )
            return
        with self._journal_lock:
            try:
                fh = self._journal_handle_locked()
                fh.write(line + "\n")
                fh.flush()
            except Exception:
                logger.exception(
                    "failed to append to event journal",
                    extra={"event": "storage.journal_append_failed",
                           "ctx": {"kind": kind, "journal_day": self._journal_day}},
                )

    def _journal_handle_locked(self):
        day = time.strftime("%Y%m%d", time.localtime())
        if self._journal_fh is not None and self._journal_day == day:
            return self._journal_fh
        if self._journal_fh is not None:
            try:
                self._journal_fh.close()
            except Exception:
                logger.exception("failed to close rotated journal handle")
        journal_dir = Path(get_journal_dir())
        journal_dir.mkdir(parents=True, exist_ok=True)
        self._journal_fh = (journal_dir / f"events-{day}.jsonl").open("a", encoding="utf-8")
        self._journal_day = day
        return self._journal_fh

    def _close_journal(self) -> None:
        with self._journal_lock:
            if self._journal_fh is not None:
                try:
                    self._journal_fh.close()
                except Exception:
                    logger.exception("failed to close journal handle")
                self._journal_fh = None
                self._journal_day = None

    def recover_from_journal(self) -> dict:
        """起動時: journalの各sessionについて、DBに欠けているevent/viewerを復元する。
        batched writerの停滞やクラッシュ・再起動でbuffer滞留分が失われても、取り込み時に
        journalへ残っているので後から埋め戻せる。安全のため:
          - session行が無い(=削除済み/未作成)ならresurrectしない(削除の意思を尊重)。
          - DBがjournalと同数以上なら何もしない。
          - journalがDBを『全項目で上回る』時のみ、当該sessionのevent/viewerをidempotentに
            全置換して復元する(count混在=不整合はskipしてwarn、誤clobber回避)。
        置換後はstats_json/buckets/analytics cacheをeventから再構成する。"""
        summary = {"sessions": 0, "events": 0, "viewers": 0}
        if not self._journal_enabled:
            return summary
        events_by_sid: dict = {}
        viewers_by_sid: dict = {}
        for path in self._journal_files():
            self._read_journal_file(path, events_by_sid, viewers_by_sid)
        session_ids = sorted(set(events_by_sid) | set(viewers_by_sid))
        with self._lock:
            for sid in session_ids:
                j_events = events_by_sid.get(sid, [])
                j_viewers = viewers_by_sid.get(sid, [])
                exists = self._conn.execute(
                    "SELECT bucket_seconds FROM sessions WHERE id = ?", (sid,)
                ).fetchone()
                if exists is None:
                    continue  # 削除済み/未作成: resurrectしない
                db_ev = self._conn.execute(
                    "SELECT COUNT(*) c FROM events WHERE session_id = ?", (sid,)
                ).fetchone()["c"]
                db_vw = self._conn.execute(
                    "SELECT COUNT(*) c FROM viewer_samples WHERE session_id = ?", (sid,)
                ).fetchone()["c"]
                if db_ev >= len(j_events) and db_vw >= len(j_viewers):
                    continue  # DBが同数以上: 復元不要
                if len(j_events) < db_ev or len(j_viewers) < db_vw:
                    # journalがどちらかでDBを下回る=不整合。全置換するとDB側の分を失うのでskip。
                    logger.warning(
                        "journal recovery skipped session %d: inconsistent counts "
                        "(db ev=%d vw=%d, journal ev=%d vw=%d) — needs manual review",
                        sid, db_ev, db_vw, len(j_events), len(j_viewers),
                        extra={"event": "storage.journal_recovery_skipped",
                               "ctx": {"restore_session_id": sid, "db_events": db_ev,
                                       "db_viewers": db_vw, "journal_events": len(j_events),
                                       "journal_viewers": len(j_viewers)}},
                    )
                    continue
                try:
                    self._conn.execute("DELETE FROM events WHERE session_id = ?", (sid,))
                    self._conn.execute("DELETE FROM viewer_samples WHERE session_id = ?", (sid,))
                    if j_events:
                        self._conn.executemany(_EVENTS_INSERT_SQL, j_events)
                    if j_viewers:
                        self._conn.executemany(_VIEWERS_INSERT_SQL, j_viewers)
                    self._recompute_session_stats_locked(sid)
                    self._rebuild_buckets_locked(sid, exists["bucket_seconds"])
                    self._conn.commit()
                    self._refresh_session_analytics_locked(sid)
                    self._conn.commit()
                except Exception:
                    logger.exception(
                        "journal recovery failed for session %d; rolling back", sid,
                        extra={"event": "storage.journal_recovery_failed",
                               "ctx": {"restore_session_id": sid,
                                       "journal_events": len(j_events),
                                       "journal_viewers": len(j_viewers)}},
                    )
                    try:
                        self._conn.rollback()
                    except Exception:
                        logger.exception(
                            "rollback failed during journal recovery",
                            extra={"event": "storage.journal_rollback_failed",
                                   "ctx": {"restore_session_id": sid}},
                        )
                    continue
                summary["sessions"] += 1
                summary["events"] += len(j_events) - db_ev
                summary["viewers"] += len(j_viewers) - db_vw
                logger.info(
                    "journal recovery: session %d restored (+%d events, +%d viewers)",
                    sid, len(j_events) - db_ev, len(j_viewers) - db_vw,
                )
        if summary["sessions"]:
            logger.info("journal recovery complete: %s", summary)
        self._prune_journal()
        return summary

    def _journal_files(self) -> list:
        journal_dir = Path(get_journal_dir())
        if not journal_dir.is_dir():
            return []
        files = list(journal_dir.glob("events-*.jsonl")) + list(journal_dir.glob("events-*.jsonl.gz"))
        return sorted(files)

    def _read_journal_file(self, path: Path, events_by_sid: dict, viewers_by_sid: dict) -> None:
        overlong = 0
        try:
            opener = gzip.open if path.suffix == ".gz" else open
            with opener(path, "rt", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        row = tuple(rec["r"])
                        sid = row[0]
                    except Exception:
                        continue  # 壊れた行はskip(部分書き込み耐性)
                    if rec.get("t") == "e":
                        # journalのrowは位置固定なので、列を足した後は旧journalが短くなる。
                        # 不足分はNULL(=計装前で未計測)で埋める。値の捏造ではなく、当時
                        # 実際に観測していなかったことをそのまま表す。
                        if len(row) < len(_EVENTS_COLUMNS):
                            row = row + (None,) * (len(_EVENTS_COLUMNS) - len(row))
                        elif len(row) > len(_EVENTS_COLUMNS):
                            overlong += 1
                            continue
                        events_by_sid.setdefault(sid, []).append(row)
                    elif rec.get("t") == "v":
                        viewers_by_sid.setdefault(sid, []).append(row)
        except Exception:
            logger.exception(
                "failed to read journal file %s", path,
                extra={"event": "storage.journal_read_failed", "ctx": {"path": str(path)}},
            )
        if overlong:
            # 列数がSCHEMAより多いjournal = 新しいTicTokが書いた記録を古い版が読んでいる。
            # 列の対応が決められないので復元しない(位置ずれのまま入れる方が有害)。
            logger.warning(
                "journal file %s has %d event row(s) wider than the current events "
                "schema (%d columns); those rows are not restorable by this build",
                path, overlong, len(_EVENTS_COLUMNS),
                extra={"event": "storage.journal_row_too_wide",
                       "ctx": {"path": str(path), "rows": overlong,
                               "columns": len(_EVENTS_COLUMNS)}},
            )

    def _recompute_session_stats_locked(self, session_id: int) -> None:
        """restore後、eventからstats_jsonのevent由来項目を再構成する。集計の定義は
        cleanup_stale_sessionsと厳密に一致させる(likes=count合計/gifts=gift_count合計等)。
        viewers系はviewer_samplesのground truthから補う。"""
        agg = self._conn.execute(
            "SELECT COALESCE(SUM(CASE WHEN kind='gift' THEN gift_count ELSE 0 END),0) gifts,"
            " COALESCE(SUM(CASE WHEN kind='gift' THEN diamonds ELSE 0 END),0) diamonds,"
            " COALESCE(SUM(CASE WHEN kind='comment' THEN 1 ELSE 0 END),0) comments,"
            " COALESCE(SUM(CASE WHEN kind='join' THEN 1 ELSE 0 END),0) joins,"
            " COALESCE(SUM(CASE WHEN kind='follow' THEN 1 ELSE 0 END),0) follows,"
            " COALESCE(SUM(CASE WHEN kind='share' THEN 1 ELSE 0 END),0) shares,"
            " COALESCE(SUM(CASE WHEN kind='like' THEN count ELSE 0 END),0) likes,"
            " COALESCE(SUM(CASE WHEN kind='subscribe' THEN 1 ELSE 0 END),0) subscribes,"
            " COALESCE(SUM(CASE WHEN kind='battle' THEN 1 ELSE 0 END),0) battles,"
            " COUNT(*) events_total FROM events WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        vw = self._conn.execute(
            "SELECT MAX(viewers) peak, MAX(total_viewers) total FROM viewer_samples WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        row = self._conn.execute(
            "SELECT stats_json FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        stats = json.loads(row["stats_json"]) if row and row["stats_json"] else {}
        stats.update({
            "likes_total": agg["likes"],
            "comments": agg["comments"],
            "gifts": agg["gifts"],
            "diamonds": agg["diamonds"],
            "follows": agg["follows"],
            "shares": agg["shares"],
            "joins": agg["joins"],
            "subscribes": agg["subscribes"],
            "battles": agg["battles"],
            "events_total": agg["events_total"],
            "recovered": True,
        })
        if vw and vw["peak"] is not None:
            stats["viewers_peak"] = max(stats.get("viewers_peak") or 0, vw["peak"])
        self._conn.execute(
            "UPDATE sessions SET stats_json = ? WHERE id = ?",
            (json.dumps(stats), session_id),
        )

    def _rebuild_buckets_locked(self, session_id: int, bucket_seconds: int) -> None:
        """restore後のeventからtimeline bucketを再構成する。各指標はeventの厳密な集計
        (bucketの定義と一致)、viewersはbucket窓内のviewer_samples最大値(ground truth)。"""
        bs = int(bucket_seconds) or 10
        self._conn.execute("DELETE FROM buckets WHERE session_id = ?", (session_id,))
        self._conn.execute(
            "INSERT INTO buckets (session_id, start, gifts, diamonds, comments, likes, joins, follows, shares, viewers)"
            " SELECT ?, CAST(time / ? AS INTEGER) * ?,"
            " COALESCE(SUM(CASE WHEN kind='gift' THEN gift_count END),0),"
            " COALESCE(SUM(CASE WHEN kind='gift' THEN diamonds END),0),"
            " COALESCE(SUM(CASE WHEN kind='comment' THEN 1 END),0),"
            " COALESCE(SUM(CASE WHEN kind='like' THEN count END),0),"
            " COALESCE(SUM(CASE WHEN kind='join' THEN 1 END),0),"
            " COALESCE(SUM(CASE WHEN kind='follow' THEN 1 END),0),"
            " COALESCE(SUM(CASE WHEN kind='share' THEN 1 END),0), 0"
            " FROM events WHERE session_id = ? GROUP BY CAST(time / ? AS INTEGER)",
            (session_id, bs, bs, session_id, bs),
        )
        self._conn.execute(
            "UPDATE buckets SET viewers = COALESCE((SELECT MAX(vs.viewers) FROM viewer_samples vs"
            " WHERE vs.session_id = buckets.session_id AND vs.time >= buckets.start"
            " AND vs.time < buckets.start + ?), viewers) WHERE session_id = ?",
            (bs, session_id),
        )

    def _prune_journal(self) -> None:
        days = get_journal_retention_days()
        if days <= 0:
            return
        cutoff = time.time() - days * 86400
        removed = 0
        for path in self._journal_files():
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except Exception:
                logger.exception("failed to prune journal file %s", path)
        if removed:
            logger.info("pruned %d journal file(s) older than %d days", removed, days)

    def flush(self) -> None:
        """バッファ済み書き込みを同期的に確定する。未flushのeventを必要とする読み取り
        (comment抽出・export・Battle貢献の再構成・session確定)の直前に呼ぶ。"""
        self._drain()

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
                    "migrated transcripts table: added %s column", name,
                    extra={"event": "storage.schema_migrated",
                           "ctx": {"table": "transcripts", "column": name}},
                )
        columns = [row["name"] for row in self._conn.execute("PRAGMA table_info(events)")]
        if "comment" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN comment TEXT")
            logger.info("migrated events table: added comment column")
        if "count" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN count INTEGER")
            logger.info("migrated events table: added count column")
        if "user_avatar" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN user_avatar TEXT")
            logger.info("migrated events table: added user_avatar column")
        if "gift_image" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN gift_image TEXT")
            logger.info("migrated events table: added gift_image column")
        if "gift_id" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN gift_id INTEGER")
            logger.info("migrated events table: added gift_id column")
        if "user_id" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN user_id TEXT")
            logger.info("migrated events table: added user_id column")
        if "user_fans_level" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN user_fans_level INTEGER")
            logger.info("migrated events table: added user_fans_level column")
        if "user_gifter_badge" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN user_gifter_badge TEXT")
            logger.info("migrated events table: added user_gifter_badge column")
        if "user_member_badge" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN user_member_badge TEXT")
            logger.info("migrated events table: added user_member_badge column")
        if "user_gifter_level" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN user_gifter_level INTEGER")
            logger.info("migrated events table: added user_gifter_level column")
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
                    "migrated events table: added %s column", name,
                    extra={"event": "storage.schema_migrated",
                           "ctx": {"table": "events", "column": name}},
                )
        if "emotes" not in columns:
            # JSON list of TikTok custom emotes carried by a comment (each a stable
            # emote_id + CDN image URL + insertion index) so the burn-in can render
            # them as inline images instead of the raw [shortcode] text.
            self._conn.execute("ALTER TABLE events ADD COLUMN emotes TEXT")
            logger.info("migrated events table: added emotes column")
        user_columns = [row["name"] for row in self._conn.execute("PRAGMA table_info(users)")]
        if "gifter_level" not in user_columns:
            self._conn.execute("ALTER TABLE users ADD COLUMN gifter_level INTEGER NOT NULL DEFAULT 0")
            logger.info("migrated users table: added gifter_level column")
        if "create_time" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN create_time REAL")
            logger.info("migrated events table: added create_time column")
        if "identity_key" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN identity_key TEXT")
            # 既存eventのidentity_keyを不変ID優先(user_id -> unique_id -> nickname)で確定。
            # TRIM込みでPython側の_identity_key(strip)と完全一致させる。
            self._conn.execute(
                "UPDATE events SET identity_key = COALESCE("
                " NULLIF(TRIM(user_id), ''), NULLIF(TRIM(user_unique_id), ''),"
                " TRIM(user_nickname))"
            )
            logger.info("migrated events table: added identity_key column and backfilled")
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
            logger.info("migrated sessions table: added owner_nickname column")
        if "owner_avatar" not in session_columns:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN owner_avatar TEXT")
            logger.info("migrated sessions table: added owner_avatar column")
        if "owner_user_id" not in session_columns:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN owner_user_id TEXT")
            logger.info("migrated sessions table: added owner_user_id column")
        if "league" not in session_columns:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN league TEXT")
            logger.info("migrated sessions table: added league column")
        if "live_create_time" not in session_columns:
            # room_infoが返す配信そのものの開始時刻(TikTok server権威値)。started_atは
            # collectorが接続した時刻でしかないため、収集開始遅延はこの2値の差でしか測れない。
            self._conn.execute("ALTER TABLE sessions ADD COLUMN live_create_time REAL")
            logger.info(
                "migrated sessions table: added live_create_time column",
                extra={"event": "storage.schema_migrated",
                       "ctx": {"table": "sessions", "column": "live_create_time"}},
            )
        if "conn_instrumentation" not in session_columns:
            # 既存行はNULLのまま(=接続系markerの計装より前の収集)。遡って埋めてはいけない。
            self._conn.execute("ALTER TABLE sessions ADD COLUMN conn_instrumentation INTEGER")
            logger.info(
                "migrated sessions table: added conn_instrumentation column",
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
                "migrated recordings table: added protected column",
                extra={"event": "storage.schema_migrated",
                       "ctx": {"table": "recordings", "column": "protected"}},
            )
        if "audio_normalized_at" not in recording_columns:
            # 既存録画はNULL(未適用)から始める。過去のmp4が正規化済みかどうかは、file
            # からは判別できない(loudnormは痕跡を残さない)ので推測で埋めてはいけない。
            self._conn.execute("ALTER TABLE recordings ADD COLUMN audio_normalized_at REAL")
            self._conn.execute("ALTER TABLE recordings ADD COLUMN audio_normalized_lufs REAL")
            logger.info(
                "migrated recordings table: added audio normalization columns",
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
                "migrated recordings table: added reprocessed_at column (%d backfilled)",
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
                "migrated recordings table: added duration_seconds column (%d backfilled)",
                backfilled,
                extra={"event": "storage.schema_migrated",
                       "ctx": {"table": "recordings", "column": "duration_seconds",
                               "backfilled": backfilled}},
            )
        target_columns = [row["name"] for row in self._conn.execute("PRAGMA table_info(monitored_targets)")]
        if "record_video" not in target_columns:
            self._conn.execute(
                "ALTER TABLE monitored_targets ADD COLUMN record_video INTEGER NOT NULL DEFAULT 1"
            )
            logger.info("migrated monitored_targets table: added record_video column")
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
                "migrated bookmarks table: added live_wall/pts_mapped columns",
                extra={"event": "storage.schema_migrated",
                       "ctx": {"table": "bookmarks", "column": "live_wall,pts_mapped"}},
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
                "migrated media_job_queue table: added params_json column",
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
                "migrated media_job_queue table: added not_before/deferred_since columns",
                extra={"event": "storage.schema_migrated",
                       "ctx": {"table": "media_job_queue",
                               "column": "not_before,deferred_since"}},
            )

    def _migrate_ops_events(self) -> None:
        """ops_eventsの列をSCHEMA定義へ揃える。CREATE TABLE IF NOT EXISTSは既存表の列を
        追加しないため、列を足す時はここに1行足すこと(events表と同じ流儀)。lock保持前提。"""
        columns = [row["name"] for row in self._conn.execute("PRAGMA table_info(ops_events)")]
        if "job_id" not in columns:
            # 焼き込みやupscaleはsub-process/worker threadを跨ぐため、Layer1のlog群と
            # ops_eventsを突き合わせる鍵がjob_id以外に無い。
            self._conn.execute("ALTER TABLE ops_events ADD COLUMN job_id TEXT")
            logger.info("migrated ops_events table: added job_id column")
        if "duration_ms" not in columns:
            self._conn.execute("ALTER TABLE ops_events ADD COLUMN duration_ms REAL")
            logger.info("migrated ops_events table: added duration_ms column")

    def _upsert_user_locked(
        self, user: dict, ts: float, key: Optional[str] = None, use_cache: bool = False
    ) -> str:
        """Userの正規化プロフィールをusers表(唯一の真実)に反映する。identity_keyで名寄せし、
        変更されうる属性(名前/@handle/avatar/Lv/badge)は最新の非空値で上書きする。lock保持前提。
        keyが指定された場合はそれを使う(逆引き補完済みeventのidentity_keyを尊重するため)。
        use_cache時は属性が変わらない限り一定時間(TTL)はupsertを間引く(liveの高頻度取り込み用。
        last_seenの更新がTTL分遅れる副作用は許容。backfill等の正確性重視の呼び出しは間引かない)。"""
        # keyが明示されたらそのまま使う。空文字(身元不明)を偽値として拾ってnicknameから
        # 再計算すると、表示用の "(unknown)" で別人が1行へ畳まれる。
        if key is None:
            key = _identity_key(
                user.get("user_id"), user.get("unique_id"), user.get("nickname")
            )
        if not key:
            return ""
        nickname = (user.get("nickname") or "").strip()
        if nickname == "(unknown)":
            nickname = ""
        if use_cache:
            attr = (
                str(user.get("user_id") or ""),
                user.get("unique_id") or "",
                nickname,
                user.get("avatar") or "",
                _to_int(user.get("fans_level")),
                _to_int(user.get("gifter_level")),
                user.get("gifter_badge") or "",
                user.get("member_badge") or "",
            )
            cached = self._user_cache.get(key)
            if (
                cached is not None
                and cached[0] == attr
                and (ts - cached[1]) < _USER_UPSERT_TTL_SECONDS
            ):
                return key
            self._user_cache[key] = (attr, ts)
        self._conn.execute(
            "INSERT INTO users (identity_key, user_id, unique_id, nickname, avatar,"
            " fans_level, gifter_level, gifter_badge, member_badge, first_seen, last_seen)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(identity_key) DO UPDATE SET"
            "  user_id = COALESCE(NULLIF(excluded.user_id, ''), users.user_id),"
            "  unique_id = COALESCE(NULLIF(excluded.unique_id, ''), users.unique_id),"
            "  nickname = COALESCE(NULLIF(excluded.nickname, ''), users.nickname),"
            "  avatar = COALESCE(NULLIF(excluded.avatar, ''), users.avatar),"
            "  fans_level = CASE WHEN excluded.fans_level > 0 THEN excluded.fans_level ELSE users.fans_level END,"
            "  gifter_level = CASE WHEN excluded.gifter_level > 0 THEN excluded.gifter_level ELSE users.gifter_level END,"
            "  gifter_badge = COALESCE(NULLIF(excluded.gifter_badge, ''), users.gifter_badge),"
            "  member_badge = COALESCE(NULLIF(excluded.member_badge, ''), users.member_badge),"
            "  last_seen = excluded.last_seen",
            (
                key,
                str(user.get("user_id") or ""),
                user.get("unique_id") or "",
                nickname,
                user.get("avatar") or "",
                _to_int(user.get("fans_level")),
                _to_int(user.get("gifter_level")),
                user.get("gifter_badge") or "",
                user.get("member_badge") or "",
                ts,
                ts,
            ),
        )
        return key

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
            logger.info("owner_user_id backfill: no owner numeric id recoverable")
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
            "owner_user_id backfill: %d handles resolved, %d sessions filled, %d battles repaired",
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
            "reverse-linked %d handle-only events to numeric user_id (%d unambiguous handles)",
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
        logger.info("backfilled users table from %d events", count)

    def close(self) -> None:
        with self._flush_cond:
            self._closed = True
            self._flush_cond.notify()
        self._writer.join(timeout=5.0)
        # 最終drainが例外を投げてもconn.close()(WAL checkpoint)は必ず走らせる。
        try:
            self._drain()
        except Exception as exc:
            logger.error(
                "final storage drain on close failed; buffered rows stay only in the journal",
                exc_info=True,
                extra={"event": "storage.final_drain_failed",
                       "ctx": self._sqlite_error_ctx(exc)},
            )
        self._close_journal()
        # ops_eventsの書き込み失敗は本流を止めないので、ここで累計を必ず1行出す。閾値を設けて
        # 「少なければ黙る」設計にすると、失敗が数件で終わった時に1行も残らず穴になる。
        with self._ops_fail_lock:
            failures = self._ops_write_failures
        logger.log(
            logging.WARNING if failures else logging.INFO,
            "storage closed (ops event write failures: %d)", failures,
            extra={"event": "storage.closed",
                   "ctx": {"ops_write_failures": failures, **self._db_space_ctx()}},
        )
        with self._lock:
            self._conn.close()

    def cleanup_stale_sessions(self) -> int:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM sessions WHERE status IN ('connecting', 'connected', 'reconnecting')"
            ).fetchall()
            for row in rows:
                session_id = row["id"]
                agg = self._conn.execute(
                    "SELECT MAX(time) AS last_time,"
                    " COALESCE(SUM(CASE WHEN kind = 'gift' THEN gift_count ELSE 0 END), 0) AS gifts,"
                    " COALESCE(SUM(CASE WHEN kind = 'gift' THEN diamonds ELSE 0 END), 0) AS diamonds,"
                    " COALESCE(SUM(CASE WHEN kind = 'comment' THEN 1 ELSE 0 END), 0) AS comments,"
                    " COALESCE(SUM(CASE WHEN kind = 'join' THEN 1 ELSE 0 END), 0) AS joins,"
                    " COALESCE(SUM(CASE WHEN kind = 'follow' THEN 1 ELSE 0 END), 0) AS follows,"
                    " COALESCE(SUM(CASE WHEN kind = 'share' THEN 1 ELSE 0 END), 0) AS shares,"
                    " COALESCE(SUM(CASE WHEN kind = 'like' THEN count ELSE 0 END), 0) AS likes,"
                    " COALESCE(SUM(CASE WHEN kind = 'subscribe' THEN 1 ELSE 0 END), 0) AS subscribes,"
                    " COALESCE(SUM(CASE WHEN kind = 'battle' THEN 1 ELSE 0 END), 0) AS battles,"
                    " COUNT(*) AS events_total"
                    " FROM events WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                stats = {
                    "viewers": 0,
                    "total_viewers": 0,
                    "anonymous": 0,
                    "likes_total": agg["likes"],
                    "comments": agg["comments"],
                    "gifts": agg["gifts"],
                    "diamonds": agg["diamonds"],
                    "follows": agg["follows"],
                    "shares": agg["shares"],
                    "joins": agg["joins"],
                    "subscribes": agg["subscribes"],
                    "battles": agg["battles"],
                    "battle_points": 0,
                    "events_total": agg["events_total"],
                    "connected_at": None,
                    "recovered": True,
                }
                self._conn.execute(
                    "UPDATE sessions SET status = 'disconnected', ended_at = ?, stats_json = ? WHERE id = ?",
                    (agg["last_time"] or time.time(), json.dumps(stats), session_id),
                )
            self._conn.commit()
        if rows:
            logger.warning("recovered %d stale sessions from previous run", len(rows))
        return len(rows)

    def create_session(self, unique_id: str, bucket_seconds: int) -> int:
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO sessions (unique_id, status, started_at, bucket_seconds,"
                " conn_instrumentation) VALUES (?, ?, ?, ?, ?)",
                (unique_id, "connecting", time.time(), bucket_seconds,
                 CONN_INSTRUMENTATION_VERSION),
            )
            self._conn.commit()
            return cursor.lastrowid

    def update_session(self, session_id: int, status: str, room_id: Optional[int] = None) -> None:
        with self._lock:
            if room_id is not None:
                self._conn.execute(
                    "UPDATE sessions SET status = ?, room_id = ? WHERE id = ?",
                    (status, str(room_id), session_id),
                )
            else:
                self._conn.execute(
                    "UPDATE sessions SET status = ? WHERE id = ?", (status, session_id)
                )
            self._conn.commit()

    def update_session_owner(
        self, session_id: int, nickname: str, avatar: str, user_id: str = ""
    ) -> None:
        owner_id = str(user_id or "") if _valid_owner_id(user_id) else ""
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET owner_nickname = ?, owner_avatar = ?,"
                " owner_user_id = COALESCE(NULLIF(?, ''), owner_user_id) WHERE id = ?",
                (nickname or None, avatar or None, owner_id, session_id),
            )
            # 数値owner IDが取れたら、同一@handleの過去sessionで未設定の分にも伝播させる。
            if owner_id:
                row = self._conn.execute(
                    "SELECT unique_id FROM sessions WHERE id = ?", (session_id,)
                ).fetchone()
                if row:
                    self._conn.execute(
                        "UPDATE sessions SET owner_user_id = ?"
                        " WHERE unique_id = ? AND (owner_user_id IS NULL OR owner_user_id = '')",
                        (owner_id, row["unique_id"]),
                    )
            self._conn.commit()

    def update_session_league(self, session_id: int, league: str) -> None:
        """配信者リーグ帯(例:A1/B3)をsessionへ記録する。デイリー変動を配信単位で残すため、
        接続時に取得したその時点の値をそのsessionにだけ保存する(過去sessionへは伝播しない)。
        空値では上書きしない(捏造・消去を避ける)。"""
        if not league:
            return
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET league = ? WHERE id = ?", (league, session_id)
            )
            self._conn.commit()

    def add_event(self, session_id: int, entry: dict) -> None:
        user = entry.get("user") or {}
        # collectorが決めたidentity_keyをそのまま使う(空文字=身元不明も尊重する)。ここで
        # nicknameから再計算すると、表示用の "(unknown)" がkeyになり別人のeventが1
        # identityへ畳まれる。keyを持たないdict(逆引き補完前のentry等)だけ計算する。
        if "identity_key" in user:
            identity_key = user["identity_key"]
        else:
            identity_key = _identity_key(
                user.get("user_id"), user.get("unique_id"), user.get("nickname")
            )
        params = (
            session_id,
            entry["time"],
            entry.get("create_time"),
            entry["kind"],
            user.get("user_id"),
            user.get("unique_id"),
            user.get("nickname"),
            identity_key,
            user.get("avatar"),
            entry.get("text"),
            entry.get("comment"),
            entry.get("gift_name"),
            entry.get("repeat_count"),
            entry.get("diamonds"),
            entry.get("count"),
            entry.get("gift_image"),
            entry.get("gift_id"),
            user.get("fans_level") or 0,
            user.get("gifter_level") or 0,
            user.get("gifter_badge") or "",
            user.get("member_badge") or "",
            entry.get("emotes"),
            entry.get("enter_source"),
            entry.get("enter_type"),
            entry.get("enter_reason"),
            entry.get("follow_status"),
            entry.get("follower_count"),
            entry.get("is_subscriber"),
            entry.get("is_moderator"),
            entry.get("is_gift_giver"),
            entry.get("share_type"),
            entry.get("share_target"),
            entry.get("content_language"),
            entry.get("comment_tag"),
        )
        # DB bufferへ積む前に耐久journalへ追記する。プロセスがこの直後に死んでも、eventは
        # diskに残り起動時recoverで復元できる(paramsはeventsの行tupleそのもの)。
        self._journal_append("e", params)
        with self._buf_lock:
            self._event_buffer.append(params)
            if identity_key:
                self._pending_users.append((user, entry["time"], identity_key))
            if len(self._event_buffer) + len(self._viewer_buffer) >= _WRITE_BATCH_SIZE:
                self._flush_cond.notify()

    def add_viewer_sample(
        self,
        session_id: int,
        ts: float,
        create_time: Optional[float],
        viewers: int,
        total_viewers: Optional[int],
        anonymous: Optional[int],
    ) -> None:
        """RoomUserSeqの同接系列をnative cadenceで永続化する。退室eventは配信側が出さない
        ため、net流入(Δ同接)はこの系列でしか測れない。bucketの10s丸め・timeline上限では
        長時間配信の系列が欠落するので、生sampleを別表に残す。"""
        row = (session_id, ts, create_time, viewers, total_viewers, anonymous)
        self._journal_append("v", row)
        with self._buf_lock:
            self._viewer_buffer.append(row)
            if len(self._event_buffer) + len(self._viewer_buffer) >= _WRITE_BATCH_SIZE:
                self._flush_cond.notify()

    def add_contributor_samples(
        self, session_id: int, ts: float, create_time: Optional[float], rows: list
    ) -> None:
        """RoomUserSeqの上位貢献者snapshotを1 messageぶんまとめて保存する。rowsは
        {rank, score, user{user_id, unique_id, nickname, avatar}} のlist。
        呼び出し側が間引き済みである前提の低頻度書き込みなので、event/viewerのbatch writerは
        通さず同期で書く(writerのbuffer/journal形式を増やさない)。

        identity_keyは_identity_key(不変user_id -> unique_id -> nickname)で採るが、users表への
        upsertは行わない。この経路のuserにはLv/badgeが載っておらず、upsertすると空の属性で
        既存profileを触りにいく余地を作るだけだからである。"""
        if not rows:
            return
        params = []
        for row in rows:
            user = row.get("user") or {}
            params.append(
                (
                    session_id,
                    ts,
                    create_time,
                    row.get("rank"),
                    row.get("score"),
                    _identity_key(
                        user.get("user_id"), user.get("unique_id"), user.get("nickname")
                    )
                    or None,
                    user.get("user_id") or None,
                    user.get("unique_id") or None,
                    user.get("nickname") or None,
                    user.get("avatar") or None,
                )
            )
        with self._lock:
            self._conn.executemany(
                "INSERT INTO contributor_samples (session_id, time, create_time, rank, score,"
                " identity_key, user_id, user_unique_id, user_nickname, user_avatar)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                params,
            )
            self._conn.commit()

    def add_follower_sample(
        self, session_id: int, ts: float, create_time: Optional[float], follower_count: int
    ) -> None:
        """FollowEventが運ぶ配信者のfollower総数を1点記録する。値が動いた時だけ呼ぶ想定。"""
        with self._lock:
            self._conn.execute(
                "INSERT INTO follower_samples (session_id, time, create_time, follower_count)"
                " VALUES (?, ?, ?, ?)",
                (session_id, ts, create_time, follower_count),
            )
            self._conn.commit()

    def finalize_session(
        self, session_id: int, status: str, stats: dict, timeline: list, markers: list
    ) -> None:
        self.flush()
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET status = ?, ended_at = ?, stats_json = ? WHERE id = ?",
                (status, time.time(), json.dumps(stats), session_id),
            )
            self._conn.execute("DELETE FROM buckets WHERE session_id = ?", (session_id,))
            self._conn.executemany(
                "INSERT INTO buckets (session_id, start, gifts, diamonds, comments, likes, joins, follows, shares, viewers)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        session_id,
                        b["start"],
                        b["gifts"],
                        b["diamonds"],
                        b["comments"],
                        b["likes"],
                        b["joins"],
                        b["follows"],
                        b["shares"],
                        b["viewers"],
                    )
                    for b in timeline
                ],
            )
            # markerだけは追記(全置換ではない)。collector側のdequeが上限を超えたsessionでは
            # 途中checkpointで残した古いmarkerがメモリ上に無いため、全置換すると確定時に
            # それらを消してしまう。
            self._append_markers_locked(session_id, markers)
            self._conn.commit()
            # 確定したsessionの全体解析payloadをここで1回だけ計算して永続化する。
            self._refresh_session_analytics_locked(session_id)
        logger.info("session finalized: id=%d status=%s", session_id, status)

    def _latest_owners(self) -> dict:
        owners = self._conn.execute(
            "SELECT unique_id,"
            " (SELECT owner_avatar FROM sessions s2 WHERE s2.unique_id = s.unique_id"
            "  AND owner_avatar IS NOT NULL AND owner_avatar != ''"
            "  ORDER BY started_at DESC LIMIT 1) AS avatar,"
            " (SELECT owner_nickname FROM sessions s3 WHERE s3.unique_id = s.unique_id"
            "  AND owner_nickname IS NOT NULL AND owner_nickname != ''"
            "  ORDER BY started_at DESC LIMIT 1) AS nickname"
            " FROM sessions s GROUP BY unique_id"
        ).fetchall()
        return {row["unique_id"]: row for row in owners}

    def _latest_owner_handles_locked(self) -> dict:
        """owner group key(owner_user_id優先) -> 最新sessionの表示@handle。相関subqueryを
        グループ毎に評価する代わりに1回の走査で決定する(streamer_index/dashboard共通)。
        lock保持前提。"""
        rows = self._conn.execute(
            "SELECT COALESCE(NULLIF(owner_user_id, ''), unique_id) AS okey, unique_id"
            " FROM sessions ORDER BY started_at DESC"
        ).fetchall()
        out: dict = {}
        for row in rows:
            if row["okey"] not in out:
                out[row["okey"]] = row["unique_id"]
        return out

    def latest_owner(self, unique_id: str) -> dict:
        """配信者(unique_id)の最後に判明したowner identity(avatar/nickname)を返す。
        live未接続でもキャッシュ済みのアイコン/表示名を出すために使う。identity系は
        point-in-timeが無ければ永続sessionへfallbackする方針。avatarとnicknameは
        それぞれ最新の非空値を独立に採用する。見つからなければ空文字。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT"
                " (SELECT owner_avatar FROM sessions WHERE unique_id = ?"
                "  AND owner_avatar IS NOT NULL AND owner_avatar != ''"
                "  ORDER BY started_at DESC LIMIT 1) AS avatar,"
                " (SELECT owner_nickname FROM sessions WHERE unique_id = ?"
                "  AND owner_nickname IS NOT NULL AND owner_nickname != ''"
                "  ORDER BY started_at DESC LIMIT 1) AS nickname",
                (unique_id, unique_id),
            ).fetchone()
        return {
            "avatar": (row["avatar"] if row else "") or "",
            "nickname": (row["nickname"] if row else "") or "",
        }

    def _owner_handles_locked(self, unique_id: str) -> list:
        """同一配信者(不変owner数値ID)に属する全@handleを返す。owner_user_idが判れば
        それを共有する全handleを、無ければ入力handle単体を返す。@handle変更が起きても
        配信者単位で履歴を束ねられる。lock保持前提。"""
        row = self._conn.execute(
            "SELECT owner_user_id FROM sessions"
            " WHERE unique_id = ? AND owner_user_id IS NOT NULL AND owner_user_id != ''"
            " LIMIT 1",
            (unique_id,),
        ).fetchone()
        if row and row["owner_user_id"]:
            rows = self._conn.execute(
                "SELECT DISTINCT unique_id FROM sessions WHERE owner_user_id = ?",
                (row["owner_user_id"],),
            ).fetchall()
            handles = [r["unique_id"] for r in rows]
            if handles:
                return handles
        return [unique_id]

    def _fill_owner(self, item: dict) -> dict:
        """履歴の各sessionは、そのsession自身が確定したowner identityで表示する。
        新配信で配信者が改名/アイコン変更しても過去sessionへは遡及させない方針のため、
        空でも最新配信のidentityは借りない。nicknameが空なら@handle(unique_id)で代替する。"""
        if not item.get("owner_nickname"):
            item["owner_nickname"] = item.get("unique_id") or ""
        if not item.get("owner_avatar"):
            item["owner_avatar"] = ""
        return item

    def list_sessions(self, limit: int) -> list:
        # limit<=0は全件(履歴のfilter/検索が最新N件に頭打ちにならないよう)。SQLiteはLIMIT -1で無制限。
        sql_limit = limit if limit and limit > 0 else -1
        with self._lock:
            rows = self._conn.execute(
                "SELECT s.*,"
                " (SELECT COUNT(*) FROM recordings r WHERE r.session_id = s.id"
                "  AND r.status IN ('completed', 'interrupted')) AS recording_count,"
                " (SELECT MAX(viewers) FROM buckets b WHERE b.session_id = s.id)"
                "  AS bucket_peak_viewers"
                " FROM sessions s ORDER BY s.started_at DESC LIMIT ?",
                (sql_limit,),
            ).fetchall()
        return [self._fill_owner(_session_row_to_dict(row)) for row in rows]

    def get_session(self, session_id: int) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT s.*,"
                " (SELECT MAX(viewers) FROM buckets b WHERE b.session_id = s.id)"
                "  AS bucket_peak_viewers"
                " FROM sessions s WHERE s.id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return None
        return self._fill_owner(_session_row_to_dict(row))

    def set_note(self, session_id: int, note: str) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE sessions SET note = ? WHERE id = ?", (note, session_id)
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def delete_session(self, session_id: int) -> bool:
        # sessionを消すと、まだwriterがdrainしていない同sessionのbuffer済みevent/viewerは
        # 参照先を失う(events/viewer_samplesはsessions(id)へFK)。そのままdrainすると
        # FK違反でbatchごと失敗し、_drainの再キューで永久に詰まる(poison-pill)。
        # 削除に先立ちbufferから該当sessionの行を取り除き、孤児を作らない。
        with self._buf_lock:
            self._event_buffer = [e for e in self._event_buffer if e[0] != session_id]
            self._viewer_buffer = [v for v in self._viewer_buffer if v[0] != session_id]
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM sessions WHERE id = ?", (session_id,)
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def find_restricted_session(self, unique_id: str, room_id) -> Optional[int]:
        """同一roomについて既に書かれている制限sessionのidを返す(無ければNone)。
        制限holdは再確認のたびにconnectを撃ち直すため、1つの配信で制限行が何本も
        並びうる。DBに問い合わせて畳み込むことで、collector側の状態に依存せず
        (プロセス再起動を跨いでも)1 room = 1行を保てる。"""
        if room_id is None:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM sessions"
                " WHERE unique_id = ? AND room_id = ? AND status = ?"
                " ORDER BY started_at LIMIT 1",
                (unique_id, str(room_id), SESSION_STATUS_RESTRICTED),
            ).fetchone()
        return row["id"] if row is not None else None

    def extend_session_end(self, session_id: int) -> None:
        """sessionの終了時刻を現在時刻まで延ばす。畳み込んだ制限行が「最後にいつまで
        録画できない状態だったか」を示すようにするため。"""
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET ended_at = ? WHERE id = ?", (time.time(), session_id)
            )
            self._conn.commit()

    def session_ids_for_users(self, unique_ids: list) -> list:
        """指定配信者に属する全session idを返す。owner-identityで@handle変更を辿るため、
        改名を跨いでもその配信者の履歴を漏れなく対象にできる(ユーザー単位の一括削除用)。"""
        with self._lock:
            handles: set = set()
            for unique_id in unique_ids:
                handles.update(self._owner_handles_locked(unique_id))
            if not handles:
                return []
            placeholders = ",".join("?" * len(handles))
            rows = self._conn.execute(
                f"SELECT id FROM sessions WHERE unique_id IN ({placeholders}) ORDER BY id",
                tuple(handles),
            ).fetchall()
        return [row["id"] for row in rows]

    def session_timeline(self, session_id: int) -> dict:
        with self._lock:
            buckets = self._conn.execute(
                "SELECT start, gifts, diamonds, comments, likes, joins, follows, shares, viewers"
                " FROM buckets WHERE session_id = ? ORDER BY start",
                (session_id,),
            ).fetchall()
            markers = self._conn.execute(
                "SELECT time, kind, label FROM markers WHERE session_id = ? ORDER BY time",
                (session_id,),
            ).fetchall()
        return {
            "buckets": [dict(b) for b in buckets],
            "markers": [dict(m) for m in markers],
        }

    def session_summary(self, session_id: int) -> dict:
        with self._lock:
            # 表示属性はその時(このSession)のsnapshotを優先し、欠けていればusers表(最新)へ
            # fallbackする。名寄せ(identity_key)と切り離すことで過去の見え方を保持する。
            user_rows = self._conn.execute(
                "SELECT e.identity_key AS key,"
                " COALESCE(NULLIF(MAX(e.user_id), ''), u.user_id) AS user_id,"
                " COALESCE(NULLIF(MAX(e.user_unique_id), ''), u.unique_id) AS unique_id,"
                " COALESCE(NULLIF(MAX(e.user_nickname), ''), u.nickname) AS nickname,"
                " COALESCE(NULLIF(MAX(e.user_avatar), ''), u.avatar) AS avatar,"
                " SUM(e.gift_count) AS gifts, SUM(e.diamonds) AS diamonds,"
                # Lv/badgeはその時点で変動する属性。users表(最新)へfallbackすると過去の値を
                # 捏造するため、このSessionのevent(point-in-time)のみ。無ければ非表示。
                " NULLIF(MAX(e.user_fans_level), 0) AS fans_level,"
                " NULLIF(MAX(e.user_gifter_level), 0) AS gifter_level,"
                " NULLIF(MAX(e.user_gifter_badge), '') AS gifter_badge,"
                " NULLIF(MAX(e.user_member_badge), '') AS member_badge"
                " FROM events e LEFT JOIN users u ON u.identity_key = e.identity_key"
                " WHERE e.session_id = ? AND e.kind = 'gift'"
                " GROUP BY e.identity_key ORDER BY diamonds DESC, gifts DESC LIMIT 100",
                (session_id,),
            ).fetchall()
            item_rows = self._conn.execute(
                "SELECT identity_key AS key,"
                " gift_name, SUM(gift_count) AS count, SUM(diamonds) AS diamonds"
                " FROM events WHERE session_id = ? AND kind = 'gift'"
                " GROUP BY identity_key, gift_name",
                (session_id,),
            ).fetchall()
            gift_rows = self._conn.execute(
                "SELECT gift_name AS name, SUM(gift_count) AS count, SUM(diamonds) AS diamonds,"
                " MAX(CASE WHEN gift_count > 0 THEN diamonds / gift_count ELSE 0 END) AS diamonds_each"
                " FROM events WHERE session_id = ? AND kind = 'gift'"
                " GROUP BY gift_name ORDER BY diamonds DESC, count DESC LIMIT 100",
                (session_id,),
            ).fetchall()
        items_by_user: dict = {}
        for row in item_rows:
            items_by_user.setdefault(row["key"], {})[row["gift_name"]] = {
                "count": row["count"] or 0,
                "diamonds": row["diamonds"] or 0,
            }
        users = []
        for row in user_rows:
            users.append(
                {
                    "user_id": row["user_id"] or "",
                    "unique_id": row["unique_id"] or "",
                    "nickname": row["nickname"] or "(unknown)",
                    "avatar": row["avatar"] or "",
                    "gifts": row["gifts"] or 0,
                    "diamonds": row["diamonds"] or 0,
                    "fans_level": row["fans_level"] or 0,
                    "gifter_level": row["gifter_level"] or 0,
                    "gifter_badge": row["gifter_badge"] or "",
                    "member_badge": row["member_badge"] or "",
                    "items": items_by_user.get(row["key"], {}),
                }
            )
        return {"users": users, "gifts": [dict(g) for g in gift_rows]}

    def session_comments(self, session_id: int, limit: int) -> list:
        """Most recent comment texts for a session, for AI analysis. The text lives in
        the `comment` column (add_event stores entry['comment']); fall back to `text`.

        本文が空の行はSQL側で落とす。Python側で落とすとLIMITが空行込みで先に効き、
        直近が空commentばかりのsessionで要求件数より少なく(最悪0件)返ってしまう。
        「空」の定義はNULLと空文字だけ(空白のみの本文は落とさない)。"""
        self.flush()
        with self._lock:
            rows = self._conn.execute(
                "SELECT comment, text FROM events"
                " WHERE session_id = ? AND kind = 'comment'"
                " AND COALESCE(NULLIF(comment, ''), NULLIF(text, '')) IS NOT NULL"
                " ORDER BY time DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [(row["comment"] or row["text"] or "") for row in rows]

    def iter_events(self, session_id: int, start: float | None = None, end: float | None = None) -> list:
        """Events for a session, ordered by arrival time. When start/end (wall-clock
        seconds, the same axis as recorder.started_at) are given, only events inside
        [start, end] are returned so a single recording of a multi-recording session
        is fed only its own events, not the whole session's."""
        self.flush()
        sql = (
            "SELECT time, create_time, kind, user_unique_id, user_nickname, text, comment, gift_name, gift_count, diamonds, count, gift_image, gift_id, emotes"
            " FROM events WHERE session_id = ?"
        )
        params: list = [session_id]
        if start is not None:
            sql += " AND time >= ?"
            params.append(start)
        if end is not None:
            sql += " AND time <= ?"
            params.append(end)
        sql += " ORDER BY time"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def _append_markers_locked(self, session_id: int, markers: list) -> int:
        """未保存のmarkerだけをINSERTする(既存行は消さない)。DELETE→INSERTの全置換に
        してはいけない: collector側のmarkerは容量上限つきdequeで保持されるため、上限を
        超えたsessionでは「既に永続化した古いmarkerがメモリ上から消えている」状態が正常に
        起きる。そこで全置換すると、既に残した行をcheckpointが消し直してしまう。
        重複判定keyは(time, kind, label)。timeはepoch秒のfloatで、同一kind・同一labelが
        同一floatに乗ることは実質無いため、これで冪等になる。"""
        rows = self._conn.execute(
            "SELECT time, kind, label FROM markers WHERE session_id = ?", (session_id,)
        ).fetchall()
        stored = {(r["time"], r["kind"], r["label"]) for r in rows}
        fresh = [
            (session_id, m["time"], m["kind"], m["label"])
            for m in markers
            if (m["time"], m["kind"], m["label"]) not in stored
        ]
        if fresh:
            self._conn.executemany(
                "INSERT INTO markers (session_id, time, kind, label) VALUES (?, ?, ?, ?)",
                fresh,
            )
        return len(fresh)

    def append_markers(self, session_id: int, markers: list) -> None:
        """markerを中間永続化する。finalize_sessionと同じ追記方式なので、途中checkpointと
        最終確定のどちらが先でも結果は同じになる。非graceful終了で接続系marker(切断・再接続)
        やBattle/Collab markerが全損すると復元する手段が他に無いため、finalizeを待たずに残す。"""
        with self._lock:
            self._append_markers_locked(session_id, markers)
            self._conn.commit()

    def set_session_live_create_time(self, session_id: int, live_create_time: float) -> None:
        """room_infoが返す配信開始時刻(epoch秒)をsessionへ確定する。取得できない場合は
        呼ばない(NULLのまま=計測不能)。"""
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET live_create_time = ? WHERE id = ?",
                (live_create_time, session_id),
            )
            self._conn.commit()

    def save_battles(self, session_id: int, battles: list) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM battles WHERE session_id = ?", (session_id,))
            self._conn.executemany(
                "INSERT INTO battles (session_id, battle_id, data_json) VALUES (?, ?, ?)",
                [
                    (session_id, b.get("battle_id", 0), json.dumps(b, ensure_ascii=False))
                    for b in battles
                ],
            )
            self._conn.commit()

    def save_envelopes(self, session_id: int, rows: list) -> None:
        """宝箱/Portalをsession単位で全置換する。battles/collab_windowsと同じ冪等な作法。

        collector側が envelope_id で重複を畳んだ結果を渡す前提。ここでUNIQUE制約を張らない
        のは、envelope_idがNULLで届く回(HIDE通知など)があり、NULL同士は制約で畳めないため
        (畳めない回を弾くと実測が欠ける)。
        """
        with self._lock:
            self._conn.execute("DELETE FROM envelopes WHERE session_id = ?", (session_id,))
            self._conn.executemany(
                "INSERT INTO envelopes (session_id, kind, envelope_id, time, create_time,"
                " business_type, diamond_count, people_count, trans_count, unpack_at,"
                " sender_user_id, sender_unique_id, data_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        session_id, r.get("kind") or "envelope", r.get("envelope_id"),
                        r.get("time"), r.get("create_time"), r.get("business_type"),
                        r.get("diamond_count"), r.get("people_count"), r.get("trans_count"),
                        r.get("unpack_at"), r.get("sender_user_id"),
                        r.get("sender_unique_id"),
                        json.dumps(r.get("data") or {}, ensure_ascii=False),
                    )
                    for r in rows
                ],
            )
            self._conn.commit()

    def session_envelopes(self, session_id: int) -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT kind, envelope_id, time, create_time, business_type,"
                " diamond_count, people_count, trans_count, unpack_at,"
                " sender_user_id, sender_unique_id, data_json"
                " FROM envelopes WHERE session_id = ? ORDER BY time",
                (session_id,),
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["data"] = json.loads(item.pop("data_json") or "{}")
            out.append(item)
        return out

    def save_collab_windows(self, session_id: int, windows: list) -> None:
        """コラボ(非BattleのLinkMic)接続窓を保存。Battle窓の差し引きは分析側で行う。"""
        with self._lock:
            self._conn.execute("DELETE FROM collab_windows WHERE session_id = ?", (session_id,))
            self._conn.executemany(
                "INSERT INTO collab_windows (session_id, channel_id, start, end, guests_max, data_json)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        session_id,
                        str(w.get("channel_id") or ""),
                        w["start"],
                        w.get("end"),
                        w.get("guests_max", 0) or 0,
                        json.dumps(w, ensure_ascii=False),
                    )
                    for w in windows
                    if w.get("start") is not None
                ],
            )
            self._conn.commit()

    def collab_windows_for_session(self, session_id: int) -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT channel_id, start, end, guests_max FROM collab_windows"
                " WHERE session_id = ? ORDER BY start",
                (session_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def battle_gift_contributions(self, session_id: int, start_time, end_time) -> list:
        """Battleの時間窓内に自陣(監視配信者)へ送られたGiftをUser単位で集計する。
        TikTokのarmies eventは相手陣の合計スコアのみで、誰がいくら実弾を送ったかの
        User単位内訳(user_armies/diamond_score)を欠くことが多い。実弾の出どころは
        確実に記録しているGift eventから復元する。相手陣のGiftは別Roomのため取得不可。
        窓境界(battle_setting.*_ms)はTikTokサーバ時刻なので、eventもサーバ時刻の
        create_timeで突合する(欠落eventのみ受信時刻timeで代用)。"""
        upper = end_time if end_time is not None else 9_999_999_999
        self.flush()
        with self._lock:
            rows = self._conn.execute(
                "SELECT e.identity_key AS key,"
                " COALESCE(NULLIF(MAX(e.user_id), ''), u.user_id) AS user_id,"
                " COALESCE(NULLIF(MAX(e.user_unique_id), ''), u.unique_id) AS unique_id,"
                " COALESCE(NULLIF(MAX(e.user_nickname), ''), u.nickname) AS nickname,"
                " COALESCE(NULLIF(MAX(e.user_avatar), ''), u.avatar) AS avatar, SUM(e.diamonds) AS diamonds,"
                " SUM(e.gift_count) AS gifts,"
                # Lv/badgeはその時点で変動する属性。users表(最新)へfallbackすると過去の値を
                # 捏造するため、このSessionのevent(point-in-time)のみ。無ければ非表示。
                " NULLIF(MAX(e.user_fans_level), 0) AS fans_level,"
                " NULLIF(MAX(e.user_gifter_level), 0) AS gifter_level,"
                " NULLIF(MAX(e.user_gifter_badge), '') AS gifter_badge,"
                " NULLIF(MAX(e.user_member_badge), '') AS member_badge"
                " FROM events e LEFT JOIN users u ON u.identity_key = e.identity_key"
                " WHERE e.session_id = ? AND e.kind = 'gift'"
                " AND COALESCE(e.create_time, e.time) >= ? AND COALESCE(e.create_time, e.time) <= ?"
                " GROUP BY e.identity_key HAVING SUM(e.diamonds) > 0 ORDER BY diamonds DESC",
                (session_id, start_time or 0, upper),
            ).fetchall()
        return [
            {
                # identity_key/giftsは配信者profileのBattle gifter集計が使う。Battle card側は
                # 参照しない(この関数を貢献集計の単一の入口にするために持たせている)。
                "key": row["key"],
                "user_id": row["user_id"] or "",
                "unique_id": row["unique_id"] or "",
                "nickname": row["nickname"] or "(unknown)",
                "avatar": row["avatar"] or "",
                "side": "own",
                "diamonds": row["diamonds"] or 0,
                "gifts": row["gifts"] or 0,
                "fans_level": row["fans_level"] or 0,
                "gifter_level": row["gifter_level"] or 0,
                "gifter_badge": row["gifter_badge"] or "",
                "member_badge": row["member_badge"] or "",
            }
            for row in rows
        ]

    def apply_battle_gift_contributions(self, session_id: int, battles: list) -> list:
        """各Battleの監視配信者(自陣host)の貢献をGift eventから再構成して差し替える。
        相手陣(side!=own)と、チーム戦の味方host(別Roomのためarmies由来)の貢献はそのまま
        残す。host_idで宛先配信者を保持し、配信者別の集計に使う。live snapshot / history
        両方で同じ集計を使う。"""
        starts = sorted(
            b["start_time"] for b in battles if b.get("start_time") is not None
        )
        fallback_duration = gift_window_fallback_duration(battles)
        for battle in battles:
            own_host = next(
                (p.get("user_id") for p in battle.get("participants", []) if p.get("is_own")),
                None,
            )
            start = battle.get("start_time")
            end = gift_window_end(battle, starts, fallback_duration)
            # 終了済みBattleは窓が確定しているので貢献集計をキャッシュし、再集計は進行中のみ。
            bid = battle.get("battle_id")
            cache_key = (
                (session_id, bid, start, end)
                if (not battle.get("ongoing") and end is not None and bid)
                else None
            )
            if cache_key is not None and cache_key in self._battle_contrib_cache:
                gift = self._battle_contrib_cache[cache_key]
            else:
                gift = self.battle_gift_contributions(session_id, start, end)
                if cache_key is not None:
                    self._battle_contrib_cache[cache_key] = gift
            gift_by_id = {g["user_id"]: g for g in gift if g.get("user_id")}
            matched = set()
            result = []
            for c in battle.get("contributions", []):
                is_own_host = c.get("side") == "own" and (
                    not own_host or c.get("host_id") in (None, "", own_host)
                )
                gid = c.get("user_id")
                if is_own_host and gid and gid in gift_by_id:
                    # armies由来の貢献(score=バトルスコア)に、Gift event由来の実弾(コイン)を
                    # 数値IDで突合して上書きし、@handle等の表示情報も補完する。
                    g = gift_by_id[gid]
                    c["diamonds"] = g["diamonds"]
                    c["unique_id"] = g.get("unique_id") or c.get("unique_id", "")
                    c["nickname"] = c.get("nickname") or g.get("nickname")
                    c["avatar"] = c.get("avatar") or g.get("avatar")
                    c["host_id"] = own_host or c.get("host_id")
                    # メンバーLv/バッジはGift event由来(armiesには無い)。取得できた分だけ付与。
                    c["fans_level"] = g.get("fans_level") or c.get("fans_level", 0)
                    c["gifter_level"] = g.get("gifter_level") or c.get("gifter_level", 0)
                    c["gifter_badge"] = g.get("gifter_badge") or c.get("gifter_badge", "")
                    c["member_badge"] = g.get("member_badge") or c.get("member_badge", "")
                    matched.add(gid)
                result.append(c)
            # armiesに無い(=PKスコア内訳が来ていない)自陣貢献者は、Gift eventから追加する
            # (この場合バトルスコアは不明=score 0)。
            for g in gift:
                if g.get("user_id") and g["user_id"] in matched:
                    continue
                result.append({
                    "user_id": g.get("user_id", ""),
                    "unique_id": g.get("unique_id", ""),
                    "nickname": g.get("nickname", "(unknown)"),
                    "avatar": g.get("avatar", ""),
                    "side": "own",
                    "host_id": own_host or "",
                    "score": 0,
                    "diamonds": g.get("diamonds", 0),
                    "fans_level": g.get("fans_level", 0),
                    "gifter_level": g.get("gifter_level", 0),
                    "gifter_badge": g.get("gifter_badge", ""),
                    "member_badge": g.get("member_badge", ""),
                })
            battle["contributions"] = result
        return battles

    def battles_for_session(self, session_id: int) -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT data_json FROM battles WHERE session_id = ?", (session_id,)
            ).fetchall()
        # 勝敗は保存値ではなくPK確定時点で判定し直す(DBは書き換えない)。履歴画面・
        # 焼き込み・解析が同じ判定を見るための単一の入口。
        battles = [annotate_result(json.loads(row["data_json"])) for row in rows]
        self.apply_battle_gift_contributions(session_id, battles)
        battles.sort(key=lambda b: b.get("start_time", 0), reverse=True)
        return battles

    def streamer_history_stats(self, unique_id: str, limit: int) -> dict:
        """Per-streamer comparison of recent finished sessions: today's run is the
        live snapshot (supplied by the caller); this returns the previous session,
        the recent average, and the personal best for each metric. Peak viewers is
        read from the buckets table (the finalized stats keep only the last value)."""
        with self._lock:
            handles = self._owner_handles_locked(unique_id)
            ph = ",".join("?" * len(handles))
            rows = self._conn.execute(
                "SELECT s.id, s.started_at, s.ended_at, s.stats_json,"
                " (SELECT MAX(viewers) FROM buckets b WHERE b.session_id = s.id) AS peak_viewers"
                f" FROM sessions s WHERE s.unique_id IN ({ph}) AND s.ended_at IS NOT NULL"
                + _EXCLUDE_RESTRICTED
                + " ORDER BY s.started_at DESC LIMIT ?",
                (*handles, limit),
            ).fetchall()
        sessions = []
        for row in rows:
            stats = json.loads(row["stats_json"])
            sessions.append(
                {
                    "session_id": row["id"],
                    "started_at": row["started_at"],
                    "gifts": stats.get("gifts", 0) or 0,
                    "diamonds": stats.get("diamonds", 0) or 0,
                    "comments": stats.get("comments", 0) or 0,
                    "viewers": stats.get("viewers_peak")
                    or row["peak_viewers"]
                    or stats.get("viewers", 0)
                    or 0,
                    "duration": (row["ended_at"] - row["started_at"]) if row["ended_at"] else 0,
                }
            )
        metrics = ["gifts", "diamonds", "comments", "viewers", "duration"]
        count = len(sessions)
        average = {
            m: (sum(s[m] for s in sessions) / count) if count else 0 for m in metrics
        }
        best = {m: max((s[m] for s in sessions), default=0) for m in metrics}
        return {
            "unique_id": unique_id,
            "count": count,
            "sessions": sessions,
            "last": sessions[0] if sessions else None,
            "average": average,
            "best": best,
        }

    def streamer_index(self) -> list:
        """List every monitored streamer with lifetime totals, for the streamer
        analytics page's left-hand selector. Identity (nickname/avatar) is the most
        recent non-empty owner record."""
        with self._lock:
            # GROUP BYは配信者identity(owner_user_id優先)。bare columnのs.unique_idは
            # SQLiteでは任意の行から取られ@handle改名者でラベルが不定になるため、表示用
            # handleは最新sessionのものを相関subqueryで決定的に選ぶ。
            rows = self._conn.execute(
                "SELECT COALESCE(NULLIF(s.owner_user_id, ''), s.unique_id) AS okey,"
                " COUNT(DISTINCT s.id) AS sessions,"
                " COALESCE(SUM(CASE WHEN e.kind = 'gift' THEN e.diamonds ELSE 0 END), 0) AS diamonds,"
                " COALESCE(SUM(CASE WHEN e.kind = 'gift' THEN e.gift_count ELSE 0 END), 0) AS gifts,"
                " COALESCE(SUM(CASE WHEN e.kind = 'comment' THEN 1 ELSE 0 END), 0) AS comments,"
                " MAX(s.started_at) AS last_started_at"
                " FROM sessions s LEFT JOIN events e ON e.session_id = s.id"
                f" WHERE 1=1{_EXCLUDE_RESTRICTED}"
                " GROUP BY COALESCE(NULLIF(s.owner_user_id, ''), s.unique_id) ORDER BY diamonds DESC, sessions DESC",
            ).fetchall()
            handles = self._latest_owner_handles_locked()
            owners = self._latest_owners()
        result = []
        for row in rows:
            handle = handles.get(row["okey"], row["okey"])
            owner = owners.get(handle)
            result.append(
                {
                    "unique_id": handle,
                    "nickname": (owner["nickname"] if owner else "") or handle,
                    "avatar": (owner["avatar"] if owner else "") or "",
                    "sessions": row["sessions"],
                    "diamonds": row["diamonds"] or 0,
                    "gifts": row["gifts"] or 0,
                    "comments": row["comments"] or 0,
                    "last_started_at": row["last_started_at"],
                }
            )
        return result

    def streamer_profile(self, unique_id: str, limit: int = 200) -> dict:
        """Cross-session profile for one streamer: lifetime/average/best metrics,
        per-session series, the streamer's own gifter base (with loyalty + revenue
        concentration), and battle record (win rate, scores, opponents, the share of
        revenue earned during battle windows). Peak viewers comes from buckets; the
        finalized stats keep only the last viewer count."""
        with self._lock:
            handles = self._owner_handles_locked(unique_id)
            ph = ",".join("?" * len(handles))
            session_rows = self._conn.execute(
                "SELECT s.id, s.started_at, s.ended_at, s.stats_json,"
                " (SELECT MAX(viewers) FROM buckets b WHERE b.session_id = s.id) AS peak_viewers"
                f" FROM sessions s WHERE s.unique_id IN ({ph})"
                + _EXCLUDE_RESTRICTED
                + " ORDER BY s.started_at DESC LIMIT ?",
                (*handles, limit),
            ).fetchall()
            # 表示属性はusers表(最新)を優先する。ここはsessionを跨いだ通算集計で、
            # 「そのSessionでの見え方」という基準が存在しないため、最新の身元で1人を1行に
            # 示すのが正しい。session単位のsession_summary/battle_gift_contributionsは逆に
            # point-in-timeを優先する(そちらは過去の見え方を保つのが目的)。
            #
            # event側をMAX()で優先してはいけない: MAX()は辞書順の最大を返すだけで「最新の
            # handle」ではない。実測では改名前の自動生成handle user5037930325926 が現handle
            # harehare12345 を、user9487377432719 が chikudenchi0807 を押しのけていた。
            gifter_rows = self._conn.execute(
                "SELECT e.identity_key AS key,"
                " COALESCE(NULLIF(u.user_id, ''), MAX(e.user_id)) AS user_id,"
                " COALESCE(NULLIF(u.unique_id, ''), MAX(e.user_unique_id)) AS unique_id,"
                " COALESCE(NULLIF(u.nickname, ''), MAX(e.user_nickname)) AS nickname,"
                " COALESCE(NULLIF(u.avatar, ''), MAX(e.user_avatar)) AS avatar, SUM(e.gift_count) AS gifts,"
                " SUM(e.diamonds) AS diamonds, COUNT(DISTINCT e.session_id) AS sessions"
                " FROM events e JOIN sessions s ON s.id = e.session_id"
                " LEFT JOIN users u ON u.identity_key = e.identity_key"
                f" WHERE s.unique_id IN ({ph}) AND e.kind = 'gift'"
                " GROUP BY e.identity_key ORDER BY diamonds DESC, gifts DESC",
                tuple(handles),
            ).fetchall()
            # Time-of-day distribution from the bucket time-series, so a session's
            # coins/comments land in the hours they actually happened (not all on the
            # start hour). 'localtime' matches the browser on this localhost app, so
            # the day/hour grid lines up with the rest of the (browser-local) UI.
            heatmap_rows = self._conn.execute(
                "SELECT CAST(strftime('%w', b.start, 'unixepoch', 'localtime') AS INTEGER) AS dow,"
                " CAST(strftime('%H', b.start, 'unixepoch', 'localtime') AS INTEGER) AS hour,"
                " CAST(strftime('%M', b.start, 'unixepoch', 'localtime') AS INTEGER) / 15 AS quarter,"
                " SUM(b.diamonds) AS diamonds, SUM(b.comments) AS comments,"
                " SUM(s.bucket_seconds) AS active_seconds"
                " FROM buckets b JOIN sessions s ON s.id = b.session_id"
                f" WHERE s.unique_id IN ({ph})"
                " GROUP BY dow, hour, quarter",
                tuple(handles),
            ).fetchall()
            # Oldest session first so that, when the same battle_id is saved under
            # more than one session (e.g. two server instances collected the same
            # room concurrently), the copy kept by the dedup below is the one whose
            # session saw the battle from its start — the most complete record.
            battle_rows = self._conn.execute(
                "SELECT b.session_id AS session_id, b.data_json AS data_json"
                " FROM battles b JOIN sessions s ON s.id = b.session_id"
                f" WHERE s.unique_id IN ({ph})"
                " ORDER BY s.started_at ASC, b.session_id ASC",
                tuple(handles),
            ).fetchall()
            owners = self._latest_owners()
            owner = owners.get(unique_id)

        # 各Battleの自陣貢献を、Battle cardと同じ窓・同じ入口(battle_gift_contributions)で
        # 復元する。窓解決は同一sessionの他Battle(次Battle開始・duration中央値)に依存する
        # ためsession単位でまとめて解く。窓を自前で持つと、end_timeを欠くBattleが無制限窓に
        # なりBattle後の通常Giftまで貢献へ混入する(実測: 貢献者0人→12人, coin 26→19397)。
        # battle_gift_contributionsは自身でlockを取るのでlockの外で回す。
        battles_by_session: dict = {}
        for brow in battle_rows:
            battles_by_session.setdefault(brow["session_id"], []).append(
                annotate_result(json.loads(brow["data_json"]))
            )

        battle_diamonds = 0
        battle_team_diamonds = 0
        # 相手陣のgifterは別Roomのためこのsessionのeventには無い。ここに集まるのは監視配信者
        # 自身のBattle gifterだけで、全Battleを通して「Battleに必ず現れるgifter」を表す。
        battle_gifters: dict = {}
        parsed_battles = []
        # battle_id is TikTok's globally-unique PK id, so the same physical battle
        # carries the same id across sessions. Dedup on it to keep concurrent-
        # collection duplicates from inflating every battle metric. id 0/missing is
        # treated as un-dedupable (old/synthetic records) and kept as-is.
        seen_battle_ids = set()
        dropped_duplicates = 0
        for session_id, session_battles in battles_by_session.items():
            # 窓解決には(重複除外前の)そのsessionの全Battleを使う。除外されるのは別session
            # が同じBattleを重複収集した分で、このsessionの「次Battle開始」は変わらないため。
            starts = sorted(
                b["start_time"] for b in session_battles if b.get("start_time") is not None
            )
            fallback_duration = gift_window_fallback_duration(session_battles)
            for battle in session_battles:
                start_time = battle.get("start_time")
                if start_time is None:
                    continue
                battle_id = battle.get("battle_id")
                if battle_id:
                    if battle_id in seen_battle_ids:
                        dropped_duplicates += 1
                        continue
                    seen_battle_ids.add(battle_id)
                end_time = gift_window_end(battle, starts, fallback_duration)
                gift = self.battle_gift_contributions(session_id, start_time, end_time)

                # 自室のGift eventで実測できる分。これが監視配信者自身の貢献者である。
                window_diamonds = 0
                key_contributors = 0
                for g in gift:
                    diamonds = g["diamonds"]
                    window_diamonds += diamonds
                    if diamonds >= _BATTLE_KEY_CONTRIB_DIAMONDS:
                        key_contributors += 1
                    key = g["key"]
                    if not key:
                        continue
                    agg = battle_gifters.setdefault(
                        key,
                        {
                            "user_id": g["user_id"],
                            "unique_id": g["unique_id"],
                            "nickname": g["nickname"],
                            "avatar": g["avatar"],
                            "diamonds": 0,
                            "gifts": 0,
                            "battles": 0,
                        },
                    )
                    agg["diamonds"] += diamonds
                    agg["gifts"] += g["gifts"]
                    agg["battles"] += 1
                    if g["avatar"] and not agg["avatar"]:
                        agg["avatar"] = g["avatar"]

                # チーム戦のteam集約armiesは味方hostの貢献者も自陣hostへ寄って届く
                # (team集約のanchorが実hostに解決できないため、host別に分けられない)。
                # 実測できる自室分とは別に、armies由来のチーム全体分も併記する。集計方法は
                # Battle card(apply_battle_gift_contributions)と揃える。
                gift_by_id = {g["user_id"]: g for g in gift if g["user_id"]}
                team_diamonds = 0
                team_key_contributors = 0
                matched = set()
                for c in battle.get("contributions", []) or []:
                    if c.get("side") != "own":
                        continue
                    cid = c.get("user_id")
                    if cid and cid in gift_by_id:
                        matched.add(cid)
                        coins = gift_by_id[cid]["diamonds"]
                    else:
                        coins = c.get("diamonds") or 0
                    team_diamonds += coins
                    if coins >= _BATTLE_KEY_CONTRIB_DIAMONDS:
                        team_key_contributors += 1
                for g in gift:
                    if g["user_id"] and g["user_id"] in matched:
                        continue
                    team_diamonds += g["diamonds"]
                    if g["diamonds"] >= _BATTLE_KEY_CONTRIB_DIAMONDS:
                        team_key_contributors += 1

                battle_diamonds += window_diamonds
                battle_team_diamonds += team_diamonds
                parsed_battles.append(
                    {
                        "battle": battle,
                        "session_id": session_id,
                        "window_diamonds": window_diamonds,
                        "key_contributors": key_contributors,
                        "team_diamonds": team_diamonds,
                        "team_key_contributors": team_key_contributors,
                    }
                )

        if dropped_duplicates:
            logger.info(
                "streamer_profile: dropped %d duplicate battle(s) by battle_id for %s"
                " (concurrent-collection artifact)",
                dropped_duplicates,
                unique_id,
            )

        identity = {
            "unique_id": unique_id,
            "nickname": (owner["nickname"] if owner else "") or unique_id,
            "avatar": (owner["avatar"] if owner else "") or "",
        }

        sessions = []
        for row in session_rows:
            stats = json.loads(row["stats_json"])
            sessions.append(
                {
                    "session_id": row["id"],
                    "started_at": row["started_at"],
                    "ended_at": row["ended_at"],
                    "duration": (row["ended_at"] - row["started_at"]) if row["ended_at"] else 0,
                    "gifts": stats.get("gifts", 0) or 0,
                    "diamonds": stats.get("diamonds", 0) or 0,
                    "comments": stats.get("comments", 0) or 0,
                    "likes": stats.get("likes_total", 0) or 0,
                    "viewers": stats.get("viewers_peak")
                    or row["peak_viewers"]
                    or stats.get("viewers", 0)
                    or 0,
                    "battles": stats.get("battles", 0) or 0,
                    "battle_points": stats.get("battle_points", 0) or 0,
                }
            )
        metrics = ["gifts", "diamonds", "comments", "likes", "viewers", "duration", "battle_points"]
        count = len(sessions)
        totals = {m: sum(s[m] for s in sessions) for m in metrics}
        average = {m: (totals[m] / count if count else 0) for m in metrics}
        best = {m: max((s[m] for s in sessions), default=0) for m in metrics}

        gifters = [
            {
                # identity_keyはFan台帳の主キー。名前からその人の横断実績へ飛ぶ導線に使う。
                "identity_key": row["key"] or "",
                "user_id": row["user_id"] or "",
                "unique_id": row["unique_id"] or "",
                "nickname": row["nickname"] or "(unknown)",
                "avatar": row["avatar"] or "",
                "gifts": row["gifts"] or 0,
                "diamonds": row["diamonds"] or 0,
                "sessions": row["sessions"] or 0,
            }
            for row in gifter_rows
        ]
        gifter_total_diamonds = sum(g["diamonds"] for g in gifters)

        def _share(top_n: int) -> float:
            if not gifter_total_diamonds:
                return 0.0
            return sum(g["diamonds"] for g in gifters[:top_n]) / gifter_total_diamonds * 100

        concentration = {
            "total_gifters": len(gifters),
            "total_diamonds": gifter_total_diamonds,
            "top1": _share(1),
            "top5": _share(5),
            "top10": _share(10),
            "repeat_gifters": sum(1 for g in gifters if g["sessions"] >= 2),
            "once_gifters": sum(1 for g in gifters if g["sessions"] == 1),
        }

        battles = [pb["battle"] for pb in parsed_battles]
        wins = sum(1 for b in battles if b.get("result") == "win")
        losses = sum(1 for b in battles if b.get("result") == "lose")
        draws = sum(1 for b in battles if b.get("result") == "draw")
        decided = wins + losses
        own_score_sum = sum(b.get("own_score", 0) or 0 for b in battles)
        opp_score_sum = sum(b.get("opp_score", 0) or 0 for b in battles)
        battle_count = len(battles)
        opponents: dict = {}
        for b in battles:
            for opp in b.get("opponents", []) or []:
                key = opp.get("unique_id") or opp.get("nickname") or opp.get("user_id")
                if not key:
                    continue
                stat = opponents.setdefault(
                    key,
                    {
                        "unique_id": opp.get("unique_id", ""),
                        "nickname": opp.get("nickname", "(unknown)"),
                        "avatar": opp.get("avatar", ""),
                        "battles": 0,
                        "wins": 0,
                        "losses": 0,
                    },
                )
                stat["battles"] += 1
                if b.get("result") == "win":
                    stat["wins"] += 1
                elif b.get("result") == "lose":
                    stat["losses"] += 1
        opponent_list = sorted(opponents.values(), key=lambda o: o["battles"], reverse=True)
        battle_gifter_list = sorted(battle_gifters.values(), key=lambda g: g["diamonds"], reverse=True)

        # Per-battle history (newest first) — the chronological record behind the
        # aggregate: each battle's scores, result, primary opponent and the coins
        # raised in its window. The frontend reverses it for a score-over-battles
        # trend chart and lists it as a table.
        history = []
        for pb in parsed_battles:
            b = pb["battle"]
            opps = b.get("opponents", []) or []
            opp = max(opps, key=lambda o: o.get("score", 0) or 0, default=None) if opps else None
            # own_scoreはチーム戦ではチーム合計。監視配信者1人ぶんのscoreは participants の
            # 自hostが持つ。個人戦(個人マルチ含む)は自陣host=1人なのでown_scoreと同値。
            # チーム戦で自hostを特定できない古いrecordはNone(不明)にする。0を入れると
            # 「そのBattleは無得点だった」と読める偽の実測値になるため。
            btype = b.get("type") or "personal"
            own_host = next(
                (p for p in (b.get("participants") or []) if p.get("is_own")), None
            )
            if own_host is not None:
                own_host_score = own_host.get("score", 0) or 0
            else:
                own_host_score = (b.get("own_score", 0) or 0) if btype != "team" else None
            history.append(
                {
                    "session_id": pb["session_id"],
                    "battle_id": b.get("battle_id"),
                    "started_at": b.get("start_time"),
                    "ended_at": b.get("end_time"),
                    "type": btype,
                    "own_score": b.get("own_score", 0) or 0,
                    "own_host_score": own_host_score,
                    "opp_score": b.get("opp_score", 0) or 0,
                    "result": b.get("result"),
                    "diamonds": pb["window_diamonds"],
                    "team_diamonds": pb["team_diamonds"],
                    "key_contributors": pb["key_contributors"],
                    "team_key_contributors": pb["team_key_contributors"],
                    "opponent_count": len(opps),
                    "opponent": {
                        "unique_id": opp.get("unique_id", ""),
                        "nickname": opp.get("nickname", "") or "(unknown)",
                        "avatar": opp.get("avatar", ""),
                    }
                    if opp
                    else None,
                }
            )
        history.sort(key=lambda h: h["started_at"] or 0, reverse=True)

        # 1戦あたり「主力貢献者(coin >= 閾値)」の平均人数。過去全Battleを集約した指標。
        # 自室のGift eventで実測した分と、armies由来のチーム全体分の両方を出す(チーム戦は
        # 味方hostの貢献者を自陣hostと分離できないため、片方だけでは実態を表さない)。
        key_contrib_sum = sum(pb["key_contributors"] for pb in parsed_battles)
        team_key_contrib_sum = sum(pb["team_key_contributors"] for pb in parsed_battles)
        # 自hostのscoreが不明なBattleは平均の母数からも外す(0として均すと平均が下振れする)。
        own_host_scores = [h["own_host_score"] for h in history if h["own_host_score"] is not None]
        battle_summary = {
            "count": battle_count,
            "wins": wins,
            "losses": losses,
            "draws": draws,
            "win_rate": (wins / decided * 100) if decided else 0,
            "avg_own_score": (own_score_sum / battle_count) if battle_count else 0,
            "avg_own_host_score": (sum(own_host_scores) / len(own_host_scores)) if own_host_scores else 0,
            "own_host_score_count": len(own_host_scores),
            "avg_opp_score": (opp_score_sum / battle_count) if battle_count else 0,
            "key_contrib_threshold": _BATTLE_KEY_CONTRIB_DIAMONDS,
            "key_contrib_total": key_contrib_sum,
            "avg_key_contributors": (key_contrib_sum / battle_count) if battle_count else 0,
            "team_key_contrib_total": team_key_contrib_sum,
            "avg_team_key_contributors": (team_key_contrib_sum / battle_count) if battle_count else 0,
            "battle_diamonds": battle_diamonds,
            "battle_team_diamonds": battle_team_diamonds,
            "battle_diamond_share": (battle_diamonds / totals["diamonds"] * 100) if totals["diamonds"] else 0,
            "opponents": opponent_list[:30],
            "gifters": battle_gifter_list[:30],
            "history": history[:80],
        }

        heatmap = [
            {
                "dow": row["dow"],
                "hour": row["hour"],
                "quarter": row["quarter"],
                "diamonds": row["diamonds"] or 0,
                "comments": row["comments"] or 0,
                "active_seconds": row["active_seconds"] or 0,
            }
            for row in heatmap_rows
        ]

        return {
            "identity": identity,
            "count": count,
            "sessions": sessions,
            "totals": totals,
            "average": average,
            "best": best,
            "gifters": gifters[:100],
            "concentration": concentration,
            "battles": battle_summary,
            "heatmap": heatmap,
        }

    def streamer_cohort(self, unique_id: str) -> dict:
        """Daily viewer cohort/retention for one streamer. A viewer counts as
        present on a day if they produced any watch-side event (entering the room,
        commenting, liking, following, sharing, subscribing, or gifting) — presence
        is what matters here, not whether they gifted. For each day: active viewers,
        new (first-ever visit this day) vs returning, and retention = share of the
        previous active day's viewers who came back to watch this day. Days are
        local-time so they line up with the browser-local UI."""
        with self._lock:
            handles = self._owner_handles_locked(unique_id)
            ph = ",".join("?" * len(handles))
            rows = self._conn.execute(
                "SELECT e.identity_key AS key,"
                " strftime('%Y-%m-%d', e.time, 'unixepoch', 'localtime') AS ymd,"
                " SUM(e.diamonds) AS diamonds"
                " FROM events e JOIN sessions s ON s.id = e.session_id"
                f" WHERE s.unique_id IN ({ph})"
                " AND e.kind IN ('join', 'comment', 'like', 'follow', 'share', 'subscribe', 'gift')"
                " GROUP BY e.identity_key, ymd",
                tuple(handles),
            ).fetchall()
        by_day: dict = {}
        first_seen: dict = {}
        for row in rows:
            ymd = row["ymd"]
            key = row["key"]
            if not ymd or not key:
                continue
            by_day.setdefault(ymd, {})[key] = row["diamonds"] or 0
            if key not in first_seen or ymd < first_seen[key]:
                first_seen[key] = ymd
        days = []
        prev_keys: set = set()
        for ymd in sorted(by_day.keys()):
            keys = set(by_day[ymd].keys())
            new = {k for k in keys if first_seen[k] == ymd}
            retained = keys & prev_keys
            days.append(
                {
                    "date": ymd,
                    "active": len(keys),
                    "new": len(new),
                    "returning": len(keys) - len(new),
                    "retained": len(retained),
                    "retention": (len(retained) / len(prev_keys) * 100) if prev_keys else 0,
                    "diamonds": sum(by_day[ymd].values()),
                }
            )
            prev_keys = keys
        return {"days": days}

    def streamer_highlights(self, unique_id: str, session_limit: int = 50, top: int = 15) -> list:
        """Auto-detected spike moments across a streamer's recent sessions. A bucket
        is a highlight when its coin value is a statistical outlier within its session
        (z-score >= 2 over that session's coin buckets); the biggest spike per session
        is kept and the top ones returned, tagged if a recording covers the moment."""
        highlights = []
        with self._lock:
            handles = self._owner_handles_locked(unique_id)
            ph = ",".join("?" * len(handles))
            session_rows = self._conn.execute(
                f"SELECT id, started_at FROM sessions WHERE unique_id IN ({ph})"
                + _EXCLUDE_RESTRICTED_NO_ALIAS
                + " ORDER BY started_at DESC LIMIT ?",
                (*handles, session_limit),
            ).fetchall()
            session_ids = [s["id"] for s in session_rows]
            buckets_by_session: dict = {}
            if session_ids:
                bph = ",".join("?" * len(session_ids))
                for brow in self._conn.execute(
                    f"SELECT session_id, start, diamonds, comments FROM buckets"
                    f" WHERE session_id IN ({bph}) ORDER BY session_id, start",
                    tuple(session_ids),
                ).fetchall():
                    buckets_by_session.setdefault(brow["session_id"], []).append(brow)
            for session in session_rows:
                buckets = buckets_by_session.get(session["id"], [])
                # 窓は1 bucket。録画単位の候補検出(server側)は同じ関数を秒指定の窓で呼ぶ。
                found = spike.detect_spikes(buckets, window_buckets=1, metrics=("diamonds",))
                best = None
                for candidate in found:
                    value = candidate["values"]["diamonds"]
                    if best is None or value > best["diamonds"]:
                        best = {
                            "session_id": session["id"],
                            "time": candidate["start"],
                            "diamonds": int(value),
                            "comments": int(candidate["values"]["comments"]),
                            "baseline": candidate["baseline"],
                            "ratio": candidate["ratio"],
                            "zscore": candidate["zscore"],
                        }
                if best:
                    highlights.append(best)
            recordings = self._conn.execute(
                f"SELECT id, session_id, started_at, ended_at FROM recordings"
                f" WHERE unique_id IN ({ph}) AND status IN ('completed', 'interrupted')",
                tuple(handles),
            ).fetchall()
        recs = [dict(r) for r in recordings]
        for highlight in highlights:
            cover = next(
                (
                    r
                    for r in recs
                    if r["session_id"] == highlight["session_id"]
                    and r["started_at"] <= highlight["time"]
                    and (r["ended_at"] is None or highlight["time"] <= r["ended_at"])
                ),
                None,
            )
            highlight["has_recording"] = cover is not None
            highlight["recording_id"] = cover["id"] if cover else None
            # Seconds into the recording to jump to, for deep-linked playback.
            highlight["offset"] = (
                max(0, highlight["time"] - cover["started_at"]) if cover else None
            )
        highlights.sort(key=lambda h: h["diamonds"], reverse=True)
        return highlights[:top]

    # ---- 全体解析(配信者横断) ------------------------------------------
    # 監視配信者を横断した集約。新規収集は行わず既存DBの再集約のみ。集約は配信(session)
    # 単位の中間集計(payload)までに留めてanalytics_session_cacheへ永続化する(終了済み
    # sessionは不変なので1回だけ計算し、収集中sessionは毎回その場で計算)。全体へ丸めた
    # 集約を持たないため、配信者データの削除はsessionsのON DELETE CASCADEで整合が保てる。
    # sinceは集計対象の下限started_at(0=全期間)。母集団のサンプル数を各所で返し、
    # 少数での断定を防ぐ。

    _ANALYTICS_SESSION_SELECT = (
        "SELECT s.id AS id, s.unique_id AS unique_id, s.started_at AS started_at,"
        " s.ended_at AS ended_at, s.bucket_seconds AS bucket_seconds, s.status AS status,"
        " COALESCE(NULLIF(s.owner_user_id, ''), s.unique_id) AS owner_key"
    )

    @staticmethod
    def _analytics_sess_dict(row) -> dict:
        return {
            "id": row["id"],
            "unique_id": row["unique_id"],
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
            "bucket_seconds": row["bucket_seconds"],
            "owner_key": row["owner_key"],
        }

    def _ensure_analytics_cache(self, kind: str) -> int:
        """終了済みで未計算(またはlogic version不一致)のsessionのpayloadを計算・保存する。
        finalizeを通らず終了したsession(異常終了の復旧等)もここで拾う。

        **lockはsession 1件ごとに取り直す(lock保持のまま全件回さない)**。CACHE_VERSIONSを
        1つ上げると全履歴が再計算対象になり、以前はその全走査をDB lockを握ったまま行って
        いた。待たされるのは解析画面だけではない: 同じlockを使う全ての読み書き — 別tabの
        録画一覧も、収集中sessionのevent書き込みも — が止まるため、userには「アプリ全体が
        固まった」ように見える。1件ごとに手放せば、他のrequestがその隙間へ入れる。

        件数が変わるのは「他のrequestが割り込める」点だけで、結果は変わらない。埋めている
        最中に追加されたsessionはcacheに載らないまま読み出しへ抜けるが、その場合は
        _analytics_rows がその場で計算する経路(収集中sessionと同じ)へ落ちる。
        """
        version = analytics.CACHE_VERSIONS[kind]
        with self._lock:
            rows = self._conn.execute(
                self._ANALYTICS_SESSION_SELECT
                + " FROM sessions s"
                " LEFT JOIN analytics_session_cache c ON c.session_id = s.id AND c.kind = ?"
                " WHERE s.ended_at IS NOT NULL AND (c.session_id IS NULL OR c.version != ?)"
                + _EXCLUDE_RESTRICTED,
                (kind, version),
            ).fetchall()
        gate = IntervalGate(progress_interval_seconds(get_log_progress_interval_seconds()))
        for index, row in enumerate(rows):
            # 1件ぶんの計算と書き込みだけをlockの中で行う。connectionはthread safeでは
            # ないので、計算をlockの外へ出すことはできない(隙間を作るのが目的で、
            # 排他を弱めるのが目的ではない)。
            with self._lock:
                payload = analytics.compute_payload(
                    self._conn, self._analytics_sess_dict(row), kind
                )
                self._conn.execute(
                    "INSERT OR REPLACE INTO analytics_session_cache"
                    " (session_id, kind, version, payload_json, computed_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (row["id"], kind, version, json.dumps(payload), time.time()),
                )
            if gate.ready():
                logger.info(
                    "analytics cache: %d/%d sessions computed for kind=%s",
                    index + 1, len(rows), kind,
                    extra={"event": "analytics.cache_progress",
                           "ctx": {"kind": kind, "done": index + 1, "total": len(rows)}},
                )
        if rows:
            with self._lock:
                self._conn.commit()
            logger.info(
                "analytics cache: computed %d sessions for kind=%s", len(rows), kind
            )
        return len(rows)

    def _analytics_rows(self, kind: str, since: float) -> list:
        """(sessionメタ, per-session payload)の列をstarted_at昇順で返す。終了済みは
        cacheから読み、収集中sessionはその場で計算する(session単位indexで軽い)。

        収集中sessionのその場計算はbufferではなくDBを読むため、先に確定させる。終了済み
        分はfinalize_sessionがflush後にcacheを作るので既に整合している。"""
        self.flush()
        # cache埋めはlockの外で行う(中で1件ごとに取り直す)。ここをlockの中へ戻すと、
        # 全session再計算のあいだDBに触る全ての処理が止まる。
        self._ensure_analytics_cache(kind)
        with self._lock:
            rows = self._conn.execute(
                self._ANALYTICS_SESSION_SELECT
                + ", c.payload_json AS payload_json FROM sessions s"
                " LEFT JOIN analytics_session_cache c ON c.session_id = s.id AND c.kind = ?"
                " WHERE s.started_at >= ? ORDER BY s.started_at",
                (kind, since),
            ).fetchall()
            out = []
            for row in rows:
                sess = self._analytics_sess_dict(row)
                if sess["ended_at"] is not None and row["payload_json"] is not None:
                    out.append((sess, json.loads(row["payload_json"])))
                else:
                    out.append((sess, analytics.compute_payload(self._conn, sess, kind)))
        return out

    def _refresh_session_analytics_locked(self, session_id: int) -> None:
        """session確定直後に全kindのpayloadを計算し保存する。lock保持前提。"""
        row = self._conn.execute(
            self._ANALYTICS_SESSION_SELECT + " FROM sessions s WHERE s.id = ?",
            (session_id,),
        ).fetchone()
        if row is None or row["ended_at"] is None:
            return
        # 制限sessionはevent 0件なので全体解析の対象外(cacheも作らない)。
        if row["status"] == SESSION_STATUS_RESTRICTED:
            return
        sess = self._analytics_sess_dict(row)
        now = time.time()
        for kind in analytics.KINDS:
            payload = analytics.compute_payload(self._conn, sess, kind)
            self._conn.execute(
                "INSERT OR REPLACE INTO analytics_session_cache"
                " (session_id, kind, version, payload_json, computed_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    session_id,
                    kind,
                    analytics.CACHE_VERSIONS[kind],
                    json.dumps(payload),
                    now,
                ),
            )
        self._conn.commit()

    def analytics_summary(self, since: float = 0.0) -> dict:
        """全体解析の母集団サマリ(何本の配信・何時間・何bucketを基に集計しているか)。"""
        return analytics.reduce_summary(self._analytics_rows("summary", since))

    def analytics_time_index(self, metric: str = "joins", since: float = 0.0) -> dict:
        """時間帯インデックス: 各配信の平均レートを1.0とした時間帯ごとの相対倍率。"""
        if metric not in analytics.INDEX_METRICS:
            raise ValueError(f"unsupported index metric: {metric}")
        return analytics.reduce_time_index(
            self._analytics_rows("time_index", since), metric
        )

    def analytics_relations(self, since: float = 0.0) -> dict:
        """指標間の関連(配信単位)のSpearman順位相関+同接(規模)制御の偏相関。"""
        return analytics.reduce_relations(self._analytics_rows("relations", since))

    def analytics_share_uplift(self, since: float = 0.0) -> dict:
        """Share→入室のevent-study(placebo帯・95%CI付き)。"""
        return analytics.reduce_peri(self._analytics_rows("peri_share", since), "share")

    def analytics_battle_uplift(self, since: float = 0.0) -> dict:
        """Battle→入室のevent-study(placebo/CI補正)。baseline非補正の旧レート比は
        ratio_metricsとして参考併記する。"""
        result = analytics.reduce_peri(
            self._analytics_rows("peri_battle", since), "battle"
        )
        result["ratio_metrics"] = analytics.reduce_battle_ratio(
            self._analytics_rows("battle_ratio", since)
        )
        return result

    def analytics_glove_crit_rate(self, since: float = 0.0) -> dict:
        """Battleのグローブ(5倍化)のcoin帯別発動率。単価不明分は全期間のGift event由来の
        gift_id→単価表で解決する(観測が増えるほど後から解ける)。"""
        rows = self._analytics_rows("glove", since)
        with self._lock:
            coin_rows = self._conn.execute(
                "SELECT gift_id, diamonds, gift_count FROM events"
                " WHERE kind = 'gift' AND gift_id IS NOT NULL AND gift_count > 0"
            ).fetchall()
        # gift_id→単価(diamonds_each)。同一gift_idは価格一定なので代表値でよい。
        unit_coins: dict = {}
        for r in coin_rows:
            gid, cnt = r["gift_id"], r["gift_count"] or 0
            if gid is None or cnt <= 0:
                continue
            unit_coins[gid] = (r["diamonds"] or 0) / cnt
        return analytics.reduce_glove(rows, unit_coins)

    def analytics_join_quality(self, since: float = 0.0) -> dict:
        """入室の質: 入室者のうち初見(初観測)の比率を時間帯別に。"""
        return analytics.reduce_join_quality(self._analytics_rows("join_quality", since))

    def analytics_scale_efficiency(self, since: float = 0.0) -> dict:
        """規模 vs 効率: 配信者ごとの平均同接(規模)と同接あたりコイン(効率)。"""
        rows = self._analytics_rows("scale_efficiency", since)
        with self._lock:
            owners = self._latest_owners()
        return analytics.reduce_scale_efficiency(rows, owners)

    def analytics_retention(self, since: float = 0.0) -> dict:
        """入室→定着: 時刻別の入室と平均同接、全体stick rate(=Σ純増/Σ入室)。"""
        return analytics.reduce_retention(self._analytics_rows("retention", since))

    def analytics_concentration(self, since: float = 0.0) -> dict:
        """ギフト/コメントの集中度(横断)。identity_key単位でgiftコインとComment数を集計し、
        Gini係数・Lorenz曲線・上位N%シェアを返す。User横断の貢献量が必要なためsession単位
        cacheでは持たず、covering index(kind, identity_key, ...)で素データを直接集計する
        (素データと同時に消えるため削除でも整合が壊れない)。"""
        with self._lock:
            gift_rows = self._conn.execute(
                "SELECT e.identity_key AS key, SUM(e.diamonds) AS v"
                " FROM events e JOIN sessions s ON s.id = e.session_id"
                " WHERE e.kind = 'gift' AND s.started_at >= ?"
                " GROUP BY e.identity_key",
                (since,),
            ).fetchall()
            comment_rows = self._conn.execute(
                "SELECT e.identity_key AS key, COUNT(*) AS v"
                " FROM events e JOIN sessions s ON s.id = e.session_id"
                " WHERE e.kind = 'comment' AND s.started_at >= ?"
                " GROUP BY e.identity_key",
                (since,),
            ).fetchall()
        gifts = analytics.concentration([r["v"] or 0 for r in gift_rows if r["key"]])
        comments = analytics.concentration(
            [r["v"] or 0 for r in comment_rows if r["key"]]
        )
        return {"gifts": gifts, "comments": comments}

    def analytics_join_context(self, since: float = 0.0) -> dict:
        """入室のコンテキスト別(Battle中/コラボ中/平時)の入室数・秒・分レート。"""
        return analytics.reduce_join_context(self._analytics_rows("join_context", since))

    def analytics_entry_source(self, since: float = 0.0) -> dict:
        """流入元(clientEnterSource)と視聴者のfollow関係の内訳。計装前のsessionは
        計測不能として分母から外し、被覆率を併記する。"""
        # 収集中sessionはその場でeventを読むため、batch writerに滞留した分を先に確定する。
        self.flush()
        return analytics.reduce_entry_source(self._analytics_rows("entry_source", since))

    def analytics_battle_flow(self, since: float = 0.0) -> dict:
        """Battle展開(残り時間軸): リード交代・残り1分時点のリード別勝率・終盤集中度。"""
        return analytics.reduce_battle_flow(self._analytics_rows("battle_flow", since))

    def analytics_coverage(self, since: float = 0.0) -> dict:
        """収集カバレッジ: 開始遅延・切断欠測・sampling間隔・録画率・STT率。

        録画のended_atも転写もsessionが終わった後から埋まるため、この2つはsession単位
        payload cacheへ載せず、都度素データから集計する(cacheすると永久に古い値になる)。"""
        # 収集中sessionのsampling間隔はviewer_samplesをその場で読むため、batch writerに
        # 滞留したsampleを先に確定させる(読み取り前flush)。
        self.flush()
        rows = self._analytics_rows("coverage", since)
        with self._lock:
            media = self._conn.execute(
                "SELECT r.session_id AS session_id, r.started_at AS started_at,"
                " r.ended_at AS ended_at, r.status AS status,"
                " (t.recording_id IS NOT NULL) AS has_transcript"
                " FROM recordings r"
                " JOIN sessions s ON s.id = r.session_id"
                " LEFT JOIN transcripts t ON t.recording_id = r.id"
                " WHERE s.started_at >= ?" + _EXCLUDE_RESTRICTED,
                (since,),
            ).fetchall()
        return analytics.reduce_coverage(rows, media)

    def analytics_organic_entries(self, since: float = 0.0) -> dict:
        """organic入室(§15): ノイズ入室を落としたgenuineness weight付き時間帯カーブ。"""
        return analytics.reduce_organic(self._analytics_rows("organic", since))

    def create_recording(self, session_id, unique_id, path, filename, quality, started_at) -> int:
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO recordings (session_id, unique_id, path, filename, quality, status, started_at)"
                " VALUES (?, ?, ?, ?, ?, 'recording', ?)",
                (session_id, unique_id, path, filename, quality, started_at),
            )
            self._conn.commit()
            return cursor.lastrowid

    def update_recording(self, recording_id, status, path, filename, ended_at, size,
                         error=None, duration_seconds=None) -> None:
        """live captureが終わった録画を確定させる。ended_atは捕捉が終わった時刻そのもの。

        duration_secondsは測れたときだけ渡す。測れなかった(ffprobeが無い等)場合に既存の
        実測値を消さないよう、Noneは「据え置き」であって「不明で上書き」ではない。"""
        with self._lock:
            self._conn.execute(
                "UPDATE recordings SET status = ?, path = ?, filename = ?, ended_at = ?, bytes = ?,"
                " error = ?, duration_seconds = COALESCE(?, duration_seconds)"
                " WHERE id = ?",
                (status, path, filename, ended_at, size, error, duration_seconds, recording_id),
            )
            self._conn.commit()

    def update_rebuilt_recording(self, recording_id, status, path, filename, size,
                                 error=None, duration_seconds=None,
                                 ended_at_if_missing=None) -> None:
        """既存録画を素材(.ts)から作り直した/拾い直した結果を書き戻す。

        **ended_atを現在時刻で上書きしてはならない**。作り直しは中身を作り直すだけで、
        捕捉が終わった時刻を変えない。update_recordingを流用していたため、起動時の復旧と
        再mp4化が実行時刻をended_atへ書き込み、DBの尺が「録画開始〜再処理時刻」に化けて
        いた(実測: 3時間の録画が177時間、同じbatchで処理した行は同一のended_atになるため
        古い行ほど尺が伸び、一覧では下へ行くほど増える見え方になる)。ended_atはrecording
        窓としてeventの絞り込みと焼き込みの時刻mapにも使われるので、被害は表示に留まらない。

        ended_at_if_missingは、そもそもended_atを持たない行(中断のまま終わった録画)を
        埋めるためだけの値。既にended_atがある行には触れない。"""
        with self._lock:
            self._conn.execute(
                "UPDATE recordings SET status = ?, path = ?, filename = ?, bytes = ?, error = ?,"
                " ended_at = COALESCE(ended_at, ?),"
                " duration_seconds = COALESCE(?, duration_seconds)"
                " WHERE id = ?",
                (status, path, filename, size, error, ended_at_if_missing,
                 duration_seconds, recording_id),
            )
            self._conn.commit()

    def set_recording_duration(self, recording_id: int, seconds: float) -> bool:
        """実測した尺だけを書き戻す。是正scriptと、中身を作り直さずに尺だけ確定させる
        経路が使う。0以下は測定失敗なので受け付けない(尺0の録画は存在しない)。"""
        if not seconds or seconds <= 0:
            return False
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE recordings SET duration_seconds = ? WHERE id = ?", (seconds, recording_id))
            self._conn.commit()
        return cursor.rowcount > 0

    def list_recordings(self, limit: int) -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM recordings ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def recordings_for_session(self, session_id: int) -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM recordings WHERE session_id = ? ORDER BY started_at", (session_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def recordings_for_user(self, unique_id: str) -> list:
        """配信者1人ぶんの全録画。容量整理の画面が対象を並べるための入力で、statusは
        絞らない(中断・失敗した録画こそHLSが残って容量を食っているため)。新しい順。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM recordings WHERE unique_id = ? ORDER BY started_at DESC",
                (unique_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_recording(self, recording_id: int) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM recordings WHERE id = ?", (recording_id,)
            ).fetchone()
        return dict(row) if row else None

    def recordings_brief(self) -> list:
        """Lightweight per-recording info for list-level done badges: each finished
        recording's session, path (to test for a burned-in output file) and whether a
        transcript exists. One query so the session list can aggregate cheaply."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT r.id, r.session_id, r.path,"
                " (t.recording_id IS NOT NULL) AS has_transcript"
                " FROM recordings r LEFT JOIN transcripts t ON t.recording_id = r.id"
                " WHERE r.status IN ('completed', 'interrupted')"
            ).fetchall()
        return [dict(row) for row in rows]

    def transcribed_recording_ids(self) -> set:
        """Recording ids that have a stored transcript (existence only, no payload)."""
        with self._lock:
            rows = self._conn.execute("SELECT recording_id FROM transcripts").fetchall()
        return {row["recording_id"] for row in rows}

    def delete_recording(self, recording_id: int) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM recordings WHERE id = ?", (recording_id,)
            ).fetchone()
            if row is None:
                return None
            self._conn.execute("DELETE FROM recordings WHERE id = ?", (recording_id,))
            self._conn.commit()
        return dict(row)

    def completed_recordings_with_paths(self) -> list:
        """完了録画のid/所在/容量。最終保存先への退避対象を選ぶための入力。

        pathの所属judgeとfileの実在確認は呼び出し側(server)が行う。record_dir /
        record_dir_final を知っているのはserver側で、ここへ持ち込むとstorageが設定に
        依存することになる。
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, unique_id, path, filename, bytes, started_at"
                " FROM recordings WHERE status = 'completed' AND path IS NOT NULL"
                " ORDER BY started_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def update_recording_bytes(self, recording_id: int, size: int) -> bool:
        """録画のbytesだけを書き換える。中身を差し替えたが所在も状態も変わらない場合
        (混在解像度normalizeの再回収)に使う。update_recordingは status/path/ended_at まで
        書き戻すので、ここで使うと呼び出し側が持っていない値で既存行を潰しかねない。"""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE recordings SET bytes = ? WHERE id = ?", (size, recording_id))
            self._conn.commit()
        return cursor.rowcount > 0

    def set_recording_reprocessed(self, recording_id: int, at: Optional[float]) -> bool:
        """録画を.tsから作り直した時刻を書く。``at=None``で未実施へ戻す。

        一括の「済み」判定はこの列だけを見る。作り直したmp4はfileから見分けが付かない
        (元と同じ名前・同じ場所の別内容)ので、file側から推測してはいけない。"""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE recordings SET reprocessed_at = ? WHERE id = ?", (at, recording_id))
            self._conn.commit()
        return cursor.rowcount > 0

    def set_recording_audio_normalized(self, recording_id: int, at: Optional[float],
                                       lufs: Optional[float]) -> bool:
        """録画本体の音量正規化の適用状態を書く。``at=None``で未適用へ戻す。

        mp4を作り直す操作は、正規化を伴わなかったなら必ずNoneで呼んで消すこと。残したまま
        にすると一括画面が「処理済」と数え、実際には素の音量のmp4が対象から外れる。
        """
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE recordings SET audio_normalized_at = ?, audio_normalized_lufs = ?"
                " WHERE id = ?",
                (at, lufs if at is not None else None, recording_id))
            self._conn.commit()
        return cursor.rowcount > 0

    def update_recording_path(self, recording_id: int, path: str) -> bool:
        """録画の所在を書き換える。移送が**成功した後にだけ**呼ぶこと。

        serverは再生・出力でrecordings.pathの絶対pathをそのまま使う(_safe_recording_path)。
        file を動かしてDBを更新しないと再生が壊れ、逆にDBだけ更新するともっと悪い
        (存在しないpathを指す)。filenameは移送で変わらないので触らない。
        """
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE recordings SET path = ? WHERE id = ?", (path, recording_id))
            self._conn.commit()
        return cursor.rowcount > 0

    def set_recording_protected(self, recording_id: int, protected: bool) -> bool:
        """保持policyの自動削除から除外するflagを立てる/下ろす。存在しない録画はFalse。"""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE recordings SET protected = ? WHERE id = ?",
                (1 if protected else 0, recording_id),
            )
            self._conn.commit()
        return cursor.rowcount > 0

    def recordings_for_retention(self) -> list:
        """保持policyの候補選定に必要な全録画。転写の有無まで含めるのは、生録画を消すと
        転写も道連れ(transcriptsはON DELETE CASCADE)になることを画面で示すため。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT r.*, (t.recording_id IS NOT NULL) AS has_transcript"
                " FROM recordings r LEFT JOIN transcripts t ON t.recording_id = r.id"
                " ORDER BY r.started_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def save_storage_scan(self, payload: dict, duration_ms: float) -> None:
        """容量内訳の走査結果を1行cacheへ全置換で保存する。"""
        with self._lock:
            self._conn.execute(
                "INSERT INTO storage_scan (id, scanned_at, duration_ms, payload_json)"
                " VALUES (1, ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET scanned_at = excluded.scanned_at,"
                " duration_ms = excluded.duration_ms, payload_json = excluded.payload_json",
                (time.time(), duration_ms, json.dumps(payload, ensure_ascii=False)),
            )
            self._conn.commit()

    def get_storage_scan(self) -> Optional[dict]:
        """保存済みの走査結果。まだ一度も走査していなければNone(空の内訳ではない)。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT scanned_at, duration_ms, payload_json FROM storage_scan WHERE id = 1"
            ).fetchone()
        if row is None:
            return None
        return {
            "scanned_at": row["scanned_at"],
            "duration_ms": row["duration_ms"],
            "usage": json.loads(row["payload_json"]),
        }

    def db_file_bytes(self) -> dict:
        """開いているDB本体とWAL/SHMのbyte数。

        env(TICTOK_DB_PATH)を読み直さず、実際に開いているpathを見る。envは後から変わり得る
        ので、読み直すと「いま計測しているDB」と別のfileを測ることになる。
        WALをdbと分けて出すのはcheckpointの判断材料になるため(実測19MB規模まで育つ)。
        """
        base = Path(self._db_path)
        out = {"db": 0, "wal": 0, "shm": 0}
        for key, suffix in (("db", ""), ("wal", "-wal"), ("shm", "-shm")):
            try:
                out[key] = (base.parent / (base.name + suffix)).stat().st_size
            except OSError:
                out[key] = 0
        return out

    def add_capacity_sample(self, payload: dict, sampled_at: Optional[float] = None) -> dict:
        """容量snapshotを1件追記する。storage_scan(1行cache)とは別で、こちらは履歴。"""
        now = time.time() if sampled_at is None else sampled_at
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO capacity_samples (sampled_at, payload_json) VALUES (?, ?)",
                (now, json.dumps(payload, ensure_ascii=False)),
            )
            self._conn.commit()
        return {"id": cursor.lastrowid, "sampled_at": now, "payload": payload}

    def latest_capacity_sample(self) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT sampled_at, payload_json FROM capacity_samples"
                " ORDER BY sampled_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return {"sampled_at": row["sampled_at"], "payload": json.loads(row["payload_json"])}

    def list_capacity_samples(self, since: Optional[float] = None, limit: int = 400) -> list:
        sql = "SELECT sampled_at, payload_json FROM capacity_samples"
        params: tuple = ()
        if since is not None:
            sql += " WHERE sampled_at >= ?"
            params = (since,)
        sql += " ORDER BY sampled_at DESC LIMIT ?"
        with self._lock:
            rows = self._conn.execute(sql, (*params, limit)).fetchall()
        samples = [
            {"sampled_at": r["sampled_at"], "payload": json.loads(r["payload_json"])}
            for r in rows
        ]
        samples.reverse()
        return samples

    def capacity_db_counts(self) -> dict:
        """健全性reportの母数。全てindexかtable走査で数十ms(実測)。"""
        with self._lock:
            rows = {}
            for name in ("events", "sessions", "users", "recordings", "transcripts",
                         "search_hits", "ops_events", "bookmarks"):
                rows[name] = self._conn.execute(
                    f"SELECT COUNT(*) AS c FROM {name}").fetchone()["c"]
            recordings = [
                dict(r) for r in self._conn.execute(
                    "SELECT status, COUNT(*) AS n, COALESCE(SUM(bytes), 0) AS bytes"
                    " FROM recordings GROUP BY status")
            ]
            transcribed = self._conn.execute(
                "SELECT COUNT(*) AS c FROM recordings r"
                " JOIN transcripts t ON t.recording_id = r.id"
                " WHERE r.status = 'completed'").fetchone()["c"]
            media_jobs = [
                dict(r) for r in self._conn.execute(
                    "SELECT kind, state, COUNT(*) AS n FROM media_job_queue"
                    " GROUP BY kind, state")
            ]
            transcribe_queue = [
                dict(r) for r in self._conn.execute(
                    "SELECT state, COUNT(*) AS n FROM transcribe_queue GROUP BY state")
            ]
        return {
            "rows": rows,
            "recordings_by_status": recordings,
            "transcribed_completed": transcribed,
            "media_jobs": media_jobs,
            "transcribe_queue": transcribe_queue,
        }

    def recording_bytes_by_day(self, limit_days: int = 120) -> list:
        """録画の日次増加(bytes)の実績。

        drive空きと違い、こちらは**遡って算出できる**: recordingsがstarted_atとbytesを
        最初から持っているためで、sampleを貯め始めるのを待つ必要がない(実測34日ぶん)。
        画面ではsample由来の系列と混ぜず、由来を分けて示すこと。
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT DATE(started_at, 'unixepoch', 'localtime') AS day,"
                " COUNT(*) AS recordings, COALESCE(SUM(bytes), 0) AS bytes"
                " FROM recordings WHERE started_at IS NOT NULL"
                " GROUP BY day ORDER BY day DESC LIMIT ?",
                (limit_days,),
            ).fetchall()
        return [
            {"day": r["day"], "recordings": r["recordings"], "bytes": r["bytes"]}
            for r in reversed(rows)
        ]

    def mark_stale_recordings(self) -> int:
        """On startup, recordings left 'recording' are orphaned (process died)."""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE recordings SET status = 'interrupted' WHERE status = 'recording'"
            )
            self._conn.commit()
        return cursor.rowcount

    def recordings_for_recovery(self) -> list:
        """クラッシュで中断した録画(status='recording'/'interrupted')を返す。捕捉済みHLS
        segmentがディスクに残っていればmp4へ再finalizeできるため、起動時の復元対象を列挙する。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, session_id, unique_id, path, filename, status, started_at, ended_at"
                " FROM recordings"
                " WHERE status IN ('recording', 'interrupted') ORDER BY started_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_transcript(self, recording_id: int) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT recording_id, language, model, text, segments_json, duration,"
                " created_at, timemap_version, timemap_anchors, timemap_drift_seconds"
                " FROM transcripts WHERE recording_id = ?",
                (recording_id,),
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["segments"] = json.loads(item.pop("segments_json"))
        return item

    def save_transcript(self, recording_id: int, result: dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO transcripts (recording_id, language, model, text, segments_json,"
                " duration, created_at, timemap_version, timemap_anchors, timemap_drift_seconds)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(recording_id) DO UPDATE SET"
                " language = excluded.language, model = excluded.model, text = excluded.text,"
                " segments_json = excluded.segments_json, duration = excluded.duration,"
                " created_at = excluded.created_at, timemap_version = excluded.timemap_version,"
                " timemap_anchors = excluded.timemap_anchors,"
                " timemap_drift_seconds = excluded.timemap_drift_seconds",
                (
                    recording_id,
                    result.get("language"),
                    result.get("model"),
                    result.get("text", ""),
                    json.dumps(result.get("segments", []), ensure_ascii=False),
                    result.get("duration"),
                    time.time(),
                    result.get("timemap_version"),
                    result.get("timemap_anchors"),
                    result.get("timemap_drift_seconds"),
                ),
            )
            self._conn.commit()
        logger.info(
            "transcript saved: recording_id=%d", recording_id,
            extra={"event": "stt.transcript_saved",
                   "ctx": {"timemap_version": result.get("timemap_version"),
                           "timemap_anchors": result.get("timemap_anchors"),
                           "timemap_drift_seconds": result.get("timemap_drift_seconds"),
                           "segments": len(result.get("segments", []))}},
        )

    def session_buckets(self, session_id: int, start: float | None = None,
                        end: float | None = None) -> list:
        """sessionの時間bucket(既定10秒粒度)。録画窓で絞ればheat barの素材になる。"""
        sql = ("SELECT start, gifts, diamonds, comments, likes, joins, follows, shares, viewers"
               " FROM buckets WHERE session_id = ?")
        params: list = [session_id]
        if start is not None:
            sql += " AND start >= ?"
            params.append(start)
        if end is not None:
            sql += " AND start <= ?"
            params.append(end)
        sql += " ORDER BY start"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    # ===== 横断検索index =====

    def replace_search_hits(self, recording_id: int, source: str, rows: list) -> int:
        """1録画・1source分のindexを差し替える。external content FTSはcontent表を
        DELETEしただけでは索引が残るので、必ず先に'delete'commandで索引を抜く。"""
        with self._lock:
            self._conn.execute(
                "INSERT INTO search_fts(search_fts, rowid, body)"
                " SELECT 'delete', id, body FROM search_hits"
                " WHERE recording_id = ? AND source = ?",
                (recording_id, source),
            )
            self._conn.execute(
                "DELETE FROM search_hits WHERE recording_id = ? AND source = ?",
                (recording_id, source),
            )
            for row in rows:
                cursor = self._conn.execute(
                    "INSERT INTO search_hits (source, recording_id, session_id, unique_id,"
                    " started_at, video_time, end_time, nickname, body)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        source,
                        recording_id,
                        row.get("session_id"),
                        row["unique_id"],
                        row["started_at"],
                        row["video_time"],
                        row.get("end_time"),
                        row.get("nickname"),
                        row["body"],
                    ),
                )
                self._conn.execute(
                    "INSERT INTO search_fts(rowid, body) VALUES (?, ?)",
                    (cursor.lastrowid, row["body"]),
                )
            self._conn.commit()
        return len(rows)

    def search_indexed_counts(self) -> dict:
        """recording_idごとのindex済み件数(source別)。画面のbadge用。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT recording_id, source, COUNT(*) AS n FROM search_hits"
                " GROUP BY recording_id, source"
            ).fetchall()
        out: dict = {}
        for row in rows:
            out.setdefault(row["recording_id"], {})[row["source"]] = row["n"]
        return out

    def search_scenes(self, query: str, sources: list, unique_ids: list | None = None,
                      since: float | None = None, until: float | None = None,
                      order: str = "time", limit: int = 200, offset: int = 0) -> dict:
        """転写segmentとcommentを横断して部分一致検索する。

        trigram tokenizerは3文字未満のtokenを作らないため、1-2文字のqueryはMATCHでは
        引けない。その場合だけbodyのLIKE走査へ落とす(件数が伸びるとFTSより遅いので、
        利用側は3文字以上を促すこと)。"""
        from tictok.search.query import QueryError, parse as parse_query

        if not sources:
            return {"total": 0, "items": [], "mode": "none", "hint": ""}
        try:
            parsed = parse_query(query)
        except QueryError as exc:
            return {"total": 0, "items": [], "mode": "none", "hint": str(exc)}

        where = ["h.source IN (%s)" % ",".join("?" * len(sources))]
        params: list = list(sources)
        if unique_ids:
            where.append("h.unique_id IN (%s)" % ",".join("?" * len(unique_ids)))
            params.extend(unique_ids)
        if since is not None:
            where.append("h.started_at >= ?")
            params.append(since)
        if until is not None:
            where.append("h.started_at <= ?")
            params.append(until)

        # 短い語(trigramでindexできない2文字以下)はLIKEで後段濾過する。MATCHと併用する
        # 限り走査対象はMATCHの結果に限られるので、全表LIKEにはならない。
        for pattern in parsed["like_all"]:
            where.append("h.body LIKE ? ESCAPE '\\'")
            params.append(pattern)
        for pattern in parsed["like_none"]:
            where.append("h.body NOT LIKE ? ESCAPE '\\'")
            params.append(pattern)

        if parsed["match"]:
            mode = "fts"
            base = ("FROM search_fts f JOIN search_hits h ON h.id = f.rowid"
                    " WHERE search_fts MATCH ? AND " + " AND ".join(where))
            params = [parsed["match"]] + params
            # snippet()の最終引数はtoken数だが、trigramでは1 token≒1文字(3文字窓を1文字ずつ
            # 作る)なので、語数のつもりの値を渡すとその文字数で切れる。1行=1コメント/1発話で
            # 元々短く、切る必要が無いのでhighlight()で全文を返す(LIKE経路とも表示が揃う)。
            select_extra = ", highlight(search_fts, 0, '\x02', '\x03') AS snippet"
            order_sql = ("ORDER BY bm25(search_fts)" if order == "rank"
                         else "ORDER BY h.started_at DESC, h.video_time")
        else:
            # 肯定語が全て2文字以下。indexが使えないので全表走査に落ちる。
            mode = "like"
            base = "FROM search_hits h WHERE " + " AND ".join(where)
            select_extra = ", h.body AS snippet"
            order_sql = "ORDER BY h.started_at DESC, h.video_time"

        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) AS n " + base, params).fetchone()["n"]
            rows = self._conn.execute(
                "SELECT h.id, h.source, h.recording_id, h.session_id, h.unique_id,"
                " h.started_at, h.video_time, h.end_time, h.nickname, h.body"
                + select_extra + " " + base + " " + order_sql + " LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()
        return {"total": total, "mode": mode, "hint": "", "terms": parsed["terms"],
                "items": [dict(row) for row in rows]}

    def search_hits_for(self, recording_id: int, source: str) -> list:
        """1録画・1source分のindex行を時間順で返す。意味検索がpassageへ束ねる際に使う。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, source, recording_id, session_id, unique_id, started_at,"
                " video_time, end_time, nickname, body FROM search_hits"
                " WHERE recording_id = ? AND source = ?"
                " ORDER BY video_time, id",
                (recording_id, source),
            ).fetchall()
        return [dict(row) for row in rows]

    def search_hit(self, hit_id: int) -> Optional[dict]:
        """id指定で1行返す。意味検索が返すidを画面表示用の行へ引き当てるのに使う。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT id, source, recording_id, session_id, unique_id, started_at,"
                " video_time, end_time, nickname, body FROM search_hits WHERE id = ?",
                (hit_id,),
            ).fetchone()
        return dict(row) if row else None

    def search_hit_groups(self) -> list:
        """(recording_id, source)ごとの件数と最大id。意味検索の差分build判定に使う。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT recording_id, source, COUNT(*) AS n, MAX(id) AS max_id"
                " FROM search_hits GROUP BY recording_id, source"
            ).fetchall()
        return [dict(row) for row in rows]

    # ===== 切り出し候補(cut list) =====

    def add_cut(self, recording_id: int, unique_id: str, start: float, end: float,
                label: str = "") -> dict:
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO cut_list (recording_id, unique_id, start, end, label, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (recording_id, unique_id, start, end, label, time.time()),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM cut_list WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return dict(row)

    def list_cuts(self) -> list:
        """cut listをNLEへ渡せる形で返す。pathはrecordingsから引く(移動後の値は
        呼び出し側が解決する)。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT c.*, r.path, r.filename, r.started_at AS recording_started_at"
                " FROM cut_list c LEFT JOIN recordings r ON r.id = c.recording_id"
                " ORDER BY c.unique_id, r.started_at, c.start"
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_cut(self, cut_id: int) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM cut_list WHERE id = ?", (cut_id,))
            self._conn.commit()
        return cursor.rowcount > 0

    def clear_cuts(self) -> int:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM cut_list")
            self._conn.commit()
        return cursor.rowcount

    # ===== 見どころ(bookmark) =====

    def add_bookmark(self, recording_id: int, unique_id: str, start: float,
                     end: Optional[float] = None, memo: str = "",
                     source_hit_id: Optional[int] = None) -> dict:
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO bookmarks"
                " (recording_id, unique_id, start, end, memo, source_hit_id, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (recording_id, unique_id, start, end, memo, source_hit_id, time.time()),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM bookmarks WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return dict(row)

    def add_live_bookmark(self, recording_id: int, unique_id: str, wall_time: float,
                          provisional_start: float, memo: str = "") -> dict:
        """配信を見ている最中に押された見どころ。

        押した瞬間に確定できるのはwall-clockだけで、mp4のPTS軸へはまだ載せられない
        (finalizeでtiming mapが書かれるまで対応が存在しない)。そこでwall-clockから出した
        暫定値をstartに入れ、pts_mapped=0で「まだPTS軸ではない」と明示する。確定は
        remap_live_bookmarks()が行う。

        provisional_startは録画開始からの経過秒。実測では最終的なPTSと数十〜数百秒ずれる
        (112分の録画で340秒)ので、確定値として扱ってはならない。"""
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO bookmarks"
                " (recording_id, unique_id, start, end, memo, source_hit_id,"
                "  live_wall, pts_mapped, created_at)"
                " VALUES (?, ?, ?, NULL, ?, NULL, ?, 0, ?)",
                (recording_id, unique_id, provisional_start, memo, wall_time, time.time()),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM bookmarks WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return dict(row)

    def list_unmapped_bookmarks(self, recording_id: int) -> list:
        """まだPTS軸へ載せていないlive見どころ(finalizeの再map対象)。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, start, live_wall FROM bookmarks"
                " WHERE recording_id = ? AND pts_mapped = 0 AND live_wall IS NOT NULL"
                " ORDER BY live_wall",
                (recording_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def apply_bookmark_pts(self, mapped: list) -> int:
        """再map結果を確定させる。mappedは [(bookmark_id, pts_start), ...]。

        再mapできなかった行はここへ渡さないこと。pts_mapped=0のまま残せば画面が暫定値だと
        言えるが、ここを通すと暫定値が確定値として固定されてしまう。"""
        if not mapped:
            return 0
        with self._lock:
            cursor = self._conn.executemany(
                "UPDATE bookmarks SET start = ?, pts_mapped = 1 WHERE id = ?",
                [(float(pts), int(bookmark_id)) for bookmark_id, pts in mapped],
            )
            self._conn.commit()
        return cursor.rowcount

    def list_bookmarks(self, recording_id: Optional[int] = None) -> list:
        """見どころ一覧。recording_id指定で1録画分(seek bar描画用)、無指定で全件(一覧tab用)。
        録画のfilename/開始時刻はどの配信のどこかを示すために結合する。"""
        sql = ("SELECT b.*, r.filename, r.started_at AS recording_started_at"
               " FROM bookmarks b LEFT JOIN recordings r ON r.id = b.recording_id")
        params: tuple = ()
        if recording_id is not None:
            sql += " WHERE b.recording_id = ?"
            params = (recording_id,)
        sql += " ORDER BY r.started_at DESC, b.start"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def update_bookmark_memo(self, bookmark_id: int, memo: str) -> Optional[dict]:
        with self._lock:
            self._conn.execute(
                "UPDATE bookmarks SET memo = ? WHERE id = ?", (memo, bookmark_id))
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM bookmarks WHERE id = ?", (bookmark_id,)).fetchone()
        return dict(row) if row else None

    def delete_bookmark(self, bookmark_id: int) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark_id,))
            self._conn.commit()
        return cursor.rowcount > 0

    # ===== 一括転写queue =====

    def enqueue_transcriptions(self, entries: list, priority: int = 0) -> int:
        """(recording_id, unique_id)をqueueへ投入する。既にdone/runningの録画は触らず、
        再投入で待ち行列を膨らませない。"""
        now = time.time()
        added = 0
        with self._lock:
            for recording_id, unique_id in entries:
                cursor = self._conn.execute(
                    "INSERT INTO transcribe_queue (recording_id, unique_id, state, priority, queued_at)"
                    " VALUES (?, ?, 'pending', ?, ?)"
                    " ON CONFLICT(recording_id) DO UPDATE SET"
                    " state = 'pending', priority = excluded.priority, queued_at = excluded.queued_at,"
                    " error = NULL, pct = 0"
                    " WHERE transcribe_queue.state IN ('failed', 'cancelled')",
                    (recording_id, unique_id, priority, now),
                )
                added += cursor.rowcount
            self._conn.commit()
        return added

    def next_pending_transcription(self) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM transcribe_queue WHERE state = 'pending'"
                " ORDER BY priority DESC, queued_at LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def set_transcription_state(self, recording_id: int, state: str,
                                pct: int | None = None, error: str | None = None) -> None:
        now = time.time()
        with self._lock:
            if state == "running":
                self._conn.execute(
                    "UPDATE transcribe_queue SET state = 'running', started_at = ?, pct = 0,"
                    " error = NULL WHERE recording_id = ?", (now, recording_id))
            elif state in ("done", "failed", "cancelled"):
                self._conn.execute(
                    "UPDATE transcribe_queue SET state = ?, finished_at = ?, error = ?,"
                    " pct = ? WHERE recording_id = ?",
                    (state, now, error, 100 if state == "done" else (pct or 0), recording_id))
            else:
                self._conn.execute(
                    "UPDATE transcribe_queue SET state = ?, pct = ? WHERE recording_id = ?",
                    (state, pct or 0, recording_id))
            self._conn.commit()

    def update_transcription_pct(self, recording_id: int, pct: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE transcribe_queue SET pct = ? WHERE recording_id = ?", (pct, recording_id))
            self._conn.commit()

    def list_transcribe_queue(self) -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT q.*, r.filename, r.started_at AS recording_started_at,"
                " r.ended_at AS recording_ended_at"
                " FROM transcribe_queue q LEFT JOIN recordings r ON r.id = q.recording_id"
                " ORDER BY CASE q.state WHEN 'running' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END,"
                " q.priority DESC, q.queued_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def count_transcribe_queue_by_state(self) -> dict:
        """state別の件数。job画面のGPU現況が転写queueの実状を併記するために使う軽量query
        (一覧を取って数えると、表示しない全行をpollのたびに読むことになる)。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT state, COUNT(*) AS n FROM transcribe_queue GROUP BY state"
            ).fetchall()
        return {row["state"]: row["n"] for row in rows}

    def cancel_transcriptions(self, recording_ids: list | None = None) -> int:
        """pendingのみ取り消す。runningはSTTの実行中で、途中で止める手段が無い。"""
        with self._lock:
            if recording_ids:
                cursor = self._conn.execute(
                    "UPDATE transcribe_queue SET state = 'cancelled', finished_at = ?"
                    " WHERE state = 'pending' AND recording_id IN (%s)"
                    % ",".join("?" * len(recording_ids)),
                    [time.time()] + list(recording_ids))
            else:
                cursor = self._conn.execute(
                    "UPDATE transcribe_queue SET state = 'cancelled', finished_at = ?"
                    " WHERE state = 'pending'", (time.time(),))
            self._conn.commit()
        return cursor.rowcount

    def reset_running_transcriptions(self) -> int:
        """起動時: 前回processが落ちて'running'のまま残った行をpendingへ戻す。"""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE transcribe_queue SET state = 'pending', started_at = NULL, pct = 0"
                " WHERE state = 'running'")
            self._conn.commit()
        return cursor.rowcount

    def untranscribed_recordings(self, unique_id: str | None = None) -> list:
        """転写もqueue登録もされていない完了録画。配信者単位の一括投入に使う。"""
        sql = ("SELECT r.id, r.unique_id, r.filename, r.path, r.started_at, r.ended_at"
               " FROM recordings r"
               " LEFT JOIN transcripts t ON t.recording_id = r.id"
               " LEFT JOIN transcribe_queue q ON q.recording_id = r.id"
               " WHERE r.status = 'completed' AND t.recording_id IS NULL"
               " AND (q.recording_id IS NULL OR q.state IN ('failed', 'cancelled'))")
        params: list = []
        if unique_id:
            sql += " AND r.unique_id = ?"
            params.append(unique_id)
        sql += " ORDER BY r.started_at DESC"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    # ===== 映像job queue(焼き込み / Up出力 / 再mp4化) =====

    @staticmethod
    def _media_job_row(row: sqlite3.Row) -> dict:
        item = dict(row)
        item["result"] = json.loads(item.pop("result_json") or "{}")
        item["params"] = json.loads(item.pop("params_json", None) or "{}")
        return item

    def enqueue_media_job(self, job_id: str, kind: str, recording_id: int, *,
                          session_id: Optional[int] = None, group_id: str = "",
                          title: str = "", priority: int = 0,
                          params: Optional[dict] = None) -> dict:
        """1件投入して行を返す。重複投入の抑止は呼び出し側(pending_media_job_for)で行う:
        「同じ焼き込みをもう一度」は再出力として正当な要求なので、ここでは拒まない。"""
        with self._lock:
            self._conn.execute(
                "INSERT INTO media_job_queue"
                " (job_id, kind, recording_id, session_id, group_id, title, state,"
                "  priority, queued_at, params_json)"
                " VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
                (job_id, kind, recording_id, session_id, group_id, title, priority,
                 time.time(), json.dumps(params or {}, ensure_ascii=False)),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM media_job_queue WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._media_job_row(row)

    def busy_recording_ids(self) -> set:
        """焼き込み/Up出力/転写が待機・実行中の録画id。

        これらのjobはsrc mp4を実行中に読むため、消すと道半ばで壊れたjobだけが残る。
        容量整理の一括削除が対象から外すために使う。"""
        with self._lock:
            media = self._conn.execute(
                "SELECT DISTINCT recording_id FROM media_job_queue"
                " WHERE state IN ('pending', 'running') AND recording_id IS NOT NULL"
            ).fetchall()
            stt = self._conn.execute(
                "SELECT recording_id FROM transcribe_queue"
                " WHERE state IN ('pending', 'running')"
            ).fetchall()
        return {row["recording_id"] for row in media} | {row["recording_id"] for row in stt}

    def pending_media_job_for(self, kind: str, recording_id: int) -> Optional[dict]:
        """同じ録画・同じ種別で既に待機/実行中のjob。二重投入を弾くために使う。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM media_job_queue"
                " WHERE kind = ? AND recording_id = ? AND state IN ('pending', 'running')"
                " ORDER BY queued_at LIMIT 1",
                (kind, recording_id),
            ).fetchone()
        return self._media_job_row(row) if row else None

    def pending_media_job_keys(self) -> set:
        """待機/実行中の全jobの (kind, recording_id) 集合。一括画面は録画ごとに二重投入を
        弾く判定を行うが、録画数ぶんの個別queryを回すと重い。1回で引いて集合の照合にする。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT kind, recording_id FROM media_job_queue"
                " WHERE state IN ('pending', 'running')"
            ).fetchall()
        return {(row["kind"], row["recording_id"]) for row in rows}

    def next_pending_media_job(self) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM media_job_queue WHERE state = 'pending'"
                " ORDER BY priority DESC, queued_at LIMIT 1"
            ).fetchone()
        return self._media_job_row(row) if row else None

    def claim_next_pending_media_job(self) -> Optional[dict]:
        """次の待機jobをrunningへ落として返す(無ければNone)。

        選ぶのと掴むのを1つのlockの中で済ませるのは、workerが複数居るときに同じ行を
        2人が拾わないため。取得と開始が別呼び出しだと、その隙間で同じ録画へ2本の
        ffmpegが走り、同じ出力fileを奪い合う。

        同じ録画に対する別種のjobも同時には出さない。再mp4化は録画のmp4を作り直して
        差し替えるので、その裏で同じmp4を読んでいる焼き込みは途中で足元を抜かれる。
        直列workerの時代はこれが起こり得なかったため、並列化と一緒に明示する。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT job_id FROM media_job_queue WHERE state = 'pending'"
                " AND (not_before IS NULL OR not_before <= ?)"
                " AND recording_id NOT IN ("
                "   SELECT recording_id FROM media_job_queue"
                "   WHERE state = 'running' AND recording_id IS NOT NULL)"
                " ORDER BY priority DESC, queued_at LIMIT 1",
                (time.time(),),
            ).fetchone()
            if row is None:
                return None
            job_id = row["job_id"]
            self._conn.execute(
                "UPDATE media_job_queue SET state = 'running', started_at = ?, pct = 0,"
                " stage = '', error = NULL WHERE job_id = ?",
                (time.time(), job_id),
            )
            self._conn.commit()
            claimed = self._conn.execute(
                "SELECT * FROM media_job_queue WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._media_job_row(claimed) if claimed else None

    def get_media_job(self, job_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM media_job_queue WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._media_job_row(row) if row else None

    def start_media_job(self, job_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE media_job_queue SET state = 'running', started_at = ?, pct = 0,"
                " stage = '', error = NULL WHERE job_id = ?",
                (time.time(), job_id),
            )
            self._conn.commit()

    def update_media_job_progress(self, job_id: str, pct: int, stage: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE media_job_queue SET pct = ?, stage = ? WHERE job_id = ?",
                (max(0, min(100, int(pct))), stage, job_id),
            )
            self._conn.commit()

    def finish_media_job(self, job_id: str, state: str, *, error: Optional[str] = None,
                         result: Optional[dict] = None) -> None:
        # stageは「いま何をしているか」であって終わり方ではない。終端で消さないと、取り消し
        # 要求時に書いた『取り消し中…』が終了後の行にも残り、stateはcancelledなのに画面は
        # まだ止めようとしているように見える。
        with self._lock:
            self._conn.execute(
                "UPDATE media_job_queue SET state = ?, finished_at = ?, error = ?, stage = '',"
                " pct = CASE WHEN ? = 'completed' THEN 100 ELSE pct END,"
                " result_json = COALESCE(?, result_json) WHERE job_id = ?",
                (state, time.time(), error, state,
                 json.dumps(result, ensure_ascii=False) if result is not None else None,
                 job_id),
            )
            self._conn.commit()

    def defer_media_job(self, job_id: str, not_before: float, stage: str) -> None:
        """実行中のjobを待機へ戻し、``not_before`` まで拾わせない。

        失敗ではないのでattemptも消費しないし、finished_atも書かない。前提(保存先volume)が
        戻れば同じ行がそのまま走り出す。``deferred_since`` は最初の1回だけ立て、以後の
        延長でも上書きしない — ここを毎回更新すると、待ち続けるjobが打ち切りに掛からない。"""
        with self._lock:
            self._conn.execute(
                "UPDATE media_job_queue SET state = 'pending', started_at = NULL,"
                " pct = 0, stage = ?, error = NULL, not_before = ?,"
                " deferred_since = COALESCE(deferred_since, ?) WHERE job_id = ?",
                (stage, not_before, time.time(), job_id),
            )
            self._conn.commit()

    REQUEUEABLE_STATES = ("failed", "interrupted", "cancelled")

    def requeue_media_jobs(self, job_ids, *, auto: bool = False) -> int:
        """終わってしまったjobを待機へ戻す。戻した件数を返す。

        対象は failed / interrupted / cancelled だけ。completed を戻せると「もう一度出力」と
        区別が付かなくなる(あれは新しい投入であって、同じ行の再開ではない)。``result_json``は
        捨てる: 失敗時の退避先が残ったままだと、起動時のrecoveryが次の実行で作った成果物を
        古い退避で上書きしかねない。

        ``auto`` は起動時の自動再開ぶん。回数を params へ数え、呼び出し側が上限で打ち切れる
        ようにする — processごと落とすjobを無条件に戻すと、起動のたびに同じ落ち方を繰り返す。
        """
        ids = [str(j) for j in job_ids]
        if not ids:
            return 0
        requeued = 0
        with self._lock:
            for job_id in ids:
                row = self._conn.execute(
                    "SELECT state, params_json FROM media_job_queue WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
                if row is None or row["state"] not in self.REQUEUEABLE_STATES:
                    continue
                params = json.loads(row["params_json"] or "{}")
                if auto:
                    params["auto_requeues"] = int(params.get("auto_requeues") or 0) + 1
                self._conn.execute(
                    "UPDATE media_job_queue SET state = 'pending', queued_at = ?,"
                    " started_at = NULL, finished_at = NULL, pct = 0, stage = '',"
                    " error = NULL, not_before = NULL, deferred_since = NULL,"
                    " result_json = '{}', params_json = ? WHERE job_id = ?",
                    (time.time(), json.dumps(params, ensure_ascii=False), job_id),
                )
                requeued += 1
            self._conn.commit()
        return requeued

    def set_media_job_result(self, job_id: str, result: dict) -> None:
        """実行の途中で判明した後始末情報を、終了を待たずに残す。再mp4化が元mp4を_backupへ
        退避した直後の退避先がこれで、processがここで落ちると起動時のrecoveryが唯一の
        復元手段になる(退避先を覚えていなければ、mp4の在り処は誰にも分からない)。"""
        with self._lock:
            self._conn.execute(
                "UPDATE media_job_queue SET result_json = ? WHERE job_id = ?",
                (json.dumps(result, ensure_ascii=False), job_id),
            )
            self._conn.commit()

    def list_media_jobs(self, limit: int = 200) -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT q.*, r.filename, r.unique_id, r.path AS recording_path"
                " FROM media_job_queue q LEFT JOIN recordings r ON r.id = q.recording_id"
                " ORDER BY CASE q.state WHEN 'running' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END,"
                " q.priority DESC, COALESCE(q.finished_at, q.started_at, q.queued_at) DESC"
                " LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._media_job_row(row) for row in rows]

    def media_job_durations(self, kind: str, limit: int = 50) -> list:
        """完了したjobの実測 (所要秒, 元録画の尺秒) を新しい順に返す。

        配信者まるごとの一括投入は所要時間を先に見せないと押せないが、その倍率を設定値や
        定数で持つとGPU・model・解像度が違う環境で必ず外れる。実績が1件も無ければ空listを
        返し、呼び出し側は「不明」と出す(推測値を出すと、根拠のある数字と区別できない)。

        尺の出所は実測(duration_seconds)だけ。壁時計で割ると、捕捉が停滞した録画や
        ended_atが再処理時刻に潰れた録画で分母が数十倍になり、倍率が桁ごと狂う。
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT q.started_at, q.finished_at, r.duration_seconds AS source"
                " FROM media_job_queue q JOIN recordings r ON r.id = q.recording_id"
                " WHERE q.kind = ? AND q.state = 'completed'"
                " AND q.started_at IS NOT NULL AND q.finished_at IS NOT NULL"
                " AND r.duration_seconds IS NOT NULL"
                " ORDER BY q.finished_at DESC LIMIT ?",
                (kind, limit),
            ).fetchall()
        pairs = []
        for row in rows:
            elapsed = row["finished_at"] - row["started_at"]
            if elapsed > 0 and row["source"] > 0:
                pairs.append((elapsed, row["source"]))
        return pairs

    def media_jobs_in_group(self, group_id: str) -> list:
        """session一括投入の1回分。group進捗はこの集合から毎回組み直す(集計値を別に持つと、
        片方だけ更新された瞬間に画面とDBが食い違う)。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM media_job_queue WHERE group_id = ? ORDER BY queued_at, id",
                (group_id,),
            ).fetchall()
        return [self._media_job_row(row) for row in rows]

    def cancel_pending_media_job(self, job_id: str) -> bool:
        """待機中のjobを取り消す。実行中はDB更新だけでは止まらない(worker側でtokenを
        投げる必要がある)ので、ここでは対象外にしている。"""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE media_job_queue SET state = 'cancelled', finished_at = ?, stage = ''"
                " WHERE job_id = ? AND state = 'pending'",
                (time.time(), job_id),
            )
            self._conn.commit()
        return cursor.rowcount > 0

    def interrupt_running_media_jobs(self) -> list:
        """起動時: 前回processが落ちて'running'のまま残った行を返し、'interrupted'にする。

        転写queueのようにここでpendingへ戻さないのは、映像jobが中途の成果物(退避したmp4・
        部分出力)を残したまま死んでいる可能性があるためで、後始末を済ませるまで自動で走らせては
        いけない。返した行はserver側のrecoveryが個別に処理し、原状へ戻した上で待機列へ戻す
        (``requeue_media_jobs(auto=True)``)。順序が逆だと、断片の上から作り直しが始まる。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM media_job_queue WHERE state = 'running'"
            ).fetchall()
            self._conn.execute(
                "UPDATE media_job_queue SET state = 'interrupted', finished_at = ?, stage = '',"
                " error = 'server再起動により中断されました。' WHERE state = 'running'",
                (time.time(),),
            )
            self._conn.commit()
        return [self._media_job_row(row) for row in rows]

    def prune_media_jobs(self, older_than_seconds: float) -> int:
        """終了済みの古い行を消す。0以下なら消さない(履歴を全部残す運用)。"""
        if older_than_seconds <= 0:
            return 0
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM media_job_queue"
                " WHERE state NOT IN ('pending', 'running') AND finished_at < ?",
                (time.time() - older_than_seconds,),
            )
            self._conn.commit()
        return cursor.rowcount

    def get_settings(self) -> dict:
        with self._lock:
            rows = self._conn.execute("SELECT key, value FROM settings").fetchall()
        return {row["key"]: row["value"] for row in rows}

    def set_settings(self, values: dict) -> None:
        with self._lock:
            self._conn.executemany(
                "INSERT INTO settings (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                [(key, str(value)) for key, value in values.items()],
            )
            self._conn.commit()

    def add_monitored_target(self, unique_id: str, record_video: bool = True) -> None:
        # ON CONFLICT DO NOTHING keeps an existing target's record_video preference
        # intact when the same monitor is (re)started; a removed-then-readded target
        # has no row, so the supplied value is applied fresh.
        with self._lock:
            self._conn.execute(
                "INSERT INTO monitored_targets (unique_id, added_at, record_video) VALUES (?, ?, ?)"
                " ON CONFLICT(unique_id) DO NOTHING",
                (unique_id, time.time(), 1 if record_video else 0),
            )
            self._conn.commit()

    def set_target_record_video(self, unique_id: str, record_video: bool) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE monitored_targets SET record_video = ? WHERE unique_id = ?",
                (1 if record_video else 0, unique_id),
            )
            self._conn.commit()

    def get_target_record_video(self, unique_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT record_video FROM monitored_targets WHERE unique_id = ?",
                (unique_id,),
            ).fetchone()
        return bool(row["record_video"]) if row is not None else True

    def remove_monitored_target(self, unique_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM monitored_targets WHERE unique_id = ?", (unique_id,)
            )
            self._conn.commit()

    def list_monitored_targets(self) -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT unique_id, record_video FROM monitored_targets ORDER BY added_at"
            ).fetchall()
        return [
            {"unique_id": row["unique_id"], "record_video": bool(row["record_video"])}
            for row in rows
        ]

    def _unidentified_gift_summary(self) -> dict:
        """台帳から外した身元不明eventの規模。黙って除外すると「Fan台帳の合計がSessionの
        coin合計と合わない」理由が画面から辿れなくなるため、件数と額を返して明示する。"""
        placeholders = ",".join("?" for _ in NON_IDENTITY_KEYS)
        row = self._conn.execute(
            "SELECT COUNT(*) AS events, COALESCE(SUM(diamonds), 0) AS diamonds"
            " FROM events WHERE kind = 'gift'"
            f" AND (identity_key IS NULL OR identity_key IN ({placeholders}))",
            NON_IDENTITY_KEYS,
        ).fetchone()
        return {"gift_events": row["events"] or 0, "diamonds": row["diamonds"] or 0}

    def fan_ledger(self, min_diamonds: int, limit: int) -> dict:
        """視聴者を主語にしたgift台帳。誰がどの配信者へ幾ら投げたかを横断で集計する。

        既存の配信者別gifter集計(streamer_profile)と同じqueryの形を使い、配信者での絞りを
        外して「identity_key × 配信者」で割る。こうすると1度の走査で通算と配信者別内訳の
        両方が出るので、内訳のために引き直さなくて済む。

        gift eventを持つ視聴者だけを台帳に載せる。events全kindを横断すると視聴者は35,000人
        規模になり(実測)、一覧として使えないうえ走査も一桁遅くなる。commentしかしない視聴者は
        別の指標であり、台帳の主題(誰が幾ら投じたか)とは分けて扱う。
        """
        placeholders = ",".join("?" for _ in NON_IDENTITY_KEYS)
        exclude = (
            f" AND e.identity_key IS NOT NULL AND e.identity_key NOT IN ({placeholders})"
        )
        with self._lock:
            rows = self._conn.execute(
                # 表示名はusers表を優先する。MAX(e.user_unique_id)は辞書順の最大を拾うだけで
                # 「最新のhandle」ではなく、実測では改名前の自動生成handle(user5037930325926)が
                # 現handle(harehare12345)を押しのけた。users表は毎eventで最新へupsertされる
                # 唯一の真実なので、eventの値はusers側が空のときだけ使う。
                "SELECT e.identity_key AS key, s.unique_id AS owner,"
                " COALESCE(NULLIF(u.user_id, ''), MAX(e.user_id)) AS user_id,"
                " COALESCE(NULLIF(u.unique_id, ''), MAX(e.user_unique_id)) AS unique_id,"
                " COALESCE(NULLIF(u.nickname, ''), MAX(e.user_nickname)) AS nickname,"
                " COALESCE(NULLIF(u.avatar, ''), MAX(e.user_avatar)) AS avatar,"
                " u.gifter_level AS gifter_level, u.first_seen AS first_seen,"
                " u.last_seen AS last_seen, SUM(e.diamonds) AS diamonds,"
                " SUM(e.gift_count) AS gifts, COUNT(DISTINCT e.session_id) AS sessions,"
                " MIN(e.time) AS first_gift, MAX(e.time) AS last_gift"
                " FROM events e JOIN sessions s ON s.id = e.session_id"
                " LEFT JOIN users u ON u.identity_key = e.identity_key"
                " WHERE e.kind = 'gift'" + exclude +
                " GROUP BY e.identity_key, s.unique_id",
                NON_IDENTITY_KEYS,
            ).fetchall()
            # commentは別kindなのでgiftの集計には相乗りできない。identity単位の件数だけを
            # 軽く引いて畳む(実測14ms)。全kindの横断走査は一覧には重すぎる。
            comment_rows = self._conn.execute(
                "SELECT e.identity_key AS key, COUNT(*) AS comments FROM events e"
                " WHERE e.kind = 'comment'" + exclude + " GROUP BY e.identity_key",
                NON_IDENTITY_KEYS,
            ).fetchall()
            unidentified = self._unidentified_gift_summary()

        comments = {r["key"]: r["comments"] or 0 for r in comment_rows}
        fans: dict = {}
        for row in rows:
            fan = fans.setdefault(
                row["key"],
                {
                    "identity_key": row["key"],
                    "user_id": row["user_id"] or "",
                    "unique_id": row["unique_id"] or "",
                    "nickname": row["nickname"] or row["unique_id"] or "(unknown)",
                    "avatar": row["avatar"] or "",
                    "gifter_level": row["gifter_level"] or 0,
                    "first_seen": row["first_seen"],
                    "last_seen": row["last_seen"],
                    "diamonds": 0,
                    "gifts": 0,
                    "sessions": 0,
                    "comments": comments.get(row["key"], 0),
                    "first_gift": None,
                    "last_gift": None,
                    "streamers": [],
                },
            )
            fan["diamonds"] += row["diamonds"] or 0
            fan["gifts"] += row["gifts"] or 0
            fan["sessions"] += row["sessions"] or 0
            for field, source, pick in (
                ("first_gift", "first_gift", min), ("last_gift", "last_gift", max),
            ):
                value = row[source]
                if value is not None:
                    current = fan[field]
                    fan[field] = value if current is None else pick(current, value)
            fan["streamers"].append(
                {
                    "unique_id": row["owner"],
                    "diamonds": row["diamonds"] or 0,
                    "gifts": row["gifts"] or 0,
                    "sessions": row["sessions"] or 0,
                }
            )

        for fan in fans.values():
            # 配信者別は必ず額の降順。「2人へ投げている」だけでは実態が分からず、実測では
            # 286,946 対 3 coin のような極端な偏りが普通にある。額を並べて出す。
            fan["streamers"].sort(key=lambda s: -s["diamonds"])
            fan["streamer_count"] = len(fan["streamers"])

        eligible = [f for f in fans.values() if f["diamonds"] >= min_diamonds]
        eligible.sort(key=lambda f: (-f["diamonds"], -f["gifts"]))
        multi = sum(1 for f in fans.values() if f["streamer_count"] > 1)
        logger.info(
            "fan ledger: %d shown of %d eligible (%d gifters, %d multi-streamer,"
            " min_diamonds=%d)",
            min(len(eligible), limit), len(eligible), len(fans), multi, min_diamonds,
            extra={"event": "storage.fan_ledger_scanned",
                   "ctx": {"gifters": len(fans), "eligible": len(eligible),
                           "multi_streamer": multi,
                           "unidentified_gift_events": unidentified["gift_events"]}},
        )
        return {
            "fans": eligible[:limit],
            "eligible": len(eligible),
            "total_gifters": len(fans),
            "multi_streamer": multi,
            "unidentified": unidentified,
            "min_diamonds": min_diamonds,
            "limit": limit,
            "generated_at": time.time(),
        }

    def fan_profile(self, identity_key: str) -> dict:
        """1人ぶんの台帳。配信者別の内訳とSession単位の明細を返す。

        eventの生行は返さない。実測で最上位のfanは47,000行(大半がlike)を持ち、明細として
        読めないうえ転送も走査も無駄になる。Session粒度まで畳んだものが台帳の単位である。
        """
        if identity_key in NON_IDENTITY_KEYS:
            raise ValueError("identity_key は1人の視聴者を指しません")
        with self._lock:
            identity = self._conn.execute(
                "SELECT identity_key, user_id, unique_id, nickname, avatar,"
                " fans_level, gifter_level, gifter_badge, first_seen, last_seen"
                " FROM users WHERE identity_key = ?",
                (identity_key,),
            ).fetchone()
            if identity is None:
                return {}
            session_rows = self._conn.execute(
                "SELECT e.session_id AS session_id, s.unique_id AS owner,"
                " s.started_at AS started_at, SUM(e.diamonds) AS diamonds,"
                " SUM(e.gift_count) AS gifts, MIN(e.time) AS first_gift,"
                " MAX(e.time) AS last_gift"
                " FROM events e JOIN sessions s ON s.id = e.session_id"
                " WHERE e.identity_key = ? AND e.kind = 'gift'"
                " GROUP BY e.session_id ORDER BY s.started_at DESC",
                (identity_key,),
            ).fetchall()
            kind_rows = self._conn.execute(
                "SELECT kind, COUNT(*) AS n FROM events WHERE identity_key = ?"
                " GROUP BY kind",
                (identity_key,),
            ).fetchall()

        sessions = [
            {
                "session_id": r["session_id"],
                "unique_id": r["owner"],
                "started_at": r["started_at"],
                "diamonds": r["diamonds"] or 0,
                "gifts": r["gifts"] or 0,
                "first_gift": r["first_gift"],
                "last_gift": r["last_gift"],
            }
            for r in session_rows
        ]
        by_streamer: dict = {}
        for s in sessions:
            entry = by_streamer.setdefault(
                s["unique_id"],
                {"unique_id": s["unique_id"], "diamonds": 0, "gifts": 0, "sessions": 0,
                 "first_gift": None, "last_gift": None},
            )
            entry["diamonds"] += s["diamonds"]
            entry["gifts"] += s["gifts"]
            entry["sessions"] += 1
            for field, pick in (("first_gift", min), ("last_gift", max)):
                value = s[field]
                if value is not None:
                    current = entry[field]
                    entry[field] = value if current is None else pick(current, value)
        streamers = sorted(by_streamer.values(), key=lambda e: -e["diamonds"])
        return {
            "identity_key": identity["identity_key"],
            "user_id": identity["user_id"] or "",
            "unique_id": identity["unique_id"] or "",
            "nickname": identity["nickname"] or identity["unique_id"] or "(unknown)",
            "avatar": identity["avatar"] or "",
            "fans_level": identity["fans_level"] or 0,
            "gifter_level": identity["gifter_level"] or 0,
            "gifter_badge": identity["gifter_badge"] or "",
            "first_seen": identity["first_seen"],
            "last_seen": identity["last_seen"],
            "diamonds": sum(s["diamonds"] for s in sessions),
            "gifts": sum(s["gifts"] for s in sessions),
            "activity": {r["kind"]: r["n"] for r in kind_rows},
            "streamers": streamers,
            "sessions": sessions,
        }

    def dismiss_discovery_candidate(self, unique_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO discovery_dismissed (unique_id, dismissed_at) VALUES (?, ?)"
                " ON CONFLICT(unique_id) DO UPDATE SET dismissed_at = excluded.dismissed_at",
                (unique_id, time.time()),
            )
            self._conn.commit()

    def restore_discovery_candidate(self, unique_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM discovery_dismissed WHERE unique_id = ?", (unique_id,)
            )
            self._conn.commit()

    def list_dismissed_candidates(self) -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT unique_id, dismissed_at FROM discovery_dismissed"
                " ORDER BY dismissed_at DESC"
            ).fetchall()
        return [
            {"unique_id": row["unique_id"], "dismissed_at": row["dismissed_at"]}
            for row in rows
        ]

    def discovery_candidates(
        self, min_contacts: int, half_life_days: float, limit: int
    ) -> dict:
        """未監視だがBattleで繰り返し当たっている配信者を、接触の多い順に返す。

        順位は「時間減衰つき接触回数」= Σ 0.5^(経過日数 / 半減期) で決める。生の回数だけ
        で並べると、もう当たらなくなった相手がいつまでも上位に居座り、逆に直近だけを見ると
        たまたま1回当たった相手が常連を押しのける。半減期つきの減衰和は両方を1つの値に
        まとめる標準的なやり方で、半減期は設定で変えられる。

        同じBattleは(battle_id, 相手)単位で1回だけ数える。1つのBattleを複数の監視配信者が
        別々のsessionで観測する(同陣営に2人監視している/両陣営とも監視対象)ため、素直に
        数えると同じ対戦が接触2回に化ける。

        start_time / battle_id を欠くBattleは数えない。どちらも減衰にも重複除外にも必須で、
        代わりの値を当てると「実際には無かった接触」を作ることになる。
        """
        if half_life_days <= 0:
            raise ValueError("half_life_days must be positive")
        with self._lock:
            rows = self._conn.execute(
                "SELECT b.data_json AS data_json, s.unique_id AS own_id"
                " FROM battles b JOIN sessions s ON s.id = b.session_id"
            ).fetchall()
            monitored = {
                r["unique_id"]
                for r in self._conn.execute("SELECT unique_id FROM monitored_targets")
            }
            dismissed = {
                r["unique_id"]
                for r in self._conn.execute("SELECT unique_id FROM discovery_dismissed")
            }

        now = time.time()
        aggregated: dict = {}
        seen_contacts = set()
        skipped_unidentified = 0
        skipped_incomplete = 0
        for row in rows:
            battle = json.loads(row["data_json"])
            start_time = battle.get("start_time")
            battle_id = battle.get("battle_id")
            if start_time is None or not battle_id:
                skipped_incomplete += 1
                continue
            age_days = max(0.0, (now - start_time) / 86400.0)
            weight = 0.5 ** (age_days / half_life_days)
            for opponent in battle.get("opponents", []) or []:
                # unique_id(=@handle)が無い相手は監視を開始する手段が無い。nicknameは
                # 変わるうえ重複するので、代わりのkeyにはできない。
                handle = (opponent.get("unique_id") or "").strip()
                if not handle:
                    skipped_unidentified += 1
                    continue
                if handle in monitored or handle in dismissed:
                    continue
                entry = aggregated.setdefault(
                    handle,
                    {
                        "unique_id": handle,
                        "nickname": opponent.get("nickname") or handle,
                        "avatar": opponent.get("avatar") or "",
                        "user_id": opponent.get("user_id") or "",
                        "contacts": 0,
                        "score": 0.0,
                        "first_contact": start_time,
                        "last_contact": start_time,
                        "via": set(),
                    },
                )
                # viaは重複観測でも積む。「同じBattleを2人が見た」ことは接触2回では
                # ないが、その相手が2人の監視配信者と当たっている事実は候補の判断材料
                # であり、1件目の観測者だけ残すとその情報が落ちる。
                entry["via"].add(row["own_id"])
                if not entry["avatar"] and opponent.get("avatar"):
                    entry["avatar"] = opponent["avatar"]
                contact = (battle_id, handle)
                if contact in seen_contacts:
                    continue
                seen_contacts.add(contact)
                entry["contacts"] += 1
                entry["score"] += weight
                entry["first_contact"] = min(entry["first_contact"], start_time)
                entry["last_contact"] = max(entry["last_contact"], start_time)

        eligible = [e for e in aggregated.values() if e["contacts"] >= min_contacts]
        eligible.sort(key=lambda e: (-e["score"], -e["last_contact"]))
        candidates = []
        for entry in eligible[:limit]:
            candidate = dict(entry)
            candidate["via"] = sorted(entry["via"])
            candidate["score"] = round(entry["score"], 3)
            candidates.append(candidate)

        logger.info(
            "discovery candidates: %d shown of %d eligible (%d seen, min_contacts=%d,"
            " half_life=%.1fd)",
            len(candidates), len(eligible), len(aggregated), min_contacts, half_life_days,
            extra={"event": "storage.discovery_scanned",
                   "ctx": {"shown": len(candidates), "eligible": len(eligible),
                           "seen": len(aggregated), "monitored": len(monitored),
                           "dismissed": len(dismissed),
                           "skipped_unidentified": skipped_unidentified,
                           "skipped_incomplete": skipped_incomplete}},
        )
        return {
            "candidates": candidates,
            "eligible": len(eligible),
            "seen": len(aggregated),
            "dismissed": len(dismissed),
            "skipped_unidentified": skipped_unidentified,
            "skipped_incomplete": skipped_incomplete,
            "min_contacts": min_contacts,
            "half_life_days": half_life_days,
            "limit": limit,
            "generated_at": now,
        }

    def session_rankings(self, limit: int) -> dict:
        with self._lock:
            base_rows = self._conn.execute(
                "SELECT id, unique_id, started_at, ended_at, stats_json FROM sessions",
            ).fetchall()
            agg_rows = self._conn.execute(
                "SELECT session_id,"
                " SUM(CASE WHEN kind = 'like' THEN count ELSE 0 END) AS like_count,"
                " SUM(CASE WHEN kind = 'comment' THEN 1 ELSE 0 END) AS comments,"
                " SUM(CASE WHEN kind = 'gift' THEN diamonds ELSE 0 END) AS diamonds"
                " FROM events GROUP BY session_id",
            ).fetchall()
        agg = {r["session_id"]: r for r in agg_rows}
        sessions = []
        for row in base_rows:
            a = agg.get(row["id"])
            stats = json.loads(row["stats_json"])
            likes_total = stats.get("likes_total")
            likes = likes_total if likes_total is not None else ((a["like_count"] if a else 0) or 0)
            sessions.append(
                {
                    "id": row["id"],
                    "unique_id": row["unique_id"],
                    "started_at": row["started_at"],
                    "ended_at": row["ended_at"],
                    "likes": likes,
                    "comments": (a["comments"] if a else 0) or 0,
                    "diamonds": (a["diamonds"] if a else 0) or 0,
                    "battle_points": stats.get("battle_points") or 0,
                }
            )

        def ranked(metric: str) -> list:
            ordered = sorted(sessions, key=lambda s: s[metric] or 0, reverse=True)
            return [
                {
                    "session_id": s["id"],
                    "unique_id": s["unique_id"],
                    "started_at": s["started_at"],
                    "ended_at": s["ended_at"],
                    "value": s[metric] or 0,
                }
                for s in ordered[:limit]
            ]

        return {
            "likes": ranked("likes"),
            "comments": ranked("comments"),
            "gifts": ranked("diamonds"),
            "battles": ranked("battle_points"),
        }

    def aggregate_dashboard(self) -> dict:
        with self._lock:
            totals = self._conn.execute(
                "SELECT"
                " (SELECT COUNT(*) FROM sessions) AS sessions,"
                " (SELECT COUNT(*) FROM recordings) AS recordings,"
                " COALESCE(SUM(CASE WHEN kind = 'gift' THEN gift_count ELSE 0 END), 0) AS gifts,"
                " COALESCE(SUM(CASE WHEN kind = 'gift' THEN diamonds ELSE 0 END), 0) AS diamonds,"
                " COALESCE(SUM(CASE WHEN kind = 'comment' THEN 1 ELSE 0 END), 0) AS comments,"
                " (SELECT COALESCE(SUM(json_extract(stats_json, '$.likes_total')), 0) FROM sessions) AS likes,"
                " (SELECT COALESCE(SUM(CASE WHEN ended_at IS NOT NULL THEN ended_at - started_at ELSE 0 END), 0) FROM sessions) AS duration"
                " FROM events"
            ).fetchone()
            # 表示用handleの選び方はstreamer_indexと同じ(最新sessionのものを決定的に)。
            streamer_rows = self._conn.execute(
                "SELECT COALESCE(NULLIF(s.owner_user_id, ''), s.unique_id) AS okey,"
                " COUNT(DISTINCT s.id) AS sessions,"
                " COALESCE(SUM(CASE WHEN e.kind = 'gift' THEN e.gift_count ELSE 0 END), 0) AS gifts,"
                " COALESCE(SUM(CASE WHEN e.kind = 'gift' THEN e.diamonds ELSE 0 END), 0) AS diamonds,"
                " COALESCE(SUM(CASE WHEN e.kind = 'comment' THEN 1 ELSE 0 END), 0) AS comments,"
                " MAX(s.started_at) AS last_started_at"
                " FROM sessions s LEFT JOIN events e ON e.session_id = s.id"
                " GROUP BY COALESCE(NULLIF(s.owner_user_id, ''), s.unique_id) ORDER BY diamonds DESC",
            ).fetchall()
            streamer_handles = self._latest_owner_handles_locked()
            # 全sessionを跨ぐ通算集計なので表示属性はusers表(最新)を優先する
            # (理由はstreamer_profileのgifter集計と同じ)。
            gifter_rows = self._conn.execute(
                "SELECT e.identity_key AS key,"
                " COALESCE(NULLIF(u.user_id, ''), MAX(e.user_id)) AS user_id,"
                " COALESCE(NULLIF(u.unique_id, ''), MAX(e.user_unique_id)) AS unique_id,"
                " COALESCE(NULLIF(u.nickname, ''), MAX(e.user_nickname)) AS nickname,"
                " COALESCE(NULLIF(u.avatar, ''), MAX(e.user_avatar)) AS avatar,"
                " SUM(e.gift_count) AS gifts, SUM(e.diamonds) AS diamonds,"
                " COUNT(DISTINCT e.session_id) AS sessions"
                " FROM events e LEFT JOIN users u ON u.identity_key = e.identity_key"
                " WHERE e.kind = 'gift'"
                " GROUP BY e.identity_key ORDER BY diamonds DESC, gifts DESC LIMIT 50",
            ).fetchall()
            gift_rows = self._conn.execute(
                "SELECT gift_name AS name, SUM(gift_count) AS count, SUM(diamonds) AS diamonds"
                " FROM events WHERE kind = 'gift'"
                " GROUP BY gift_name ORDER BY diamonds DESC, count DESC LIMIT 50",
            ).fetchall()
            session_rows = self._conn.execute(
                "SELECT id, unique_id, started_at,"
                " COALESCE(json_extract(stats_json, '$.diamonds'), 0) AS diamonds,"
                " COALESCE(json_extract(stats_json, '$.gifts'), 0) AS gifts,"
                " COALESCE(json_extract(stats_json, '$.comments'), 0) AS comments"
                " FROM sessions ORDER BY started_at DESC LIMIT 30",
            ).fetchall()
        return {
            "totals": dict(totals),
            "streamers": [
                {
                    "unique_id": streamer_handles.get(row["okey"], row["okey"]),
                    "sessions": row["sessions"],
                    "gifts": row["gifts"],
                    "diamonds": row["diamonds"],
                    "comments": row["comments"],
                    "last_started_at": row["last_started_at"],
                }
                for row in streamer_rows
            ],
            "top_gifters": [
                {
                    "user_id": row["user_id"] or "",
                    "unique_id": row["unique_id"] or "",
                    "nickname": row["nickname"] or "(unknown)",
                    "avatar": row["avatar"] or "",
                    "gifts": row["gifts"] or 0,
                    "diamonds": row["diamonds"] or 0,
                    "sessions": row["sessions"],
                }
                for row in gifter_rows
            ],
            "top_gifts": [dict(row) for row in gift_rows],
            "recent_sessions": [dict(row) for row in reversed(session_rows)],
        }
