"""出来上がった short を機械で検品する。

自動生成は「作れた」と「作れている」を混同しやすい。ffmpegが ``rc=0`` を返し、mp4が出来て
いて、尺も名乗っている — それでも中身は片側trackが3割で終わっていたり、範囲が無音の谷に
着地していたりする(前者は実測で焼き込み59件中3件、doc/OVERLAY_OUTPUT_INTEGRITY.md)。人が
1本ずつ再生していた頃はそこで気付けたが、一括生成にはその工程が無い。

ここが見るのは**成果物そのもの**で、生成過程の申告(要求した尺・設定値)は使わない。過程を
信じるなら関門を置く意味が無い。

## 落ちたものを消さない

検品に落ちた成果物は削除せず、``failures`` を付けて残す。消してしまうと、なぜ落ちたのかを
確かめる手段がその場で失われ、閾値が厳しすぎるのか本当に壊れているのかを誰も言えなくなる。
呼び出し側は「落ちた物を成果物として名乗らせない」だけでよい。
"""

import asyncio
import logging
import re
from pathlib import Path
from typing import Optional

from tictok.core import cancel, config
from tictok.media import tighten
from tictok.record.video_overlay import _probe_stream_spans

logger = logging.getLogger(__name__)

# blackdetectの報告行。black_duration まで揃った行だけを採る。
_BLACK_RE = re.compile(
    r"black_start:\s*(?P<start>[\d.]+)\s+black_end:\s*(?P<end>[\d.]+)"
    r"\s+black_duration:\s*(?P<duration>[\d.]+)")

# 検品の不合格理由。画面・log・sidecarが同じ語で名乗れるよう定数にする。
FAIL_NO_VIDEO = "no_video"
FAIL_NO_AUDIO = "no_audio"
FAIL_TRUNCATED = "truncated"
FAIL_SHORTFALL = "shortfall"
FAIL_TOO_SHORT = "too_short"
FAIL_TOO_LONG = "too_long"
FAIL_SILENT = "silent"
FAIL_BLACK = "black"
FAIL_NO_SUBTITLE = "no_subtitle"
FAIL_UNMEASURED = "unmeasured"

FAIL_LABELS = {
    FAIL_NO_VIDEO: "映像trackがありません",
    FAIL_NO_AUDIO: "音声trackがありません",
    FAIL_TRUNCATED: "映像と音声の尺が揃っていません",
    FAIL_SHORTFALL: "要求した尺より短く終わっています",
    FAIL_TOO_SHORT: "尺が型の下限に届きません",
    FAIL_TOO_LONG: "尺が型の上限を超えています",
    FAIL_SILENT: "ほぼ全編が無音です",
    FAIL_BLACK: "映像がほぼ真っ黒です",
    FAIL_NO_SUBTITLE: "字幕を焼く指定なのに焼く発話がありません",
    FAIL_UNMEASURED: "成果物を測れませんでした",
}


async def _black_seconds(path: Path) -> Optional[float]:
    """真っ黒だったframeの合計秒。測れなければNone(0で埋めない)。"""
    cancel.check_cancelled()
    cmd = ["ffmpeg", "-v", "info", "-nostats", "-i", str(path),
           "-vf", "blackdetect=d=0.1", "-an", "-f", "null", "-"]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    cancel.register_process(proc)
    try:
        _, stderr = await proc.communicate()
    finally:
        cancel.forget_process(proc)
    cancel.check_cancelled()
    if proc.returncode != 0:
        return None
    text = (stderr or b"").decode("utf-8", "replace")
    return round(sum(float(m.group("duration")) for m in _BLACK_RE.finditer(text)), 3)


async def inspect(path: Path) -> dict:
    """成果物を測る。判定はしない(:func:`evaluate` の入力になる)。

    測れなかった項目はNoneのまま残す。0で埋めると「無音0秒だった」「真っ黒0秒だった」と
    いう観測を捏造することになり、測れなかった回が最も静かに合格する。
    """
    path = Path(path)
    spans = await _probe_stream_spans(path)
    video = (spans.get("video") or {}).get("seconds")
    audio = (spans.get("audio") or {}).get("seconds")
    seconds = max([s for s in (video, audio) if s is not None], default=None)
    silences = await tighten.detect_silences(path) if audio is not None else []
    silent = None if audio is None else round(
        sum(min(s["end"], audio) - s["start"] for s in silences
            if s["end"] > s["start"]), 3)
    return {
        "path": str(path),
        "bytes": path.stat().st_size if path.is_file() else 0,
        "video_seconds": video,
        "audio_seconds": audio,
        "video_frames": (spans.get("video") or {}).get("frames"),
        "seconds": seconds,
        "silent_seconds": silent,
        "black_seconds": await _black_seconds(path) if video is not None else None,
    }


def _fail(code: str, detail: str) -> dict:
    return {"code": code, "label": FAIL_LABELS[code], "detail": detail}


def evaluate(report: dict, *, preset: dict, expected_seconds: Optional[float] = None,
             subtitle_lines: Optional[int] = None,
             scenes: Optional[int] = None) -> dict:
    """測定結果を合否へ落とす。落ちた理由は**すべて**返す(最初の1件で打ち切らない)。

    打ち切らないのは、閾値の調整に使うためである。1件ずつしか出ないと、直すたびに次の
    不合格が現れる形になり、その成果物が何箇所壊れているのかが最後まで分からない。

    ``scenes`` を渡すと作品(:mod:`tictok.media.work`・Nシーン)として見る。このとき型の
    **尺の下限・上限は当てない**。あれは1シーンの尺を決める値で、5シーンを繋いだ作品は
    定義上その上限を超えるためである。当てれば全ての作品が「上限超過」で落ち、その不合格は
    成果物について何も語らない。

    代わりに作品では ``expected_seconds`` が効く。呼び出し側が「範囲の合計 − 間の詰めで
    落とした合計」を渡すので、どちらの段も frame 精度である以上、成果物はその秒数と一致
    しなければならない。**両trackが揃って短く終わった場合**(片側だけなら ``truncated`` が
    拾う)を捕まえられるのはこの比較だけである。
    """
    failures: list = []
    tolerance = config.get_short_gate_tolerance_seconds()
    video, audio = report.get("video_seconds"), report.get("audio_seconds")
    seconds = report.get("seconds")

    if video is None:
        failures.append(_fail(FAIL_NO_VIDEO, "映像trackを検出できません。"))
    if audio is None:
        failures.append(_fail(FAIL_NO_AUDIO, "音声trackを検出できません。"))
    if video is not None and audio is not None and abs(video - audio) > tolerance:
        failures.append(_fail(
            FAIL_TRUNCATED,
            f"映像 {video:.2f}s / 音声 {audio:.2f}s（許容 {tolerance:.2f}s）"))
    if seconds is None:
        failures.append(_fail(FAIL_UNMEASURED, "尺を測れないため合否を出せません。"))
        return {"ok": False, "failures": failures}

    if expected_seconds is not None and seconds < float(expected_seconds) - tolerance:
        failures.append(_fail(
            FAIL_SHORTFALL, f"要求 {float(expected_seconds):.2f}s に対し {seconds:.2f}s"))
    if scenes is None:
        # 型の尺は1シーンぶんの値。作品には当てない(docstring)。
        if seconds < float(preset["min_seconds"]) - tolerance:
            failures.append(_fail(
                FAIL_TOO_SHORT, f"{seconds:.2f}s < 下限 {float(preset['min_seconds']):.2f}s"))
        if seconds > float(preset["max_seconds"]) + tolerance:
            failures.append(_fail(
                FAIL_TOO_LONG, f"{seconds:.2f}s > 上限 {float(preset['max_seconds']):.2f}s"))

    silent = report.get("silent_seconds")
    if silent is not None and seconds > 0:
        ratio = silent / seconds
        limit = config.get_short_gate_silent_ratio()
        if ratio > limit:
            failures.append(_fail(
                FAIL_SILENT, f"無音 {silent:.2f}s / {seconds:.2f}s（{ratio:.0%}）"))
    black = report.get("black_seconds")
    if black is not None and seconds > 0:
        ratio = black / seconds
        limit = config.get_short_gate_black_ratio()
        if ratio > limit:
            failures.append(_fail(
                FAIL_BLACK, f"黒 {black:.2f}s / {seconds:.2f}s（{ratio:.0%}）"))
    # 字幕は画素を見ても数えられない(焼いた後は背景と区別が付かない)ので、焼く材料が
    # 在ったかどうかで見る。材料が0件なら、字幕ありの指定は満たされていない。
    if int(preset.get("subtitles") or 0) and subtitle_lines is not None and subtitle_lines <= 0:
        failures.append(_fail(FAIL_NO_SUBTITLE, "範囲内に発話が1件もありません。"))
    return {"ok": not failures, "failures": failures}


async def check(path: Path, *, preset: dict, expected_seconds: Optional[float] = None,
                subtitle_lines: Optional[int] = None,
                scenes: Optional[int] = None) -> dict:
    """測って判定する、までを1回で。落ちても成果物は消さない。

    ``scenes`` を渡すと作品として見る(:func:`evaluate`)。logのeventもそちらを名乗る —
    同じ ``short.gate_failed`` で出すと、shortの不合格率を数えたときに作品が混ざる。
    """
    report = await inspect(path)
    verdict = evaluate(report, preset=preset, expected_seconds=expected_seconds,
                       subtitle_lines=subtitle_lines, scenes=scenes)
    result = {**report, **verdict}
    kind, prefix = ("作品", "work") if scenes is not None else ("short", "short")
    if verdict["ok"]:
        logger.info(
            "%sの検品に合格しました: %s（%.2fs）", kind, Path(path).name,
            report["seconds"] or 0.0,
            extra={"event": f"{prefix}.gate_passed", "ctx": result},
        )
    else:
        logger.warning(
            "%sの検品に落ちました: %s（%s）", kind, Path(path).name,
            "、".join(f["label"] for f in verdict["failures"]),
            extra={"event": f"{prefix}.gate_failed", "ctx": result},
        )
    return result
