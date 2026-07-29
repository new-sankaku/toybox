"""1回の配信(session)の一覧・詳細・battle/collab・note・削除・export、および順位表。"""

import asyncio
import csv
import io
import json
from collections import Counter
from pathlib import Path
from typing import Optional
from fastapi import HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from tictok.record.upscale import upscale_done
from fastapi import APIRouter
from tictok.api import files
from tictok.api import fsfacts
from tictok.api import runtime

router = APIRouter()


class NoteRequest(BaseModel):
    note: str = Field(max_length=10000)


class DeleteUsersRequest(BaseModel):
    unique_ids: list[str] = Field(min_length=1, max_length=500)


@router.get("/api/sessions")
async def list_sessions(limit: Optional[int] = None) -> dict:
    # limit省略時は設定の既定上限、limit<=0は全件(履歴のfilter/検索が最新N件で頭打ちにならないよう)。
    effective_limit = runtime.settings.get("session_list_limit") if limit is None else limit
    sessions = await asyncio.to_thread(runtime.storage.list_sessions, effective_limit)
    briefs = await asyncio.to_thread(runtime.storage.recordings_brief)
    active = runtime.manager.active_session_ids()
    # Per-session done badges: a Session is "済" only when every finished recording is
    # transcribed / output (all-done), so a partial Session still reads as not done.
    by_session: dict = {}
    for brief in briefs:
        by_session.setdefault(brief["session_id"], []).append(brief)
    # 出力済みbadgeは録画ごとにfileをstatして決める。録画346本で実測90〜140msかかり、
    # event loop上で回すとその間WSの配信も他のrequestも止まる(この画面は収集中1回/秒で
    # 叩かれる)。TTL cacheは効くがcacheが切れた回に必ず払うので、まとめて別threadへ出す。
    def _output_states() -> dict:
        return {sid: [fsfacts._recording_output_state(b["path"]) for b in recs]
                for sid, recs in by_session.items()}

    states_by_session = await asyncio.to_thread(_output_states)
    # stats_json is persisted only at finalize, so a still-collecting session would
    # otherwise show stale/empty counts (battles included). Overlay the live stats.
    for session in sessions:
        recs = by_session.get(session["id"], [])
        states = states_by_session.get(session["id"], [])
        session["transcript_done"] = bool(recs) and all(b["has_transcript"] for b in recs)
        session["output_done"] = bool(recs) and all(s[0] for s in states)
        session["up_output_done"] = bool(recs) and all(s[1] for s in states)
        if session["id"] in active:
            collector = runtime.manager.get(session["unique_id"])
            if collector is not None and collector.session_id == session["id"]:
                session["stats"] = collector.stats
    return {
        "sessions": sessions,
        "active_session_ids": sorted(active),
    }


@router.get("/api/sessions/{session_id}")
async def session_detail(session_id: int) -> dict:
    session = await asyncio.to_thread(runtime._get_session_or_404, session_id)

    # timeline・summary・録画ごとのfile stat はどれも同期のDB/filesystem読みで、
    # 素のまま並べるとevent loopを掴んだまま数十ms止まる。live collectorを見る部分
    # (battlesの収集中の枝)だけはevent loop側に残す — あれはprocess内のsnapshotで、
    # 別threadから覗くと収集中のcollectorが書き換えている最中の状態を掴む
    # (枝の分かれ方は ``_battles_for_session`` を参照)。
    def _read() -> dict:
        timeline = runtime.storage.session_timeline(session_id)
        timeline["bucket_seconds"] = session["bucket_seconds"]
        recordings = runtime.storage.recordings_for_session(session_id)
        transcribed = runtime.storage.transcribed_recording_ids()
        for rec in recordings:
            rec["has_transcript"] = rec["id"] in transcribed
            rec["has_output"] = fsfacts._output_done(rec.get("path"))
            rec["has_up_output"] = bool(rec.get("path")) and upscale_done(Path(rec["path"]))
            rec["media"] = files._recording_media_kinds(rec)
            rec["file_exists"] = bool(rec["media"])
        return {
            "timeline": timeline,
            "recordings": recordings,
            "summary": runtime.storage.session_summary(session_id),
            # 宝箱/Portalの実測。collectorがcheckpointで書くので、収集中でも直近まで読める。
            "envelopes": runtime.storage.session_envelopes(session_id),
        }

    payload = await asyncio.to_thread(_read)
    return {
        "session": session,
        **payload,
        "owner": _session_owner(session),
        "battles": await _battles_for_session(session),
    }


async def _battles_for_session(session: dict) -> list:
    """Battles are persisted only when the session ends (_persist_final). While the
    session is still collecting, the live collector holds the authoritative, updating
    battle list, so serve that; once ended, read the saved rows.

    どちらの経路も勝敗はcore.battleの確定判定へ揃えて返す(live側はbattles_snapshot、
    保存側はbattles_for_sessionがannotate_result済み)。

    live側だけevent loopに残すのは、あれがprocess内のsnapshotで、別threadから覗くと
    収集中のcollectorが書き換えている最中の状態を掴むため。終わったsessionを読む側は
    DBなので、書き込みlockを待つあいだloopを明け渡す。"""
    collector = runtime.manager.get(session["unique_id"])
    if collector is not None and collector.session_id == session["id"]:
        return collector.battles_snapshot()["battles"]
    return await asyncio.to_thread(runtime.storage.battles_for_session, session["id"])


def _session_owner(session: dict) -> dict:
    """Owner identity for a stored session, so battle cards can render the monitored
    streamer's name/avatar (the own host) the same way the live snapshot does."""
    return {
        "unique_id": session["unique_id"],
        "nickname": session.get("owner_nickname") or session["unique_id"],
        "avatar": session.get("owner_avatar") or "",
    }


@router.get("/api/sessions/{session_id}/battles")
async def session_battles(session_id: int) -> dict:
    session = await asyncio.to_thread(runtime._get_session_or_404, session_id)
    return {
        "unique_id": session["unique_id"],
        "owner": _session_owner(session),
        "battles": await _battles_for_session(session),
    }


@router.get("/api/sessions/{session_id}/collabs")
async def session_collabs(session_id: int) -> dict:
    """コラボ(非BattleのLinkMic)接続窓の一覧。

    Battleと違い、進行中sessionでもcollectorではなくDBを読む。collectorは窓を確定した時点と
    定期checkpointでsave_collab_windowsへ書き出しており(未クローズの窓も現在時刻を終端として
    含む)、公開snapshot APIを持たないため。よって進行中sessionの最後の窓は最大でcheckpoint
    間隔ぶん古いことがある。"""
    await asyncio.to_thread(runtime._get_session_or_404, session_id)
    windows = await asyncio.to_thread(runtime.storage.collab_windows_for_session, session_id)
    return {"session_id": session_id, "collabs": windows}


@router.patch("/api/sessions/{session_id}")
async def update_session_note(session_id: int, request: NoteRequest) -> dict:
    await asyncio.to_thread(runtime._get_session_or_404, session_id)
    await asyncio.to_thread(runtime.storage.set_note, session_id, request.note)
    return {"id": session_id, "note": request.note}


@router.delete("/api/sessions/{session_id}")
async def delete_session(session_id: int) -> dict:
    await asyncio.to_thread(runtime._get_session_or_404, session_id)
    # 収集中かの判定は live collector のsnapshotなので event loop 側に残す。別threadから
    # 覗くと、収集中のcollectorが書き換えている最中の集合を掴む(session_detail と同じ理由)。
    if session_id in runtime.manager.active_session_ids():
        raise HTTPException(status_code=409, detail="収集中のSessionは削除できません。先に停止してください。")

    # DB読み・録画fileの削除・DB削除をまとめてthreadへ出す。file削除まで含めて重く、
    # 素のまま並べると削除の間ずっとevent loopが止まる。
    def _delete() -> Counter:
        kept = Counter(files._delete_session_recording(recording)
                       for recording in runtime.storage.recordings_for_session(session_id))
        runtime.storage.delete_session(session_id)
        return kept

    kept = await asyncio.to_thread(_delete)
    return {"deleted": session_id, "recordings": dict(kept)}


@router.post("/api/sessions/delete-by-users")
async def delete_sessions_by_users(request: DeleteUsersRequest) -> dict:
    """Delete every session belonging to the given streamers. Handle renames are
    followed via owner identity so a streamer's whole history is removed. Blocks if any
    target streamer is still collecting.

    録画の原本は消さない。素材(.ts)はそのまま残し、素材を持たない録画のmp4も残す
    (_delete_session_recording参照)。原本を捨てるのは単体録画の削除endpointの役目である。"""
    session_ids = await asyncio.to_thread(
        runtime.storage.session_ids_for_users, request.unique_ids)
    if not session_ids:
        return {"deleted_sessions": 0}
    # 収集中かの判定は live collector のsnapshot。event loop 側に残す(delete_session と同じ)。
    active = runtime.manager.active_session_ids()
    if any(session_id in active for session_id in session_ids):
        raise HTTPException(
            status_code=409,
            detail="収集中のSessionを含む配信者は削除できません。先に停止してください。",
        )

    # 配信者まるごとの削除はsession数ぶんのDB削除とfile削除になる。1件ずつthreadへ出すと
    # 往復だけで嵩むので、まとめて1回で出す。
    def _delete() -> tuple:
        kept: Counter = Counter()
        for session_id in session_ids:
            for recording in runtime.storage.recordings_for_session(session_id):
                kept[files._delete_session_recording(recording)] += 1
        deleted = sum(1 for session_id in session_ids
                      if runtime.storage.delete_session(session_id))
        return kept, deleted

    kept, deleted = await asyncio.to_thread(_delete)
    return {"deleted_sessions": deleted, "recordings": dict(kept)}


@router.get("/api/sessions/{session_id}/export.csv")
async def export_session_csv(session_id: int) -> Response:
    session = await asyncio.to_thread(runtime._get_session_or_404, session_id)
    events = await asyncio.to_thread(runtime.storage.iter_events, session_id)

    def _rows():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            ["time", "kind", "user_unique_id", "user_nickname", "comment", "text", "gift_name", "gift_count", "diamonds", "like_count"]
        )
        yield "\ufeff" + buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        for event in events:
            writer.writerow(
                [
                    event["time"],
                    event["kind"],
                    event["user_unique_id"] or "",
                    event["user_nickname"] or "",
                    event["comment"] or "",
                    event["text"] or "",
                    event["gift_name"] or "",
                    event["gift_count"] if event["gift_count"] is not None else "",
                    event["diamonds"] if event["diamonds"] is not None else "",
                    event["count"] if event["count"] is not None else "",
                ]
            )
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)

    filename = f"tictok_session_{session_id}_{session['unique_id']}.csv"
    return StreamingResponse(
        _rows(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/sessions/{session_id}/export.json")
async def export_session_json(session_id: int) -> Response:
    session = await asyncio.to_thread(runtime._get_session_or_404, session_id)

    def _build() -> str:
        payload = {
            "session": session,
            "summary": runtime.storage.session_summary(session_id),
            "timeline": runtime.storage.session_timeline(session_id),
            "events": runtime.storage.iter_events(session_id),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    content = await asyncio.to_thread(_build)
    filename = f"tictok_session_{session_id}_{session['unique_id']}.json"
    return Response(
        content=content,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


RANKING_STAT_KEYS = {
    "likes": "likes_total",
    "comments": "comments",
    "gifts": "diamonds",
    "battles": "battle_points",
}


@router.get("/api/rankings")
async def session_rankings() -> dict:
    rankings = await asyncio.to_thread(runtime.storage.session_rankings, runtime.settings.get("session_list_limit"))
    live_stats = {
        snap["session_id"]: snap["stats"]
        for snap in runtime.manager.snapshots()
        if snap.get("session_id") is not None
    }
    if live_stats:
        for metric, stat_key in RANKING_STAT_KEYS.items():
            entries = rankings[metric]
            for entry in entries:
                stats = live_stats.get(entry["session_id"])
                if stats is not None:
                    entry["value"] = stats.get(stat_key, entry["value"])
            entries.sort(key=lambda e: e["value"], reverse=True)
    return rankings
