"""Local AI analysis over collected data via an OpenAI-compatible chat endpoint
(Ollama / llama.cpp server / LM Studio). Provider, model and endpoint are config-
driven (see config.py) so no provider/model is hard-coded. AI is opt-in and there is
no fallback: when disabled, unconfigured or unreachable this raises AIError and the
caller surfaces it as "unavailable" rather than fabricating a result."""

import json
import logging

import httpx

from tictok.core.config import (
    get_ai_api_key,
    get_ai_base_url,
    get_ai_comment_sample,
    get_ai_enabled,
    get_ai_model,
    get_ai_timeout_seconds,
)

logger = logging.getLogger("tictok.ai")


class AIError(RuntimeError):
    """AI機能が無効・未設定・到達不能、または応答が不正なときに送出する。"""


def ai_status() -> dict:
    model = get_ai_model()
    return {
        "enabled": get_ai_enabled(),
        "configured": bool(get_ai_enabled() and model),
        "model": model,
        "base_url": get_ai_base_url(),
    }


_SYSTEM_PROMPT = (
    "あなたはライブ配信のチャットコメントを分析するアナリストです。"
    "与えられた視聴者コメント群を読み、全体の感情傾向・主な話題・盛り上がりを分析します。"
    "出力は指定のJSON形式のみとし、日本語で記述してください。JSON以外の文字は一切出力しないでください。"
)

_SCHEMA_HINT = (
    '{\n'
    '  "sentiment": {"positive": <0-100>, "neutral": <0-100>, "negative": <0-100>},\n'
    '  "mood": "<全体の雰囲気を一文で>",\n'
    '  "topics": [{"label": "<話題>", "share": <0-100>, "example": "<代表コメント>"}],\n'
    '  "highlights": ["<特筆点>"]\n'
    '}'
)


def _build_messages(comments: list) -> list:
    joined = "\n".join(f"- {c}" for c in comments)
    user = (
        f"以下は配信中の視聴者コメントです（{len(comments)}件）。\n\n"
        f"<comments>\n{joined}\n</comments>\n\n"
        "次のJSON形式で出力してください（JSON以外は出力しない）:\n"
        f"{_SCHEMA_HINT}\n\n"
        "- sentiment は positive/neutral/negative のおおよその割合で、合計が概ね100になるようにする。\n"
        "- topics は主要な話題を share(%) の降順で最大6件、example は実際のコメントから引用する。\n"
        "- highlights は盛り上がりや特筆すべき点を最大5件。\n"
        "- mood は全体の雰囲気を簡潔な一文で。"
    )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


async def _chat(messages: list) -> str:
    url = get_ai_base_url() + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    api_key = get_ai_api_key()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = {
        "model": get_ai_model(),
        "messages": messages,
        "temperature": 0.2,
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=get_ai_timeout_seconds()) as client:
            resp = await client.post(url, json=body, headers=headers)
    except httpx.HTTPError as exc:
        logger.warning("AI endpoint unreachable: %s", exc, exc_info=True)
        raise AIError(f"AIエンドポイントへ接続できません（{get_ai_base_url()}）: {exc}") from exc
    if resp.status_code != 200:
        raise AIError(f"AI応答エラー (HTTP {resp.status_code}): {resp.text[:300]}")
    try:
        payload = resp.json()
        return payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as exc:
        raise AIError(f"AI応答の形式が不正です: {exc}") from exc


def _extract_json(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise AIError("AIがJSONを返しませんでした。modelを確認してください。")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise AIError(f"AI応答のJSON解析に失敗しました: {exc}") from exc


_REVIEW_SYSTEM = (
    "あなたはライブ配信のグロース分析の専門家です。"
    "与えられた配信者の集約データ（配信回数・コイン・視聴・固定ファン比率・収益集中度・Battle成績・"
    "時間帯傾向など）を基に、強み・課題・具体的な改善提案を述べます。"
    "出力は指定のJSON形式のみとし、日本語で記述してください。JSON以外の文字は一切出力しないでください。"
)

_REVIEW_SCHEMA = (
    '{\n'
    '  "summary": "<全体評を2-3文で>",\n'
    '  "strengths": ["<強み>"],\n'
    '  "issues": ["<課題>"],\n'
    '  "advice": ["<具体的な改善提案>"]\n'
    '}'
)


async def analyze_streamer(data: dict) -> dict:
    """Generate a natural-language growth review from a streamer's aggregated profile.
    `data` is a compact summary built by the caller (no raw event dumps)."""
    if not get_ai_enabled():
        raise AIError("AI機能が無効です（TICTOK_AI_ENABLED=1 を設定してください）。")
    if not get_ai_model():
        raise AIError("AI modelが未設定です（TICTOK_AI_MODEL を設定してください）。")
    summary = json.dumps(data, ensure_ascii=False, indent=2)
    user = (
        "以下は配信者の集約データです。\n\n"
        f"<data>\n{summary}\n</data>\n\n"
        "次のJSON形式で出力してください（JSON以外は出力しない）:\n"
        f"{_REVIEW_SCHEMA}\n\n"
        "- 数値の根拠に触れつつ具体的に。strengths/issues/advice は各最大5件。\n"
        "- advice は実行可能な提案にする（例: 伸びる時間帯への配信集中、固定ファン育成、Battle戦略）。"
    )
    messages = [
        {"role": "system", "content": _REVIEW_SYSTEM},
        {"role": "user", "content": user},
    ]
    content = await _chat(messages)
    result = _extract_json(content)
    logger.info("streamer review done: model=%s", get_ai_model())
    return result


async def analyze_comments(comments: list) -> dict:
    """Run sentiment/topic analysis over a batch of comment texts. Caps the sample to
    the configured size to bound prompt length / latency."""
    if not get_ai_enabled():
        raise AIError("AI機能が無効です（TICTOK_AI_ENABLED=1 を設定してください）。")
    if not get_ai_model():
        raise AIError("AI modelが未設定です（TICTOK_AI_MODEL を設定してください）。")
    cleaned = [c.strip().replace("\n", " ") for c in comments if c and c.strip()]
    if not cleaned:
        raise AIError("分析できるコメントがありません。")
    cleaned = cleaned[-get_ai_comment_sample() :]
    content = await _chat(_build_messages(cleaned))
    data = _extract_json(content)
    logger.info("comment analysis done: %d comments, model=%s", len(cleaned), get_ai_model())
    return data
