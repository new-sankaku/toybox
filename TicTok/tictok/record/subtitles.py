"""文字起こしsegmentを字幕fileへ書き出す(sidecar)。

segments_jsonのstart/endは文字起こし時にmedia軸(元録画mp4のPTS秒)へ再map済みなので、そのまま
字幕のtimecodeへ落とせる。焼き込み出力・Up出力は再encodeで尺が変わり得るため、ここが出す
timecodeが合うのは**元録画mp4**に対してだけである(UI文言にもその旨を出す)。

start/endが欠けたsegmentやtextが空のsegmentは捨てる。時刻を推測して埋めると、外部NLEで
「それらしいが合っていない字幕」になり、誤りを検出する手段が無くなるため。

**segmentの端をそのままcueにしない。** whisperは30秒窓を隙間なく分割する形で時刻を吐くので、
segmentの終端は次のsegmentの開始まで伸び、その間の無音までcueに入る。字幕fileを出す経路は
すべて :func:`split_for_display` を通す(詳細は doc/STT_SUBTITLE_TIMING.md)。
"""

import hashlib
import json
import logging
from typing import Optional

from tictok.record import jp_wrap
from tictok.record.transcription import TIMEMAP_VERSION

logger = logging.getLogger("tictok.subtitles")

# 書き出せる形式: format -> (拡張子, media type, 文字encode)。txtはtimecodeを持たない
# 素のtextで、字幕ではなく原稿として使う用途。
EXPORT_FORMATS = {
    "srt": (".srt", "application/x-subrip; charset=utf-8", "utf-8"),
    "vtt": (".vtt", "text/vtt; charset=utf-8", "utf-8"),
    "txt": (".txt", "text/plain; charset=utf-8", "utf-8"),
}


def timemap_current(timemap_version) -> bool:
    """このtranscriptの時刻が現行のmedia軸mapで作られたか。

    Falseなら字幕のtimecodeが動画とズレている可能性がある(mapが無かった頃のtranscriptは
    尺が伸びるほど後ろへズレる)。呼び出し側は警告するか、焼き込みのように取り返しがつかない
    用途では拒否する。"""
    return timemap_version == TIMEMAP_VERSION


# 文字起こしの尺と素材の実尺の差がこれを超えたら、別の軸で作られたと判断する。同じ素材から
# 作られていれば両者は秒未満で一致する(実測: やり直した62件が0.15秒以内)。VADの丸めと最終
# segmentの端数を吸収するぶんだけ余裕を持たせる。
AXIS_TOLERANCE_SECONDS = 2.0


def axis_matches_media(transcript, media_duration) -> bool:
    """このtranscriptの時刻が、いま焼き込む素材と同じ時間軸に載っているか。

    ``timemap_current`` は「どの版のmapで作られたか」しか見ない。版が同じでも、作られた
    ときの入力が別物なら時刻は尺に比例してずれる。実測でいずれも版1のまま:

      * 幻の音声穴で伸びた旧mp4から作った文字起こし … 実尺+191秒
      * 源のtimestampが壊れたsegmentのjumpを含むもの … 実尺+28287秒

    こうなると字幕は録画の外側を指す。焼き込みは元に戻せないので、尺が合わないものは
    焼かずに拒否する。

    実尺が測れないときはTrueを返す。根拠が無いまま拒否すると、正しい文字起こしまで焼けなく
    なる — 拒否するのは「ズレている証拠がある」ときだけにする。"""
    if media_duration is None or media_duration <= 0:
        return True
    duration = (transcript or {}).get("duration")
    if not duration:
        return True
    return abs(float(duration) - float(media_duration)) <= AXIS_TOLERANCE_SECONDS


def usable_segments(segments, media_duration=None) -> list:
    """字幕として出せるsegmentだけを時刻順で返す。

    start/endがNULL、end<=start、textが空のものは落とす(捏造して埋めない)。

    負の時刻は0へ寄せてからend<=startを判定する。segments_jsonの時刻はmedia軸へ再map済み
    なので負値が来ること自体が異常で、全区間が負のsegmentは実在しない区間を指す。0へ寄せた
    結果0-->0になるものを残すと、playerに長さ0のcueが出るだけで内容は救えない。

    ``media_duration`` を渡すと、cueの終端を実尺で打ち切る。whisperのsegment終端は
    VADの窓境界なので実尺をわずかに超えることがあり(実測1.77秒)、そのまま出すとplayerが
    存在しない位置のcueを持つ。実尺が測れない場合はNoneを渡す(推測して詰めない)。"""
    items = []
    for seg in segments or []:
        start = seg.get("start")
        end = seg.get("end")
        text = (seg.get("text") or "").strip()
        if start is None or end is None or not text:
            continue
        start = max(0.0, float(start))
        end = max(0.0, float(end))
        if end <= start:
            continue
        if media_duration is not None:
            if start >= media_duration:
                continue
            end = min(end, float(media_duration))
            if end <= start:
                continue
        row = {"start": start, "end": end, "text": text}
        words = seg.get("words")
        if words:
            row["words"] = words
        items.append(row)
    items.sort(key=lambda s: s["start"])
    dropped = len(segments or []) - len(items)
    if dropped:
        logger.info(
            "字幕の書き出しで使えないsegment %d 件を除外しました（全 %d 件）",
            dropped, len(segments or []),
            extra={"event": "subtitle.segments_dropped",
                   "ctx": {"dropped": dropped, "total": len(segments or [])}},
        )
    return items


def slice_segments(segments, origin: float, duration=None) -> list:
    """``[origin, origin+duration)`` に掛かるsegmentを、origin を 0 とした軸へ移して返す。

    切り抜きは元録画の一部なので、文字起こしの時刻(media軸)をそのまま添えると開始位置ぶん丸ごと
    ずれる。引くのは**成果物の先頭が指す元録画の時刻**であって、要求した開始位置ではない
    — stream copyの切り出しは要求より手前のkeyframeから始まるので、両者は数秒違う
    (``make_clip`` の ``actual_start_seconds``)。ここへ要求値を渡すと、その差がそのまま
    全cueのズレになる。

    窓の端に掛かるsegmentは落とさず、時刻だけを窓の内側へ詰める。切り抜きの中で確かに
    聞こえる発話なので、落とすと聞こえている言葉が字幕から消える。textは切らない — どこで
    切れたかは語の時刻を持たない文字起こしでは分からず、文字数で按分すれば時刻の捏造になる。

    ``duration`` を渡すと終端をそこで打ち切る(渡さなければ打ち切らない)。語の時刻を持つ
    segmentは語も同じだけずらし、窓の外の語は落とす — 鳴っていない語まで表示単位へ割る
    (:func:`split_for_display`)と、切り抜きに無い言葉がテロップになる。
    """
    origin = float(origin)
    upper = None if duration is None else max(0.0, float(duration))
    out: list = []
    for seg in usable_segments(segments):
        start = float(seg["start"]) - origin
        end = float(seg["end"]) - origin
        if end <= 0 or (upper is not None and start >= upper):
            continue
        row = {"start": max(0.0, start),
               "end": end if upper is None else min(end, upper),
               "text": seg["text"]}
        if row["end"] <= row["start"]:
            continue
        words = []
        for word in seg.get("words") or []:
            if word.get("start") is None or word.get("end") is None:
                continue
            w_start = float(word["start"]) - origin
            w_end = float(word["end"]) - origin
            if w_end <= 0 or (upper is not None and w_start >= upper):
                continue
            words.append({**word, "start": max(0.0, w_start),
                          "end": w_end if upper is None else min(w_end, upper)})
        if words:
            row["words"] = words
        out.append(row)
    return out


# 1枚のテロップを出しておく上限。これを超える表示は、画面の文と喋っている言葉が食い違う
# 時間がそのまま伸びるという意味になる。
DISPLAY_MAX_SECONDS = 3.0
# 1行に載せる全角換算の文字数と、1枚を折り返す行数。掛けたものが1枚の文字予算になる。
# 縦画面(1080x1920)で幅の9割を使うと、読める大きさのテロップは1行あたり全角15〜16字。
DISPLAY_CHARS_PER_LINE = 16
DISPLAY_WRAP_LINES = 2
# 行の端に空けておく余白の割合。上限ちょうどまで詰めた行は、読み手の書体・字間・player側の
# 内側余白が想定と少し違うだけで端が切れる。SRT/VTTは**読み手が何で描くか分からない**書式
# なので、上限そのものを守っても収まる保証が無い。焼き込みも同じ割合を実測幅から引く。
DISPLAY_SAFE_MARGIN = 0.06
# 1枚に載せる文字数の上限。行×1行あたりの字数で決まる。
DISPLAY_MAX_CHARS = DISPLAY_CHARS_PER_LINE * DISPLAY_WRAP_LINES
# 語と語の間がこれ以上空いたら、そこで切る。**話の切れ目そのもの**なので、尺や文字数より
# 先に見る。これが無いと、間の空いた2語が1枚に入って上限に触れ、語の途中で切れる
# (実測: 「かわ」と3.4秒空いた「いい」が同じ枚に入り、尺の上限で機械的に割れた)。
DISPLAY_GAP_SECONDS = 0.6


def layout_from_settings(settings) -> dict:
    """設定値から表示単位の寸法を引く。設定を持たない呼び出し元は既定値のまま使う。

    ``per_line`` / ``max_chars`` は**余白を引いた後**の値である。引く前の値を使う経路が
    1つでもあると、その経路だけ端まで詰まった行が出る。
    """
    def _num(key, default, cast, lowest=1):
        value = (settings or {}).get(key)
        return default if value in (None, "") else max(cast(lowest), cast(value))
    chars = _num("subtitle_chars_per_line", DISPLAY_CHARS_PER_LINE, int)
    lines = _num("subtitle_wrap_lines", DISPLAY_WRAP_LINES, int)
    percent = _num("subtitle_safe_margin_percent", DISPLAY_SAFE_MARGIN * 100, float, 0)
    margin = min(0.5, max(0.0, percent / 100.0))
    per_line = chars * (1.0 - margin)
    return {
        "chars_per_line": chars,
        "wrap_lines": lines,
        "max_seconds": _num("subtitle_max_seconds", DISPLAY_MAX_SECONDS, float),
        "margin": margin,
        "per_line": per_line,
        "max_chars": per_line * lines,
    }


def has_word_times(segments) -> bool:
    """語ごとの時刻を持つ文字起こしか。持たない文字起こしは分割できない(古い文字起こしは全部これ)。"""
    return any(seg.get("words") for seg in segments or [])


def coarse_ratio(segments, limit: float = DISPLAY_MAX_SECONDS) -> float:
    """``limit`` より長いsegmentの割合。テロップとして使えるかの判定に使う。"""
    rows = [s for s in segments or []
            if s.get("start") is not None and s.get("end") is not None]
    if not rows:
        return 0.0
    long = sum(1 for s in rows if float(s["end"]) - float(s["start"]) > limit)
    return long / len(rows)


def _cue(words: list) -> dict:
    return {"start": float(words[0]["start"]), "end": float(words[-1]["end"]),
            "text": "".join(w["text"] for w in words).strip()}


def _plan_segment(words: list, max_seconds: float, max_chars: float,
                  per_line: float, wrap_lines: int) -> list:
    """1つのsegmentの語列を、枚(cue)の並びへ割る。

    **枚の境と行の折りを同時に決める。** 左から順に「上限に達したら切る」と、切る時点では
    後ろに何が来るか分からず、出来た枚が良い位置で折れるかも分からない。実測では、枚が予算
    いっぱいになると1行目の許容幅が数文字まで狭まり、そこに形態素境界が1つしか無ければ、
    それが文節を割る位置でも選ぶしかなくなる。

    そこでsegment全体を見渡し、次の合計を最小にする割り方をDPで選ぶ:

      * 枚の境の悪さ × WEIGHT — 境が文の切れ目に落ちているか
      * その枚を折るときの切れ目の悪さ × WEIGHT — **折れない枚を作らない**
      * 予算の余り — 枚を無駄に短くしない(これが無いと細切れが最良になる)

    候補になる境は**語の時刻がある位置だけ**である。文字数で按分すれば時刻の捏造になる。

    語と語の間(``DISPLAY_GAP_SECONDS``)を跨ぐ枚は作らない。**間そのものが話の切れ目**で、
    文字の並びより強い根拠である。
    """
    text = "".join(w["text"] for w in words)
    costs = jp_wrap.break_costs(text)
    offset = [0]
    for word in words:
        offset.append(offset[-1] + len(word["text"]))
    count = len(words)
    weight = jp_wrap.WEIGHT

    infinity = float("inf")
    best = [infinity] * (count + 1)
    back = [-1] * (count + 1)
    best[0] = 0.0
    for start in range(count):
        if best[start] == infinity:
            continue
        for end in range(start + 1, count + 1):
            piece = text[offset[start]:offset[end]]
            body = piece.strip()
            # 語が1つだけの枚は、上限を超えていても作る。語の内側には時刻が無いので割れず、
            # ここで諦めるとsegment全体が1枚に潰れる(実測: 幅62.5の枚が86件出た)。
            single = end == start + 1
            if not single:
                if jp_wrap.width(body) > max_chars:
                    break
                if float(words[end - 1]["end"]) - float(words[start]["start"]) > max_seconds:
                    break
                if (float(words[end - 1]["start"])
                        - float(words[end - 2]["end"]) > DISPLAY_GAP_SECONDS):
                    break
            if not body:
                continue
            # 折りやすさは**枚として出る文**(前後を落とした形)で測る。piece のまま測ると、
            # 語に前後の空白が付く文字起こしで位置が1つずれ、実際に折る文と別の文を採点する。
            head_at = offset[start] + len(piece) - len(piece.lstrip())
            tail_at = offset[end] - (len(piece) - len(piece.rstrip()))
            # 予算を超えるのは語1つの枚だけで、それは他に選びようが無い。負の余りにして
            # 「大きいほど得」にしない。
            score = (weight * jp_wrap.layout_badness(
                         body, costs[head_at:tail_at + 1], per_line, wrap_lines)
                     + max(0.0, max_chars - jp_wrap.width(body)))
            if end < count:
                score += weight * jp_wrap.split_cost(costs, offset[end])
            if best[start] + score < best[end]:
                best[end] = best[start] + score
                back[end] = start
    if best[count] == infinity:
        # 1語が単独で上限を超える等、どう割っても成り立たない。語順のまま素直に詰める。
        return [_cue(words)]
    bounds, end = [], count
    while end > 0:
        bounds.append((back[end], end))
        end = back[end]
    bounds.reverse()
    return [_cue(words[start:end]) for start, end in bounds]


def split_for_display(segments, max_seconds: float = DISPLAY_MAX_SECONDS,
                      max_chars: float = DISPLAY_MAX_CHARS,
                      per_line: float = DISPLAY_CHARS_PER_LINE,
                      wrap_lines: int = DISPLAY_WRAP_LINES) -> list:
    """segmentを、テロップとして出せる長さの表示単位へ割る。

    **語の時刻でしか割らない。** 文字数で按分して割る形は時刻の捏造で、「それらしいが合って
    いない字幕」を作る(module docstringの方針そのもの)。語の時刻を持たないsegmentはそのまま
    返す — 割れないことは、割った振りをするより害が小さい。

    なぜ要るか: whisperのsegmentは1件が数十秒になる。実測(全297文字起こし・459,738件)で5秒超が
    16.5%、20秒超が1.0%、最大5,354秒。40秒のsegmentを1枚のテロップとして出すと、画面には
    40秒ぶんの文が居座り、その間ずっと別の言葉が喋られる。時刻軸をどう直しても解けない。

    どこで割るかは :func:`_plan_segment` が、枚の境と行の折りを同時に見て決める。
    """
    out: list = []
    if segments:
        # 割る必要が出た枚だけ解析器へ行く形にすると、素材によって落ちたり落ちなかったりする。
        jp_wrap.tagger()
    for seg in segments or []:
        words = [w for w in (seg.get("words") or [])
                 if w.get("start") is not None and w.get("end") is not None
                 and (w.get("text") or "").strip()]
        if not words:
            out.append({k: v for k, v in seg.items() if k != "words"})
            continue
        out.extend(_plan_segment(words, max_seconds, max_chars, per_line, wrap_lines))
    return [row for row in out if row.get("text") and row["end"] > row["start"]]


def _clock(seconds: float, millis_sep: str) -> str:
    total_ms = int(round(max(0.0, seconds) * 1000))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    m = (total_s // 60) % 60
    h = total_s // 3600
    return f"{h:02d}:{m:02d}:{s:02d}{millis_sep}{ms:03d}"


def cue_body(text: str, chars_per_line: float = DISPLAY_CHARS_PER_LINE * (1 - DISPLAY_SAFE_MARGIN),
             wrap_lines: int = DISPLAY_WRAP_LINES) -> str:
    """cueの中身を、意味の切れ目で折り返した複数行にする。

    SRT/VTTはcueに複数行を書ける書式だが、**1行のまま渡すと読み手は折り返さない。** 縦画面へ
    載せると横へはみ出して端が切れる。書体を持たない書式なので、幅は全角換算の文字数で
    数えるしかない(:func:`tictok.record.jp_wrap.width`)。

    折る位置は形態素解析で決める。文字数だけで折ると、実データで**49.7%が語の内側**へ落ちた
    (詳細は :mod:`tictok.record.jp_wrap`)。
    """
    return "\n".join(jp_wrap.wrap(text, chars_per_line, wrap_lines))


# 0秒に置く錨のcue。中身は半角空白1つで、どの読み手でも字は出ない。
ANCHOR_TEXT = " "
# 錨を出す下限。これ未満のズレは錨を置く価値が無く、丸めて長さ0のcueになる方が害が大きい。
ANCHOR_MIN_SECONDS = 0.001
# 錨の長さの上限。頭の無音が長い切り抜きでも、空のcueが何秒も居座らないようにする。
ANCHOR_MAX_SECONDS = 0.5


def anchor_cue(items) -> Optional[dict]:
    """先頭cueが0秒から始まらないとき、0秒に置く空のcueを返す(要らなければNone)。

    なぜ要るか: 字幕fileをNLEのtimelineへ**dragで置くと、先頭cueが落とした位置へ吸着する**
    実装がある。DaVinci Resolveがそれで、manualにも "with its timing offset relative to the
    position of the first frame of the first subtitle in that file" と書かれている。頭が無音の
    切り抜きでは、その無音ぶん(実測2.584秒)だけ全cueが早くなる。

    0秒に錨を置けば先頭cueの位置が成果物の先頭と一致するので、dragで置いても時刻で差し込んでも
    同じ結果になる。中身は半角空白なので、**発話を捏造しない** — 鳴っていない区間に出るのは
    「字の無いcue」であって、言葉ではない。
    """
    if not items:
        return None
    first = float(items[0]["start"])
    if first < ANCHOR_MIN_SECONDS:
        return None
    return {"start": 0.0, "end": min(first, ANCHOR_MAX_SECONDS),
            "text": ANCHOR_TEXT, "anchor": True}


def _cues(segments, media_duration, anchor: bool) -> list:
    items = usable_segments(segments, media_duration)
    head = anchor_cue(items) if anchor else None
    return [head, *items] if head else items


def _cue_text(seg, chars_per_line: float, wrap_lines: int) -> str:
    """錨のcueは折り返しに掛けない(空白は語ではないので、解析器に渡すと消える)。"""
    if seg.get("anchor"):
        return seg["text"]
    return cue_body(seg["text"], chars_per_line, wrap_lines)


def to_srt(segments, media_duration=None,
           chars_per_line: float = DISPLAY_CHARS_PER_LINE * (1 - DISPLAY_SAFE_MARGIN),
           wrap_lines: int = DISPLAY_WRAP_LINES, *, anchor: bool = False) -> str:
    lines = []
    for index, seg in enumerate(_cues(segments, media_duration, anchor), start=1):
        lines.append(str(index))
        lines.append(f"{_clock(seg['start'], ',')} --> {_clock(seg['end'], ',')}")
        lines.append(_cue_text(seg, chars_per_line, wrap_lines))
        lines.append("")
    return "\n".join(lines)


def to_vtt(segments, media_duration=None,
           chars_per_line: float = DISPLAY_CHARS_PER_LINE * (1 - DISPLAY_SAFE_MARGIN),
           wrap_lines: int = DISPLAY_WRAP_LINES, *, anchor: bool = False) -> str:
    lines = ["WEBVTT", ""]
    for seg in _cues(segments, media_duration, anchor):
        lines.append(f"{_clock(seg['start'], '.')} --> {_clock(seg['end'], '.')}")
        lines.append(_cue_text(seg, chars_per_line, wrap_lines))
        lines.append("")
    return "\n".join(lines)


def to_text(segments, text: str = "") -> str:
    """timecode無しの素のtext。segmentが1件も出せない場合のみ、文字起こし全文をそのまま返す。"""
    items = usable_segments(segments)
    if not items:
        return text or ""
    return "\n".join(seg["text"] for seg in items) + "\n"


def render(fmt: str, transcript: dict, media_duration=None, settings=None) -> str:
    """録画丸ごとの書き出し。字幕書式(srt/vtt)は表示単位へ割り、txtは割らない。

    whisperのsegmentは30秒窓を**隙間なく分割する形**で時刻を吐くため、segmentの終端が次の
    segmentの開始まで伸び、間の無音までcueに入る。実測(版2の文字起こし331件)でSRTがtimelineを覆う
    割合は中央値97.7%——実際の発話は約30%(録画926でVAD実測 91.9s/306s)なので、無音の上に
    関係のないcueが出続ける。語の時刻で割ると被覆は48.4%まで落ち、cueの長さもp99が12.04秒
    →3.90秒、最大2100秒→29秒になる。

    txtは字幕ではなく原稿として使う書式なので割らない(割ると行が細切れになる)。

    語の時刻を持たない文字起こしは :func:`split_for_display` がそのまま返す。割れないことは、
    割った振りをするより害が小さい——救うには再文字起こししかない。"""
    if fmt in ("srt", "vtt"):
        box = layout_from_settings(settings)
        display = split_for_display(
            usable_segments(transcript.get("segments"), media_duration),
            max_seconds=box["max_seconds"], max_chars=box["max_chars"],
            per_line=box["per_line"], wrap_lines=box["wrap_lines"])
        render_cues = to_srt if fmt == "srt" else to_vtt
        return render_cues(display, media_duration, box["per_line"], box["wrap_lines"])
    if fmt == "txt":
        return to_text(transcript.get("segments"), transcript.get("text") or "")
    raise ValueError(f"unknown subtitle format: {fmt}")


# 章立ての書き出し形式: format -> (拡張子, media type, 文字encode)。vttはplayerのchapter
# markerとして読ませるWebVTT、txtは投稿説明欄へ貼るtimecode付きの素のtext。
CHAPTER_FORMATS = {
    "vtt": (".chapters.vtt", "text/vtt; charset=utf-8", "utf-8"),
    "txt": (".chapters.txt", "text/plain; charset=utf-8", "utf-8"),
}


def usable_chapters(chapters, media_duration=None) -> list:
    """書き出せる章だけを時刻順で返す。

    start/endが欠ける・end<=start・表題が空のものは落とす(字幕segmentと同じ扱いで、
    推測して埋めない)。``media_duration`` を渡すと終端を実尺で打ち切る。"""
    items = []
    for chapter in chapters or []:
        start = chapter.get("start")
        end = chapter.get("end")
        title = (chapter.get("title") or "").strip()
        if start is None or end is None or not title:
            continue
        start = max(0.0, float(start))
        end = max(0.0, float(end))
        if media_duration is not None:
            if start >= float(media_duration):
                continue
            end = min(end, float(media_duration))
        if end <= start:
            continue
        items.append({"start": start, "end": end, "title": title})
    items.sort(key=lambda c: c["start"])
    return items


def to_vtt_chapters(chapters, media_duration=None) -> str:
    """WebVTTのchapter track。cueのidに通し番号を振るのは、chapter trackを読むplayerが
    章の識別子として使うため(字幕trackのcueはidを持たないので to_vtt とは形が違う)。"""
    lines = ["WEBVTT", ""]
    for index, chapter in enumerate(usable_chapters(chapters, media_duration), start=1):
        lines.append(str(index))
        lines.append(f"{_clock(chapter['start'], '.')} --> {_clock(chapter['end'], '.')}")
        lines.append(chapter["title"])
        lines.append("")
    return "\n".join(lines)


def _timecode(seconds: float) -> str:
    """投稿説明欄へ貼るtimecode。1時間未満は m:ss、以上は h:mm:ss。動画sitesのchapterは
    どちらの表記も受けるが、桁を無駄に増やすと目次として読みにくい。"""
    total = int(max(0.0, seconds))
    h, m, s = total // 3600, (total // 60) % 60, total % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def to_chapter_text(chapters, media_duration=None) -> str:
    """投稿説明欄へ貼るtimecode付きtext。先頭が0:00でない場合も時刻をずらして揃えたりは
    しない(0:00から始まる章listにするのは章を確定させる側の責任で、ここで書き換えると
    生成物と書き出しで時刻が食い違う)。"""
    items = usable_chapters(chapters, media_duration)
    if not items:
        return ""
    return "\n".join(f"{_timecode(c['start'])} {c['title']}" for c in items) + "\n"


def render_chapters(fmt: str, chapters, media_duration=None) -> str:
    if fmt == "vtt":
        return to_vtt_chapters(chapters, media_duration)
    if fmt == "txt":
        return to_chapter_text(chapters, media_duration)
    raise ValueError(f"unknown chapter format: {fmt}")


def fingerprint(transcript) -> str:
    """焼き込みcacheのsignatureへ混ぜるtranscript指紋。

    文字起こしのやり直しでsegmentが変われば字幕も変わるが、元mp4のsize/mtimeも設定値も変わらない
    ため、これを混ぜないと『文字起こし後に焼き直しても古い字幕なしmp4がcache hitで返る』という
    v23のper-recording窓と同型の踏み抜きになる。"""
    if not transcript:
        return ""
    h = hashlib.sha256()
    h.update(json.dumps(
        {"timemap_version": transcript.get("timemap_version"),
         "segments": usable_segments(transcript.get("segments"))},
        sort_keys=True, ensure_ascii=False, default=str,
    ).encode("utf-8"))
    return h.hexdigest()
