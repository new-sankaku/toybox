"""画面(HTML)とavatar画像・gift icon。APIではなくbrowserが直接開くpath。"""

import asyncio
from fastapi import HTTPException
from fastapi.responses import FileResponse, Response
from tictok.core.http_cache import REVALIDATE_CACHE_CONTROL
from tictok.media.avatar_proxy import AvatarProxy
from tictok.media.gift_icons import GiftIconCache
from fastapi import APIRouter
from tictok.api import runtime

router = APIRouter()


def _page_response(filename: str) -> FileResponse:
    """HTML shellの応答。必ずrevalidateさせ、JS/CSSとの版ズレを防ぐ。"""
    return FileResponse(runtime.STATIC_DIR / filename,
                        headers={"Cache-Control": REVALIDATE_CACHE_CONTROL})


@router.get("/")
async def index() -> FileResponse:
    return _page_response("index.html")


@router.get("/overview")
async def overview_page() -> FileResponse:
    return _page_response("overview.html")


@router.get("/history")
async def history_page() -> FileResponse:
    return _page_response("history.html")


@router.get("/videos")
async def videos_page() -> FileResponse:
    return _page_response("videos.html")


@router.get("/capacity")
async def capacity_page() -> FileResponse:
    return _page_response("capacity.html")


@router.get("/jobs")
async def jobs_page() -> FileResponse:
    return _page_response("jobs.html")


@router.get("/ops")
async def ops_page() -> FileResponse:
    return _page_response("ops.html")


@router.get("/settings")
async def settings_page() -> FileResponse:
    return _page_response("settings.html")


@router.get("/streamers")
async def streamers_page() -> FileResponse:
    return _page_response("streamers.html")


@router.get("/analytics")
async def analytics_page() -> FileResponse:
    return _page_response("analytics.html")


@router.get("/fans")
async def fans_page() -> FileResponse:
    return _page_response("fans.html")


@router.get("/api/avatar")
async def avatar_image(u: str = "", id: str = "") -> Response:
    """Same-origin proxy for TikTok CDN avatars. The CDN hotlink/Referer-blocks
    direct <img src> loads and its signed URLs expire, so the browser fetches via
    here instead. ``id`` (the user's unique_id, optional) lets an expired URL fall
    back to that user's latest pooled avatar (owner or commenter). On total failure
    the UI falls back to its initial-letter avatar."""
    if not u:
        # URLを持たない行(その時点のavatarを記録できなかったsession)は、id単位のpoolだけを
        # 見る。取りに行くURLが無いので、poolに無ければ404で頭文字へ落ちる。
        if not id:
            raise HTTPException(status_code=400, detail="画像URLかuser idのどちらかが必要です。")
        pooled = await asyncio.to_thread(runtime.avatar_proxy.pooled, id)
        if pooled is None:
            raise HTTPException(status_code=404, detail="このuserのアイコン画像がありません。")
        content, content_type = pooled
        return Response(
            content=content,
            media_type=content_type,
            headers={"Cache-Control": "public, max-age=21600"},
        )
    if not AvatarProxy.is_allowed(u):
        raise HTTPException(status_code=400, detail="許可されていない画像URLです。")
    result = await runtime.avatar_proxy.fetch(u, user_key=id or None)
    if result is None:
        raise HTTPException(status_code=502, detail="アイコン画像の取得に失敗しました。")
    content, content_type = result
    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=21600"},
    )


@router.get("/api/gift-icon")
async def gift_icon_image(gift_id: int, u: str = "") -> Response:
    """収集時にdiskへ溜めたgift icon(``<gift_id>.img``)を返す。timelineへ載せる
    icon画像を画面が直に引く口。

    iconはgift_id別の不変画像なので、poolに在るものをそのまま返す。まだ無いgiftだけ
    eventが持っていたCDN URL(``u``)から1度だけ取り込む — このURLは署名/地域hostで
    後から失効するため、取り込めない(=404)ことは普通に起きる。代わりの画像は返さない:
    別の絵を出せば、実際には飛んでいないgiftが飛んだように読める。"""
    icon = await asyncio.to_thread(runtime.gift_icons.load, gift_id)
    if icon is None and u:
        if not GiftIconCache.is_allowed(u):
            raise HTTPException(status_code=400, detail="許可されていない画像URLです。")
        if await runtime.gift_icons.persist(gift_id, u):
            icon = await asyncio.to_thread(runtime.gift_icons.load, gift_id)
    if icon is None:
        raise HTTPException(status_code=404, detail="giftのicon画像がありません。")
    content, content_type = icon
    return Response(
        content=content,
        media_type=content_type,
        # gift_idに対して中身が変わらないので長く持たせる(再生位置を動かすたびに
        # 同じiconを引き直さない)。
        headers={"Cache-Control": "public, max-age=604800, immutable"},
    )
