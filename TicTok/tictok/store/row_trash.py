"""消えた行そのものを残す(row単位のundo)。DELETE triggerと、その保持・復元。

**DBの保護の3段目である。** 前の2段には塞げない穴がそれぞれ在る:

  1. authorizer(``dbmaint.attach_drop_guard``)は ``DROP TABLE/INDEX/TRIGGER/VIEW`` を
     拒否するが、**serverの接続にしか掛からない**。sqlite3.exe やDB browserは自分でfileを
     開くので素通りする。
  2. 行数の見張り(``dbmaint.check_row_guard``)は急減を検知して古い退避の刈り取りを凍結する
     が、**小さい表の部分削除を原理的に見分けられない** —— bookmarks 192件のうち59件が
     誤って消えても、同じ59件は「表示中をすべて削除」という正常な操作でも消える。行数
     だけを見ている限り、この2つは同じ観測になる。

区別が付かないなら、**消えた行そのものを残す**しかない。それがこのmoduleである。

**なぜtriggerなのか。** triggerはschemaの一部なのでengineが強制する。誰がその接続を開いた
かに関係なく発火するので、authorizerが効かない外部processのDELETEでも退避が残る(この
性質は実測で確認済み: 直接DELETE / FK cascade削除 / **別processからのDELETE** のいずれでも
捕捉した)。``DROP TABLE`` されればtrigger自身も消えるが、それまでに積んだ退避行は
:data:`TRASH_TABLE` に残る。

対象表(:data:`ROW_TRASH_TABLES`)
--------------------------------

  bookmarks / clip_groups / clip_presets / transcript_corrections / settings /
  monitored_targets / user_aliases / user_merges

条件は「人がやり直すしか復旧手段が無く、かつ1回の削除で積む行が少ないこと」である。
``dbmaint.GUARDED_TABLES`` の中で、この2つを同時に満たすのがこの8つに当たる。

**events と viewer_samples には掛けない。** これらは実配信からしか採れない収集dataなので
価値の面では対象に見えるが、削除が桁違いに大きい —— session 1件の削除で events が最大
36,892行 cascade する(``config.get_db_guard_drop_rows`` の実測)。実DBのcopyで同じ形の
triggerを events へ付けて測った(2026-09-02、session 501 の36,892行):

  ==========  ==========  ====================
  trigger     session削除  退避に積む量
  ==========  ==========  ====================
  無          0.60〜0.72秒  —
  有          1.07〜1.09秒  36,892行 / 30.1MB
  ==========  ==========  ====================

**session 1件を消すたびに30MBである。** 対象7表は1年ぶんを貯めても数百KB(下記)なので、
桁が5つ違う。しかもこちらは journal(取り込み時点でdiskへ追記する耐久log)の再生と、
行数・割合の見張りが既に守っている —— 見張りの盲点は「小さい表の部分削除」であって、
36,892行の急減ではない。**盲点の無いところに費用を払わない。**

settingsの境界
--------------

``settings`` 表は ``INSERT ... ON CONFLICT DO UPDATE``(``store/settings_store.py`` の
``set_settings`` 等)で更新される。**UPDATEはDELETEではないのでtriggerは発火しない。**
つまりここに残るのは「設定の行が消えた」ときだけで、**「設定値を変えた」は退避の対象外**
である。設定値の履歴を守るのは ``core/settings_export`` が各保存先へ書き出すJSONの世代で、
この表ではない。境界を書いておかないと、次に読む人が「設定はいつでも戻せるはず」と読む。

trigger定義の作り直し
---------------------

triggerは列名を1つずつ書いた ``json_object()`` を持つので、対象表に列が増えると**古い列の
ままの退避**を作り続ける(足した列の値が消えても残らない)。そこで、あるべき定義を毎起動で
組み立て、``sqlite_master`` に入っている実物と突き合わせ、**食い違ったら作り直す**。

指紋を db_maintenance のような別の場所へ持たない。実物そのものと比べるほうが強い ——
外から ``DROP TRIGGER`` された場合も「食い違い」として同じ経路で直る。作り直しは
``DROP TRIGGER`` を含むので ``dbmaint.allow_schema_drops()`` で包む。

保持
----

無限には貯めない。保持日数は ``config.get_row_trash_keep_days()``(既定365日)で、刈り取りは
起動時に1回(``store/maintenance.py`` の ``_migrate_row_trash``)。ops_eventsのretentionが
起動時にしか走らないのと同じ流儀である。

**既定が長いのは、これが安いからである。** 実測(2026-09-02、logs/ の46日ぶんのJSONL):
対象7表へのDELETE要求は46日で29件(bookmarks 11 / monitored_targets 17 / clip_groups 1 /
clip_presets・transcript_corrections・settings 各0)、およそ0.63件/日。1行のJSONは実測で
bookmarks 292 byte・transcript_corrections 224 byte・clip_presets 448 byteなので、365日
貯めても数百KBにしかならない(現行DBは1.6GB)。cascadeで最も大きいのは録画1本の削除で、
実測の最大は transcript_corrections 1,070行(約240KB)である。

DBの退避(``core/dbmaint.py``)の暦層(日次14日 + 週次8週 ≒ 70日)より長く持つのは、
**戻せる単位が違う**からである。退避はその時点の全体なので、1行を戻すために他の全ての
変更も巻き戻る。行単位で戻せるのはこちらだけなので、退避より長く残す意味がある。

費用
----

実DB(1.6GB)のcopyで、trigger有/無の insert / delete を対象7表それぞれ2,000行 x 3試行
(中央値)で測った(2026-09-02):

* **INSERT は変わらない。** AFTER DELETE triggerなので当然だが、確かめてある。
* **DELETE は1行あたり +3.6〜8.2 マイクロ秒**(1 transactionで2,000行を消した場合)。
  1行ずつcommitする形(画面の1操作と同じ)では +64〜106 マイクロ秒/行で、削除1回が
  実測0.035ミリ秒から0.125ミリ秒になる。
* 最も大きい cascade(録画1本の削除で transcript_corrections 1,070行)でも +6ミリ秒。

人が待つ操作でこの差が見えることはない。**遅くならないから採る**のであって、
遅くなるなら対象表を減らす側へ倒すこと(判断の材料はこの節の測り方をそのまま使える)。

限界(このmoduleが守らないもの)
------------------------------

* ``DROP TABLE`` そのもの。表ごと落とされればtriggerも消え、以後の削除は残らない
  (それまでの退避行は残る)。
* ``UPDATE`` による書き換え。上のsettingsの節と同じで、消えた行だけが対象である。
* 対象表の列にBLOBが入っていた場合。``json_object()`` はBLOBを表現できず例外になり、
  triggerを含むDELETEごと失敗する。7表はいずれもPython側から str/int/float/None でしか
  書かれないので実際には起きないが、**起きたときは黙って捨てるのではなく削除が失敗する**。

対象表の列を落とすとき
----------------------

triggerは列を1つずつ名指しするので、SQLiteは**その列を参照するtriggerが在る間
``ALTER TABLE ... DROP COLUMN`` を拒否する**(``error in trigger ... : no such column``)。
対象7表から列を落とすmigrationを書くときは :func:`without_triggers` で包むこと ——
抜けた区間の削除は退避されないので、包む幅は必要な最小にする。
"""
import json
import logging
import time
from contextlib import contextmanager

from tictok.core import dbmaint

logger = logging.getLogger("tictok.storage")

# 退避表の名前。schemaの定義は tictok/store/_common.py の SCHEMA に在る。
TRASH_TABLE = "row_trash"
# triggerの名前の頭。作り直しの対象を名前だけで見分けられるようにしてある。
TRIGGER_PREFIX = "trg_row_trash_"

# 退避の対象表。**増やすときはmodule docstringの条件を満たすか確かめること。**
ROW_TRASH_TABLES = (
    "bookmarks",
    "clip_groups",
    "clip_presets",
    "transcript_corrections",
    "settings",
    "monitored_targets",
    "user_aliases",
    "user_merges",
)

# triggerの中で「今の時刻」を作る式。epoch秒(REAL)で、この repo が時刻に使っている単位と
# 揃えてある。julianday('now')はUTC基準なので、書いた機械のtimezoneに依存しない。
# strftime('%s')は秒までしか持たず、同じ秒に消えた行の順序が付かなくなるので使わない。
_NOW_EPOCH_SQL = "(julianday('now') - 2440587.5) * 86400.0"


def trigger_name(table: str) -> str:
    return f"{TRIGGER_PREFIX}{table}"


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _quote_text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _table_columns(conn, table: str) -> list:
    """(列名, PKでの位置) の並び。表が無ければ空。"""
    rows = conn.execute(f"PRAGMA table_info({_quote_ident(table)})").fetchall()
    return [(row[1], int(row[5])) for row in rows]


def build_trigger_sql(conn, table: str):
    """``table`` のAFTER DELETE triggerのあるべき定義。表が無ければ None。

    書式を1通りに固定してあるのは、これが**指紋そのもの**だからである
    (:func:`ensure_triggers` は ``sqlite_master`` の実物とこの文字列を比べる)。改行や空白の
    入れ方を変えれば全DBでtriggerが1度だけ作り直される —— 壊れはしないが、意味の無い
    作り直しなので、体裁を触るなら理由を持って触ること。

    識別子は必ず引用する。``bookmarks.end`` のようにSQLの予約語と同じ名前の列が実在し、
    引用しないとtriggerの作成そのものが構文errorになる。
    """
    columns = _table_columns(conn, table)
    if not columns:
        return None
    pk = [name for name, position in columns if position > 0]
    if pk:
        # 複数列のPKは '/' で連結する。今の7表はすべて1列だが、連結を後から足すと
        # それまでの退避行と表記が食い違う。
        pk_expr = " || '/' || ".join(f"CAST(OLD.{_quote_ident(name)} AS TEXT)" for name in pk)
    else:
        # PKを持たない表は行を名指しできない。row_pkはNULLにして、row_jsonだけで残す。
        pk_expr = "NULL"
    payload = ", ".join(
        f"{_quote_text(name)}, OLD.{_quote_ident(name)}" for name, _ in columns)
    return (
        f"CREATE TRIGGER {_quote_ident(trigger_name(table))}"
        f" AFTER DELETE ON {_quote_ident(table)}\n"
        f"BEGIN\n"
        f"INSERT INTO {_quote_ident(TRASH_TABLE)}"
        f" (table_name, row_pk, deleted_at, row_json)\n"
        f"VALUES ({_quote_text(table)}, {pk_expr}, {_NOW_EPOCH_SQL},"
        f" json_object({payload}));\n"
        f"END"
    )


def _stored_trigger_sql(conn, name: str):
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = ?", (name,)
    ).fetchone()
    return row[0] if row is not None else None


def _same_definition(left, right) -> bool:
    """定義が同じか。空白の入り方だけは無視する。

    SQLiteは ``CREATE TRIGGER IF NOT EXISTS`` の ``IF NOT EXISTS`` を落として保存する
    (実測 3.39.4)ので、こちらは ``IF NOT EXISTS`` を付けずに組み立てて素で比べられる。
    それでも空白を畳んでから比べるのは、将来のSQLiteが体裁を整え直した場合に**毎起動で
    作り直し続ける**状態を避けるためである(内容は同じなのに永久に一致しない)。"""
    if left is None or right is None:
        return False
    return " ".join(left.split()) == " ".join(right.split())


def ensure_triggers(conn) -> dict:
    """対象表のDELETE triggerを、あるべき定義に揃える。冪等。

    lockは取らない。呼び出し側(``store/maintenance.py`` の ``_migrate_row_trash``)が
    ``self._lock`` を保持した起動時の区間から呼ぶ。

    作り直しは ``DROP TRIGGER`` を伴うので ``dbmaint.allow_schema_drops()`` で包む。
    包む範囲を1つのtriggerに絞ってあるのは、許可区間を必要な最小の幅で開けるためである。
    """
    created = []
    replaced = []
    skipped = []
    for table in ROW_TRASH_TABLES:
        desired = build_trigger_sql(conn, table)
        if desired is None:
            # 表が無いDB(古いschema・別のDB)ではその表だけを飛ばす。数えられないことと
            # 0行であることを混同しない(GUARDED_TABLESと同じ規約)。
            skipped.append(table)
            continue
        name = trigger_name(table)
        current = _stored_trigger_sql(conn, name)
        if _same_definition(current, desired):
            continue
        if current is not None:
            with dbmaint.allow_schema_drops():
                conn.execute(f"DROP TRIGGER {_quote_ident(name)}")
            replaced.append(table)
        else:
            created.append(table)
        conn.execute(desired)
    if created or replaced:
        logger.info(
            "消えた行の退避triggerを設定しました（新規 %d / 作り直し %d）",
            len(created), len(replaced),
            extra={"event": "storage.row_trash_triggers",
                   "ctx": {"created": created, "replaced": replaced,
                           "skipped": skipped, "table": TRASH_TABLE}},
        )
    return {"created": created, "replaced": replaced, "skipped": skipped}


@contextmanager
def without_triggers(conn):
    """対象表のDELETE triggerを一時的に外す区間。抜けたら :func:`ensure_triggers` で戻す。

    要るのは1つの場面だけ —— **対象7表から列を落とすmigration**である。triggerは列を名指し
    するので、SQLiteはその列を参照するtriggerが在る間 ``DROP COLUMN`` を拒否する。

    **この区間の削除は退避されない。** 包む幅は落とす操作そのものだけにすること。区間の
    中で例外になってもtriggerは戻すが、戻せたかどうかは呼び出し側の責任ではなく、次の起動の
    :func:`ensure_triggers` が実物と突き合わせて必ず揃える。"""
    for table in ROW_TRASH_TABLES:
        name = trigger_name(table)
        if _stored_trigger_sql(conn, name) is None:
            continue
        with dbmaint.allow_schema_drops():
            conn.execute(f"DROP TRIGGER {_quote_ident(name)}")
    try:
        yield
    finally:
        ensure_triggers(conn)


def prune(conn, keep_days: int, now=None) -> int:
    """保持日数を過ぎた退避行を消す。消した件数を返す。

    ``keep_days`` が0以下なら1行も消さない(0=無効という、この repo の設定群の規約)。

    deleted_at 単独のindexは張っていないので全表scanになるが、この表は実測でも数千行に
    しかならず(module docstringの削除頻度)、走るのは起動時の1回だけである。索引を1本増やす
    費用はDELETEのたびに払う側に乗るので、そちらを避けた。
    """
    if keep_days <= 0:
        return 0
    cutoff = (time.time() if now is None else now) - keep_days * 86400.0
    removed = conn.execute(
        f"DELETE FROM {_quote_ident(TRASH_TABLE)} WHERE deleted_at < ?", (cutoff,)
    ).rowcount
    if removed:
        logger.info(
            "保持日数(%d 日)を過ぎた退避行 %d 件を削除しました", keep_days, removed,
            extra={"event": "storage.row_trash_pruned",
                   "ctx": {"keep_days": keep_days, "removed": removed,
                           "cutoff": cutoff}},
        )
    return removed


def list_rows(conn, *, table=None, since=None, until=None, limit=None) -> list:
    """退避行を新しい順に。表名と期間(epoch秒)で絞れる。"""
    sql = (f"SELECT id, table_name, row_pk, deleted_at, row_json"
           f" FROM {_quote_ident(TRASH_TABLE)} WHERE 1 = 1")
    params: list = []
    if table:
        sql += " AND table_name = ?"
        params.append(table)
    if since is not None:
        sql += " AND deleted_at >= ?"
        params.append(float(since))
    if until is not None:
        sql += " AND deleted_at < ?"
        params.append(float(until))
    sql += " ORDER BY deleted_at DESC, id DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))
    return conn.execute(sql, params).fetchall()


def counts_by_table(conn) -> list:
    """表ごとの件数と、最も古い/新しい退避の時刻。"""
    return conn.execute(
        f"SELECT table_name, COUNT(*) AS rows, MIN(deleted_at) AS oldest,"
        f" MAX(deleted_at) AS newest FROM {_quote_ident(TRASH_TABLE)}"
        f" GROUP BY table_name ORDER BY table_name"
    ).fetchall()


def restore_row(conn, trash_row, *, apply: bool) -> dict:
    """退避行を1件、元の表へ戻す。戻した/戻さなかった理由を返す。

    **既に同じidの行が在れば上書きしない。** 戻すつもりで現行の行を壊すのは、この仕組みが
    防ごうとしている事故そのものである(``INSERT OR REPLACE`` は使わない)。

    列は**今の表に在る列だけ**を書く。退避した後に落ちた列はそのまま捨て、退避した後に
    足された列はDEFAULTで埋まる。どちらも結果に載せるので、戻した行が元と同じでない場合は
    呼び出し側が名指しで言える。

    ``apply`` がFalseなら、判定だけ行って書き込まない(dry-run)。
    """
    table = trash_row["table_name"]
    # ok は「戻せる」、restored は「戻した」。dry-runでは ok だけが立つ ―― 2つを1つに
    # 畳むと、dry-runの結果を見た人が書き込まれたと読む。
    result = {"id": trash_row["id"], "table": table, "row_pk": trash_row["row_pk"],
              "deleted_at": trash_row["deleted_at"], "ok": False, "restored": False,
              "dropped_columns": [], "missing_columns": [], "reason": ""}
    columns = _table_columns(conn, table)
    if not columns:
        result["reason"] = "表が存在しません"
        return result
    try:
        payload = json.loads(trash_row["row_json"])
    except ValueError as exc:
        result["reason"] = f"row_jsonを読めません: {exc}"
        return result
    present = {name for name, _ in columns}
    result["dropped_columns"] = sorted(set(payload) - present)
    result["missing_columns"] = sorted(present - set(payload))
    pk = [name for name, position in columns if position > 0]
    if pk and all(name in payload for name in pk):
        where = " AND ".join(f"{_quote_ident(name)} IS ?" for name in pk)
        existing = conn.execute(
            f"SELECT 1 FROM {_quote_ident(table)} WHERE {where}",
            [payload[name] for name in pk],
        ).fetchone()
        if existing is not None:
            result["reason"] = "同じidの行が既に在るため戻しません"
            return result
    elif pk:
        result["reason"] = "退避にPRIMARY KEYの列が無く、既存行と突き合わせられません"
        return result
    names = [name for name, _ in columns if name in payload]
    result["ok"] = True
    if not apply:
        result["reason"] = "戻せます（dry-run）"
        return result
    conn.execute(
        f"INSERT INTO {_quote_ident(table)}"
        f" ({', '.join(_quote_ident(name) for name in names)})"
        f" VALUES ({', '.join('?' * len(names))})",
        [payload[name] for name in names],
    )
    result["restored"] = True
    result["reason"] = "戻しました"
    return result
