"""cut listをNLEへ渡す形式へ書き出す。

mp4を書き出さずに範囲情報だけを渡せば、再encodeもdisk消費もなくNLE上で原本を参照した
まま微調整できる。切り出しmp4は素材を単体で扱いたいとき用で、編集へ渡す本線はこちら。

EDLのtimecodeは固定fpsを前提とする形式で、録画はHLS stream-copy由来のVFR(公称fpsと
実測が一致しない)。よってEDLの位置は概位置であり、frame単位の正確さは保証しない。
秒をそのまま持てるCSVの方が誤差が無いので、用途に応じて選べるよう両方を出す。
"""

import csv
import io

EDL_DEFAULT_FPS = 30.0


def _timecode(seconds: float, fps: float) -> str:
    seconds = max(0.0, float(seconds))
    frames_total = int(round(seconds * fps))
    frames = frames_total % int(round(fps))
    total_seconds = frames_total // int(round(fps))
    s = total_seconds % 60
    m = (total_seconds // 60) % 60
    h = total_seconds // 3600
    return f"{h:02d}:{m:02d}:{s:02d}:{frames:02d}"


def to_csv(cuts: list) -> str:
    """秒をそのまま持つ一覧。誤差が無く、表計算でもscriptでも扱える。"""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["unique_id", "filename", "path", "start_seconds", "end_seconds",
                     "duration_seconds", "start_timecode", "end_timecode", "label"])
    for cut in cuts:
        duration = cut["end"] - cut["start"]
        writer.writerow([
            cut["unique_id"],
            cut.get("filename") or "",
            cut.get("path") or "",
            f"{cut['start']:.3f}",
            f"{cut['end']:.3f}",
            f"{duration:.3f}",
            _timecode(cut["start"], EDL_DEFAULT_FPS),
            _timecode(cut["end"], EDL_DEFAULT_FPS),
            cut.get("label") or "",
        ])
    return buffer.getvalue()


def to_edl(cuts: list, title: str = "tictok_cutlist", fps: float = EDL_DEFAULT_FPS) -> str:
    """CMX3600 EDL。record側は各clipを順に並べた連番timelineとして書く。"""
    lines = [f"TITLE: {title}", "FCM: NON-DROP FRAME", ""]
    record_position = 0.0
    for index, cut in enumerate(cuts, start=1):
        duration = max(0.0, cut["end"] - cut["start"])
        source_in = _timecode(cut["start"], fps)
        source_out = _timecode(cut["end"], fps)
        record_in = _timecode(record_position, fps)
        record_out = _timecode(record_position + duration, fps)
        record_position += duration
        lines.append(
            f"{index:03d}  AX       AA/V  C        "
            f"{source_in} {source_out} {record_in} {record_out}"
        )
        lines.append(f"* FROM CLIP NAME: {cut.get('filename') or ''}")
        if cut.get("path"):
            lines.append(f"* SOURCE FILE: {cut['path']}")
        if cut.get("label"):
            lines.append(f"* COMMENT: {cut['label']}")
        lines.append("")
    return "\n".join(lines)
