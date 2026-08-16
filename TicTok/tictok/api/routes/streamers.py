"""配信者・fan・発見候補の集計route。配信横断で「誰が」を見る側。"""

import asyncio
from fastapi import APIRouter, HTTPException
from tictok.api import runtime

router = APIRouter()


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
