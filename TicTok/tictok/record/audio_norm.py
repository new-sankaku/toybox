"""音量正規化(loudnorm)のffmpeg引数を1箇所に持つ。

配信ごとに音量が大きくばらつくため、clip・焼き込み出力・Up出力・録画本体の音量正規化・
再mp4化のどれから出しても同じ目標値へ揃うようにする。目標はEBU R128のI(統合ラウドネス)と
TP(true peak)の2値だけで、preset tableのような機構は置かない。

**one-passのまま使う(2-passにしない)**: ffmpegのloudnormは1 passでは3秒先読みの動的
normalizerとして働き、配信中の場面差(静かな一人喋りとbattleで20dB以上開く)をその場で
詰める。measured_*を渡す2 passは統合値を正確に当てられる代わりに一定gainになり、1本の
中の落差はそのまま残る。実録画18分での実測は、短期音量の広がりが 元26.0 LU → 1 pass
7.7 LU → 2 pass 25.4 LU。揃えたいのは1本の中の聞き取りやすさなので1 passを採る。
speechnorm・dynaudnormの併用も同じ実測で 8.6 / 8.0 LU と1 pass単体(7.7)より悪く、
処理時間だけ増えたので使わない。

**aresample=async=1を必ず前段に置く**: 録画はHLS由来のVFRで、音声側にもsegment境界の
timestamp跳びがある。loudnormは時刻を見ずにsampleを流すため、これを挟まないまま音声だけ
再encodeすると映像(stream copy)との同期が崩れる。

**出力sample rateはsourceと同じ値へ明示的に戻す**: loudnormは入力に関わらず192kHzで
出力するため、指定しないと後段のaac encoderが対応可能な最寄りの96kHzを選び、音質は
変わらないまま音声dataだけが約2倍になる。sourceの実値はprobe_sample_rate()で測る。
"""

import json
import logging
import subprocess
from pathlib import Path
from typing import Optional

from tictok.core import ffprobe
from tictok.record.recorder import ffmpeg_ctx, ffprobe_available

logger = logging.getLogger(__name__)

# 単一streamのheaderを読むだけなので短い方の上限。実体は core.ffprobe。
_PROBE_TIMEOUT_SECONDS = ffprobe.SHORT_TIMEOUT_SECONDS

# 設定key(clip・焼き込み・Up出力で共有する)。焼き込みのcache signatureへも渡すので、
# 値を増やしたらvideo_overlay.OVERLAY_KEYSにも足すこと。
NORMALIZE_SETTING_KEYS = (
    "audio_normalize_lufs",
    "audio_normalize_true_peak",
    "audio_normalize_bitrate_kbps",
)


def targets(settings) -> dict:
    """設定から正規化の目標値を取り出す。有効/無効の判断は呼び出し側が行う。"""
    return {
        "target_lufs": float(settings.get("audio_normalize_lufs")),
        "true_peak": float(settings.get("audio_normalize_true_peak")),
        "bitrate_kbps": int(settings.get("audio_normalize_bitrate_kbps")),
    }


def targets_from_cfg(cfg: dict) -> Optional[dict]:
    """焼き込みcfg(overlay_settings)から目標値を作る。無効ならNone。"""
    if not int(cfg.get("video_output_normalize_audio") or 0):
        return None
    return {
        "target_lufs": float(cfg["audio_normalize_lufs"]),
        "true_peak": float(cfg["audio_normalize_true_peak"]),
        "bitrate_kbps": int(cfg["audio_normalize_bitrate_kbps"]),
    }


def probe_sample_rate(src: Path, input_args: tuple = ()) -> Optional[int]:
    """入力の音声sample rateをffprobeで測る。音声streamを持たない入力ではNone。

    blockingなので、async側からはasyncio.to_thread()経由で呼ぶこと。取得できない
    ときに既定値を当てると出力が黙って別のrateへ書き換わるため、probe自体の失敗は
    Noneに丸めずraiseする(「音声streamが無い」だけをNoneで表す)。
    """
    if not ffprobe_available():
        raise RuntimeError("ffprobeが見つかりません。音量正規化にはffmpeg一式のinstallが必要です。")
    args = [
        "ffprobe", "-v", "error", *input_args, "-select_streams", "a:0",
        "-show_entries", "stream=sample_rate", "-of", "json", str(src),
    ]
    try:
        completed = subprocess.run(
            args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=_PROBE_TIMEOUT_SECONDS, check=True,
        )
        streams = json.loads(completed.stdout.decode("utf-8", "replace")).get("streams") or []
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        stderr = getattr(exc, "stderr", None)
        logger.error(
            "%s の音声のsample rateを取得できません", Path(src).name,
            extra={"event": "process.ffprobe_failed",
                   "ctx": {"stage": "audio_sample_rate", "path": str(src),
                           **ffmpeg_ctx(
                               args,
                               getattr(exc, "returncode", None),
                               stderr_text=stderr.decode("utf-8", "replace") if stderr else None,
                           )}},
            exc_info=True,
        )
        raise RuntimeError(f"音声情報の取得に失敗しました: {exc}") from exc
    if not streams:
        return None
    rate = int(streams[0]["sample_rate"])
    if rate <= 0:
        raise RuntimeError(f"音声のsample rateが不正です: {rate}")
    return rate


def audio_filter(target_lufs: float, true_peak: float,
                 resample: str = "async=1") -> str:
    """``resample`` はaresampleへ渡す指定。既定は完成したmp4を入力に取る経路(切り出し・
    焼き込み・音量正規化)向け。HLS segmentを結合しながら正規化する経路(再mp4化)だけは
    ``async=1:first_pts=0`` を渡すこと。live .tsの開始PTSは任意の値なので、先頭を0へ
    寄せないと音声だけが映像と別の原点で始まる。"""
    return f"aresample={resample},loudnorm=I={target_lufs:g}:TP={true_peak:g}"


def encode_args(target_lufs: float, true_peak: float, bitrate_kbps: int,
                sample_rate: Optional[int], resample: str = "async=1") -> list:
    """音声だけを再encodeする引数。映像側の指定(-c:v copy等)は呼び出し側が持つ。

    ``sample_rate`` はprobe_sample_rate()で測ったsourceの実値。loudnormが192kHzへ
    上げた分をここで元へ戻す。音声streamを持たない入力(None)では制約する対象が無い
    ので付けない。
    """
    args = ["-c:a", "aac", "-b:a", f"{int(bitrate_kbps)}k",
            "-af", audio_filter(target_lufs, true_peak, resample)]
    if sample_rate is not None:
        args += ["-ar", str(int(sample_rate))]
    return args


def describe(normalize: Optional[dict]) -> dict:
    """logのctxへ入れる形。Noneのときも「正規化していない」ことを明示的に残す。"""
    if not normalize:
        return {"audio_normalize": False}
    return {"audio_normalize": True,
            "audio_target_lufs": normalize["target_lufs"],
            "audio_true_peak": normalize["true_peak"],
            "audio_bitrate_kbps": normalize["bitrate_kbps"]}
