"""画面(HTML)とavatar画像。APIではなくbrowserが直接開くpath。"""

from fastapi import HTTPException
from fastapi.responses import FileResponse, Response
from tictok.core.http_cache import REVALIDATE_CACHE_CONTROL
from tictok.media.avatar_proxy import AvatarProxy
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
async def avatar_image(u: str, id: str = "") -> Response:
    """Same-origin proxy for TikTok CDN avatars. The CDN hotlink/Referer-blocks
    direct <img src> loads and its signed URLs expire, so the browser fetches via
    here instead. ``id`` (the user's unique_id, optional) lets an expired URL fall
    back to that user's latest pooled avatar (owner or commenter). On total failure
    the UI falls back to its initial-letter avatar."""
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
