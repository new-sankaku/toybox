"""文字起こしの訂正を、生のsegmentへ**重ねる**ための純粋関数。

なぜ層にするか
==============

文字起こしは誤りを含む。直した結果を ``transcripts`` へ書き戻すと、その録画を再文字起こし
した瞬間に消える。かといって「直したら再文字起こし禁止」にもできない — modelを変えた・
時刻mapの版が上がった場合は、直しを捨てて取り直すのが正しいからである。

そこで ``transcripts`` は常に生のまま置き、訂正は ``transcript_corrections`` の行として
別に持ち、**読み出すときに重ねる**。再文字起こしは生の層を入れ替えるだけなので、訂正は
構造的に生き残る。捨てるかどうかは実行時に選ぶ(:func:`rematch`)。

同定はindexではなく (時刻, 原文)
================================

再文字起こしするとsegmentの数もindexも時刻も変わる。indexで指した訂正は次の実行で全滅し、
しかも**別の発話に乗る**(黙って起きる最悪の壊れ方)。そこで照合は
``|開始時刻の差| <= MATCH_TOLERANCE_SECONDS`` かつ **原文が完全一致** の組で行う。
どちらか一方では足りない: 時刻だけでは言い直し(「トイレ行きたい」が3回続く)で隣に乗り、
原文だけでは同じ相槌(「うん」)が録画中に何百回もある。

一致しなかった訂正は保留(orphan)にして人へ返す。近いものへ寄せにはいかない。

語枠(words)への反映
===================

焼き込み字幕・切り抜き字幕は ``segment["text"]`` ではなく ``words`` のtextを連結して作る
(:func:`tictok.record.subtitles.split_for_display`)。segmentのtextだけ直しても字幕には
出ないので、訂正は語の枠まで下ろす必要がある。

下ろし方は文字単位の差分で、**置換された連なりは、それが置き換えた元の連なりの時刻spanを
そのまま継ぐ**。文字数で按分して新しい時刻を作ることはしない — それは時刻の捏造で、
subtitlesが一貫して拒否している当のものである。語の連結が原文と一致しない
segment(実測3,306件中2件、U+FFFDで途切れたもの)は語を捨てる。割れないことは、割った振りを
するより害が小さい。
"""

import difflib
import logging

logger = logging.getLogger("tictok.corrections")

# 訂正を再文字起こし後のsegmentへ貼り直すときに許す開始時刻の差。VADの窓境界と
# 丸めで秒未満は普通に動くが、隣の発話まで届く長さにはしない。
MATCH_TOLERANCE_SECONDS = 2.0


def _word_spans(words: list) -> list:
    """語ごとの (開始文字位置, 終了文字位置)。連結順にそのまま並ぶ。"""
    spans, pos = [], 0
    for word in words:
        text = word.get("text") or ""
        spans.append((pos, pos + len(text)))
        pos += len(text)
    return spans


def _owner_of_char(spans: list, word_count: int) -> list:
    """原文の文字位置 -> その文字を持つ語のindex。末尾(=len(src))は最後の語に寄せる。"""
    total = spans[-1][1] if spans else 0
    owner = [word_count - 1] * (total + 1)
    for index, (start, end) in enumerate(spans):
        for position in range(start, end):
            owner[position] = index
    return owner


def remap_words(words: list, src: str, dst: str):
    """``words`` を訂正後のtextへ貼り直す。貼り直せなければ ``None``。

    変わらなかった語はそのまま、変わった語の連なりは1語へ畳んで**元のspanを継ぐ**。

    やり方は「文字位置の対応表」ではなく「**訂正文の全文字を語へ割り当てる**」。前者だと、
    語と語のちょうど境目に入った文字がどちらの語の受け持ちにもならず、黙って消える
    (実測: 1,069件の訂正のうち112件でこれが起きた)。割り当て方式なら訂正文の文字は必ず
    どこかの語に属するので、組み直した結果は定義上 ``dst`` と一致する。
    """
    if not words:
        return None
    joined = "".join(word.get("text") or "" for word in words)
    if joined != src:
        # 語の連結が原文と違う。ここで無理に当てると、訂正が別の語の時刻へ乗る。
        return None

    spans = _word_spans(words)
    owner = _owner_of_char(spans, len(words))
    opcodes = difflib.SequenceMatcher(None, src, dst, autojunk=False).get_opcodes()

    take = [0] * len(words)          # その語が受け持つ訂正文の文字数
    touched = [False] * len(words)   # 訂正が掛かった語
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            for offset in range(i2 - i1):
                take[owner[i1 + offset]] += 1
        elif tag == "delete":
            for position in range(i1, i2):
                touched[owner[position]] = True
        elif tag == "insert":
            # 幅を持たないので、挿入位置の文字を持つ語(末尾なら最後の語)へ寄せる。
            take[owner[i1]] += j2 - j1
            touched[owner[i1]] = True
        else:
            for position in range(i1, i2):
                touched[owner[position]] = True
            take[owner[i1]] += j2 - j1

    bounds = [0]
    for count in take:
        bounds.append(bounds[-1] + count)
    if bounds[-1] != len(dst):
        return None

    out, index = [], 0
    while index < len(words):
        if not touched[index]:
            if dst[bounds[index]:bounds[index + 1]] != (words[index].get("text") or ""):
                # 触れていない語の受け持ちが元のtextと違う = 割り当てが壊れている。
                return None
            out.append(dict(words[index]))
            index += 1
            continue
        run_end = index
        while run_end < len(words) and touched[run_end]:
            run_end += 1
        text = dst[bounds[index]:bounds[run_end]]
        if text:
            out.append({"start": words[index]["start"],
                        "end": words[run_end - 1]["end"],
                        "text": text})
        index = run_end

    if "".join(word["text"] for word in out) != dst:
        return None
    return out


def _match_index(segments: list, start: float, src: str, taken: set):
    """(時刻±許容, 原文一致) で当たるsegmentのindex。無ければ ``None``。

    複数当たったら時刻が最も近いものを採る。既に他の訂正が使ったsegmentは避ける
    (同じ発話の言い直しへ同じ訂正が二重に乗るのを防ぐ)。
    """
    best, best_gap = None, None
    for index, seg in enumerate(segments):
        if index in taken or seg.get("text") != src:
            continue
        gap = abs(float(seg.get("start") or 0.0) - float(start))
        if gap > MATCH_TOLERANCE_SECONDS:
            continue
        if best_gap is None or gap < best_gap:
            best, best_gap = index, gap
    return best


def apply_to_segments(segments: list, corrections: list) -> dict:
    """訂正を重ねた ``segments`` を作る。生の ``segments`` は変更しない。

    戻り値は ``{"segments", "applied", "orphans", "words_dropped"}``。
    ``orphans`` は当たらなかった訂正の行そのもの — 呼び出し側が「再適用できなかった」と
    名乗れるように、件数ではなく中身を返す。
    """
    out = [dict(seg) for seg in segments or []]
    taken: set = set()
    applied, orphans, words_dropped = 0, [], 0

    for correction in sorted(corrections or [], key=lambda c: float(c["start"])):
        index = _match_index(out, float(correction["start"]), correction["src"], taken)
        if index is None:
            orphans.append(correction)
            continue
        taken.add(index)
        seg = out[index]
        seg["text"] = correction["dst"]
        seg["corrected"] = True
        words = seg.get("words")
        if words:
            remapped = remap_words(words, correction["src"], correction["dst"])
            if remapped is None:
                seg.pop("words", None)
                words_dropped += 1
            else:
                seg["words"] = remapped
        applied += 1

    return {"segments": out, "applied": applied, "orphans": orphans,
            "words_dropped": words_dropped}


def rematch(segments: list, corrections: list) -> dict:
    """再文字起こし後のsegmentへ訂正を貼り直す。

    戻り値は ``{"matched": [(id, 新しいstart), ...], "orphaned": [id, ...]}``。
    ここでは判定だけを行い、DBの書き換えは呼び出し側が行う。
    """
    taken: set = set()
    matched, orphaned = [], []
    for correction in sorted(corrections or [], key=lambda c: float(c["start"])):
        index = _match_index(segments or [], float(correction["start"]),
                             correction["src"], taken)
        if index is None:
            orphaned.append(correction["id"])
            continue
        taken.add(index)
        matched.append((correction["id"], float(segments[index]["start"])))
    return {"matched": matched, "orphaned": orphaned}
