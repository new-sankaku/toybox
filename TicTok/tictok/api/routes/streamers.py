"""配信者・fan・発見候補の集計route。配信横断で「誰が」を見る側。"""

import asyncio
from fastapi import HTTPException
from pydantic import BaseModel, Field
from tictok.record import retention
from fastapi import APIRouter
from tictok.api import files
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


@router.get("/api/streamers/{unique_id}/highlights")
async def streamer_highlights(unique_id: str) -> dict:
    highlights = await asyncio.to_thread(runtime.storage.streamer_highlights, unique_id)
    return {"highlights": highlights}


def _recording_file_summary(recording: dict, busy_ids: set) -> dict:
    """1録画の「今ディスクに何が残っているか」。DBのbytesではなく実fileをstatする。

    recordings.bytesは録画完了時の値で、fileを消しても残る。容量整理の画面はこれを
    信じてはならない(消えたはずの容量を消せると表示してしまう)。"""
    try:
        path = files._safe_recording_path(recording["path"]) if recording.get("path") else None
    except HTTPException:
        path = None
    mp4_bytes = 0
    derived_bytes = 0
    if path is not None:
        try:
            mp4_bytes = path.stat().st_size if path.is_file() else 0
        except OSError:
            mp4_bytes = 0
        derived_bytes = retention.artifact_bytes(files._recording_derived_paths(path))
    ts_dirs = files._recording_ts_dirs(recording)
    ts_bytes = sum(files._dir_bytes(d) for d in ts_dirs)
    return {
        "id": recording["id"],
        "session_id": recording.get("session_id"),
        "filename": recording.get("filename"),
        "status": recording.get("status"),
        "protected": bool(recording.get("protected")),
        "started_at": recording.get("started_at"),
        "ended_at": recording.get("ended_at"),
        "mp4_exists": mp4_bytes > 0,
        "mp4_bytes": mp4_bytes,
        # 派生物はmp4を消すとき道連れになる。合計容量の内訳として別枠で見せる。
        "derived_bytes": derived_bytes,
        "ts_exists": bool(ts_dirs),
        "ts_bytes": ts_bytes,
        # 消せない理由。UIはこれを見てcheckboxを閉じる(理由の判断をUIへ複製しない)。
        "busy": recording["id"] in busy_ids or recording.get("status") == "recording",
    }


@router.get("/api/streamers/{unique_id}/recordings")
async def streamer_recordings(unique_id: str) -> dict:
    """容量整理用の録画一覧。mp4とHLSを別々に集計して返す。"""
    handle = runtime._normalize_unique_id(unique_id)

    def _collect() -> list:
        recordings = runtime.storage.recordings_for_user(handle)
        busy_ids = runtime.storage.busy_recording_ids()
        return [_recording_file_summary(rec, busy_ids) for rec in recordings]

    items = await asyncio.to_thread(_collect)
    return {
        "unique_id": handle,
        "recordings": items,
        "total_mp4_bytes": sum(i["mp4_bytes"] + i["derived_bytes"] for i in items),
        "total_ts_bytes": sum(i["ts_bytes"] for i in items),
    }


class DeleteRecordingFilesRequest(BaseModel):
    # 「mp4を消す録画」「HLSを消す録画」を別listで受ける。片方だけ消す使い方
    # (mp4は残してHLSの残骸だけ掃く)が主目的なので、1件1flagにはしない。
    mp4_ids: list[int] = Field(default_factory=list, max_length=2000)
    ts_ids: list[int] = Field(default_factory=list, max_length=2000)


@router.post("/api/streamers/{unique_id}/recordings/delete-files")
async def delete_streamer_recording_files(
    unique_id: str, payload: DeleteRecordingFilesRequest,
) -> dict:
    """選択した録画のmp4/HLSをdiskから消す。recordings行は残す。

    行を消さないのは、転写・検索hit・bookmark・切り出しlist・解析がrecording idに
    ぶら下がっており(いずれもON DELETE CASCADE)、容量を空けたいだけの操作でそれらを
    道連れにしないため。file不在は行のflagではなく実在確認で表す。"""
    handle = runtime._normalize_unique_id(unique_id)
    requested = set(payload.mp4_ids) | set(payload.ts_ids)
    if not requested:
        raise HTTPException(status_code=400, detail="削除対象が選択されていません。")

    def _delete() -> dict:
        owned = {rec["id"]: rec for rec in runtime.storage.recordings_for_user(handle)}
        # 他の配信者の録画idを混ぜて投げられても、この配信者の持ち物しか触らない。
        unknown = sorted(requested - owned.keys())
        if unknown:
            raise HTTPException(
                status_code=404,
                detail=f"@{handle} の録画に存在しないidが含まれています: {unknown[:5]}",
            )
        busy_ids = runtime.storage.busy_recording_ids()
        blocked = sorted(
            rid for rid in requested
            if rid in busy_ids or owned[rid].get("status") == "recording"
        )
        if blocked:
            raise HTTPException(
                status_code=409,
                detail=f"録画中または処理中のためfileを削除できません: {blocked[:5]}",
            )
        freed = 0
        mp4_deleted = 0
        ts_deleted = 0
        for rid in payload.mp4_ids:
            recording = owned[rid]
            try:
                path = files._safe_recording_path(recording["path"]) if recording.get("path") else None
            except HTTPException:
                path = None
            if path is None:
                continue
            freed += files._unlink_quietly([path, *files._recording_derived_paths(path)])
            mp4_deleted += 1
        for rid in payload.ts_ids:
            ts_freed = files._remove_recording_ts(owned[rid])
            if ts_freed or not files._recording_ts_dirs(owned[rid]):
                ts_deleted += 1
            freed += ts_freed
        return {"freed_bytes": freed, "mp4_deleted": mp4_deleted, "ts_deleted": ts_deleted}

    result = await asyncio.to_thread(_delete)
    await asyncio.to_thread(
        runtime.storage.record_ops_event,
        runtime.logger,
        "storage.recording_files_deleted",
        f"@{handle} の録画fileを削除しました",
        detail={"unique_id": handle, "mp4_ids": payload.mp4_ids,
                "ts_ids": payload.ts_ids, **result},
    )
    return result
