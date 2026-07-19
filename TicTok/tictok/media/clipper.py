"""動画編集向けのラフ切り出し。

用途は「探したシーンを素材として抜く」ところまでで、仕上げは既存の焼き込み
(video_overlay)・高画質化(upscale)とNLEに任せる。

既定はstream copy: 録画のHLS segmentは2秒刻み(recorderのsegment_seconds)なので
keyframe間隔も約2秒で、切り出し開始は最大でその1区間だけ手前へ寄る。再encodeが無い分
巨大fileでも即座に終わるため、素材出しにはこちらが適する。frame単位の精度が要る場合だけ
precise=Trueで再encodeする(encoderは焼き込みと同じ能力解決を通す)。
"""

import asyncio
import logging
import re
from pathlib import Path
from typing import Optional

from tictok.core import cancel, config, layout
from tictok.record import audio_norm
from tictok.record.video_overlay import (
    _encoder_args,
    _mapped_quality,
    _duration_seconds,
    ffmpeg_available,
    video_encoder_name,
)

logger = logging.getLogger(__name__)

# file名に使えない文字と制御文字だけを落とす。検索語をそのままlabelにするため、
# 日本語を落とすと(検索語はほぼ日本語なので)labelが常に空になり用を成さない。
_UNSAFE_LABEL_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def _hhmmss(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    h, rest = divmod(int(seconds), 3600)
    m, s = divmod(rest, 60)
    return f"{h:02d}{m:02d}{s:02d}"


def clip_path(src: Path, start: float, end: float, label: Optional[str] = None) -> Path:
    streamer = layout.streamer_of(src.stem)
    target_dir = layout.clips_dir(layout.record_root_of(src), streamer)
    name = f"{src.stem}_{_hhmmss(start)}-{_hhmmss(end)}"
    if label:
        safe = _UNSAFE_LABEL_RE.sub("_", label).strip(" ._")[:40]
        if safe:
            name = f"{name}_{safe}"
    return target_dir / f"{name}.mp4"


async def make_clip(src: Path, start: float, end: float, label: Optional[str] = None,
                    precise: bool = False, normalize: Optional[dict] = None) -> dict:
    """[start, end)をmp4へ切り出し、出力pathを返す。

    ``normalize`` に audio_norm.targets() を渡すと音声だけを再encodeして音量を揃える。
    映像は既定どおりstream copyのままなので、正規化しても切り出しの速さは変わらない。
    録画はHLS由来のVFRで、音声filterだけを足すと同期が崩れるため、audio_norm側で
    aresample=async=1を必ず前段に置いている。
    """
    if not ffmpeg_available():
        raise RuntimeError("ffmpegが見つかりません。切り出しにはffmpegのinstallが必要です。")
    if not src.is_file():
        raise RuntimeError("録画fileが存在しません。")
    duration = float(end) - float(start)
    if duration <= 0:
        raise RuntimeError("終了位置は開始位置より後にしてください。")

    out = clip_path(src, start, end, label)
    out.parent.mkdir(parents=True, exist_ok=True)

    if normalize:
        # loudnormは192kHzを出すので、sourceの実rateを測って出力をそこへ戻す。
        rate = await asyncio.to_thread(audio_norm.probe_sample_rate, src)
        audio_args = audio_norm.encode_args(**normalize, sample_rate=rate)
    else:
        audio_args = ["-c:a", "aac"]
    # 正規化しないstream copyは従来どおり全streamをそのまま複製する(-c copy)。音声だけを
    # 差し替えるときだけ映像を名指しでcopyする。
    copy_args = (["-c:v", "copy", *audio_args] if normalize else ["-c", "copy"])

    if precise:
        codec = config.get_normalize_codec()
        encoder = await video_encoder_name(codec)
        quality = _mapped_quality(encoder, config.get_normalize_quality())
        # -ssを-iの後ろに置くとdecodeしてから捨てるためframe精度で切れる。
        codec_args = ["-ss", f"{start:.3f}", "-t", f"{duration:.3f}"] \
            + _encoder_args(encoder, quality) + audio_args
        args = ["-i", str(src)] + codec_args
    else:
        encoder = "copy"
        # -ssは必ず-iの後ろ(出力側)に置く。録画はHLS stream-copy由来のVFRで、入力側-ssだと
        # -tの尺計算が崩れ、11.6秒の指定が25.5秒出力になる実例を確認している。出力側seekでも
        # ffmpegは内部でseekするため6579秒のfileで約1.1秒と実用速度に収まる。
        # avoid_negative_tsは先頭PTSを0へ寄せ、playerが黒画で待つのを防ぐ。
        args = ["-i", str(src), "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
                *copy_args, "-avoid_negative_ts", "make_zero"]

    cmd = ["ffmpeg", "-v", "error", "-y", *args, "-movflags", "+faststart", str(out)]
    cancel.check_cancelled()
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    cancel.register_process(proc)
    try:
        _, stderr = await proc.communicate()
    finally:
        cancel.forget_process(proc)
    if cancel.is_cancelled():
        out.unlink(missing_ok=True)
        cancel.check_cancelled()
    if proc.returncode != 0 or not out.is_file():
        message = (stderr or b"").decode("utf-8", "replace").strip()
        logger.error(
            "clip export failed for %s (%.2f-%.2f)", src.name, start, end,
            extra={"event": "clip.failed",
                   "ctx": {"src": str(src), "start": start, "end": end,
                           "precise": precise, "encoder": encoder,
                           **audio_norm.describe(normalize),
                           "returncode": proc.returncode, "stderr": message[:2000]}},
        )
        raise RuntimeError(f"切り出しに失敗しました: {message[:300]}")

    size = out.stat().st_size
    # 音声だけを再encodeする経路は、filterがsampleを詰めたり落としたりすると尺が動く。
    # 指定と実測が離れていないかを毎回測って記録する(判定不能なときは捏造せずNone)。
    actual = await _duration_seconds(out)
    ctx = {"src": str(src), "output": str(out), "start": start, "end": end,
           "duration_seconds": duration, "output_duration_seconds": actual,
           "precise": precise, "encoder": encoder, "size_bytes": size,
           **audio_norm.describe(normalize)}
    if actual is not None and abs(actual - duration) > config.get_clip_duration_tolerance_seconds():
        logger.warning(
            "clip duration differs from the request: %s (%.2fs requested, %.2fs written)",
            out.name, duration, actual,
            extra={"event": "clip.duration_mismatch", "ctx": ctx},
        )
    logger.info(
        "clip exported: %s (%.2f-%.2f, %s)", out.name, start, end, encoder,
        extra={"event": "clip.exported", "ctx": ctx},
    )
    return {
        "path": str(out),
        "filename": out.name,
        "bytes": size,
        "start": start,
        "end": end,
        "precise": precise,
        "encoder": encoder,
        "normalized": bool(normalize),
        "output_duration_seconds": actual,
    }
