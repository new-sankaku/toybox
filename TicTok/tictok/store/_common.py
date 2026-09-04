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
import hashlib
import json
import logging
import queue
import sqlite3
from typing import Optional

from tictok.core.battle import BATTLE_TOPOLOGY_VERSION, GLOVE_EVENT_VERSION
from tictok.record.transcription import TIMEMAP_VERSION
from tictok.core.intervals import merge_intervals, subtract_intervals, total_span
from tictok.core import perf

logger = logging.getLogger("tictok.storage")

# 同じ場面と見なす端のずれ(1 frame)。切り出しの範囲は無音への吸着やframe境界の都合で
# わずかに動くので、厳密一致だけを重複と見なすと同じ場面の行が何本も並ぶ。画面側の
# 重複判定(videos.jsのFRAME_STEP_SECONDS)と同じ幅にしてある。
CUT_SAME_RANGE_TOLERANCE = 1.0 / 30.0

# 見どころの出所。誰がその行を置いたかであって、良し悪しでも進み具合でもない。
#   manual  人が押した(既定)
#   auto    shortの自動生成が範囲を書き戻した
#   pick    切り抜き候補 — 章立てのうち「ここは切り出す価値がある」と推した範囲
# 画面はこの値だけを根拠に色と名乗りを決める(static/videos.jsのMARK_ORIGIN_LABELS)。
# 増やすときは画面側の対応も同時に足すこと ―― 知らない値は名乗りが「—」になり、
# 色の付かない行として黙って混ざる。
#
# **章立てそのものはここへ入れない。** 目次は録画1本に対する1つの成果物で、置き場は
# ai_analysis(kind=chapters)である(書き出し・再生画面の目次・切り出し範囲の章clampが
# すべてそちらを読む)。見どころへ入るのは、その目次から選ばれて「切り出す素材」になった
# 範囲だけで、それが pick である。
BOOKMARK_ORIGINS = ("manual", "auto", "pick")

# events / viewer_samples のINSERT。batch(executemany)と1行隔離(同一SQLを1行ずつ)で同じ
# 列順を使うため定数化する。列順はbuffer済みtupleおよびjournal記録のrowと厳密に一致させること。
#
# **これはDBの列名ではなくbuffer/journalが運ぶ行の形である。** intern(下記
# _INTERNED_EVENT_COLUMNS)を入れた後、DBが持つ列名とはここが食い違う: bufferもjournalも
# 生の文字列を運び続け、id列への差し替えは書き出し直前(_drain)にだけ起きる。DBへ投げる
# 列名は _events_insert_sql() が段階から組み立てる。
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
    # 届いているが専用の列を持たないfieldのJSON。列にしないのはkindごとに疎で、意味が
    # 未確定なため — 解釈が定まったものだけ後から列へ昇格させる。中身の規約は
    # collector._extra_payload にあり、NULLは「計装前で未計測」を意味する。
    "extra",
    # TikTokがmessage 1件ごとに振る一意のid(base_message.message_id)。接続のたびに
    # 届き直す遡り分を判別する唯一の鍵で、除去そのものは受信時に済ませている
    # (tictok/collect/dedup.py)。ここに残すのはDB側の一意制約の鍵にするためと、
    # 「重複が起きたか」を後から確かめられるようにするため。collector自身が書く
    # system eventと、計装前の既存行はNULL。
    # **列は必ず末尾へ足すこと。** journalは位置固定の行を運ぶので、途中に挟むと
    # 復元時に旧journalの値が1つずれた列へ入る(_iter_journal_rowsの幅の正規化参照)。
    "message_id",
)
_VIEWERS_INSERT_SQL = (
    "INSERT INTO viewer_samples (session_id, time, create_time, viewers, total_viewers, anonymous)"
    " VALUES (?, ?, ?, ?, ?, ?)"
)

# ----- eventsの重複文字列のintern ------------------------------------------------------
# eventsの同じ文字列が何度も行に載る列を、値そのものではなく event_strings のidで持つ。
# (bufferとjournalが運ぶ生の列名, DBが持つid列名) の対。
#
# 実測(2026-08-23, events 1,256,138行)での内訳:
#   user_avatar        342.1MB / distinct 292,114 — 同じURLが平均4.3回
#   user_gifter_badge   97.2MB / distinct     14  — Lv別の固定badge画像URL
#   user_member_badge   74.7MB / distinct     19  — 同上
# 併せてcopy DBで 1767.6MB -> 1297.1MB(-470.5MB / -26.6%)を実測した。
#
# **avatarの伸びは止まらない。** TikTokのavatar URLは署名付き(x-expires/x-signature)で
# 回転するため、実在88,678人に対して新規のdistinct URLが3,735〜10,540件/日発生する。
# internで 5.11MB/日 -> 1.30MB/日 へ落ちるが、intern表は1.23MB/日で伸び続ける。
# badge側は種類が増えないので伸びは実質ゼロで、こちらが本命である。
_INTERNED_EVENT_COLUMNS = (
    ("user_avatar", "user_avatar_id"),
    ("user_gifter_badge", "user_gifter_badge_id"),
    ("user_member_badge", "user_member_badge_id"),
)
# contributor_samplesも同じ形(141,708行 / 39.1MB / distinct 21,689)で、同じ event_strings
# へ相乗りする。あちらはbatch writerを通らない同期書き込みなのでjournalの心配が無い。
_INTERNED_CONTRIBUTOR_COLUMNS = (("user_avatar", "user_avatar_id"),)

# migrationの段階。expandとcontractを分けるのは、**旧列を落とすと読み出し側が一斉に
# 壊れる**ためである(旧列を残したままでは1 byteも減らないので、途中で止まる形にはできない)。
#   EXPAND   : event_strings とid列が在り、旧列とid列の両方へ書く。読み出しはどちらでも同じ
#              答えになるので、書き換え済みの読み出し箇所と未着手の箇所が共存できる
#   CONTRACT : 全行の突き合わせを関門にして旧列を落とし、以後はid列だけへ書く
_INTERN_PHASE_NONE = 0
_INTERN_PHASE_EXPAND = 1
_INTERN_PHASE_CONTRACT = 2
# db_maintenance表に持つ「今どこまで進んだか」。
_INTERN_PHASE_KEY = "events_intern_phase"

# **どこまで進めるかの目標。**
#
# eventsのavatar/badgeを読む7箇所(users / sessions / maintenance._backfill_users /
# streamers x4 / battles)はJOIN形へ書き換え済みで、EXPAND段階の実DB(1,256,138行)で
# 旧列形と同じ答えを返すことを確認してある(doc/DB_INTERN.md)。
#
# それでもEXPANDに置いてあるのは、**CONTRACTへ上げるのが「いつ本番のDBから旧列を
# 落とすか」の決定そのもの**だからである。上げた次の再起動で、退避 -> 全行の突き合わせ
# -> DROP COLUMN が走り、旧列の値はどこにも残らない。codeが揃ったかどうかとは別に、
# 実行してよい時機かどうかの判断が要る。
#
# 上げるときはこの1行だけを _INTERN_PHASE_CONTRACT にする。上げる前に、旧列を読む形が
# 1つも残っていないことを必ず確かめること:
#   grep -rn "MAX(e\.user_avatar)\|MAX(e\.user_gifter_badge)\|MAX(e\.user_member_badge)" tictok/
_INTERN_TARGET_PHASE = _INTERN_PHASE_CONTRACT

# 既存行のid埋めを何行ずつcommitするか。再開条件は「id列がNULLの行」という述語そのものな
# ので、途中で落ちてもこの粒度で続きから再開する。operatorが回す値ではない。
_INTERN_MIGRATE_CHUNK_ROWS = 100000

# 値 -> id のprocess内cacheの上限件数。**hit率のtuningではなくmemoryの天井である。**
# 実測(直近60万event)では上限を5,000から無制限まで振っても1 batchあたりのDB問い合わせは
# 12.38 -> 12.32件しか動かない — avatarのURLは署名が回転するので、未hitの大半はどの
# 大きさのcacheでも持てない初見の値だからである。cache自体は効いていて、cache無しの
# 31.46件/batchを12.32件へ61%減らす。効かないのは上限の大小だけである。
# 40,000は実測15.3MB(1 entry 422 byte)で、users表のupsert間引き(_USER_CACHE_MAX)と同値。
# 捨て方も揃えてある(上限到達時に古い方から1/4、dictの挿入順を利用)。
_EVENT_STRING_CACHE_MAX = 40000


def _events_insert_columns(phase: int) -> tuple:
    """段階に応じた**DB側の**events列名。_EVENTS_COLUMNS(buffer/journalの行の形)とは
    CONTRACT以降で食い違う。

    EXPANDでは旧列とid列の両方へ書く(行tupleは生の値 + id 3つで、_EVENTS_COLUMNS より
    3つ長い)。CONTRACTでは旧列がもう無いので、生の値の位置をidへ差し替えて同じ幅で書く。
    """
    if phase >= _INTERN_PHASE_CONTRACT:
        renamed = {old: new for old, new in _INTERNED_EVENT_COLUMNS}
        return tuple(renamed.get(c, c) for c in _EVENTS_COLUMNS)
    if phase >= _INTERN_PHASE_EXPAND:
        return _EVENTS_COLUMNS + tuple(new for _, new in _INTERNED_EVENT_COLUMNS)
    return _EVENTS_COLUMNS


def _events_insert_sql(phase: int) -> str:
    """段階に応じたevents INSERTのSQL。値tupleの形は _events_insert_columns と対。

    末尾の ON CONFLICT は接続時の遡りの二重記録に対する**耐久側の防波堤**である。第一の
    防波堤は受信側(tictok/collect/dedup.py)で、そちらは統計とbucketごと落とすのでこの
    経路まで届かない。ここが効くのはprocessが落ちて記憶を失った直後だけだが、その窓こそ
    再接続が集中する場面なので塞いでおく。

    衝突の対象を ``idx_events_message`` の3列に限定してあるのが要点である。IntegrityError
    にしてしまうと、writerのbatch INSERTが失敗して隔離経路(_write_isolating_locked)へ
    落ち、意図した重複がdead-letterへ「復旧が必要なdata喪失」として積まれる。DO NOTHING
    なら黙って捨てられるが、**FK違反やNOT NULL違反はこれまで通り送出される** — OR IGNORE
    だと孤児eventのFK違反まで飲み込み、poison-pillの検知が効かなくなる。
    """
    columns = _events_insert_columns(phase)
    return (f"INSERT INTO events ({', '.join(columns)})"
            f" VALUES ({', '.join('?' * len(columns))})"
            f" ON CONFLICT (session_id, kind, message_id) WHERE message_id IS NOT NULL"
            f" DO NOTHING")


def _interned_event_positions() -> tuple:
    """_EVENTS_COLUMNS 上での、intern対象列の位置。bufferとjournalの行はこの位置に
    生の文字列を持ち、書き出し直前にだけidへ差し替わる。"""
    return tuple(_EVENTS_COLUMNS.index(old) for old, _ in _INTERNED_EVENT_COLUMNS)


# 署名を落として保存する列。**internとは別の判断である。** internは同じ文字列を1度だけ持つ
# 変更で記録の中身を変えないが、こちらは保存する値そのものを変える。
#
# avatarのCDN URLは「画像を指すpath」と「取得のたびに変わる署名query」でできている。実測で
# 1本301 byteのうち162 byteが署名で、URLは48,542種あるのに指している画像は25,020枚しかない。
# 署名の有効期限は約2日で、保存済みの95.5%(1,190,818/1,246,969)は既に切れている。
#
# 落として困らないのは、表示がこの値を使っていないからである。画面は必ず
# `/api/avatar?u=<URL>&id=<unique_id>` の形で呼び(static/common.js:2167 avatarSrc)、
# AvatarProxy._load_local は **user_key(=id)のpoolを先に見る**。poolは収集時にcollectorが
# 実体を保存したもので662,315件あり、URLは参照されない。poolに無い時だけURLでCDNへ行くが、
# その経路は95.5%が既に期限切れで機能していない。
#
# badgeは対象外。Lv別の固定画像で署名が付かず(実測 gifter 14種/member 19種ともquery無し)、
# 落とす対象が無い。**avatarとbadgeが同じevent_strings行を共有している例が1件ある**ので、
# 行を書き換えるのではなくavatar側のidを付け替える(維持すべき不変条件)。
_INTERN_STRIPPED_COLUMNS = frozenset({"user_avatar"})
# 既存行の付け替えを1度だけ走らせるための世代。上げると次の起動で作り直す。
_INTERN_STRIP_VERSION = 1
_INTERN_STRIP_KEY = "events_intern_avatar_stripped"


def _value_for_intern(column: str, value):
    """internする前に値を正規化する。対象外の列と None はそのまま返す。"""
    if value is None or column not in _INTERN_STRIPPED_COLUMNS:
        return value
    head, sep, _ = value.partition("?")
    return head if sep else value


def _interned_event_normalizers() -> tuple:
    """_interned_event_positions() と同じ並びの、列ごとの正規化関数。"""
    return tuple(old for old, _ in _INTERNED_EVENT_COLUMNS)


def _string_hash(value: str) -> int:
    """event_strings を引くためのhash。SQLiteのINTEGERに収まる符号付き64bit。

    Pythonのhash()を使わない: PYTHONHASHSEEDでprocess毎に変わるため、DBへ保存すると
    次の起動で同じ文字列が引けなくなる。blake2bは値が決まればprocessを跨いで不変である。
    桁数を設定可能にもしない — 変えると保存済みのhashが全て無効になり、「DBの中身と
    設定が食い違う」状態を作れてしまう。"""
    digest = hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)

# 書き込みは単一writerスレッドでバッチ化する。add_event/add_viewer_sampleはキュー投入で
# 即returnし、writerがN件または一定間隔でexecutemany+1commitへまとめる。
_WRITE_BATCH_SIZE = 50
_WRITE_FLUSH_INTERVAL_SECONDS = 0.2
# 同一identity_keyの属性が変わらない限り、この秒数はusers表のupsertを間引く(live取り込みのみ)。
_USER_UPSERT_TTL_SECONDS = 60.0
# 索引から先頭メンションを外すための既知表示名(Storage.mention_names)の保持秒数。
# 実測31.8万件・0.4秒で、一括のindex投入は録画ごとに引く。名前の台帳は分単位で変わる
# ものではないので、読み直しの頻度より安さを取る。
_MENTION_NAMES_TTL_SECONDS = 600.0
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
# 投稿へ貼る省略形(user_aliases)の長さの上限。省略のための欄なので、元の表示名より長く
# 書けても意味が無い。上限を置くのは、貼る文面が1行に収まらなくなるのと、押し間違いで
# 文章を丸ごと貼り込んだ行がDBへ残るのを止めるためである。
USER_ALIAS_MAX = 40
# 1戦のBattle貢献者を「主力貢献者」とみなすcoin(diamond)下限。この閾値以上を投げた
# 貢献者を1戦ごとに数え、過去全Battleの平均人数を出す。
_BATTLE_KEY_CONTRIB_DIAMONDS = 100
# Battle分析の集計対象にするscore下限。**全ての陣営**のscoreがこの値以下だったBattleは
# 勝負が成立していない(開始直後に流れた/相手が現れない枠)ため、勝率・平均Score・貢献者
# などの集計から外す。実dataでは984戦中202戦(20.5%)がこれに当たり、うち0対0は6戦だけで
# 残りは1〜100の微少scoreである。共演構成(配信時間の内訳)からは外さない — 成立しなくても
# その時間はBattle枠に使われているため。
_BATTLE_NO_CONTEST_SCORE = 100
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
# 「検索の索引を、どの畳み込みrule(normalize.FOLD_VERSION)で作ったか」。索引語そのものが
# ruleに依存するので、版が上がったら全行を畳み直してFTSを作り直す。
_SEARCH_FOLD_KEY = "search_fold_version"
# 「plannerの統計(sqlite_stat1)を、eventsが何行の時点で採ったか」。値はJSONで
# {"rows": N, "at": epoch}。sqlite_stat1の有無だけでは「在るが古い」を区別できず、
# かといって毎起動でANALYZEすると2.3秒のwrite lockを無条件に払うことになる。行数の
# 伸びで測るのは、planを変える要因が「表の大きさとindexの選択性」だからである。
_ANALYZE_STATE_KEY = "planner_stats_state"


# cut_listをbookmarksへ畳んだ版。**表を1つ落とす**ので、この版を上げないと退避を取らずに
# 破壊的なmigrationが走る(他の3つはin-placeの書き換えで、表そのものは残る)。
CUT_MERGE_VERSION = 1


def _migration_versions() -> str:
    # internの段階もmarkerへ載せる。**旧列を落とす**破壊的なmigrationなので、段階が上がる
    # 起動では退避を取り直させる必要がある(EXPANDとCONTRACTで別々に1回ずつ退避が要る)。
    return (f"glove={GLOVE_EVENT_VERSION},topo={BATTLE_TOPOLOGY_VERSION}"
            f",timemap={TIMEMAP_VERSION},cutmerge={CUT_MERGE_VERSION}"
            f",intern={_INTERN_TARGET_PHASE},avstrip={_INTERN_STRIP_VERSION}")


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
-- eventsの重複文字列(avatar / badge のURL)を1度だけ持つ表。列ごとに表を分けず1つに畳んで
-- あるので、対象列を増やしてもDDLは増えない(_INTERNED_EVENT_COLUMNS に1行足すだけ)。
-- kind列を持たないのは意図的で、同じ文字列がavatarとbadgeの両方で使われれば1行を共有する。
--
-- value に UNIQUE を張らない理由: valueのUNIQUE indexは実測81.5MB(292k件 x 274 byte)で、
-- interで回収する294MBの28%をindexが食い潰す。hashのindexなら約4MBで済む。
-- 引くときは hash で絞ってから **value を実比較** するので、hashが衝突しても別idとして
-- 正しく扱われる(確率に頼って潰しているのではない)。
-- 追記のみで行を消さない: 参照している行が在るかを数えるには全参照列を走査する必要があり、
-- その費用を払う理由が無い(実測で最大の user_avatar でも intern表は1.23MB/日でしか伸びない)。
CREATE TABLE IF NOT EXISTS event_strings (
    id INTEGER PRIMARY KEY,
    hash INTEGER NOT NULL,
    value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_event_strings_hash ON event_strings(hash);
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
-- 素材画面のUserアイコン一覧が使う「最近見た順」。列の向きを ORDER BY と一字一句
-- 揃えてある(last_seen DESC, identity_key ASC) —— 向きが片方でも違うとSQLiteは
-- indexを順序の充足には使えず、193,360行を毎回並べ直す。identity_keyを載せているのは
-- last_seenが重複するためで、これが無いとpageを跨いで同じ行が二度出たり抜けたりする。
CREATE INDEX IF NOT EXISTS idx_users_last_seen ON users(last_seen DESC, identity_key ASC);
-- 投稿へ貼る文面で名前の代わりに出す省略形。人が付ける層なので users 表とは別に置く ——
-- あちらは event が来るたび最新の非空値で上書きされるので、同じ列へ書くと配信のたびに
-- 消えて付け直しになる(字幕の直しを transcript_corrections へ分けたのと同じ理由)。
-- 1人1つ。空文字の行は置かず消す —— 空で残すと「省略形を付けた人」を数えられない。
CREATE TABLE IF NOT EXISTS user_aliases (
    identity_key TEXT PRIMARY KEY,
    alias TEXT NOT NULL,
    updated_at REAL NOT NULL
);
-- 同じ人が持つ別アカウント(サブアカウント)の束ね。人が指す層なので user_aliases と
-- 同じくusers表とは別に置く —— あちらはeventのたびに上書きされる観測値で、こちらは
-- 「この2つは同じ人だ」という人の判断である。
-- member_key が主keyなのは、1つのアカウントが2人ぶんの中身になることは無いためである。
-- 束ねの深さは1段しかない(primary_key は他の行の member_key になれない): 段を許すと
-- 「AはBへ、BはCへ」の途中で環ができ、集計の畳み先が引く順で変わる。
CREATE TABLE IF NOT EXISTS user_merges (
    member_key TEXT PRIMARY KEY,
    primary_key TEXT NOT NULL,
    updated_at REAL NOT NULL
);
-- 束ね先から辿る向き。日のGifterの集計は member_key 側から引くが、画面の一覧と
-- 「主へ束ねた人を数え直す」はこの向きで引く。
CREATE INDEX IF NOT EXISTS idx_user_merges_primary ON user_merges(primary_key);
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
    -- 窓を作った判定ruleの版(core.collab.COLLAB_WINDOW_VERSION)。既定1は旧rule。
    version INTEGER NOT NULL DEFAULT 1,
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
-- 消えた行そのものの退避(row単位のundo)。DELETE triggerが1行1件で積む
-- (仕組みと対象表の線引きは :mod:`tictok.store.row_trash`)。
--
-- **DBの保護の3段目である。** 1段目のauthorizer(``dbmaint.attach_drop_guard``)はserverの
-- 接続にしか掛からず、2段目の行数の見張り(``dbmaint.check_row_guard``)は**小さい表の部分
-- 削除**を原理的に見分けられない —— bookmarks 192件のうち59件が消えても、同じ59件は
-- 「表示中をすべて削除」という正常な操作でも消えるので、行数だけからは区別が付かない。
-- 区別できないなら、**消えた行そのものを残す**しかない。
--
-- triggerはschemaの一部なのでengineが強制する。つまり sqlite3.exe やDB browserのような
-- **外部processのDELETEでも発火する** —— authorizerが効かない穴はここで塞がる。
--
-- 列を4つに抑え、行の中身は json_object() の1列で持つ。対象表の列構成が変わっても
-- 退避表のschemaを追いかけずに済むためで、追いかける形にすると「列を足した日に、
-- 足す前に消えた行が読めなくなる」。
--   table_name  元の表名
--   row_pk      その表のPRIMARY KEYを文字にしたもの。一覧で行を名指しするためと、
--               復元時の「既に在るか」を1回のindex参照で見るため
--   deleted_at  消えた時刻(epoch秒)。triggerが julianday('now') から作るのでUTC基準
--   row_json    行の中身そのもの
--
-- indexは1本だけにする。復元の一覧は表名と期間で絞るのでこの並びが要るが、保持日数の
-- 刈り取り(deleted_at単独)のためにもう1本足すのは割に合わない —— 刈り取りは起動時に
-- 1回で、この表は実測でも数千行にしかならない(削除の実測は row_trash のdocstring)。
-- 対して索引はDELETEのたびに書かれる側なので、本数がそのまま削除の費用になる。
CREATE TABLE IF NOT EXISTS row_trash (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name TEXT NOT NULL,
    row_pk TEXT,
    deleted_at REAL NOT NULL,
    row_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_row_trash_table ON row_trash(table_name, deleted_at);
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
    -- HLSのmedia軸(#EXTINF累積)。search_hits.video_time / bookmarks /
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
    review_updated_at REAL,
    -- 録画1本ぶんの覚え書き。operatorが手で書く文字だけを入れる(自動では何も書かない)。
    -- sessionのnoteと別に持つのは、この一覧の1行が1録画であるため: 1つの配信が最大12本の
    -- 録画に割れており(実測)、session側に置くと同じ文がその本数ぶん並ぶ。加えてsessionを
    -- 失った録画(session_id IS NULL、実測72本)はsession側のメモを持ちようがない。
    memo TEXT NOT NULL DEFAULT '',
    -- 笑い声indexを最後に張ったときの条件(search.indexer.laugh_index_metaのJSON)。rule版と
    -- 共演の除外設定を持つ。NULLは「まだ張っていない、または条件が分からない」で、
    -- 一括処理(笑い声分析)の済み判定はこの列が現行の条件と一致することを見る ―― 行が
    -- 在るかだけで済みにすると、共演中を外す前に張ったindexが済みのまま残る。
    laugh_index_json TEXT
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
    timemap_drift_seconds REAL,
    word_times INTEGER
);
-- 文字起こしの訂正。transcriptsは常に生のまま置き、直しはここへ積んで読み出し時に重ねる
-- (tictok.record.corrections)。書き戻さないのは、再文字起こしで直しが消えるためである。
-- 同定はindexではなく (start, src) の組で行う: 再文字起こしでindexも時刻も変わるため、
-- indexで指すと次の実行で別の発話へ乗る。当たらなかった行は state='orphan' で人へ返す。
--   state: active(適用中) / orphan(貼り直せず保留) / discarded(破棄。行は消さない)
CREATE TABLE IF NOT EXISTS transcript_corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    start REAL NOT NULL,
    src TEXT NOT NULL,
    dst TEXT NOT NULL,
    origin TEXT NOT NULL DEFAULT 'human',
    confidence TEXT,
    note TEXT,
    state TEXT NOT NULL DEFAULT 'active',
    created_at REAL NOT NULL,
    updated_at REAL
);
CREATE INDEX IF NOT EXISTS idx_transcript_corrections_rec
    ON transcript_corrections(recording_id, state);
-- 同じ発話への同じ訂正を二重に積まない(取り込みを何度流しても同じ状態になる)。
CREATE UNIQUE INDEX IF NOT EXISTS idx_transcript_corrections_key
    ON transcript_corrections(recording_id, start, src);
-- 配信者動画画面の横断検索index。文字起こしsegmentとcommentを同じ行形式へ正規化し、
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
    body TEXT NOT NULL,
    -- 照合用に表記ゆれを畳んだ本文(tictok.search.normalize.fold)。索引もLIKEもこちらを
    -- 見る。bodyは画面に出す原文のまま残す。畳み込みは文字数を保つので、body_norm上で
    -- 見つけた位置はbodyの同じ位置である。
    body_norm TEXT NOT NULL DEFAULT '',
    -- その行の強さ。尺度はsourceごとに違い、laughは窓の中の最大確率(0..1)。語を持たない
    -- 行(笑い声)は語の一致で順位を付けられないので、強い順に並べる根拠はこの列しか無い。
    -- 本文へ「強さ 0.78」と書いた文字列から読み戻すのは、表示の書式を数値の出所にする
    -- ことになるので行わない。語で引く行(文字起こし・comment)はNULLのまま。
    score REAL
);
CREATE INDEX IF NOT EXISTS idx_search_hits_rec ON search_hits(recording_id, source);
CREATE INDEX IF NOT EXISTS idx_search_hits_uid ON search_hits(unique_id, started_at);
-- source単独で絞って新しい順に並べる経路(笑い声の一覧)用。source条件だけでは
-- idx_search_hits_rec も idx_search_hits_uid も効かず、56万行の全表走査に落ちる。
CREATE INDEX IF NOT EXISTS idx_search_hits_source ON search_hits(source, started_at);
-- 切り抜きグループ(group)。見どころ(bookmarks)を「切り抜き動画1本のグループ」単位で束ねる。
-- 項目側は排他所属(group_idを1つ持つ)で、グループ間の共用は行の複製で表す: グループごとに
-- IN/OUTの詰め方が変わるため、所属を共有すると片方の調整が他方のグループを壊す。
CREATE TABLE IF NOT EXISTS clip_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    memo TEXT NOT NULL DEFAULT '',
    -- 棚(グループ一覧)の表示順。作成順は「今どれを進めているか」とは無関係なので、
    -- 人が並べ替えられるようにする。NULLは末尾扱い(並べ替え前の既存行)。
    position INTEGER,
    created_at REAL NOT NULL
);
-- 切り出し候補(cut_list)は廃止した。範囲を持つ見どころ(bookmarks.end IS NOT NULL)が
-- そのまま素材の候補で、二重に持たない。移行は _migrate() の cut_list 統合が行う。
-- short(縦の短尺動画)の作り方一式。「尺をどう決め、どう仕上げるか」の組を1行で持つ。
--
-- 設定表(settings)ではなく独立の表にしてあるのは、これが**同時に複数成立する**値だから
-- である。settingsは1 keyに1値しか持てないので、15〜60秒の型と30〜90秒の型を併存させたい
-- 時点で表現できない。key名に番号を埋めて増やす形(clip_short1_*, clip_short2_*)は、型の
-- 数を code 側で固定することになるので採らない。
--
-- 範囲確定(media/clip_range)が読むのは尺とsnapの列だけ、仕上げ(short job)が読むのは
-- 残りの列だけで、両者は同じ行を別の目的で参照する。
CREATE TABLE IF NOT EXISTS clip_presets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    -- 一覧の並び順と、種別を指定しなかったときに使う既定(先頭の行)。
    position INTEGER,
    -- 尺の狙いと許容。targetは範囲を作るときの目標で、min/maxは満たせなければ候補ごと
    -- 捨てる下限・上限である(縮めて無理やり通すと話の途中で切れた物が出る)。
    min_seconds REAL NOT NULL,
    target_seconds REAL NOT NULL,
    max_seconds REAL NOT NULL,
    -- 山(盛り上がりの中心)を範囲内のどこへ置くか。0.5で中央。大きいほど山が後ろに来る
    -- =頭に助走が付く。shortは「何が起きるか」を見せてから山へ入る必要があるため既定は
    -- 中央より後ろに置く。
    peak_position REAL NOT NULL DEFAULT 0.65,
    -- 端の吸着先。発話境界(文字起こしsegment)へ寄せると話の途中で始まらなくなり、無音spanへ
    -- 寄せると音の切れ目で始まる。両方立てた場合は近い方を採る。
    snap_speech INTEGER NOT NULL DEFAULT 1,
    snap_silence INTEGER NOT NULL DEFAULT 1,
    -- 吸着で端を動かしてよい最大秒。これを超える距離しか吸着先が無い端は動かさない
    -- (遠くの境界へ引っ張ると、山を範囲から押し出す)。
    snap_max_shift_seconds REAL NOT NULL DEFAULT 3.0,
    -- 章(chapter)の境界を跨がせない。跨いだ範囲は「別の話題が混ざったshort」になる。
    chapter_clamp INTEGER NOT NULL DEFAULT 1,
    -- 間の詰め(無音カット)。max_secondsに収めるための手段でもある。
    tighten INTEGER NOT NULL DEFAULT 0,
    tighten_min_silence_seconds REAL NOT NULL DEFAULT 1.2,
    tighten_keep_seconds REAL NOT NULL DEFAULT 0.25,
    -- 仕上げで何を焼くか。commentの既定がoffなのは、shortでは画面が小さく、telopと
    -- commentが同じ面積を奪い合うため。gift・スコアバーはcommentと別に持つ — 短い尺では
    -- 「コメントは要らないがBattleの点は要る」という組み合わせが実際に成立する。
    subtitles INTEGER NOT NULL DEFAULT 1,
    comments INTEGER NOT NULL DEFAULT 0,
    gifts INTEGER NOT NULL DEFAULT 0,
    score_bar INTEGER NOT NULL DEFAULT 1,
    normalize_audio INTEGER NOT NULL DEFAULT 1,
    upscale INTEGER NOT NULL DEFAULT 0,
    -- 効果音(作品のみ)。シーンの継ぎ目とテロップの出現に置く。既定でoffなのは、素材として
    -- 外部の編集softへ持ち込む用途では音が入っていると邪魔になるためである。
    sfx INTEGER NOT NULL DEFAULT 0,
    -- 縦画面の安全域(上下からの%)。投稿先のUIが被る帯で、ここにはtelopを置かない。
    safe_top_percent REAL NOT NULL DEFAULT 12.0,
    safe_bottom_percent REAL NOT NULL DEFAULT 18.0,
    created_at REAL NOT NULL
);
-- 見どころ(bookmark)。録画の中で人が印を付けた1箇所で、**素材の候補もこの表が持つ**。
--
-- 以前は「後でまた見たい場所」(bookmarks)と「書き出す素材の候補」(cut_list)を別表にし、
-- 範囲付きの見どころを『昇格』させてcut_listへ写していた。分けた理由は「グループごとに
-- IN/OUTの詰め方が変わるので所属を共有できない」だったが、実データではcut_list 21件の
-- うち20件が元の見どころと範囲・グループ・ラベルまで完全一致で、詰め直しは一度も起き
-- なかった。写した先で別の値になるという前提が成立していないので、昇格は行を1つ増やす
-- だけの操作になっていた。表を1つにして、その1行が印であり素材でもある形にする。
-- グループを跨いで同じ場面を別々に詰めたい場合は、行ごと複製する(所属は排他のまま)。
--
-- end IS NULLが点(コメント1件や現在位置)、endを持てば範囲。**mp4にできるのは範囲だけ**で、
-- 点は書き出しの対象に入らない。source_hit_idはメモ元のsearch_hits行(コメント由来のとき)。
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
    -- 覚え書きであり、mp4を書き出すときのfile名でもある(旧cut_list.labelを兼ねる)。
    memo TEXT NOT NULL DEFAULT '',
    source_hit_id INTEGER,
    live_wall REAL,
    pts_mapped INTEGER NOT NULL DEFAULT 1,
    -- 所属するグループ。NULLは未分類。positionはグループ内の並び順で、mp4の書き出し順
    -- (=「1本に連結」「作品にする」の繋ぐ順)そのものになる。NULLは末尾扱い。
    -- FK pragmaは有効化していないためON DELETE系は書かず、グループ削除時の解除は
    -- delete_group()が自前で行う。
    group_id INTEGER REFERENCES clip_groups(id),
    position INTEGER,
    -- 誰が付けた行か。manual=人、auto=shortの自動生成が「同じ場面を二度作らない」ために
    -- 書き戻した行。機械の行を人の印と混ぜて並べると、自分が付けた覚えの無い行が一覧を
    -- 埋めるので、画面は既定でmanualだけを出す(autoは絞り込みで呼び出す)。
    origin TEXT NOT NULL DEFAULT 'manual',
    -- 最後にmp4として書き出した時刻と、その出力path。「この行は書き出した」という**過去の
    -- 事実**であって、今もそのfileが在るという意味ではない(出力先の掃除はDBを通らない)。
    -- 画面が「済」ではなく日時とpathで名乗るのはそのため。無ければ一度も書き出していない。
    exported_at REAL,
    exported_path TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bookmarks_rec ON bookmarks(recording_id, start);
-- group_id/positionのindexはここに置けない。既存DBではこのscriptが走る時点で列がまだ
-- 無く(ALTERは_migrateが行う)、索引だけが先に列を要求して落ちる。_migrateが張る。
-- 一括文字起こしのqueue。processが落ちても残るようDBに置き、起動時にrunningをpendingへ戻す。
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
-- 映像job(焼き込み/Up出力/再mp4化)の永続queue。文字起こしqueueと同格の位置づけだが、1録画に対して
-- 種別違いのjobが同時に並ぶ(焼き込みとUp出力)ため、PKはrecording_idではなく独立のidにする。
-- job_idはJobRegistry(process内の進捗台帳)とops_events.job_idと同じ値を入れ、log・DB・画面を
-- 1つのIDで突き合わせられるようにする。
-- recording_id/session_idともCASCADE: 対象が消えたjobは投入意図ごと無意味になるため残さない
-- (孤児行を残すと、worker が存在しない録画を延々pickして失敗し続ける)。
--
-- recording_idは**任意**である。台帳に載るjobの多くは録画1本に対する処理だが、highlightの
-- 突き合わせは「どの録画のどこから来たのか」を求めるjobそのものなので、投入時点で書ける
-- 録画idが原理的に無い。埋め合わせに無関係な録画idを入れると、この列を読む側(busy判定・
-- 削除の抑止・sweepの済み判定)がその録画で嘘を言う。既存DBの制約外しは
-- ``_migrate_media_job_recording_optional``。
CREATE TABLE IF NOT EXISTS media_job_queue (
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
    -- 人が投げたのではなくsweepが自動で積んだ行。同時実行本数を人の投入と別枠で
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
-- 素材pool(Userアイコン/Giftアイコン/Emote)の走査結果cache。方針はstorage_scanと同じで、
-- 走査は明示操作のときだけ行い、APIは常にこの表を返す(実測: avatarのpoolは662,315 entryで
-- 1回1.2〜2.5秒。pageを開くたびに払ってよい費用ではない)。
--
-- storage_scanと違い**種別ごとに1行**持つ。走査費用が種別で3桁違い(実測 emote 1ms /
-- gift_icon 0.2秒 / avatar 2.5秒)、安い2つは一覧を作るついでに数え直せるのに対し、
-- avatarは一覧がusers表駆動でdirを歩く機会が無いためである。1行cacheに畳むと、安い2つを
-- 更新するたびにavatarまで数え直すことになり、明示操作へ寄せた意味が消える。
--
-- item_count と listable_count は**同じ母集団(diskに在る素材)**を数えた別の値である。
-- 前者は全点、後者はそのうち名前を辿れる点数で、差が「実体は在るが名乗る名前が無い素材」に
-- ちょうど一致する。avatarだけこの2つがずれる: file名は sha1(unique_id or nickname) で、
-- 鍵から人へ戻せるのはusers表に居る人だけだからである(実測 234,480点のうち191,844点、
-- 差は42,636点)。**users表の行数ではない** —— あちらは「人」の数でcacheを持たない人を
-- 含むため(実測193,359行)、item_countから引いても素材の数にはならない。
-- **両方を同じ走査で採る** —— 片方だけが新しい値だと、画面に並ぶ2つの数字がいつの時点の
-- ものか読めなくなる。
--
-- payload_json は種別ごとの付随物。今はgift_iconだけが使い、eventsから引いた
-- {gift_id: 名前}(実測500ms)を持つ —— 一覧のたびには引けないが、名前が無いと画面がidしか
-- 名乗れないため、走査と同じ契機で採ってここへ置く。参照先を持たない単独表なので
-- ON DELETEの伝播は無く、種別ごとに全置換する。
CREATE TABLE IF NOT EXISTS asset_scan (
    kind TEXT PRIMARY KEY,
    scanned_at REAL NOT NULL,
    duration_ms REAL NOT NULL DEFAULT 0,
    item_count INTEGER NOT NULL DEFAULT 0,
    listable_count INTEGER NOT NULL DEFAULT 0,
    total_bytes INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL DEFAULT '{}'
);
-- Userアイコンの「配信者ごとの出現回数」。asset_scan.payload_json に入れられない唯一の
-- 集計なので表にする: 配信者×視聴者で、実測93,621行(配信者3人)ある。JSONに畳むと
-- 1行が数MBになり、一覧を1page出すたびに全部parseすることになる。
--
-- streamer='' の行は**全配信者を通した合計**。queryを1本にするために持つ(合計を毎回
-- GROUP BYで作ると、配信者を選ばない既定の一覧が毎回93,621行を畳むことになる)。
-- 鍵が identity_key で avatar_key(sha1)でないのは、一覧の1行が「素材」ではなく「人」
-- だからである(users表と直接joinできる形にしておく)。
-- 参照先を持たない単独表。走査のたびに全置換するので ON DELETE の伝播も要らない。
CREATE TABLE IF NOT EXISTS asset_avatar_freq (
    streamer TEXT NOT NULL,
    identity_key TEXT NOT NULL,
    uses INTEGER NOT NULL,
    PRIMARY KEY (streamer, identity_key)
);
-- 「出現の多い順」をindexだけで満たすためのもの。列の向きをORDER BYと揃えてある
-- (idx_users_last_seen と同じ理由)。これが無いと、その配信者の行(実測で最大62,000行)を
-- 1page出すたびに並べ直すことになる。
CREATE INDEX IF NOT EXISTS idx_asset_avatar_freq_uses
    ON asset_avatar_freq(streamer, uses DESC, identity_key ASC);
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
-- TikTok本体が出すhighlight(LIVE replayの切り抜き)1本。実体はfilesystemに在り、この表は
-- 「どこで見つけたか」と「照合の結果どうだったか」だけを持つ。
--
-- 置き場が複数ある(``layout.highlight_dirs``)ので、root_key と source_dir を必ず残す。
-- pathだけでは、同じfile名の別の置き場の物と区別が付かず、画面も利用者もfileへ戻れない。
--
-- unique(unique_id, filename) にしてあるのは、同じhighlightが正規の置き場と現行の置き場の
-- 両方に在り得るためである(移行の途中では必ずそうなる)。実体は1本なので行も1本にし、
-- 見つけた場所は先に当たった置き場(highlight_dirsの順)で上書きする。
--
-- statusは 'new'(未照合) / 'matching'(queueに居る) / 'matched' / 'failed' / 'missing'。
-- missing は走査でfileが見つからなかった行で、**消さない** —— segmentには人が直した内容が
-- 貼り付いているので、外付けdriveを挿し忘れた回に消えると取り返せない。fileが戻れば
-- 走査が status を元へ戻す(matched_at が在れば matched、無ければ new)。
CREATE TABLE IF NOT EXISTS highlight_videos (
    id INTEGER PRIMARY KEY,
    unique_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    path TEXT NOT NULL,
    root_key TEXT,
    source_dir TEXT,
    bytes INTEGER,
    duration_seconds REAL,
    status TEXT NOT NULL DEFAULT 'new',
    error TEXT,
    -- 照合時の設定(days/scope/gift_lead/...)をそのまま。既定値は動くので、この結果が
    -- どの条件で出たのかは行が自分で名乗れないといけない。
    scope_json TEXT,
    matched_at REAL,
    created_at REAL,
    UNIQUE(unique_id, filename)
);
CREATE INDEX IF NOT EXISTS idx_highlight_videos_uid ON highlight_videos(unique_id, status);
-- highlight 1本の中のgift演出1つ。highlightはmontageで、平均6秒のgift演出が10個ほど、複数の録画から
-- 繋がれている(doc/HIGHLIGHT_MATCH.md)。start/end は**highlight自身の時間軸**の秒で、
-- media_start は当たった録画のmedia軸の秒である。2つの軸を1行に持つので名前で分ける。
--
-- approved/edited/excluded/memo と、手で差し替えたgift列は**人の入力**である。再照合は
-- 機械の列だけを書き換え、ここは残す(``tictok.store.highlights`` のdocstringに保存し直し方)。
-- dropped は「前回は在ったが今回の照合では出なくなった」印で、人の入力を持つ行だけが残る。
CREATE TABLE IF NOT EXISTS highlight_segments (
    id INTEGER PRIMARY KEY,
    highlight_id INTEGER NOT NULL REFERENCES highlight_videos(id) ON DELETE CASCADE,
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
    -- 映像が切り替わり終わる秒(highlight自身の時間軸)。start は**音**で決めた境目で、
    -- TikTokのmontageは音を一瞬で切り替えながら映像には演出を掛ける。実測(境目29箇所)で
    -- 映像は中央値0.60秒あと、手前に出た境目は1つも無い。切り出しの頭の既定はこちらで、
    -- start のままにすると全部の切り出しの頭に前のgiftの場面が残る。
    -- NULL は「測っていない/測れなかった」で、0や start では表せない。**既定値で埋めない**。
    video_start REAL,
    -- **次の**giftへの切り替わりが始まる秒。end は次の音の境目で、演出はそこを跨ぐ ――
    -- 実測で end より 0.93秒手前から次の場面が現れている境目が在り、その窓を通しで観ると
    -- 「2人目のgiftの終わりに3人目のgiftが少し映る」形になっていた(誰のgiftかを誤認させる)。
    -- 切り出しの尻の既定はこちらである。NULL の意味は video_start と同じ。
    video_end REAL,
    -- 測ろうとしたか。video_start/video_end が NULL のままでも、測って決まらなかったのか
    -- 一度も測っていないのかで画面の言うことが変わる(前者は素材の側の話、後者は操作の話)。
    -- 両端は1回の測定で同時に出る(:func:`tictok.media.highlight_switch.switch_span`)ので、
    -- 印は1つで足りる。
    video_probed INTEGER NOT NULL DEFAULT 0,
    approved INTEGER NOT NULL DEFAULT 0,
    edited INTEGER NOT NULL DEFAULT 0,
    excluded INTEGER NOT NULL DEFAULT 0,
    dropped INTEGER NOT NULL DEFAULT 0,
    memo TEXT
);
CREATE INDEX IF NOT EXISTS ix_highlight_segments_hl ON highlight_segments(highlight_id, idx);
-- gift演出1つが持つgift。**1 segment 1 gift では持てない。** segmentは最長8.3秒あり、その中に
-- 演出を持つgiftが複数入る —— 実測の最後のgift演出(t=54–60)に Galaxy 1000💎(54.99s)と
-- Spartan Helmet 399💎(57.43s)が入っており、画面に映っていたのは**後者**(t=59.0から兜)なのに
-- 「窓の中で最も高額」の規則が範囲内の399💎を範囲外の1000💎に負けさせた。出力をgifterごとに
-- 1本ずつ作る以上、これは「giftが1件落ちる」ではなく**別人の名前が付く**誤りである。
-- **成果物の単位はsegmentではなくgiftである。**
--
-- gift演出の属性はここへ降ろさない。降ろすと意味が変わる ―― idx は「gift演出の並び」で書き出しの
-- 順序が読んでいる値、votes/ratio/corr/confidence は「そのgift演出が当たっている確からしさ」で
-- あってgiftの確からしさではなく、media_start はgift演出の頭(giftの位置は gift_media_time)、
-- effect_json は検出した演出区間(giftごとの重なりは has_effect)、approved は「このgift演出を
-- 確認した」であって「このgifterを確認した」ではない。
CREATE TABLE IF NOT EXISTS highlight_segment_gifts (
    id INTEGER PRIMARY KEY,
    segment_id INTEGER NOT NULL REFERENCES highlight_segments(id) ON DELETE CASCADE,
    -- highlight_id は segment から辿れるが持たせる。俯瞰(coverage)と書き出しは
    -- 「このhighlightのgift全部」をJOIN 1回で引くので、辿らせると毎回2表を跨ぐ。
    highlight_id INTEGER NOT NULL REFERENCES highlight_videos(id) ON DELETE CASCADE,
    -- そのsegmentの中の時刻順。gift演出の並び(highlight_segments.idx)とは別物である。
    idx INTEGER NOT NULL,
    -- events.id そのもの。**画面が選ぶのは「どのeventか」だけ**なので、ここがNULLの
    -- gift行は存在しない(giftを持たないgift演出は、この表に行を持たないことで表す)。
    gift_event_id INTEGER NOT NULL,
    -- events.gift_id はINTEGERだが、こちらはTEXTで持つ。SQLiteは型を強制しないので、
    -- 混ぜると同じgiftが 1234 と '1234' の2通りで入り、突き合わせが黙って外れる。
    gift_id TEXT,
    gift_name TEXT,
    diamonds INTEGER,
    -- events.gift_count そのもの(1回のeventでまとめて投げた個数)。**diamonds は個数を
    -- 掛けた後の合計**なので、これが無いと「30💎を9個」と「270💎を1個」が同じ値になる。
    -- 演出が出るかを決めるのは1個あたりの単価の方で、下限の判定はそちらで行う
    -- (``store.highlights.gift_unit_diamonds``)。
    gift_count INTEGER,
    gift_image TEXT,
    user_unique_id TEXT,
    user_nickname TEXT,
    user_id TEXT,
    identity_key TEXT,
    -- そのgiftが録画のmedia軸のどこに在るか。**差ではなく絶対秒で持つ** —— 差にすると、
    -- 人がgift演出の端を1秒ずらした瞬間にgiftの位置まで1秒動く(動いていないのは録画の中の
    -- giftの方である)。highlight内の秒は ``store.highlights.gift_position`` が毎回引き直す。
    gift_media_time REAL,
    -- segmentの [start, end] の中に居るか。0 は gift_lead で手前へ伸ばした窓に入っただけで、
    -- **highlightにはその手前の映像が無い**(別の時刻のgift演出が繋がっているだけ)。
    inside INTEGER NOT NULL DEFAULT 1,
    -- そのsegmentの主。inside の中で最も高額な1件(insideが1件も無いときだけlead窓の中)。
    is_primary INTEGER NOT NULL DEFAULT 0,
    -- **gift単位の「演出と重なるか」の列は持たない。** 差分による演出検出は実測で両方向に
    -- 無力だった —— 60.8秒の実物で最も分かりやすい全画面演出(Flying Jets 5000💎 / 白鳥 /
    -- 花火)は区間が1つも出ず、出た2区間はどちらもTikTok自身の継ぎ目のワイプだった。
    -- 7本のgift 47件で当たりは0件である。**当たりが0件の信号を表に置くと、いずれ誰かが
    -- 信じる。** 生の演出区間は診断用に ``highlight_segments.effect_json`` へ残してあり、
    -- 検出器を作り直すならそこが起点になる。演出が映っているかを人が見る手段は代表frameの
    -- 2枚並べ(highlight側と録画側の同じ秒)で、**人の目のほうがこの検出器より確実に強い。**
    -- 人がこのgiftを差し替えた/足した印。gift演出側の ``edited``(端を動かした)とは**別にする**
    -- —— 1つにすると、端を微調整しただけで人のgift差し替えが守られたことになり、再照合が
    -- 機械の答えで上書きすべき行を守ってしまう(逆も起きる)。
    manual INTEGER NOT NULL DEFAULT 0,
    -- そのgiftの**見せ場**。1つのgift演出に順番待ちで並んだ演出のうち、このgiftのものが
    -- 映っている区間で、映像の切り替わりまで詰めた後の値である(highlight_match の
    -- ``_attach_shows``)。**NULLは「まだ割っていない」**で、gift演出の窓と同じという意味では
    -- ない —— gift演出を割れるのは演出の数と載ったgiftの数が一致したときだけなので、多くの
    -- 行はNULLのままである。人が触った ``cut_start``/``cut_end`` とは持ち主が違い、
    -- **人の窓の方が優先する**(``store.highlights.gift_cut``)。
    show_start REAL,
    show_end REAL,
    -- 人がこのgift 1件だけを出力から外した印。gift演出側の ``excluded`` と**別に要る** ——
    -- gift演出が残ったままgift 1件だけを落とす場面があり、gift演出単位でしか外せないと巻き添えで
    -- 同じgift演出の他のgiftまで消える。
    excluded INTEGER NOT NULL DEFAULT 0,
    -- **このgiftだけの切り出し範囲**(highlight自身の時間軸の秒)。NULL は「gift演出の窓をその
    -- まま使う」という意味で、gift演出の値をcopyして埋めてはいけない —— copyすると、再照合で
    -- gift演出が動いたときに、人が一度も触っていないgiftの窓だけが古い場所へ取り残される。
    --
    -- gift演出の窓と**別に要る**。1つのgift演出は最長8.3秒あり、そこに別人のgiftが複数入る(実測で
    -- 6.0秒のgift演出に あきと6000💎(1.17s) / おニャンコ999💎(4.55s) / るきしろ99💎(0.32s) の
    -- 3人)。出力はgifterごとに1本なので、窓がgift演出単位だと**同じ6秒が3人ぶんのfileへ同じ形で
    -- 入り**、しかも1人の行から窓を詰めると他の2人のfileまで一緒に動く。
    --
    -- 範囲は必ずgift演出の中に収める。montageなのでgift演出の外は「その少し前」ではなく**まったく
    -- 無関係な場面**で、そこにこのgiftの映像は無い。
    cut_start REAL,
    cut_end REAL,
    -- **人がこのgiftの当たりとして選んだ1本**の印。同じgiftはTikTokの複数のhighlightに
    -- 入るので(実測で1件が3本)、そのgiftを代表する当たりが機械の順位で決まっていた。
    -- 順位はgift演出の中で一番よく映っている人を当てる代用でしかなく、**その人自身の演出が
    -- 映っているのは別のhighlightの方**という形が普通に起きる(実測: Whale diving 2,150💎は
    -- 3本に当たり、11.1秒ある1本にだけ本人の演出が映っていて、代表は5.9秒の別の本だった)。
    -- 立つのは同じ ``gift_event_id`` の中で1行だけで、書き出しの重複排除(``dedup_by_gift``)も
    -- 画面の代表もこの印を最優先に読む。gift演出側の ``approved`` とは別物である ——
    -- あちらは「このgift演出を確認した」、こちらは「このgiftはこの1本を使う」である。
    chosen INTEGER NOT NULL DEFAULT 0,
    -- 前回の照合には在ったが今回は出なくなった印。人の入力を持つ行だけが残る。
    dropped INTEGER NOT NULL DEFAULT 0,
    -- 同じgiftが1つのgift演出へ2度入ることは無い(``highlight_match._assign_gifts`` が保証する)。
    -- 保存し直しが行を二重に積まないための最後の砦でもある。
    UNIQUE(segment_id, gift_event_id)
);
CREATE INDEX IF NOT EXISTS ix_highlight_segment_gifts_seg
    ON highlight_segment_gifts(segment_id, idx);
-- 俯瞰(coverage)は「その週のgift eventがhighlightのどこに出たか」をevent idで引く。
CREATE INDEX IF NOT EXISTS ix_highlight_segment_gifts_event
    ON highlight_segment_gifts(gift_event_id);
CREATE INDEX IF NOT EXISTS ix_highlight_segment_gifts_hl
    ON highlight_segment_gifts(highlight_id);
-- 検証の面で人が「この行は見た」と付ける印。**gift event 1件ごとに持つ。**
--
-- gift演出(highlight_segments.approved)にもgift行にも載せられない。載せられるのは
-- highlightに当たった行だけで、**この面で一番確かめたいのは「1本も出ていない」行**
-- —— 高額なのにhighlightに現れないgiftが、TikTokが選ばなかったのかこちらの照合が
-- 取りこぼしたのかを人が判ずる相手である。その行はgift演出もgift行も持たないので、
-- 印を残す場所がそもそも無い。approved は「このgift演出を確認した」であって
-- 「このgiftを確認した」ではない(highlight_segment_gifts の注)。
--
-- 行が在ること = 確認済み。取り消しは行を消す(状態列を持たない ―— 2値しか無い印に
-- 列を足すと、行が在るのに未確認、という読み手のいない状態が作れる)。
--
-- gift_event_id は events.id だが**外部keyにはしない**(highlight_segment_gifts.
-- gift_event_id と同じ約束)。eventの側の整理でこの表がFK違反の元になると、印を
-- 消すのではなく書き込みそのものが止まる。
CREATE TABLE IF NOT EXISTS highlight_gift_checks (
    gift_event_id INTEGER PRIMARY KEY,
    -- いつ確認したか。印を消して付け直すと更新される。**再照合で古くなった印を
    -- 見分けるための材料**であって、画面の絞り込みはこの値を読まない。
    checked_at REAL NOT NULL
);
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

# 横断検索の索引。日本語は語境界が無いのでunicode61では部分一致にならない。trigramなら
# 3文字以上の任意部分文字列が引ける(1-2文字のqueryはLIKEへ落とす)。索引する列は原文
# (body)ではなく畳んだ本文(body_norm)で、「ウザ」と「うざ」が同じ索引語になる。
# 列の入れ替えには既存索引の作り直しが要るため、DDLはmigrationからも参照する。
SEARCH_FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
    body_norm, content='search_hits', content_rowid='id', tokenize='trigram'
);
"""

SCHEMA += SEARCH_FTS_DDL

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
    名乗らないと、画面で相手から履歴を辿れない(名前だけが一致する別人になる)。

    順番は不変のuser_idが先(users表のidentity_keyと同じ考え方)。handle先頭にしていた頃は、
    同じ相手でもhandleの載らない戦(実data 1921件中24件)が別keyへ落ち、13名が2行に割れて
    いた。handleは改名で変わり、nicknameは別人と衝突しうるので、両方ともfallback。"""
    return opp.get("user_id") or opp.get("unique_id") or opp.get("nickname")


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

    active_seconds = 0.0
    battle_seconds = collab_seconds = 0.0
    battle_count = collab_count = 0
    sessions_with_battle = sessions_with_collab = 0
    # 配信ごとの内訳(古い順)。**窓を1つも持たないsessionも並べる** — コラボ0%の配信を
    # 落とすと、推移が「コラボした配信だけ」の系列になり、比率が実態より高く見える。
    series = []
    for sid, start, _end in sorted(session_spans, key=lambda s: (s[1], s[0])):
        span = spans.get(sid)
        if span is None:
            continue
        kinds = by_session.get(sid) or {"b": [], "c": []}
        b_ints = merge_intervals(kinds["b"])
        c_only = subtract_intervals(merge_intervals(kinds["c"]), b_ints)
        s_active = span[1] - span[0]
        s_battle = total_span(b_ints)
        s_collab = total_span(c_only)
        active_seconds += s_active
        battle_seconds += s_battle
        collab_seconds += s_collab
        battle_count += len(kinds["b"])
        collab_count += len(kinds["c"])
        if kinds["b"]:
            sessions_with_battle += 1
        if kinds["c"]:
            sessions_with_collab += 1
        series.append(
            {
                "session_id": sid,
                "started_at": span[0],
                "active_seconds": s_active,
                "collab_seconds": s_collab,
                "battle_seconds": s_battle,
                "solo_seconds": max(0.0, s_active - s_battle - s_collab),
                # 比率は各配信の中での割合。移動平均は画面側で秒を足し直して出す
                # (この率をそのまま平均すると、10分の配信と6時間の配信が同じ重みになる)。
                "collab_share": (s_collab / s_active * 100) if s_active > 0 else 0.0,
                "battle_share": (s_battle / s_active * 100) if s_active > 0 else 0.0,
                "collab_count": len(kinds["c"]),
                "battle_count": len(kinds["b"]),
            }
        )
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
        # 配信ごとの内訳(古い順)。通算の比率だけでは「増えているのか減っているのか」が
        # 判らないため、推移を引けるだけの素の秒を渡す。
        "series": series,
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
    """集計read専用の接続を**上限付きで**共有するpool。

    executeのたびに空いている接続を1本借り、行を読み切ってから返す。cursorのまま外へ
    返すと、まだ読み終えていない結果集合の裏で別threadが同じ接続へqueryを流せてしまう。
    呼び出し側は sqlite3.Connection と同じ書き方(``execute(...).fetchall()``)のままでよい。

    **かつては1本に直列化していた。** 理由は「threadごとに持つとpage cacheが接続ごとに
    積み上がる(to_threadのpoolは数十threadあり、集計は数百MBの表を舐める)」であり、これは
    今も正しい。上限付きのpoolはその心配に当たらない — 接続数は _read_pool_size で決まる
    数本で、threadの数では増えない。

    直列のままにしなかったのは、直列化の代償が測れる大きさになったからである。配信者画面は
    profile / cohort / 期間別rankingなどを**同時に**投げるので、直列だと後続は前の合計を
    待つ。実測(本番の複製・921 battle窓を各threadが舐める):

    | 同時 | 接続1本(直列) | pool | |
    | ---: | ---: | ---: | ---: |
    | 1 |  237ms |  209ms | 1.13倍 |
    | 2 |  458ms |  295ms | 1.55倍 |
    | 4 | 1001ms |  300ms | **3.33倍** |

    **この判断はcohortのcache化とprofileのJSON parse削減より後でしか成立しない。** それ以前
    に測ったときはpoolの方が遅かった(profile 1,069 -> 1,511ms) — 数秒のCPU律速な集計が
    重なると、並べても互いのCPUを食い合うだけだった。先に律速をSQL側へ寄せたので逆転した。
    """

    __slots__ = ("_free", "_conns")

    def __init__(self, conns, lock=None) -> None:
        # lock引数は受け取らない設計へ移ったが、呼び出し側の互換のため位置引数は残す。
        self._conns = list(conns)
        self._free: "queue.LifoQueue" = queue.LifoQueue()
        for conn in self._conns:
            self._free.put(conn)

    def execute(self, sql: str, params=()) -> _ReadResult:
        # 空き待ちとSQL本体は別の内訳へ積む。SQL自体はTimedConnectionが ``db.read``。
        with perf.timer("db.read_wait"):
            conn = self._free.get()
        try:
            return _ReadResult(conn.execute(sql, params).fetchall())
        finally:
            self._free.put(conn)

    def close(self) -> None:
        for _ in self._conns:
            self._free.get()
        for conn in self._conns:
            conn.close()
