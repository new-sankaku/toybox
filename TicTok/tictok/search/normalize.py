"""検索の照合用に本文とqueryを同じ形へ畳む(表記ゆれの吸収)。

「ウザ」と「うざ」は同じ語だが、FTS5のtrigramもSQLiteのLIKEもcode point比較なので、
片方で引くともう片方が出ない。文字起こし(Whisperは漢字・カタカナ寄りに書く)とコメント(人は
ひらがな・全角半角が混ざる)を横断で引く画面では、この差がそのまま取りこぼしになる。
そこでindex時とquery時に同じ ``fold`` を通し、畳んだ形どうしで照合する。

**この畳み込みは必ず文字数を保つ**。畳んだ本文(``search_hits.body_norm``)で位置を見つけ、
その位置をそのまま元の本文へ当てて一致箇所を囲む(``mark``)ため、1文字が2文字になる
変換を混ぜると囲む位置がずれる。NFKC正規化を使わないのはこれが理由で、NFKCは
``ｶﾞ -> ガ``(2->1)や``㍿ -> 株式会社``(1->4)のように長さを変える。

畳むもの:
    ひらがな -> カタカナ      うざ = ウザ
    半角カナ -> 全角カナ      ｳｻﾞ の ｳ = ウ(濁点は下記の制限あり)
    全角英数記号 -> 半角      ＡＢＣ１２３ = ABC123
    英大文字 -> 小文字        Ramen = ramen
    全角空白 -> 半角空白

畳まないもの:
    濁点・半濁点(ウザとウサは別語)、小書き文字(ッとツは別語)、長音記号。
    半角カナの濁点は``ｻﾞ``のように2文字で1音を表すので、``ザ``へは畳めない(長さが変わる)。
    ``ｻ゛``までは寄るが``ザ``とは一致しない — 文字起こしにもコメントにも実例が無いため許容する。

索引へ載せる本文はさらに ``blank_mention`` を通す(``index_fold``)。返信コメントの先頭に付く
``@表示名`` は本文ではなく宛先なので、語で探すとその人の名前が全返信に当たる。原文には
残し、索引からだけ外す。
"""
from typing import Iterable, Optional

# 半角カナ U+FF61..U+FF9F の全角対応。濁点・半濁点は合成せず独立した記号へ写す(長さ保存)。
_HALFWIDTH_KANA_FIRST = 0xFF61
_HALFWIDTH_KANA = (
    "。「」、・ヲァィゥェォャュョッーアイウエオカキクケコサシスセソタチツテト"
    "ナニヌネノハヒフヘホマミムメモヤユヨラリルレロワン゛゜"
)

_HIRAGANA_FIRST, _HIRAGANA_LAST = 0x3041, 0x3096
_KANA_SHIFT = 0x60
_ITERATION_MARKS = {0x309D: "ヽ", 0x309E: "ヾ"}
_FULLWIDTH_ASCII_FIRST, _FULLWIDTH_ASCII_LAST = 0xFF01, 0xFF5E
_FULLWIDTH_ASCII_SHIFT = 0xFEE0
_IDEOGRAPHIC_SPACE = 0x3000

MARK_OPEN = "\x02"
MARK_CLOSE = "\x03"

# 畳み込みruleの版。**畳む範囲を変えたら必ず上げること**。索引(search_hits.body_norm)は
# 投入時の版で畳まれたまま残るので、上げないと新しいruleで畳んだqueryが古い索引を引き、
# 「その語だけ何も出ない」という形で静かに壊れる。起動時のmigrationがこの版の変化を見て
# 全行を畳み直す(実測: 55万行で約8秒)。
# 1 = 表記ゆれの畳み込みのみ / 2 = 索引から先頭の返信メンションを外す(blank_mention)。
FOLD_VERSION = 2

# 返信の宛先。TikTokは本文の先頭へ ``@表示名`` を置いて送る。全角の＠も同じ扱いにするのは、
# 畳む前の原文で切るため(畳んでから切ると、名前の照合相手である表示名も畳む必要が出る)。
MENTION_HEADS = ("@", "＠")

# 名前がここで終わったと見なせる文字。既知の表示名に当たらなかったときだけ使う。
_MENTION_BREAKS = (" ", "　", "\n", "\t")


def _fold_char(code: int) -> str:
    if _HIRAGANA_FIRST <= code <= _HIRAGANA_LAST:
        return chr(code + _KANA_SHIFT)
    if code in _ITERATION_MARKS:
        return _ITERATION_MARKS[code]
    if _HALFWIDTH_KANA_FIRST <= code < _HALFWIDTH_KANA_FIRST + len(_HALFWIDTH_KANA):
        return _HALFWIDTH_KANA[code - _HALFWIDTH_KANA_FIRST]
    if _FULLWIDTH_ASCII_FIRST <= code <= _FULLWIDTH_ASCII_LAST:
        code -= _FULLWIDTH_ASCII_SHIFT
    if code == _IDEOGRAPHIC_SPACE:
        return " "
    # ASCIIの大小のみ畳む。str.lower()はトルコ語のİのように1文字が2文字になる組があり、
    # 文字数を保つという前提が崩れる。
    if 0x41 <= code <= 0x5A:
        code += 0x20
    return chr(code)


def _build_table() -> dict:
    """写す文字だけのtranslation table。indexの作り直しは全行に掛かる(実測55万行)ので、
    1文字ずつ関数を呼ばずstr.translateへ渡す。"""
    codes = list(range(_HIRAGANA_FIRST, _HIRAGANA_LAST + 1))
    codes += list(_ITERATION_MARKS)
    codes += list(range(_HALFWIDTH_KANA_FIRST, _HALFWIDTH_KANA_FIRST + len(_HALFWIDTH_KANA)))
    codes += list(range(_FULLWIDTH_ASCII_FIRST, _FULLWIDTH_ASCII_LAST + 1))
    codes += [_IDEOGRAPHIC_SPACE] + list(range(0x41, 0x5B))
    return {code: _fold_char(code) for code in codes}


_TABLE = _build_table()


def fold(text: str) -> str:
    """照合用の形へ畳む。戻り値の文字数は入力と必ず同じ。"""
    return (text or "").translate(_TABLE)


class MentionNames:
    """先頭メンションの名前をどこで切るかを決めるための、既知の表示名。

    「最初の空白まで」では切れない。表示名そのものに空白を含むものがあり(``Alice Torres``、
    ``🐉　名　前　🐉``)、実測では先頭メンション7,497件のうち531件がこれに当たる。切り損ねると
    名前の後半(``Torres``)が索引へ残り、その語で引いたときに結局その人の返信が全部出る。

    そこで既知の表示名で最長一致を取る。当たらないのは我々が一度も観測していないuserへの
    返信で(実測422件)、そのときだけ空白で切る。
    """

    __slots__ = ("_names", "_max_len")

    def __init__(self, names: Iterable = ()) -> None:
        self._names = frozenset(name for name in names if name)
        self._max_len = max((len(name) for name in self._names), default=0)

    def __len__(self) -> int:
        return len(self._names)

    def match_length(self, text: str) -> int:
        """``text``の先頭に一致する最長の表示名の文字数。当たらなければ0。

        長い方から順に集合を引く。表示名の側を走査すると31万件を毎回舐めることになるが、
        こちらは名前の最大長ぶんの集合参照で済む。
        """
        for size in range(min(len(text), self._max_len), 0, -1):
            if text[:size] in self._names:
                return size
        return 0


def blank_mention(text: str, names: Optional[MentionNames] = None) -> str:
    """先頭の返信メンション(``@表示名``)を空白へ置き換える。文字数は変えない。

    消すのではなく空白で埋めるのは、畳み込みと同じ「文字数を保つ」前提を索引側でも
    崩さないため。
    """
    if not text or text[0] not in MENTION_HEADS:
        return text
    rest = text[1:]
    size = names.match_length(rest) if names is not None else 0
    if not size:
        stops = [pos for pos in (rest.find(brk) for brk in _MENTION_BREAKS) if pos >= 0]
        # 区切りが無い本文はメンションだけの発言(``@よい``)なので、全部が宛先である。
        size = min(stops) if stops else len(rest)
    return " " * (size + 1) + text[size + 1:]


def index_fold(text: str, names: Optional[MentionNames] = None) -> str:
    """索引(``search_hits.body_norm``)へ載せる形。宛先を外してから畳む。"""
    return fold(blank_mention(text, names))


def mark(body: str, terms: list, open_mark: str = MARK_OPEN,
         close_mark: str = MARK_CLOSE) -> str:
    """本文中の一致箇所を囲んで返す。囲むのは元の本文で、探すのは畳んだ形。

    FTS5の``highlight()``を使わないのは、FTSが索引しているのが畳んだ本文(body_norm)で、
    そのまま返すと画面に出る文字が「うざい」から「ウザイ」へ化けるため。ついでに、
    2文字以下のqueryが落ちるLIKE経路でも同じ強調が付く(FTS経路にしか無かった)。
    """
    if not body or not terms:
        return body
    folded = fold(body)
    spans = []
    for term in terms:
        needle = fold(term)
        if not needle:
            continue
        start = folded.find(needle)
        while start >= 0:
            spans.append((start, start + len(needle)))
            start = folded.find(needle, start + len(needle))
    if not spans:
        return body
    out = []
    cursor = 0
    for start, end in _merge(spans):
        out.append(body[cursor:start])
        out.append(open_mark)
        out.append(body[start:end])
        out.append(close_mark)
        cursor = end
    out.append(body[cursor:])
    return "".join(out)


def _merge(spans: list) -> list:
    """重なり合う一致範囲を畳む。語どうしが重なると囲みが入れ子になり、画面側の
    ``split(/[\\x02\\x03]/)``が強調の対応を取り違える。"""
    merged: list = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged
