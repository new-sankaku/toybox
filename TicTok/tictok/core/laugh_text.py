"""commentが笑いかどうかの判定。

切り抜き候補は既定で diamonds と comments のz-scoreで選ぶが、これは「盛り上がった」としか
言えず、gift連打が上位を占める。「配信者が笑っている・喜んでいる場面」を探すには別の信号が
要る。視聴者の笑いはその最も安価な代理で、**追加の依存もmodel fileも要らない**。

## 判定の設計と、実dataで訂正した既定値

実DB(84 session / 81,831 bucket / comment 76,368件 / 40日)で測って決めた。

- **単発の ``w`` を笑いに含める。** 当初は誤爆を恐れて2連以上を既定にしていたが、単発wのみで
  当たった3,468件のうちASCII英単語を含むもの88件を全数目視して**誤検出は0件**だった。
  前後のlookaroundが効いており ``new`` ``wow`` ``welcome`` ``w/`` ``windows`` は1件も拾わない。
  既定を2連以上にすると笑いcommentの**41%を捨てる**。
- **``藁`` は入れない。** 唯一のhitが「藁人形を打ち付ける時間帯」だった(TP 0 / FP 1)。
- **``草`` は複合語を除く。** 水草・除草・仕草・雑草で誤爆する。
- **gift案内templateを除く。** 配信者が定型で流す案内文に「爆笑」「🤣」が入っており、
  これを数えるとgift由来の汚染がそのまま笑い指標に乗る。同一session内で3回以上・20文字以上
  の本文を落とす(影響は全hitの0.6%)。
- **同一userの畳み込み(dedup)はしない。** 10秒bucketでは同一userが同じbucketに2回書くことが
  ほとんど無く、落ちるのは3.22%、相関の差は0.0002だった。実装を複雑にする価値が無い。
- タイ語の ``555`` は既定で使わない。有効にしてもhitは+2件で、数値との誤爆の方が大きい。

## 数え方

**1 commentは最大1件**として数える。``wwwwwwwwww`` を10と数えると、1人の長いwが「10人が別々に
草と打った場面」を上回る。盛り上がりは何人が笑ったかであって何文字打たれたかではない。

## 「かわいい」は入れない

笑いではなく好意・称賛の表明で、しかもgift誘発の常套句である。配信者が笑っている瞬間を探す
指標に混ぜると、外見への反応で盛り上がった場面が笑い候補の上位に来る。別のmetricとして
足せるよう、patternは種別ごとの辞書で持つ。
"""

import re
import unicodedata
from typing import Iterable, Optional

# 種別ごとのpattern。設定で差し替えられるよう辞書で持つ(丸ごと1本の正規表現にすると、
# どの種別が効いたのかを数えられず、誤爆したときに直す場所が分からない)。
# 連続wの前後lookaroundは必須。無いと new / wow / welcome / windows が全部当たる。
# ``w/``(=with)を除くため ``/`` も後方に除外する。
DEFAULT_PATTERNS = {
    "w_run": r"(?<![A-Za-z])[wW]{{{min_run},}}(?![A-Za-z/])",
    "kusa": r"大草原|(?<![水除仕雑薬海牧甘香乾])草(?![履食原案むみ刈])",
    "shou": r"笑(?!顔)",
    "warota": r"ワロタ|わろた|ワロス",
    "emoji": r"[😂🤣😆😹]",
    # NFKCは互換jamo(U+314B ㅋ / U+314E ㅎ)を初声jamo(U+110F / U+1112)へ畳むので、
    # 正規化後の字形も並べないと1件も当たらない。
    "kr": r"[ᄏㅋ]{2,}|[ᄒㅎ]{2,}",
    # ``hah(a)+`` だと ``hahaha`` の末尾で \b が立たず(次がhで語中)当たらない。
    "en": r"(?i)\b(?:lol|lmao|rofl|ha(?:ha)+)\b",
}

# 既定で無効にする種別。tha(555)は数値との誤爆が大きく、実dataでのhitは2件しか増えない。
DEFAULT_DISABLED = ("tha",)

OPTIONAL_PATTERNS = {
    "tha": r"555+",
}

# gift案内templateの判定。同一session内で同じ本文がこの回数以上現れ、かつこの長さ以上なら
# 定型文とみなす。実dataでの該当は703本文/落ちる笑いhitは51件(0.6%)。
TEMPLATE_MIN_REPEATS = 3
TEMPLATE_MIN_CHARS = 20


def compile_patterns(patterns: Optional[dict] = None, min_w_run: int = 1) -> dict:
    """種別 -> compiled patternの辞書を返す。

    ``min_w_run`` は笑いとみなす連続wの最小長。1が既定(実dataで単発wの誤検出が0件)。
    """
    source = dict(DEFAULT_PATTERNS if patterns is None else patterns)
    compiled = {}
    for kind, expr in source.items():
        if "{min_run}" in expr:
            expr = expr.format(min_run=max(1, int(min_w_run)))
        compiled[kind] = re.compile(expr)
    return compiled


def normalize(text: Optional[str]) -> str:
    """全角ｗ→w、全角記号→半角へ畳む。小文字化はしない(``W`` はpattern側で拾う)。"""
    return unicodedata.normalize("NFKC", text or "")


def classify(text: Optional[str], compiled: dict) -> Optional[str]:
    """当たった種別名を1つ返す(当たらなければNone)。

    1 commentは最大1件。複数種別に当たっても最初の1つだけを返す — 何人が笑ったかを
    数えるのが目的で、1人のcommentに何種類の笑い表現が入っていたかは関係が無い。
    """
    normalized = normalize(text)
    if not normalized:
        return None
    for kind, pattern in compiled.items():
        if pattern.search(normalized):
            return kind
    return None


def template_bodies(texts: Iterable[str], *, min_repeats: int = TEMPLATE_MIN_REPEATS,
                    min_chars: int = TEMPLATE_MIN_CHARS) -> set:
    """定型文とみなす本文の集合。

    配信者のgift案内templateは「爆笑」「🤣」を含むことがあり、そのまま数えるとgift由来の
    文言が笑い指標に化ける。同一sessionで繰り返される長い本文だけを落とす — 短い本文
    (「草」「www」)は繰り返されて当然なので、長さの条件が無いと本物を捨てる。
    """
    counts: dict = {}
    for text in texts:
        body = (text or "").strip()
        if len(body) >= min_chars:
            counts[body] = counts.get(body, 0) + 1
    return {body for body, n in counts.items() if n >= min_repeats}
