"""検索(全文・意味)・cut list・bookmark・文字起こしqueue。

文字起こしのqueue操作をここへ置くのは、投入の動機が検索(見つけたい)だからで、
実行そのものは映像jobのqueue(``media_jobs``)が持つ。
"""

import asyncio
import os
import secrets
import time
import urllib.parse
from typing import Optional
from fastapi import HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from tictok.core.config import get_job_progress_min_interval_seconds
from tictok.record.transcription import stt_available, stt_status
from tictok.search import cutlist_export, indexer, semantic
from tictok.core.progress import IntervalGate
from fastapi import APIRouter
from tictok.api import files
from tictok.api import fsfacts
from tictok.api import media_jobs
from tictok.api import runtime

router = APIRouter()


@router.get("/api/stt/status")
async def stt_status_api() -> dict:
    return stt_status()


class EnqueueRequest(BaseModel):
    unique_id: Optional[str] = None
    recording_ids: Optional[list[int]] = None
    priority: int = 0


class CancelRequest(BaseModel):
    recording_ids: Optional[list[int]] = None


@router.get("/api/search")
async def search_api(q: str, sources: str = "stt,comment", unique_ids: str = "",
                     since: Optional[float] = None, until: Optional[float] = None,
                     order: str = "time", limit: int = 200, offset: int = 0) -> dict:
    """転写・comment・笑い声を横断して検索する。1件=1シーンで、video_timeへそのまま
    seekできる。"""
    wanted = [s for s in sources.split(",")
              if s in (indexer.SOURCE_STT, indexer.SOURCE_COMMENT, indexer.SOURCE_LAUGH)]
    ids = [u for u in unique_ids.split(",") if u]
    result = await asyncio.to_thread(
        runtime.storage.search_scenes, q, wanted, ids, since, until, order,
        max(1, min(limit, 500)), max(0, offset))
    return result


class CutRequest(BaseModel):
    recording_id: int
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    label: str = ""
    group_id: Optional[int] = None


class GroupRequest(BaseModel):
    name: str
    memo: str = ""


class GroupPatchRequest(BaseModel):
    name: Optional[str] = None
    memo: Optional[str] = None


class GroupOrderRequest(BaseModel):
    cut_ids: list[int]


class CutBulkRequest(BaseModel):
    op: str
    ids: list[int]
    group_id: Optional[int] = None


async def _require_group(group_id: int) -> dict:
    group = await asyncio.to_thread(runtime.storage.get_group, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="グループが見つかりません。")
    return group


# ===== 切り抜きグループ(group) =====
# cut_list/bookmarksの項目を「切り抜き動画1本のグループ」単位で束ねる。所属は排他で、
# グループ間の共用は行の複製(op=copy)で表す。


@router.get("/api/groups")
async def list_groups_api() -> dict:
    return {"items": await asyncio.to_thread(runtime.storage.list_groups)}


@router.post("/api/groups")
async def add_group_api(payload: GroupRequest) -> dict:
    """グループを作る。同名が既にあればそのグループを返す(検索語からの1-click作成を冪等にする)。"""
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="グループ名を入力してください。")
    return await asyncio.to_thread(runtime.storage.add_group, name, payload.memo)


@router.patch("/api/groups/{group_id}")
async def update_group_api(group_id: int, payload: GroupPatchRequest) -> dict:
    name = payload.name.strip() if payload.name is not None else None
    if payload.name is not None and not name:
        raise HTTPException(status_code=400, detail="グループ名を入力してください。")
    group = await asyncio.to_thread(
        runtime.storage.update_group, group_id, name, payload.memo)
    if group is None:
        raise HTTPException(status_code=404, detail="グループが見つかりません。")
    return group


@router.delete("/api/groups/{group_id}")
async def delete_group_api(group_id: int) -> dict:
    """グループを消す。中の項目は消えず未分類へ戻る(項目まで消したければ先にbulk deleteする)。"""
    if not await asyncio.to_thread(runtime.storage.delete_group, group_id):
        raise HTTPException(status_code=404, detail="グループが見つかりません。")
    return {"deleted": group_id}


@router.post("/api/groups/{group_id}/order")
async def reorder_group_api(group_id: int, payload: GroupOrderRequest) -> dict:
    """グループ内の並びをcut_idsの順へ振り直す。この並びがEDL/FCPXMLの書き出し順になる。"""
    await _require_group(group_id)
    ordered = await asyncio.to_thread(
        runtime.storage.reorder_group_cuts, group_id, payload.cut_ids)
    return {"ordered": ordered}


@router.post("/api/cutlist/bulk")
async def cutlist_bulk_api(payload: CutBulkRequest) -> dict:
    """cut listの一括操作。move=所属変更、copy=行を複製して別グループへ、delete=削除。
    group_id=Noneは未分類を指す。"""
    if payload.op not in ("move", "copy", "delete"):
        raise HTTPException(status_code=400,
                            detail="opはmove/copy/deleteのいずれかを指定してください。")
    if not payload.ids:
        raise HTTPException(status_code=400, detail="対象を選んでください。")
    if payload.op in ("move", "copy") and payload.group_id is not None:
        await _require_group(payload.group_id)
    if payload.op == "move":
        affected = await asyncio.to_thread(
            runtime.storage.move_cuts_to_group, payload.ids, payload.group_id)
    elif payload.op == "copy":
        affected = await asyncio.to_thread(
            runtime.storage.copy_cuts_to_group, payload.ids, payload.group_id)
    else:
        affected = await asyncio.to_thread(runtime.storage.delete_cuts, payload.ids)
    return {"affected": affected}


@router.post("/api/bookmarks/bulk")
async def bookmarks_bulk_api(payload: CutBulkRequest) -> dict:
    """見どころの一括操作。move=所属変更、delete=削除。見どころは並びもIN/OUTも
    持たないので、cut listと違いcopy(行の複製)は無い — 同じ位置の見どころを2つ持っても
    区別が付かず、片方が消し忘れとして残るだけになる。"""
    if payload.op not in ("move", "delete"):
        raise HTTPException(status_code=400,
                            detail="opはmove/deleteのいずれかを指定してください。")
    if not payload.ids:
        raise HTTPException(status_code=400, detail="対象を選んでください。")
    if payload.op == "move":
        if payload.group_id is not None:
            await _require_group(payload.group_id)
        affected = await asyncio.to_thread(
            runtime.storage.set_bookmark_group, payload.ids, payload.group_id)
    else:
        affected = await asyncio.to_thread(runtime.storage.delete_bookmarks, payload.ids)
    return {"affected": affected}


@router.get("/api/cutlist")
async def list_cutlist_api() -> dict:
    """cut listを返す。pathは移動後の実体を指すよう解決し直す。

    読みも解決も1回のthread呼び出しにまとめる。以前はcut 1件ごとにto_threadを跨いで
    get_recordingを引き、**path解決(実fileのstat)はloop側**に残っていたので、cutが増える
    ほどserverが止まる時間が伸びていた。同じ録画を指すcutは1回だけ解決する。"""
    def _collect() -> list:
        cuts = runtime.storage.list_cuts()
        resolved: dict = {}
        for cut in cuts:
            if not cut.get("path"):
                continue
            recording_id = cut["recording_id"]
            if recording_id not in resolved:
                recording = runtime.storage.get_recording(recording_id)
                resolved[recording_id] = (
                    str(files._resolved_recording_path(recording))
                    if recording is not None else None)
            if resolved[recording_id] is not None:
                cut["path"] = resolved[recording_id]
        return cuts

    return {"items": await asyncio.to_thread(_collect)}


@router.post("/api/cutlist")
async def add_cut_api(payload: CutRequest) -> dict:
    recording = await asyncio.to_thread(runtime.storage.get_recording, payload.recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    if payload.end <= payload.start:
        raise HTTPException(status_code=400, detail="終了位置は開始位置より後にしてください。")
    if payload.group_id is not None:
        await _require_group(payload.group_id)
    return await asyncio.to_thread(
        runtime.storage.add_cut, payload.recording_id, recording["unique_id"],
        payload.start, payload.end, payload.label, payload.group_id)


class CutPatchRequest(BaseModel):
    label: str = ""


@router.patch("/api/cutlist/{cut_id}")
async def update_cut_api(cut_id: int, payload: CutPatchRequest) -> dict:
    """cutのlabelだけを直す。labelは書き出しfile名・EDL/FCPXMLのclip名になるので、
    見どころのメモから引き継いだままでは直せないと最終成果物にそのまま残る。"""
    label = payload.label.strip()
    if not await asyncio.to_thread(runtime.storage.update_cut_label, cut_id, label):
        raise HTTPException(status_code=404, detail="対象が見つかりません。")
    return {"id": cut_id, "label": label}


@router.delete("/api/cutlist/{cut_id}")
async def delete_cut_api(cut_id: int) -> dict:
    if not await asyncio.to_thread(runtime.storage.delete_cut, cut_id):
        raise HTTPException(status_code=404, detail="対象が見つかりません。")
    return {"deleted": cut_id}


def _parse_group_param(group: str) -> tuple:
    """query paramのgroup指定を(group_id, only_ungrouped)へ。'':全て / 'none':未分類 /
    数字:そのグループ。export・一括削除が同じ書式を使う。"""
    if not group:
        return None, False
    if group == "none":
        return None, True
    try:
        return int(group), False
    except ValueError:
        raise HTTPException(status_code=400,
                            detail="groupはグループのid、none、または空を指定してください。")


@router.delete("/api/cutlist")
async def clear_cutlist_api(group: str = "") -> dict:
    """一括削除。group=idでそのグループの分だけ、group=noneで未分類だけを消す。"""
    group_id, only_ungrouped = _parse_group_param(group)
    if group_id is not None:
        await _require_group(group_id)
    return {"deleted": await asyncio.to_thread(
        runtime.storage.clear_cuts, group_id, only_ungrouped)}


@router.get("/api/cutlist/export")
async def export_cutlist_api(format: str = "csv", unique_ids: str = "",
                             group: str = "") -> Response:
    """cut listをCSV/EDL/FCPXMLで書き出す。mp4を出さずに範囲だけ渡せば再encodeが要らない。

    EDL/FCPXMLはframeが最小単位なので、素材のfpsをffprobeで実測してから組み立てる
    (既定値で埋めるとNLE上の位置が素材ごとにずれる)。実測できない素材が混ざる場合は
    frame基準の形式を出さずにerrorへ倒す。

    実測では配信者ごとにfpsが違う(25/60fpsの実例)。EDLはlist全体で1 frame rateしか
    持てないため、配信者を跨いで出すとほぼ確実に混在で止まる。unique_idsで配信者を
    絞って出すか、素材ごとにframe rateを持てるFCPXMLを使うこと。"""
    if format not in ("csv", "edl", "fcpxml"):
        raise HTTPException(status_code=400,
                            detail="formatはcsv/edl/fcpxmlのいずれかを指定してください。")
    wanted = {u for u in unique_ids.split(",") if u}
    group_id, only_ungrouped = _parse_group_param(group)
    group_row = await _require_group(group_id) if group_id is not None else None
    cuts = (await list_cutlist_api())["items"]
    if wanted:
        cuts = [c for c in cuts if c["unique_id"] in wanted]
    if group_id is not None:
        # グループ単位はposition順で出す。この並びがそのままNLEのtimeline順になる。
        cuts = [c for c in cuts if c.get("group_id") == group_id]
        cuts.sort(key=lambda c: (c.get("position") is None, c.get("position") or 0,
                                 c["start"], c["id"]))
    elif only_ungrouped:
        cuts = [c for c in cuts if c.get("group_id") is None]
    # 素材ごとに逐次ffprobeを回すので、cutが多いと待たされる。job台帳へ出しておけば
    # 「押したのに無反応」ではなく「いま何本目を測っているか」が見える。
    async with runtime._tracked_job("cutlist", f"cut listの書き出し（{format}）") as job_id:
        async def _probe_progress(done: int, total: int) -> None:
            await runtime.jobs.progress(job_id, int(done * 100 / total) if total else 100,
                                stage=f"素材のframe rateを実測中（{done}/{total}本）")

        cuts = await cutlist_export.resolve_timebases(cuts, _probe_progress)
    # グループ単位の書き出しはtitle/file名もグループ名にする。NLE上でどのグループのtimelineかを
    # fileの名前が名乗れないと、複数グループを出し分けた瞬間に取り違える。
    title = group_row["name"] if group_row else "tictok_cutlist"
    try:
        if format == "csv":
            body = cutlist_export.to_csv(cuts)
            media_type, filename = "text/csv; charset=utf-8", "tictok_cutlist.csv"
        elif format == "edl":
            body = cutlist_export.to_edl(cuts, title=title)
            media_type, filename = "text/plain; charset=utf-8", "tictok_cutlist.edl"
        else:
            body = cutlist_export.to_fcpxml(cuts, name=title)
            media_type, filename = "application/xml; charset=utf-8", "tictok_cutlist.fcpxml"
    except cutlist_export.CutlistExportError as exc:
        runtime.logger.warning(
            "cutlistの書き出しを拒否しました（%s）: %s", format, exc, exc_info=True,
            extra={"event": "cutlist.export_refused",
                   "ctx": {"format": format, "cuts": len(cuts)}},
        )
        raise HTTPException(status_code=400, detail=str(exc))
    disposition = f'attachment; filename="{filename}"'
    if group_row:
        # HTTP headerはlatin-1しか運べないため、グループ名(日本語)のfile名はRFC 5987の
        # filename*で併記する。filename=はそれを読めないclient向けのASCII fallback。
        extension = filename.rsplit(".", 1)[-1]
        disposition += (
            "; filename*=UTF-8''"
            + urllib.parse.quote(f"{group_row['name']}.{extension}")
        )
    return Response(
        content=body.encode("utf-8-sig" if format == "csv" else "utf-8"),
        media_type=media_type,
        headers={"Content-Disposition": disposition},
    )


class BookmarkRequest(BaseModel):
    recording_id: int
    start: float = Field(ge=0)
    end: Optional[float] = None
    memo: str = ""
    source_hit_id: Optional[int] = None
    group_id: Optional[int] = None


class BookmarkPatchRequest(BaseModel):
    """部分更新。group_id=Noneは「未分類へ戻す」を意味するので、更新の有無は
    model_fields_setで判定する(Noneを既定値と読み違えると所属が黙って外れる)。"""
    memo: Optional[str] = None
    group_id: Optional[int] = None


@router.get("/api/bookmarks")
async def list_bookmarks_api(recording_id: Optional[int] = None) -> dict:
    """見どころ一覧。recording_id指定で1録画分(seek barのmarker用)、無指定で全録画分。"""
    return {"items": await asyncio.to_thread(runtime.storage.list_bookmarks, recording_id)}


@router.post("/api/bookmarks")
async def add_bookmark_api(payload: BookmarkRequest) -> dict:
    """見どころを1件記録する。endを省くと点(コメント1件や現在位置)として残る。"""
    recording = await asyncio.to_thread(runtime.storage.get_recording, payload.recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    if payload.end is not None and payload.end <= payload.start:
        raise HTTPException(status_code=400, detail="終了位置は開始位置より後にしてください。")
    if payload.group_id is not None:
        await _require_group(payload.group_id)
    return await asyncio.to_thread(
        runtime.storage.add_bookmark, payload.recording_id, recording["unique_id"],
        payload.start, payload.end, payload.memo, payload.source_hit_id,
        payload.group_id)


class LiveBookmarkRequest(BaseModel):
    memo: str = ""


@router.post("/api/monitors/{unique_id}/bookmark")
async def add_live_bookmark_api(unique_id: str, payload: LiveBookmarkRequest) -> dict:
    """配信を見ている最中に見どころを1件記録する。

    時刻はServerが今この瞬間で打つ。押した時刻をclientから受け取ると、browserの時計ずれが
    そのまま印のずれになるうえ、収集側の時計(録画のstarted_at)と別の時計を混ぜることになる。

    録画中でなければ409で断る。見どころは動画の中の位置を指すものなので、録画が無ければ
    後から戻る先が無く、置いても再生できない印が残るだけである(session全体に対する印が要る
    なら、それはmarkers表の役割で見どころとは別物)。

    ここで入るstartはwall-clockから出した暫定値で、finalizeでmp4のPTS軸へ載せ直される。
    """
    collector = runtime._get_collector(unique_id)
    snapshot = collector.snapshot()
    recording = snapshot.get("recording") or {}
    recording_id = recording.get("recording_id")
    started_at = recording.get("started_at")
    if not recording.get("live") or not recording_id or not started_at:
        raise HTTPException(
            status_code=409,
            detail=f"@{unique_id} は録画中ではありません。録画を開始してから記録してください。",
        )
    now = time.time()
    return await asyncio.to_thread(
        runtime.storage.add_live_bookmark,
        recording_id, unique_id, now, max(0.0, now - started_at), payload.memo,
    )


@router.patch("/api/bookmarks/{bookmark_id}")
async def update_bookmark_api(bookmark_id: int, payload: BookmarkPatchRequest) -> dict:
    provided = payload.model_fields_set
    if not provided:
        raise HTTPException(status_code=400, detail="更新する内容がありません。")
    if "group_id" in provided:
        if payload.group_id is not None:
            await _require_group(payload.group_id)
        if not await asyncio.to_thread(
                runtime.storage.set_bookmark_group, [bookmark_id], payload.group_id):
            raise HTTPException(status_code=404, detail="対象が見つかりません。")
    if "memo" in provided:
        updated = await asyncio.to_thread(
            runtime.storage.update_bookmark_memo, bookmark_id, payload.memo or "")
        if updated is None:
            raise HTTPException(status_code=404, detail="対象が見つかりません。")
        return updated
    updated = await asyncio.to_thread(runtime.storage.get_bookmark, bookmark_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="対象が見つかりません。")
    return updated


@router.delete("/api/bookmarks/{bookmark_id}")
async def delete_bookmark_api(bookmark_id: int) -> dict:
    if not await asyncio.to_thread(runtime.storage.delete_bookmark, bookmark_id):
        raise HTTPException(status_code=404, detail="対象が見つかりません。")
    return {"deleted": bookmark_id}


def _semantic_min_score() -> float:
    """意味検索の類似度の下限。これ未満は「該当なし」として捨てる。

    scoreの尺度は埋め込みmodel依存(embeddinggemma:300mでの実測に基づく既定値)なので、
    modelを替えたら測り直して設定すること。
    TODO: 他のTICTOK_SEMANTIC_*と併せてcore/config.pyへ移す。"""
    return float(os.environ.get("TICTOK_SEMANTIC_MIN_SCORE", "0.30"))


@router.get("/api/search/semantic")
async def semantic_search_api(q: str, sources: str = "stt,comment", unique_ids: str = "",
                              since: Optional[float] = None, until: Optional[float] = None,
                              limit: int = 50) -> dict:
    """意味検索。語の一致ではなく意味の近さで探すので、言い回しを覚えていなくても引ける。

    結果はkeyword検索と同じ行形式へ揃えて返す(画面が両者を同じ表で描けるようにする)。
    passageは複数のsearch_hits行を束ねたものなので、代表行の位置へseekする。
    sources/since/untilの意味は /api/search と同じで、絞り込むほど走査行が減って速くなる。"""
    wanted = [s for s in sources.split(",") if s in (indexer.SOURCE_STT, indexer.SOURCE_COMMENT)]
    ids = [u for u in unique_ids.split(",") if u]
    if not wanted:
        # 0件は0件として返す。ここで全件を検索すると、種類を全部外したのに結果が出る。
        return {"total": 0, "mode": "semantic", "items": [],
                "hint": "検索する種類（発話／コメント）を選んでください。"}
    try:
        matches = await semantic.search(q, max(1, min(limit, 200)), ids or None,
                                        wanted, since, until)
    except semantic.SemanticError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    # 意味検索は常に上位k件を返すので、そもそも該当が無い話題でも「それらしいゴミ」が並ぶ。
    # 実測ではdata内に在る話題のtop1が0.40〜0.49、無い話題が0.12〜0.27と分離するため、
    # 下限を設けて後者を落とす。閾値はscoreの尺度がmodel依存なので設定で変えられる。
    floor = _semantic_min_score()
    kept = [m for m in matches if m["score"] >= floor]
    if not kept:
        best = max((m["score"] for m in matches), default=0.0)
        return {"total": 0, "mode": "semantic", "items": [],
                "hint": f"意味の近いシーンが見つかりませんでした（最も近いもので類似度{best:.2f}"
                        f"／下限{floor:.2f}）。別の言い方を試すか、語で一致に切り替えてください。"}
    matches = kept
    # semantic.searchはpassage全文(既定25秒ぶん)をbodyに持つ。先頭行のsearch_hitsを
    # 引き直して表示すると、当たった本文ではなく「でその」のような断片が並び、
    # 精度が実際より遥かに悪く見える。返ってきたpassageをそのまま見せる。
    items = []
    for match in matches:
        items.append({
            "id": match["id"],
            "source": match["source"],
            "recording_id": match["recording_id"],
            "session_id": match["session_id"],
            "unique_id": match["unique_id"],
            "started_at": match["started_at"],
            "video_time": match["video_time"],
            "end_time": match["end_time"],
            "nickname": None,
            "body": match["body"],
            "snippet": match["body"],
            "score": round(match["score"], 4),
        })
    return {"total": len(items), "mode": "semantic", "hint": "", "items": items}


@router.get("/api/search/semantic/status")
async def semantic_status_api() -> dict:
    return await asyncio.to_thread(semantic.index_status)


async def _broadcast_semantic_status(result: Optional[dict] = None,
                                     error: str = "") -> None:
    """意味検索indexの現況を配る。開始時はcreate_taskで投げっぱなしにするので、
    ここで例外を出すと「Task exception was never retrieved」だけが残る。通知の失敗で
    buildを巻き添えにする理由も無いので、logへ落として飲む。

    ``result`` は構築完了時のみ、``error`` は失敗時のみ。応答を待たなくなった以上、
    件数のまとめも失敗も、この通知でしか画面へ届かない。"""
    try:
        status = await asyncio.to_thread(semantic.index_status)
        await runtime.hub.broadcast({"type": "semantic_index", "status": status,
                             "result": result, "error": error})
    except Exception:
        runtime.logger.exception(
            "意味検索のindexの現況を配れませんでした",
            extra={"event": "search.semantic_status_broadcast_failed", "ctx": {}},
        )


# 進捗通知のtask。asyncioはrunning taskを強参照しないので、投げっぱなしにすると通知が
# 配られる前にGCへ回収され得る(buildは走り続けるが画面は0%のまま動かなくなる)。
# 保持の仕方は semantic_build_api の ``runtime._semantic_build_tasks`` と同じ流儀にする。
_progress_tasks: set = set()


def _spawn_progress(loop, coro) -> None:
    """進捗通知を投げ、完了まで参照を持つ。build本体を待たせないための投げっぱなし。"""
    task = loop.create_task(coro)
    _progress_tasks.add(task)
    task.add_done_callback(_progress_tasks.discard)


async def _run_semantic_build() -> None:
    """意味検索indexの構築本体。requestとは切り離してbackgroundで走る。

    進捗はjob台帳(意味検索index)とWSのsemantic_indexで届くので、呼び出し側が結果を
    待つ必要はない。例外はここで畳む: 誰もawaitしないtaskの外へ投げても
    「Task exception was never retrieved」が残るだけで、userには何も伝わらない。"""
    loop = asyncio.get_running_loop()
    # 埋め込みは数十万passageを数千batchに分けて回す。build_indexは件数入りの
    # stage="embed" を出しているのに、以前は stage=="start" 以外を全て捨てており、
    # 画面は固定文字列だけで進み具合を知る手段が無かった。
    gate = IntervalGate(get_job_progress_min_interval_seconds())
    # job台帳への登録は stage=="start"(=lockを実際に握った後)まで遅らせる。開始前に
    # 登録すると、競合で弾かれただけのbuildが「失敗したjob」として履歴に残る。
    # pct(int)とjob_id(str)が同居するので、注釈が無いと値の型が object に潰れる。
    state: dict = {"pct": -1, "job_id": ""}

    def on_progress(info: dict) -> None:
        stage = info.get("stage")
        if stage == "start":
            # lockを実際に握った後なので、配る status の building は真。これが無いと
            # 別tabやこのbuildを始めていない画面はbuttonを塞げない。
            _spawn_progress(loop, _broadcast_semantic_status())
            state["job_id"] = secrets.token_hex(4)
            _spawn_progress(loop, runtime.jobs.start(
                state["job_id"], "semantic", "意味検索indexの構築",
                total=int(info.get("hits") or 0) or 1))
            return
        if stage not in ("embed", "group_done") or not state["job_id"]:
            return
        total = info.get("total") or 0
        done = info.get("done") or 0
        pct = int(done * 100 / total) if total else 0
        # batchごとに鳴るcallbackなので、%が動いた時と時間gateが開いた時だけ配る。
        if pct == state["pct"] and not gate.ready():
            return
        state["pct"] = pct
        _spawn_progress(loop, runtime.jobs.progress(
            state["job_id"], pct, stage=f"文章を埋め込み中（{done:,}/{total:,}件）"))

    outcome, message, result = "completed", "", None
    try:
        async with runtime._job_ops("semantic", None):
            result = await semantic.build_index(runtime.storage, on_progress=on_progress)
    except semantic.SemanticBusy:
        # 入口の判定をすり抜けた競合。もう1本が同じ仕事をしているので、失敗ではない。
        return
    except semantic.SemanticError as exc:
        outcome, message = "failed", str(exc)
    except Exception as exc:
        outcome, message = "failed", str(exc)
        runtime.logger.exception(
            "意味検索のindex作成に失敗しました",
            extra={"event": "search.semantic_build_failed", "ctx": {}},
        )
    finally:
        if state["job_id"]:
            await runtime.jobs.finish(state["job_id"], outcome, message=message)
        # 失敗して抜けた場合もbuildingを下ろす。ここを通さないと画面が塞がったまま残る。
        # errorも必ず載せる: 応答を待たなくなった以上、失敗をrequestで返す経路はもう無い。
        # ここで配らないと、buildが死んでも画面には「開始しました」が残り続ける。
        await _broadcast_semantic_status(result, message)


@router.post("/api/search/semantic/build", status_code=202)
async def semantic_build_api() -> dict:
    """意味検索indexの構築を開始し、受け付けた時点で返す(差分構築)。

    完了まで応答を握らない。対象は数十万passageで構築に数時間かかることがあり、その間
    HTTP requestを開いたままにするとbrowser/proxyのtimeoutで接続が切れる。**server側の
    構築は続いているのに画面には失敗として出る**ため、userは失敗したと思って押し直し、
    今度は実行中として弾かれる、という経路に入っていた。進捗はjob台帳とWSで届く。"""
    if semantic.build_running():
        raise HTTPException(
            status_code=409,
            detail="意味検索indexの構築が既に実行中です。完了までお待ちください。",
        )
    task = asyncio.create_task(_run_semantic_build())
    # taskへの参照を保持する。GCがrunning taskを回収するとbuildが黙って消える。
    runtime._semantic_build_tasks.add(task)
    task.add_done_callback(runtime._semantic_build_tasks.discard)
    return {"started": True}


@router.get("/api/search/status")
async def search_status_api() -> dict:
    """検索対象がどこまで揃っているか。転写は配信者単位で進むため、配信者ごとに集計する。"""

    # search_hitsの集計は36万行のindex走査で、素のままevent loopに載せるとその間WSの
    # 配信も他のrequestも止まる(この画面は動画tabを開くたびに叩かれる)。
    def _collect() -> list:
        counts = runtime.storage.search_indexed_counts()
        transcribed = runtime.storage.transcribed_recording_ids()
        rows = [rec for rec in runtime.storage.list_recordings(100000)
                if rec["status"] == "completed"]
        # 実体の有無まで返す。DB行だけを数えると、素材もmp4も残っていない配信者
        # (retentionで消えた・外で消された)が「録画N本」を名乗り続け、画面の配信者選択に
        # 出てくる。投入側(``_enqueue_stt_jobs``)は既に実体の無い録画を弾いているので、
        # 数える側がDB行だけを見ていると、押しても何も起きないだけの行になる。
        # 判定は_recording_media_kindsと同値(has_hls or has_file)だが、録画ごとのstat/globを
        # 数百回起こさないよう、dir単位に畳んだ一括版で引く。
        facts_by_id = fsfacts._bulk_fs_facts_batch(rows)
        fsfacts._bulk_hls_batch(rows, facts_by_id)
        per_streamer: dict = {}
        for recording in rows:
            entry = per_streamer.setdefault(
                recording["unique_id"],
                {"unique_id": recording["unique_id"], "recordings": 0, "playable": 0,
                 "transcribable": 0, "transcribed": 0, "comment_indexed": 0,
                 "seconds": 0.0},
            )
            facts = facts_by_id.get(recording["id"]) or {}
            playable = bool(facts.get("has_hls") or facts.get("has_file"))
            entry["recordings"] += 1
            if playable:
                entry["playable"] += 1
            if recording["id"] in transcribed:
                entry["transcribed"] += 1
            elif playable:
                # 転写を積める録画。「録画数 - 転写済」だと実体の無い録画が永久に残り、
                # 文字起こしのbuttonが押せるのに1件も投入されない状態になる。
                entry["transcribable"] += 1
            if indexer.SOURCE_COMMENT in counts.get(recording["id"], {}):
                entry["comment_indexed"] += 1
            entry["seconds"] += files._recording_seconds(recording)
        return sorted(per_streamer.values(), key=lambda e: e["seconds"], reverse=True)

    streamers = await asyncio.to_thread(_collect)
    return {"streamers": streamers, "queue": await transcribe_queue_api()}


@router.post("/api/transcribe/queue")
async def enqueue_transcriptions_api(payload: EnqueueRequest) -> dict:
    """文字起こしをqueueへ投入する。recording_ids指定なら1本単位、無ければ配信者単位
    (unique_id未指定なら全配信者)。

    走る先は映像jobと同じ ``media_job_queue`` である(kind=stt)。専用台帳を分けていた頃は、
    同じGPUを取り合っているのにJob一覧へ出ず、取り消しも別画面だった。"""
    if not stt_available():
        raise HTTPException(
            status_code=503,
            detail="STTが利用できません。faster-whisperのinstallとTICTOK_STT_ENABLEDを確認してください。")
    if payload.recording_ids:
        recordings = []
        for recording_id in payload.recording_ids:
            recording = await asyncio.to_thread(runtime.storage.get_recording, recording_id)
            if recording is None:
                raise HTTPException(status_code=404,
                                    detail=f"録画が見つかりません: {recording_id}")
            recordings.append(recording)
    else:
        recordings = await asyncio.to_thread(
            runtime.storage.untranscribed_recordings,
            payload.unique_id,
        )
    return await media_jobs._enqueue_stt_jobs(recordings, payload.priority)


@router.get("/api/transcribe/queue")
async def transcribe_queue_api() -> dict:
    """文字起こしの待ち行列。Job一覧(kind=stt)と同じ台帳を、この画面の列で返す。

    stateは映像jobのものをそのまま出す(completed/skipped/interruptedを含む)。別台帳だった
    頃の名前(done)へ翻訳し直すと、Job一覧とこの画面が同じ行を別の言葉で名乗ることになる。"""
    # list_jobs() も台帳(DB)を読むので、event loop 側に残すとここだけで書き込みlockを
    # 待つことになる。台帳の読みと行の組み立てをまとめて1回でthreadへ出す
    # (この画面はpollingで叩かれ続ける)。
    def _rows() -> tuple:
        rows = [job for job in media_jobs.media_job_queue.list_jobs()
                if job.get("domain") == "stt"]
        counts: dict = {}
        items = []
        # 同じ録画に複数の行(再試行・取り消し後の積み直し)が並ぶので、録画は1回だけ引く。
        seen_recordings: dict = {}
        for job in rows:
            counts[job["state"]] = counts.get(job["state"], 0) + 1
            recording_id = job.get("recording_id")
            if recording_id and recording_id not in seen_recordings:
                seen_recordings[recording_id] = runtime.storage.get_recording(recording_id)
            recording = seen_recordings.get(recording_id) if recording_id else None
            items.append({
                "job_id": job["job_id"],
                "recording_id": job.get("recording_id"),
                "unique_id": (recording or {}).get("unique_id") or "",
                "filename": (recording or {}).get("filename") or "",
                "state": job["state"], "pct": job.get("pct") or 0,
                "error": job.get("error") or "",
                "queued_at": job.get("queued_at"),
            })
        running = next((job["recording_id"] for job in rows
                        if job["state"] == "running"), None)
        return counts, items, running

    counts, items, running = await asyncio.to_thread(_rows)
    return {"available": stt_available(), "running": running, "counts": counts,
            "items": items}


@router.delete("/api/transcribe/queue")
async def cancel_transcriptions_api(payload: CancelRequest) -> dict:
    """待機中の文字起こしを取り消す。実行中は映像jobと同じくtokenでkillできる。"""
    targets = set(payload.recording_ids or [])
    cancelled = 0
    # 台帳の読みはDB。取り消し自体(cancel)はqueue側がawaitできる形を持っているので、
    # ここでthreadへ出すのは一覧の取得だけでよい。
    jobs = await asyncio.to_thread(media_jobs.media_job_queue.list_jobs)
    for job in jobs:
        if job.get("domain") != "stt" or job["state"] not in ("pending", "running"):
            continue
        if targets and job.get("recording_id") not in targets:
            continue
        if await media_jobs.media_job_queue.cancel(job["job_id"]) in ("cancelled", "cancelling"):
            cancelled += 1
    return {"cancelled": cancelled, "queue": await transcribe_queue_api()}
