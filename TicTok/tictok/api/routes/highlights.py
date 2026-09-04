"""TikTok本体のhighlight(LIVE replayの切り抜き)の台帳・突き合わせ・手直し。

highlightは「誰が投げたか」を持たない。こちらは同じ配信を録画し、gift eventをuser付きで
DBに持っている。**highlightが録画のどこから来たのかさえ判れば、その区間のgift eventを
引くだけでgifterが決まる。** 突き合わせは音の指紋で行う(根拠と実測はdoc/HIGHLIGHT_MATCH.md、
algorithm本体は :mod:`tictok.media.highlight_match`)。

highlight 1本は**montage**である。平均6秒のgift演出が10個ほど、複数の録画から繋がれており、
そのすべてがgift地点ではない(実測で10個中3個はgift無し)。よってこの画面が扱う単位は
「highlight 1本」ではなく「highlight = gift演出の列」で、gift演出1つずつに録画上の位置と
gifterが付く。

**置き場は2通り在る**(``layout.highlight_dirs``): 正規の置き場
(``<配信者>/highlights``)と、利用者が現に使っている ``<配信者>/LiveHightlite``。しかも
どちらも work / final の両rootに在り得る。応答は必ず ``root_key`` と ``source_dir`` を
運ぶ —— 置き場が複数ある以上、どこの物かを画面が名乗れなければ利用者は自分が置いたfileへ
戻れない(``tictok.api.routes.clips`` のmodule docstringと同じ約束)。

**投入する口は1つだけである**(``POST /api/highlights/upload``)。画面へmp4をdropすると
そこへ流れ、fileは**正規の置き場**(``layout.highlight_dir``)へ置かれる —— 読む側が置き場を
2通り辿るのに対し、作る側の場所は1つでなければ「自分が置いた物がどこに在るか」を人が
辿れない。投入した後は**同じ口の中で走査まで済ませる**: 台帳の行はfile systemの写しなので、
投入経路ごとに別の載せ方を作ると、そちらだけが走査と違う行を作る。

実体を再生する口は ``GET /api/highlights/{id}/media`` で、行の ``url`` がそれを名乗る。
画面へpathは渡すが、**画面がpathからURLを組み立てることは想定していない** —— 名前を実pathへ
解く口を作れば、そこから任意のdirを名乗れてしまう。

台帳の行はfilesystemの写しであって原本ではない。行を消してもmp4は消さない(外から来た
素材で、こちらが作った成果物ではない)。逆にfileが消えても行は残す —— gift演出には人が確認・
修正した内容が貼り付いており、外付けdriveを挿し忘れた回にそれが消えては困る。

giftの差し替えで画面から受け取るのは **event の id だけ** である。名前や💎を直接受け取る
口を作ると、そこがDBのeventと食い違う入口になる。

== 週ぜんたいの俯瞰(検証) ==

``GET /api/highlights/coverage`` だけは**主語がgiftである**。1本ずつの照合結果は「この
highlightは何から出来ているか」しか言えず、**TikTokが選ばなかったgift**はそこに現れない ——
照合が取りこぼしたのか、そもそもhighlightに無いのかを人が確かめられる面が他に無い。
``hits`` が空の行は隠さない。並ぶのは**対象gifter(週合計1,000🪙)のgiftだけ**で、fileが
作られない人のgiftは母集団に入れない。週の窓も対象gifterの規則もメンション一覧が持ち、
判定は ``store.highlights.highlight_coverage`` の1箇所に在る。

== 書き出し(gifterごとに1本) ==

素材を並べる口の下に、繋いだ成果物を作る口が2つある。``/export/plan`` は結合前の下見で
ffmpegを起こさず、``/export`` はqueueへ投入する。**同じbodyを投げれば、下見の ``groups`` が
そのまま出来上がる**という関係を保つのがこの2つの契約である。

**誰が対象かをここで判定しない。** 週の境界(土曜7時〜次の土曜7時)も1,000💎の閾値も名寄せも
``streamer_mention_week`` に在り、gift演出の選び方と名前は
:func:`tictok.media.highlight_export.plan_exports` に在る。画面へ規則を写させないために、
件数もfile名もServerが名乗る。

出来上がった物を並べるのは ``GET /api/highlights/exports`` で、置き場
(``layout.merged_highlight_dir``)を走査するだけである —— 成果物はDBに行を持たず、台帳は
file systemそのものだからである(``tictok.api.routes.clips`` と同じ立場)。**配信は自分で
しない**。実体は成果物の置き場に在るので、既に在る ``/api/clips/file`` へURLを組む。
"""

import asyncio
import filecmp
import json
import ntpath
import os
import posixpath
import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from tictok.api import files, media_jobs, runtime
from tictok.api.routes import clips
from tictok.core import layout
from tictok.media import highlight_export, highlight_frames, highlight_match
from tictok.media import hls_source
from tictok.media.clipper import parse_clip_name
from tictok.store.highlights import (gift_position, HIGHLIGHT_EXTENSIONS,
                                     HIGHLIGHT_STATUS_MATCHED,
                                     HIGHLIGHT_STATUS_MISSING)
from tictok.store.streamers import week_folder_choices

router = APIRouter()

# 差し替え候補を拾うときに、gift演出のmedia窓の前後へどれだけ広げるか(秒)。既定を25秒に
# しているのは、gift演出が平均6秒で、アニメはgiftから遅れて立ち上がり十数秒続くためである
# (doc/HIGHLIGHT_MATCH.md)。窓の外のgiftはそのgift演出とは無関係になる。
DEFAULT_CANDIDATE_SPAN_SECONDS = 25.0
MAX_CANDIDATE_SPAN_SECONDS = 600.0

# 録画の窓からgift eventを引くときの余白(秒)。捕捉の開始/終了と配信の境目はぴったり
# 一致しないので、両端を少しだけ広げてから時間軸へ載せ、載った結果で絞る。
_GIFT_WINDOW_MARGIN_SECONDS = 60.0

# highlightを配信するときのContent-Type。台帳に載せるのはmp4だけ
# (``store.highlights.HIGHLIGHT_EXTENSIONS``)なので、拡張子で分岐する理由が無い。
HIGHLIGHT_MEDIA_TYPE = "video/mp4"

# 代表frameのContent-Type。切り出す側(``media.highlight_frames``)がjpegしか作らない。
FRAME_MEDIA_TYPE = "image/jpeg"

# 投入されたbytesを一時fileへ流すときの1回ぶん。highlightは実測で数MB〜数十MBあるので、
# 丸ごとmemoryへ載せずにこの大きさで書き出す。
UPLOAD_CHUNK_BYTES = 1024 * 1024

# 書き終わるまでの仮の名前。**走査が見るのは ``HIGHLIGHT_EXTENSIONS`` だけ**なので、
# この名前で置いてある間は台帳に載らない —— 途中で切れた半端なmp4が「新しいhighlight」
# として並び、照合に回されることが無い。
UPLOAD_TEMP_PREFIX = ".upload_"
UPLOAD_TEMP_SUFFIX = ".part"

# 同名で中身の違うfileへ別名を付けるときに試す上限。番号を無限に試すと、置き場が壊れて
# いるときにloopから戻らない。
UPLOAD_ALT_NAME_LIMIT = 1000

# 画面へ出す「作れる週のfolder」の候補数(今週から遡って)。素材を入れるのは直近の週なので、
# 遡り過ぎると選ぶ方が手間になる。**作れるのはこの候補の名前だけ**である —— 任意の名前で
# dirを作れる口にすると、置き場の下に走査が二度と辿らない名前のfolderが増える。
WEEK_FOLDER_CHOICES = 8

# 書き出し済みの成果物を配信する口のroot key。**綴りをここへ書き写さない** ——
# 置き場(``layout.merged_highlight_dir``)は work root 固定で、その root を ``work`` と
# 名付けているのは配信する側(``clips.ROOT_KEYS``)である。書き写すと、あちらが名前を
# 変えた日にこの一覧のURLだけが誰も配信しない場所を指す(押しても400になる)。
EXPORT_ROOT_KEY = clips.ROOT_KEYS[0]


class HighlightScanRequest(BaseModel):
    streamer: Optional[str] = None


class HighlightFolderRequest(BaseModel):
    """素材を仕分ける週のfolderを作る指定。

    受けるのは配信者と**Serverが名乗った候補の名前**だけである。pathも親のfolderも
    受けないのは、そこから任意のdirを作れる口になるためで、作る場所は投入先
    (``layout.highlight_dir``)の直下に固定されている。"""

    model_config = ConfigDict(extra="forbid")

    streamer: Optional[str] = None
    name: Optional[str] = None


class HighlightMatchRequest(BaseModel):
    """照合の設定。**既定値はここに持たない。**

    未指定(None)の項目はそのまま落とし、``highlight_match.match_highlight`` の署名にある
    既定が使われる。ここへ既定を書き写すと、実際に使われる値と2箇所に分かれる。"""

    # 知らないfieldは受け取らずに弾く。黙って捨てると、画面が送った値が何事も無く
    # 消えたまま「指定したはずの条件と違う結果」が出る(出力側と同じ約束)。
    model_config = ConfigDict(extra="forbid")

    days: Optional[float] = None
    scope: Optional[str] = None
    gift_lead: Optional[float] = None
    gift_tail: Optional[float] = None
    min_diamonds: Optional[int] = None
    window: Optional[float] = None
    hop: Optional[float] = None


class CoverageCheckRequest(BaseModel):
    """検証の面の「確認済み」の印。**受け取るのは event の id と真偽値だけ。**

    印はgift event 1件ごとで、gift演出にもgift行にも紐づかない —— highlightに1本も出ていない
    giftにも押せることが要件で(そこがこの面の一番の用途)、その行はgift演出もgift行も持たない。

    idを**listで受ける**のは、表の1行が複数のeventを畳むためである(同じ人が同じgiftを
    同じgift演出へ連投した数件は1行になる)。1件ずつ往復させると、途中で失敗した行が
    「半分だけ確認済み」という、checkboxで表せない状態になる。
    """

    model_config = ConfigDict(extra="forbid")

    gift_event_ids: list[int] = Field(min_length=1)
    checked: bool


class HighlightSegmentPatch(BaseModel):
    """gift演出1件の手直し。**giftはここでは触らない。**

    gift演出1つが複数のgiftを持つので、gift 1件の付け替え・除外は
    ``/segments/{id}/gifts`` の2つの口が受ける。単数の ``gift_event_id`` をここへ残すと
    「gift演出のgift」という概念が戻り、実測で別人の名前が付いた形(高額な1件が範囲内の1件を
    押しのける)へ逆戻りする。"""

    model_config = ConfigDict(extra="forbid")

    start: Optional[float] = None
    end: Optional[float] = None
    approved: Optional[bool] = None
    excluded: Optional[bool] = None
    memo: Optional[str] = None


class HighlightGiftAdd(BaseModel):
    """gift演出へgiftを1件足す。受け取るのは **event の id だけ**。

    名前や💎を受け取る口を作ると、そこがDBのeventと食い違う入口になる。"""

    model_config = ConfigDict(extra="forbid")

    gift_event_id: int


class HighlightGiftPatch(BaseModel):
    """gift 1件の人の印と、**このgiftだけの切り出し範囲**。

    ``excluded`` はこのgift 1件だけを出力から外す(gift演出ごとではない)。``is_primary`` は
    gift演出の主を指し直す。

    ``chosen`` は「このgiftはこの1本を使う」という選択で、**同じgiftが当たっている他の
    highlightの行からは自動で落ちる**(同じ ``gift_event_id`` の中で1行だけ立つ)。
    ``is_primary`` が1つのgift演出の中の順位なのに対し、こちらはhighlightどうしの選択である。
    書き出しの重複排除も検証tabの代表行も、この印を他のどの順位よりも先に読む。

    ``cut_start``/``cut_end`` はこのgiftを切り出す範囲(highlight自身の時間軸の秒)で、
    **2つ揃えて**送る。1つのgift演出に別人のgiftが複数入るので(実測で6.0秒のgift演出に3人)、
    範囲がgift演出単位だと、1人の行で詰めた値が他の2人のfileまで動かす。

    ``cut_clear`` を立てると範囲を捨ててgift演出の窓へ戻る。``cut_start`` に null を送る形に
    しないのは、``exclude_unset`` で「送っていない」と「nullを送った」を区別する作りだと、
    JSONを組む側の取り違えが**黙って範囲を消す**操作になるためである。"""

    model_config = ConfigDict(extra="forbid")

    excluded: Optional[bool] = None
    is_primary: Optional[bool] = None
    chosen: Optional[bool] = None
    cut_start: Optional[float] = None
    cut_end: Optional[float] = None
    cut_clear: Optional[bool] = None


def _require_highlight(highlight_id: int) -> dict:
    highlight = runtime.storage.get_highlight(highlight_id)
    if highlight is None:
        raise HTTPException(status_code=404, detail="highlightが見つかりません。")
    return highlight


def _require_segment(highlight_id: int, segment_id: int) -> dict:
    segment = runtime.storage.get_highlight_segment(highlight_id, segment_id)
    if segment is None:
        raise HTTPException(status_code=404, detail="このgift演出は見つかりません。")
    return segment


def _gift_media_times(recording: dict, events: list) -> dict:
    """``{event_id: 録画のmedia軸の秒}``。

    ``time - started_at`` を自分で引いてはいけない。録画の時間軸は配信のmedia PTSで、捕捉の
    壁時計とは開始latency・再接続の穴のぶんずれ続ける。

    軸の作り方は :func:`highlight_match.time_mapper` をそのまま使う。gift演出の ``media_start``
    はあちらが出した秒なので、こちらが同じ材料で自前に組み直すと、いつか片方だけが直されて
    候補の秒とgift演出の秒が別の軸に載る(そうなっても数字は出るので、誰も気付かない)。"""
    path = files._resolved_recording_path(recording)
    to_media = highlight_match.time_mapper(path, recording)
    return {event["gift_event_id"]: float(to_media(event["at"])) for event in events}


def _recording_gift_events(recording: dict) -> tuple:
    """(その録画の窓のgift event, {event_id: media軸の秒})。

    窓は**録画自身の窓**で切る。1つのsessionは録画を複数本束ねる(実測11本)ので、session
    全体から採ると別の録画のgiftが候補に混ざる(doc/HIGHLIGHT_MATCH.md)。"""
    session_id = recording.get("session_id")
    if session_id is None:
        return [], {}
    started_at = float(recording["started_at"])
    span = float(recording.get("duration_seconds") or 0.0)
    ended_at = recording.get("ended_at")
    until = (float(ended_at) if ended_at else started_at + span)
    events = runtime.storage.highlight_gift_events(
        session_id, started_at - _GIFT_WINDOW_MARGIN_SECONDS,
        until + _GIFT_WINDOW_MARGIN_SECONDS)
    if not events:
        return [], {}
    return events, _gift_media_times(recording, events)


def _gift_payload(event: dict, media_time: float, media_start: Optional[float]) -> dict:
    """候補1件を画面の形へ。

    ``gift_image`` はproxy経由のURLに解決して返す。eventが持つCDN URLはそのまま渡さない ——
    署名付きで失効するため、画面が直に引くと時間の経った候補だけicon が出なくなる
    (解決できなければ空文字。代わりの絵は出さない)。"""
    return {
        "event_id": event["gift_event_id"],
        "gift_id": event["gift_id"],
        "gift_name": event["gift_name"],
        "diamonds": event["diamonds"],
        "gift_image": runtime.gift_icon_url(
            int(event["gift_id"]) if event["gift_id"] else 0,
            event.get("gift_image") or ""),
        "user_nickname": event["user_nickname"],
        "user_unique_id": event["user_unique_id"],
        "identity_key": event["identity_key"],
        "media_time": round(media_time, 3),
        # gift演出の何秒目か。gift演出の頭が判らない(録画が当たっていない)ならNone。
        "at": (round(media_time - media_start, 3) if media_start is not None else None),
    }


def _with_url(item: dict) -> dict:
    """行へ再生URLを添える。実体が無ければ ``url`` は None。

    画面がpathからURLを組み立てる形にはしない。client由来の名前を実pathへ解く口を作ると、
    そこから任意のdirを名乗れてしまう(``tictok.api.routes.clips`` が既に持っている方針)。
    **Serverが名乗り、画面はそれをそのまま使う。** 出せないときにNoneを返すのは、画面が
    「再生できない」と言えるようにするためで、押しても404になるbuttonを出さないためである。
    """
    playable = bool(item.get("path")) and item.get("status") != HIGHLIGHT_STATUS_MISSING
    return {**item,
            "url": f"/api/highlights/{item['id']}/media" if playable else None}


def _segment_payload(highlight_id: int, segment: dict) -> dict:
    """gift演出1件を画面の形へ。giftのiconと代表frameのURLを添える。

    **giftは複数ある。** gift演出の絵はgift演出の頭ではなく **giftの位置**(``gift["at"]``)で採る
    —— giftはgift演出の頭に在るとは限らず、頭で採ると全部の行が同じような絵になり、しかも
    「だいたい合っている」ので誰も気付かない。giftを持たないgift演出だけ、gift演出の頭を採る
    (そこに他に指せる点が無く、`` at `` を名乗らないので画面も推測しない)。

    録画側のURLも併せて返す。highlight側の絵だけでは「そのgift演出に何が映っているか」しか
    判らず、**当たっているか**は録画の同じ瞬間と並べて初めて見える。
    """
    has_recording = segment["recording_id"] is not None
    gifts = []
    for gift in segment.get("gifts") or []:
        gift_id = gift.get("gift_id")
        gifts.append({
            **gift,
            # eventが運んできたCDN URLはそのまま渡さない —— 署名付きで失効するため、
            # 画面が直に引くと古い照合結果だけiconが出ない。
            "gift_image": runtime.gift_icon_url(
                int(gift_id) if gift_id else 0, gift.get("gift_image") or ""),
            "frame_url": highlight_frame_url(highlight_id, gift["at"]),
            "recording_frame_url": (
                segment_frame_url(highlight_id, segment["id"], gift["at"])
                if has_recording else None),
        })
    primary = next((gift for gift in gifts if gift["is_primary"]), None)
    at = primary["at"] if primary else (
        gifts[0]["at"] if gifts else round(float(segment["start"]), 3))
    return {
        **segment,
        "gifts": gifts,
        "primary": primary,
        "frame_url": highlight_frame_url(highlight_id, at),
        "recording_frame_url": (segment_frame_url(highlight_id, segment["id"], at)
                                if has_recording else None),
    }


def _folders(streamer: str = "") -> list:
    """置き場と、その下のsubfolderを1件ずつ。file systemを歩いて**在る物だけ**を名乗る。

    ``place`` は抱えている置き場の名乗り、``name`` はその置き場から見た相対
    (置き場そのものは空文字)。画面はこの2つで棚の見出しを組む —— 名前を
    ``source_dir`` から切り出させると、置き場の綴りを画面が知ることになる。
    """
    streamers = [streamer] if streamer else layout.highlight_streamers()
    out: list = []
    for unique_id in streamers:
        for base in layout.highlight_dirs(unique_id):
            root_key = layout.root_key_of(base)
            place = layout.source_dir_of(base, root_key)
            for path in [base, *layout.highlight_subdirs(base)]:
                out.append({
                    "unique_id": unique_id,
                    "root_key": root_key,
                    "source_dir": layout.source_dir_of(path, root_key),
                    "place": place,
                    "name": "" if path == base else path.relative_to(base).as_posix(),
                    "path": str(path),
                })
    return out


@router.get("/api/highlights")
async def list_highlights_api(streamer: str = "", status: str = "") -> dict:
    """台帳の一覧。gift演出の集計(件数・gift付き・最高額・合計)と、Serverの既定値を添える。

    集計から除外済みのgift演出は外してある —— 一覧の読みどころは「出力に入るのは何件で
    幾らぶんか」であって、消し込んだ物まで含む総数ではない。

    ``defaults`` は**照合側と出力側を分けて**返す。両方に ``min_diamonds`` が在り、意味が
    違うためである(照合側は「gift窓を張る候補の下限」= 探す範囲、出力側は「出来上がりの
    1本へ載せる下限」= 成果物の中身)。平らに混ぜると、画面はどちらの下限を出しているのか
    言えなくなる。値は**必ずmodule側の ``defaults()`` から引く** —— route側で数字を書き写すと、
    設定画面で変えた値がそこを素通りする。

    ``folders`` は置き場と、その下のsubfolder(``layout.highlight_subdirs``)。**在る物を
    そのまま名乗る**(まだ1本も入っていないfolderも含む) —— どれを棚として出すかは画面の
    見せ方の判断で、Serverが先に間引くと、画面はもう「在るのに空だ」と言えなくなる
    (今の一覧は中身も子孫も無い棚を出さない)。``place``/``name`` で入れ子の親子が判るので、
    画面はpathを切らずに段を組める。行の ``source_dir`` と同じ綴りで名乗る
    (``layout.source_dir_of`` が唯一の持ち主)ので、画面はpathを組み立てずにfolderと行を
    突き合わせられる。

    ``extensions`` は受け取れる拡張子。画面がfolderごとdropされた中身を絞るために要る
    —— 綴りを画面へ書き写すと、Serverが受ける拡張子と2箇所に分かれ、絞られて届かない
    fileが出た日にどちらが本当か読めない。

    ``week_folders`` は素材を仕分ける**週のfolderの候補**(名前と窓の名乗り)。週の境目は
    土曜の朝7時で、``streamer_mention_week`` と同じ ``WEEK_START_HOUR`` から出る。
    画面へ日付を組ませないためにServerが名乗る —— 画面側で組むと、対象の週(検証・出力の
    面)と1日ずれた名前のfolderが静かに増える。

    ``upload_dirs`` は配信者ごとの**投入先**(``layout.highlight_dir``)。dropの受け皿が、
    落とす前に「どこへ入るのか」を名乗るために要る。**画面にpathを組み立てさせない**ため
    Serverが名乗る —— 置き場の決まりが変わった日に、画面だけが実在しない場所を名乗る
    (しかも投入は成功するので、名乗りが嘘であることに誰も気付かない)。行に現れる配信者
    ぶんだけ返す(pathの計算だけで、file systemは見ない)。
    """
    def _collect() -> dict:
        items = [_with_url(item)
                 for item in runtime.storage.list_highlights(streamer, status)]
        return {"items": items,
                "defaults": {"match": highlight_match.defaults(),
                             "export": highlight_export.defaults()},
                "folders": _folders(streamer),
                "extensions": sorted(HIGHLIGHT_EXTENSIONS),
                "week_folders": week_folder_choices(WEEK_FOLDER_CHOICES),
                "upload_dirs": {unique_id: str(layout.highlight_dir(unique_id))
                                for unique_id in
                                {item["unique_id"] for item in items if item["unique_id"]}}}

    return await asyncio.to_thread(_collect)


@router.get("/api/highlights/{highlight_id}/media")
async def highlight_media(highlight_id: int) -> FileResponse:
    """highlightの実体をそのまま配信する。FileResponseはRangeを解するのでseekできる。

    範囲指定(``?start=&end=``)は受けない。gift演出の位置決めはplayer側のseekでやる —— gift演出は
    平均6秒で、切り出しを挟むより頭出しの方が速く、成果物も残さない。

    pathを引数で受けないのは意図的である。行のidだけを受け、実pathは台帳から引く
    (``/api/clips/file`` がrootとname を検証してから開くのと同じ約束を、id 1つで満たす)。"""
    highlight = await asyncio.to_thread(_require_highlight, highlight_id)
    path = Path(highlight["path"])
    if not await asyncio.to_thread(path.is_file):
        raise HTTPException(
            status_code=404,
            detail=f"highlightのfileがありません: {highlight['filename']}")
    return FileResponse(path, media_type=HIGHLIGHT_MEDIA_TYPE,
                        filename=highlight["filename"],
                        headers={"Cache-Control": "no-store"})


@router.get("/api/highlights/coverage")
async def highlight_coverage_api(streamer: str = "", week: str = "",
                                 min_diamonds: Optional[int] = None) -> dict:
    """その週のgiftを1件ずつ並べ、highlightのどこに現れたかを添える(検証の面)。

    **主語はgiftであってhighlightではない。** 1本ずつの照合結果は「このhighlightは何から
    出来ているか」しか言えず、**TikTokが選ばなかったgift**はそこに現れない。突き合わせが
    取りこぼしたのか、そもそもhighlightに無いのかを人が確かめられるのは、週のgiftを全部
    並べて「1本も無い」行を見せるこの面だけである。``hits`` が空の行は隠さない。

    ``min_diamonds`` は **gift 1件あたり**の下限。未指定なら照合側と同じ設定値(98💎)で、
    **0を明示すれば全gift**が並ぶ(未指定と0を同じ扱いにしない)。ただし ``0`` でも
    **対象gifter以外のgiftは並ばない**。対象gifterの下限(週合計1,000🪙)は受け取らない ——
    ``streamer_mention_week`` が持つ規則で、画面からもここからも動かさない。外れた件数は
    ``totals.offtarget`` が名乗る。

    **path の並びに意味がある。** ``/api/highlights/{highlight_id}`` より前に置かないと、
    ``coverage`` がidとして解釈されて422になる(FastAPIは先に宣言したrouteから照合する)。
    """
    unique_id = (streamer or "").strip()
    if not unique_id:
        raise HTTPException(status_code=400,
                            detail="配信者を指定してください（週の窓は配信者ごとです）。")
    if min_diamonds is not None and min_diamonds < 0:
        raise HTTPException(status_code=400,
                            detail="min_diamondsは0以上で指定してください。")
    selected_week = (week or "").strip()

    def _collect() -> dict:
        # 既定値は**照合側と同じ出所**から引く(``highlight_match.defaults``)。route側で
        # 数字を書き写すと、設定画面で変えた値がここだけ素通りする。設定はDBを読むので、
        # 解決もthread側でやる。
        floor = (highlight_match.defaults()["min_diamonds"] if min_diamonds is None
                 else int(min_diamonds))
        result = runtime.storage.highlight_coverage(unique_id, selected_week, floor)
        for item in result["items"]:
            # eventが運んできたCDN URLはそのまま渡さない —— 署名付きで失効するため、
            # 画面が直に引くと古いgiftだけiconが出ない(``get_highlight_api`` と同じ規則)。
            item["gift_image"] = runtime.gift_icon_url(
                int(item.get("gift_id") or 0), item.get("gift_image") or "")
            for hit in item["hits"]:
                # 当たりの絵。gift名とgifter名の文字列だけでは「別人のfileへ別人のgiftが
                # 入る」誤りに人が気付けない。位置が出せないgift演出では None のままにして、
                # 画面が壊れた画像箱ではなく「絵なし」を出せるようにする。
                #
                # **秒はgift演出の窓の中へ丸める**(書き出しの下見と同じ関数)。丸めない秒の絵は
                # montageの別のgift演出 —— まったく無関係な場面 —— が映る。ここは人が
                # 「合っている/間違っている」を判定する面なので、無関係な場面を見て
                # 「間違っている」と判断されると正しい照合が捨てられる。丸めたことは
                # ``frame_clamped`` が名乗る(黙って丸めると、その絵が「giftの瞬間」だと
                # 読まれる)。
                frame_at, clamped = highlight_export.clamp_to_segment(
                    hit["at"], hit["segment_start"], hit["segment_end"])
                hit["frame_url"] = highlight_frame_url(hit["highlight_id"], frame_at)
                hit["frame_clamped"] = clamped
        return result

    return await asyncio.to_thread(_collect)


@router.post("/api/highlights/coverage/checks")
async def set_coverage_check_api(payload: CoverageCheckRequest) -> dict:
    """検証の面の「確認済み」の印を付ける/外す。

    **印はgift event 1件ごと**である。gift演出の ``approved`` は使わない —— あちらは
    「このgift演出を確認した」で、highlightに1本も出ていないgift(この面で人が一番確かめる
    相手)はgift演出を持たないため、印を残す場所がそもそも無い。

    **path の並びに意味がある。** ``/api/highlights/{highlight_id}`` を持つ口より前に
    置く(``highlight_coverage_api`` と同じ理由)。
    """
    def _write() -> dict:
        written = runtime.storage.set_highlight_gift_checks(
            payload.gift_event_ids, payload.checked)
        return {"gift_event_ids": written, "checked": payload.checked}

    return await asyncio.to_thread(_write)


def _export_url(base: Path, path: Path) -> str:
    """書き出したmp4を配信するURL。**この口は自分で配信しない。**

    実体は成果物の置き場(``LiveHightlite_マージ済み`` は ``layout.ARTIFACT_DIRNAMES`` に
    在る)なので、配信する口は既に ``/api/clips/file`` が持っている。同じ物を配る口を2つ
    持つと、片方だけがroot外を弾く条件を直した日に、もう片方から任意のdirを名乗れる。

    名前はrootからの相対で、符号化は ``clips`` の組み立てと同じ ``quote`` を通す —— 配信者名
    にもgifterの表示名にも記号・日本語が入るので、生のまま渡すと再生できないfileが出る。

    置き場が一時保存先の外に在ったら**推測しない**。URLの ``root`` はそこを指すので、外に
    在る物へURLを組んでも配信側が弾く。ここで理由を名乗る方が、画面に押せないbuttonが
    並ぶより早く直せる。"""
    try:
        relative = path.relative_to(base)
    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail=(f"書き出しの置き場が一時保存先の外にあります（{path}）。"
                    "この一覧は一時保存先を配信する口へURLを組むため、"
                    "外に在る成果物は再生できません。")) from exc
    return (f"/api/clips/file?root={EXPORT_ROOT_KEY}"
            f"&name={quote(relative.as_posix())}")


def _export_listing(directory: Path) -> tuple:
    """置き場を1度だけ走査して (file名順に並べたmp4のentry, 置き場の全file名) を返す。

    素性のJSONが隣に在るかを1本ずつ ``is_file`` で確かめると、成果物の数だけstatが増える。
    同じ走査で名前は全部手に入るので、隣の有無は名前の集合で判る。

    **並びはfile名順**である。file名の先頭にはその週の順位が入る(``01_``…)ので、名前順が
    そのまま💎の高い順になる。"""
    with os.scandir(directory) as entries:
        found = [entry for entry in entries if entry.is_file()]
    videos = sorted(
        (entry for entry in found
         if entry.name.lower().endswith(highlight_export.STORY_EXT)),
        key=lambda entry: entry.name)
    return videos, {entry.name for entry in found}


def _export_item(entry, base: Path, names: set) -> dict:
    """書き出し済み1本を画面の形へ。

    素性(週・コイン・順位・表示名)は :func:`tictok.media.clipper.parse_clip_name` だけが
    読み戻す。**file名をここで分解しない** —— 名前の規約が変わった日に、一覧だけが古い
    読み方のまま「それらしい値」を出し続ける。読めない名前は推測せず空のまま並べる
    (検証用の出力は ``_story`` で終わらないので、必ずそちらへ落ちる)。

    ``verified`` はfile名の印で決める。素性のJSONにも同じ真偽が入っているが、あれは隣に
    在るだけの別fileで、mp4を1本だけ運べば付いて行かない(``highlight_export`` の
    :data:`~tictok.media.highlight_export.UNVERIFIED_MARK` の項)。判定は書き出す側の
    ``_require_marked_name`` と同じ形にする。"""
    path = Path(entry.path)
    stat = entry.stat()
    parsed = parse_clip_name(entry.name) or {}
    unverified = (highlight_export.UNVERIFIED_MARK + highlight_export.STORY_EXT
                  in entry.name)
    return {
        "filename": entry.name,
        "path": str(path),
        "bytes": stat.st_size,
        "modified_at": stat.st_mtime,
        "url": _export_url(base, path),
        "week": parsed.get("week") or "",
        "coin": parsed.get("coin"),
        "position": parsed.get("position"),
        "nickname": parsed.get("label") or "",
        "verified": not unverified,
        # 素性のJSONが隣に在るか。無い1本は「誰のどのgiftから出来たか」を辿れないので、
        # 画面がその旨を出せるように名乗る(在るかどうかだけで、中身はここでは読まない)。
        "provenance": highlight_export.provenance_path(path).name in names,
    }


@router.get("/api/highlights/exports")
async def list_highlight_exports_api(streamer: str = "", week: str = "") -> dict:
    """その配信者の**書き出し済みのmp4**を並べる(出力の面が成果物を再生するための一覧)。

    画面はここまで「何が出来るか」(``/export/plan``)と「作れ」(``/export``)しか持たず、
    出来上がった1本を人が観る手立てが無かった。成果物はDBに行を持たず、台帳は
    file systemそのもの(``layout.merged_highlight_dir``)なので、一覧もそこを走査して名乗る。

    ``week`` を渡すとその週だけに絞る。絞りは**file名の週**で行い、素性のJSONは読まない ——
    件数ぶんのfileを開くことになるうえ、名前と素性が食い違ったfileだけが一覧から消える
    (消えた理由は画面からは見えない)。

    置き場が無いときは404にしない。まだ1本も書き出していないだけで、失敗ではない。
    ``exists`` で名乗れば、画面は「0件」と「置き場が無い」を言い分けられる。

    file systemのstatは全てthread側で行う。一覧は数十本になり、loop上でstatすると
    その間serverが止まる(``list_clips_api`` と同じ約束)。

    **path の並びに意味がある。** ``/api/highlights/{highlight_id}`` より前に置かないと
    ``exports`` がidとして解釈されて422になる(``highlight_coverage_api`` と同じ理由で、
    FastAPIは先に宣言したrouteから照合する)。
    """
    unique_id = (streamer or "").strip()
    if not unique_id:
        raise HTTPException(status_code=400,
                            detail="配信者を指定してください（置き場は配信者ごとです）。")
    selected_week = (week or "").strip()

    def _collect() -> dict:
        directory = layout.merged_highlight_dir(unique_id)
        # URLのrootと同じ出所からrootを引く(``clips._roots`` はこの並びでkeyを当てる)。
        base = Path(layout.record_roots()[0])
        head = {"streamer": unique_id, "week": selected_week,
                "directory": str(directory), "exists": directory.is_dir()}
        if not head["exists"]:
            return {**head, "items": []}
        videos, names = _export_listing(directory)
        items = [_export_item(entry, base, names) for entry in videos]
        if selected_week:
            items = [item for item in items if item["week"] == selected_week]
        return {**head, "items": items}

    return await asyncio.to_thread(_collect)


@router.get("/api/highlights/exports/provenance")
async def highlight_export_provenance_api(streamer: str = "", filename: str = "") -> dict:
    """書き出し済み1本の素性から、**繋いだ窓の並び**を返す。``{cuts, ...}``。

    一覧(:func:`list_highlight_exports_api`)は素性を読まない ―― 件数ぶんのfileを開く
    ことになるためである。ここは**人が1本を選んで観るとき**にだけ、その1本ぶんを読む。

    画面はこれを章の帯にする。1本のmp4は3〜8個の窓を繋いだもので、繋ぎ目は素性にしか
    残っていない —— container側のchapterは書いていないので、mp4だけを見ても
    「いま何本目の何のgiftを観ているか」は判らない。

    窓の**開始位置は累計で作る**(素性は窓ごとの尺しか持たない)。実測との差は
    ``output.measured`` に残っているが、章の位置には使わない ―― 全体の伸縮を各章へ
    案分すると、当たっている章の位置まで動かすことになる。

    素性が無いfileは404にしない。検証用の書き出しでも素材が消えた後でもmp4は再生できる
    ので、**章が出せないだけ**である(``provenance`` で名乗る)。
    """
    unique_id = (streamer or "").strip()
    name = (filename or "").strip()
    if not unique_id or not name:
        raise HTTPException(status_code=400,
                            detail="配信者とfile名を指定してください。")
    if name != Path(name).name or name != ntpath.basename(name):
        raise HTTPException(status_code=400, detail=f"file名が不正です: {filename}")

    def _read() -> dict:
        directory = layout.merged_highlight_dir(unique_id)
        target = directory / name
        if not target.is_file():
            raise HTTPException(status_code=404, detail=f"fileがありません: {name}")
        sidecar = highlight_export.provenance_path(target)
        try:
            record = json.loads(sidecar.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"provenance": False, "cuts": []}
        except ValueError as exc:
            # 壊れた素性は「無い」で済ませない。**mp4は在るのに出所が読めない**という
            # 状態そのものが、この記録を作る理由になった事故である。
            raise HTTPException(
                status_code=500,
                detail=f"素性のJSONが壊れています（{sidecar.name}）: {exc}") from exc
        except OSError as exc:
            # OSErrorの文言にはpathが載る。file名は既に名乗っているので、内部の置き場を
            # そのまま外へ出さない(理由の種類だけを渡す)。
            runtime.logger.warning("素性のJSONが読めませんでした: %s", sidecar,
                                   exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"素性のJSONが読めません（{sidecar.name} / "
                       f"{type(exc).__name__}）。") from exc
        if not isinstance(record, dict):
            raise HTTPException(
                status_code=500, detail=f"素性のJSONの形が違います（{sidecar.name}）。")
        cuts = []
        at = 0.0
        for index, cut in enumerate(record.get("cuts") or []):
            seconds = float(cut.get("seconds") or 0.0)
            cuts.append({
                "index": index,
                "at": round(at, 3),
                "seconds": round(seconds, 3),
                "highlight_id": cut.get("highlight_id"),
                "src": Path(str(cut.get("src") or "")).name,
                "diamonds": cut.get("diamonds"),
                "start": cut.get("start"), "end": cut.get("end"),
                "gifts": cut.get("gifts") or [],
            })
            at += seconds
        return {"provenance": True, "cuts": cuts,
                "seconds": round(at, 3),
                "verified": bool(record.get("verified")),
                "week": record.get("week") or "",
                "nickname": (record.get("gifter") or {}).get("nickname") or ""}

    return {"streamer": unique_id, "filename": name,
            **await asyncio.to_thread(_read)}


def highlight_frame_url(highlight_id: int, at: Optional[float],
                        width: Optional[int] = None) -> Optional[str]:
    """代表frameのURL。位置が出せないなら **None**(画面は絵を出さない)。

    **URLを組み立てる場所はここ1つにする。** 同じ組み立てが2箇所に在ると、片方だけが
    引数を足した日に、一方の面だけ絵が出なくなる(しかも404は画面には壊れた画像箱としてしか
    見えない)。giftのiconを :func:`runtime.gift_icon_url` に一本化してあるのと同じ約束で、
    書き出しの下見も検証の面もこの関数を呼ぶ。

    ``at`` が None のときにそれらしい秒(gift演出の頭など)で埋めない —— 位置が判っていない
    ことと、判っていて0秒であることは別である。"""
    if at is None:
        return None
    url = f"/api/highlights/{highlight_id}/frame?at={float(at):.3f}"
    return f"{url}&w={int(width)}" if width else url


def segment_frame_url(highlight_id: int, segment_id: int, at: Optional[float],
                      width: Optional[int] = None) -> Optional[str]:
    """そのgift演出が指す**録画**の同じ瞬間のframeのURL。出せないなら None。

    ``at`` は :func:`highlight_frame_url` と**同じ軸**(highlight自身の秒)である。2つのURLへ
    同じ ``at`` を渡せば同じ瞬間の2枚が並ぶ —— 片方をmedia秒で組む形にすると、それらしい
    別の場面が並んで「一致している」ように見える。"""
    if at is None:
        return None
    url = (f"/api/highlights/{highlight_id}/segments/{segment_id}"
           f"/frame?at={float(at):.3f}")
    return f"{url}&w={int(width)}" if width else url


def _frame_response(path: Path) -> FileResponse:
    """切り出したframeを返す。

    素材(highlightのmp4・finalize済みの録画)は不変なので、browserに持たせてよい。一覧には
    20〜60枚が並ぶので、scrollのたびに引き直させるとその数だけffmpegが起きる。**唯一の
    ずれる余地**は、利用者が同じfile名でhighlightを置き直したときにmax-ageのあいだ古い絵が
    残ることである(cacheのfile名はbytesとmtimeを含むので、server側は取り違えない)。"""
    return FileResponse(
        path, media_type=FRAME_MEDIA_TYPE,
        headers={"Cache-Control":
                 f"private, max-age={runtime.RECORDING_CACHE_MAX_AGE_SECONDS}"})


@router.get("/api/highlights/{highlight_id}/frame")
async def highlight_frame_api(highlight_id: int, at: float,
                              w: Optional[int] = None) -> FileResponse:
    """highlightの ``at`` 秒の1 frame(jpeg)。

    照合の結果として画面に並ぶのはgift名とgifterの**文字列だけ**で、実際に「別人のfileへ
    別人のgiftが入る」誤りが起きた。**行に鹿が映っていて名前が「Goal Highlight」なら人は
    一目で気付ける。** 検証の面・gift演出の表・書き出しの下見が同じ1枚を並べられるように、
    口はここ1つにする(画面はffmpegを呼べない)。

    ``at`` は**highlight自身の時間軸の秒**である。録画のmedia秒を渡してはいけない ——
    それらしい別の場面が出るだけで、絵は出るので誰も気付かない。

    尺を超えた ``at`` は **404** にする。手前へ丸めて最後のframeを返すと、範囲外を指した
    ことが画面から見えなくなる(丸めた絵は「その位置の絵」として並ぶ)。
    """
    if at < 0:
        raise HTTPException(status_code=400, detail="atは0以上で指定してください。")
    try:
        width = highlight_frames.normalize_width(w)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    highlight = await asyncio.to_thread(_require_highlight, highlight_id)
    path = Path(highlight["path"])
    if not await asyncio.to_thread(path.is_file):
        raise HTTPException(
            status_code=404,
            detail=f"highlightのfileがありません: {highlight['filename']}")
    try:
        frame = await asyncio.to_thread(
            highlight_frames.highlight_frame, path, at, width)
    except highlight_frames.FrameUnavailable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _frame_response(frame)


@router.get("/api/highlights/{highlight_id}/thumbnails")
async def highlight_thumbnails_api(highlight_id: int) -> dict:
    """時間軸へ敷くfilmstrip(sprite sheet)の仕様。

    **hoverの1枚(``/frame``)とは役目が違う。** あちらは指した秒に何が映っているかを1枚で
    答える口で、こちらは軸そのものを絵で埋めて「どこで場面が変わるか」を目で追わせる物で
    ある。1枚ずつ敷くと軸1本に数十のHTTP往復が要るので、録画側と同じくsheetにする。

    highlightは実測6〜61秒なので初回でも1秒前後で焼ける。2回目以降はcache hitで即返る。"""
    highlight = await asyncio.to_thread(_require_highlight, highlight_id)
    path = Path(highlight["path"])
    if not await asyncio.to_thread(path.is_file):
        raise HTTPException(
            status_code=404,
            detail=f"highlightのfileがありません: {highlight['filename']}")
    try:
        spec = await asyncio.to_thread(highlight_frames.highlight_strip, path)
    except highlight_frames.FrameUnavailable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    sheet, _meta = highlight_frames.strip_paths(path)
    spec["highlight_id"] = highlight_id
    # URLへsheetの鍵(素材のbytesとmtimeを含む)を混ぜる。idだけのURLにすると、利用者が同じ
    # 名前でhighlightを置き直したとき、browserのcacheが**古い絵を新しい仕様で**読む ――
    # 画面はtileの番号からしか秒を知らないので、絵と秒が黙ってずれる。
    spec["url"] = f"/api/highlights/{highlight_id}/thumbnails.jpg?v={sheet.stem}"
    return spec


@router.get("/api/highlights/{highlight_id}/thumbnails.jpg")
async def highlight_thumbnails_image(highlight_id: int) -> FileResponse:
    """焼いてあるsprite sheetそのもの。無ければ **404**(仕様の口が先である)。"""
    highlight = await asyncio.to_thread(_require_highlight, highlight_id)
    sheet, _meta = highlight_frames.strip_paths(Path(highlight["path"]))
    if not await asyncio.to_thread(sheet.is_file):
        raise HTTPException(status_code=404, detail="filmstripが未生成です。")
    return _frame_response(sheet)


@router.get("/api/highlights/{highlight_id}/segments/{segment_id}/frame")
async def highlight_segment_recording_frame_api(
    highlight_id: int, segment_id: int, at: float, w: Optional[int] = None,
) -> FileResponse:
    """そのgift演出が指す**録画**の、同じ瞬間の1 frame(jpeg)。

    highlight側の1枚と並べて「同じ場面か」を人が確かめるための口である。突き合わせが
    当たっているかは、結局そこでしか判らない。

    ``at`` は highlight側と**同じ軸**(highlight自身の秒)で受け、gift演出の ``media_start`` を
    通してmedia軸へ写す。画面に2つの軸を持たせないためで、軸を2つ受ける口にすると、いつか
    片方だけがmedia秒で呼ばれて別の場面が並ぶ。

    録画が当たっていないgift演出は **409**。0件でも空の絵でもなく「そもそも探せない」であり、
    候補の口(``/candidates``)が同じ理由で409を返すのと揃える。
    """
    if at < 0:
        raise HTTPException(status_code=400, detail="atは0以上で指定してください。")
    try:
        width = highlight_frames.normalize_width(w)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    def _resolve() -> tuple:
        _require_highlight(highlight_id)
        segment = _require_segment(highlight_id, segment_id)
        if segment["recording_id"] is None or segment["media_start"] is None:
            raise HTTPException(
                status_code=409,
                detail="このgift演出はまだ録画に当たっていないため、録画のframeを出せません。")
        recording = runtime.storage.get_recording(segment["recording_id"])
        if recording is None:
            raise HTTPException(
                status_code=409, detail="このgift演出が指す録画がありません（削除済み）。")
        source = files._resolved_recording_path(recording)
        media_at = float(segment["media_start"]) + (at - float(segment["start"]))
        return source, media_at

    source, media_at = await asyncio.to_thread(_resolve)
    if media_at < 0:
        raise HTTPException(
            status_code=400,
            detail="その位置は録画の先頭より手前です（gift演出の範囲外を指しています）。")
    try:
        frame = await asyncio.to_thread(
            highlight_frames.recording_frame, source, media_at, width)
    except highlight_frames.FrameUnavailable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except hls_source.SourceMissing as exc:
        raise HTTPException(
            status_code=409,
            detail=f"この録画の素材がありません（{exc}）。") from exc
    return _frame_response(frame)


@router.post("/api/highlights/scan")
async def scan_highlights_api(payload: HighlightScanRequest) -> dict:
    """置き場を走査して行を作る。``{added, updated, missing, dirs}``。

    ``dirs`` は実際に見た置き場。0件だったときに「どこも見ていない」のか「見たが空」なのか
    を画面が言い分けられるようにするために返す(0件を『無い』と断定させない)。"""
    streamer = (payload.streamer or "").strip()
    return await asyncio.to_thread(runtime.storage.scan_highlights, streamer)


class _Rejected(Exception):
    """このfile 1件だけを断る理由。

    **1件の拒否で全部を落とさない。** 画面へ十数本まとめてdropしたときに、mp4でない1本の
    せいで残りが1本も入らないと、利用者は駄目な1本を自分で見つけて取り除くまで何もできない
    (しかもどれが駄目だったかは画面から見えない)。断った1件は理由付きで応答に並べる。"""


def _upload_dir(streamer: str) -> Path:
    """投入先(``layout.highlight_dir``)。無ければ作る。

    **配信者名もclient由来である。** 置き場のpathの一部になるので、解決した後に必ず
    pool root の下に居ることを照合する(``clips._resolve`` と同じ約束)—— ``..`` を名乗られ
    ればrootの外へ書ける。

    投入先を ``highlight_dir`` に固定するのは、読む側(``highlight_dirs``)が旧来の
    ``LiveHightlite`` と両rootも辿るのに対し、**作る側の場所は1つでなければ人が自分の
    置いたfileへ戻れない**からである(module docstring)。"""
    if (streamer in (".", "..") or streamer != posixpath.basename(streamer)
            or streamer != ntpath.basename(streamer)):
        # 台帳のunique_idは必ずfolder名1つぶんである。区切りを含む名前を受けると、rootの
        # 中とはいえ走査が二度と辿らない深さへfileが積まれる(置いた本人にも見えない)。
        raise HTTPException(
            status_code=400,
            detail=f"配信者名にpathの区切りは使えません: {streamer}")
    base = layout.pool_root().resolve()
    target = layout.highlight_dir(streamer).resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"配信者名が置き場の外を指しています: {streamer}") from exc
    target.mkdir(parents=True, exist_ok=True)
    return target


def _highlight_places(streamer: str) -> list:
    """その配信者のhighlightの置き場(実在するもの)を解決済みpathで。

    ``highlight_dir`` は**まだ無くても混ぜる**。投入先は :func:`_upload_dir` が作るので、
    一度も投入していない配信者でも、そこの下のfolderは正しい投入先である。"""
    places = [path.resolve() for path in layout.highlight_dirs(streamer)]
    upload = layout.highlight_dir(streamer).resolve()
    if upload not in places:
        places.append(upload)
    return places


def _resolve_source_dir(streamer: str, root_key: str, source_dir: str) -> Path:
    """一覧が名乗ったfolder(``root_key`` + ``source_dir``)を実pathへ解く。

    **画面からpathを受けない。** 受ければそこから任意のdirを名乗れてしまうので、受けるのは
    一覧の応答が持っていた2つの値だけにして、こちらでrootを当てて組み直す
    (``layout.source_dir_of`` の逆で、綴りの持ち主はやはりlayoutである)。

    解決したpathが**その配信者の置き場の中に居ること**を必ず照合する。名前の見た目だけでは
    足りない —— symlinkやosごとの正規化で、綴りは無害なまま別の場所へ着地し得る。
    置き場の外を指せると、別人のfolderへ投入できる口になる(そのハイライトは「照合で
    当たらないだけ」の形で静かに増え、後から気付く手立てが無い)。"""
    roots = dict(zip(layout.RECORD_ROOT_KEYS, layout.record_roots()))
    root = roots.get(root_key)
    if root is None:
        raise HTTPException(
            status_code=400,
            detail=f"置き場のrootが判りません: {root_key or '(空)'}")
    target = (Path(root) / source_dir).resolve()
    if not any(target == place or place in target.parents
               for place in _highlight_places(streamer)):
        raise HTTPException(
            status_code=400,
            detail=f"{streamer} の置き場の外を指しています: {source_dir}")
    if not target.is_dir():
        raise HTTPException(
            status_code=404,
            detail=f"そのfolderがもうありません: {source_dir}")
    return target


def _upload_name(base: Path, filename: str) -> str:
    """client が名乗ったfile名を、置き場の下の1つの名前として確かめて返す。

    弾くのは3つ。**dir区切り・drive付き・``..``** —— どれも置き場の外を指せる。区切りを
    posixとwindowsの両方で見るのは、Serverがどちらのosで動いていても client は反対側の
    綴りを送れるからである。名前を黙って ``basename`` へ削らないのは、削った結果が利用者の
    知らない名前になるためで、断って名乗る方が早く直せる。

    拡張子は :data:`~tictok.store.highlights.HIGHLIGHT_EXTENSIONS` から引く。ここへ綴りを
    書き写すと、台帳が載せる拡張子と受け取る拡張子が2箇所に分かれる —— 受け取ったのに
    走査が載せないfileが置き場へ増える。

    最後に**解決したpathが置き場の直下に居ることを照合する**。名前の見た目だけでは足りない
    (symlinkやosごとの正規化で、綴りは無害なまま別の場所へ着地し得る)。"""
    raw = (filename or "").strip()
    if not raw:
        raise _Rejected("file名がありません。")
    if raw in (".", "..") or raw != posixpath.basename(raw) or raw != ntpath.basename(raw):
        raise _Rejected(f"置き場の外を指すfile名は扱えません: {raw}")
    if Path(raw).suffix.lower() not in HIGHLIGHT_EXTENSIONS:
        raise _Rejected(
            f"扱えるのは {'・'.join(HIGHLIGHT_EXTENSIONS)} だけです: {raw}")
    if (base / raw).resolve().parent != base:
        raise _Rejected(f"置き場の外を指すfile名は扱えません: {raw}")
    return raw


def _new_upload_temp(base: Path) -> Path:
    """書き込み中のbytesを受ける一時file。**置き場と同じdirへ作る。**

    別のdir(system の temp)へ書くと、別volumeになった時点で rename が跨げず、
    「書き終わってから据える」が copy になる —— 途中で切れた半端なmp4が置き場に残る。"""
    handle, path = tempfile.mkstemp(dir=base, prefix=UPLOAD_TEMP_PREFIX,
                                    suffix=UPLOAD_TEMP_SUFFIX)
    os.close(handle)
    return Path(path)


def _discard_upload_temp(temp: Path) -> None:
    """据えられなかった一時fileを片付ける。無ければ何もしない。"""
    if temp.exists():
        temp.unlink()


async def _write_upload(upload: UploadFile, temp: Path) -> int:
    """受けたbytesを一時fileへ流し込み、書いた量を返す。

    **file I/Oはすべてthread側で行う。** 数十MBの書き込みをevent loop上でやると、その間
    serverは他の誰にも応答しない(loop停止の実例がある)。

    空のfileはここで断る。0 bytesのmp4を置き場へ据えると、走査がそれを新しいhighlightと
    して台帳へ載せ、照合が開けないfileを掴む。"""
    handle = await asyncio.to_thread(open, temp, "wb")
    total = 0
    try:
        while True:
            chunk = await upload.read(UPLOAD_CHUNK_BYTES)
            if not chunk:
                break
            await asyncio.to_thread(handle.write, chunk)
            total += len(chunk)
    finally:
        await asyncio.to_thread(handle.close)
    if total == 0:
        raise _Rejected("中身が空のfileです。")
    return total


def _free_upload_name(base: Path, name: str) -> Path:
    """同名が在るときに使う別名(``<名前>_2.mp4``…)。"""
    stem, suffix = Path(name).stem, Path(name).suffix
    for number in range(2, UPLOAD_ALT_NAME_LIMIT):
        candidate = base / f"{stem}_{number}{suffix}"
        if not candidate.exists():
            return candidate
    raise _Rejected(f"同じ名前のfileが多すぎて別名を付けられません: {name}")


def _store_upload(base: Path, name: str, temp: Path) -> dict:
    """書き終えた一時fileを本来の名前へ据える。``{path, saved, reason}``。

    **既存fileを黙って上書きしない。** 同名が在るときの扱いは中身で分ける:

    * **bytesが同じなら置き換えない。** 同じ物なので台帳の行は1文字も変わらず、置き換えて
      得る物が無い。逆に、投入の途中で切れた側で無事な原本を潰す目が残る。
    * **中身が違うなら別名を付ける**(409で断らない)。断ると、まとめてdropした中の1本だけが
      落ちる形になり、しかも**利用者の手元に断られたfileは戻らない** —— browserのdropは
      その場でfileを渡すだけで、断った物を後から拾い直す道が無い。台帳はfile名で行を作る
      ので、別名のまま2本並べれば人がどちらを使うか選べる。

    どちらを選んだかは ``reason`` が名乗る(黙って捨てるfileも、黙って増える名前も作らない)。

    据える操作は ``os.replace`` の1手である。書き込み中の名前(``UPLOAD_TEMP_PREFIX``)は
    走査の対象外なので、途中で落ちても半端なmp4が台帳へ載ることはない。"""
    target = base / name
    if not target.exists():
        os.replace(temp, target)
        return {"path": target, "saved": True, "reason": ""}
    if filecmp.cmp(temp, target, shallow=False):
        temp.unlink()
        return {"path": target, "saved": False,
                "reason": "同じ内容のfileが既にあるので置き換えませんでした。"}
    alt = _free_upload_name(base, name)
    os.replace(temp, alt)
    return {"path": alt, "saved": True,
            "reason": f"同じ名前で中身の違うfileがあったため、{alt.name} として保存しました。"}


async def _receive_upload(base: Path, upload: UploadFile) -> dict:
    """file 1件を受けて置き場へ据える。結末(1行)を返す。**例外は投げない。**

    1件ごとに独立して結末を出すのがこの口の約束で、ここで投げると残りのfileが道連れになる
    (:class:`_Rejected` の項)。OSError も同じ扱いにする —— 容量切れや権限は「そのfileだけが
    入らなかった」であって、他のfileまで断る理由にはならない。**stack traceはlogへ残す。**"""
    name = upload.filename or ""
    row = {"filename": name, "saved": False, "reason": "", "bytes": None, "path": None}
    try:
        safe = _upload_name(base, name)
    except _Rejected as exc:
        return {**row, "reason": str(exc)}
    temp = await asyncio.to_thread(_new_upload_temp, base)
    try:
        written = await _write_upload(upload, temp)
        placed = await asyncio.to_thread(_store_upload, base, safe, temp)
    except _Rejected as exc:
        await asyncio.to_thread(_discard_upload_temp, temp)
        return {**row, "reason": str(exc)}
    except OSError as exc:
        await asyncio.to_thread(_discard_upload_temp, temp)
        runtime.logger.warning(
            "ハイライトの投入に失敗しました（%s / %s）", name, base, exc_info=True,
            extra={"event": "highlight.upload_failed",
                   "ctx": {"filename": name, "directory": str(base)}})
        return {**row, "reason": f"保存できませんでした: {exc}"}
    return {**row, "saved": placed["saved"], "reason": placed["reason"],
            "bytes": written, "path": str(placed["path"])}


@router.post("/api/highlights/folders")
async def create_highlight_folder_api(payload: HighlightFolderRequest) -> dict:
    """素材を仕分ける**週のfolder**を投入先の下に作る。``{path, source_dir, created}``。

    ここまでは利用者がfile管理画面を開いて手でfolderを作っていた。一覧はそのfolderを棚として
    出し、棚へdropすればそこへ投入できるので、**作る手段だけが画面の外に在った**。

    作る場所は :func:`_upload_dir`(``layout.highlight_dir``)の直下に固定する。読む側
    (``highlight_dirs``)が旧来の置き場と両rootを辿るのに対し、**作る側の場所は1つでなければ
    人が自分の作ったfolderへ戻れない**からで、投入先と同じ約束である(module docstring)。

    **名前はServerが名乗った候補だけを受ける**(:func:`week_folder_choices`)。任意の名前で
    dirを作れる口にすると、置き場の下に走査の辿らない名前のfolderが増えるうえ、週の境目
    (土曜7時)を知らない綴りが混ざって、対象の週と1日ずれたfolderが静かに生まれる。

    既に在るなら作らずに ``created: false`` で返す。409で断らないのは、**利用者の望む結末は
    既に満たされている**からで、断ると「押しても何も起きないbutton」に見える。"""
    unique_id = (payload.streamer or "").strip()
    name = (payload.name or "").strip()
    if not unique_id:
        raise HTTPException(
            status_code=400,
            detail="配信者を指定してください（置き場は配信者ごとなので、作る先が決まりません）。")
    names = {item["name"] for item in week_folder_choices(WEEK_FOLDER_CHOICES)}
    if name not in names:
        raise HTTPException(
            status_code=400,
            detail=f"作れるのは週のfolderだけです（{name or '(空)'} は候補にありません）。")

    def _make() -> dict:
        base = _upload_dir(unique_id)
        target = base / name
        created = not target.is_dir()
        target.mkdir(parents=True, exist_ok=True)
        return {"path": str(target), "created": created,
                "source_dir": layout.source_dir_of(target),
                "root_key": layout.root_key_of(target)}

    result = await asyncio.to_thread(_make)
    runtime.logger.info(
        "ハイライトのfolderを作りました（%s / %s / 新規=%s）",
        unique_id, result["path"], result["created"],
        extra={"event": "highlight.folder_created",
               "ctx": {"streamer": unique_id, "name": name,
                       "path": result["path"], "created": result["created"]}},
    )
    return {"streamer": unique_id, "name": name, **result}


@router.post("/api/highlights/upload")
async def upload_highlights_api(
    streamer: str = Form(""),
    root_key: str = Form(""),
    source_dir: str = Form(""),
    files: list[UploadFile] = File(default_factory=list),
) -> dict:
    """mp4を置き場へ投入し、**そのまま走査して台帳へ載せる**(画面のdropの受け皿)。

    ここまでは利用者が手でfolderへfileを置き、画面の「置き場を走査」を押していた。置き場は
    ``<work root>/<配信者>/highlights`` で、配信者ごとに分かれている —— folderを開いて
    正しい配信者の下へ落とす作業は、毎週の投入のたびに繰り返され、間違えても気付けない
    (別人の置き場に入ったhighlightは、その人の週のgiftと突き合わせられて当たらないだけ)。

    **配信者は必ず受け取る。** 置き場が配信者folderの下に在る以上、配信者が決まらなければ
    投入先が決まらない。推測はしない(400で理由を名乗る) —— 適当な場所へ置くと、上のとおり
    「当たらないhighlight」が静かに増える。

    ``root_key`` / ``source_dir`` を添えると、置き場の下の**そのfolder**へ入る(画面の一覧で
    folderの行へdropした場合)。素材は週ごとに仕分けられており、投入した後に人が手でfileを
    動かしていた —— 一覧には既にその棚が出ているので、そこへ落とせるなら移す手間が丸ごと
    消える。**pathは受けない**: 受けるのは一覧が名乗った2つの値だけで、実pathへ解くのも
    置き場の中に居ることを照合するのも :func:`_resolve_source_dir` が行う。添えなければ
    今までどおり置き場そのもの(``layout.highlight_dir``)である。

    受けるのは :data:`~tictok.store.highlights.HIGHLIGHT_EXTENSIONS` の拡張子だけで、それ
    以外は**その1件だけ**を理由付きで断る(:class:`_Rejected`)。file名はclient由来なので
    :func:`_upload_name` で無害化し、同名の扱いは :func:`_store_upload` が決める。

    **走査までこの口の中で済ませる。** 台帳の行はfile systemの写しであって、投入経路ごとに
    別の載せ方を作ると、そちらだけが走査と違う行を作る。1本も置けなかったときは走査しない
    —— 置き場は何も変わっておらず、走ったという名乗りだけが増える。

    応答は**1件ずつの結末**(``filename`` / ``saved`` / ``reason`` / ``bytes`` / ``path``)を
    並べる。黙って捨てるfileを作らないためで、画面はこれを1行ずつ出す。

    **path の並びに意味がある。** ``/api/highlights/{highlight_id}`` より前に置かないと
    ``upload`` がidとして解釈されて422になる(``highlight_coverage_api`` と同じ理由)。
    """
    unique_id = (streamer or "").strip()
    if not unique_id:
        raise HTTPException(
            status_code=400,
            detail="配信者を指定してください（置き場は配信者ごとなので、投入先が決まりません）。")
    if not files:
        raise HTTPException(status_code=400, detail="投入するfileがありません。")

    folder = (source_dir or "").strip()
    base = (await asyncio.to_thread(_resolve_source_dir, unique_id,
                                    (root_key or "").strip(), folder)
            if folder else await asyncio.to_thread(_upload_dir, unique_id))
    items = [await _receive_upload(base, upload) for upload in files]
    saved = [item for item in items if item["saved"]]
    # 1本も置けていないなら置き場は変わっていない。走査を空打ちすると、画面は「走査した」
    # という名乗りだけを受け取る。
    scan = (await asyncio.to_thread(runtime.storage.scan_highlights, unique_id)
            if saved else None)
    runtime.logger.info(
        "ハイライトを投入しました（%s / 保存 %d件 / 断り %d件 / %s）",
        unique_id, len(saved), len(items) - len(saved), base,
        extra={"event": "highlight.uploaded",
               "ctx": {"streamer": unique_id, "directory": str(base),
                       "saved": len(saved), "rejected": len(items) - len(saved),
                       "filenames": [item["filename"] for item in saved]}},
    )
    return {"streamer": unique_id, "directory": str(base), "items": items,
            "saved": len(saved), "rejected": len(items) - len(saved), "scan": scan}


@router.get("/api/highlights/{highlight_id}")
async def get_highlight_api(highlight_id: int) -> dict:
    """highlight 1本と、そのgift演出すべて(録画の身元付き)。

    giftのiconはproxy経由のURLへ解決して返す。gift演出が持っているのはeventが運んできたCDN URL
    で、署名付きなので時間が経つと失効する —— そのまま渡すと、古い照合結果だけiconが出ない。
    出せないgiftにはURLを付けない(代わりの絵は出さない)。"""
    def _collect() -> dict:
        highlight = _require_highlight(highlight_id)
        segments = [_segment_payload(highlight_id, segment)
                    for segment in runtime.storage.highlight_segments(highlight_id)]
        return {"highlight": _with_url(highlight), "segments": segments}

    return await asyncio.to_thread(_collect)


@router.post("/api/highlights/{highlight_id}/match")
async def match_highlight_api(highlight_id: int, payload: HighlightMatchRequest) -> dict:
    """突き合わせをqueueへ投入する(同期実行はしない)。``{job_id}``。

    実測7.5〜16.3秒で終わるが、その間serverを塞がない。人がその場で待つ種類のjobなので
    即時lane(``media_queue.INSTANT_KINDS``)へ入る —— 通常のlaneに入れると、長い焼き込みの
    後ろで数時間動かない。

    二重投入は行のstatusで弾く。録画idを持たないjobなので、録画ごとの二重投入judge
    (``pending_for``)が使えない。
    """
    highlight = await asyncio.to_thread(_require_highlight, highlight_id)
    if highlight["status"] == "matching":
        raise HTTPException(
            status_code=409,
            detail="このhighlightの突き合わせは既にqueueにあります（jobで確認できます）。")
    path = Path(highlight["path"])
    if not await asyncio.to_thread(path.is_file):
        raise HTTPException(
            status_code=404,
            detail=f"highlightのfileがありません: {highlight['filename']}")
    options = payload.model_dump(exclude_none=True)
    row = await media_jobs._enqueue_media_job(
        "highlight_match",
        stem=f"{highlight['unique_id']} / {highlight['filename']}",
        params={"highlight_id": highlight_id, **options},
        priority=media_jobs.HIGHLIGHT_MATCH_JOB_PRIORITY,
    )
    # 投入した設定を先に書いておく。実行前に取り消された行でも「何をやろうとしたか」が
    # 残る。**指定されなかった項目は既定で埋めてから書く** —— 指定分だけを残すと、
    # 待機中の行のscopeが「下限の指定なし」に見え、実際には設定の98💎が効いているのに
    # 「下限なしで照合される」と読めてしまう。実行が終われば照合が返した実効値で
    # 上書きされるので、ここで埋める値と最終的な値は同じものである。
    await asyncio.to_thread(
        runtime.storage.set_highlight_status, highlight_id, "matching",
        scope={**await asyncio.to_thread(highlight_match.defaults), **options})
    return {**row, "highlight_id": highlight_id}


@router.get("/api/highlights/{highlight_id}/segments/{segment_id}/candidates")
async def highlight_segment_candidates_api(
    highlight_id: int, segment_id: int,
    span: float = DEFAULT_CANDIDATE_SPAN_SECONDS,
) -> dict:
    """そのgift演出のmedia窓の前後にあるgift eventの一覧(差し替え用)。

    録画が当たっていないgift演出には候補が無い —— 探す先の録画が決まっていないので、母集団を
    作れない。0件を返さずに409で断るのは、「候補が無い」と「そもそも探せない」を同じ空listで
    見せないためである。
    """
    if not 0 < span <= MAX_CANDIDATE_SPAN_SECONDS:
        raise HTTPException(
            status_code=400,
            detail=f"spanは0より大きく{MAX_CANDIDATE_SPAN_SECONDS:.0f}秒以下で指定してください。")

    def _collect() -> dict:
        _require_highlight(highlight_id)
        segment = _require_segment(highlight_id, segment_id)
        if segment["recording_id"] is None or segment["media_start"] is None:
            raise HTTPException(
                status_code=409,
                detail="このgift演出はまだ録画に当たっていないため、giftの候補を探せません。")
        recording = runtime.storage.get_recording(segment["recording_id"])
        if recording is None:
            raise HTTPException(
                status_code=409, detail="このgift演出が指す録画がありません（削除済み）。")
        events, media_times = _recording_gift_events(recording)
        media_start = float(segment["media_start"])
        media_end = media_start + (float(segment["end"]) - float(segment["start"]))
        items = [
            _gift_payload(event, media_times[event["gift_event_id"]], media_start)
            for event in events
            if media_start - span <= media_times[event["gift_event_id"]] <= media_end + span
        ]
        items.sort(key=lambda item: item["media_time"])
        return {"highlight_id": highlight_id, "segment_id": segment_id,
                "recording_id": recording["id"], "span": span,
                "media_start": round(media_start, 3), "media_end": round(media_end, 3),
                "candidates": items}

    return await asyncio.to_thread(_collect)


@router.patch("/api/highlights/{highlight_id}/segments/{segment_id}")
async def patch_highlight_segment_api(highlight_id: int, segment_id: int,
                                      payload: HighlightSegmentPatch) -> dict:
    """gift演出を1件直す(端・確認・除外・memo)。

    端を動かしたら ``edited`` を立てる。印が無いと、次の再照合が人の値を機械の値で上書き
    してしまう。**giftはここでは触らない** —— gift演出1つが複数のgiftを持つので、付け替えは
    ``POST /segments/{id}/gifts``、1件だけの除外は ``PATCH /segments/{id}/gifts/{gift_id}``。
    """
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="変更する項目がありません。")

    def _apply() -> dict:
        _require_highlight(highlight_id)
        _require_segment(highlight_id, segment_id)
        updated = runtime.storage.update_highlight_segment(
            highlight_id, segment_id, fields)
        if updated is None:
            raise HTTPException(status_code=404, detail="このgift演出は見つかりません。")
        return updated

    updated = await asyncio.to_thread(_apply)
    runtime.logger.info(
        "highlightのgift演出を手直ししました（highlight=%s segment=%s）: %s",
        highlight_id, segment_id, sorted(fields),
        extra={"event": "highlight.segment_edited",
               "ctx": {"highlight_id": highlight_id, "segment_id": segment_id,
                       "fields": sorted(fields)}},
    )
    return {"segment": _segment_payload(highlight_id, updated)}


@router.post("/api/highlights/{highlight_id}/segments/{segment_id}/gifts")
async def add_highlight_segment_gift_api(highlight_id: int, segment_id: int,
                                         payload: HighlightGiftAdd) -> dict:
    """gift演出へgiftを1件足す(既に在れば人のものとして戻す)。

    受け取るのは **event の id だけ**。列はDBのeventから引き直して埋め、``manual`` を立てる
    ので、次の再照合はこの行のeventを機械の答えで置き換えない。

    ``gift_media_time`` は録画の時間軸が要るのでここで解決する —— 軸の作り方は
    ``highlight_match.time_mapper`` をそのまま使う(候補の秒とgift演出の秒が別の軸に載らない
    ようにするため)。録画が当たっていないgift演出には紐付けられないので409。
    """
    def _apply() -> dict:
        _require_highlight(highlight_id)
        segment = _require_segment(highlight_id, segment_id)
        gift = runtime.storage.highlight_gift_event(payload.gift_event_id)
        if gift is None:
            raise HTTPException(
                status_code=404,
                detail=f"gift eventが見つかりません: {payload.gift_event_id}")
        recording_id = segment["recording_id"]
        recording = (runtime.storage.get_recording(recording_id)
                     if recording_id is not None else None)
        if recording is None:
            raise HTTPException(
                status_code=409,
                detail="このgift演出は録画に当たっていないため、giftを紐付けられません。")
        _events, media_times = _recording_gift_events(recording)
        if gift["gift_event_id"] not in media_times:
            raise HTTPException(
                status_code=409, detail="そのgiftはこのgift演出が指す録画の窓の外です。")
        gift["gift_media_time"] = media_times[gift["gift_event_id"]]
        updated = runtime.storage.add_highlight_segment_gift(
            highlight_id, segment_id, gift)
        if updated is None:
            raise HTTPException(status_code=404, detail="このgift演出は見つかりません。")
        return updated

    updated = await asyncio.to_thread(_apply)
    runtime.logger.info(
        "highlightのgift演出へgiftを紐付けました（highlight=%s segment=%s event=%s）",
        highlight_id, segment_id, payload.gift_event_id,
        extra={"event": "highlight.gift_added",
               "ctx": {"highlight_id": highlight_id, "segment_id": segment_id,
                       "gift_event_id": payload.gift_event_id}},
    )
    return {"segment": _segment_payload(highlight_id, updated)}


# 1つの窓として成り立つ最短。これより短い範囲はffmpegが空のpartを作って落ちるので、
# 書き出しまで行かせずここで断る(``highlight_export.MIN_CUT_SECONDS`` と同じ床)。
MIN_GIFT_CUT_SECONDS = highlight_export.MIN_CUT_SECONDS
# 端の比較に使う遊び。画面はgift演出の端ちょうど(0.001秒に丸めた値)を送ってくるので、
# 厳密に比べると自分が出した値で400になる。
_CUT_EPSILON = 0.001


def _resolve_gift_cut(segment: dict, fields: dict) -> None:
    """giftの切り出し範囲を検算して ``fields`` を整える。壊れていれば400。

    **黙って丸めない。** gift演出の外を指す値を丸めて受けると、画面には打った値が残り、出力
    だけが別の場所を切る —— しかも数字は出るので誰も気付かない。断ってしまえば、画面が
    そのまま人へ返せる。

    範囲は**gift演出の中**に収める。montageなのでgift演出の外は「その少し前」ではなく、まったく
    無関係な場面である(別の時刻のgift演出が繋がっているだけ)。

    ``cut_clear`` はここで ``cut_start``/``cut_end`` を None へ畳んでstoreへ渡す。storeは
    「2つ揃っていればその範囲、揃っていなければgift演出の窓」だけを知っていればよい。"""
    if fields.pop("cut_clear", None):
        if fields.get("cut_start") is not None or fields.get("cut_end") is not None:
            raise HTTPException(
                status_code=400,
                detail="区間を消す指定と、区間の値を同時に送ることはできません。")
        fields["cut_start"] = None
        fields["cut_end"] = None
        return
    if "cut_start" not in fields and "cut_end" not in fields:
        return
    start = fields.get("cut_start")
    end = fields.get("cut_end")
    if start is None or end is None:
        raise HTTPException(
            status_code=400,
            detail="giftの区間は頭と尻を揃えて指定してください"
                   "（gift演出の窓へ戻すときは cut_clear を送ってください）。")
    span_start = float(segment["start"])
    span_end = float(segment["end"])
    if start < span_start - _CUT_EPSILON or end > span_end + _CUT_EPSILON:
        raise HTTPException(
            status_code=400,
            detail=f"giftの区間はgift演出の中に収めてください"
                   f"（gift演出 {span_start:.2f}〜{span_end:.2f}秒 に対し "
                   f"{float(start):.2f}〜{float(end):.2f}秒）。")
    # 端の丸め誤差ぶんだけ内側へ寄せる。ここは「外へ出た値を直す」のではなく、画面が
    # gift演出の端ちょうどを送ってきたときに浮動小数の桁で弾かないためである。
    start = min(max(float(start), span_start), span_end)
    end = min(max(float(end), span_start), span_end)
    if end - start < MIN_GIFT_CUT_SECONDS:
        raise HTTPException(
            status_code=400,
            detail=f"giftの区間が短すぎます"
                   f"（{end - start:.2f}秒 / 最短 {MIN_GIFT_CUT_SECONDS:g}秒）。")
    fields["cut_start"] = round(start, 3)
    fields["cut_end"] = round(end, 3)


@router.patch("/api/highlights/{highlight_id}/segments/{segment_id}/gifts/{gift_id}")
async def patch_highlight_segment_gift_api(highlight_id: int, segment_id: int,
                                           gift_id: int,
                                           payload: HighlightGiftPatch) -> dict:
    """gift 1件の人の印を直す。

    ``gift_id`` は **``highlight_segment_gifts.id``**(行のid)であって、giftの種別idでも
    eventのidでもない。同じeventが2つのgift演出に現れることは無いが、行を名指しできる鍵は
    行のidだけである。
    """
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="変更する項目がありません。")

    def _apply() -> dict:
        _require_highlight(highlight_id)
        segment = _require_segment(highlight_id, segment_id)
        _resolve_gift_cut(segment, fields)
        updated = runtime.storage.update_highlight_segment_gift(
            highlight_id, segment_id, gift_id, fields)
        if updated is None:
            raise HTTPException(status_code=404, detail="このgiftは見つかりません。")
        return updated

    updated = await asyncio.to_thread(_apply)
    runtime.logger.info(
        "highlightのgiftを手直ししました（highlight=%s segment=%s gift=%s）: %s",
        highlight_id, segment_id, gift_id, sorted(fields),
        extra={"event": "highlight.gift_edited",
               "ctx": {"highlight_id": highlight_id, "segment_id": segment_id,
                       "gift_id": gift_id, "fields": sorted(fields)}},
    )
    return {"segment": _segment_payload(highlight_id, updated)}


@router.delete("/api/highlights/{highlight_id}")
async def delete_highlight_api(highlight_id: int) -> dict:
    """台帳の行だけを消す。**mp4には触らない。**

    highlightは外から来た素材で、こちらが作った成果物ではない。次に走査すれば同じfileが
    新しい行として戻る(そのときgift演出の手直しは戻らないので、消す前に画面が確認を出すこと)。
    """
    highlight = await asyncio.to_thread(_require_highlight, highlight_id)
    deleted = await asyncio.to_thread(runtime.storage.delete_highlight, highlight_id)
    runtime.logger.info(
        "highlightの行を削除しました（id=%s / %s）", highlight_id, highlight["filename"],
        extra={"event": "highlight.deleted",
               "ctx": {"highlight_id": highlight_id, "path": highlight["path"],
                       "unique_id": highlight["unique_id"]}},
    )
    return {"deleted": deleted, "highlight_id": highlight_id,
            "path": highlight["path"]}


# --- ここから下は出力(結合)のroute。 ---


class HighlightExportRequest(BaseModel):
    """書き出しの設定。**既定値はここに持たない。**

    未指定(None)の項目はそのまま落とし、``highlight_export.export_highlights`` の署名にある
    既定が使われる。ここへ既定を書き写すと、実際に使われる値と2箇所に分かれる
    (``HighlightMatchRequest`` と同じ約束)。

    **出力はgifterごとに1本ずつ**で、1本にまとめる指定は無い。対象はその週に
    ``post_min``(1,000💎)以上投げたgifterだけで、この閾値も週の境界も
    ``streamer_mention_week`` が持つ ―― 画面からもここからも指定させない。

    ``week`` はその週の**土曜の日付**(``YYYY-MM-DD``)。未指定なら最新の週になる。

    ``order`` は**1本の中の並び**だけを決める(``diamonds`` / ``time``)。fileを分ける軸は
    gifterで、選べない。

    ``min_diamonds`` は**gift 1件あたり**の下限で、既定は設定の演出gift下限(98💎)である。
    **0を明示すれば全gift**が載るので、未指定と0を同じ扱いにしないこと。週合計の1,000💎とは
    別の軸である。
    """

    # 知らないfieldは**弾く**(422)。黙って無視すると、呼び出し側は指定が効いていると
    # 思い込んだまま別の結果を受け取る。設計が変わって消えた引数(``group_by_gifter`` /
    # ``name``)を送っている画面には、その場で気付いてもらう必要がある。
    model_config = ConfigDict(extra="forbid")

    highlight_ids: list[int]
    week: Optional[str] = None
    order: Optional[str] = None
    min_diamonds: Optional[int] = None
    pad_lead: Optional[float] = None
    pad_tail: Optional[float] = None
    precise: Optional[bool] = None


def _require_export_targets(highlight_ids: list) -> list:
    """指定されたhighlightが実在し、素材のfileも在ることを確かめて行を返す。

    workerで初めて落とすと、待機列の順番を待った末に「fileが無い」で終わる。配信者を
    またぐ選択もここで弾く ―― 出力の置き場は配信者folderの下なので、混ぜると片方の
    配信者の物として置かれ、file systemが台帳である以上そこで持ち主が失われる。

    **照合が終わっていないhighlightもここで弾く。** 書き出せるのはDBに保存された実照合
    結果からだけで(``highlight_export`` のmodule docstring)、その判定は
    ``_fetch_segments`` も持っている。ここにも置くのは、jobを積む前に画面へ理由を返す
    ためである —— 待機列の順番を待った末に同じ理由で失敗させても、押した人には届かない。"""
    found = []
    for highlight_id in highlight_ids:
        highlight = _require_highlight(highlight_id)
        if not Path(highlight["path"]).is_file():
            raise HTTPException(
                status_code=404,
                detail=f"highlightのfileがありません: {highlight['filename']}")
        if highlight["status"] != HIGHLIGHT_STATUS_MATCHED:
            raise HTTPException(
                status_code=409,
                detail=(f"照合が終わっていないhighlightは書き出せません:"
                        f" {highlight['filename']}（{highlight['status']}）。"
                        "先に突き合わせを実行してください。"))
        found.append(highlight)
    streamers = sorted({h["unique_id"] for h in found})
    if len(streamers) > 1:
        raise HTTPException(
            status_code=400,
            detail=f"配信者をまたいで書き出せません（{'、'.join(streamers)}）。")
    return found


@router.post("/api/highlights/export/plan")
async def export_highlights_plan_api(payload: HighlightExportRequest) -> dict:
    """結合前の下見。**誰の何が、どの名前で、どの順に出るか**を返す。ffmpegは動かさない。

    画面が「結合したら何が出来るか」を出すための唯一の口である。**除外の規則を画面へ
    写さないこと** —— 同じ規則が2つになると、片方だけが更新された日に予告と成果物が
    食い違う。判定は :func:`tictok.media.highlight_export.plan_exports` の1箇所に在り、
    ここはそれをそのまま返すだけである。

    bodyは結合と同じ ``HighlightExportRequest``。**同じbodyを投げれば、この応答の
    ``files`` がそのまま出来上がる。**
    """
    highlight_ids = list(dict.fromkeys(payload.highlight_ids))
    if not highlight_ids:
        raise HTTPException(status_code=400,
                            detail="書き出すhighlightを1本以上選んでください。")
    found = await asyncio.to_thread(_require_export_targets, highlight_ids)
    streamer = found[0]["unique_id"]
    options = payload.model_dump(exclude_none=True,
                                 exclude={"highlight_ids", "precise"})
    week = options.pop("week", "")

    def _plan() -> dict:
        rows = highlight_export._fetch_segments(runtime.storage, highlight_ids)
        mention = runtime.storage.streamer_mention_week(streamer, week)
        directory = layout.merged_highlight_dir(streamer)
        # その週に**載るはずのgift全部**。下見だけがこれを引く —— 書き出しの実行経路は
        # 「無い物」を素性のJSONに書かないので要らない。下限は下見が実際に使う値と
        # **同じ出所**から解決する(画面が数字を持たないのと同じ理由で、ここでも書かない)。
        floor = options.get("min_diamonds")
        if floor is None:
            floor = highlight_export.defaults()["min_diamonds"]
        ledger = runtime.storage.highlight_week_gifts(streamer, week, int(floor))
        plan = highlight_export.plan_exports(rows, mention, directory=directory,
                                             week_gifts=ledger["gifts"], **options)
        return {**plan, "streamer": streamer, "directory": str(directory)}

    try:
        plan = await asyncio.to_thread(_plan)
    except (highlight_export.NoSegments, highlight_export.NotMatched) as exc:
        # 0件も未照合も、失敗ではなく「今の状態では出せない」という結果である。画面が理由を
        # そのまま出せるよう、内訳を含む文言を返す(空の一覧として描かせない)。
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**plan,
            "files": [_export_group(entry) for entry in plan["files"]],
            "uncovered": [{**entry,
                           "missing": [_missing_row(g) for g in entry.get("missing") or []]}
                          for entry in plan.get("uncovered") or []]}


def _gift_icon(item: dict) -> str:
    """gift iconのproxy URL。gift演出が持つ署名付きCDN URLは時間が経つと失効するので、
    そのまま画面へ渡さない(``get_highlight_api`` と同じ規則)。読めないidはicon無し。"""
    try:
        gift_id = int(item.get("gift_id") or 0)
    except (TypeError, ValueError):
        gift_id = 0
    return runtime.gift_icon_url(gift_id, item.get("gift_image") or "")


def _missing_row(gift: dict) -> dict:
    """1本へ載らなかったgift 1件を画面へ渡す形にする。**理由はServerの文言のまま**返す
    (:data:`highlight_export.MISSING_UNMATCHED` ほか) —— 画面で言い換えると、同じ判断の
    説明が2箇所に増える。"""
    return {**gift, "gift_image": _gift_icon(gift)}


def _export_group(entry: dict) -> dict:
    """下見の1束を画面へ渡す形にする。

    giftのiconはproxy経由のURLへ解決する。gift演出が持つのは署名付きCDN URLで、時間が経つと
    失効する —— そのまま渡すと古い照合結果だけiconが出ない(``get_highlight_api`` と同じ規則)。
    出せないgiftにはURLを付けない(代わりの絵は出さない)。

    ``src`` は素材の実pathなのでそのままは渡さない。画面が指すのはhighlightの行(id)であって
    file systemではない —— 実pathを返すと、client側から任意のdirを名乗る足掛かりになる。

    **代表frameのURLを行ごとに付ける。** gift名とgifter名の文字列だけでは「別人のfileへ
    別人のgiftが入る」誤りに人が気付けない —— 実際にそれで7本の誤出力が出た。絵が並べば
    押す前に判る。URLの組み立ては :func:`highlight_frame_url` /
    :func:`segment_frame_url` の1箇所だけを使う(画面でffmpegは呼べない)。"""
    items = []
    for item in entry["items"]:
        at, frame_at, clamped = _export_frame_at(item)
        items.append({
            "highlight_id": item.get("highlight_id"), "idx": item.get("idx"),
            # gift演出の確からしさ。画面が「確認していないgift演出が N 件あります」と名乗り、
            # confidence が high でないgift演出を目立たせるために要る。
            "segment_id": item.get("segment_id"),
            "approved": bool(item.get("approved")), "edited": bool(item.get("edited")),
            "confidence": item.get("confidence") or "",
            "start": item.get("start"), "end": item.get("end"),
            "gift_event_id": item.get("gift_event_id"),
            "gift_id": item.get("gift_id"), "gift_name": item.get("gift_name"),
            "gift_image": _gift_icon(item),
            "diamonds": item.get("diamonds"),
            # まとめ投げの個数と単価。合計(``diamonds``)だけでは「270💎なのに小さな
            # bannerしか出ない」giftを人が見分けられない。下限を判定しているのは単価。
            "gift_count": item.get("gift_count"),
            "unit_diamonds": item.get("unit_diamonds"),
            # **誰が投げたか。** 行にこれが無いと、束を開いても持ち主と違うgifterのgift演出が
            # 紛れていることに人が気付けない —— 今回の事故(``視聴者A`` のfileに ``よい`` の
            # gift)は、束の2件目に別の名前が並んでいれば一目で判った。
            #
            # ``identity_key`` まで返すのは、**表示名で比べては駄目**だからである。改名すれば
            # 別人に見え、同名を名乗れば同一人に見える。画面は鍵どうしで比べる。
            #
            # **比べる鍵は ``person_key`` の方である。** ``identity_key`` は投げた
            # アカウントで、人が束ねたサブアカウント(user_merges)はそのままでは別人に
            # 見える —— 束ねた人が自分のサブで投げるたびに「別人が混ざっている」と
            # 名乗ることになる。両方返すのは、どのアカウントから来たgiftかも行から
            # 読めるようにするためである。
            "user_nickname": item.get("user_nickname"),
            "user_unique_id": item.get("user_unique_id"),
            "identity_key": item.get("identity_key"),
            "person_key": item.get("person_key"),
            "recording_id": item.get("recording_id"),
            "media_start": item.get("media_start"),
            # gift演出の範囲の中に居るgiftか。偽なら ``at`` はgift演出の頭より手前を指し、
            # **そこにhighlightの映像は無い**(切り出しはgift演出の窓のままである)。
            "inside": bool(item.get("inside")),
            "is_primary": bool(item.get("is_primary")),
            "manual": bool(item.get("manual")),
            # giftがgift演出の何秒目か(**丸めない値**)と、その絵。絵だけはgift演出の窓の中へ丸め、
            # 丸めたことを ``frame_clamped`` が名乗る。
            "at": at,
            "frame_url": highlight_frame_url(item.get("highlight_id"), frame_at),
            # 同じ秒で録画側の1枚も出す。2枚が同じ場面なら突き合わせが当たっている。
            "recording_frame_url": segment_frame_url(item.get("highlight_id"),
                                                     item.get("segment_id"), frame_at),
            "frame_clamped": clamped,
        })
    # ``cuts`` は**実際に切る窓**で、``items``(gift 1件ずつの記録)とは1対1にならない。
    # 連投は記録6件・窓1つになるので、画面が「件数と尺が比例しない」理由を出せるように
    # 両方返す。素材の実pathは落とす(``_cut_summary`` が名乗るのはidと秒だけ)。
    cuts = [{k: v for k, v in highlight_export._cut_summary(cut).items() if k != "src"}
            for cut in (entry.get("cuts") or [])]
    # 1本へ載らなかったgift。**中身には入らないが、無いことを人へ見せるために返す。**
    missing = [_missing_row(gift) for gift in (entry.get("missing") or [])]
    return {**{k: v for k, v in entry.items()
               if k not in ("items", "cuts", "missing")},
            "items": items, "cuts": cuts, "missing": missing}


def _export_frame_at(item: dict) -> tuple:
    """下見の1行の ``(giftの位置, 絵を採る秒, 丸めたか)``。位置が出せないなら3つとも空。

    giftの瞬間を採る(``store.highlights.gift_position``)。gift演出の頭ではない —— giftはgift演出の
    頭に在るとは限らず、頭で代用すると全部の行がgift演出の頭の絵になり、しかも「だいたい
    合っている」ので誰も気付かない。

    絵の秒だけはgift演出の窓の中へ丸める(:func:`highlight_export.clamp_to_segment`)。丸める
    理由と、丸めたことを名乗る理由はあちらのdocstringに書いた。**丸めるのは絵であって
    ``at`` ではない** —— 「giftが本当は何秒目か」と「その行を書き出すと何が映るか」は別の
    話で、両方を返すから人はその2つを突き合わせられる。"""
    at = gift_position(item.get("segment_start"), item.get("media_start"),
                       item.get("gift_media_time"))
    frame_at, clamped = highlight_export.clamp_to_segment(
        at, item.get("segment_start"), item.get("segment_end"))
    return at, frame_at, clamped


@router.post("/api/highlights/export")
async def export_highlights_api(payload: HighlightExportRequest) -> dict:
    """gifterごとに1本ずつ書き出すjobをqueueへ投入する(同期実行はしない)。``{job_id}``。

    **突き合わせと違って即時laneへは入れない。** 対象のgifterの数だけmp4を作り、gift演出ごとに
    frame精度の再encodeを掛けるので数分かかる。数秒の操作のために空けてある枠を塞ぐと、
    その間スクショも突き合わせも待たされる(``media_jobs.HIGHLIGHT_EXPORT_JOB_PRIORITY``)。

    **誰が対象かはここで判定しない。** 週の境界も1,000💎の閾値も名寄せも
    ``streamer_mention_week`` に在り、選び方は ``plan_exports`` に在る。下見が要るなら
    ``/api/highlights/export/plan`` を先に叩くこと ―― 同じbodyから同じ結果が出る。
    """
    highlight_ids = list(dict.fromkeys(payload.highlight_ids))
    if not highlight_ids:
        raise HTTPException(status_code=400,
                            detail="書き出すhighlightを1本以上選んでください。")
    found = await asyncio.to_thread(_require_export_targets, highlight_ids)
    streamer = found[0]["unique_id"]
    options = payload.model_dump(exclude_none=True, exclude={"highlight_ids"})
    row = await media_jobs._enqueue_media_job(
        "highlight_export",
        stem=f"{streamer} / {len(highlight_ids)}本",
        params={"highlight_ids": highlight_ids, **options},
        priority=media_jobs.HIGHLIGHT_EXPORT_JOB_PRIORITY,
    )
    runtime.logger.info(
        "highlightの書き出しをqueueへ投入しました（%s / %d本）",
        streamer, len(highlight_ids),
        extra={"event": "highlight.export_queued",
               "ctx": {"job_id": row["job_id"], "highlight_ids": highlight_ids,
                       "streamer": streamer, "options": options}},
    )
    return {**row, "highlight_ids": highlight_ids, "streamer": streamer}
