"""storage 層で共有する定数・schema・純粋helper。

Storage の method は持たない。ここに置くのは「どのmixinからも参照され、DB接続にも
lockにも触れないもの」だけである:
  - SCHEMA と migration版
  - events / viewer_samples のINSERT列定義(batchと1行隔離で同一SQLを使うため)
  - ops_events の severity 値域、録画の確認状態、SQLiteの致命error判定材料
  - session集計の共通CTEと、配信者identityの通算SELECT
  - 行 -> dict 変換や区間計算のような純粋関数
  - 集計read専用接続のwrapper(_LockedReader / _ReadResult)

logger もここが持つ。mixinへ分けた後も log の名前は "tictok.storage" のまま一本に
保つ必要があるため(module別にlogを抽出する運用が、分割で壊れてはならない)。
"""
import json
import logging
import sqlite3
from typing import Optional

from tictok.core.battle import BATTLE_TOPOLOGY_VERSION, GLOVE_EVENT_VERSION
from tictok.record.transcription import TIMEMAP_VERSION
from tictok.core.intervals import merge_intervals, subtract_intervals, total_span

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
# upsert間引きcacheの上限件数。keyはidentity_keyで、上限が無いとprocess寿命の間ずっと
# 積み上がる(実測: 1 sessionで最大8,642 user、DB全体では78,355 identity)。
#
# 値の根拠は「同時進行するsessionが、それぞれ最大数のuserを載せても入り切ること」:
# 実測の同時session最大4本 x 1 sessionあたり最大8,642 user = 34,568 に余裕を足した。
# 上限で溢れるとTTL内の再upsertがDB書き込みへ戻るので、hit率を落とさない側へ倒す。
#
# TTLが60秒である以上、実際にhitを生み得るのは「直近60秒に現れたuser」だけで、これは
# 実測で全session合計258件しかない。上限はその桁を大きく上回るので、hit率への影響は無い。
# 溢れるのは「もう二度と参照されない古い行」であり、そこを捨てるための上限である。
#
# 代償はmemory。1 entryは実測875 byte(avatarのURLが大半を占める)で、上限まで埋まると
# 約33MB。上限が無い現状はここに天井が無く、identity数(実測78,355)ぶん伸び続ける。
_USER_CACHE_MAX = 40000
# 1戦のBattle貢献者を「主力貢献者」とみなすcoin(diamond)下限。この閾値以上を投げた
# 貢献者を1戦ごとに数え、過去全Battleの平均人数を出す。
_BATTLE_KEY_CONTRIB_DIAMONDS = 100
# 終了済みBattleの貢献集計cacheの上限件数。窓が確定したBattleの集計は不変なので期限は
# 要らないが、profile閲覧のたびに全sessionのBattleが載るため件数だけは頭打ちにする。
_BATTLE_CONTRIB_CACHE_MAX = 2000

# ops_events.severity の値域。DB側のCHECK制約は付けない: ops_eventsは障害時に記録を残す
# ための表で、制約違反で書き込みが失敗して本流を巻き込むのが最悪の失敗様式だからである。
# 値域はここで担保し、record_ops_eventが呼び出し時点で検証する。
# 「このmigration版のmigrationは完走済み」を示すmarker(db_maintenance表)。値はmigration版の
# 組で、片方でも上がれば不一致になり、次の起動が退避してからmigrationを走らせる。
# 「退避済み」ではなく「完走済み」であることに意味がある: 書き換える行が1つも無かった起動でも
# markerは進み、退避fileは作られない(守る対象が無いため)。
_MIGRATION_BACKUP_KEY = "premigration_backup_versions"
# 「文字起こしの時刻map版を、どの選別ruleで選り分け済みか」。migration版の組とは別に持つ:
# 選別ruleだけが変わった場合(物差しの変更)にも選り直しが要り、逆に時刻map版が同じまま
# rule版だけ据え置けば選り直しは不要、という組み合わせがあるため。
_TIMEMAP_SELECTION_KEY = "timemap_selection_version"


def _migration_versions() -> str:
    return (f"glove={GLOVE_EVENT_VERSION},topo={BATTLE_TOPOLOGY_VERSION}"
            f",timemap={TIMEMAP_VERSION}")


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

# 録画1本を「観たかどうか」の確認状態。既定は未確認で、値はoperatorが手で動かす。
REVIEW_UNCHECKED = "unchecked"
REVIEW_CHECKING = "checking"
REVIEW_CHECKED = "checked"
RECORDING_REVIEW_STATES = (REVIEW_UNCHECKED, REVIEW_CHECKING, REVIEW_CHECKED)

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
    last_seen REAL,
    -- 視聴者が配信者でもあるか。NULL=未確認、0=LIVE不可/未経験、1=配信者。
    -- broadcaster_room_id は過去の室でも league を引けるため使い回す(取得は1回で足りる)。
    broadcaster INTEGER,
    broadcaster_room_id TEXT NOT NULL DEFAULT '',
    league TEXT NOT NULL DEFAULT '',
    league_checked_at REAL
);
-- リーグ取得の待ち行列。processを跨いで残す必要がある(1件15秒で流すため、再起動で
-- 消えると当日ぶんが丸ごと落ちる)。1人1行で、取得できた時点で消える。
CREATE TABLE IF NOT EXISTS league_queue (
    identity_key TEXT PRIMARY KEY,
    unique_id TEXT NOT NULL,
    enqueued_at REAL NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at REAL NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_league_queue_due ON league_queue(next_attempt_at, enqueued_at);
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
-- session一覧と配信者profileは session ごとの MAX(viewers) を相関subqueryで引く。
-- session_idだけのindexだと本体行を全部読みに行くため、実測で162 sessionのlist_sessionsが
-- 25msかかっていた。viewersを載せてcovering indexにすると0.9msで済む。
CREATE INDEX IF NOT EXISTS idx_buckets_session_viewers ON buckets(session_id, viewers);
-- bucketは「そのsessionの、この開始秒の1本」で引かれるが、上の2本はどちらもstartを
-- 持たない。_fill_missing_buckets_lockedのHAVING NOT EXISTS(b.start = ...)がsessionの
-- bucket全件を毎回舐めることになり、bucket数の2乗で伸びる — 配信長が2倍になると
-- bucket数も評価回数も2倍で4倍である。実測: 2,839 bucketのsessionで、補うbucketが
-- 0本でも644ms。これはfinalize_sessionが必ず通る経路で、その間はDB lockを握っている。
-- session_buckets(start範囲)とsession_timeline(ORDER BY start)も同じindexに乗る。
CREATE INDEX IF NOT EXISTS idx_buckets_session_start ON buckets(session_id, start);
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
    duration_seconds REAL,
    -- この録画に紐づく「秒」がどの時間軸の値か。'pts' はmp4のPTS軸(既定)、'media' は
    -- HLSのmedia軸(#EXTINF累積)。search_hits.video_time / bookmarks / cut_list /
    -- transcripts.segments_json が従う軸で、再生位置もこれに一致していなければならない。
    --
    -- 2軸を併存させるのは、片方へ寄せきれないため: HLSで再生する録画はmedia軸で観るが、
    -- .tsが1本も残っていない録画(実測12件)はmp4でしか観られず、しかもmedia_ptsを持たない
    -- 版のtiming mapしか無いので変換もできない。どちらの軸かを録画ごとに持たないと、
    -- 推測で読むことになる。実測では両軸の差は中央値0.44秒だが最大536秒あり、推測は破綻する。
    time_axis TEXT NOT NULL DEFAULT 'pts',
    -- 「この録画を観たか」の確認状態。'unchecked'(未確認・既定) / 'checking'(確認中) /
    -- 'checked'(確認済)。operatorが手で付ける印で、再生や出力では動かさない: 開いただけで
    -- 「確認中」が付くと、印が観た事実を指すのか開いた事実を指すのか読めなくなる。
    review_state TEXT NOT NULL DEFAULT 'unchecked',
    review_updated_at REAL
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
-- 切り抜きグループ(group)。cut_list/bookmarksの項目を「切り抜き動画1本のグループ」単位で束ねる。
-- 項目側は排他所属(group_idを1つ持つ)で、グループ間の共用は行の複製で表す: NLEへ渡す前提では
-- グループごとにIN/OUTの詰め方が変わるため、所属を共有すると片方の調整が他方のグループを壊す。
CREATE TABLE IF NOT EXISTS clip_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    memo TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
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
    -- 所属するグループ。NULLは未分類。positionはグループ内の並び順で、EDL/FCPXMLの書き出し順
    -- (=NLEのtimeline順)そのものになる。NULLは末尾扱い(グループに入れた時に採番する)。
    -- FK pragmaは有効化していないためON DELETE系は書かず、グループ削除時の解除は
    -- delete_group()が自前で行う。
    group_id INTEGER REFERENCES clip_groups(id),
    position INTEGER,
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
    -- 所属するグループ(cut_listと共通のclip_groups)。NULLは未分類。見どころは点の記憶で
    -- 書き出し順を持たないため、positionは持たない(並びは常にstart順)。
    group_id INTEGER REFERENCES clip_groups(id),
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
    -- 段階(stage)の遷移履歴。stageは「今どこか」の1点しか持てず、終わったjobでは空にされる
    -- ため、どの段階で何秒かかったか・どこで落ちたかを後から辿る手段が無かった。段階が
    -- 変わった時だけ1件追記する(進捗tickそのものは数万回鳴るので、ここには載せない)。
    stages_json TEXT NOT NULL DEFAULT '[]',
    -- 待機へ戻したjobを、この時刻まで拾わない(保存先volumeの復帰待ちなど)。
    not_before REAL,
    -- 最初に待機へ戻した時刻。総待ち時間の打ち切り判定に使う。
    deferred_since REAL,
    -- 人が投げたのではなく起動時sweepが自動で積んだ行。同時実行本数を人の投入と別枠で
    -- 絞るために、paramsではなく列で持つ(claimのSQLが1文で判定できる必要がある)。
    sweep INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_media_job_queue_state ON media_job_queue(state, priority, queued_at);
CREATE INDEX IF NOT EXISTS idx_media_job_queue_rec ON media_job_queue(recording_id, state);
-- group進捗は member 1件が進むたび組み直す(media_jobs_in_group)。index無しだと台帳の全行を
-- 毎回scanすることになり、配信者まるごとの一括投入で行が数百に増えたときに効いてくる。
CREATE INDEX IF NOT EXISTS idx_media_job_queue_group ON media_job_queue(group_id, queued_at);
CREATE TABLE IF NOT EXISTS viewer_samples (
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    time REAL NOT NULL,
    create_time REAL,
    viewers INTEGER NOT NULL,
    total_viewers INTEGER,
    anonymous INTEGER
);
CREATE INDEX IF NOT EXISTS idx_viewer_samples_session ON viewer_samples(session_id);
-- bucketのviewersは「そのbucketの窓に入るsampleのMAX」で埋める(_rebuild_buckets_locked /
-- _fill_missing_buckets_locked)。session_idだけのindexではtimeの範囲条件が乗らないため、
-- bucket 1本ごとにそのsessionのsampleを端から端まで舐めることになり、bucket数 x sample数で
-- 伸びる — 配信長が2倍になると両方が2倍で4倍である。実測: 9,438 sample / 2,112 bucketの
-- sessionで2,693ms。timeを載せると同じ結果が2.4msで出る(検証DBで1,612ms -> 2.4ms)。
-- 走るのは起動時の中断session回収・bucket backfill・journal復元・session確定で、いずれも
-- DB lockを握ったままなので、その間collectorのevent書き出しが止まる。
CREATE INDEX IF NOT EXISTS idx_viewer_samples_session_time ON viewer_samples(session_id, time);
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

# session単位のgift/comment集計。配信者別・全体の通算はこれを土台にする。
#
# 通算集計を毎回 events から作り直すのをやめるためにある。sessions LEFT JOIN events は
# events 1行ごとにsessionを跨いだGROUP BYとCOUNT(DISTINCT)を要求するため、実測で710k行に
# 対し1.8〜5.4秒かかっていた(dashboardと配信者一覧が両方これを持っていた)。
#
# 終了済みsessionの集計値はfinalizeがstats_jsonへ確定させ、journal restore後は
# _rebuild_stats_lockedがeventから同じ定義で作り直す。つまりstats_jsonはevent集計の
# 実体化であって別系統の数字ではない(実測: 確定済み158 sessionすべてで
# diamonds/gifts/comments が完全一致)。よってそれを読み、まだ確定していないsessionだけを
# eventから引く。
#
# 「確定していない」は ended_at と3つのkeyの実在で判定する。ended_atだけで見ると、
# 終了はしたが集計を書けなかったsessionが0件として通算に入り、欠測が実績の減少に化ける。
_SESSION_TOTALS_CTE = """
WITH unfinalized AS (
    SELECT id FROM sessions
     WHERE ended_at IS NULL
        OR json_extract(stats_json, '$.diamonds') IS NULL
        OR json_extract(stats_json, '$.gifts') IS NULL
        OR json_extract(stats_json, '$.comments') IS NULL
),
live_totals AS (
    -- CROSS JOIN は「未確定sessionの側から回す」という指定であって直積ではない(SQLiteでは
    -- 結合順の固定を意味する)。素のJOINだと planner は events を全走査して1行ずつ
    -- unfinalized を引き当てる計画を選ぶ: CTEの行数を見積れないためで、実測では未確定が
    -- 2 sessionしか無くても events index を端から端まで舐めて 207ms かかっていた。
    -- 未確定側から index(session_id, kind, time) を引くと同じ結果が 4ms で出る。
    SELECT e.session_id AS session_id,
           SUM(CASE WHEN e.kind = 'gift' THEN e.diamonds ELSE 0 END) AS diamonds,
           SUM(CASE WHEN e.kind = 'gift' THEN e.gift_count ELSE 0 END) AS gifts,
           SUM(CASE WHEN e.kind = 'comment' THEN 1 ELSE 0 END) AS comments
      FROM unfinalized u CROSS JOIN events e ON e.session_id = u.id
     GROUP BY e.session_id
),
session_totals AS (
    SELECT s.id AS id, s.unique_id AS unique_id, s.owner_user_id AS owner_user_id,
           s.status AS status, s.started_at AS started_at,
           COALESCE(t.diamonds, json_extract(s.stats_json, '$.diamonds'), 0) AS diamonds,
           COALESCE(t.gifts, json_extract(s.stats_json, '$.gifts'), 0) AS gifts,
           COALESCE(t.comments, json_extract(s.stats_json, '$.comments'), 0) AS comments
      FROM sessions s LEFT JOIN live_totals t ON t.session_id = s.id
)
"""
# 配信者identity(owner_user_id優先)ごとの通算。dashboardと配信者一覧が同じ数字を出す必要が
# あるので、集計句もここへ置いて共有する。
_STREAMER_TOTALS_SELECT = (
    "SELECT COALESCE(NULLIF(s.owner_user_id, ''), s.unique_id) AS okey,"
    " COUNT(*) AS sessions,"
    " COALESCE(SUM(s.diamonds), 0) AS diamonds,"
    " COALESCE(SUM(s.gifts), 0) AS gifts,"
    " COALESCE(SUM(s.comments), 0) AS comments,"
    " MAX(s.started_at) AS last_started_at"
    " FROM session_totals s"
)

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


def _opponent_key(opp: dict):
    """Battleの対戦相手を1人として畳むkey。集計(対戦相手別)と1戦ごとの履歴が同じkeyを
    名乗らないと、画面で相手から履歴を辿れない(名前だけが一致する別人になる)。"""
    return opp.get("unique_id") or opp.get("nickname") or opp.get("user_id")


def _covering_recording(recs: list, session_id, at) -> Optional[dict]:
    """その時刻を含む録画(無ければNone)。同じsessionに複数の録画がある(実測46 session)
    ため、開始が近い方を採る。中断録画はended_atを持たないので、次の録画の開始までを
    その録画の窓とみなす — 無制限に伸ばすと、後続の録画の時間帯まで先頭の中断録画が
    名乗ってしまう。"""
    if at is None:
        return None
    same = sorted(
        (r for r in recs if r["session_id"] == session_id and r["started_at"] is not None),
        key=lambda r: r["started_at"],
    )
    found = None
    for i, rec in enumerate(same):
        if rec["started_at"] > at:
            break
        end = rec["ended_at"]
        if end is None:
            end = same[i + 1]["started_at"] if i + 1 < len(same) else None
        if end is None or at <= end:
            # 開始が最も近い録画を採る(後の周回で上書きされる)。
            found = rec
    return found


def _coop_summary(session_spans: list, collab_windows: list, battle_windows: list) -> dict:
    """配信時間を「Battle中 / コラボ中 / ソロ」へ分解し、時間あたりの回数まで出す。

    session_spans は [(session_id, start, end)]、窓は [(session_id, start, end)]。
    どちらもwall-clock秒で、窓は所属sessionの範囲へclipしてから数える — 収集断で
    session側が先に終わっている窓を全長で足すと、比率が100%を超える。

    Battleとコラボは同じLinkMicの上で起きるため重なり得る。二重計上を避けるため
    コラボ側からBattle区間を差し引く(analyticsの入室コンテキストと同じ扱い)。
    区間は先にmergeするので、同時刻に複数の窓が開いていても秒は1回しか数えない。

    回数は「clip後に長さが残った窓」を1回と数える。長さ0の窓(実測506件中14件)は
    開いた瞬間に閉じており、これを1回に数えると時間あたりの頻度だけが持ち上がる。
    """
    spans = {sid: (start, end) for sid, start, end in session_spans if end > start}

    def clip(sid, a, b):
        span = spans.get(sid)
        if span is None or a is None:
            return None
        lo = max(a, span[0])
        hi = min(b if b is not None else span[1], span[1])
        return (lo, hi) if hi > lo else None

    by_session: dict = {}
    for sid, start, end in battle_windows:
        c = clip(sid, start, end)
        if c:
            by_session.setdefault(sid, {"b": [], "c": []})["b"].append(c)
    for sid, start, end in collab_windows:
        c = clip(sid, start, end)
        if c:
            by_session.setdefault(sid, {"b": [], "c": []})["c"].append(c)

    active_seconds = sum(end - start for start, end in spans.values())
    battle_seconds = collab_seconds = 0.0
    battle_count = collab_count = 0
    sessions_with_battle = sessions_with_collab = 0
    for sid, kinds in by_session.items():
        b_ints = merge_intervals(kinds["b"])
        c_only = subtract_intervals(merge_intervals(kinds["c"]), b_ints)
        battle_seconds += total_span(b_ints)
        collab_seconds += total_span(c_only)
        battle_count += len(kinds["b"])
        collab_count += len(kinds["c"])
        if kinds["b"]:
            sessions_with_battle += 1
        if kinds["c"]:
            sessions_with_collab += 1
    solo_seconds = max(0.0, active_seconds - battle_seconds - collab_seconds)
    hours = active_seconds / 3600

    def share(seconds):
        return (seconds / active_seconds * 100) if active_seconds > 0 else 0.0

    def per_hour(count):
        return (count / hours) if hours > 0 else 0.0

    return {
        "sessions": len(spans),
        "active_seconds": active_seconds,
        "battle_seconds": battle_seconds,
        "collab_seconds": collab_seconds,
        "solo_seconds": solo_seconds,
        "battle_share": share(battle_seconds),
        "collab_share": share(collab_seconds),
        "solo_share": share(solo_seconds),
        # コラボ・Battleを合わせた「誰かと一緒に映っていた」割合。共演の多さを1つの数で見る。
        "coop_share": share(battle_seconds + collab_seconds),
        "battle_count": battle_count,
        "collab_count": collab_count,
        "battles_per_hour": per_hour(battle_count),
        "collabs_per_hour": per_hour(collab_count),
        "avg_battle_seconds": (battle_seconds / battle_count) if battle_count else 0.0,
        "avg_collab_seconds": (collab_seconds / collab_count) if collab_count else 0.0,
        "sessions_with_battle": sessions_with_battle,
        "sessions_with_collab": sessions_with_collab,
    }


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


class _ReadResult:
    """読み切った行を、sqlite3.Cursorと同じ呼び方で渡すための入れ物。"""

    __slots__ = ("_rows",)

    def __init__(self, rows: list) -> None:
        self._rows = rows

    def fetchall(self) -> list:
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


class _LockedReader:
    """集計read専用の接続を1本だけ共有するためのwrapper。

    executeのたびにlockを取り、行を読み切ってから返す。cursorのまま外へ返すと、まだ
    読み終えていない結果集合の裏で別threadが同じ接続へqueryを流せてしまう。呼び出し側は
    sqlite3.Connectionと同じ書き方(``execute(...).fetchall()``)のままでよい。
    """

    __slots__ = ("_conn", "_lock")

    def __init__(self, conn: sqlite3.Connection, lock) -> None:
        self._conn = conn
        self._lock = lock

    def execute(self, sql: str, params=()) -> _ReadResult:
        # lock待ちとSQL本体は別の内訳へ積む(接続は1本なので、集計が重なった回は待ちが
        # 支配する)。SQL自体はTimedConnectionが ``db.read`` として測る。
        with self._lock:
            return _ReadResult(self._conn.execute(sql, params).fetchall())

    def close(self) -> None:
        with self._lock:
            self._conn.close()
