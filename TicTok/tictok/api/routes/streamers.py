"""配信者・fan・発見候補の集計route。配信横断で「誰が」を見る側。"""

import asyncio
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from tictok.api import runtime

router = APIRouter()


class UserAliasRequest(BaseModel):
    """投稿へ貼る文面で名前の代わりに出す省略形。空文字は「外す」で、行ごと消える。"""

    identity_key: str
    alias: str = ""


class UserMergeRequest(BaseModel):
    """同じ人の別アカウント(サブ)を主アカウントへ束ねる指定。"""

    member_key: str
    primary_key: str


class UserUnmergeRequest(BaseModel):
    """束ねを1件外す指定。外れるのはサブ側だけで、同じ主の他のサブは残る。"""

    member_key: str


@router.get("/api/dashboard")
async def aggregate_dashboard() -> dict:
    return await asyncio.to_thread(runtime.storage.aggregate_dashboard)


@router.get("/api/streamers")
async def list_streamers() -> dict:
    streamers = await asyncio.to_thread(runtime.storage.streamer_index)
    return {"streamers": streamers}


@router.get("/api/fans")
async def fan_ledger() -> dict:
    """視聴者を主語にしたgift台帳。誰がどの配信者へ幾ら投じたかの横断一覧。"""
    return await asyncio.to_thread(
        runtime.storage.fan_ledger,
        runtime.settings.get("fan_min_diamonds"),
        runtime.settings.get("fan_limit"),
    )


@router.get("/api/fans/{identity_key}")
async def fan_profile(identity_key: str) -> dict:
    try:
        profile = await asyncio.to_thread(runtime.storage.fan_profile, identity_key)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not profile:
        raise HTTPException(status_code=404, detail="該当する視聴者が見つかりません。")
    return profile


@router.put("/api/user-aliases")
async def set_user_alias(payload: UserAliasRequest) -> dict:
    """1人ぶんの省略形を置く(空なら外す)。

    識別子をpathではなくbodyで受けるのは、identity_keyが数値IDだけでなく@handleや表示名
    にもなり得るためである —— 表示名には '/' も '?' も入り得るので、pathへ載せるとURLの
    区切りと区別が付かなくなる。

    書けたら省略形だけでなく、その値の入った文面を組み直すための応答は返さない。画面は
    /mentions を引き直す —— 文面はServerが組む物なので、画面側で名前だけ差し替えると
    名乗りの形が2つに割れる。
    """
    try:
        return await asyncio.to_thread(
            runtime.storage.set_user_alias, payload.identity_key, payload.alias)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/api/user-aliases")
async def list_user_aliases() -> dict:
    """付いている省略形の一覧(identity_key -> 省略形)。付いていない人は入らない。"""
    aliases = await asyncio.to_thread(runtime.storage.list_user_aliases)
    return {"aliases": aliases}


@router.put("/api/user-merges")
async def merge_users(payload: UserMergeRequest) -> dict:
    """サブアカウントを主アカウントへ束ねる。効くのは日のGifterの集計で、eventは動かない。

    識別子をbodyで受けるのは省略形と同じ理由(identity_keyは表示名にもなり得るので、
    pathへ載せるとURLの区切りと区別が付かない)。応答は束ねた結果の1件で、画面はこの後
    /mentions を引き直す —— 畳んだ顔ぶれを組むのはServerだからである。
    """
    try:
        return await asyncio.to_thread(
            runtime.storage.merge_users, payload.member_key, payload.primary_key)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.delete("/api/user-merges")
async def unmerge_user(payload: UserUnmergeRequest) -> dict:
    """束ねを1件外す。外した側は次の引き直しで元のアカウントとして顔ぶれへ戻る。"""
    return await asyncio.to_thread(runtime.storage.unmerge_user, payload.member_key)


@router.get("/api/user-merges")
async def list_user_merges() -> dict:
    """束ねの一覧(主+サブの名乗り込み)。束ねの無いときは空。"""
    merges = await asyncio.to_thread(runtime.storage.list_user_merges)
    return {"merges": merges}


@router.get("/api/discovery")
async def discovery_candidates() -> dict:
    """未監視だがBattleで繰り返し当たっている配信者の候補list。

    昇格は既存の POST /api/monitors をそのまま使う(この画面のためだけの追加経路は作らない)。
    ここが返すのは候補と却下の管理だけである。"""
    return await asyncio.to_thread(
        runtime.storage.discovery_candidates,
        runtime.settings.get("discovery_min_contacts"),
        runtime.settings.get("discovery_half_life_days"),
        runtime.settings.get("discovery_limit"),
    )


@router.post("/api/discovery/{unique_id}/dismiss")
async def dismiss_candidate(unique_id: str) -> dict:
    handle = runtime._normalize_unique_id(unique_id)
    await asyncio.to_thread(runtime.storage.dismiss_discovery_candidate, handle)
    return {"dismissed": handle}


@router.delete("/api/discovery/{unique_id}/dismiss")
async def restore_candidate(unique_id: str) -> dict:
    handle = runtime._normalize_unique_id(unique_id)
    await asyncio.to_thread(runtime.storage.restore_discovery_candidate, handle)
    return {"restored": handle}


@router.get("/api/discovery/dismissed")
async def list_dismissed_candidates() -> dict:
    dismissed = await asyncio.to_thread(runtime.storage.list_dismissed_candidates)
    return {"dismissed": dismissed}


@router.get("/api/streamers/{unique_id}/profile")
async def streamer_profile(unique_id: str) -> dict:
    profile = await asyncio.to_thread(runtime.storage.streamer_profile, unique_id)
    # A still-collecting session persists stats only at finalize, so overlay the
    # live collector's running stats so today's numbers are reflected in the totals.
    collector = runtime.manager.get(unique_id)
    if collector is not None and collector.session_id is not None:
        for session in profile["sessions"]:
            if session["session_id"] == collector.session_id:
                stats = collector.stats
                session["gifts"] = stats.get("gifts", session["gifts"]) or 0
                session["diamonds"] = stats.get("diamonds", session["diamonds"]) or 0
                session["comments"] = stats.get("comments", session["comments"]) or 0
                session["likes"] = stats.get("likes_total", session["likes"]) or 0
                session["viewers"] = stats.get("viewers", session["viewers"]) or 0
                session["battles"] = stats.get("battles", session["battles"]) or 0
                session["battle_points"] = stats.get("battle_points", session["battle_points"]) or 0
                session["live"] = True
                # Re-derive the lifetime aggregates so the live session's running
                # numbers are reflected (stats_json is stale until finalize).
                sessions = profile["sessions"]
                metrics = ["gifts", "diamonds", "comments", "likes", "viewers", "duration", "battle_points"]
                count = len(sessions)
                profile["totals"] = {m: sum(s[m] for s in sessions) for m in metrics}
                profile["average"] = {m: (profile["totals"][m] / count if count else 0) for m in metrics}
                profile["best"] = {m: max((s[m] for s in sessions), default=0) for m in metrics}
                break
    return profile


@router.get("/api/streamers/{unique_id}/cohort")
async def streamer_cohort(unique_id: str) -> dict:
    return await asyncio.to_thread(runtime.storage.streamer_cohort, unique_id)


@router.get("/api/streamers/{unique_id}/mentions")
async def streamer_mention_week(unique_id: str, week: str = "") -> dict:
    """土曜7時〜次の土曜7時にGiftを投げた人。ショート動画のメンションに貼る用。

    weekを省くと最新の週を返す。rankingと別の口にしてあるのは、こちらが配信者を選んだ
    時点で必ず引かれるためで、Battle窓の解決を含めない(実測 0.14s / 0.41s)。

    応答のdaysは、その週を日(7時〜翌7時)へ割った貢献。日ぶんを別の口にしないのは、
    週と同じ窓・同じ行から数えることで合計の一致を保証するためである。
    """
    return await asyncio.to_thread(
        runtime.storage.streamer_mention_week, unique_id, week)


@router.get("/api/streamers/{unique_id}/mentions/gifts")
async def streamer_mention_gifts(unique_id: str, week: str = "",
                                 identity_key: str = "") -> dict:
    """メンション一覧の1人が、その週に投げたgiftを1件ずつ。画面が行を開いた時だけ引く。

    iconのURLはここで解決する(poolに在ればidだけ、無ければeventのCDN URLを添えて1度だけ
    取り込ませる)。出せないgiftにはURLを付けない — 代わりの絵を出すと、実際には飛んで
    いないgiftが飛んだように読める。
    """
    payload = await asyncio.to_thread(
        runtime.storage.streamer_mention_gifts, unique_id, week, identity_key)
    icons: dict = {}
    for item in payload["items"]:
        gift_id = item["gift_id"]
        if gift_id and gift_id not in icons:
            url = await asyncio.to_thread(
                runtime.gift_icon_url, gift_id, item.get("image") or "")
            if url:
                icons[gift_id] = url
        # CDN URLは画面へ渡さない。使うのはproxy側だけで、渡すと失効した署名URLを
        # 画面が直に引きに行くことになる。
        item.pop("image", None)
    payload["icons"] = {str(gift_id): url for gift_id, url in icons.items()}
    return payload


@router.get("/api/streamers/{unique_id}/ranking")
async def streamer_gifter_ranking(unique_id: str, granularity: str = "month",
                                  period: str = "") -> dict:
    """Gifter / Battle Gifterを暦の期間(月・週・日)で切ったランキング。periodを省くと
    最新の期間を返す。profileとは別の口にしてあるのは、期間を変えるたびに通算集計
    (session全件・battle全件)を引き直さないためである。"""
    try:
        return await asyncio.to_thread(
            runtime.storage.streamer_gifter_ranking, unique_id, granularity, period)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/streamers/{unique_id}/matrix")
async def streamer_gifter_matrix(
    unique_id: str, granularity: str = "day", since: str = "", until: str = "",
    columns: int = 0,
) -> dict:
    """期間 × Gifter の一覧。rankingが1期間の断面なのに対し、こちらは期間を跨いで同じ人を
    横へ並べる。1回の応答にGifterとBattle Gifterの両方が入る。

    since/untilはカレンダーで選んだ日付('YYYY-MM-DD')で、その日の属する期間まで含む。
    """
    try:
        return await asyncio.to_thread(
            runtime.storage.streamer_gifter_matrix, unique_id, granularity,
            since, until, columns)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
