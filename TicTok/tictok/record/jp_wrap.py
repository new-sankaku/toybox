"""日本語字幕の改行位置を決める段。

字幕が画面からはみ出すのは「折り返していない」からで、意味の通らない位置で切れるのは
「文字数で折っている」からである。この2つは別の問題で、どちらもここで解く。

== なぜ形態素解析が要るか ==

実録画の文字起こしから取った表示単位 126,719 件のうち、全角16文字を超えて折り返しが要るのは
14,500 件(11.4%)。この 14,500 件で方式を突き合わせた。物差しは「折った位置が形態素の内側か
(明白な誤り)」で、**自分以外の解析器**に判定させて循環を避けている:

====================  ==========  ==========  ==========  ==========
方式                  語内断裂    文節一致    行の不均衡  ちぎれ行
====================  ==========  ==========  ==========  ==========
文字数で折る                49.7%        9.5%       12.31       63.0%
規則ベース(辞書なし)        11.0%       68.9%        5.27       14.1%
SudachiPy(mode C)          7.2%          --        3.34        2.9%
fugashi(unidic-lite)       3.4%       72.8%        3.75        3.8%
====================  ==========  ==========  ==========  ==========

「文節一致」は解析器2つが**どちらも**文節の頭と認めた割合、「ちぎれ行」は短い方の行が
全角5字未満になった割合である。

fugashiの切り位置はSudachiPyが 96.6% 認め、逆は 92.8% しか認めない。辞書を持たない規則
(字種の変わり目＋助詞表)は文字数よりは遥かに良いが、語内断裂が3倍以上残る。**最も品質の
高い fugashi + unidic-lite を採る。**

解析器が無い環境で文字数へ落とすことはしない。落ちたことは成果物を見るまで誰にも分からず、
「意味不明な所で切られる」という元の症状に静かに戻るだけである。無ければ理由を名乗って
止まる(:func:`tagger` が導入方法つきで送出する)。

== 切れ目の優先度と、行の釣り合いの釣り合い ==

文節境界ならどこでもよいわけではない。句点の後と、複合語の内側かもしれない位置は同じ価値では
ない。品詞から切れ目に点数を付け、``score = cost * WEIGHT + 行の不揃い`` を最小化する。

``WEIGHT`` は実データで掃引して決めた。大きいほど意味の切れ目を優先し、行が不揃いになる:

=====  ==========  ==========  ==========  ==========
重み   語内断裂    文節一致    行の不均衡  ちぎれ行
=====  ==========  ==========  ==========  ==========
0            7.3%       42.2%        1.35        0.1%
1.0          4.3%       66.9%        2.57        0.6%
2.0          3.4%       72.8%        3.75        3.8%
3.0          3.3%       73.4%        4.23        6.4%
6.0          3.2%       74.3%        4.83        9.6%
=====  ==========  ==========  ==========  ==========

2を超えると、語内断裂が 0.1〜0.2pt しか改善しない一方でちぎれ行が倍増する。**2 が膝である。**

== 折る前に「折りやすさ」を言えること ==

枚(cue)をどこで割るかが、行をどこで折れるかを決めてしまう。枚が予算いっぱいになると1行目の
許容幅が数文字まで狭まり、そこに形態素境界が1つしか無ければ、それが文節を割る位置でも選ぶ
しかない。:func:`layout_badness` はそれを**折る前に**数字で返すためにあり、枚を割る段
(:func:`tictok.record.subtitles._plan_segment`)がこれを見て、折れない枚を作らないようにする。

測り方と、実装中に見つかった落とし穴(「非自立可能」の扱い)は doc/SUBTITLE_LINEBREAK.md。
"""

import logging
import math
import threading
import unicodedata

logger = logging.getLogger(__name__)

# 切れ目の良さ(小さいほど良い)。品詞から決まる。
COST_SENTENCE_END = 0      # 「。！？」の後 — 文が終わっている
COST_COMMA = 1             # 「、」の後 — 節が終わっている
COST_CONJUNCTION = 2       # 接続詞・感動詞の前 — 次の文がそこから始まる
COST_CONJ_PARTICLE = 3     # 接続助詞(て・から・けど・ので・が)の後
COST_BINDING_PARTICLE = 4  # 係助詞・副助詞・終助詞(は・も・こそ)の後
COST_PARTICLE = 5          # 格助詞・助動詞の後
COST_OTHER = 7             # 上記以外の文節境界(副詞・連体詞の後など)
COST_ADNOMINAL_NO = 8      # 連体化の「の」の後 — 修飾語と被修飾語を引き剥がす
COST_CONTENT_JOIN = 9      # 自立語どうしが直に隣り合う — 複合語の内側でありうる
COST_INSIDE_BUNSETSU = 10  # 付属語の前 — 文節を割る(「終わらせ|たくない」)
COST_INSIDE_MORPHEME = 12  # 形態素の内側。行の折り返しには使わない(cue分割のみ)

# 切れ目の良さを、行の不揃い(全角文字数)と同じ土俵へ乗せる係数。上のtableで決めた。
WEIGHT = 2.0

# 行頭に置けない文字。この直前で折ると次行の頭に来る。
HEAD_FORBIDDEN = frozenset(
    "、。，．・：；？！?!,.:;"
    "ゝゞーぁぃぅぇぉっゃゅょゎゐゑァィゥェォッャュョヮヵヶ"
    "）］｝」』】〉》〕〙〗”’)]}»…‥〜～"
    "%％‰℃°ヶ々"
)
# 行末に置けない文字。この直後で折ると前行の末に来る。
TAIL_FORBIDDEN = frozenset("（［｛「『【〈《〔〘〖“‘([{«¥￥＄$#＃@＠")

_SENTENCE_END_CHARS = frozenset("。！？!?")
_COMMA_CHARS = frozenset("、，,")

# 直前がこれらの自立語だと、その境目は複合語の内側でありうる。
_CONTENT_POS = frozenset(("名詞", "動詞", "形容詞", "形状詞", "接頭辞", "接尾辞"))
# 付属語。文節はこれで**始まらない**ので、この前で折ると文節を割る。
_FUNCTION_POS = frozenset(("助詞", "助動詞", "接尾辞"))

_local = threading.local()


def tagger():
    """thread毎のfugashi Tagger。

    Taggerはthread safeではなく、焼き込みは ``asyncio.to_thread`` 越しに走るので
    thread localで持つ。構築は辞書の読み込みを伴うため使い回す。
    """
    tg = getattr(_local, "tagger", None)
    if tg is not None:
        return tg
    try:
        import fugashi  # noqa: PLC0415 — 辞書の読み込みを起動時から遅らせる
    except ImportError as exc:
        raise RuntimeError(
            "日本語字幕の改行位置を決めるのに形態素解析器(fugashi)が要ります。"
            "未installのため字幕は出せません: pip install fugashi unidic-lite"
        ) from exc
    try:
        tg = fugashi.Tagger()
    except Exception as exc:
        raise RuntimeError(
            "形態素解析器(fugashi)の辞書を読み込めませんでした。"
            "辞書が未installの可能性があります: pip install unidic-lite"
        ) from exc
    _local.tagger = tg
    return tg


def char_width(ch: str) -> float:
    """全角を1、半角を0.5として数えた1文字の表示幅。

    字幕の1行に何字入るかは本来は書体の送り幅で決まるが、SRT/VTTは書体を持たない書式なので
    読み手が何で描くか分からない。全角/半角の別だけは Unicode が持っているので、そこまでで
    数える。焼き込みASSは実測した送り幅を持っているので、そちらは ``measure`` で差し替える
    (:mod:`tictok.record.video_overlay`)。
    """
    if unicodedata.combining(ch) or ord(ch) in (0x200D, 0xFE0E, 0xFE0F):
        return 0.0
    return 1.0 if unicodedata.east_asian_width(ch) in ("W", "F", "A") else 0.5


def width(text: str, measure=None) -> float:
    """表示幅。``measure`` を渡すとその1文字あたりの幅で数える。"""
    fn = measure or char_width
    return sum(fn(ch) for ch in text)


def _kinsoku_ok(text: str, i: int) -> bool:
    """位置 i が禁則に触れないか。"""
    if i <= 0 or i >= len(text):
        return False
    if text[i] in HEAD_FORBIDDEN or text[i - 1] in TAIL_FORBIDDEN:
        return False
    # 結合文字・異体字selector・ZWJ の直前で切ると字形が壊れる
    if unicodedata.combining(text[i]) or ord(text[i]) in (0x200D, 0xFE0E, 0xFE0F):
        return False
    return ord(text[i - 1]) != 0x200D


def _is_auxiliary(prev, nxt) -> bool:
    """``nxt`` が直前の語に付いて1文節を成す補助用言か。

    unidicの「非自立可能」は**なり得る**という印で、そうであるとは言っていない。決めるのは
    直前の語の形である:

      * 「言っ|て|いたら」 — 接続助詞「て」の後は補助用言(「〜ている」「〜てくる」)
      * 「終わらせ|たく|ない」 — 連用形の後は補助用言(「〜たくない」)
      * 「でき|なかっ|たら|やり|に行く」 — 仮定形「たら」の後は節が切れており、
        「やり」は独立した動詞。ここは折ってよい

    形を見ずに「非自立可能」だけで束縛と決めると、後者まで折れなくなる。
    """
    if nxt[3] != "非自立可能":
        return False
    if prev[2] == "助詞" and prev[3] == "接続助詞":
        return True
    return prev[4].startswith("連用形")


def _token_cost(prev, nxt) -> float:
    """形態素境界の切れ目の良さ。前後の語の品詞と活用形で決まる。

    ``prev``/``nxt`` は ``(位置, 表記, 品詞大分類, 品詞中分類, 活用形)``。
    """
    prev_surface, prev_pos1, prev_pos2 = prev[1], prev[2], prev[3]
    next_surface, next_pos1 = nxt[1], nxt[2]
    if prev_surface and prev_surface[-1] in _SENTENCE_END_CHARS:
        return COST_SENTENCE_END
    if prev_surface and prev_surface[-1] in _COMMA_CHARS:
        return COST_COMMA
    # 文節は自立語で始まる。付属語と補助用言の前で折ると文節を割る。
    if next_pos1 in _FUNCTION_POS or _is_auxiliary(prev, nxt):
        return COST_INSIDE_BUNSETSU
    if next_pos1 == "接続詞" or (next_pos1 == "感動詞" and len(next_surface) > 1):
        return COST_CONJUNCTION
    if prev_pos1 == "助詞":
        if prev_pos2 == "接続助詞":
            return COST_CONJ_PARTICLE
        if prev_pos2 in ("係助詞", "副助詞", "終助詞"):
            return COST_BINDING_PARTICLE
        if prev_pos2 == "準体助詞" or prev_surface == "の":
            return COST_ADNOMINAL_NO
        return COST_PARTICLE
    if prev_pos1 == "助動詞":
        return COST_PARTICLE
    if prev_pos1 in _CONTENT_POS:
        return COST_CONTENT_JOIN
    return COST_OTHER


def break_costs(text: str) -> list:
    """長さ ``len(text)+1`` の配列。``i`` は ``text[:i]`` と ``text[i:]`` の境目の良さ。

    折ってはいけない位置(禁則・字形が壊れる位置・両端)は ``None``。形態素の内側は
    ``COST_INSIDE_MORPHEME`` で、行の折り返しには使わないが、語の時刻でしか割れない
    cue分割からは選べる。
    """
    costs = [COST_INSIDE_MORPHEME] * (len(text) + 1)
    costs[0] = None
    costs[len(text)] = None
    if not text:
        return costs
    tokens = []
    pos = 0
    for word in tagger()(text):
        feature = word.feature
        tokens.append((pos, word.surface, feature.pos1 or "*", feature.pos2 or "*",
                       feature.cForm or "*"))
        pos += len(word.surface)
    for k in range(1, len(tokens)):
        index = tokens[k][0]
        if 0 < index < len(text):
            costs[index] = _token_cost(tokens[k - 1], tokens[k])
    for i in range(1, len(text)):
        if not _kinsoku_ok(text, i):
            costs[i] = None
    return costs


def _prefix_widths(text: str, measure=None) -> list:
    fn = measure or char_width
    out = [0.0]
    for ch in text:
        out.append(out[-1] + fn(ch))
    return out


def _two_lines(text: str, costs: list, widths: list, per_line: float):
    """2行へ割る最良の位置。割れなければ ``None``。

    :func:`_layout` を ``lines=2`` で回したのと**同じ答えを返す**。目標幅が全体の半分なので
    「各行の目標からのずれの和」は行長の差そのものになり、DPを組まずに1回の走査で解ける。
    枚を割る段が候補ごとにこれを呼ぶので、2行(既定であり縦画面の既定でもある)だけは
    畳んでおかないと、同じ計算をn倍繰り返すことになる。
    """
    total = widths[len(text)]
    best = None
    for i in range(1, len(text)):
        cost = costs[i]
        if cost is None or cost >= COST_INSIDE_MORPHEME:
            continue
        first = widths[i]
        second = total - first
        if first > per_line or second > per_line:
            continue
        score = cost * WEIGHT + abs(first - second)
        if best is None or score < best[0]:
            best = (score, [i])
    return best


def _layout(text: str, costs: list, widths: list, lines: int,
            per_line: float, allow_overflow: bool):
    """``lines`` 本ちょうどへ割る最良の分け方。割れなければ ``None``。

    最小化するのは ``切れ目のcost * WEIGHT + 各行の目標幅からのずれ``。目標幅は
    ``全体 / 行数`` なので、2行なら「ずれの和」は行長の差そのものになる(掃引で使った
    物差しと同じ量)。
    """
    length = len(text)
    target = widths[length] / lines
    infinity = float("inf")
    # best[k][i] = text[:i] を k 行で覆う最小score
    best = [[infinity] * (length + 1) for _ in range(lines + 1)]
    back = [[-1] * (length + 1) for _ in range(lines + 1)]
    best[0][0] = 0.0
    for k in range(1, lines + 1):
        for end in range(1, length + 1):
            # 最終行は end == length のみ
            if k == lines and end != length:
                continue
            for start in range(0, end):
                if best[k - 1][start] == infinity:
                    continue
                if start > 0 and (costs[start] is None or costs[start] >= COST_INSIDE_MORPHEME):
                    continue
                line_width = widths[end] - widths[start]
                if line_width > per_line and not allow_overflow:
                    continue
                score = best[k - 1][start] + abs(line_width - target)
                if line_width > per_line:
                    # 溢れは不揃いより重い罰にする(溢れない分け方があるなら必ずそちらを選ぶ)
                    score += (line_width - per_line) * 100.0
                if start > 0:
                    score += costs[start] * WEIGHT
                if score < best[k][end]:
                    best[k][end] = score
                    back[k][end] = start
    if best[lines][length] == infinity:
        return None
    cuts = []
    end = length
    for k in range(lines, 0, -1):
        start = back[k][end]
        if start > 0:
            cuts.append(start)
        end = start
    cuts.reverse()
    return best[lines][length], cuts


def wrap(text: str, per_line: float, max_lines: int, measure=None) -> list:
    """``text`` を、意味の切れ目で ``max_lines`` 行以内へ折る。

    ``per_line`` と ``measure`` は同じ単位であること。既定は全角換算の文字数で、焼き込みは
    実測した送り幅のpixel値を渡す(折り返し幅は描く書体で測らないと実物とずれる)。

    **文字は1つも捨てない。** ``max_lines`` 行に収まらない場合も、最も溢れの少ない分け方で
    ``max_lines`` 行を返す(切り詰めるかどうかは呼び出し側が決める — 字幕fileでは捨てず、
    焼き込みは画面を覆わないよう別に上限を持つ)。

    行数は少ないほど良いので、収まる最小の行数を採る。1行に収まる文は折らない。
    """
    # 折る必要が無い文でも先に確かめる。長い文が来たときだけ落ちる形にすると、同じ設定・
    # 同じ経路が素材によって成功したり失敗したりする。
    tagger()
    text = text.strip()
    if not text:
        return []
    if per_line <= 0 or max_lines <= 1:
        return [text]
    widths = _prefix_widths(text, measure)
    if widths[-1] <= per_line:
        return [text]
    costs = break_costs(text)
    lower = max(2, math.ceil(widths[-1] / per_line - 1e-9))
    for lines in range(lower, max_lines + 1):
        found = (_two_lines(text, costs, widths, per_line) if lines == 2
                 else _layout(text, costs, widths, lines, per_line, allow_overflow=False))
        if found:
            return _slice(text, found[1])
    # どう割っても収まらない(1形態素が1行より長い等)。溢れを最小にして最大行数へ割る。
    found = _layout(text, costs, widths, max_lines, per_line, allow_overflow=True)
    return _slice(text, found[1]) if found else [text]


def _slice(text: str, cuts: list) -> list:
    out, prev = [], 0
    for cut in cuts:
        out.append(text[prev:cut])
        prev = cut
    out.append(text[prev:])
    return [line for line in out if line]


def layout_badness(text: str, costs, per_line: float, max_lines: int,
                   measure=None) -> float:
    """``text`` を折るときに選ばれる切れ目のうち、**最も悪いもの**の点数。1行なら0。

    「この文は良い位置で折れるか」を、折る前に数字で言うための関数である。枚(cue)を割る段が
    これを見て、良い位置で折れない枚を作らないようにする。

    ``costs`` は ``text`` と同じ長さ+1の配列。全体の配列から切り出して渡せる —— 枚の候補
    ごとに解析し直すと、同じ文を何度も解析することになる。切り出した端は境目ではないので、
    ここで無効化する(呼び出し側に揃えさせると、揃え忘れが黙って端で折る形で出る)。
    """
    widths = _prefix_widths(text, measure)
    if widths[-1] <= per_line:
        return 0.0
    costs = list(costs)
    costs[0] = None
    costs[len(text)] = None
    lower = max(2, math.ceil(widths[-1] / per_line - 1e-9))
    for lines in range(lower, max_lines + 1):
        found = (_two_lines(text, costs, widths, per_line) if lines == 2
                 else _layout(text, costs, widths, lines, per_line, allow_overflow=False))
        if found:
            return max((costs[cut] for cut in found[1]), default=0.0)
    return float(COST_INSIDE_MORPHEME)


def split_cost(costs: list, index: int) -> float:
    """cue分割から見た切れ目の良さ。

    cueの切れ目は**語の時刻がある位置**にしか置けないので、行の折り返しと違って禁則位置も
    形態素の内側も候補から外せない(外すと時刻の無い位置で割ることになる)。使えない位置は
    最悪の点として扱い、他に候補があれば必ずそちらが選ばれるようにする。
    """
    if index <= 0 or index >= len(costs):
        return COST_INSIDE_MORPHEME
    cost = costs[index]
    return COST_INSIDE_MORPHEME + 8.0 if cost is None else cost
