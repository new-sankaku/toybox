"""切り抜きmp4の隣へ、文字起こしとcommentをsidecarとして書く。

切り抜きはstream copy 1本(clipper.make_clip)で、元録画はHLS由来のvideo+audioしか持たない。
つまり切り抜きmp4には話した内容もcommentも一切残らず、素材としてNLEへ渡した時点で
「絵と音だけ」になる。DBには両方あるので、切り抜きの時間軸へ写してfileにする。

== 0点はactual_start_secondsであってstartではない ==

stream copyは要求位置ではなく直前のkeyframeから始まるため、実際の内容は要求より手前から
始まる(実測2.1秒〜37.6秒、clipperのdocstringを参照)。要求のstartを0点にすると字幕が
まるごとlead秒ぶん後ろへずれる。clipper.make_clipが返すactual_start_secondsが実物の
0点なので、必ずそちらを使う。

== 元録画から切ったものにしか出さない ==

DBの時刻は元録画mp4のPTS軸。焼き込み出力・Up出力は再encodeを挟んで尺が動き得るので、
そこから切った切り抜きに対しては時刻を保証できない。保証できないまま出すと外部NLEで
「それらしいが合っていない字幕」になり、誤りを検出する手段が無くなる(subtitlesが
segmentを推測で埋めないのと同じ理由)。よってsource以外は書かず、理由を返す。
"""

import logging
from pathlib import Path
from typing import Optional

from tictok.core import config
from tictok.media import comment_track
from tictok.record import subtitles

logger = logging.getLogger("tictok.clip_sidecar")

# 時刻を保証できる素材版。clipperの入力がこれ以外なら書かない。
SOURCE_VARIANT = "source"


def _window(clip: dict) -> tuple:
    """切り抜きが実際に含む区間を元録画の時間軸で返す。

    尺はffprobeの実測を使い、測れない場合だけ要求の尺を使う(その場合keyframe leadも
    測れていないので0点も要求どおりになり、窓は要求区間そのものになる)。"""
    origin = float(clip["actual_start_seconds"])
    actual = clip.get("output_duration_seconds")
    span = float(clip["end"]) - float(clip["start"]) if actual is None else float(actual)
    return origin, origin + span


def _write(path: Path, body: str, encoding: str) -> bool:
    """中身があるときだけ書く。空fileを置くと、NLEは字幕trackが在るものとして読み込み、
    「字幕は付いているが何も出ない」という切り分けにくい状態になる。"""
    if not body.strip():
        return False
    path.write_text(body, encoding=encoding, newline="")
    return True


def skip_reason(variant: str) -> str:
    """この素材版へsidecarを書かない理由。書く場合は空を返す。

    呼び出し側はDBを引く前にこれで判定できる(書かないと決まっているのに転写とcommentを
    読み出すのは無駄なので)。"""
    if not config.get_clip_sidecar_enabled():
        return "sidecarの書き出しが無効です。"
    if variant != SOURCE_VARIANT:
        return ("元録画以外から切り出したため、字幕・commentは書き出しません"
                "(再encodeで時刻が変わり得るため)。")
    return ""


def write(clip: dict, variant: str, transcript: Optional[dict], comments: list) -> dict:
    """切り抜きの隣へsidecarを書き、書けたfile名と省いた理由を返す。

    ``clip`` はclipper.make_clipの戻り値、``comments`` はstorage.search_hits_forの行list
    (元録画の時間軸のまま)。transcriptが無い・commentが無い場合はそのぶんを書かない。"""
    result = {"files": [], "skipped": skip_reason(variant), "timemap_stale": False}
    if result["skipped"]:
        return result

    out = Path(clip["path"])
    start, end = _window(clip)
    duration = end - start

    if transcript is not None:
        stale = not subtitles.timemap_current(transcript.get("timemap_version"))
        result["timemap_stale"] = stale
        segments = subtitles.window_segments(
            transcript.get("segments"), start, end, origin=start)
        suffix, _media_type, encoding = subtitles.EXPORT_FORMATS["srt"]
        if _write(out.with_name(out.stem + suffix),
                  subtitles.to_srt(segments, duration), encoding):
            result["files"].append(out.stem + suffix)
        if stale:
            logger.warning(
                "clip subtitle sidecar written from a stale timemap: %s", out.name,
                extra={"event": "clip.sidecar_timemap_stale",
                       "ctx": {"output": str(out),
                               "timemap_version": transcript.get("timemap_version")}},
            )

    picked = comment_track.usable_comments(comments, start, end, origin=start)
    if picked:
        for fmt in ("srt", "csv"):
            suffix, _media_type, encoding = comment_track.EXPORT_FORMATS[fmt]
            if _write(out.with_name(out.stem + suffix),
                      comment_track.render(fmt, picked, duration), encoding):
                result["files"].append(out.stem + suffix)

    logger.info(
        "clip sidecars written: %s (%d file(s))", out.name, len(result["files"]),
        extra={"event": "clip.sidecar_written",
               "ctx": {"output": str(out), "files": result["files"],
                       "window_start_seconds": round(start, 3),
                       "window_end_seconds": round(end, 3),
                       "comments": len(picked),
                       "timemap_stale": result["timemap_stale"]}},
    )
    return result


def write_safely(clip: dict, variant: str, transcript: Optional[dict],
                 comments: list) -> dict:
    """writeのdisk例外だけを畳む版。

    mp4は既に書けているので、sidecarのwriteが失敗しても切り出しそのものは成功として
    返す。ただし黙って落とすと「字幕が付かない」理由が残らないため、stack traceを記録し、
    errorを戻り値へ載せて画面まで運ぶ。"""
    try:
        return write(clip, variant, transcript, comments)
    except OSError as exc:
        logger.error(
            "clip sidecar write failed: %s", clip.get("filename"),
            exc_info=True,
            extra={"event": "clip.sidecar_failed",
                   "ctx": {"output": clip.get("path"), "variant": variant}},
        )
        return {"files": [], "skipped": "", "timemap_stale": False, "error": str(exc)}
