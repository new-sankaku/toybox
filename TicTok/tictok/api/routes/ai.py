"""AIによるcomment分析と配信者review。cacheの当たり判定と応答整形を含む。"""

import asyncio
from typing import Optional
from fastapi import HTTPException
from tictok.ai import ai_analysis, review_digest
from tictok.ai.ai_analysis import AIError, ai_status, analyze_comments, analyze_streamer
from tictok.core.config import get_ai_enabled
from fastapi import APIRouter
from tictok.api import runtime

router = APIRouter()


@router.get("/api/ai/status")
async def ai_status_api() -> dict:
    return ai_status()


# AI分析の永続化。GETは保存済みの結果だけを返し、LLMは一切走らせない(画面を開くたびに
# 数十秒の推論が始まるのを構造的に防ぐ)。実行はPOSTのみで、operatorがbuttonを押したとき
# だけ走る。未計算の対象をまとめて計算する経路は作らない。
def _ai_payload(base: dict, record: Optional[dict], *, cached: bool) -> dict:
    """API応答の共通部分。分析日時・model・prompt版・cacheかどうかを必ず載せる
    (いつ・どのmodelで出した結果なのかが分からない表示にはしない)。"""
    payload = dict(base)
    payload["cached"] = cached
    if record is None:
        payload.update({"analysis": None, "computed_at": None, "model": None,
                        "prompt_version": None})
        return payload
    payload.update({
        "analysis": record.get("payload"),
        "computed_at": record.get("computed_at"),
        "model": record.get("model"),
        "prompt_version": record.get("prompt_version"),
    })
    if record.get("payload_unreadable"):
        # 読めない行を「未分析」に化けさせない。再分析すれば直ることを画面へ伝える。
        payload["error"] = "保存された分析結果を読み取れませんでした。再分析してください。"
    return payload


def _ai_cache_hit(record: Optional[dict], model: str, prompt_version: int,
                  signature: str) -> bool:
    return bool(
        record
        and not record.get("payload_unreadable")
        and record.get("model") == model
        and record.get("prompt_version") == prompt_version
        and record.get("input_signature") == signature
    )


def _ai_model_or_503() -> str:
    model = ai_status()["model"]
    if not get_ai_enabled():
        raise HTTPException(status_code=503,
                            detail="AI機能が無効です（TICTOK_AI_ENABLED=1 を設定してください）。")
    if not model:
        raise HTTPException(status_code=503,
                            detail="AI modelが未設定です（TICTOK_AI_MODEL を設定してください）。")
    return model


def _session_comment_entries(session_id: int) -> list:
    """sessionのcommentを(時刻, 本文)で返す。時刻が要るのは時間層化抽出のため。

    storage.session_commentsは新しい順にN件を切って本文だけを返すので、そこから採ると
    標本が配信終盤に偏る(=出力されるsentiment比率が配信全体の推定量にならない)。件数を
    絞るのは抽出側の仕事なので、ここでは全commentを時刻付きで渡す。"""
    return [
        (row["time"], row["comment"] or row["text"] or "")
        for row in runtime.storage.iter_events(session_id)
        if row["kind"] == "comment" and (row["comment"] or row["text"])
    ]


async def _session_comment_input(session_id: int) -> list:
    entries = await asyncio.to_thread(_session_comment_entries, session_id)
    sample = ai_analysis.comment_sample(entries)
    if not sample:
        raise HTTPException(status_code=404, detail="このSessionに分析できるCommentがありません。")
    return sample


def _comment_analysis_payload(session_id: int, record: Optional[dict],
                              *, cached: bool) -> dict:
    """comment分析の保存形式は {analysis, comment_count} の包み。何件を分析した結果なのかは
    分析日時と同じくらい読み手に必要で、payload以外に置き場が無いため一緒に保存している。"""
    stored = (record or {}).get("payload")
    wrapped = stored if isinstance(stored, dict) else {}
    view = dict(record) if record else None
    if view is not None:
        view["payload"] = wrapped.get("analysis")
    payload = _ai_payload({"session_id": session_id}, view, cached=cached)
    payload["comment_count"] = wrapped.get("comment_count")
    return payload


@router.get("/api/sessions/{session_id}/comment-analysis")
async def session_comment_analysis(session_id: int) -> dict:
    """保存済みの分析結果のみを返す。無ければanalysis=nullで、LLMは起動しない。"""
    await asyncio.to_thread(runtime._get_session_or_404, session_id)
    record = await asyncio.to_thread(
        runtime.storage.get_ai_analysis, ai_analysis.KIND_COMMENT,
        ai_analysis.TARGET_SESSION, str(session_id))
    return _comment_analysis_payload(session_id, record, cached=record is not None)


@router.post("/api/sessions/{session_id}/comment-analysis")
async def run_session_comment_analysis(session_id: int, refresh: int = 0) -> dict:
    """明示要求でのみ実行する。入力・model・prompt版が前回と同じなら保存済みを返し、
    refresh=1 のときだけ同一条件でも作り直す。"""
    await asyncio.to_thread(runtime._get_session_or_404, session_id)
    model = _ai_model_or_503()
    sample = await _session_comment_input(session_id)
    signature = ai_analysis.input_signature({"comments": sample})
    record = await asyncio.to_thread(
        runtime.storage.get_ai_analysis, ai_analysis.KIND_COMMENT,
        ai_analysis.TARGET_SESSION, str(session_id))
    if not refresh and _ai_cache_hit(record, model, ai_analysis.COMMENT_PROMPT_VERSION,
                                     signature):
        return _comment_analysis_payload(session_id, record, cached=True)
    try:
        analysis = await analyze_comments(sample)
    except AIError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    saved = await asyncio.to_thread(
        runtime.storage.save_ai_analysis, ai_analysis.KIND_COMMENT, ai_analysis.TARGET_SESSION,
        str(session_id), session_id=session_id, model=model,
        prompt_version=ai_analysis.COMMENT_PROMPT_VERSION, input_signature=signature,
        payload={"analysis": analysis, "comment_count": len(sample)})
    return _comment_analysis_payload(session_id, saved, cached=False)


def _streamer_review_input(profile: dict) -> dict:
    """配信者profileと全体解析からLLMへ渡す集約dictを組む。指紋もこの戻り値から取るので、
    実行経路と指紋計算で別のdictを作らないこと(作ると毎回cacheが外れる)。

    全体解析(信頼区間・標本数・被覆率つき)を併せて渡すのは、profileだけでは時間帯の話が
    「最も稼いだ15分枠top5」という粗い入力からしか語れないため。解析側の母集団は監視対象
    全体なので、review_digestが入れ物を分けて区別できる形にする。DB読みなので同期で組み、
    呼び出し側がto_threadへ逃がす。"""
    return review_digest.review_input(
        profile,
        time_index=runtime.storage.analytics_time_index(),
        retention=runtime.storage.analytics_retention(),
        entry_source=runtime.storage.analytics_entry_source(),
        battle_flow=runtime.storage.analytics_battle_flow(),
        coverage=runtime.storage.analytics_coverage(),
    )


@router.get("/api/streamers/{unique_id}/ai-review")
async def streamer_ai_review(unique_id: str) -> dict:
    """保存済みの講評のみを返す。無ければreview=nullで、LLMは起動しない。"""
    record = await asyncio.to_thread(
        runtime.storage.get_ai_analysis, ai_analysis.KIND_STREAMER_REVIEW,
        ai_analysis.TARGET_STREAMER, unique_id)
    payload = _ai_payload({"unique_id": unique_id}, record, cached=record is not None)
    payload["review"] = payload.pop("analysis")
    return payload


@router.post("/api/streamers/{unique_id}/ai-review")
async def run_streamer_ai_review(unique_id: str, refresh: int = 0) -> dict:
    """Natural-language growth review of a streamer from their aggregated profile.
    A compact summary (no raw events) is sent to the local model."""
    model = _ai_model_or_503()
    profile = await asyncio.to_thread(runtime.storage.streamer_profile, unique_id)
    if profile["count"] == 0:
        raise HTTPException(status_code=404, detail="この配信者の集計データがありません。")
    review_input = await asyncio.to_thread(_streamer_review_input, profile)
    signature = ai_analysis.input_signature(review_input)
    record = await asyncio.to_thread(
        runtime.storage.get_ai_analysis, ai_analysis.KIND_STREAMER_REVIEW,
        ai_analysis.TARGET_STREAMER, unique_id)
    base = {"unique_id": unique_id}
    if not refresh and _ai_cache_hit(record, model, ai_analysis.REVIEW_PROMPT_VERSION,
                                     signature):
        payload = _ai_payload(base, record, cached=True)
        payload["review"] = payload.pop("analysis")
        return payload
    try:
        review = await analyze_streamer(review_input)
    except AIError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    saved = await asyncio.to_thread(
        runtime.storage.save_ai_analysis, ai_analysis.KIND_STREAMER_REVIEW,
        ai_analysis.TARGET_STREAMER, unique_id, session_id=None, model=model,
        prompt_version=ai_analysis.REVIEW_PROMPT_VERSION, input_signature=signature,
        payload=review)
    payload = _ai_payload(base, saved, cached=False)
    payload["review"] = payload.pop("analysis")
    return payload
