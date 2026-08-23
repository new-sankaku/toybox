"""収集時にdiskへ溜めた画像素材(Userアイコン / Giftアイコン / Emote)を見る口。

素材は録画のためでも解析のためでもなく取ってある訳ではない。焼き込みが後から使うために
「URLが新鮮なうち」に落としたものが結果として貯まったもので(``media/avatar_pool.py`` /
``media/gift_icons.py`` / ``media/emote_pool.py``)、署名付きCDN URLは失効するので二度と
取り直せない。ここはその山を人が探して取り出せるようにするだけの読み取り専用の層である。

3種の一覧の**源が違う**のが、この moduleの形を決めている:

  Giftアイコン / Emote  poolのdirをそのまま数える。1,000件前後・実測0.2秒未満なので、
                        一覧を作るたびに歩いてよい。
  Userアイコン          **users表**が源。file名は ``sha1(unique_id or nickname)`` で、
                        disk側には人へ戻す情報が無い。diskを源にすると40桁hexが22万件
                        並ぶだけの画面になる。DB駆動にすると「まだcacheが無いuser」も
                        行として出るので、それは ``cached: false`` で名乗る(落とすと
                        pageの継ぎ目がずれ、総数も嘘になる)。

**件数と容量(summary)はDBのsnapshotを返し、pageを開いても走査しない。** avatarのpoolは
実測662,315 entryで1回1.2〜2.5秒かかり、pageを開くたびに払ってよい費用ではない。
再走査は ``POST /api/assets/rescan`` という明示操作だけが起こす —— 容量内訳
(``routes/storage.py`` と ``storage_scan`` 表)が同じ問題を同じ形で解いており、そこへ揃えた。
まだ走査していない種別は0件ではなく **null** で返す(``asset_scan`` 表のSQL comment)。

代替画像は一切返さない。素材が無いことは普通に起きる(取得前に配信が終わった・CDNが
403を返した)ので、それらしい絵を返すと「在るのに出ない」と「そもそも無い」が画面から
見分けられなくなる。名前も同じで、引けなければ空のまま出す。
"""

import asyncio
import json
import logging
import os
import re
import secrets
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from tictok.api import runtime
from tictok.core import layout
from tictok.media.avatar_pool import avatar_key
from tictok.media.emote_pool import is_valid_emote_id
from tictok.media.gift_icons import sniff_image_type
from tictok.store.assets import ASSET_USER_SORTS

router = APIRouter()

logger = logging.getLogger("tictok.assets")

KIND_GIFT_ICON = "gift_icon"
KIND_EMOTE = "emote"
KIND_AVATAR = "avatar"

# 画面のtabの並びでもある。件数順ではなく「1件を名指しで探しに来る確率」の高い順
# (giftとemoteは名前で探せる、avatarは人を知っていないと探せない)。
KIND_ORDER = (KIND_GIFT_ICON, KIND_EMOTE, KIND_AVATAR)
KIND_LABELS = {
    KIND_GIFT_ICON: "Giftアイコン",
    KIND_EMOTE: "Emote",
    KIND_AVATAR: "Userアイコン",
}

# 一覧を作るためにdirを歩く種別。ここに居ない種別(avatar)は、一覧がusers表駆動なので
# 「ついでに数え直す」機会が無く、snapshotはrescanでしか更新されない。
WALKED_KINDS = (KIND_GIFT_ICON, KIND_EMOTE)

# poolのfileは拡張子を持たない(``<id>.img``)。実形式は中身の先頭bytesで決める。
POOL_SUFFIX = ".img"

# 外部由来のid。ここを通った文字列だけをfile名として使うので、pool外のpathは組み立たない。
_GIFT_ID_RE = re.compile(r"^[0-9]{1,20}$")
_AVATAR_ID_RE = re.compile(r"^[0-9a-f]{40}$")

# 素材の一覧が受け付ける並び順。**先頭がその種別の既定**で、summaryがそのまま画面へ渡す。
# 種別ごとに成立するものが違うのは、一覧の源が違うため: disk源は素材そのものの属性
# (容量・更新日時)で並べられるが、avatarはusers表が源なのでfileの属性を持たない。
# 画面側に同じ一覧を持たせない —— 持たせると、ここへ並び順が増えても画面が黙って
# 古いままになる(Job画面の種別labelで実際に起きた形)。集計結果ではなく種別の性質なので、
# DBのsnapshotではなくこの定義から載せる。
SORT_NAME = "name"
SORT_SIZE = "size"
SORT_MTIME = "mtime"
SORT_LAST_SEEN = "last_seen"
# 集計由来の並び順。**itemの ``stats`` のkeyと同じ語**にしてある —— 画面が「今どの数字で
# 並んでいるか」を、並び順と数値の対応表を自前で持たずに示せるようにするため。
SORT_SENDS = "sends"
SORT_COINS = "coins"
SORT_USES = "uses"
SORT_FREQ = "freq"
DISK_SORTS = (SORT_NAME, SORT_SIZE, SORT_MTIME)
# 並び順の語 -> 走査結果の項目名。``size`` は応答でもfileでも ``bytes`` という名前で、
# 語をそのままkeyに使うと「容量順」だけが500になる。集計由来の語は ``stats`` に同じ名前で
# 入っているので、ここには要らない(``_disk_items`` が同じkeyで引く)。
DISK_SORT_FIELDS = {SORT_SIZE: "bytes", SORT_MTIME: "mtime"}
# 集計が無い素材の扱い。並べるときだけ最小値として置き、``stats`` には出さない ——
# 「送られた記録が無い」と「0回送られた」は別の事実で、後者として画面に出すと嘘になる。
_MISSING_STAT_SORT_KEY = -1
KIND_SORTS = {
    # 既定は「送られた回数が多い順」。素材を探しに来る人が最初に見たいのは、その配信で
    # 実際によく飛んでいるgiftだからである(名前順の先頭は数字idのgiftで埋まる)。
    KIND_GIFT_ICON: (SORT_SENDS, SORT_COINS, SORT_NAME, SORT_SIZE, SORT_MTIME),
    KIND_EMOTE: (SORT_USES, SORT_NAME, SORT_SIZE, SORT_MTIME),
    # avatarはusers表(と頻度表)の列でしか並べられない。ここの語は store 側の
    # ``ASSET_USER_SORTS`` に在るものだけ(下のassertが両者のずれを起動時に落とす)。
    KIND_AVATAR: (SORT_FREQ, SORT_LAST_SEEN, SORT_NAME),
}
assert all(sort in ASSET_USER_SORTS for sort in KIND_SORTS[KIND_AVATAR])

# 配信者で絞れる種別。giftは配信者別に採っていないので受けない —— 受ける形にだけして
# 全配信者の値を返すと、絞ったつもりの人が絞れていないことに気付けない。
KIND_FILTERS = {
    KIND_GIFT_ICON: (),
    KIND_EMOTE: ("streamer",),
    KIND_AVATAR: ("streamer",),
}

# ``stats`` の項目定義。labelはserverが持つ(画面に訳語を置くと必ずずれる)。keyは
# :data:`KIND_SORTS` の並び順の語と同じで、そこが対応表の代わりになっている。
# ``core/ops_labels.py`` へ出さないのは、あちらが画面を跨いで使う語(job種別・状態)の置き場で、
# ここの語は並び順と対で意味を持つため —— 離すと、片方だけ増えたときに黙って対応が切れる。
STAT_DEFS = {
    # 「回数」ではなく「個数」。値は gift_count の合計(=送られた個)で、10連は1 eventだが
    # 10個である。「回数」と名乗ると10連が1回に見え、隣に出る数字(10)と食い違う。
    # 同じ理由で単位も「個」—— labelが個数で単位が回だと、1つのtileの中で語が矛盾する。
    SORT_SENDS: {"label": "送られた個数", "unit": "個"},
    # gift 1つを送るのにかかるコインの数(userの定義)。連打の総額ではないので、
    # 値は gift_count で割った1個あたりの値を採る。
    SORT_COINS: {"label": "コイン数", "unit": None},
    SORT_USES: {"label": "使われた回数", "unit": "回"},
    # 「出現回数」であって「出現順」ではない。「〜順」にすると、昇順/降順のcontrolと
    # 意味が二重になる。
    SORT_FREQ: {"label": "出現回数", "unit": "回"},
}
KIND_STATS = {
    KIND_GIFT_ICON: (SORT_SENDS, SORT_COINS),
    KIND_EMOTE: (SORT_USES,),
    KIND_AVATAR: (SORT_FREQ,),
}

# 1ページの上限。画面が指定するのは100前後だが、まとめて確認したい場合のために広く取る。
# 上限を置くのは、offsetの無い巨大なlimitがそのままresponseの大きさになるため。
LIST_LIMIT_MAX = 1000

# ZIPを組むときに1回のthread呼び出しで処理するfile数。全件(19万file/316MB)を1回の
# to_threadで作るとその間event loopが返らないので、束ねて刻む。
ARCHIVE_BATCH = 200

# 束の中のfileを何本並行で読むか。ZIPの生成はほぼ全部が小さいfileのrandom readで、実測
# (avatar 2,000件・cold)は 逐次17.7秒 / 4本5.0秒 / 8本2.9秒 / 16本2.5秒 —— 全件へ引き直すと
# 28分が4.6分になる。8本にしてあるのは、16本にしても14%しか縮まないうえ、serverの
# thread poolは焼き込み・文字起こし・容量scanと共用だからである(policyではなく実測から
# 決めた定数なので設定にはしない)。書き込む側(zipfile)は1本のまま —— ZipFileはthread
# safeではなく、並行にするのは読む側だけである。
ARCHIVE_READ_WORKERS = 8

# 素材は不変(idが同じなら中身も同じ)なので、browserに長く持たせてよい。一覧のthumbnailは
# 1画面で100枚並ぶため、page送りのたびに引き直させない。
ASSET_CACHE_CONTROL = "public, max-age=604800, immutable"

# 中身から形式を判定できたときのfile拡張子。判らない形式に拡張子を騙らせない
# (``.jpg`` と名乗ったwebpは、開く側によっては黙って壊れた絵になる)。
CONTENT_TYPE_EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/avif": "avif",
    "image/heic": "heic",
}
UNKNOWN_CONTENT_TYPE = "application/octet-stream"
UNKNOWN_EXTENSION = "bin"

# file名に残してよい文字。path区切り・制御文字・drive指定(':')をここで落とす。
_UNSAFE_NAME_RE = re.compile(r"[^\w\-. ]", re.UNICODE)
_NAME_PART_MAX = 80

# ZIPのtimestampが表せる下限(1980-01-01)。これより古いmtimeのfileを入れると
# zipfileが例外を投げるので、その1件でまとめ全体が落ちないよう丸める。
_ZIP_EPOCH = 315532800.0

# 走査中のrescanは1本だけ。同時に2本走らせても速くならず(同じdirを2重に舐める)、
# snapshotの書き込みが競合する(``routes/storage.py`` の容量scanと同じ作法)。
_rescan_lock = asyncio.Lock()

# まとめDownloadの引換券。processが持つ小さな辞書で、期限で捨てる。
_tickets: dict = {}


# ---------------------------------------------------------------------------------------
# 種別とid
# ---------------------------------------------------------------------------------------


def _require_kind(kind: str) -> str:
    if kind not in KIND_LABELS:
        raise HTTPException(
            status_code=400,
            detail=f"知らない素材の種別です: {kind}（{', '.join(KIND_ORDER)}）")
    return kind


def _pool_dir(kind: str) -> Path:
    if kind == KIND_GIFT_ICON:
        return layout.gift_icon_pool_dir()
    if kind == KIND_EMOTE:
        return layout.emote_pool_dir()
    return layout.avatar_pool_dir()


def _valid_id(kind: str, asset_id: str) -> bool:
    """そのidをfile名として使ってよいか。

    kindごとに実際の命名規則そのもので判定する。「'..' と区切り文字を弾く」式の否定形に
    しないのは、通る文字を数えられない条件が1つでもあると、pool外を指すpathが組み立つ
    余地が残るためである(emoteは ``emote_pool.is_valid_emote_id`` が同じ判定を持っており、
    保存側とここで別の規則を持たない)。"""
    if kind == KIND_GIFT_ICON:
        return bool(_GIFT_ID_RE.match(asset_id))
    if kind == KIND_EMOTE:
        return is_valid_emote_id(asset_id)
    return bool(_AVATAR_ID_RE.match(asset_id))


def _asset_path(kind: str, asset_id: str) -> Path:
    """その素材の実path。idが規則に合わなければ400。

    idが通った後にもう一度 parent を確かめるのは、規則の方を後から緩めたときに
    pool外への書き出し/読み出しが黙って通らないようにするため。"""
    if not _valid_id(kind, asset_id):
        raise HTTPException(status_code=400, detail=f"素材のidが不正です: {asset_id[:64]}")
    pool = _pool_dir(kind)
    path = pool / f"{asset_id}{POOL_SUFFIX}"
    if path.parent.resolve() != pool.resolve():
        raise HTTPException(status_code=400, detail=f"素材のidが不正です: {asset_id[:64]}")
    return path


# ---------------------------------------------------------------------------------------
# 中身の名乗り(content-type と拡張子)
# ---------------------------------------------------------------------------------------


def _sidecar_type(path: Path) -> str:
    """``<key>.type`` に控えてある取得時のcontent-type。無ければ空。"""
    sidecar = path.with_suffix(".type")
    try:
        if sidecar.is_file():
            return sidecar.read_text(encoding="utf-8").strip()
    except OSError:
        logger.warning(
            "素材のcontent-type sidecarを読めませんでした: %s", sidecar,
            extra={"event": "http.asset_type_read_failed",
                   "ctx": {"path": str(sidecar)}},
            exc_info=True,
        )
    return ""


def _content_type(path: Path, head: bytes) -> str:
    """その素材を名乗るcontent-type。判らなければ ``application/octet-stream``。

    中身のbytesを先に見て、判らないときだけ ``.type`` sidecarを使う。逆順にしないのは、
    sidecarが取得時のHTTP headerの写しで、``avatar_pool`` はimage/*でない値を
    ``image/jpeg`` へ丸めて書くため —— 実物と違う形式を名乗ったimageはbrowserが黙って
    捨て、「iconが出ない」だけの症状になる。sniffは実物を見るので嘘をつかない。
    どちらでも判らない形式(sniffが知らず sidecarも無い)は octet-stream で名乗る。
    それらしい ``image/jpeg`` を付けない: 拡張子もそれに従うので、開けないfileが
    正しい名前で保存されることになる。"""
    sniffed = sniff_image_type(head)
    if sniffed:
        return sniffed
    sidecar = _sidecar_type(path)
    if sidecar.startswith("image/"):
        return sidecar
    return UNKNOWN_CONTENT_TYPE


def _extension(content_type: str) -> str:
    return CONTENT_TYPE_EXTENSIONS.get(content_type, UNKNOWN_EXTENSION)


def _read_head(path: Path) -> bytes:
    """形式判定に足りるだけの先頭bytes。読めなければ空。"""
    try:
        with path.open("rb") as handle:
            return handle.read(16)
    except OSError:
        return b""


# ---------------------------------------------------------------------------------------
# poolの走査
# ---------------------------------------------------------------------------------------


def _scan_pool(kind: str) -> dict:
    """poolを1度だけ舐めて、素材の点数・実占有量・(disk源のkindなら)一覧を作る。

    filesystemしか触らない。DBを引かないのは、一覧のたびに呼ばれる経路だからである
    (gift名の解決は500msかかるので :func:`_gift_names` へ分けてある)。

    ``count`` は **素材の点数**であってfile数ではない。avatarは1人あたり ``.img``
    (画像) / ``.type``(取得時のcontent-type) / ``.meta``(解像度の向上を検出するための
    識別子) / ``.up-<hash>.png``(焼き込みが作るAI超解像cache)を持ち得るので、file数で
    数えると3倍近い数を名乗る。数えるのは ``.img`` だけ。

    **中身が0 byteの ``.img`` は数えない。** 一覧の ``cached`` 判定(``_describe_user``)も
    ZIP(``_archive_plan``)も既にこれを除いており、ここだけが数えていると「summaryの件数」と
    「全件ZIPの件数」がその分ずれる。実測(2026-08-23)では3種とも0件で、今のところ数字は
    変わらない —— 揃えてあるのは、書き損じた素材が1つ出た日に**気付けないずれ**へ化けるのを
    防ぐためである。

    逆に ``bytes`` は同じidに紐づく付随fileも全部足した**実占有量**にする ——
    「片付けたらどれだけ空くか」を答えられない数字には意味が無いため。実測では
    ``.img`` だけなら430.6MBだが、実際にpoolが食っているのは538.2MB(差の107MBは
    超解像cache)で、この差は消す判断をする人が知るべき量である。

    gift iconのdirには焼き込みが置く得点表示用のavatar(``savatar_*``)とgift名のindex
    (``names.json``)も同居している(``record/video_overlay.py``)。素材ではないので
    件数にも容量にも入れない —— 入れると、画面の件数がpoolのgift数と一致しない。

    threadで走らせる前提。avatarでは実測1.2〜2.5秒かかる。
    """
    pool = _pool_dir(kind)
    items: list = []
    ids: set = set()
    total_bytes = 0
    count = 0
    try:
        entries = list(os.scandir(pool))
    except OSError:
        # poolがまだ無い(収集を1度もしていない)のは異常ではない。0件として返す。
        return {"kind": kind, "count": 0, "bytes": 0, "items": [], "ids": ids}
    for entry in entries:
        name = entry.name
        stem = name.split(".", 1)[0]
        if not _valid_id(kind, stem):
            continue
        try:
            stat = entry.stat()
        except OSError:
            continue
        total_bytes += stat.st_size
        if name != f"{stem}{POOL_SUFFIX}" or stat.st_size <= 0:
            continue
        count += 1
        if kind == KIND_AVATAR:
            # avatarの一覧はusers表から出るので、bytes/mtimeを持つitemsは作らない
            # (22万件のdictを抱えても、鍵だけでは誰のものか名乗れず一覧には使えない)。
            # 鍵の集合だけは残す —— 「名前を辿れる素材が何点か」(listable)は、この集合と
            # users由来の鍵との重なりでしか数えられない。
            ids.add(stem)
        else:
            items.append({"id": stem, "bytes": stat.st_size, "mtime": stat.st_mtime})
    return {"kind": kind, "count": count, "bytes": total_bytes, "items": items,
            "ids": ids}


def _catalog_gift_names(pool: Path) -> dict:
    """``<pool>/gift_icons/names.json`` が持つ {gift_id: 名前}。

    接続時に取得したgift listから ``GiftIconCache.persist_gift_list`` が書く、その時点の
    TikTokのカタログである。fileを1本読むだけ(実測20KB)なので、一覧のたびに読み直して
    構わない —— 収集が新しいgiftを覚えたら、rescanを待たずに名前が出る。"""
    names: dict = {}
    index = pool / "names.json"
    try:
        if not index.is_file():
            return names
        catalog = json.loads(index.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning(
            "gift名のindexを読めないため、gift名は走査時に採ったものだけになります: %s", index,
            extra={"event": "http.asset_gift_names_index_failed",
                   "ctx": {"path": str(index)}},
            exc_info=True,
        )
        return names
    if not isinstance(catalog, dict):
        return names
    # 保存されているのは {名前: gift_id} なので、引くには逆に組み直す。
    for name, gift_id in catalog.items():
        try:
            names[int(gift_id)] = str(name).strip()
        except (TypeError, ValueError):
            continue
    return names


def _gift_names(scans: Optional[dict] = None) -> dict:
    """{gift_id: 表示名}。引けなかったgiftはこのdictに現れない。threadで呼ぶ前提。

    源が2つあり、費用が3桁違う:

      1. カタログ(``names.json``) —— fileを1本読むだけ。**毎回読み直す**。
      2. eventsで実際に観測した名前 —— gift_id列にindexが無く全走査で実測500ms。
         走査(rescan)のときだけ引き、``asset_scan`` のpayloadに載せて持ち回る。

    カタログを先に採る。実測(2026-08-23、gift icon 991件)でカタログは868件を名乗れるのに
    対しeventsは457件しか無く、両方在る384件のうち47件で食い違った。食い違いの中身は
    ``'Romanian Train '``(末尾空白)や ``'Team Cheers'``→``'Club Cheers'``(改名)で、
    eventsが持つのは**その時そう呼ばれていた名前**、カタログが持つのは**今の名前**である。
    探す人が知っているのは後者なので、カタログを優先し、カタログから消えた旧giftだけを
    eventsで埋める(実測で+73件、合わせて941件。残る50件は名前の源が無く空のまま)。

    まだ一度もrescanしていない環境では、カタログの868件だけで名乗る。0件にはならない。

    どちらにも無いgiftへ代替名は作らない。画面はidだけで名乗る。
    """
    names = _catalog_gift_names(_pool_dir(KIND_GIFT_ICON))
    for gift_id, row in _stored_stats(KIND_GIFT_ICON, "gift", scans).items():
        try:
            names.setdefault(int(gift_id), str(row.get("name") or ""))
        except (TypeError, ValueError):
            continue
    return {gift_id: name for gift_id, name in names.items() if name}


# 集計を採ったかどうか。走査(rescan)でしか採れない値なので、走査していない種別では
# 配信者の絞り込みも集計順も**空を返す**。それを「この配信者は使っていない」と読ませない
# ために、summaryが真偽で名乗る —— 画面は0件と未集計を別の文言で出せる。
_AGGREGATE_KEYS = {KIND_GIFT_ICON: "gift", KIND_EMOTE: "emote"}


def _has_aggregate(kind: str, scan: dict, avatar_freq: bool) -> bool:
    # avatarの集計はsnapshotではなく表(asset_avatar_freq)に在るので、そちらの実体を見る。
    # payloadの印で代用すると、印を足す前に採った集計が「未集計」を名乗る。
    if kind == KIND_AVATAR:
        return avatar_freq
    payload = scan.get("payload") or {}
    return bool(payload.get(_AGGREGATE_KEYS[kind]))


def _stored_stats(kind: str, key: str, scans: Optional[dict] = None) -> dict:
    """走査のときにsnapshotへ載せた集計。まだ走査していなければ空。threadで呼ぶ前提。

    空を「集計が0だった」と読ませないのは呼び出し側の責務 —— 値が無い素材は ``stats``
    からその項目ごと落とす(0で埋めない)。"""
    if scans is None:
        scans = runtime.storage.get_asset_scans()
    payload = (scans.get(kind) or {}).get("payload") or {}
    stored = payload.get(key)
    return stored if isinstance(stored, dict) else {}


def _event_stats() -> dict:
    """eventsを1度舐めて作った集計を、種別ごとの保存できる形へ整える。threadで呼ぶ前提。

    走査(rescan)だけが呼ぶ。実測1.8秒で、一覧のたびに払える費用ではない。

    ``avatar`` だけ形が違う: ここでpoolのfile名の鍵(sha1)へ変換せず、``identity_key`` の
    まま返す。頻度表の1行が指すのは「素材」ではなく「人」で、一覧はusers表と結合して
    引くからである。合計(``streamer=''``)もここで作る —— 配信者を選ばない既定の一覧が
    毎回93,621行を畳まずに済む。

    JSONへ落とすkeyは全て文字列にする(JSONのobject keyは文字列しか持てず、intのまま
    書くと読み戻したときに型が変わって引けなくなる)。
    """
    stats = runtime.storage.asset_event_stats()
    gift = {str(gift_id): {"name": row["name"], "sends": row["sends"],
                           "coins": row["coins"]}
            for gift_id, row in stats["gift"].items()}
    emote = {owner: {str(emote_id): uses for emote_id, uses in counts.items()}
             for owner, counts in stats["emote"].items()}
    # 頻度表の行。user keyのままでは users表と結合できないので identity_key へ戻す。
    freq: list = []
    totals: dict = {}
    for owner, counts in stats["avatar"].items():
        for identity_key, uses in counts.items():
            freq.append((owner, identity_key, uses))
            totals[identity_key] = totals.get(identity_key, 0) + uses
    freq.extend(("", identity_key, uses) for identity_key, uses in totals.items())
    return {"gift": gift, "emote": emote, "avatar_freq": freq}


def _scan_payload(kind: str, stats: dict) -> dict:
    """その種別のsnapshotへ載せる集計。載らない種別は空。

    gift と emote はpoolの点数が1,000件前後なので、集計ごとJSONで持って構わない
    (実測: gift 457件・emote 160組)。avatarだけは別表で、理由は ``asset_avatar_freq`` の
    SQL commentにある。"""
    if kind == KIND_GIFT_ICON:
        return {"gift": stats["gift"]}
    if kind == KIND_EMOTE:
        return {"emote": stats["emote"]}
    return {}


async def _listable_count(kind: str, scan: dict) -> int:
    """**diskに実体が在り、かつ名前を辿れる**素材の点数。

    数える母集団は ``count`` と同じ「diskに在る素材」で、そのうち名乗る名前が在るものだけを
    数える。``count - listable`` が「実体は在るが名前を辿れない素材の数」にちょうど一致する
    ので、画面はその差をそのまま注記にできる。

    **users表の行数ではない。** あちらは「人」の数で、cacheを持たない人(一覧に
    ``cached: false`` で出る行)を含む。母集団が「人」と「素材」で違うので、``count`` から
    引いても「名前を辿れない素材の数」にはならない —— 実測(2026-08-23)で
    users表の行は193,359、diskに実体が在って名前も辿れる素材は191,844で、
    ``234,480 - 191,844 = 42,636`` が名前を辿れない素材の実数である。

    avatarだけがずれる。file名が ``sha1(unique_id or nickname)`` で、鍵から人へ戻せるのは
    users表に居る人だけだからである。他の種別はidそのものが名乗りなので全点が辿れる。

    走査と同じ契機で採る。別々に採ると、画面に並ぶ2つの数字がいつの時点のものか読めない。
    """
    if kind != KIND_AVATAR:
        return scan["count"]
    # 逆引きは1件のdownloadとZIPが使うのと同じ物(実測0.6秒)。rescanは明示操作なので払う。
    names = await asyncio.to_thread(_avatar_names)
    return len(scan["ids"] & names.keys())


async def _rescan_kind(kind: str, stats: dict) -> dict:
    """1種別を数え直してsnapshotへ全置換で保存する。所要時間も記録する。

    ``stats`` は :func:`_event_stats` が1度の走査で作った全種別ぶんの集計。種別ごとに
    引き直さないのは、3種の集計が同じ1回のevents走査から出るためである。"""
    started = time.monotonic()
    scan = await asyncio.to_thread(_scan_pool, kind)
    listable = await _listable_count(kind, scan)
    payload = _scan_payload(kind, stats)
    if kind == KIND_AVATAR:
        # 配信者ごとの出現回数だけはpayloadに入らない(実測93,621行)。表へ全置換する。
        await asyncio.to_thread(
            runtime.storage.save_asset_avatar_freq, stats["avatar_freq"])
    duration_ms = (time.monotonic() - started) * 1000
    await asyncio.to_thread(
        runtime.storage.save_asset_scan, kind, scan["count"], listable, scan["bytes"],
        duration_ms, payload)
    logger.info(
        "素材を数え直しました（種別=%s / %d点（一覧に出せる %d点） / %.1fMB / %.0fms）",
        kind, scan["count"], listable, scan["bytes"] / 1e6, duration_ms,
        extra={"event": "http.asset_rescanned",
               "ctx": {"kind": kind, "count": scan["count"], "listable": listable,
                       "bytes": scan["bytes"], "duration_ms": round(duration_ms, 1)}},
    )
    return scan


async def _touch_scan(kind: str, scan: dict, duration_ms: float) -> None:
    """一覧を作るためにdirを歩いた結果を、そのままsnapshotへ反映する。

    ここを通るのはgift_iconとemoteだけである。**avatarが通らないのは**、その一覧が
    users表駆動でdirを歩かないため —— 「ついでに数え直す」ための走査が発生しない。
    avatarのsnapshotは ``POST /api/assets/rescan`` でしか動かない。

    payloadは渡さない(保存済みを残す)。この経路はgift名を持っていないので、渡すと
    一覧を1回開くだけで走査時に採った名前が消える。

    ここを通る種別は ``listable`` が ``count`` と同値である(名前の源がidそのものなので、
    diskに在る素材は全部名前を辿れる)。ずれるのはavatarだけで、そのavatarはここを通らない。
    """
    await asyncio.to_thread(
        runtime.storage.save_asset_scan, kind, scan["count"], scan["count"],
        scan["bytes"], duration_ms)


# ---------------------------------------------------------------------------------------
# 一覧
# ---------------------------------------------------------------------------------------


def _resolve_sort(kind: str, sort: str, order: str) -> tuple:
    """(sort, order) を確定する。成立しない並び順は400で断る。

    avatarの一覧はusers表から出るので、fileの属性(size / mtime)では並べられない。
    黙って別の並びで返さない —— 押した並び順と出てくる順が違うことに画面からは
    気付けず、「並べ替えが効かない」ではなく「順序が信用できる」と誤読される。"""
    allowed = KIND_SORTS[kind]
    sort = sort or allowed[0]
    if sort not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"{KIND_LABELS[kind]}は「{sort}」で並べ替えできません。"
                   f"使えるのは {', '.join(allowed)} です。")
    if order not in ("", "asc", "desc"):
        # 上の「並べ替えできません」は並び順の**語**、こちらは**向き**。同じ文言にすると、
        # 400を受けた人がどちらを直せばよいか読めない。
        raise HTTPException(
            status_code=400,
            detail=f"並び順の向きは asc か desc で指定してください: {order[:32]}")
    # 既定の向き: 名前は小さい方から、時刻と容量は大きい方から(新しい・重い順に見る)。
    return sort, order or ("asc" if sort == SORT_NAME else "desc")


def _disk_items(scan: dict, kind: str, names: dict, stats: dict, q: str,
                sort: str, order: str, filtered: bool) -> list:
    """走査済みのpoolから、絞り込み・並べ替えを済ませた全一致を返す(切り出す前)。

    行を落とすのは ``filtered``(配信者で絞った)ときだけ。**並べ替えでは落とさない** ——
    落とす形にすると、まだ一度も再走査していない環境で既定の並び(集計順)が空の一覧に
    なる。集計を持たない素材は末尾へ回し、``stats`` からはその項目を落とす。"""
    rows = []
    for item in scan["items"]:
        name = names.get(int(item["id"]), "") if kind == KIND_GIFT_ICON else ""
        rows.append({**item, "name": name, "stats": stats.get(item["id"]) or {}})
    if filtered:
        rows = [row for row in rows if row["stats"]]
    if q:
        needle = q.strip().lower()
        rows = [row for row in rows
                if needle in row["id"].lower() or needle in row["name"].lower()]
    if sort == SORT_NAME:
        # 名前が無い素材(emoteは常に、カタログに無いgiftも)は id を名乗りに使う。
        # 空文字で揃えると名無しが全て先頭へ固まり、並べ替えが機能していないように見える。
        rows.sort(key=lambda row: ((row["name"] or row["id"]).lower(), row["id"]))
    elif sort in STAT_DEFS:
        # 集計を持たない素材は最小値として並べる(``stats`` には出さない)。降順で末尾へ
        # 回るので、「記録が無い」ものが上位を占めることはない。SQL側のNULLの扱いと揃えてある。
        rows.sort(key=lambda row: (
            _MISSING_STAT_SORT_KEY if row["stats"].get(sort) is None
            else row["stats"][sort], row["id"]))
    else:
        rows.sort(key=lambda row: (row[DISK_SORT_FIELDS[sort]], row["id"]))
    if order == "desc":
        rows.reverse()
    return rows


def _stats_payload(kind: str, values: dict) -> list:
    """画面へ出す ``stats``。値の無い項目は**落とす**(0で埋めない)。

    labelはserverが持つ(:data:`STAT_DEFS`)。keyは並び順の語と同じなので、画面は
    「今どの数字で並んでいるか」を対応表なしに示せる。"""
    return [{"key": key, "label": STAT_DEFS[key]["label"], "value": values[key],
             "unit": STAT_DEFS[key]["unit"]}
            for key in KIND_STATS[kind] if values.get(key) is not None]


def _describe_disk_item(kind: str, row: dict) -> dict:
    path = _pool_dir(kind) / f"{row['id']}{POOL_SUFFIX}"
    sub = (f"gift_id {row['id']}" if kind == KIND_GIFT_ICON
           else f"emote_id {row['id']}")
    return {
        "id": row["id"],
        "name": row["name"],
        "sub": sub,
        "bytes": row["bytes"],
        "mtime": row["mtime"],
        "content_type": _content_type(path, _read_head(path)),
        # diskの走査で見つけた行なので、実体は必ず在る。
        "cached": True,
        "src": _src(kind, row["id"]),
        "stats": _stats_payload(kind, row["stats"]),
    }


def _describe_user(row: dict) -> dict:
    """users表の1行を素材の行にする。cacheが無くても行は落とさない。

    ``cached`` は**表示するこの瞬間の事実**で、走査のsnapshotからは答えない。古い集計から
    答えると、既に消えた素材にDownload buttonを出すことになる。1ページ100件のstatは
    実測で無視できる(cold 890ms / warm 233ms のうち大半はSQL側)。

    poolに無いuserを落とすと、``total``(SQLのCOUNT)と実際に返る件数が食い違い、
    page送りが進むほどずれる。無いことは ``cached: false`` で名乗る —— 「まだ取れて
    いない人」は画面に出てよい情報で、隠すと「居ないこと」と区別が付かない。"""
    user_key = row["unique_id"] or row["nickname"] or ""
    key = avatar_key(user_key)
    path = layout.avatar_pool_dir() / f"{key}{POOL_SUFFIX}"
    size = 0
    mtime = None
    cached = False
    content_type = ""
    try:
        stat = path.stat()
        if stat.st_size > 0:
            cached = True
            size = stat.st_size
            mtime = stat.st_mtime
            content_type = _content_type(path, _read_head(path))
    except OSError:
        pass
    return {
        "id": key,
        "name": row["nickname"] or "",
        "sub": f"@{row['unique_id']}" if row["unique_id"] else "",
        "bytes": size,
        "mtime": mtime,
        "content_type": content_type,
        "cached": cached,
        "src": _src(KIND_AVATAR, key) if cached else "",
        # 出現回数は頻度表と結合したときにだけ載る(結合しない並びではNULL)。持たない行に
        # 0を置かない —— 「一度も現れていない」と「0回現れた」は別の事実である。
        "stats": _stats_payload(KIND_AVATAR, {SORT_FREQ: row.get("uses")}),
    }


def _src(kind: str, asset_id: str) -> str:
    return f"/api/assets/file?kind={kind}&id={asset_id}"


# ---------------------------------------------------------------------------------------
# file名
# ---------------------------------------------------------------------------------------


def _safe_part(text: str) -> str:
    """人が読めるfile名の部品。path区切り・制御文字を落として長さを切る。

    gift名もnicknameも外部由来で、``/`` や改行、右横書きの制御文字が普通に混じる。
    残す文字を数え上げる形(通す集合を書く)にしてあるのは、落とす文字を並べる形だと
    数え漏らした1文字が区切りとして解釈され、保存先が変わり得るため。日本語のnicknameは
    ``\\w`` に入るのでそのまま残る。"""
    cleaned = _UNSAFE_NAME_RE.sub("_", text).strip(" ._")
    return cleaned[:_NAME_PART_MAX]


def _download_stem(kind: str, asset_id: str, name: str) -> str:
    """``download=1`` とZIPの中で使うfile名の、拡張子より前。

    名前が引けなかった素材はidだけで名乗る。それらしい名前を作らない —— 実在しない
    gift名が付いたfileは、後から見ると実在する素材と見分けが付かない。

    拡張子を切り離してあるのは、それが**中身を読まないと決まらない**ためである
    (poolのfileは形式を名前に持たない)。ZIPは中身を読む段でしか形式を知らないので、
    先に拡張子まで決めると、全fileを名前決めと中身読みで二度開くことになる。"""
    part = _safe_part(name)
    if kind == KIND_GIFT_ICON:
        return f"gift_{asset_id}_{part}" if part else f"gift_{asset_id}"
    if kind == KIND_EMOTE:
        return f"emote_{asset_id}"
    return part or asset_id


def _download_name(kind: str, asset_id: str, name: str, content_type: str) -> str:
    return f"{_download_stem(kind, asset_id, name)}.{_extension(content_type)}"


def _content_disposition(filename: str) -> str:
    """非ASCIIのfile名(日本語のnickname・gift名)をheaderへ載せる形。RFC 5987。"""
    return f"attachment; filename*=UTF-8''{quote(filename, safe='')}"


def _display_name(kind: str, asset_id: str) -> str:
    """その素材の人が読む名前。引けなければ空。threadで呼ぶ前提。"""
    if kind == KIND_GIFT_ICON:
        return _gift_names().get(int(asset_id), "")
    if kind == KIND_AVATAR:
        return _avatar_names().get(asset_id, "")
    return ""


def _avatar_names() -> dict:
    """{avatar_key: unique_id または nickname}。threadで呼ぶ前提。

    cacheしない。19万件のdictは40MB前後になり、file 1枚のdownloadのために常駐させる
    には重い。組むのは人が「download」か「まとめてDownload」を押したときだけで、
    実測0.6秒(193,359行のSELECTとsha1の合計)である。"""
    names = {}
    for user_key, unique_id, nickname in runtime.storage.asset_user_keys():
        names.setdefault(avatar_key(user_key), unique_id or nickname)
    return names


# ---------------------------------------------------------------------------------------
# route: 件数と容量
# ---------------------------------------------------------------------------------------


@router.get("/api/assets/summary")
async def assets_summary() -> dict:
    """素材の種別ごとの点数と実占有量。**diskは一切歩かない。**

    返すのはDBのsnapshot(``asset_scan``)だけで、走査は ``POST /api/assets/rescan`` が
    行う。avatarのpoolは662,315 entryで1回1.2〜2.5秒、pageを開くたびに払ってよい費用では
    ないためである(容量内訳 ``/api/storage/usage`` と同じ方針)。

    まだ数えていない種別は ``count`` / ``bytes`` / ``scanned_at`` / ``duration_ms`` を
    **null** で返す。0件にしない —— 「素材が無い」と「まだ数えていない」は別の事実で、
    畳むと画面が0件と嘘をつく。

    ``count`` は素材の点数(avatarなら中身の在る ``.img`` の数)、``bytes`` は付随file
    (``.type`` / ``.meta`` / 超解像cache)まで含めた実占有量で、数える対象が違う。
    片付けの判断に使えるのは後者で、まとめてDownloadで出てくる件数は前者である。

    ``listable`` は ``count`` と**同じ母集団**(diskに在る素材)のうち、**名前を辿れる**点数。
    差 ``count - listable`` が「実体は在るが名乗る名前が無い素材」の数そのものになる
    (実測 234,480点のうち191,844点、差は42,636点)。avatarだけがずれるのは、poolのfile名が
    鍵(sha1)で、人へ戻せるのはusers表に居る分だけだからである。

    一覧の ``total`` とは**一致しない**。あちらはusers表の行数=「人」の数で、cacheを持たない
    人(``cached: false`` の行)を含む(実測193,359行)。母集団が「人」と「素材」で違うので、
    3つの数字はそれぞれ別の問いに答えている: ``count`` は「diskに何点在るか」(=全件ZIPの
    件数)、``listable`` は「そのうち名乗れるのは何点か」、一覧の ``total`` は「一覧に何行
    並ぶか」である。

    ``sorts`` はその種別で成立する並び順で、先頭がその種別の既定である。``filters`` は
    その種別が受ける絞り込み。どちらも集計結果ではなく種別の性質なので、snapshotではなく
    code側の定義(:data:`KIND_SORTS` / :data:`KIND_FILTERS`)から載せる。

    ``streamers`` は配信者filterに並べる配信者。画面に書かせないためにserverが配る ——
    書かせると、監視対象が増えた日に画面だけが黙って古いままになる。"""
    scans, streamers = await asyncio.to_thread(_summary_sources)
    avatar_freq = await asyncio.to_thread(runtime.storage.asset_avatar_freq_exists)
    kinds = []
    for kind in KIND_ORDER:
        scan = scans.get(kind) or {}
        kinds.append({
            "kind": kind,
            "label": KIND_LABELS[kind],
            "count": scan.get("count"),
            "listable": scan.get("listable"),
            "bytes": scan.get("bytes"),
            "scanned_at": scan.get("scanned_at"),
            "duration_ms": scan.get("duration_ms"),
            "sorts": list(KIND_SORTS[kind]),
            # その種別が受ける絞り込み。受けない種別は空 —— 画面がどの種別で配信者を
            # 選ばせてよいかを、種別名の決め打ち無しに決められる。
            "filters": list(KIND_FILTERS[kind]),
            # 集計はrescanでしか採れない。未集計のまま配信者で絞ると必ず0件になるので、
            # 「素材が無い」と読まれないよう真偽で名乗る。
            "aggregated": _has_aggregate(kind, scan, avatar_freq),
        })
    return {"pool_root": str(layout.pool_root()), "kinds": kinds,
            "scanning": _rescan_lock.locked(), "streamers": streamers}


def _summary_sources() -> tuple:
    """summaryが要るDBの中身。1回のthreadで両方引く(どちらも数msのDB読み)。"""
    return runtime.storage.get_asset_scans(), runtime.storage.asset_streamers()


class RescanRequest(BaseModel):
    """再走査する種別。空でその種別を選ばない(=全種別)。"""

    kind: str = ""


@router.post("/api/assets/rescan")
async def rescan_assets(payload: Optional[RescanRequest] = None,
                        kind: str = "") -> dict:
    """poolを数え直してsnapshotを更新する。``kind`` 省略で全種別。

    種別はbody(``{"kind": "emote"}``)でもqueryでも受ける。押す側から見ればどちらも
    「この種別を数え直せ」であり、片方だけを受ける形にすると、もう片方で呼んだ人には
    **全種別の走査(avatarを含めて実測2.7秒)が黙って走る** —— 指定が無視されたことが
    応答からは読めない。

    これが唯一の走査の契機である(gift_icon / emoteは一覧を作るついでにも更新されるが、
    avatarはここでしか動かない —— :func:`_touch_scan` の理由)。poolの走査もeventsの集計も
    ``asyncio.to_thread`` で走らせ、event loopは塞がない。

    **eventsの走査は種別を何個指定しても1回だけ**行う。3種の集計(gift・emote・出現回数)は
    同じ1回の走査から出るので、種別ごとに引き直すと同じ126万行を最大3周することになる。

    応答は走査後のsnapshotで、``GET /api/assets/summary`` と同じ形である。押した人が
    続けてsummaryを引き直さずに済むようにするため。"""
    target = ((payload.kind if payload else "") or kind).strip()
    kinds = KIND_ORDER if not target else (_require_kind(target),)
    if _rescan_lock.locked():
        raise HTTPException(status_code=409, detail="素材の再走査が既に実行中です。")
    async with _rescan_lock:
        stats = await asyncio.to_thread(_event_stats)
        for target in kinds:
            await _rescan_kind(target, stats)
    # snapshotの読み直しはlockの外で行う。中で組むと、自分がlockを握っているせいで
    # 応答の scanning が必ず true になり、押した人には走査が終わっていないように見える。
    return await assets_summary()


# ---------------------------------------------------------------------------------------
# route: 一覧と1件の取得
# ---------------------------------------------------------------------------------------


@router.get("/api/assets")
async def list_assets(kind: str, q: str = "", sort: str = "", order: str = "",
                      limit: int = 100, offset: int = 0, streamer: str = "") -> dict:
    """1種別の素材の一覧。

    ``gift_icon`` / ``emote`` はpoolのdirを歩いて作る(実測 0.2秒未満 / 1ms)。歩いた結果は
    そのままsnapshotへ反映するので、この種別はsummaryの数字がtabを開くだけで新しくなる。
    ``q`` は id と名前の部分一致で、emoteは名前の源が無いのでidだけに当たる。

    ``avatar`` だけは **users表** が源で、diskは表示する行ごとに1回statするだけである
    (理由はmodule docstring)。歩く走査が無いので、この種別のsummaryは再走査でしか
    動かない。cacheの無いuserも ``cached: false`` の行として返す。

    ``streamer`` はその配信者の配信に現れた素材だけへ絞る。受けるのは ``filters`` に
    ``streamer`` を持つ種別だけで、持たない種別へ渡すと400になる —— 受けた振りをして
    全配信者の値を返すと、絞ったつもりの人が絞れていないことに気付けない。

    **絞り込みと集計順は母集団を変える。** ``streamer`` を指定した一覧、``sort`` が集計
    (``sends`` / ``coins`` / ``uses`` / ``freq``)の一覧には、その集計を持たない素材は
    出ない。0を入れて並べないためである —— 「記録が無い」と「0回だった」は別の事実で、
    前者に順位を与える意味は無い。母集団が変わることは ``total`` にそのまま出る。
    """
    _require_kind(kind)
    if limit < 1 or limit > LIST_LIMIT_MAX:
        raise HTTPException(
            status_code=400, detail=f"limitは1〜{LIST_LIMIT_MAX}で指定してください。")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offsetは0以上で指定してください。")
    sort, order = _resolve_sort(kind, sort, order)
    streamer = await _resolve_streamer(kind, streamer)
    if kind == KIND_AVATAR:
        rows, total = await asyncio.to_thread(
            runtime.storage.asset_user_page, q.strip(), sort, order, limit, offset,
            streamer)
        items = await asyncio.to_thread(
            lambda: [_describe_user(row) for row in rows])
    else:
        started = time.monotonic()
        scan = await asyncio.to_thread(_scan_pool, kind)
        # 計測はdirを歩いた分だけ。集計の読み出しを混ぜると、summaryの「走査に何秒かかるか」
        # が再走査のときと一覧のときで別の物を指す。
        walk_ms = (time.monotonic() - started) * 1000
        names, stats = await asyncio.to_thread(_disk_stats, kind, streamer)
        await _touch_scan(kind, scan, walk_ms)
        matched = _disk_items(scan, kind, names, stats, q, sort, order,
                              bool(streamer))
        total = len(matched)
        page = matched[offset:offset + limit]
        items = await asyncio.to_thread(
            lambda: [_describe_disk_item(kind, row) for row in page])
    return {"kind": kind, "total": total, "limit": limit, "offset": offset,
            "items": items}


async def _resolve_streamer(kind: str, streamer: str) -> str:
    """配信者の絞り込みを検証する。受けない種別・知らない配信者は400。

    知らない配信者を「該当0件」にしない —— 綴りを1文字間違えただけの人に、素材が無いと
    答えることになる。"""
    streamer = streamer.strip()
    if not streamer:
        return ""
    if "streamer" not in KIND_FILTERS[kind]:
        raise HTTPException(
            status_code=400,
            detail=f"{KIND_LABELS[kind]}は配信者で絞り込めません"
                   "（この種別は配信者ごとに集計していません）。")
    known = {row["unique_id"] for row in
             await asyncio.to_thread(runtime.storage.asset_streamers)}
    if streamer not in known:
        raise HTTPException(status_code=400, detail=f"知らない配信者です: {streamer[:64]}")
    return streamer


def _disk_stats(kind: str, streamer: str) -> tuple:
    """disk源の種別の (名前, 集計) を1回のsnapshot読みで作る。threadで呼ぶ前提。

    集計は走査のときに採ったもの。``streamer`` を指定するとその配信者ぶんだけ、
    指定しなければ全配信者の合計を返す。"""
    scans = runtime.storage.get_asset_scans()
    if kind == KIND_GIFT_ICON:
        rows = _stored_stats(kind, "gift", scans)
        return (_gift_names(scans),
                {asset_id: {SORT_SENDS: row.get("sends"), SORT_COINS: row.get("coins")}
                 for asset_id, row in rows.items()})
    by_owner = _stored_stats(kind, "emote", scans)
    if streamer:
        counts = dict(by_owner.get(streamer) or {})
    else:
        counts = {}
        for owned in by_owner.values():
            for asset_id, uses in (owned or {}).items():
                counts[asset_id] = counts.get(asset_id, 0) + uses
    return {}, {asset_id: {SORT_USES: uses} for asset_id, uses in counts.items()}


@router.get("/api/assets/file")
async def asset_file(kind: str, asset_id: str = Query(alias="id"),
                     download: int = 0) -> Response:
    """素材の実bytes。``download=1`` で人が読めるfile名を付けて添付にする。

    content-typeは中身から決める(``_content_type``)。代わりの画像は返さない ——
    無い素材に絵を返すと、焼き込みで実際に使われた素材と区別が付かなくなる。"""
    _require_kind(kind)
    path = _asset_path(kind, asset_id)

    def _load():
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError:
            logger.warning(
                "素材を読めませんでした: %s", path,
                extra={"event": "http.asset_read_failed",
                       "ctx": {"kind": kind, "id": asset_id, "path": str(path)}},
                exc_info=True,
            )
            return None
        if not data:
            return None
        return data, _content_type(path, data[:16])

    loaded = await asyncio.to_thread(_load)
    if loaded is None:
        raise HTTPException(status_code=404, detail="その素材はありません。")
    content, content_type = loaded
    headers = {"Cache-Control": ASSET_CACHE_CONTROL}
    if download:
        name = await asyncio.to_thread(_display_name, kind, asset_id)
        headers["Content-Disposition"] = _content_disposition(
            _download_name(kind, asset_id, name, content_type))
    return Response(content=content, media_type=content_type, headers=headers)


# ---------------------------------------------------------------------------------------
# まとめてDownload(発券 -> 引き換え)
# ---------------------------------------------------------------------------------------
#
# 2段に分けてあるのは、選んだidをURLへ載せられないためである。avatarのidは40桁hexなので
# 1件41文字、200件で8KBを超えてrequest lineの上限に触れる(431/400)。
#
# POSTでZIPそのものを返す形は採らない。browserがPOSTでfileを受け取るには hidden form +
# iframe になり、**errorがiframeの中に消えて画面が結末を名乗れなくなる**。発券だけをPOSTに
# すればfetchで受けられるので、種別誤り・件数超過・対象0件は普通のJSON errorとして
# showErrorへ載る。引き換えのURLは券1枚ぶんしか無いので長さの問題も消える。


class ArchiveRequest(BaseModel):
    kind: str
    # 省略・空でその種別の全件。全件は選んだ物を持ち回らないので件数の上限を受けない。
    ids: list = Field(default_factory=list)


def _prune_tickets() -> None:
    now = time.time()
    for ticket, entry in list(_tickets.items()):
        if entry["expires_at"] < now:
            del _tickets[ticket]


def _pool_sizes(kind: str) -> dict:
    """poolに実在する素材の {id: byte数}。中身の空いたfileは入らない。threadで呼ぶ前提。

    1件ずつ ``Path.stat()` を呼ばずdirを1度歩くのは、**桁が違う**ためである: avatarの
    全件を1件ずつstatすると実測20秒近く(191,844回)かかるのに対し、``os.scandir`` は
    662,315 entryを2〜5秒で返す(dirent自体がsizeを持つ)。まとめDownloadを押した人が
    「何件・何MBか」を知るまでの待ち時間がそのまま変わる。"""
    sizes: dict = {}
    try:
        entries = list(os.scandir(_pool_dir(kind)))
    except OSError:
        return sizes
    for entry in entries:
        name = entry.name
        stem = name.split(".", 1)[0]
        if name != f"{stem}{POOL_SUFFIX}" or not _valid_id(kind, stem):
            continue
        try:
            size = entry.stat().st_size
        except OSError:
            continue
        if size > 0:
            sizes[stem] = size
    return sizes


def _archive_plan(kind: str, ids: list) -> tuple:
    """ZIPの中身を確定する。``(entries, 件数, byte数)``。threadで呼ぶ前提。

    ``entries`` は ``(拡張子より前のfile名, 実path)`` の並びで、**実体が在る素材だけ**が
    入る。数えるのと並びを作るのを同じ場所で行うのは、発券が名乗った件数とZIPの中身が
    一致することを、実装上の約束ではなく構造で保証するためである(別々に数えると、
    片方だけが条件を変えたときに黙ってずれる)。

    ``ids`` が空なら **その種別の全件**。全件は「diskに在る全件」であって「一覧に出せる
    全件」ではない —— avatarのpoolには users表から辿れないfileが実測42,636件あり(改名等で
    結び付かなくなったもの)、一覧には出せないが**素材としては在る**。それをZIPから外すと、
    summaryが名乗る点数(234,480)とZIPの件数が食い違い、「片付けたら空く容量」に対応する
    ものを取り出す手段が無くなる。名前を引けない鍵は ``<avatar_key>.<ext>`` で名乗る ——
    鍵はその素材の身元そのものなので、捏造ではない。

    拡張子をここで決めないのは :func:`_download_stem` の通り。中身を読む段で付ける。
    """
    sizes = _pool_sizes(kind)
    if kind == KIND_AVATAR:
        names = _avatar_names()
        rows = [(key, names.get(key, "")) for key in (ids or sorted(sizes))]
    else:
        gift_names = _gift_names() if kind == KIND_GIFT_ICON else {}
        keys = ids or sorted(sizes)
        rows = [(key, gift_names.get(int(key), "") if kind == KIND_GIFT_ICON else "")
                for key in keys]
    pool = _pool_dir(kind)
    entries = []
    total = 0
    for asset_id, name in rows:
        size = sizes.get(asset_id, 0)
        if size <= 0:
            continue
        total += size
        entries.append((_download_stem(kind, asset_id, name),
                        pool / f"{asset_id}{POOL_SUFFIX}"))
    return entries, len(entries), total


@router.post("/api/assets/archive")
async def issue_archive_ticket(payload: ArchiveRequest) -> dict:
    """まとめてDownloadする対象を数えて、引換券を1枚出す。ZIPはここでは作らない。

    数えるためにdirを1度歩く(avatar全件なら22万fileのstatで実測2秒弱)。人が押したときに
    しか走らない明示操作なので、この費用は払う —— 代わりに、押した人は始める前に
    「何件・何MBになるか」を知る。

    券は有効期限内なら**何度でも引き換えられる**。538MBの転送は途中で切れることがあり、
    使い切りにすると再試行のたびに選び直しからやり直すことになるためである。
    期限は設定(``asset_archive_ticket_ttl_seconds``)で、切れた券は404になる。"""
    kind = _require_kind(payload.kind)
    requested = [str(item).strip() for item in payload.ids if str(item).strip()]
    limit = int(runtime.settings.get("asset_archive_max_ids"))
    if len(requested) > limit:
        raise HTTPException(
            status_code=400,
            detail=f"一度にまとめられるのは{limit}件までです（選択 {len(requested)}件）。"
                   "件数を減らすか、全件を選んでください。")
    for asset_id in requested:
        if not _valid_id(kind, asset_id):
            # 黙って除かない。除くと、押した件数より少ないZIPが理由なしで出来る。
            raise HTTPException(status_code=400,
                                detail=f"素材のidが不正です: {asset_id[:64]}")
    _entries, count, total_bytes = await asyncio.to_thread(
        _archive_plan, kind, requested)
    if not count:
        raise HTTPException(status_code=404, detail="まとめる素材がありません。")
    _prune_tickets()
    ticket = secrets.token_urlsafe(16)
    expires_at = time.time() + int(runtime.settings.get("asset_archive_ticket_ttl_seconds"))
    # 券が覚えるのは種別と選んだidだけで、解決済みの並び(19万件のpath)は持たない。
    # 全件の券はidも持たず、引き換えのときに解決し直す —— 22万件の名簿をprocessに
    # 数分置くことになるためで、その間に収集が新しい素材を足せばZIPの方が多くなり得る
    # (``count`` は発券した時点の実測である)。
    _tickets[ticket] = {"kind": kind, "ids": requested, "count": count,
                        "bytes": total_bytes, "expires_at": expires_at}
    logger.info(
        "素材のまとめDownloadの引換券を出しました（種別=%s / %d件 / %.1fMB）",
        kind, count, total_bytes / 1e6,
        extra={"event": "http.asset_archive_ticket_issued",
               "ctx": {"kind": kind, "count": count, "bytes": total_bytes,
                       "selected": len(requested)}},
    )
    return {"ticket": ticket, "kind": kind, "count": count, "bytes": total_bytes,
            "expires_at": expires_at}


class _StreamSink:
    """``write`` と ``tell`` だけを持つ、seekできない書き出し先。

    ``zipfile`` はseekできない相手だと、中身のsizeを先に書く形(data descriptorを使わない
    形)へ自動で切り替える。一時fileを作ってから返す形にしないのは、avatar全件が440MBあり、
    その書き出しが終わるまでbrowserに何も届かないためである(押した人には固まったように
    見え、その間diskも倍使う)。"""

    def __init__(self) -> None:
        self._chunks: list = []
        self._pos = 0

    def write(self, data) -> int:
        self._chunks.append(bytes(data))
        self._pos += len(data)
        return len(data)

    def tell(self) -> int:
        return self._pos

    def flush(self) -> None:
        pass

    def take(self) -> bytes:
        out = b"".join(self._chunks)
        self._chunks.clear()
        return out


def _zip_info(name: str, mtime: float) -> zipfile.ZipInfo:
    stamp = time.localtime(max(mtime, _ZIP_EPOCH))
    info = zipfile.ZipInfo(name, stamp[:6])
    # 画像はすでに圧縮済みなので、詰め直しても縮まずCPUだけを使う。
    info.compress_type = zipfile.ZIP_STORED
    return info


def _read_asset(path: Path):
    """(中身, mtime)。読めない・空なら None。

    開いたhandleからmtimeを採るのは、``read_bytes`` と ``stat`` を別々に呼ぶと同じfileを
    2度開くことになるためである(19万件では往復が倍になる)。"""
    try:
        with path.open("rb") as handle:
            data = handle.read()
            mtime = os.fstat(handle.fileno()).st_mtime
    except OSError:
        return None
    return (data, mtime) if data else None


async def _zip_stream(kind: str, entries: list):
    """ZIPを先頭から順に組んで、出来たbytesから流す。

    束(``ARCHIVE_BATCH``)ごとにthreadへ渡す。全件を1回のto_threadで組むと、その間
    event loopが返らない(avatar全件で数分)。束の中のfileは ``ARCHIVE_READ_WORKERS`` 本
    並行で読む(定数のcommentに実測)。読むのは並行、ZIPへ書くのは1本 —— ZipFileは
    thread safeではない。
    """
    sink = _StreamSink()
    archive = zipfile.ZipFile(sink, "w", zipfile.ZIP_STORED, allowZip64=True)
    readers = ThreadPoolExecutor(max_workers=ARCHIVE_READ_WORKERS,
                                 thread_name_prefix="asset-zip")
    skipped = {"count": 0}
    # 同じ名前になった素材は連番で退避する(nicknameは重複し得るし、名前を持たない素材は
    # idで名乗るので普通は衝突しない)。黙って上書きすると、要求した件数より少ないfileが
    # 入ったZIPが出来上がる。
    used: dict = {}

    def _add(batch: list) -> bytes:
        loaded = readers.map(_read_asset, [path for _stem, path in batch])
        for (stem, path), result in zip(batch, loaded):
            if result is None:
                skipped["count"] += 1
                continue
            data, mtime = result
            filename = f"{stem}.{_extension(_content_type(path, data[:16]))}"
            seen = used.get(filename, 0) + 1
            used[filename] = seen
            if seen > 1:
                head, _, ext = filename.rpartition(".")
                filename = f"{head}_{seen}.{ext}"
            archive.writestr(_zip_info(filename, mtime), data)
        return sink.take()

    def _close() -> bytes:
        archive.close()
        return sink.take()

    try:
        for start in range(0, len(entries), ARCHIVE_BATCH):
            chunk = await asyncio.to_thread(_add, entries[start:start + ARCHIVE_BATCH])
            if chunk:
                yield chunk
        yield await asyncio.to_thread(_close)
    finally:
        # 途中でbrowserが切っても(generatorがcloseされる)threadを残さない。
        readers.shutdown(wait=False)
    if skipped["count"]:
        # 握り潰さない。取れなかったのは「収集時に落とせなかった素材」か「消えたfile」で、
        # どちらもZIPの中身が要求より少ないことを意味する。
        logger.warning(
            "素材のまとめDownloadで %d 件を読めずに飛ばしました（種別=%s / 対象=%d件）",
            skipped["count"], kind, len(entries),
            extra={"event": "http.asset_archive_skipped",
                   "ctx": {"kind": kind, "skipped": skipped["count"],
                           "total": len(entries)}},
        )


@router.get("/api/assets/archive/{ticket}")
async def download_archive(ticket: str) -> StreamingResponse:
    """引換券のZIPを流す。

    圧縮しない(``ZIP_STORED``)。中身はPNG/JPEG/WebPで既に圧縮済みなので、詰め直しても
    縮まずCPUだけを使う。一時fileへ書き出してから返さず、先頭から組んだそばから流す。

    期限切れ・知らない券は404にする。画面が「有効期限が切れました。選び直してください」と
    名乗れる形にするためで、券を作り直して黙って続けない —— 選んだ物は画面にしか無く、
    server側で復元すると別の物を渡すことになる。"""
    _prune_tickets()
    entry = _tickets.get(ticket)
    if entry is None:
        raise HTTPException(
            status_code=404, detail="このDownloadの有効期限が切れています。選び直してください。")
    kind = entry["kind"]
    entries, _count, _bytes = await asyncio.to_thread(
        _archive_plan, kind, entry["ids"])
    filename = f"tictok_assets_{kind}_{entry['count']}.zip"
    logger.info(
        "素材のまとめDownloadを開始します（種別=%s / %d件）", kind, len(entries),
        extra={"event": "http.asset_archive_started",
               "ctx": {"kind": kind, "total": len(entries),
                       "ticket_count": entry["count"]}},
    )
    return StreamingResponse(
        _zip_stream(kind, entries),
        media_type="application/zip",
        headers={"Content-Disposition": _content_disposition(filename),
                 "Cache-Control": "no-store"},
    )


def reset_tickets() -> None:
    """発券済みの引換券を捨てる。processを跨がない物なので、testの後始末に使う。"""
    _tickets.clear()
