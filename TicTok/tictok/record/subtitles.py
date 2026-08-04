"""転写segmentを字幕fileへ書き出す(sidecar)。

segments_jsonのstart/endは転写時にmedia軸(元録画mp4のPTS秒)へ再map済みなので、そのまま
字幕のtimecodeへ落とせる。焼き込み出力・Up出力は再encodeで尺が変わり得るため、ここが出す
timecodeが合うのは**元録画mp4**に対してだけである(UI文言にもその旨を出す)。

start/endが欠けたsegmentやtextが空のsegmentは捨てる。時刻を推測して埋めると、外部NLEで
「それらしいが合っていない字幕」になり、誤りを検出する手段が無くなるため。
"""

import hashlib
import json
import logging

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
        items.append({"start": start, "end": end, "text": text})
    items.sort(key=lambda s: s["start"])
    dropped = len(segments or []) - len(items)
    if dropped:
        logger.info(
            "subtitle export dropped %d unusable segment(s) of %d",
            dropped, len(segments or []),
            extra={"event": "subtitle.segments_dropped",
                   "ctx": {"dropped": dropped, "total": len(segments or [])}},
        )
    return items


def window_segments(segments, start: float, end: float, origin=None) -> list:
    """[start, end]に掛かるsegmentだけを、originを0とする相対時刻へ写す。

    切り抜きmp4のsidecarを作るための窓取りで、originには切り抜きの**実際の内容開始**
    (clipper.make_clipのactual_start_seconds)を渡す。stream copyは要求位置ではなく直前の
    keyframeから始まるため、要求のstartを0点にすると字幕がlead秒ぶん後ろへずれる。

    窓の端に掛かるsegmentは落とさず端で打ち切る。落とすと切り抜きの冒頭・末尾の発話が
    まるごと字幕から消え、「その区間は無言だった」と読めてしまう。"""
    start = float(start)
    end = float(end)
    origin = start if origin is None else float(origin)
    items = []
    for seg in usable_segments(segments):
        if seg["end"] <= start or seg["start"] >= end:
            continue
        lo = max(seg["start"], start) - origin
        hi = min(seg["end"], end) - origin
        if hi <= lo:
            continue
        items.append({"start": max(0.0, lo), "end": max(0.0, hi), "text": seg["text"]})
    return items


def _clock(seconds: float, millis_sep: str) -> str:
    total_ms = int(round(max(0.0, seconds) * 1000))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    m = (total_s // 60) % 60
    h = total_s // 3600
    return f"{h:02d}:{m:02d}:{s:02d}{millis_sep}{ms:03d}"


def clock(seconds: float, millis_sep: str = ",") -> str:
    """字幕timecode(HH:MM:SS<sep>mmm)。CSVなど字幕以外の書き出しからも使う。"""
    return _clock(seconds, millis_sep)


def to_srt(segments, media_duration=None) -> str:
    lines = []
    for index, seg in enumerate(usable_segments(segments, media_duration), start=1):
        lines.append(str(index))
        lines.append(f"{_clock(seg['start'], ',')} --> {_clock(seg['end'], ',')}")
        lines.append(seg["text"])
        lines.append("")
    return "\n".join(lines)


def to_vtt(segments, media_duration=None) -> str:
    lines = ["WEBVTT", ""]
    for seg in usable_segments(segments, media_duration):
        lines.append(f"{_clock(seg['start'], '.')} --> {_clock(seg['end'], '.')}")
        lines.append(seg["text"])
        lines.append("")
    return "\n".join(lines)


def to_text(segments, text: str = "") -> str:
    """timecode無しの素のtext。segmentが1件も出せない場合のみ、転写全文をそのまま返す。"""
    items = usable_segments(segments)
    if not items:
        return text or ""
    return "\n".join(seg["text"] for seg in items) + "\n"


def render(fmt: str, transcript: dict, media_duration=None) -> str:
    if fmt == "srt":
        return to_srt(transcript.get("segments"), media_duration)
    if fmt == "vtt":
        return to_vtt(transcript.get("segments"), media_duration)
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

    転写のやり直しでsegmentが変われば字幕も変わるが、元mp4のsize/mtimeも設定値も変わらない
    ため、これを混ぜないと『転写後に焼き直しても古い字幕なしmp4がcache hitで返る』という
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
