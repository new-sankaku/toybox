"""検索入力をFTS5のMATCH式とLIKE条件へ分解する。

trigram tokenizerは3文字未満のtokenを作らないため、短い語はMATCHで引けない。そこで
語ごとに長短を判定し、3文字以上はMATCH式へ、2文字以下はbodyのLIKE条件へ振り分ける。
両方が混ざる場合はMATCHで候補を絞ってからLIKEで濾すので、短い語を含む検索でも
全表走査にはならない。

対応する記法(利用者向けの説明は画面のhintと揃えること):
    ラーメン 美味しい   ... 両方を含む(AND)
    "ザル ラーメン"     ... 語順込みのフレーズ
    ラーメン -カップ    ... 後者を含むものを除外
    ラーメン OR うどん  ... どちらかを含む

``OR``がひとつでも現れたら、その検索の肯定語はすべてORで結ぶ。ANDとORの混在は
優先順位の説明が必要になり、入力欄1つのUIでは誤解の方が多いと判断した。
"""

import re

MIN_FTS_CHARS = 3

_TOKEN_RE = re.compile(r'(-?)"([^"]*)"|(\S+)')


class QueryError(ValueError):
    """検索式として成立しない入力(否定語しかない等)。"""


def _fts_phrase(text: str) -> str:
    return '"%s"' % text.replace('"', '""')


def _like_pattern(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def parse(raw: str) -> dict:
    """検索入力を分解して返す。

    戻り値:
        match       FTS5のMATCH式。肯定語が全て短くMATCHできない場合はNone。
        like_all    追加で満たすべきLIKE pattern(短い肯定語)。
        like_none   満たしてはいけないLIKE pattern(短い否定語)。
        terms       強調表示用の肯定語(引用符と符号を外したもの)。
    """
    raw = (raw or "").strip()
    if not raw:
        raise QueryError("検索語を入力してください。")

    use_or = " OR " in f" {raw} "
    positives: list = []
    negatives: list = []
    for match in _TOKEN_RE.finditer(raw):
        quoted_sign, quoted, bare = match.group(1), match.group(2), match.group(3)
        if quoted is not None:
            text, negated = quoted.strip(), quoted_sign == "-"
        else:
            token = bare
            if token == "OR":
                continue
            negated = token.startswith("-") and len(token) > 1
            text = token[1:] if negated else token
        text = text.strip()
        if not text:
            continue
        (negatives if negated else positives).append(text)

    if not positives:
        raise QueryError("除外語だけでは検索できません。含めたい語も入力してください。")

    long_positives = [t for t in positives if len(t) >= MIN_FTS_CHARS]
    short_positives = [t for t in positives if len(t) < MIN_FTS_CHARS]
    long_negatives = [t for t in negatives if len(t) >= MIN_FTS_CHARS]
    short_negatives = [t for t in negatives if len(t) < MIN_FTS_CHARS]

    match = None
    if long_positives:
        joiner = " OR " if use_or else " AND "
        match = joiner.join(_fts_phrase(t) for t in long_positives)
        if len(long_positives) > 1:
            match = f"({match})"
        if long_negatives:
            # FTS5のNOTは二項演算子。除外側をORで束ねて一度だけ引く。
            excluded = " OR ".join(_fts_phrase(t) for t in long_negatives)
            match = f"{match} NOT ({excluded})"
    else:
        # 肯定語が全て短い: MATCHできないので除外語もLIKE側で処理する。
        short_negatives = short_negatives + long_negatives

    return {
        "match": match,
        "like_all": [_like_pattern(t) for t in short_positives],
        "like_none": [_like_pattern(t) for t in short_negatives],
        "terms": positives,
        "or_mode": use_or,
    }
