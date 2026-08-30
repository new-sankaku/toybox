"""検索(全文・意味)・見どころ(bookmark)・切り抜きグループ・文字起こしの投入。

文字起こしの投入をここへ置くのは、動機が検索(見つけたい)だからで、実行そのものは映像job
のqueue(``media_jobs``)が持つ。進捗の一覧と取り消しはここには無い — 台帳は同じ(kind=stt)
なので、Job画面(``/api/jobs``)が唯一の置き場である。
"""

import asyncio
import os
import secrets
import time
from typing import Optional
from fastapi import HTTPException
from pydantic import BaseModel, Field
from tictok.core.config import get_job_progress_min_interval_seconds
from tictok.record.transcription import stt_available, stt_status
from tictok.search import indexer, semantic
from tictok.core.progress import IntervalGate
from tictok.store._common import BOOKMARK_ORIGINS
from fastapi import APIRouter
from tictok.api import files
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


@router.get("/api/search")
async def search_api(q: str, sources: str = "stt,comment", unique_ids: str = "",
                     since: Optional[float] = None, until: Optional[float] = None,
                     order: str = "time", limit: int = 200, offset: int = 0) -> dict:
    """文字起こし・commentを横断して**語で**検索する。1件=1シーンで、video_timeへそのまま
    seekできる。

    笑い声(``indexer.SOURCE_LAUGH``)はここでは引けない。音そのものが根拠で本文に当たる
    語が無く、受け付けていた頃は「笑い声」と打ったときだけ出る隠しmodeになっていた
    (`ガンダム` で探しても笑いは1件も混ざらない)。語を持たない行は /api/search/laughs。
    """
    wanted = [s for s in sources.split(",")
              if s in (indexer.SOURCE_STT, indexer.SOURCE_COMMENT)]
    ids = [u for u in unique_ids.split(",") if u]
    result = await asyncio.to_thread(
        runtime.storage.search_scenes, q, wanted, ids, since, until, order,
        max(1, min(limit, 500)), max(0, offset))
    return result


@router.get("/api/search/hits")
async def search_hits_api(ids: str) -> dict:
    """id指定でsearch_hitsの行を引く。意味検索のpassageを文へ開くのに使う。

    passageは約25秒ぶんの発話・コメントを束ねた窓で、行そのものへ飛ぶと当たった文の
    十数秒手前から始まる。画面はpassageの本文を1文ずつ押せるようにし、押された文のidだけを
    ここへ引きに来る。秒はindexの写しではなくDBから引くので、文字起こしのやり直しで
    位置が動いていても最新の値が返る。"""
    wanted = []
    for token in ids.split(","):
        token = token.strip()
        if not token:
            continue
        if not token.lstrip("-").isdigit():
            raise HTTPException(status_code=400, detail=f"idは整数で指定してください: {token}")
        wanted.append(int(token))
    if not wanted:
        raise HTTPException(status_code=400, detail="idを1つ以上指定してください。")
    if len(wanted) > 500:
        raise HTTPException(status_code=400, detail="一度に引けるidは500件までです。")
    items = await asyncio.to_thread(runtime.storage.search_hit_rows, wanted)
    return {"items": items}


# 笑い声の一覧で受け付ける並び。ここに無い値は 'time' として扱う(SQLへ素通しさせない)。
LAUGH_ORDERS = ("time", "strength", "length")


@router.get("/api/search/laughs")
async def laugh_scenes_api(unique_ids: str = "", order: str = "time",
                           limit: int = 200, offset: int = 0) -> dict:
    """音声から検出した笑い声の窓を、語で絞らずに列挙する。

    語を受け取らないのが /api/search との違いである。行の形は同じなので、画面は同じ表で
    描き、同じ経路でseekできる。並べ替えだけがこちら固有で、強い順・長い順を持つ
    (語での一致度が無い代わりに、確率と長さが選ぶ手掛かりになる)。
    """
    ids = [u for u in unique_ids.split(",") if u]
    return await asyncio.to_thread(
        runtime.storage.laugh_scenes, ids,
        order if order in LAUGH_ORDERS else "time",
        max(1, min(limit, 500)), max(0, offset))


class GroupRequest(BaseModel):
    name: str
    memo: str = ""


class GroupPatchRequest(BaseModel):
    name: Optional[str] = None
    memo: Optional[str] = None


class GroupOrderRequest(BaseModel):
    bookmark_ids: list[int]


class GroupShelfOrderRequest(BaseModel):
    group_ids: list[int]


class GroupMergeRequest(BaseModel):
    into: int


class BookmarkBulkRequest(BaseModel):
    op: str
    ids: list[int]
    group_id: Optional[int] = None


async def _require_group(group_id: int) -> dict:
    group = await asyncio.to_thread(runtime.storage.get_group, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="グループが見つかりません。")
    return group


# ===== 切り抜きグループ(group) =====
# 見どころ(bookmarks)を「切り抜き動画1本のグループ」単位で束ねる。所属は排他で、
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


@router.post("/api/groups/order")
async def reorder_groups_api(payload: GroupShelfOrderRequest) -> dict:
    """棚(グループ一覧)の表示順をgroup_idsの順へ振り直す。グループ内の切り出しの並び
    (/api/groups/{id}/order)とは別物で、こちらは書き出し順に一切影響しない。"""
    ordered = await asyncio.to_thread(runtime.storage.reorder_groups, payload.group_ids)
    return {"ordered": ordered}


@router.post("/api/groups/{group_id}/merge")
async def merge_group_api(group_id: int, payload: GroupMergeRequest) -> dict:
    """group_idの中身をintoのグループへ全て移し、group_idを消す(統合)。"""
    if group_id == payload.into:
        raise HTTPException(status_code=400, detail="同じグループへは統合できません。")
    await _require_group(group_id)
    await _require_group(payload.into)
    moved = await asyncio.to_thread(runtime.storage.merge_groups, group_id, payload.into)
    return {"merged": group_id, "into": payload.into, **moved}


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
    """グループ内の並びをbookmark_idsの順へ振り直す。この並びがmp4の書き出し順になる。"""
    await _require_group(group_id)
    ordered = await asyncio.to_thread(
        runtime.storage.reorder_group_bookmarks, group_id, payload.bookmark_ids)
    return {"ordered": ordered}


@router.post("/api/bookmarks/bulk")
async def bookmarks_bulk_api(payload: BookmarkBulkRequest) -> dict:
    """見どころの一括操作。move=所属変更、copy=行を複製して別グループへ、delete=削除。
    group_id=Noneは未分類を指す。

    copyが在るのは、同じ場面をグループごとに別の詰め方で持てるようにするためである
    (所属は排他なので、共用ではなく複製で表す)。"""
    if payload.op not in ("move", "copy", "delete"):
        raise HTTPException(status_code=400,
                            detail="opはmove/copy/deleteのいずれかを指定してください。")
    if not payload.ids:
        raise HTTPException(status_code=400, detail="対象を選んでください。")
    if payload.op in ("move", "copy") and payload.group_id is not None:
        await _require_group(payload.group_id)
    if payload.op == "move":
        affected = await asyncio.to_thread(
            runtime.storage.set_bookmark_group, payload.ids, payload.group_id)
    elif payload.op == "copy":
        affected = await asyncio.to_thread(
            runtime.storage.copy_bookmarks_to_group, payload.ids, payload.group_id)
    else:
        affected = await asyncio.to_thread(runtime.storage.delete_bookmarks, payload.ids)
    return {"affected": affected}


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


@router.delete("/api/bookmarks")
async def clear_bookmarks_api(group: str = "") -> dict:
    """一括削除。group=idでそのグループの分だけ、group=noneで未分類だけを消す。"""
    group_id, only_ungrouped = _parse_group_param(group)
    if group_id is not None:
        await _require_group(group_id)
    return {"deleted": await asyncio.to_thread(
        runtime.storage.clear_bookmarks, group_id, only_ungrouped)}


class BookmarkRequest(BaseModel):
    recording_id: int
    start: float = Field(ge=0)
    end: Optional[float] = None
    memo: str = ""
    source_hit_id: Optional[int] = None
    group_id: Optional[int] = None
    # 誰が置いた行かを、置く側が名乗る。既定が manual なのは、この経路を叩くのが
    # 画面の「見どころに記録」だからである。
    origin: str = "manual"


class BookmarkPatchRequest(BaseModel):
    """部分更新。group_id=Noneは「未分類へ戻す」、end=Noneは「範囲を捨てて点へ戻す」を
    意味するので、更新の有無はmodel_fields_setで判定する(Noneを既定値と読み違えると
    所属や範囲が黙って外れる)。startのNoneは「触らない」で、位置は空にできない。"""
    memo: Optional[str] = None
    group_id: Optional[int] = None
    start: Optional[float] = Field(default=None, ge=0)
    end: Optional[float] = None


@router.get("/api/bookmarks")
async def list_bookmarks_api(recording_id: Optional[int] = None) -> dict:
    """見どころ一覧。recording_id指定で1録画分(seek barのmarker用)、無指定で全録画分。

    pathは移動後の実体を指すよう解決し直す。範囲を持つ見どころはそのまま書き出しの素材な
    ので、一覧に出ているpathが実体と食い違うと、書き出せない行が書き出せるように見える。

    読みも解決も1回のthread呼び出しにまとめる。1件ごとにto_threadを跨いでget_recordingを
    引くと、**path解決(実fileのstat)はloop側**に残り、件数が増えるほどserverが止まる時間が
    伸びる。同じ録画を指す行は1回だけ解決する。"""
    def _resolve(rec_id: int) -> Optional[str]:
        # 解決できない1行で一覧全体を落とさない。pathは「どこに実体が在るか」の補助情報で、
        # 一覧そのものはDBの行だけで成立する。ここが例外を上げると、seek barのmarkerまで
        # 消える(この経路は再生画面が録画を開くたびに通る)。
        recording = runtime.storage.get_recording(rec_id)
        if recording is None:
            return None
        try:
            return str(files._resolved_recording_path(recording))
        except Exception:
            runtime.logger.warning(
                "見どころ一覧で録画pathを解決できませんでした（recording=%s）", rec_id,
                exc_info=True,
                extra={"event": "bookmarks.path_unresolved",
                       "ctx": {"recording_id": rec_id}})
            return None

    def _collect() -> list:
        items = runtime.storage.list_bookmarks(recording_id)
        resolved: dict = {}
        for item in items:
            if not item.get("path"):
                continue
            rec_id = item["recording_id"]
            if rec_id not in resolved:
                resolved[rec_id] = _resolve(rec_id)
            if resolved[rec_id] is not None:
                item["path"] = resolved[rec_id]
        return items

    return {"items": await asyncio.to_thread(_collect)}


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
    if payload.origin not in BOOKMARK_ORIGINS:
        raise HTTPException(
            status_code=400,
            detail=f"出所は {'/'.join(BOOKMARK_ORIGINS)} のいずれかにしてください。")
    return await asyncio.to_thread(
        runtime.storage.add_bookmark, payload.recording_id, recording["unique_id"],
        payload.start, payload.end, payload.memo, payload.source_hit_id,
        payload.group_id, payload.origin)


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
    if "start" in provided or "end" in provided:
        # 位置と尺を一覧の上で直せるようにする。直せないと、点に尺を与えるにも端を
        # 1秒詰めるにも再生画面へ戻って取り直すことになり、古い行を消し忘れれば
        # 同じ場面の見どころが2件残る。
        try:
            row = await asyncio.to_thread(
                runtime.storage.update_bookmark_range, bookmark_id,
                payload.start, payload.end, "end" in provided)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        if row is None:
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
        found = await semantic.search(runtime.storage, q, max(1, min(limit, 200)),
                                      ids or None, wanted, since, until)
    except semantic.SemanticError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    matches = found["items"]
    # 文字起こしのやり直しや時刻の張り直しで、indexが指す行が消えたpassage。古い秒で返すと
    # 数分ずれた場所へ飛ぶので落としてある。落としたことは必ず伝える — 黙って消すと
    # 「意味検索はこの配信を拾わない」という誤った理解になる。
    stale_note = ("" if not found["stale"] else
                  f"（{found['stale']}件は文字起こし・時刻の張り直し後にindexが未更新のため"
                  "除外しました。「意味検索indexを更新」を押してください）")

    # 意味検索は常に上位k件を返すので、そもそも該当が無い話題でも「それらしいゴミ」が並ぶ。
    # 実測ではdata内に在る話題のtop1が0.40〜0.49、無い話題が0.12〜0.27と分離するため、
    # 下限を設けて後者を落とす。閾値はscoreの尺度がmodel依存なので設定で変えられる。
    floor = _semantic_min_score()
    kept = [m for m in matches if m["score"] >= floor]
    if not kept:
        best = max((m["score"] for m in matches), default=0.0)
        return {"total": 0, "mode": "semantic", "items": [],
                "hint": f"意味の近いシーンが見つかりませんでした（最も近いもので類似度{best:.2f}"
                        f"／下限{floor:.2f}）。別の言い方を試すか、語で一致に切り替えてください。"
                        + stale_note}
    matches = kept
    # semantic.searchはpassage全文(既定25秒ぶん)をbodyに持つ。先頭行のsearch_hitsを
    # 引き直して表示すると、当たった本文ではなく「でその」のような断片が並び、
    # 精度が実際より遥かに悪く見える。返ってきたpassageをそのまま見せる。
    items = []
    for match in matches:
        items.append({
            "id": match["id"],
            # passageを組んでいる文のid。画面はこれで本文の各行を押せるようにし、押された
            # 文の秒を /api/search/hits から引く(行そのものへ飛ぶとpassageの頭に着地する)。
            "hit_ids": match["hit_ids"],
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
    return {"total": len(items), "mode": "semantic", "hint": stale_note, "items": items}


@router.get("/api/search/semantic/status")
async def semantic_status_api() -> dict:
    return await asyncio.to_thread(semantic.index_status, runtime.storage)


async def _broadcast_semantic_status(result: Optional[dict] = None,
                                     error: str = "") -> None:
    """意味検索indexの現況を配る。開始時はcreate_taskで投げっぱなしにするので、
    ここで例外を出すと「Task exception was never retrieved」だけが残る。通知の失敗で
    buildを巻き添えにする理由も無いので、logへ落として飲む。

    ``result`` は構築完了時のみ、``error`` は失敗時のみ。応答を待たなくなった以上、
    件数のまとめも失敗も、この通知でしか画面へ届かない。"""
    try:
        status = await asyncio.to_thread(semantic.index_status, runtime.storage)
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


async def _run_semantic_build() -> bool:
    """意味検索indexの構築本体。requestとは切り離してbackgroundで走る。

    進捗はjob台帳(意味検索index)とWSのsemantic_indexで届くので、呼び出し側が結果を
    待つ必要はない。例外はここで畳む: 誰もawaitしないtaskの外へ投げても
    「Task exception was never retrieved」が残るだけで、userには何も伝わらない。

    戻り値(完走したか)を読むのは自動起動の側だけで、失敗した相手へ何度も起こしに行かない
    ための材料である(``start_build_if_pending``)。人が押した経路は結果をWSで受け取る。"""
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
        return True
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
    return outcome == "completed"


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


# 自動で起こしたbuildが失敗した後、次に自動で試みるまで空ける時間。埋め込みserverが
# 落ちていれば何度起こしても同じ所で失敗し、台帳が同じ失敗の行で埋まるだけで、直せるのは
# 人しかいない。sweepの周期(既定30分)より粗くする。人が押す「indexを更新」はこの待ちを
# 見ない(押した本人はその場で結果を要求している)。
AUTO_BUILD_RETRY_SECONDS = 3600.0
_auto_retry_at = 0.0


def _remember_auto_outcome(task) -> None:
    """自動で起こしたbuildの結末を覚える。完走しなかった回だけ次を遅らせる。

    ``cancelled()`` を先に見るのは、取り消し済みtaskへ ``exception()`` を訊くと
    CancelledErrorが飛ぶため(callbackの中なので、飛ばすと誰も受け取らない)。"""
    global _auto_retry_at
    if task.cancelled() or task.exception() is not None or not task.result():
        _auto_retry_at = time.time() + AUTO_BUILD_RETRY_SECONDS


async def start_build_if_pending() -> int:
    """indexに未反映のgroupが残っていれば構築を1本起こし、その件数を返す(起こさなければ0)。

    sweep(``api.startup``)から呼ぶ自動経路。起こし方を人が押す経路と同じ
    ``_run_semantic_build`` に揃えるのは、差分判定・job台帳・進捗のWS・競合の弾きを
    そちらが全部持っているからで、自動でもJob画面には同じ1行が出る。別の作り方は持たない。

    埋め込みserverが無効・未設定なら何もしない(意味検索そのものが使えない状態で、
    indexだけ作っても行き先が無い)。到達性はここでは確かめない — 確かめるにはHTTPを
    1本投げることになり、それはbuildが最初のbatchでやることそのものである。"""
    if not semantic.semantic_available() or semantic.build_running():
        return 0
    if time.time() < _auto_retry_at:
        return 0
    # search_hitsの全groupとindexed表の突き合わせ。件数に比例するのでloopの外(別thread)へ。
    pending = await asyncio.to_thread(semantic.pending_groups, runtime.storage)
    if not pending:
        return 0
    task = asyncio.create_task(_run_semantic_build())
    runtime._semantic_build_tasks.add(task)
    task.add_done_callback(runtime._semantic_build_tasks.discard)
    task.add_done_callback(_remember_auto_outcome)
    return pending


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
