"""動画編集向けのラフ切り出し。

用途は「探したシーンを素材として抜く」ところまでで、仕上げは既存の焼き込み
(video_overlay)・高画質化(upscale)とNLEに任せる。

既定はstream copy。再encodeが無い分、巨大fileでも即座に終わるため素材出しに適する。
frame単位の精度が要る場合だけ precise=True で再encodeする(encoderは焼き込みと同じ能力解決を
通す)。

== 切り出しの引数順(過去の誤りと訂正) ==

stream copyの-ssは**入力側**(-iの前)に置く。出力側(-iの後ろ)に置くと、ffmpegはkeyframeが
来るまでvideo packetを捨てるため、**先頭が最大1 GOPぶん映像なしになる**。実録画で確認した
実害:

- keyframe間隔17.67秒の録画から10秒を切ると、video streamが存在しない(音声のみの)mp4になる
- 同じ録画から11.6秒を切ると、11.67秒に対してvideo frameが5枚しか入らない
- 60秒を切っても先頭11.3秒、30秒を切っても先頭16.2秒が映像なしになる

このmoduleは以前「HLS segmentが2秒刻みだからkeyframe間隔も約2秒」と仮定していたが、実測の
keyframe間隔は録画ごとに2.1秒〜37.6秒とばらつく(配信側のencoder設定次第で、こちらでは
決められない)。仮定が崩れた分だけ映像が失われていた。

出力側-ssへ寄せた当時の根拠として「入力側-ssだと-tの尺計算が崩れ、11.6秒の指定が25.5秒
出力になる」と記録されていたが、これは**誤診**である。実測すると25.5秒の内訳は
「要求11.6秒 + 直前keyframeまでの13.9秒」で、尺計算は壊れていない。stream copyは
keyframeからしか始められないという原理どおりの結果を、計算誤りと読み違えていた。

よって現在は ``-ss <start> -i <src> -to <end> -copyts`` を使う。-toで終端を絶対時刻として
渡すので、-tのように尺の引き算を挟まずに済む。内容は[startの直前のkeyframe, end]になり、
要求より手前へ伸びた分は lead_seconds として返す(捨てるにはframe精度の再encodeが要る上、
素材用途では前後の余白はむしろ扱いやすいので残す)。

``-noaccurate_seek`` は音声を再encodeする経路(normalize)のために要る。既定のaccurate seekは
「decodeするstreamだけ」-ssの正確な位置まで捨てるため、videoはkeyframeから、audioは要求位置
から始まり、**両者がGOPぶん(実測3.5秒、長い録画では最大37秒)ずれる**。stream copyだけの
経路では復号が無いので影響しない。
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
    ffprobe_available,
    video_encoder_name,
)

logger = logging.getLogger(__name__)

# file名に使えない文字と制御文字だけを落とす。検索語をそのままlabelにするため、
# 日本語を落とすと(検索語はほぼ日本語なので)labelが常に空になり用を成さない。
_UNSAFE_LABEL_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


async def _video_duration_seconds(src: Path) -> Optional[float]:
    """video trackだけの尺。keyframe leadの算出に使う。

    containerの尺(format=duration)は全streamの最大終端-最小開始なので、音声を再encodeする
    normalize経路では loudnorm/aresample がsampleを詰めた分やAAC encoderのdelayまで含む。
    その差をleadとして扱うと、**音声filterの都合でsidecarの0点がずれる**。leadが表すのは
    「videoがkeyframeまで手前へ伸びた量」なので、常にstream copyされるvideo trackの尺だけを
    測る。containerの尺は音声filterが尺を変えたことを検知するcanaryとして別に使うため、
    こちらで置き換えない。"""
    if not ffprobe_available():
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=duration",
            "-of", "default=nokey=1:noprint_wrappers=1", str(src),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
        seconds = float(out.decode().strip())
    except (ValueError, OSError):
        # N/A(trackにdurationが無い)もValueErrorで来る。測れないことは測れないと返す。
        logger.warning("ffprobe video duration probe failed for %s", src, exc_info=True)
        return None
    return seconds if seconds > 0 else None


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
        # -ssは必ず-iの前(入力側)に置く。出力側だとkeyframeが来るまでvideo packetが捨てられ、
        # 先頭が最大1 GOPぶん映像なしになる(module docstringの実測を参照)。
        # -noaccurate_seekは、音声だけ再encodeするnormalize経路でaudioがvideoより後ろから
        # 始まるのを防ぐ。avoid_negative_tsは先頭PTSを0へ寄せ、playerが黒画で待つのを防ぐ。
        args = ["-noaccurate_seek", "-ss", f"{start:.3f}", "-i", str(src),
                "-to", f"{end:.3f}", "-copyts",
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
    # stream copyはkeyframeからしか始められないので、実際の内容は要求より手前から始まる。
    # 何秒手前かを返して、呼び出し側が実物の時刻を示せるようにする。
    # 測るのはvideo trackの尺。containerの尺で引くと、音声を再encodeする経路では音声filterが
    # 動かした尺までleadに混ざり、0点がその分ずれる(_video_duration_secondsを参照)。
    video_actual = None if precise else await _video_duration_seconds(out)
    lead = None if video_actual is None else max(0.0, video_actual - duration)
    tolerance = config.get_clip_duration_tolerance_seconds()
    ctx = {"src": str(src), "output": str(out), "start": start, "end": end,
           "duration_seconds": duration, "output_duration_seconds": actual,
           "video_duration_seconds": video_actual,
           "keyframe_lead_seconds": None if lead is None else round(lead, 3),
           "precise": precise, "encoder": encoder, "size_bytes": size,
           **audio_norm.describe(normalize)}
    # 判定は経路で分ける。再encodeはframe精度なので両側で見るが、stream copyは前へ伸びるのが
    # 正常なので短い側だけを見る。伸びた分まで警告にすると、正常な切り出しが毎回警告になり
    # 「音声filterが尺を変えた」という本来拾いたい異常が埋もれる。
    if actual is not None and (
        abs(actual - duration) > tolerance if precise else actual < duration - tolerance
    ):
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
        # 実際の内容開始。stream copyでは要求より手前のkeyframeになる(preciseでは要求どおり)。
        "keyframe_lead_seconds": None if lead is None else round(lead, 3),
        "actual_start_seconds": start if lead is None else round(start - lead, 3),
    }
