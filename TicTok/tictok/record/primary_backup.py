"""一次保存先(SSD)の中身を、元を残したまま別driveへ写す定期backup。

最終保存先への「移動」(``tictok.api.disk``)とは別物である。あちらは一次保存先から実体を
**運び出して**空きを作る操作で、運び終えた録画は一次保存先に居なくなる。こちらは一次保存先を
主とし、同じ中身の控えを別のdriveへ**増やす**。したがって元は必ず残り、backup先が壊れても
一次保存先だけで運用が続く。

写す先は ``<record_backup_dir>/_primary_backup/`` で、その下は3つに分ける::

    <record_backup_dir>/_primary_backup/
        data/                ... 一次保存先の木をそのまま写した物(poolを除く)
        pools/               ... 録画横断pool(avatars/emotes/gift_icons)のarchive
        ledger.json          ... 台帳(消えたfileの初検知日時・archiveの世代)

木と台帳を混ぜないのは、台帳が「写した物」と同じ名前空間に居ると、一次保存先に同名のfileが
生まれた瞬間に台帳が上書きされるからである。restoreは ``data/`` を丸ごと一次保存先へ戻し、
poolは ``pools/`` の最新archiveを展開する ―― 復旧する人が読む場所は2つだけで済む。

**差分の判定は size + mtime(秒)で行い、内容のhashは取らない。** 一次保存先は実測31GBで、
毎回の全読みはbackupの所要をdiskの読み出し速度そのものに縛り付ける(HDD 100MB/sなら1回
5分以上、しかもその間ずっと録画と同じdiskを奪い合う)。size+mtimeで見逃せるのは「sizeが1
byteも変わらず、mtimeも動かないまま中身だけが変わった」fileだけで、この保存先の中身
(書いたら二度と書き換えない .ts / mp4 / png)にそれは起こらない。判定材料を落とす代わりに、
判定の基準は**写した先の実fileのstat**に置く ―― 台帳に「写した」と書く方式だと、backup先の
fileが外から消えても台帳は写した気でいる。

**厳密なmirrorにはしない。** 一次保存先から消えたfileは
:func:`~tictok.core.config.get_record_backup_keep_deleted_days` が0なら残し続ける。厳密な
mirrorは、一次保存先での誤削除をそのままbackupへ伝播させ、「backupがあるのに戻せない」を
作る。backupの目的は事故から戻すことなので、伝播を遅らせる側に倒す。消えたと判定した日時は
台帳が持つ(``deleted``)。

**avatarsの73万fileはarchiveへ固める。** 費用がbytesではなくfile数で決まる領域で、素の
file copyでは書き込み先のdriveがそれを捌けない(実測は :data:`POOL_DIRNAMES` の項)。
poolは録画横断の1塊で1件ずつ取り出す運用も無いので、1本のzipへ固めて世代で置く。

作り直すかの判定は**2段の指紋**で行い、時刻では回さない(:func:`_plan_pool`)。
"""

import asyncio
import json
import logging
import os
import re
import secrets
import shutil
import time
import zipfile
from pathlib import Path

from tictok.core import cancel, config, layout
from tictok.record.backups import BACKUP_DIRNAME

logger = logging.getLogger("tictok.primary_backup")


class PrimaryBackupError(RuntimeError):
    """backupを始められない・続けられない。degradeせずに投げる。

    「空きが足りないので一部だけ写した」は、後で戻そうとした人が初めて気付く形の失敗である。
    始められない条件は始める前に投げ切り、backup先には中途半端な姿を作らない。"""


PRIMARY_BACKUP_DIRNAME = "_primary_backup"
# 写した木の置き場。名前を"recordings"にしないのは、一次保存先のfolder名が設定で変わる
# ためで、backup先の構造が設定値によって変わると復旧する人が場所を推測できない。
TREE_DIRNAME = "data"
POOL_ARCHIVE_DIRNAME = "pools"
LEDGER_NAME = "ledger.json"
LEDGER_VERSION = 1
# backup先の識別子。**台帳とは別のfile**に置く ―― 台帳は「読めなければ空から始める」
# 約束で(:func:`_load_ledger`)、識別子をそこへ同居させると台帳の破損が「別のdrive」と
# 区別できなくなる。中身は一度作ったら二度と変えない乱数1行で、DB側(``db_maintenance``)
# に控えた値と突き合わせる(:func:`_verify_root_identity`)。
ROOT_ID_NAME = "root-id.txt"

# 書きかけの一時名。dbmaint と同じ綴りに揃える(backup先を人が覗いたとき、DBの退避と
# 一次保存のbackupで「書きかけ」の見た目が違うと、どちらが壊れているのか判断できない)。
PARTIAL_SUFFIX = ".partial"

# 写さないもの。**root直下の名前だけ**で判定する ―― 深い階層まで名前で除外すると、
# 利用者が配信者folderの下に同じ名前のfolderを作った瞬間、その中身が黙って控えから
# 落ちる。ここに挙がる物はいずれも root直下にしか存在しない規約である(layout)。
#
#   _backup … 再mp4化・音量正規化が元mp4を退避する使い捨て(tictok.record.backups)。
#             成功が確かめられた時点で消される物で、控えを取る価値が無いどころか、
#             実測304GBまで積み上がった実績がある(backupの容量を数倍にしてしまう)。
EXCLUDED_TOP_LEVEL = (BACKUP_DIRNAME,)

# archiveへ固めるpool。いずれも録画横断で、録画1本には属さない(layout.pool_root)。
# 実測(2026-09-02, 一次保存先):
#     avatars     733,604 file / 0.55GB
#     emotes          275 file / 0.003GB
#     gift_icons    1,227 file / 0.037GB
# bytesは3つ合わせて0.6GBしかないのに、file数は木全体(3,481 file)の200倍である。
#
# **archiveにするのは速度の好みではなく、そうしないと成立しないからである。** 書き込み先の
# driveの実測(256MBを8MBずつ書いてfsync / 800 byteのfileを1000本):
#
#     drive   逐次        小fileの書き込み
#     D:      149.5 MB/s   30.1 file/s   ← backup先の第一候補
#     H:      108.2 MB/s  343.1 file/s
#     J:      164.7 MB/s  127.5 file/s
#     K:      136.4 MB/s  437.5 file/s
#
# avatars 733,604 file を素のfile copyでD:へ写すと 733,604 ÷ 30.1 ≒ **6.8時間**。最速の
# K:でも28分かかる。同じ0.6GBでも1本のzipなら逐次149.5MB/sの世界で、書き込みは数秒で終わる。
# 一方 ts原本31GB + mp4 8.6GB は大きいfileなので逐次側に載り、D:でも約4.5分で済む。
# 「大きいfileは差分copy・poolはarchive」の2本立てはこの表が決めている。
POOL_DIRNAMES = (
    layout.AVATAR_POOL_DIRNAME,
    layout.EMOTE_POOL_DIRNAME,
    layout.GIFT_ICON_POOL_DIRNAME,
)

# mtimeの一致とみなす幅(秒)。exFATのmtimeは2秒刻みで、SSD(NTFS)から写した直後でも
# 写した先のmtimeが最大2秒ずれる。ずれを許さないと、一度も変わっていないfileを毎回
# 写し直すことになる(rsync の --modify-window と同じ考え方)。
MTIME_TOLERANCE_SECONDS = 2.0

# 空き容量の余裕。写す量ちょうどでは、同じdriveへ他が1byte書いた時点で溢れる。
FREE_SPACE_MARGIN = 1.05

# poolのarchiveを作り直す閾値。前回のarchiveから件数がこれだけ増減したら作り直す。
# 1回の作り直しは実測4分23秒(SSD→SSD。上記のとおり元を読む費用が支配的なので、写す先が
# D:でも同程度)かかるので、配信が終わるたびに掛かる値にはしない。
# 20,000 file はavatar約6,700人ぶん(1人=.img/.meta/.type の3 file)で、73万fileの2.7%。
# 小さくすると毎回0.6GBを読み直し、大きくすると新しいavatarが控えに載らない期間が延びる。
POOL_REBUILD_FILE_DELTA = 20000
# 件数が動かなくても中身が入れ替わることはある(同じidのavatarの取り直し)。bytesの
# 変化率でも作り直しを掛ける。0.55GBの2%=11MBで、上の件数の閾値とほぼ同じ位置になる。
POOL_REBUILD_BYTES_RATIO = 0.02
# 残すarchiveの世代数。作り直した直後のarchiveが実は途中で切れていた、という失敗から
# 戻れるように、必ず1つ前を残す。世代を増やしても中身はほぼ同じで容量だけ増えるので、
# 設定にはしない(backup先の容量は録画本体のために使う)。
POOL_KEEP_GENERATIONS = 2

# 形式はzipの無圧縮(ZIP_STORED)。tarと実測で比べて選んだ(**いずれもSSD→SSDでの計測**。
# 所要のほとんどは73万fileを1つずつ読む費用で、写す先の書き込みは0.682GBの逐次 ―― D:の
# 149.5MB/sなら約5秒 ―― なので、実際のbackup先でもこの所要は大きく変わらない):
#     tar 282秒 / 1.872GB / 中間dataのpeak 429MB
#     zip 263秒 / 0.682GB / 中間dataのpeak 483MB
# 所要とmemoryは差が無く、**sizeだけが2.7倍違う**。tarはentryごとに512 byte headerを
# 置き、data部も512 byte境界へ丸める。avatar poolは3 fileのうち2つ(.meta/.type)が数十
# byteしかないため、この丸めが中身より大きくなる。zipは1 entryあたり数十byteで済む。
# 加えてzipは中央目録を持つので、1枚のavatarだけを取り出す復旧ができる(tarは頭から舐める)。
#
# 圧縮はしない。poolの中身はpng/jpeg(既に圧縮済み)で、掛けてもsizeはほとんど縮まず、
# 0.6GBぶんのCPU時間だけが増える。狙いはsizeの圧縮ではなく「73万回のfile作成を1回にする」
# ことである。
#
# 引き換えに、作り直しの間だけ中央目録ぶんのmemory(実測483MB)を持つ。archiveの形式上
# 避けられず(目録は末尾に一括で書く)、tarでも同じ桁(429MB)を払う。作り直しの頻度を
# :data:`POOL_REBUILD_FILE_DELTA` で絞ってあるので、常時ではなく数日に1度の山になる。
POOL_ARCHIVE_SUFFIX = ".zip"
_POOL_ARCHIVE_STAMP = "%Y%m%d-%H%M%S"
# archive名から時刻と連番を読む。世代の新旧はこれで決める(:func:`_pool_archives`)。
_ARCHIVE_NAME_RE = re.compile(
    rf"-(?P<stamp>\d{{8}}-\d{{6}})(?:-(?P<seq>\d+))?{re.escape(POOL_ARCHIVE_SUFFIX)}$")
# 同じ秒に作れるarchiveの上限。ここに当たるのは何かが暴走しているときなので、黙って
# 名前を再利用せず投げる(:func:`_next_archive_target`)。
MAX_ARCHIVE_SEQ = 99

# 進捗callbackの最短間隔(秒)。呼び出し側はjobの進捗行を更新するので、fileごとに呼ぶと
# 3千回のDB書き込みになる。始点と終点だけは間隔に関わらず必ず報告する。
PROGRESS_INTERVAL_SECONDS = 1.0

# 戻り値と台帳へ載せる失敗の明細の上限。件数(``failed``)は必ず全部数えるが、明細まで
# 全部持つと、backup先のdriveが外れた回に数千件のlistが台帳へ書き込まれる。原因を掴むには
# 先頭の数十件で足り、残りは件数で分かる。
MAX_REPORTED_FAILURES = 50

# 何件**連続**で写せなかったら中断するか。
#
# 散発的な失敗は正常である ―― 録画中のfileは掴まれていることがあり、ウイルス対策softが
# 一瞬handleを持つこともある。そこで止めると、1本のlockのためにbackupが永久に取れない
# という別の壊れ方になる。だから数えるのは**連続**で、1本でも成功したら0へ戻す。
#
# 連続で失敗し続ける原因は実質1つ、書き込み先が丸ごと居なくなったこと(外付けHDDがbusから
# 落ちる。この repo で実際に起きている失敗の型で、``Recorder._move_session_dir`` に記録が
# ある)。20 は、正当に連続し得る最大 ―― 録画中の1つのsession dirが同時に掴んでいるfile
# (書き込み中のsegmentと再生list)は多くて数本 ―― に対して一桁の余裕を置いた値である。
# 中断しないと木の3,481 fileを全部舐め、運用logには原因を1つも指さない
# 「失敗3,481件」だけが残る。
MAX_CONSECUTIVE_FAILURES = 20

# 書き込めることを確かめるためだけに作って消すfile。名前を持つのは、万一消し損ねたときに
# 何者か分かるようにするため(0 byteなので容量は問題にならない)。
WRITE_PROBE_NAME = ".writable"


# ---- 設定と場所 --------------------------------------------------------------------

def is_configured() -> bool:
    """定期backupを走らせてよいか(写す先が設定され、かつ有効)。

    2つの条件を1つの関数に畳むのは、呼ぶ側(startupのschedule)がどちらか片方だけを見て
    「設定はあるのに無効」を走らせる形を作らないためである。写す先が無いのに有効、有効
    なのに写す先が無い、のどちらも「走らない」で同じ意味しか持たない。"""
    return bool(config.record_backup_dir_from_db(config.get_db_path())) and \
        config.get_record_backup_enabled()


def source_root() -> Path:
    """写す元 = 一次保存先(work root)。

    ``layout.work_root()`` を通す。serverは起動時に自分が解決した RECORD_DIR を渡して
    いるので、ここで設定を引き直すと server と別の場所を見る余地が生まれる。"""
    return Path(layout.work_root())


def backup_root() -> Path:
    """写す先(``<record_backup_dir>/_primary_backup``)。未設定なら投げる。"""
    configured = config.record_backup_dir_from_db(config.get_db_path())
    if not configured:
        raise PrimaryBackupError("一次保存のbackup先が設定されていません")
    return Path(configured).resolve() / PRIMARY_BACKUP_DIRNAME


def _tree_root(root: Path) -> Path:
    return root / TREE_DIRNAME


def _pool_root(root: Path) -> Path:
    return root / POOL_ARCHIVE_DIRNAME


def _ledger_path(root: Path) -> Path:
    return root / LEDGER_NAME


def _check_roots(src: Path, dest: Path) -> None:
    """写す元と写す先が入れ子になっていないか。

    backup先を一次保存先の中へ設定すると、写した物を次の走査が拾って写す、を繰り返して
    diskを食い潰す。逆(一次保存先がbackup先の中)も、削除の伝播が一次保存先のfileを
    消し得るので許さない。"""
    if src == dest or src in dest.parents or dest in src.parents:
        raise PrimaryBackupError(
            f"一次保存先とbackup先が入れ子になっています（一次 {src} / backup {dest}）")


# ---- 写す先の同一性 ----------------------------------------------------------------

def _root_id_path(root: Path) -> Path:
    return root / ROOT_ID_NAME


def _read_root_id(root: Path):
    """backup先に置いた識別子。無ければ None。読めるが空・壊れている物は「無い」と同じ。"""
    try:
        text = _root_id_path(root).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise PrimaryBackupError(f"backup先の識別子 {_root_id_path(root)} を読めません: {exc}") from exc
    return text or None


def _verify_root_identity(root: Path, expected) -> dict:
    """backup先が**前回と同じdrive**かを、書き始める前に確かめる。

    外付けdriveのletterは、差す順序やhubの構成で入れ替わる。``K:\Backup`` に別のdriveが
    見えている状態でそのまま走ると、台帳が無いので「初回」として一次保存先の31GBを丸ごと
    写し始める ―― 本物の控えは古いまま置き去りで、しかも運用logには「完了」と出る。
    driveが外れている場合は :func:`_require_destination_available` が捕まえるが、**別の
    driveが同じ場所に居る**場合は親folderが在るので素通りする。それをここで止める。

    識別子は2箇所に持つ: backup先の :data:`ROOT_ID_NAME` と、呼ぶ側がDBへ控える値
    (``expected``)。判定は次の3通りだけである。

    * ``expected`` が None(このbackup先を初めて使う・設定を変えた直後)なら、在る識別子を
      採用し、無ければ作って書く。DBを古いsnapshotへ戻した直後もここに入り、その時は
      backup先の識別子をそのまま採用する ―― 控え側が正で、DB側は控えを写しただけ。
    * 一致すれば通る。
    * **無い・違うなら1byteも書かずに断る。** 同じpathに見えている物が、これまで写して
      きたdriveではない。driveを差し直してletterが戻れば次の周期で一致する。本当に別の
      driveへ替えたなら、設定の保存先を別のfolder名に変える(DB側の控えは保存先の文字列と
      組で持つので、値が変われば None から始まる)か、古いdriveの識別子fileを写す。
    """
    found = _read_root_id(root)
    if expected is None:
        if found is not None:
            return {"root_id": found, "adopted": True}
        token = secrets.token_hex(16)
        path = _root_id_path(root)
        partial = path.with_name(path.name + PARTIAL_SUFFIX)
        try:
            partial.write_text(token + "\n", encoding="utf-8")
            os.replace(partial, path)
        except OSError as exc:
            raise PrimaryBackupError(f"backup先の識別子 {path} を書けません: {exc}") from exc
        logger.info(
            "一次保存のbackup先 %s に識別子を置きました", root,
            extra={"event": "record_backup.root_adopted",
                   "ctx": {"dest": str(root), "root_id": token}},
        )
        return {"root_id": token, "adopted": True}
    if found is None:
        raise PrimaryBackupError(
            f"backup先 {root} に識別子（{ROOT_ID_NAME}）がありません。"
            "これまで写してきたdriveとは別のdriveが同じ場所に見えている可能性があります"
            "（driveのletterが入れ替わっていないか確認してください。別のdriveへ替えたのなら"
            "設定の保存先を別のfolder名に変えるか、古いdriveの識別子fileを写してください）")
    if found != expected:
        raise PrimaryBackupError(
            f"backup先 {root} の識別子が控えと一致しません（backup先 {found[:8]}… / 控え "
            f"{expected[:8]}…）。これまで写してきたdriveとは別のdriveです"
            "（driveのletterが入れ替わっていないか確認してください。別のdriveへ替えたのなら"
            "設定の保存先を別のfolder名に変えるか、古いdriveの識別子fileを写してください）")
    return {"root_id": found, "adopted": False}


# ---- 台帳 --------------------------------------------------------------------------

def _load_ledger(root: Path) -> dict:
    """台帳を読む。無い・壊れているときは空の台帳を返す。

    台帳が読めなくても復旧はできる ―― 差分の判定は写した先のstatで行うので、台帳が持つ
    のは「消えたと最初に気付いた日時」と「archiveの世代」だけである。読めない台帳で
    backupごと止めると、消えたfileの猶予を守るためにbackupが1本も取れなくなる。
    日時が失われた場合は次の走査で今の時刻から数え直しになるが、それは猶予が**延びる**
    方向で、消し過ぎる側には倒れない。"""
    path = _ledger_path(root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"version": LEDGER_VERSION, "deleted": {}, "pools": {}, "last_run": None}
    except (OSError, ValueError):
        logger.warning(
            "一次保存backupの台帳 %s を読めないため、空の台帳から始めます", path,
            extra={"event": "record_backup.ledger_unreadable", "ctx": {"path": str(path)}},
            exc_info=True,
        )
        return {"version": LEDGER_VERSION, "deleted": {}, "pools": {}, "last_run": None}
    if not isinstance(data, dict):
        return {"version": LEDGER_VERSION, "deleted": {}, "pools": {}, "last_run": None}
    data.setdefault("version", LEDGER_VERSION)
    data.setdefault("deleted", {})
    data.setdefault("pools", {})
    data.setdefault("last_run", None)
    return data


def _save_ledger(root: Path, ledger: dict) -> None:
    """台帳を書く。書きかけを最終名に見せないよう一時名からrenameする。"""
    path = _ledger_path(root)
    partial = path.with_name(path.name + PARTIAL_SUFFIX)
    try:
        partial.write_text(json.dumps(ledger, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(partial, path)
    except OSError:
        logger.warning(
            "一次保存backupの台帳 %s を書けませんでした", path,
            extra={"event": "record_backup.ledger_write_failed", "ctx": {"path": str(path)}},
            exc_info=True,
        )


def last_run() -> dict | None:
    """前回の実行結果。まだ1度も走っていない・写す先が未設定なら None。"""
    if not config.record_backup_dir_from_db(config.get_db_path()):
        return None
    try:
        root = backup_root()
    except PrimaryBackupError:
        return None
    return _load_ledger(root).get("last_run")


# ---- 走査 --------------------------------------------------------------------------

def _normalize_exclusions(rels, src: Path) -> frozenset:
    """除外するpathを走査の相対path(``/`` 区切り)へ揃える。

    **空の項目は落とす。** 1つでも残ると root 自身に一致し、一次保存先が丸ごと控えから
    落ちる ―― しかも結果は「写した件数0」で、差分が無かった正常な回と見分けが付かない。

    絶対pathも受け取る(呼ぶ側はDBの録画pathを持っている)。一次保存先の外を指す絶対pathは
    **投げる** ―― 黙って一致しないままにすると、除外したつもりの録画が普通に写される。
    除外は「書き込み中のfileを写さない」ための仕組みなので、効いていないことに気付けない
    形がいちばん悪い。実在しない相対pathは投げない(消えた録画を指したまま呼ばれるのは
    正常で、単に一致しないだけである)。"""
    found: set = set()
    for raw in rels or ():
        candidate = Path(raw)
        if candidate.is_absolute():
            try:
                candidate = candidate.resolve().relative_to(src.resolve())
            except (OSError, ValueError):
                raise PrimaryBackupError(
                    f"除外に一次保存先の外のpathが渡されました: {raw}") from None
            text = candidate.as_posix()
        else:
            text = str(raw).replace("\\", "/")
        text = text.strip().strip("/")
        if text and text != ".":
            found.add(text)
    return frozenset(found)


def _matched_exclusion(rel: str, excluded):
    """``rel`` を覆っている除外のpath。覆われていなければ None。

    除外は**拡張子を持たない接頭辞**として渡される(:func:`run_backup`)。1つのstemからは
    ``<stem>.mp4`` ``<stem>.overlay.mp4`` ``<stem>.up.mp4`` ``<stem>.waveform.json`` … と
    派生が出て、しかも走っている最中にも増えるので、呼ぶ側が全部を列挙することはできない。

    したがって境目は ``/`` と ``.`` の**2つ**である。``/`` だけを見ていた頃は
    ``alice/mp4/00001_x`` が ``alice/mp4/00001_x.mp4`` に一致せず、**進行中の録画のmp4と
    sidecarが素通りで写っていた**(確定の瞬間に書かれかけのmp4を掴む)。

    ``.`` が ``/`` と同じく安全な境目なのは、stemの直後に来る文字が区切りに限られるから
    である ―― ``00001_x.`` は ``00001_x2.mp4`` に一致しない。接頭辞の一致だけで済ませると
    別の録画を巻き込む。

    どの除外に当たったかを返すのは、呼ぶ側へ「実際に何を写さなかったか」を名乗るためである
    (存在の有無を後から測り直すと、拡張子を持たない接頭辞は ``exists()`` が偽になる)。"""
    for one in excluded:
        if rel == one or rel.startswith(one + "/") or rel.startswith(one + "."):
            return one
    return None


def _is_excluded(rel: str, excluded) -> bool:
    """``rel`` が除外の下に在るか。判定は :func:`_matched_exclusion` に一本化する ――
    走査の刈り込みと削除の伝播が別々の照合を持つと、片方だけが漏れる。"""
    return _matched_exclusion(rel, excluded) is not None


def _iter_tree(root: Path, skip_top_level=(), exclude=frozenset(), hits=None):
    """``root`` 配下のfileを ``(相対path, size, mtime)`` で1件ずつ返す。

    走査は ``scandir`` で行う(``tictok.api.files._dir_usage`` と同じ理由)。session dirは
    束ね前で数千のsegmentを抱えるため、rglob+statのようにfileごとのstatを起こすと
    同じ答えに3倍の呼び出しを払う。DirEntryのstatはWindowsでは一覧の時点で得た値を
    そのまま使う。

    **listではなくgeneratorで返す。** avatars poolは実測73万fileあり、tupleのlistとして
    抱えるだけで百MB規模になる。走査結果を全部持つ必要があるのは差分の計画
    (:func:`_plan`)だけで、poolの集計もarchiveの作成もその場で畳める。

    相対pathは ``/`` 区切りの文字列で返す。台帳へ載る値であり、backup先を別のOSから
    読む可能性がある以上、区切りをOSに依存させない。

    ``exclude`` に覆われた名前は返さない。判定は :func:`_matched_exclusion` で、``/`` と
    ``.`` の両方を境目に見る ―― ここを ``rel in exclude`` の完全一致で済ませていた頃は、
    除外に ``<配信者>/mp4/<stem>`` を渡しても ``<stem>.mp4`` は名前が違うので素通りし、
    **書き込み中のmp4がそのまま控えへ写っていた**。

    directoryに一致したときは**stackへ積まない**ので、その下は歩きもしない ―― 除外の主な
    用途が録画中のsession dir(束ね前で実測11,285 entries)である以上、一致してから捨てるのでは
    費用を払ってしまう。

    ``hits`` を渡すと、実際に何かを覆った除外のpathがそこへ入る。「控えが増えない理由」を
    呼ぶ側へ返すためで、後から ``exists()`` で測り直すことはできない(除外は拡張子を持たない
    接頭辞なので、それ自体はfileとして実在しない)。"""
    stack: list = [(root, "")]
    while stack:
        here, prefix = stack.pop()
        try:
            entries = list(os.scandir(here))
        except OSError:
            # 走査中に消えた・読めないdirectory。写せないものは数えないだけでよく、
            # backup全体を失敗にする理由にはならない。
            logger.debug(
                "一次保存backupの走査で %s を読めませんでした", here, exc_info=True,
                extra={"event": "record_backup.scan_failed", "ctx": {"path": str(here)}},
            )
            continue
        for entry in entries:
            if not prefix and entry.name in skip_top_level:
                continue
            rel = f"{prefix}{entry.name}"
            matched = _matched_exclusion(rel, exclude) if exclude else None
            if matched is not None:
                if hits is not None:
                    hits.add(matched)
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    stack.append((Path(entry.path), f"{rel}/"))
                    continue
                info = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            yield rel, info.st_size, info.st_mtime


def _pool_dir_mtimes(pool: Path, relatives) -> dict:
    """**安い指紋**: 覚えておいたdirectoryのmtimeだけを読む。fileには一切触らない。

    NTFSのdirectoryのmtimeは、そのdirectoryへのentryの**追加と削除**で動く。実測で
    確かめた(2026-09-02, NTFS):

        fileを1本足す        → directoryのmtime 変化する
        既存fileを書き換える  → directoryのmtime 変化しない（fileのmtimeだけが動く）
        fileを1本消す        → directoryのmtime 変化する

    ``relatives`` は前回の全走査で見つけたdirectoryの相対path。実在するpoolのdirectoryは
    実測で5個(avatars / avatars/by-id / avatars/commenter / emotes / gift_icons)しかない。
    avatars単体なら3個で**実測89.2マイクロ秒**、3つのpool合わせた5個でも115マイクロ秒である。
    avatarsの全走査(実測1.898秒)の**21,285分の1**にあたる。

    読めなかったdirectoryは ``None`` を入れる。項目ごと落とすと、消えたdirectoryと
    「前回も見ていないdirectory」が同じ形になり、比較が通ってしまう。"""
    found: dict = {}
    for rel in relatives:
        target = pool / rel if rel else pool
        try:
            found[rel] = os.stat(target).st_mtime
        except OSError:
            found[rel] = None
    return found


def _walk_pool(pool: Path) -> dict:
    """**高い指紋**: poolを全走査して ``{files, bytes, mtime, dirs}`` を返す。

    件数・合計byte・最新mtimeの3点で素材を数えるのは、この codebase が既に
    ``tictok.media.hls_source.fingerprint`` で使っている形に揃えたものである。1点では
    足りない ―― 件数だけでは同じ名前のまま中身が入れ替わるavatarの更新
    (``AvatarPool.needs_update`` は解像度が上がった時と別avatarに変わった時にTrueを返す)を
    映さず、合計byteだけでは同sizeの入れ替えを取りこぼす。

    ``_iter_tree`` を使わず自前で歩くのは、**directoryそのものの一覧**が要るためである
    (安い指紋がその一覧をstatする)。``_iter_tree`` は意図的にfileしか返さない。

    ``dirs`` は ``{相対path: mtime}`` で、mtimeは**そのdirectoryを一覧する直前**に読む。
    後からまとめて読んではいけない ―― 歩いている最中にavatarが1件足されると、後から読んだ
    mtimeは「その追加も見た」姿になり、次回の安い指紋がそこで一致して、実際には数え損ねた
    追加を永久に見落とす。先に読んでおけば、その回のmtimeは古い側に倒れ、次回は必ず歩き直す。
    """
    files = 0
    total = 0
    newest = 0.0
    dirs: dict = {}
    stack: list = [(pool, "")]
    while stack:
        here, prefix = stack.pop()
        try:
            dirs[prefix.rstrip("/")] = os.stat(here).st_mtime
            entries = list(os.scandir(here))
        except OSError:
            continue
        for entry in entries:
            rel = f"{prefix}{entry.name}"
            try:
                if entry.is_dir(follow_symlinks=False):
                    stack.append((Path(entry.path), f"{rel}/"))
                    continue
                info = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            files += 1
            total += info.st_size
            newest = max(newest, info.st_mtime)
    return {"files": files, "bytes": total, "mtime": newest, "dirs": dirs}


def _up_to_date(src_size: int, src_mtime: float, dst: Path) -> bool:
    """写した先が元と同じか(size一致 かつ mtimeが :data:`MTIME_TOLERANCE_SECONDS` 以内)。

    判定を写した先の実fileで行うのがこの関数の主旨である(module docstring)。"""
    try:
        info = dst.stat()
    except OSError:
        return False
    return info.st_size == src_size and \
        abs(info.st_mtime - src_mtime) <= MTIME_TOLERANCE_SECONDS


def _plan(src: Path, dest_tree: Path, excluded=frozenset(), hits=None) -> dict:
    """写す物・既に同じ物・写した先にしか無い物を数える(何も書かない)。

    実行前に全部数え切るのは、空き容量を「始める前に」判定するためである
    (:func:`_require_free_space`)。途中で溢れると、backup先には最後まで写らなかった木が
    残り、しかも次の走査はその中途半端な木を「写し済み」と読む。

    ``excluded`` の下は歩かないので ``source_rels`` にも入らない。**その結果を
    「消えた」と読ませてはいけない**ので、削除の伝播にも同じ集合を渡すこと
    (:func:`_propagate_deletions`)。"""
    to_copy: list = []
    copy_bytes = 0
    skipped = 0
    skipped_bytes = 0
    source_rels: set = set()
    for rel, size, mtime in _iter_tree(
            src, EXCLUDED_TOP_LEVEL + POOL_DIRNAMES, excluded, hits):
        source_rels.add(rel)
        if _up_to_date(size, mtime, dest_tree / rel):
            skipped += 1
            skipped_bytes += size
            continue
        to_copy.append((rel, size))
        copy_bytes += size
    return {"to_copy": to_copy, "copy_bytes": copy_bytes,
            "skipped": skipped, "skipped_bytes": skipped_bytes,
            "source_rels": source_rels}


def _require_destination_available(parent: Path, root: Path) -> None:
    """backup先が**今この瞬間**に在って書けるか。駄目なら1byteも書かずに断る。

    ``tictok.api.disk._unavailable_final_dirs`` と同じ判定の流儀で、外付けHDDがbusから
    落ちた状態を始める前に捕まえる。

    **設定された親folderは自分で作らない。** 作ってしまうと、driveごと見えなくなった状態で
    systemのdriveに同じ名前の空folderが生まれ、そこへ31GBを写し始める ―― 本物の控えは古い
    まま置き去りになり、しかも画面上は「backupは成功した」と見える。在るべき物が在ることの
    確認であって、作ることではない。作ってよいのはその下の ``_primary_backup/`` だけである。

    実在の確認だけでは足りないので、実際に1 file書いて消す。I/O errorのあとNTFSがread-only
    へ落ちたdriveは ``is_dir()`` を通り、書き込みだけが失敗する ―― その場合に4分かけて
    archiveを作ってから気付くのでは、確かめた意味が無い。"""
    if not parent.is_dir():
        raise PrimaryBackupError(
            f"backup先 {parent} が見つかりません（driveが外れている可能性があります）")
    probe = root / WRITE_PROBE_NAME
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as exc:
        raise PrimaryBackupError(f"backup先 {root} へ書き込めません: {exc}") from exc


def _require_free_space(dest: Path, needed: int) -> dict:
    """写す前にbackup先の空きを確かめる。足りなければ**始めない**。

    dbmaint の ``_ensure_free_space`` と同じ形で、足りなければ例外を投げて1byteも書かない。
    途中で溢れると、写し終えたつもりのfileが尻切れで残る ―― 尻切れのmp4は再生できるので、
    戻したときに初めて壊れていると分かる形になる。"""
    required = int(needed * FREE_SPACE_MARGIN)
    try:
        free = shutil.disk_usage(str(dest)).free
    except OSError as exc:
        raise PrimaryBackupError(f"backup先 {dest} の空き容量を読み取れません: {exc}") from exc
    if free < required:
        raise PrimaryBackupError(
            f"backup先の空き容量が不足しています: 必要 {required:,} bytes"
            f"（写す量 {needed:,} × {FREE_SPACE_MARGIN}）/ 空き {free:,} bytes（{dest}）"
        )
    return {"needed_bytes": needed, "required_bytes": required, "free_bytes": free}


# ---- copy --------------------------------------------------------------------------

def _copy_one(src: Path, dst: Path) -> None:
    """1本を一時名へ写してからrenameする。

    途中でserverが落ちても、最終名に現れるのは写し終えた物だけである。次回はその
    一時名を消してから写し直す ―― 一時名の中身がどこまで進んでいたかは分からないので、
    続きから足すことはしない(size+mtimeで判定する以上、途中まで写った物を「途中まで」
    と識別する手段が無い)。"""
    partial = dst.with_name(dst.name + PARTIAL_SUFFIX)
    dst.parent.mkdir(parents=True, exist_ok=True)
    partial.unlink(missing_ok=True)
    # copy2はmtimeを保つ。保たないと、写した先のmtimeが常に「写した時刻」になり、
    # 次回の判定が全fileを「変わった」と読む。
    shutil.copy2(str(src), str(partial))
    os.replace(partial, dst)


def _sweep_partials(*roots: Path) -> int:
    """写した先に残った書きかけを掃く。

    落ちた回の残骸で、中身がどこまで進んでいたかは分からない。削除の伝播の対象に混ざると
    「一次保存に無いfile」として数えられてしまうので、走査より先に消す。

    poolのarchiveの書きかけも同じ場所で掃く。1本1GB規模になるうえ、archiveを作り直す
    条件(件数差)を満たさない限り誰も上書きしないので、掃く場所を分けると残り続ける。"""
    removed = 0
    for root in roots:
        for rel, _size, _mtime in _iter_tree(root):
            if not rel.endswith(PARTIAL_SUFFIX):
                continue
            try:
                (root / rel).unlink()
            except OSError:
                continue
            removed += 1
    return removed


# ---- 削除の伝播 --------------------------------------------------------------------

def _propagate_deletions(dest_tree: Path, source_rels: set, deleted: dict,
                         keep_days: int, now: float, excluded=frozenset()) -> dict:
    """一次保存先から消えたfileを台帳へ記録し、猶予を過ぎた物だけ消す。

    ``keep_days`` が0なら記録するだけで消さない(既定)。0を「無効」に割り当てるのは
    ``get_db_backup_keep`` と同じ規約である。記録だけは0でも続ける ―― 後から日数を設定
    したときに、その時点から数え直すのではなく、実際に消えた日から数えられる。

    **``excluded`` の下は1件も触らない。** 除外は「まだ見ていない」であって「消えた」では
    ない。同じ集合を :func:`_plan` にも渡してある以上、除外した録画のfileは ``source_rels``
    に入っていない ―― ここで区別しなければ、一次保存先に**実在するfile**の控えへ削除の印が
    付き、猶予が過ぎれば消される。控えを取る操作が控えを壊す形なので、印を付けないだけでなく
    既に付いている印も動かさない(進行中の録画は次の回に正しく数え直される)。

    戻り値は ``{"marked": n, "restored": n, "deleted": n, "deleted_bytes": n}``。
    ``restored`` は一度消えたfileが一次保存先へ戻ってきた件数で、そのときは台帳から
    落とす(戻したfileが猶予切れで消されるのを防ぐ)。"""
    marked = restored = removed = 0
    freed = 0
    keep_seconds = keep_days * 86400
    present: set = set()
    for rel, size, _mtime in _iter_tree(dest_tree, (), excluded):
        if rel.endswith(PARTIAL_SUFFIX):
            # このrunのcopyが失敗して残した書きかけ。次のrunが掃くので、消えたfileとして
            # 数えない(数えると台帳が実在しない一次保存先のpathを覚え続ける)。
            continue
        present.add(rel)
        if rel in source_rels:
            continue
        first_seen = deleted.get(rel)
        if first_seen is None:
            deleted[rel] = now
            marked += 1
            continue
        if keep_seconds <= 0 or now - float(first_seen) < keep_seconds:
            continue
        try:
            (dest_tree / rel).unlink()
        except OSError:
            logger.warning(
                "猶予を過ぎたbackup先のfile %s を削除できませんでした", rel,
                extra={"event": "record_backup.delete_failed",
                       "ctx": {"path": str(dest_tree / rel)}},
                exc_info=True,
            )
            continue
        deleted.pop(rel, None)
        removed += 1
        freed += size
    for rel in [rel for rel in deleted
                if not _is_excluded(rel, excluded)
                and (rel in source_rels or rel not in present)]:
        # 一次保存先へ戻ってきた物と、既にbackup先から消えている物。どちらも台帳に
        # 「消えた日」を持ち続ける意味が無い。持ち続けると台帳が単調増加する。
        # 除外の下は触らない —— 歩いていないので ``present`` に居らず、ここを素通りさせると
        # 「backup先から消えた」と読んで印を落とし、猶予の起点が黙って今日へ動く。
        deleted.pop(rel, None)
        restored += 1
    return {"marked": marked, "restored": restored,
            "deleted": removed, "deleted_bytes": freed}


# ---- pool archive ------------------------------------------------------------------

def _archive_generation(path: Path):
    """archive名から ``(時刻, 連番)``。規約に合わない名前なら None。

    連番なしを1として読む。新旧の比較(:func:`_pool_archives`)と、次の名前を決める側
    (:func:`_next_archive_target`)が**同じ読み方**をしていることがこの機能の要で、
    片方だけが文字列で見ると刈り取りが新しい世代を消す。"""
    matched = _ARCHIVE_NAME_RE.search(path.name)
    if matched is None:
        return None
    return matched.group("stamp"), int(matched.group("seq") or 1)


def _pool_archives(pool_dir: Path, name: str) -> list:
    """そのpoolのarchiveを新しい順に返す。

    **名前の文字列順では並べない。** 同じ秒に2本作ると連番が付く(:func:`_next_archive_target`)
    が、``avatars-20260902-162706-2.zip`` は ``avatars-20260902-162706.zip`` より文字列では
    小さい('-' < '.')。文字列順に頼ると後から作った方が古い側に回り、刈り取りが**新しい
    世代を消す**。時刻と連番を数として読む。

    名前の規約に合わないfileは返さない。読めない名前を世代として数えると、それが刈り取りの
    対象になる ―― 人が別の目的で置いたfileかもしれないものを、この機能が消してよい理由は無い。
    """
    if not pool_dir.is_dir():
        return []
    found: list = []
    for path in pool_dir.glob(f"{name}-*{POOL_ARCHIVE_SUFFIX}"):
        generation = _archive_generation(path)
        if generation is None:
            continue
        found.append((generation, path))
    return [path for _key, path in sorted(found, key=lambda item: item[0], reverse=True)]


def _plan_pool(pool: Path, name: str, record, pool_dir: Path) -> dict:
    """このpoolのarchiveを作り直すかを、**2段の指紋**で決める。

    段を分けるのは、判定そのものが費用になるからである。素朴に毎回全走査すると、73万
    fileを数えるためだけにbackupのたび1.898秒を払う。段を分けると、何も足されていない回は
    **89.2マイクロ秒**で「作り直し不要」に至る。

      1段目（安い / avatarsで実測89.2マイクロ秒）: 覚えておいたdirectoryのmtime
         (:func:`_pool_dir_mtimes`)。前回**歩いた時**と1つも動いていなければ、file の
         追加も削除も起きていないので全走査を省く。
      2段目（高い / avatarsで実測1.898秒）: 1段目が動いていたときだけ全走査し、件数・
         合計byte・最新mtimeを採る(:func:`_walk_pool`)。閾値と比べて作り直しを決める。

    **1段目だけでは判定材料にならない。** directoryのmtimeはentryの追加・削除しか映さず、
    同じ名前のまま中身が入れ替わるavatarの更新を素通りさせる(実測で確認、
    :func:`_pool_dir_mtimes`)。だから1段目は「全走査を省いてよいか」だけを決め、作り直すか
    は必ず2段目の数字で決める。この構成で取りこぼすのは「1 fileも足されず、既存fileの
    中身だけが入れ替わった回」で、その差分は次にavatarが1人でも増えた回(=次の配信)の
    2段目で拾われる。

    ``record`` が無い・archiveの実体が無いときは指紋を見るまでもなく作り直す。実体が
    消えていれば控えが無いということで、判定の余地は無い。

    戻り値 ``{"reason", "fingerprint", "scanned", "files", "bytes"}``。``reason`` が空文字
    なら作り直さない。``scanned`` は2段目まで走ったか(``False`` なら件数は前回の値)。"""
    archives = _pool_archives(pool_dir, name)
    if not record or not archives:
        fingerprint = _walk_pool(pool)
        return {"reason": "初回", "fingerprint": fingerprint, "scanned": True,
                "files": fingerprint["files"], "bytes": fingerprint["bytes"]}

    seen = record.get("seen_dirs") or {}
    if seen and _pool_dir_mtimes(pool, seen.keys()) == seen:
        # directoryが1つも動いていない = 前回歩いた時から追加も削除も無い。
        return {"reason": "", "fingerprint": None, "scanned": False,
                "files": record.get("files"), "bytes": record.get("bytes")}

    fingerprint = _walk_pool(pool)
    last_files = int(record.get("files") or 0)
    last_bytes = int(record.get("bytes") or 0)
    files = fingerprint["files"]
    total = fingerprint["bytes"]
    reason = ""
    if abs(files - last_files) >= POOL_REBUILD_FILE_DELTA:
        reason = f"件数差 {files - last_files:+d}（閾値 {POOL_REBUILD_FILE_DELTA}）"
    elif last_bytes and abs(total - last_bytes) >= last_bytes * POOL_REBUILD_BYTES_RATIO:
        reason = f"bytes差 {total - last_bytes:+d}（閾値 {POOL_REBUILD_BYTES_RATIO:.0%}）"
    return {"reason": reason, "fingerprint": fingerprint, "scanned": True,
            "files": files, "bytes": total}


def _next_archive_target(dest_dir: Path, name: str, now: float) -> Path:
    """次の世代のarchive名。

    stampは秒までなので、同じ秒に2回作り直すと名前が衝突する。衝突した名前へ書くと、
    **健全性を確かめる前に1つ前の世代を上書きする** ―― 新しい方が壊れていた場合、
    世代を残しておいた意味がその瞬間に消える。だから連番を足して必ず別のfileにする。

    **「空いている名前」を拾ってはならない。** 刈り取り(:func:`_prune_pool_archives`)は
    古い世代を消すので、同じ秒の中で連番の**若い**名前が後から空く。そこを埋めると、いま
    書いた最新のarchiveが最も古い名前を名乗ることになり、直後の刈り取りがそれを最古と見なして
    消す —— 出来たばかりの控えが、作った操作自身に即座に消される。健全性を確かめた意味も
    そこで消える(確かめた物が残らないのだから)。

    だから採るのは**既存のどれよりも必ず後の連番**(max+1)。並べる側(:func:`_pool_archives`)が
    時刻と連番を数値で比べるのと対になっている。``tictok.core.dbmaint._next_target`` が同じ形を
    しているが、命名規則が別物(pool名/理由)なので共通化はしない。"""
    stamp = time.strftime(_POOL_ARCHIVE_STAMP, time.localtime(now))
    used = 0
    for path in _pool_archives(dest_dir, name):
        generation = _archive_generation(path)
        if generation is not None and generation[0] == stamp:
            used = max(used, generation[1])
    seq = used + 1
    if seq > MAX_ARCHIVE_SEQ:
        raise PrimaryBackupError(f"同じ時刻のarchive名が使い切られています: {dest_dir}")
    suffix = "" if seq == 1 else f"-{seq}"
    return dest_dir / f"{name}-{stamp}{suffix}{POOL_ARCHIVE_SUFFIX}"


def _build_pool_archive(src_pool: Path, dest_dir: Path, name: str, now: float) -> tuple:
    """poolを1本のzip(無圧縮)へ固める。``(archiveのpath, 入れた件数)`` を返す。

    件数を返すのは :func:`_verify_pool_archive` が突き合わせるためである。走査から追加
    までの間に消えたfileは飛ばすので、入れた件数は指紋の件数と一致するとは限らない。
    健全性の判定に使ってよいのは「**実際に入れた**件数」だけである。

    一時名で作り、閉じ切ってからrenameする。

    最終名で現れるのは、中央目録まで書き終えたarchiveだけである。zipは目録が末尾に付いて
    初めて読めるので、途中で落ちたfileが最終名に居ると「在るのに開けないarchive」になる。

    ``ZipFile`` へdirectoryごと渡さずfileを1件ずつ足すのは、取り消しを受け取れるように
    するためである(73万件の追加は実測4分23秒かかり、その間まったく止まらないのは困る)。

    中身のpathは ``<pool名>/<相対path>`` で始める。展開すると一次保存先の直下へそのまま
    戻せる形にしておく ―― 復旧する人がどこへ展開するかを考えずに済む。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = _next_archive_target(dest_dir, name, now)
    partial = final.with_name(final.name + PARTIAL_SUFFIX)
    partial.unlink(missing_ok=True)
    written = 0
    with zipfile.ZipFile(str(partial), "w", compression=zipfile.ZIP_STORED,
                         allowZip64=True) as archive:
        for rel, _size, _mtime in _iter_tree(src_pool):
            cancel.check_cancelled()
            try:
                archive.write(str(src_pool / rel), arcname=f"{name}/{rel}")
            except OSError:
                # 走査から追加までの間に消えたfile。poolは追記されるだけの塊なので、
                # 1件欠けてもarchive自体は使える。
                continue
            written += 1
    os.replace(partial, final)
    return final, written


def _verify_pool_archive(path: Path, expected: int) -> str:
    """作ったarchiveが読めるかを確かめる。健全なら空文字、駄目なら理由。

    **古い世代を消す前に必ず通す。** 壊れたarchiveで健全な世代を置き換えることは、この
    機能が防ごうとしている状態(控えがあるのに戻せない)そのものを、控えを取る操作自身が
    作ることになる。書き終えたつもりのfileが実は途中で切れている、はdiskが埋まった回に
    普通に起きる。

    見るのは中央目録から読める件数で、書いた件数と一致することを要求する。zipは目録が
    末尾に付いて初めて読めるので、**書き切れなかったarchiveはここで必ず落ちる**。

    中身のCRCまで検算する ``testzip()`` は使わない。backup先から0.68GBを読み直すことに
    なり、目録の検査で捕まえられる失敗(途中で切れた・目録が壊れた)より先の話 ―― 個々の
    byteの化けは、写した直後ではなく置いておく間に起きる種類の事故である。"""
    try:
        with zipfile.ZipFile(str(path)) as archive:
            found = len(archive.namelist())
    except (OSError, zipfile.BadZipFile) as exc:
        return f"開けません（{exc}）"
    if found != expected:
        return f"件数が合いません（書いた {expected} 件 / 読めた {found} 件）"
    return ""


def _prune_pool_archives(pool_dir: Path, name: str) -> list:
    """古い世代を落とす。消せなくても失敗にはしない(新しい世代は既に出来ている)。"""
    pruned: list = []
    for path in _pool_archives(pool_dir, name)[POOL_KEEP_GENERATIONS:]:
        try:
            path.unlink()
        except OSError:
            logger.warning(
                "古いpool archive %s を削除できませんでした", path,
                extra={"event": "record_backup.prune_failed", "ctx": {"path": str(path)}},
                exc_info=True,
            )
            continue
        pruned.append(path.name)
    return pruned


# ---- 実行 --------------------------------------------------------------------------

class _Progress:
    """進捗callbackの間引き。始点と終点は間隔に関わらず必ず通す。"""

    def __init__(self, on_progress, total: int) -> None:
        self._on_progress = on_progress
        self._total = total
        self._last = 0.0

    def __call__(self, done: int, current, force: bool = False) -> None:
        if self._on_progress is None:
            return
        now = time.monotonic()
        if not force and now - self._last < PROGRESS_INTERVAL_SECONDS:
            return
        self._last = now
        self._on_progress(done, self._total, current)


def _run_backup_blocking(on_progress, exclude_rels, expected_root_id=None) -> dict:
    """1回ぶんのbackup。**blockingなので必ずthreadで回す**(:func:`run_backup`)。

    順序は「写す先の確認 → 同一性の確認 → 走査 → 空きの判定 → 木のcopy → poolのarchive →
    削除の伝播 → 台帳」。削除の伝播をcopyの後に置くのは、copyの途中で落ちた回に「まだ写して
    いないfile」を消えた物として記録しないためである。"""
    started = time.monotonic()
    now = time.time()
    src = source_root()
    if not src.is_dir():
        raise PrimaryBackupError(f"一次保存先が見つかりません: {src}")
    root = backup_root()
    _check_roots(src.resolve(), root)
    _require_destination_available(Path(root).parent, root)
    identity = _verify_root_identity(root, expected_root_id)
    # 除外はrootが決まってから解く(絶対pathを相対へ直すのに一次保存先が要る)。
    excluded = _normalize_exclusions(exclude_rels, src)

    tree = _tree_root(root)
    pools_dir = _pool_root(root)
    try:
        tree.mkdir(parents=True, exist_ok=True)
        pools_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PrimaryBackupError(f"backup先 {root} を作れません: {exc}") from exc

    ledger = _load_ledger(root)
    swept = _sweep_partials(tree, pools_dir)

    cancel.check_cancelled()
    excluded_hits: set = set()
    plan = _plan(src, tree, excluded, excluded_hits)

    # poolは「作り直すか」まで先に決める。archiveぶんの空きも始める前に要るためで、
    # 木を写し終えてからpoolで溢れるのでは、始める前に判定した意味が無い。
    pool_plans: list = []
    pool_bytes = 0
    for name in POOL_DIRNAMES:
        cancel.check_cancelled()
        src_pool = src / name
        if not src_pool.is_dir():
            continue
        record = (ledger.get("pools") or {}).get(name)
        decision = _plan_pool(src_pool, name, record, pools_dir)
        pool_plans.append({"name": name, "files": decision["files"],
                           "bytes": decision["bytes"], "reason": decision["reason"],
                           "scanned": decision["scanned"],
                           "fingerprint": decision["fingerprint"]})
        if decision["reason"]:
            pool_bytes += int(decision["fingerprint"]["bytes"])

    space = _require_free_space(root, plan["copy_bytes"] + pool_bytes)

    total_units = len(plan["to_copy"]) + sum(1 for p in pool_plans if p["reason"])
    progress = _Progress(on_progress, total_units)
    progress(0, None, force=True)

    copied = 0
    copied_bytes = 0
    failures: list = []
    failed = 0
    done = 0
    # 連続して写せなかった回数。1本でも成功したら0へ戻す(:data:`MAX_CONSECUTIVE_FAILURES`)。
    consecutive = 0
    stopped = ""
    for rel, size in plan["to_copy"]:
        cancel.check_cancelled()
        progress(done, rel)
        try:
            _copy_one(src / rel, tree / rel)
        except OSError as exc:
            # 1本の失敗で残りを諦めない(``tictok.api.disk._run_relocation`` と同じ判断)。
            # 写せなかったfileは写した先に現れないので、次回の走査がそのまま拾い直す。
            logger.warning(
                "一次保存backupで %s を写せませんでした", rel,
                extra={"event": "record_backup.copy_failed",
                       "ctx": {"rel": rel, "src": str(src / rel), "dst": str(tree / rel)}},
                exc_info=True,
            )
            failed += 1
            if len(failures) < MAX_REPORTED_FAILURES:
                failures.append({"path": rel, "reason": str(exc)})
            done += 1
            consecutive += 1
            if consecutive >= MAX_CONSECUTIVE_FAILURES:
                stopped = (f"連続で {consecutive} 件写せませんでした"
                           f"（backup先 {root} が外れた可能性があります）")
                logger.warning(
                    "一次保存backupを中断しました: %s", stopped,
                    extra={"event": "record_backup.aborted",
                           "ctx": {"dest": str(root), "consecutive": consecutive,
                                   "copied": copied, "failed": failed,
                                   "remaining": len(plan["to_copy"]) - done}},
                )
                break
            continue
        consecutive = 0
        copied += 1
        copied_bytes += size
        done += 1

    pools: list = []
    for entry in pool_plans:
        name = entry["name"]
        fingerprint = entry.pop("fingerprint")
        if stopped:
            # 写す先が居なくなった疑いがある状態で0.68GBのarchiveを書きに行かない。
            # 台帳も触らない ―― 作れなかったarchiveを作った事にすると、次回は指紋が
            # 一致して作り直しを見送る。
            pools.append({**entry, "archived": False, "archive": None, "seconds": 0.0,
                          "pruned": []})
            continue
        if not entry["reason"]:
            if entry["scanned"]:
                # 歩いたが閾値に届かなかった。**見た姿だけ**を台帳へ書き戻す ―― 次回の
                # 安い指紋がここで一致し、同じ姿をもう一度歩かずに済む。件数の基準
                # (files/bytes)は動かさない。動かすと、少しずつの増加が毎回「前回比ゼロ」
                # になり、閾値に永久に届かなくなる。
                stored = dict((ledger.get("pools") or {}).get(name) or {})
                stored["seen_dirs"] = fingerprint["dirs"]
                ledger.setdefault("pools", {})[name] = stored
            pools.append({**entry, "archived": False, "archive": None, "seconds": 0.0,
                          "pruned": []})
            continue
        cancel.check_cancelled()
        progress(done, f"{name}（archive）")
        pool_started = time.monotonic()
        try:
            archive, written = _build_pool_archive(src / name, pools_dir, name, now)
        except OSError as exc:
            logger.warning(
                "pool %s のarchiveを作れませんでした", name,
                extra={"event": "record_backup.pool_failed", "ctx": {"pool": name}},
                exc_info=True,
            )
            failed += 1
            if len(failures) < MAX_REPORTED_FAILURES:
                failures.append({"path": name, "reason": str(exc)})
            pools.append({**entry, "archived": False, "archive": None,
                          "seconds": time.monotonic() - pool_started, "pruned": []})
            done += 1
            continue
        # 古い世代を消す前に、出来たばかりのarchiveが読めることを確かめる。
        broken = _verify_pool_archive(archive, written)
        if broken:
            # 壊れた物を残すと、次の走査がそれを最新世代と数え、健全な世代を押し出す。
            archive.unlink(missing_ok=True)
            logger.warning(
                "pool %s のarchiveが健全ではないため破棄しました: %s", name, broken,
                extra={"event": "record_backup.pool_unhealthy",
                       "ctx": {"pool": name, "archive": archive.name, "reason": broken,
                               "written": written}},
            )
            failed += 1
            if len(failures) < MAX_REPORTED_FAILURES:
                failures.append({"path": name, "reason": broken})
            pools.append({**entry, "archived": False, "archive": None,
                          "seconds": time.monotonic() - pool_started, "pruned": []})
            done += 1
            continue
        pruned = _prune_pool_archives(pools_dir, name)
        ledger.setdefault("pools", {})[name] = {
            "archive": archive.name, "entries": written,
            "files": fingerprint["files"], "bytes": fingerprint["bytes"],
            "mtime": fingerprint["mtime"], "built_at": now,
            "seen_dirs": fingerprint["dirs"],
        }
        pools.append({**entry, "archived": True, "archive": archive.name,
                      "entries": written,
                      "seconds": time.monotonic() - pool_started, "pruned": pruned})
        done += 1

    # 実際に何かを覆った除外だけを「外した」と名乗る。消えた録画を指したまま呼ばれるのは
    # 正常で、それを件数に混ぜると、控えが増えない理由を読もうとした人が実在しない録画を探す。
    # 判定に ``exists()`` は使えない ―― 除外は拡張子を持たない接頭辞なので、それ自体は
    # fileとして実在しない(``alice/mp4/<stem>`` は在るが ``<stem>.mp4`` という名前で在る)。
    held_back = sorted(excluded_hits)

    if stopped:
        # 削除の伝播は行わない。写す先がまともに読めない状態で「一次保存に無いfile」を
        # 数えると、消えたことにする側へ倒れる。控えを減らす判断は、写す先が健全だと
        # 確かめられた回にだけ行う。
        removal = {"marked": 0, "restored": 0, "deleted": 0, "deleted_bytes": 0}
    else:
        cancel.check_cancelled()
        removal = _propagate_deletions(
            tree, plan["source_rels"], ledger.setdefault("deleted", {}),
            config.get_record_backup_keep_deleted_days(), now, excluded)
    progress(done if stopped else total_units, None, force=True)

    result = {
        "source": str(src),
        "dest": str(root),
        "started_at": now,
        "seconds": time.monotonic() - started,
        "copied": copied,
        "copied_bytes": copied_bytes,
        "skipped": plan["skipped"],
        "skipped_bytes": plan["skipped_bytes"],
        "swept_partials": swept,
        "failed": failed,
        "failures": failures,
        "marked_deleted": removal["marked"],
        "restored": removal["restored"],
        "deleted": removal["deleted"],
        "deleted_bytes": removal["deleted_bytes"],
        "keep_deleted_days": config.get_record_backup_keep_deleted_days(),
        "pools": pools,
        "space": space,
        # 中断した理由。空文字なら最後まで走った。**失敗ではなく「途中で止めた」**として
        # 名乗る ―― 写せなかった件数だけを見せると、原因を1つも指さない記録になる。
        # 次回は書きかけ(.partial)を掃いて続きから進む。
        "stopped": stopped,
        "remaining": len(plan["to_copy"]) - done if stopped else 0,
        # 呼ぶ側が外した物のうち、実際に一次保存先に在って写さなかったもの。控えが
        # 増えない理由が読めるように、件数だけでなくpathも名乗る(進行中の録画は数本)。
        "excluded": len(held_back),
        "excluded_rels": held_back[:MAX_REPORTED_FAILURES],
        # backup先の識別子と、この回で採用した(=呼ぶ側がDBへ控えるべき)か。
        "root_id": identity["root_id"],
        "root_id_adopted": identity["adopted"],
    }
    ledger["last_run"] = result
    _save_ledger(root, ledger)
    if stopped:
        logger.warning(
            "一次保存のbackupを中断しました: %s（写した %d 件 / 残り %d 件 / %.1f秒）",
            stopped, copied, result["remaining"], result["seconds"],
            extra={"event": "record_backup.stopped", "ctx": result},
        )
    else:
        logger.info(
            "一次保存のbackupが完了しました: 写した %d 件（%.2fGB）/ 据え置き %d 件 / "
            "消した %d 件 / 失敗 %d 件（%.1f秒）",
            copied, copied_bytes / 1024 ** 3, plan["skipped"], removal["deleted"],
            failed, result["seconds"],
            extra={"event": "record_backup.completed", "ctx": result},
        )
    return result


async def run_backup(on_progress=None, exclude_rels=(), expected_root_id=None) -> dict:
    """一次保存先を1回ぶんbackup先へ写す。

    ``expected_root_id`` は呼ぶ側がDBへ控えている**backup先の識別子**(初回・保存先を変えた
    直後は None)。写す先の識別子と一致しなければ1byteも写さずに断る
    (:func:`_verify_root_identity`)。戻り値の ``root_id`` / ``root_id_adopted`` で、この回に
    採用した識別子を呼ぶ側へ返す ―― DBへ控えるのは呼ぶ側の仕事で、このmoduleは
    filesystemだけを触る。

    **scheduleは持たない。** いつ走らせるか(録画の確定を合図に静穏時間を置く・下限間隔を
    空ける)は呼ぶ側が決める。この関数は「呼ばれたら1回走る」だけである ―― 走らせる条件が
    module内とschedule側の2箇所に分かれると、片方だけを見て走らない理由を探すことになる。

    ``exclude_rels`` は**写さないpathの集合**(一次保存先からの相対path、または一次保存先の
    下を指す絶対path)。指したpathとその下は、走査からも削除の伝播からも外れる。

    **渡す形は「拡張子を付けない接頭辞」である。** 1つのstemからは ``<stem>.mp4``
    ``<stem>.overlay.mp4`` ``<stem>.up.mp4`` ``<stem>.waveform.json`` … と派生が出て、しかも
    走っている最中にも増えるので、呼ぶ側が全部を列挙することはできない。接頭辞を渡せば
    ``/`` と ``.`` の両方を境目に覆う(:func:`_matched_exclusion`)。

    進行中の録画1本につき渡すのは**3つ**で、置き場が3箇所に分かれているためである
    (:mod:`tictok.core.layout`)::

        <配信者>/ts/<stem>       ... HLSの素材(session dir)
        <配信者>/mp4/<stem>      ... 完成mp4と派生(拡張子を付けない)
        .sidecars/<stem>         ... 時刻map・波形・サムネ。**root直下**で配信者別ではない

    3つのうち1つでも欠けると、その置き場のfileだけが書き込み中のまま控えへ写る。実際に
    ``ts`` しか覆えていなかった時期があり、mp4とsidecarは素通りしていた。

    用途は**進行中の録画**である。監視は複数の配信者に同時に掛かるので、ある録画の確定を
    合図に走らせても他の録画は書き込み中のままであることが多い(実測: 確定録画529本のうち
    156本=29.5%が終了時に他の録画と重なっており、この合図で走った回の65.4%が「他の録画が
    進行中」に当たる)。書き込み中の ``.ts`` を写せば控えには途中の姿が残り、しかも録画中の
    SSDを奪い合う。

    **進行中かどうかをこのmoduleは判断しない。** それはDBを見なければ分からず、ここは
    filesystemだけを触る層である。判断は呼ぶ側が持ち、結果の集合だけを渡す ―― 走らせる
    条件をmodule内とschedule側へ分けない、という上の判断と同じ理由である。

    poolは除外の対象にならない。録画1本には属さない録画横断の塊で、進行中の録画とは別物
    である(:data:`POOL_DIRNAMES`)。

    戻り値の ``stopped`` が空文字でなければ**途中で止めた**という意味で、その理由が入る
    (写す先が居なくなった疑い)。失敗とは別に名乗る ―― 止めた回は残りを次回が続きから
    進めるので、``remaining`` に残件数を返す。書きかけは次回の頭で掃かれる。

    ``on_progress(done, total, current)`` は**worker threadから**呼ばれる同期callback。
    ``total`` は写すfile数とarchiveを作り直すpool数の合計、``current`` は今写している
    相対path(poolのときは ``avatars（archive）``、始点と終点では None)。呼び出しは
    :data:`PROGRESS_INTERVAL_SECONDS` に間引くが、始点と終点は必ず届く。

    処理そのものはfilesystemのみを触るblockingな仕事なので ``to_thread`` で回す。event
    loop上で走らせると、31GBの走査とcopyのあいだserverが丸ごと止まる。"""
    if not is_configured():
        raise PrimaryBackupError("一次保存のbackupが有効ではありません（保存先か有効設定を確認してください）")
    return await asyncio.to_thread(
        _run_backup_blocking, on_progress, exclude_rels, expected_root_id)
