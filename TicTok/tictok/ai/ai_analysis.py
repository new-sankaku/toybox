"""Local AI analysis over collected data via an OpenAI-compatible chat endpoint
(Ollama / llama.cpp server / LM Studio). Provider, model and endpoint are config-
driven (see config.py) so no provider/model is hard-coded. AI is opt-in and there is
no fallback: when disabled, unconfigured or unreachable this raises AIError and the
caller surfaces it as "unavailable" rather than fabricating a result."""

import hashlib
import json
import logging

import httpx

from tictok.core.config import (
    get_ai_api_key,
    get_ai_base_url,
    get_ai_comment_sample,
    get_ai_comment_sample_windows,
    get_ai_enabled,
    get_ai_json_schema_enabled,
    get_ai_max_tokens,
    get_ai_model,
    get_ai_timeout_seconds,
)

logger = logging.getLogger("tictok.ai")


class AIError(RuntimeError):
    """AI機能が無効・未設定・到達不能、または応答が不正なときに送出する。"""


# 保存済み結果を再利用してよいかの判定に使うprompt版。system prompt・schema・組み立てを
# 変えたら必ず+1すること。+1しない限り、新しいpromptで得られるはずの結果が古いcacheで
# 隠れ続ける(model名とprompt版と入力指紋の3つが一致したときだけcacheを返す)。
COMMENT_PROMPT_VERSION = 2
REVIEW_PROMPT_VERSION = 2

# ai_analysis表のkind/target_type。DBのkeyなので画面・APIの文言とは分けて固定する。
KIND_COMMENT = "comment_analysis"
KIND_STREAMER_REVIEW = "streamer_review"
TARGET_SESSION = "session"
TARGET_STREAMER = "streamer"


def input_signature(payload) -> str:
    """LLMへ渡す入力の指紋。これが変わらない限り再実行しても同じ入力なのでcacheを返す。
    sort_keysで辞書順を固定し、dict構築順の違いで指紋が変わらないようにする。"""
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _allocate(counts: list, total: int) -> list:
    """各窓のcomment数に比例した割り当てを、合計が``total``ちょうどになるよう最大剰余法で
    決める。素の切り捨てだと窓数ぶんの端数が落ちて標本が要求より小さくなり、窓ごとに
    切り上げると合計が超過して結局末尾が溢れる。"""
    population = sum(counts)
    if population <= 0:
        return [0] * len(counts)
    exact = [n * total / population for n in counts]
    quotas = [min(counts[i], int(value)) for i, value in enumerate(exact)]
    remaining = total - sum(quotas)
    if remaining <= 0:
        return quotas
    # 残りは小数部の大きい窓から配る。同値のときはindex順(=時刻順)で決めるので、
    # 同じ入力からは常に同じ標本になる(指紋が揺れるとcacheが毎回外れる)。
    order = sorted(range(len(counts)), key=lambda i: (-(exact[i] - int(exact[i])), i))
    for i in order:
        if remaining <= 0:
            break
        if quotas[i] < counts[i]:
            quotas[i] += 1
            remaining -= 1
    return quotas


def _pick_evenly(items: list, quota: int) -> list:
    """窓の中から``quota``件を等間隔で採る。無作為抽出にすると同じ入力でも実行のたびに
    標本が変わり、入力指紋が一致しなくなるため決定的に選ぶ。"""
    n = len(items)
    if quota >= n:
        return list(items)
    return [items[(j * n) // quota] for j in range(quota)]


def comment_sample(entries: list) -> list:
    """analyze_commentsが実際にmodelへ渡す整形済みsample。指紋はこの結果から取る
    (整形前のlistで指紋を取ると、空白だけの差でcacheが外れる)。

    ``entries`` は ``(発生時刻, 本文)`` の列。配信を等間隔の窓へ割り、各窓のcomment数に
    比例した件数を窓の中から等間隔で採る**時間層化抽出**にしている。末尾N件を採る方式だと
    標本が配信終盤に偏り、出力されるsentiment比率が配信全体の推定量にならない(終盤だけ
    Battleや締めの挨拶で埋まっている配信では、その時間帯の空気が配信全体の評として出る)。
    時刻はcomment数の多い時間帯ほど多く採るためのものなので、単位は問わない(秒でよい)。
    """
    cleaned = [
        (float(t), c.strip().replace("\n", " "))
        for t, c in entries
        if c and c.strip() and t is not None
    ]
    if not cleaned:
        return []
    cleaned.sort(key=lambda item: item[0])
    cap = get_ai_comment_sample()
    if len(cleaned) <= cap:
        return [c for _, c in cleaned]
    windows = max(1, get_ai_comment_sample_windows())
    first, last = cleaned[0][0], cleaned[-1][0]
    span = last - first
    if span <= 0:
        # 全commentが同時刻(時刻が記録されていない等)。層に分ける根拠が無いので
        # 全区間から等間隔で採る。
        return [c for _, c in _pick_evenly(cleaned, cap)]
    grouped: list = [[] for _ in range(windows)]
    for t, text in cleaned:
        index = min(windows - 1, int((t - first) / span * windows))
        grouped[index].append(text)
    quotas = _allocate([len(g) for g in grouped], cap)
    sample: list = []
    for group, quota in zip(grouped, quotas):
        if quota > 0:
            sample.extend(_pick_evenly(group, quota))
    return sample


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

# 上のhintと同じ形をendpointへ渡す機械可読schema。llama.cpp server / Ollama はこれを
# 文法制約へ落として復号するので、brace走査で拾い直す必要がなくなる。hintを変えたら
# 必ずこちらも合わせること(2つがずれると、modelはhintに従い制約に弾かれる)。
_PERCENT = {"type": "number", "minimum": 0, "maximum": 100}
_COMMENT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "sentiment": {
            "type": "object",
            "properties": {"positive": _PERCENT, "neutral": _PERCENT, "negative": _PERCENT},
            "required": ["positive", "neutral", "negative"],
            "additionalProperties": False,
        },
        "mood": {"type": "string"},
        "topics": {
            "type": "array",
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "share": _PERCENT,
                    "example": {"type": "string"},
                },
                "required": ["label", "share", "example"],
                "additionalProperties": False,
            },
        },
        "highlights": {"type": "array", "maxItems": 5, "items": {"type": "string"}},
    },
    "required": ["sentiment", "mood", "topics", "highlights"],
    "additionalProperties": False,
}


def _build_messages(comments: list) -> list:
    joined = "\n".join(f"- {c}" for c in comments)
    user = (
        f"以下は配信中の視聴者コメントです（{len(comments)}件）。\n"
        "配信を等間隔の時間帯に割り、各時間帯のコメント数に比例して抜き出した標本で、"
        "時刻の古い順に並んでいます（配信の一部の時間帯に偏った抜粋ではありません）。\n\n"
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


async def _chat(messages: list, schema: dict, schema_name: str) -> str:
    """chat completionを1往復。``schema``は応答の形をendpoint側で拘束するためのJSON Schema
    で、設定で無効化したときだけprompt頼み(brace走査)になる。応答長を上限なしにすると、
    局所modelは長いcomment束に対して文脈上限まで書き続け、途中で切れた=解析不能なJSONが
    返るため max_tokens も明示する。"""
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
    max_tokens = get_ai_max_tokens()
    if max_tokens > 0:
        body["max_tokens"] = max_tokens
    if get_ai_json_schema_enabled():
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": schema_name, "schema": schema, "strict": True},
        }
    try:
        async with httpx.AsyncClient(timeout=get_ai_timeout_seconds()) as client:
            resp = await client.post(url, json=body, headers=headers)
    except httpx.HTTPError as exc:
        logger.warning("AI endpoint unreachable: %s", exc, exc_info=True)
        raise AIError(f"AIエンドポイントへ接続できません（{get_ai_base_url()}）: {exc}") from exc
    if resp.status_code != 200:
        hint = ""
        if resp.status_code == 400 and get_ai_json_schema_enabled():
            hint = ("（このendpointがresponse_format: json_schemaに対応していない可能性が"
                    "あります。TICTOK_AI_JSON_SCHEMA=0 で無効にできます）")
        raise AIError(f"AI応答エラー (HTTP {resp.status_code}): {resp.text[:300]}{hint}")
    try:
        payload = resp.json()
        choice = payload["choices"][0]
        content = choice["message"]["content"]
    except (KeyError, IndexError, ValueError) as exc:
        raise AIError(f"AI応答の形式が不正です: {exc}") from exc
    # 途中で切れた応答は必ずJSONとして壊れている。brace走査で拾えた断片を成功として
    # 返すと欠けた項目が「無かった」ことになるため、上限到達は明示的な失敗にする。
    if choice.get("finish_reason") == "length":
        raise AIError(
            f"AI応答が長さ上限({get_ai_max_tokens()} tokens)で打ち切られました。"
            "TICTOK_AI_MAX_TOKENS を増やしてください。")
    return content


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
    "時間帯傾向など）と、統計処理済みの解析指標を基に、強み・課題・具体的な改善提案を述べます。"
    "指標には標本数(n)・95%信頼区間(ci)・有意フラグ(significant)・被覆率(coverage)が付いています。"
    "これらは推定の確からしさを表すもので、必ず読んだうえで書いてください。"
    "出力は指定のJSON形式のみとし、日本語で記述してください。JSON以外の文字は一切出力しないでください。"
)

# 「捏造しない」を出力側で担保するための指示。統計値をそのまま渡すだけでは、局所modelは
# n=3の観測からでも断定形の助言を書く。根拠の弱さを言葉に出させることで、読み手が
# 確からしさを取り違えないようにする。
_REVIEW_RULES = (
    "- 数値の根拠に触れつつ具体的に。strengths/issues/advice は各最大5件。\n"
    "- significant が false、または n が min_observations 未満の指標を根拠に断定しないこと。"
    "触れる場合は「標本が少なく傾向は未確定」と明記し、断定形（〜である／〜すべき）を避ける。\n"
    "- ci がある指標は、区間の広さも読むこと。区間が広い（例: 勝率0.2〜0.8）なら結論は保留する。\n"
    "- coverage が低い指標は、その割合の母数が配信全体の一部でしかないことを明記する。\n"
    "- 値が null の項目は「取得できていない」であって0ではない。値があるかのように書かないこと。\n"
    "- cross_streamer_reference は監視対象の配信者全体の傾向であり、この配信者の実績ではない。"
    "この配信者の値と比べる用途にだけ使い、この配信者の数値として提示しないこと。\n"
    "- データに無い事実（視聴者層・配信内容・使用機材など）を推測で補わないこと。\n"
    "- advice は実行可能な提案にする（例: 伸びる時間帯への配信集中、固定ファン育成、Battle戦略）。"
)

_REVIEW_SCHEMA = (
    '{\n'
    '  "summary": "<全体評を2-3文で>",\n'
    '  "strengths": ["<強み>"],\n'
    '  "issues": ["<課題>"],\n'
    '  "advice": ["<具体的な改善提案>"],\n'
    '  "uncertain": ["<標本が少なく判断を保留した点>"]\n'
    '}'
)

_REVIEW_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "strengths": {"type": "array", "maxItems": 5, "items": {"type": "string"}},
        "issues": {"type": "array", "maxItems": 5, "items": {"type": "string"}},
        "advice": {"type": "array", "maxItems": 5, "items": {"type": "string"}},
        "uncertain": {"type": "array", "maxItems": 5, "items": {"type": "string"}},
    },
    "required": ["summary", "strengths", "issues", "advice", "uncertain"],
    "additionalProperties": False,
}


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
        f"{_REVIEW_RULES}\n"
        "- uncertain には、根拠が弱いために結論を保留した点を挙げる（無ければ空配列）。"
    )
    messages = [
        {"role": "system", "content": _REVIEW_SYSTEM},
        {"role": "user", "content": user},
    ]
    content = await _chat(messages, _REVIEW_JSON_SCHEMA, "streamer_review")
    result = _extract_json(content)
    logger.info("streamer review done: model=%s", get_ai_model())
    return result


async def analyze_comments(sample: list) -> dict:
    """Run sentiment/topic analysis over a prepared comment sample.

    ``sample`` は ``comment_sample`` の戻り値そのもの(整形済みの本文列)。ここで採り直さ
    ないのは、入力指紋を取ったlistと実際にmodelへ渡すlistを必ず同一にするため。"""
    if not get_ai_enabled():
        raise AIError("AI機能が無効です（TICTOK_AI_ENABLED=1 を設定してください）。")
    if not get_ai_model():
        raise AIError("AI modelが未設定です（TICTOK_AI_MODEL を設定してください）。")
    cleaned = [c for c in sample if c]
    if not cleaned:
        raise AIError("分析できるコメントがありません。")
    content = await _chat(_build_messages(cleaned), _COMMENT_JSON_SCHEMA, "comment_analysis")
    data = _extract_json(content)
    logger.info("comment analysis done: %d comments, model=%s", len(cleaned), get_ai_model())
    return data
