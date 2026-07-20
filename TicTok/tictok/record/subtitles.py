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


def _clock(seconds: float, millis_sep: str) -> str:
    total_ms = int(round(max(0.0, seconds) * 1000))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    m = (total_s // 60) % 60
    h = total_s // 3600
    return f"{h:02d}:{m:02d}:{s:02d}{millis_sep}{ms:03d}"


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
