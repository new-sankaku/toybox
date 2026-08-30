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
from tictok.api import battles
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


# マージ表示で一度に選べるSession数の上限。DeleteUsersRequestと同じ考えで、URLと
# 1requestの読み取り量が青天井にならないところで止める。
MERGE_MAX_SESSIONS = 500

# 合算できる集計。最大同接だけは合算ではなくMAX(同時に居た人数は足し算にならない)。
MERGE_SUM_STATS = (
    "gifts", "diamonds", "comments", "likes_total", "follows",
    "shares", "joins", "battles", "battle_points",
)
MERGE_MAX_STATS = ("viewers_peak",)


def _parse_session_ids(ids: str) -> list:
    """``?ids=1,2,3`` を重複なしのint列にする。並びは指定順を保つ。"""
    parsed: list = []
    seen: set = set()
    for chunk in (ids or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            value = int(chunk)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Session idが数値ではありません: {chunk}")
        if value not in seen:
            seen.add(value)
            parsed.append(value)
    if not parsed:
        raise HTTPException(status_code=400, detail="Session idが指定されていません。")
    if len(parsed) > MERGE_MAX_SESSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"一度にマージできるSessionは{MERGE_MAX_SESSIONS}件までです。",
        )
    return parsed


def _merged_stats(sessions: list) -> dict:
    """選択したsessionの通算。最大同接はMAX、収集時間は各sessionの長さの合算。

    平均同接はここに出さない。あれは階段保持積分で宝箱窓を除いて出す値で、session跨ぎでは
    積分をやり直さないと出せない — 各sessionの平均を平均すると、長さの違うsessionが同じ
    重みで混ざった別物になる。"""
    stats = {key: 0 for key in MERGE_SUM_STATS}
    for key in MERGE_MAX_STATS:
        stats[key] = 0
    duration = 0.0
    for session in sessions:
        source = session.get("stats") or {}
        for key in MERGE_SUM_STATS:
            stats[key] += source.get(key) or 0
        for key in MERGE_MAX_STATS:
            stats[key] = max(stats[key], source.get(key) or 0)
        if session.get("ended_at"):
            duration += max(0.0, session["ended_at"] - session["started_at"])
    stats["duration"] = duration
    return stats


def _merge_sessions_or_404(session_ids: list) -> list:
    """指定順のsession行。収集中のsessionはlive collectorのstatsで上書きする
    (stats_jsonはfinalizeでしか書かれないため、そのままでは古い値が混ざる)。"""
    sessions = [runtime._get_session_or_404(session_id) for session_id in session_ids]
    active = runtime.manager.active_session_ids()
    for session in sessions:
        if session["id"] not in active:
            continue
        collector = runtime.manager.get(session["unique_id"])
        if collector is not None and collector.session_id == session["id"]:
            session["stats"] = collector.stats
    return sessions


@router.get("/api/sessions/merged")
async def merged_sessions(ids: str) -> dict:
    """複数sessionをまとめて1つの詳細として返す。

    ``/api/sessions/{session_id}`` より前に置くこと。後ろに置くと "merged" が
    ``session_id: int`` に食われて422になる。

    timelineは返さない。bucketは絶対時刻を持つので、別日のsessionを1本の軸へ並べても
    大半が空白になる。画面側もマージ中はSession Timelineを出さない。"""
    session_ids = _parse_session_ids(ids)
    sessions = await asyncio.to_thread(_merge_sessions_or_404, session_ids)

    # 貢献集計・録画・コラボはどれも同期のDB/filesystem読み。session数ぶん並ぶので、
    # 素のまま置くとevent loopをその間ずっと掴む(session_detailと同じ理由)。
    def _read() -> dict:
        transcribed = runtime.storage.transcribed_recording_ids()
        recordings: list = []
        collabs: list = []
        for session in sessions:
            for rec in runtime.storage.recordings_for_session(session["id"]):
                rec["has_transcript"] = rec["id"] in transcribed
                rec["has_output"] = fsfacts._output_done(rec.get("path"))
                rec["has_up_output"] = bool(rec.get("path")) and upscale_done(Path(rec["path"]))
                rec["media"] = files._recording_media_kinds(rec)
                rec["file_exists"] = bool(rec["media"])
                recordings.append(rec)
            for window in runtime.storage.collab_windows_for_session(session["id"]):
                window["session_id"] = session["id"]
                collabs.append(window)
        return {
            "summary": _summary_with_gift_icons(
                runtime.storage.sessions_summary([s["id"] for s in sessions])),
            "recordings": recordings,
            "collabs": collabs,
        }

    payload = await asyncio.to_thread(_read)
    battles: list = []
    for session in sessions:
        owner = _session_owner(session)
        for battle in await _battles_for_session(session):
            # カードは自陣がどちらかをownerで決める。配信者を跨いだ選択では1つに
            # 決まらないので、Battleごとにその配信者を連れて行く。
            battle["session_id"] = session["id"]
            battle["owner"] = owner
            battles.append(battle)
    return {
        "sessions": sessions,
        "stats": _merged_stats(sessions),
        **payload,
        "battles": battles,
    }


EVENT_EXPORT_COLUMNS = [
    "time", "kind", "user_unique_id", "user_nickname", "comment", "text",
    "gift_name", "gift_count", "diamonds", "like_count",
]


def _event_export_row(event) -> list:
    return [
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


@router.get("/api/sessions/merged/export.csv")
async def export_merged_csv(ids: str) -> Response:
    """選択したsessionのeventを1本のCSVに繋ぐ。どのsessionの行かは先頭2列で分かる
    (単体exportと列が違うのは、混ざった行を区別できないと合算の検算ができないため)。"""
    session_ids = _parse_session_ids(ids)
    sessions = await asyncio.to_thread(_merge_sessions_or_404, session_ids)
    events_by_session = await asyncio.to_thread(
        lambda: [(s, runtime.storage.iter_events(s["id"])) for s in sessions])

    def _rows():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["session_id", "session_unique_id", *EVENT_EXPORT_COLUMNS])
        yield "\ufeff" + buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        for session, events in events_by_session:
            for event in events:
                writer.writerow([session["id"], session["unique_id"], *_event_export_row(event)])
                yield buffer.getvalue()
                buffer.seek(0)
                buffer.truncate(0)

    filename = f"tictok_merged_{len(sessions)}sessions.csv"
    return StreamingResponse(
        _rows(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/sessions/merged/export.json")
async def export_merged_json(ids: str) -> Response:
    """マージ表示と同じ集計 + session別のevent。timelineは入れない(合算しない値なので、
    file側にだけ在ると画面に無い軸を持ち込むことになる)。"""
    session_ids = _parse_session_ids(ids)
    sessions = await asyncio.to_thread(_merge_sessions_or_404, session_ids)

    def _build() -> str:
        payload = {
            "sessions": sessions,
            "stats": _merged_stats(sessions),
            "summary": runtime.storage.sessions_summary([s["id"] for s in sessions]),
            "events": [
                {"session_id": s["id"], "session_unique_id": s["unique_id"],
                 "events": runtime.storage.iter_events(s["id"])}
                for s in sessions
            ],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    content = await asyncio.to_thread(_build)
    filename = f"tictok_merged_{len(sessions)}sessions.json"
    return Response(
        content=content,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
            "summary": _summary_with_gift_icons(runtime.storage.session_summary(session_id)),
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


def _summary_with_gift_icons(summary: dict) -> dict:
    """summaryにgift_id→icon URLの対応を添える。

    URLはgift単位で1本あればよいので、行ごとに持たせず1つのmapにまとめる。iconを出せない
    giftはmapに載らない — icon画像が無いことは「そのgiftが飛ばなかった」ではないので、
    行そのものは名前だけで残す。"""
    sources: dict = {}
    for gift in summary.get("gifts") or []:
        gift_id = int(gift.get("gift_id") or 0)
        if gift_id and not sources.get(gift_id):
            sources[gift_id] = gift.get("gift_image") or ""
    for user in summary.get("users") or []:
        for item in (user.get("items") or {}).values():
            gift_id = int(item.get("gift_id") or 0)
            if gift_id and not sources.get(gift_id):
                sources[gift_id] = item.get("gift_image") or ""
    icons = {}
    for gift_id, image_url in sources.items():
        url = runtime.gift_icon_url(gift_id, image_url)
        if url:
            icons[str(gift_id)] = url
    summary["gift_icons"] = icons
    return summary


async def _battles_for_session(session: dict) -> list:
    """そのsessionのBattle一覧(収集中はlive collector、終わっていればDB)。

    分岐の本体は :mod:`tictok.api.battles` にある — 再生画面(録画)側も同じ一覧を引くので、
    経路ごとに書くと片方だけが収集中のsessionでPKを出さない状態になる。"""
    return await battles.battles_for_session(session["unique_id"], session["id"])


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


@router.get("/api/sessions/{session_id}/battle-series/{battle_id}")
async def session_battle_series(session_id: int, battle_id: int) -> dict:
    """1戦のscore推移(時系列)だけを返す軽い経路。

    session丸ごとのbattles(中央値183KB・最大1.1MB。貢献者一覧とグローブ判定を含む)を
    曲線1本のために引かせないための分割。相手別のscoreが要る(個人マルチ/チーム戦では
    opp_scoreは最強の敵陣であって特定の相手の値ではない)ので、参加者別のsampleも返す。"""
    session = await asyncio.to_thread(runtime._get_session_or_404, session_id)
    fought = await _battles_for_session(session)
    battle = next((b for b in fought if b.get("battle_id") == battle_id), None)
    if battle is None:
        raise HTTPException(status_code=404, detail="そのBattleは見つかりません。")
    return {
        "battle_id": battle_id,
        "start_time": battle.get("start_time"),
        "end_time": battle.get("end_time"),
        "type": battle.get("type") or "personal",
        "result": battle.get("result"),
        "participants": [
            {
                "user_id": p.get("user_id", ""),
                "nickname": p.get("nickname", ""),
                "is_own": bool(p.get("is_own")),
                "side": p.get("side"),
            }
            for p in (battle.get("participants") or [])
        ],
        "series": [
            {
                "t": s.get("t"),
                "own": s.get("own", 0) or 0,
                "opp": s.get("opp", 0) or 0,
                "parts": [
                    {"id": p.get("id", ""), "score": p.get("score", 0) or 0}
                    for p in (s.get("parts") or [])
                ],
            }
            for s in (battle.get("score_series") or [])
        ],
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
        writer.writerow(EVENT_EXPORT_COLUMNS)
        yield "\ufeff" + buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        for event in events:
            writer.writerow(_event_export_row(event))
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
