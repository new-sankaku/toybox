"""再生中の1 frameをそのままpngで残す(スクショ)。

置き場は ``<一時保存先>/<配信者>/_screenshots/`` である。rootの決め方(work root固定)も
配信者folderの下という規約も切り出しと同じで、dirだけを分けている — 切り出しmp4の山に1枚ずつ
pngが混ざると、file managerではどちらも探せない。名前の規約は切り出しと揃えたままで
(:func:`tictok.media.clipper.still_path` / :func:`tictok.media.clipper.parse_clip_name`)、
成果物を辿る口(「出力済みclip」tab)も両方の置き場を見るので変わらない。

== 読む素材は「再生に使ったもの」と同じにする ==

mp4と素材(.ts)は時間軸が別物である(mp4のPTS軸と素材のmedia軸。過去の録画は幻の音声穴で
mp4側が数%長い)。playerがHLSで再生している録画をmp4から抜くと、画面で止めた位置と別の絵が
出る。呼び出し側は再生経路(``hls_source.plays_from_hls``)と同じ判断で ``prefer_hls`` を渡す。

== ``-ss`` へ要求時刻をそのまま渡さない(実測) ==

HLS入力は任意時刻に対し、要求より**後ろ**のsegment境界へ着地することがある。実録画
(00058_pomiiiip、3時間級)で測った直接seekの着地は **要求+2.88秒**(1時間地点)と
**+2.90秒**(2時間地点)で、静止画ではこの差がそのまま「別の場面が保存された」になる。
手前(``SEEK_LEADS``)から復号し、``select`` で要求時刻以降の最初のframeを採ると、同じ位置が
+0.001〜0.017秒で収まった。

== 着地は測って確かめる(仮定しない) ==

前置きを何秒取れば足りるかは素材で決まり、こちらからは決められない。そこで ``showinfo`` で
実際の着地時刻を読み、要求から離れていれば前置きを広げて撮り直す。それでも寄らない場合は
**その録画の映像がそこから始まっていない**ことがある(実測: 冒頭10.127秒まで映像frameが無い
録画がある)ため、無限に広げず、返す ``at_seconds`` を**実際の位置**にする — file名もその値で
付くので、名前と中身が食い違わない。
"""

import asyncio
import logging
import re
from pathlib import Path

from tictok.core import cancel, config
from tictok.media import hls_source
from tictok.record.video_overlay import ffmpeg_available

logger = logging.getLogger(__name__)

# 要求時刻の何秒手前からdecodeを始めるか。1つ目で足りなければ広げて撮り直す。実測では
# 6秒で足り(着地の遅れは最大2.90秒)、45秒でも所要は1秒未満だった。
SEEK_LEADS = (6.0, 45.0)
# 着地が要求からこれ以上離れていたら、前置きを広げて撮り直す。実測の正常な着地は+0.02秒
# 以内で、VFRのframe間隔(30fpsで0.033秒)より広く取れば十分。
LANDING_TOLERANCE_SECONDS = 0.3

# ``showinfo`` が出す出力frameの時刻(media軸。-copyts下でfilterが見る値)。
_PTS_RE = re.compile(r"pts_time:([0-9.]+)")


async def _extract(source, at: float, lead: float, out: Path) -> tuple:
    """1回ぶんの抽出。(着地時刻, returncode, stderr) を返す。着地不明ならNone。"""
    offset = float(source.media_offset or 0.0)
    seek = max(0.0, at - lead)
    # -ss は -itsoffset より前の時刻で解釈されるので、こちらへは足し戻す。
    inputs = [*source.input_args, "-copyts"]
    if offset:
        inputs += ["-itsoffset", f"{-offset:.6f}"]
    inputs += ["-ss", f"{seek + offset:.6f}", "-i", str(source.path)]
    # showinfoはINFOで出るので、この1本だけloglevelを落とせない(filterごとの指定は無い)。
    cmd = ["ffmpeg", "-nostdin", "-y", "-loglevel", "info", *inputs,
           "-an", "-sn", "-vf", f"select='gte(t,{at:.6f})',showinfo",
           "-fps_mode", "passthrough", "-frames:v", "1", "-update", "1", str(out)]
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
    cancel.check_cancelled()
    text = (stderr or b"").decode("utf-8", "replace")
    found = _PTS_RE.search(text)
    return (float(found.group(1)) if found else None), proc.returncode, text


async def capture_still(src: Path, at: float, out: Path, *,
                        prefer_hls: bool = False) -> dict:
    """``at``(秒・media軸)のframeを ``out`` へpngで書き、その素性を返す。

    ``at`` ちょうどのframeが無い素材(VFR)では、その直後の最初のframeを採る。要求位置より
    手前のframeは決して採らない。返す ``at_seconds`` は**実際に採れたframeの位置**で、
    要求値ではない。
    """
    if not ffmpeg_available():
        raise RuntimeError("ffmpegが見つかりません。スクショの保存にはffmpegのinstallが必要です。")
    at = max(0.0, float(at))
    out.parent.mkdir(parents=True, exist_ok=True)
    async with hls_source.ffmpeg_source_async(src, prefer_hls=prefer_hls) as source:
        landed = None
        for index, lead in enumerate(SEEK_LEADS):
            landed, returncode, text = await _extract(source, at, lead, out)
            size = out.stat().st_size if out.is_file() else 0
            ctx = {"src": str(src), "output": str(out), "at_seconds": round(at, 3),
                   "lead_seconds": lead, "landed_seconds": landed,
                   "hls": source.is_hls, "returncode": returncode, "size_bytes": size}
            if returncode != 0 or size == 0:
                out.unlink(missing_ok=True)
                tail = text.strip()[-config.get_log_ffmpeg_stderr_chars():]
                logger.error(
                    "%s の %.2f秒 のスクショを保存できませんでした", Path(src).name, at,
                    extra={"event": "still.failed", "ctx": {**ctx, "stderr": tail}},
                )
                # 尺の外を指すとffmpegは正常終了して0 frameを出す(0 byteのfileが残る)。
                # 理由が読めない失敗になるので、この場合だけは何が起きたかを名乗る。
                if returncode == 0:
                    raise RuntimeError(
                        f"この位置に映像がありません（{at:.2f}秒）。録画の尺の中で撮ってください。")
                raise RuntimeError(f"スクショの保存に失敗しました: {tail[:300]}")
            if landed is None or landed - at <= LANDING_TOLERANCE_SECONDS:
                break
            if index + 1 < len(SEEK_LEADS):
                logger.info(
                    "スクショの着地が要求より後ろなので前置きを広げて撮り直します"
                    "（要求 %.2f秒 / 着地 %.2f秒）", at, landed,
                    extra={"event": "still.landing_retry", "ctx": ctx},
                )
            else:
                # 素材の映像がそこから始まっていない場合はどれだけ広げても寄らない
                # (実測: 冒頭10.127秒まで映像frameが無い録画)。実際の位置で名乗る。
                logger.warning(
                    "スクショが要求より後ろのframeになりました（要求 %.2f秒 / 実際 %.2f秒）",
                    at, landed,
                    extra={"event": "still.landed_late", "ctx": ctx},
                )
        actual = at if landed is None else landed
        size = out.stat().st_size
        logger.info(
            "スクショを保存しました: %s（%.2f秒）", out.name, actual,
            extra={"event": "still.saved",
                   "ctx": {"src": str(src), "output": str(out),
                           "requested_seconds": round(at, 3),
                           "at_seconds": round(actual, 3),
                           "hls": source.is_hls, "size_bytes": size}},
        )
        return {"path": str(out), "filename": out.name, "bytes": size,
                "at_seconds": actual, "requested_seconds": at, "hls": source.is_hls}
