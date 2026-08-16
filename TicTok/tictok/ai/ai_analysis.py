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
    get_ai_chapter_chunk_chars,
    get_ai_chapter_max,
    get_ai_chapter_min_seconds,
    get_ai_chapter_per_chunk,
    get_ai_clip_description_chars,
    get_ai_clip_hashtag_max,
    get_ai_clip_title_chars,
    get_ai_comment_sample,
    get_ai_comment_sample_windows,
    get_ai_enabled,
    get_ai_json_schema_enabled,
    get_ai_max_tokens,
    get_ai_model,
    get_ai_timeout_seconds,
)
# 「使えるsegment」の判定(時刻欠落・end<=start・空text)と時刻mapの版判定は字幕書き出しと
# 共有する。ここで別に書くと定義が2つに割れ、字幕には出るが章立てには出ない発話が生まれる。
from tictok.record.subtitles import timemap_current, usable_segments

logger = logging.getLogger("tictok.ai")


class AIError(RuntimeError):
    """AI機能が無効・未設定・到達不能、または応答が不正なときに送出する。"""


# 保存済み結果を再利用してよいかの判定に使うprompt版。system prompt・schema・組み立てを
# 変えたら必ず+1すること。+1しない限り、新しいpromptで得られるはずの結果が古いcacheで
# 隠れ続ける(model名とprompt版と入力指紋の3つが一致したときだけcacheを返す)。
COMMENT_PROMPT_VERSION = 2
REVIEW_PROMPT_VERSION = 2
CHAPTERS_PROMPT_VERSION = 1
CLIP_META_PROMPT_VERSION = 1

# ai_analysis表のkind/target_type。DBのkeyなので画面・APIの文言とは分けて固定する。
KIND_COMMENT = "comment_analysis"
KIND_STREAMER_REVIEW = "streamer_review"
KIND_CHAPTERS = "chapters"
KIND_CLIP_META = "clip_meta"
TARGET_SESSION = "session"
TARGET_STREAMER = "streamer"
TARGET_RECORDING = "recording"
# shortは録画の一部分なので、録画idだけでは的を指せない。target_idは範囲まで含めた文字列
# (:func:`clip_target_id`)で、同じ録画の別範囲が別の行になる。
TARGET_CLIP = "clip"


def clip_target_id(recording_id: int, start: float, end: float) -> str:
    """short 1本を指すcacheのkey。範囲をmilli秒まで書くのは、範囲確定が吸着で数百ms動く
    ためで、秒で丸めると別の範囲が同じ的を指す。"""
    return f"{int(recording_id)}:{float(start):.3f}-{float(end):.3f}"


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
        logger.warning("AI endpointへ接続できません: %s", exc, exc_info=True)
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
    logger.info("配信者の講評が完了しました: model=%s", get_ai_model())
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
    logger.info("commentの分析が完了しました: comment %d件, model=%s", len(cleaned), get_ai_model())
    return data


# ---- 章立て(chapter)生成 ---------------------------------------------------------------
# 3時間級の文字起こしは一度にmodelの文脈へ入らないため、map-reduceで組む。
#   map:    文字起こしを予算内のchunkへ割り、chunkごとに「話題が変わる行」を候補として出させる。
#   reduce: 候補の一覧(title+時刻)だけをもう一度渡し、最終的に残す候補と表題を選ばせる。
#
# 時刻をmodelに書かせないことがこの実装の要点である。map/reduceのどちらでもmodelが返すのは
# **提示した行/候補の番号**だけで、秒はこちら側がsegmentのstartから引く。modelが時刻を書ける
# 形にすると、存在しない位置を指す章が混ざっても検出する手段が無くなる(章の誤りは、そこへ
# seekして初めて分かる種類の誤りなので、静かに壊れる)。番号方式なら「実在するsegmentの開始
# 時刻のいずれか」であることが構造的に保証され、LLMが誤り得るのは表題だけになる。


def _stamp(seconds: float) -> str:
    total = int(max(0.0, seconds))
    return f"{total // 3600}:{(total // 60) % 60:02d}:{total % 60:02d}"


def chapter_chunks(segments: list) -> list:
    """文字起こしsegmentを文字数予算でchunkへ割る。境界は必ずsegmentの切れ目に置く。

    重なりは付けない。chunkの先頭segmentはそれ自体がmap段の候補になり得るので、chunk境界に
    ある話題の切れ目は候補として拾える。重なりを入れると同じ話題が2つのchunkから別々の候補
    として出て、reduce段の入力が水増しされる。"""
    budget = max(1, get_ai_chapter_chunk_chars())
    chunks: list = []
    current: list = []
    size = 0
    for seg in segments:
        cost = len(seg["text"]) + 16
        if current and size + cost > budget:
            chunks.append(current)
            current = []
            size = 0
        current.append(seg)
        size += cost
    if current:
        chunks.append(current)
    return chunks


_CHAPTER_SYSTEM = (
    "あなたはライブ配信の書き起こしを読み、話題の切れ目を見つけて目次を作る編集者です。"
    "出力は指定のJSON形式のみとし、日本語で記述してください。JSON以外の文字は一切出力しないでください。"
)

_CHAPTER_RULES = (
    "- 話題が実際に切り替わる行だけを選ぶこと。一定間隔で機械的に区切らない。\n"
    "- title は書き起こしに実際に出てくる内容だけで書く。推測で補わないこと。\n"
    "- title は20文字以内の名詞句にする（「〜について話す」のような冗長な語尾を付けない）。\n"
    "- 行番号は必ず提示した範囲内の整数にする。書き起こしに無い時刻や行番号を作らないこと。\n"
    "- 雑談が続くだけで話題が変わらない場合は、候補を無理に増やさず少なく返してよい。"
)

_CHAPTER_MAP_SCHEMA_HINT = (
    '{\n'
    '  "chapters": [{"line": <行番号>, "title": "<20文字以内の表題>"}]\n'
    '}'
)

def _chapter_json_schema(key: str, limit: int, maximum: int) -> dict:
    """章listのschema。件数上限は設定値なので定数では書けず、実行時に組む。

    maxItemsを載せるのが要点。promptで「最大N件」と言うだけでは復号は止まらず、局所model
    は文脈上限まで章を出し続けてfinish_reason=lengthで落ちる(=解析不能なJSON)。行番号側の
    maximumも同様に、範囲外の行を復号段階で弾くために入れる。"""
    return {
        "type": "object",
        "properties": {
            "chapters": {
                "type": "array",
                "maxItems": max(1, limit),
                "items": {
                    "type": "object",
                    "properties": {
                        key: {"type": "integer", "minimum": 1, "maximum": max(1, maximum)},
                        "title": {"type": "string"},
                    },
                    "required": [key, "title"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["chapters"],
        "additionalProperties": False,
    }


_CHAPTER_REDUCE_SCHEMA_HINT = (
    '{\n'
    '  "chapters": [{"id": <候補番号>, "title": "<20文字以内の表題>"}]\n'
    '}'
)


def _clean_title(value) -> str:
    """表題を1行へ均す。長さの上限はpromptで指示するがmodelは超えることがあるので、
    表示側で切るのではなくここで確定させる(cacheに入る値と画面の値を同じにする)。"""
    text = str(value or "").strip().replace("\n", " ")
    text = " ".join(text.split())
    return text[:40]


def _map_messages(lines: list, first_at: float, last_at: float, opening: bool) -> list:
    # 冒頭chunkでは1行目を必ず候補に入れさせる。冒頭が章にならないと目次が途中から始まり、
    # 投稿説明欄のchapterとしても認識されない。ここで採らせず後段で0秒へ寄せて埋めるのは、
    # 別の話題の区間を1章目の表題で覆うことになるので採らない(_finalizeの注記を参照)。
    head = ("- 1行目は配信の冒頭なので、必ず1件目の候補に含めること。\n" if opening else "")
    body = "\n".join(lines)
    user = (
        f"以下はライブ配信の書き起こしの一部です（{_stamp(first_at)}〜{_stamp(last_at)}、"
        f"{len(lines)}行）。各行は「行番号 [時刻] 発話」の形式です。\n\n"
        f"<transcript>\n{body}\n</transcript>\n\n"
        f"話題が切り替わる行を最大{get_ai_chapter_per_chunk()}件選び、次のJSON形式で出力してください"
        "（JSON以外は出力しない）:\n"
        f"{_CHAPTER_MAP_SCHEMA_HINT}\n\n"
        f"{head}{_CHAPTER_RULES}"
    )
    return [
        {"role": "system", "content": _CHAPTER_SYSTEM},
        {"role": "user", "content": user},
    ]


def _reduce_messages(candidates: list, total_seconds: float) -> list:
    listing = "\n".join(
        f"{i} [{_stamp(c['start'])}] {c['title']}" for i, c in enumerate(candidates, start=1)
    )
    user = (
        f"以下は{_stamp(total_seconds)}のライブ配信について、書き起こしを分割して抽出した"
        f"章の候補です（{len(candidates)}件、時刻順）。分割して読ませたため、同じ話題が"
        "重複していたり、目次としては細かすぎる区切りが含まれています。\n\n"
        f"<candidates>\n{listing}\n</candidates>\n\n"
        f"目次として残す候補を最大{get_ai_chapter_max()}件選び、次のJSON形式で出力してください"
        "（JSON以外は出力しない）:\n"
        f"{_CHAPTER_REDUCE_SCHEMA_HINT}\n\n"
        "- id は上の候補番号をそのまま使う。候補に無い番号や新しい時刻を作らないこと。\n"
        "- 候補1（配信の冒頭）は必ず残すこと。\n"
        "- 同じ話題が連続する候補は1つにまとめ、最も早い候補の id を残す。\n"
        "- title は候補の表題を整えたもので、20文字以内の名詞句にする。\n"
        "- 候補に書かれていない内容を title に足さないこと。\n"
        "- 配信全体を通して読める目次にする（一部の時間帯に偏らせない）。"
    )
    return [
        {"role": "system", "content": _CHAPTER_SYSTEM},
        {"role": "user", "content": user},
    ]


def _select_candidates(data: dict, chunk: list) -> list:
    """map段の応答から、実在するsegmentを指す候補だけを取り出す。

    範囲外の行番号は落とす(近い行へ寄せない)。modelが範囲外を返したということは、その章の
    位置に根拠が無いということなので、寄せると根拠の無い位置に章が立つ。"""
    picked: dict = {}
    for item in data.get("chapters") or []:
        if not isinstance(item, dict):
            continue
        try:
            line = int(item.get("line"))
        except (TypeError, ValueError):
            continue
        if not 1 <= line <= len(chunk):
            continue
        title = _clean_title(item.get("title"))
        if not title:
            continue
        seg = chunk[line - 1]
        # 同じsegmentを2度指してきたら先に出たものを残す。
        picked.setdefault(seg["start"], {"start": seg["start"], "title": title,
                                         "quote": seg["text"]})
    return [picked[k] for k in sorted(picked)]


def _thin(chapters: list, min_seconds: float, limit: int) -> list:
    """時刻順の章listから、最小間隔と最大件数を満たす部分列を採る。

    先頭から貪欲に残す。「重要度順に残す」ことはできない(重要度はmodelの返り値に無く、
    こちらで作れば捏造になる)ため、時間軸で均すのではなく素直に前から詰める。"""
    kept: list = []
    for chapter in chapters:
        if kept and chapter["start"] - kept[-1]["start"] < min_seconds:
            continue
        kept.append(chapter)
        if len(kept) >= limit:
            break
    return kept


def _finalize(chapters: list, segments: list, duration) -> list:
    """章の区間を確定させる。終端は次章の開始、最後の章は実尺(取れなければ最終segmentの終端)。

    先頭の章は、それが最初のsegmentから始まっているときに限り0秒まで伸ばす。この場合に
    増える区間は最初の発話より前の無音だけなので、章の内容は変わらない。

    「章立ては動画全体を分割するものだから1章目は必ず0」として無条件に寄せてはならない。
    modelが冒頭を章にしなかった録画でそれをやると、1章目の表題が、その章が実際に始まる前の
    まったく別の話題の区間まで覆う(実測: 107秒地点で始まる話題の章が0秒からになり、冒頭の
    別の話題がその表題の下に入った)。引用も自分の開始位置を指さなくなり、ズレの検出手段が
    無くなる。冒頭が章にならなかったのなら、その事実をそのまま出す。"""
    if not chapters:
        return []
    items = [dict(c) for c in chapters]
    if segments and items[0]["start"] <= segments[0]["start"]:
        items[0]["start"] = 0.0
    if duration is not None and float(duration) > 0:
        tail = float(duration)
    else:
        tail = segments[-1]["end"]
    result = []
    for index, chapter in enumerate(items):
        end = items[index + 1]["start"] if index + 1 < len(items) else tail
        if end <= chapter["start"]:
            continue
        result.append({
            "start": round(float(chapter["start"]), 3),
            "end": round(float(end), 3),
            "title": chapter["title"],
            "quote": chapter["quote"],
        })
    return result


async def analyze_chapters(transcript: dict, media_duration=None) -> dict:
    """文字起こしから章立てを作る。``transcript`` は storage.get_transcript の戻り値そのもの。

    時刻mapが現行版でないtranscriptは拒否する。焼き込みと同じ理由で、ズレは尺に比例して
    大きくなり、出てきた章は「それらしいが合っていない目次」になる。合っていないことは
    そこへseekして初めて分かるので、警告して通す扱いにはしない。"""
    if not get_ai_enabled():
        raise AIError("AI機能が無効です（TICTOK_AI_ENABLED=1 を設定してください）。")
    if not get_ai_model():
        raise AIError("AI modelが未設定です（TICTOK_AI_MODEL を設定してください）。")
    if not transcript:
        raise AIError("この録画には文字起こしがありません。")
    if not timemap_current(transcript.get("timemap_version")):
        raise AIError(
            "この文字起こしは古い時刻mapで作られているため、章立ての時刻が動画とズレます。"
            "文字起こしをやり直してから実行してください。")
    segments = usable_segments(transcript.get("segments"), media_duration)
    if not segments:
        raise AIError("章立てに使える発話がありません。")

    chunks = chapter_chunks(segments)
    candidates: list = []
    for chunk_index, chunk in enumerate(chunks):
        lines = [
            f"{i} [{_stamp(seg['start'])}] {seg['text']}"
            for i, seg in enumerate(chunk, start=1)
        ]
        content = await _chat(
            _map_messages(lines, chunk[0]["start"], chunk[-1]["end"], chunk_index == 0),
            _chapter_json_schema("line", get_ai_chapter_per_chunk(), len(chunk)),
            "chapter_candidates")
        candidates.extend(_select_candidates(_extract_json(content), chunk))
    candidates.sort(key=lambda c: c["start"])
    if not candidates:
        raise AIError("話題の切れ目を検出できませんでした。")

    if len(chunks) == 1:
        # chunkが1つならmap段の候補は既に配信全体を通した一貫した並びなので、統合は要らない。
        chapters = candidates
        reduced = False
    else:
        content = await _chat(
            _reduce_messages(candidates, segments[-1]["end"]),
            _chapter_json_schema("id", get_ai_chapter_max(), len(candidates)),
            "chapter_merge")
        chosen: dict = {}
        for item in _extract_json(content).get("chapters") or []:
            if not isinstance(item, dict):
                continue
            try:
                index = int(item.get("id"))
            except (TypeError, ValueError):
                continue
            if not 1 <= index <= len(candidates):
                continue
            title = _clean_title(item.get("title"))
            source = candidates[index - 1]
            # 表題はreduce段のものを採るが、時刻と引用はmap段で確定した候補のまま使う。
            # reduce段は「どれを残すか」だけを決める役で、位置を動かす権限は持たない。
            chosen.setdefault(source["start"], {
                "start": source["start"],
                "title": title or source["title"],
                "quote": source["quote"],
            })
        chapters = [chosen[k] for k in sorted(chosen)]
        reduced = True
        if not chapters:
            raise AIError("章の統合に失敗しました（候補が1つも選ばれませんでした）。")

    chapters = _thin(chapters, get_ai_chapter_min_seconds(), get_ai_chapter_max())
    result = {
        "chapters": _finalize(chapters, segments, media_duration),
        "segment_count": len(segments),
        "chunk_count": len(chunks),
        "candidate_count": len(candidates),
        "reduced": reduced,
    }
    logger.info(
        "chapterの生成が完了しました: %d chapter（%d segment / %d chunk）, model=%s",
        len(result["chapters"]), len(segments), len(chunks), get_ai_model(),
        extra={"event": "ai.chapters_done",
               "ctx": {"chapters": len(result["chapters"]), "segments": len(segments),
                       "chunks": len(chunks), "candidates": len(candidates)}},
    )
    return result


# ---------------------------------------------------------------------------------------
# short の題名・説明・hashtag・表紙
# ---------------------------------------------------------------------------------------

_CLIP_SYSTEM = (
    "あなたはライブ配信の切り抜き動画に、題名・説明・hashtagを付ける編集者です。"
    "出力は指定のJSON形式のみとし、日本語で記述してください。JSON以外の文字は一切出力しないでください。"
)

_CLIP_RULES = (
    "- 題名・説明は、提示した発話に実際に出てくる内容だけで書く。推測で補わないこと。\n"
    "- 何が起きたかが分かる題名にする。「面白い場面」「神回」のような中身を持たない語は使わない。\n"
    "- 誇張しないこと。提示した発話より強い出来事が起きたように書かない。\n"
    "- hashtag は「#」を付けず語だけを返す。配信者名や、発話に出てくる語から選ぶ。\n"
    "- cover_line は、表紙にするのに最もふさわしい発話の行番号を1つ選ぶ。"
    "提示した範囲内の整数にすること。"
)


def _clean_text(value, limit: int) -> str:
    """1行へ均して上限で切る。上限は設定値なので呼び出し側から渡す。"""
    text = " ".join(str(value or "").strip().split())
    return text[:limit]


def _clean_hashtags(values, limit: int) -> list:
    """hashtagを語だけの列へ均す。先頭の「#」は落とし、重複と空を捨てる。

    modelは指示に関わらず「#」を付けてくることがある。ここで落としておかないと、投稿先で
    「##配信」になるか、こちらで二重に付けないよう表示側が各所で気を遣うことになる。
    """
    cleaned: list = []
    for value in values or []:
        word = " ".join(str(value or "").strip().split()).lstrip("#").strip()
        # 語中の空白と「#」は投稿先でtagが切れる原因になるので、そこで打ち切る。
        word = word.split()[0] if word.split() else ""
        word = word.split("#")[0]
        if word and word not in cleaned:
            cleaned.append(word)
        if len(cleaned) >= limit:
            break
    return cleaned


def _clip_json_schema(line_count: int) -> dict:
    """題名・説明・hashtag・表紙行のschema。

    件数と行番号の上限をschemaへ載せるのが要点で、chapterと同じ理由である。promptで
    「最大N件」と言うだけでは復号は止まらず、範囲外の行番号も復号段階で弾けない。
    """
    return {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "hashtags": {
                "type": "array",
                "maxItems": max(1, get_ai_clip_hashtag_max()),
                "items": {"type": "string"},
            },
            "cover_line": {"type": "integer", "minimum": 1,
                           "maximum": max(1, line_count)},
        },
        "required": ["title", "description", "hashtags", "cover_line"],
        "additionalProperties": False,
    }


_CLIP_SCHEMA_HINT = (
    '{\n'
    '  "title": "<題名>",\n'
    '  "description": "<説明>",\n'
    '  "hashtags": ["<語>"],\n'
    '  "cover_line": <行番号>\n'
    '}'
)


def _clip_messages(lines: list, context: dict, seconds: float) -> list:
    who = context.get("streamer") or ""
    why = context.get("reason") or ""
    comments = context.get("comments") or []
    intro = f"配信者: {who}\n" if who else ""
    if why:
        intro += f"この場面が候補になった理由: {why}\n"
    if comments:
        listing = " / ".join(comments)
        intro += f"この場面の視聴者コメント（抜粋）: {listing}\n"
    body = "\n".join(lines)
    user = (
        f"以下はライブ配信の切り抜き（{seconds:.0f}秒）の書き起こしです。"
        f"各行は「行番号 発話」の形式です。\n\n"
        f"{intro}\n"
        f"<transcript>\n{body}\n</transcript>\n\n"
        f"この切り抜きに付ける題名（{get_ai_clip_title_chars()}文字以内）、"
        f"説明（{get_ai_clip_description_chars()}文字以内）、"
        f"hashtag（最大{get_ai_clip_hashtag_max()}語）、"
        "表紙にする発話の行番号を、次のJSON形式で出力してください（JSON以外は出力しない）:\n"
        f"{_CLIP_SCHEMA_HINT}\n\n"
        f"{_CLIP_RULES}"
    )
    return [
        {"role": "system", "content": _CLIP_SYSTEM},
        {"role": "user", "content": user},
    ]


def clip_lines(segments: list, start: float, end: float) -> list:
    """範囲に掛かる発話segmentだけを、時刻順で返す。

    掛かっていれば端が範囲の外へはみ出していても採る。切り出しの端は無音や発話の切れ目へ
    吸着させてあるので、はみ出す量は語の途中までであり、その語を落とすと題名の根拠が欠ける。
    """
    picked = []
    for seg in segments or []:
        try:
            seg_start, seg_end = float(seg["start"]), float(seg["end"])
            text = str(seg.get("text") or "").strip()
        except (KeyError, TypeError, ValueError):
            continue
        if not text or seg_end <= start or seg_start >= end:
            continue
        picked.append({"start": seg_start, "end": seg_end, "text": text})
    picked.sort(key=lambda s: s["start"])
    return picked


async def analyze_clip_meta(segments: list, start: float, end: float,
                            context: dict | None = None) -> dict:
    """short 1本ぶんの題名・説明・hashtag・表紙位置を作る。

    **秒はmodelに書かせない。** 表紙の位置はmodelが選んだ行番号から、こちら側がsegmentの
    ``start`` を引いて決める。章立てと同じ理由で、時刻を書かせる形にすると存在しない位置を
    指す表紙が混ざっても検出する手段が無くなる。範囲外の行番号は近い行へ寄せずに落とし、
    表紙位置を ``None`` のまま返す — 寄せれば根拠の無い位置が表紙になる。
    """
    if not get_ai_enabled():
        raise AIError("AI機能が無効です（TICTOK_AI_ENABLED=1 を設定してください）。")
    if not get_ai_model():
        raise AIError("AI modelが未設定です（TICTOK_AI_MODEL を設定してください）。")
    lines = clip_lines(segments, float(start), float(end))
    if not lines:
        raise AIError("この範囲には題名の根拠になる発話がありません。")

    numbered = [f"{i} {line['text']}" for i, line in enumerate(lines, start=1)]
    content = await _chat(
        _clip_messages(numbered, context or {}, float(end) - float(start)),
        _clip_json_schema(len(lines)), "clip_meta")
    data = _extract_json(content)

    title = _clean_text(data.get("title"), get_ai_clip_title_chars())
    if not title:
        raise AIError("題名が空で返りました。")
    cover_line = None
    cover_seconds = None
    try:
        index = int(data.get("cover_line"))
    except (TypeError, ValueError):
        index = None
    if index is not None and 1 <= index <= len(lines):
        cover_line = index
        cover_seconds = round(lines[index - 1]["start"], 3)
    result = {
        "title": title,
        "description": _clean_text(data.get("description"),
                                   get_ai_clip_description_chars()),
        "hashtags": _clean_hashtags(data.get("hashtags"), get_ai_clip_hashtag_max()),
        "cover_line": cover_line,
        "cover_seconds": cover_seconds,
        "line_count": len(lines),
        "start": round(float(start), 3),
        "end": round(float(end), 3),
    }
    logger.info(
        "shortのmetadataを生成しました: %s（%d行, 表紙 %s）",
        title, len(lines), "なし" if cover_seconds is None else f"{cover_seconds:.1f}s",
        extra={"event": "ai.clip_meta_done",
               "ctx": {"lines": len(lines), "cover_seconds": cover_seconds,
                       "hashtags": len(result["hashtags"]),
                       "start": result["start"], "end": result["end"]}},
    )
    return result
