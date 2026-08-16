"""発話の合間の無音を落として繋ぐ(間の詰め)。

shortは尺が短いほど最後まで見られる。ところが配信の切り抜きは「面白い一言」の前後に
数秒の間が入っていることが多く、その間を残したまま尺の上限へ収めようとすると、肝心の
やり取りの方が範囲から落ちる。ここで落とすのは**無音だけ**で、発話は1文字も削らない。

## 対象は成果物であって原本ではない

無音の測定も詰めも、切り出して仕上げた後のmp4に対して行う。原本の時刻軸で計画して切り出し
後へ写す形は採らない — 切り出しはkeyframe境界で前置きが付き(:mod:`tictok.media.clipper`)、
焼き込みも独自にCFRへ畳むので、原本で測った秒はこの時点で成果物の秒ではない。実物を測れば
座標の写し替えが1つも要らず、写し損ねという壊れ方が存在しなくなる。

## 詰め方: 無音の真ん中を落とす

無音spanを丸ごと落とすと発話と発話が密着して聞き苦しくなるため、``keep_seconds`` を残す。
残す位置は**両端**で、落とすのは真ん中である。無音の端は発話の減衰・立ち上がりが含まれる
場所で、そこを落とすと語頭・語尾が欠けたように聞こえる。

## 再encodeである

``select`` filterはframe単位で選ぶのでstream copyでは実現できない。切り出し済みの短い
mp4が相手なので費用は知れているが、**呼び出し順は「焼き込みの後」でなければならない**。
先に詰めると、焼き込みが参照する文字起こしの秒と実物の秒がずれる。
"""

import asyncio
import logging
import re
from pathlib import Path
from typing import Optional

from tictok.core import cancel, config
from tictok.media import concat
from tictok.record.video_overlay import (
    _duration_seconds,
    _encoder_args,
    _mapped_quality,
    ffmpeg_available,
    video_encoder_name,
)

logger = logging.getLogger(__name__)

# silencedetectの報告行。silence_endの行だけが区間の両端を持つ(startは開始しか持たない)。
_SILENCE_END_RE = re.compile(
    r"silence_end:\s*(?P<end>[-\d.]+)\s*\|\s*silence_duration:\s*(?P<duration>[\d.]+)")
_SILENCE_START_RE = re.compile(r"silence_start:\s*(?P<start>[-\d.]+)")

# 1箇所あたりこれ未満しか落とせないなら、その無音は詰めない。接合を1つ増やす代償
# (再encodeの継ぎ目・音の途切れ)に見合わないため。
MIN_REMOVAL_SECONDS = 0.2


async def detect_silences(path: Path, *, threshold_dbfs: Optional[float] = None,
                          min_seconds: Optional[float] = None) -> list:
    """``path`` の無音区間を ``[{"start", "end"}]`` で返す。

    波形cache(:mod:`tictok.media.waveform`)ではなくffmpegのsilencedetectを使う。あちらは
    録画1本ぶんの粗い区間peak列で、shortの尺では刻みが粗すぎて0.2秒級の間を判定できない。
    """
    threshold_dbfs = (config.get_audio_silence_dbfs() if threshold_dbfs is None
                      else float(threshold_dbfs))
    min_seconds = (config.get_audio_silence_min_seconds() if min_seconds is None
                   else float(min_seconds))
    cancel.check_cancelled()
    cmd = ["ffmpeg", "-v", "info", "-nostats", "-i", str(path),
           "-af", f"silencedetect=noise={threshold_dbfs}dB:d={min_seconds}",
           "-f", "null", "-"]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    cancel.register_process(proc)
    try:
        _, stderr = await proc.communicate()
    finally:
        cancel.forget_process(proc)
    cancel.check_cancelled()
    text = (stderr or b"").decode("utf-8", "replace")
    if proc.returncode != 0:
        logger.error(
            "無音の検出に失敗しました: %s", Path(path).name,
            extra={"event": "tighten.detect_failed",
                   "ctx": {"src": str(path), "returncode": proc.returncode,
                           "stderr": text.strip()[:2000]}},
        )
        raise RuntimeError(f"無音を検出できませんでした: {Path(path).name}")
    return parse_silence_log(text)


def parse_silence_log(text: str) -> list:
    """silencedetectの報告から無音区間を読み取る。

    最後の無音がfileの終端まで続く場合、``silence_end`` は出るが ``silence_start`` と対に
    ならない並びで現れることがある。開始を取り逃したときは ``silence_duration`` から復元
    する — 捨てると、末尾の間だけが詰められないという分かりにくい欠落になる。
    """
    spans: list = []
    start = None
    for line in text.splitlines():
        opened = _SILENCE_START_RE.search(line)
        if opened:
            start = max(0.0, float(opened.group("start")))
            continue
        closed = _SILENCE_END_RE.search(line)
        if not closed:
            continue
        end = float(closed.group("end"))
        opened_at = start if start is not None else end - float(closed.group("duration"))
        start = None
        if end > opened_at:
            spans.append({"start": round(max(0.0, opened_at), 3), "end": round(end, 3)})
    return spans


def plan_keeps(duration: float, silences: list, *, min_silence_seconds: float,
               keep_seconds: float) -> dict:
    """残す区間(keeps)と、落とす秒数を決める。

    戻り値の ``keeps`` は ``[(start, end)]`` で、**元のfileの時刻**である。落とすものが
    無ければ ``keeps`` は全体1つになり、呼び出し側は詰め自体を省ける。
    """
    duration = float(duration)
    cuts: list = []
    for span in silences or []:
        start, end = float(span["start"]), min(float(span["end"]), duration)
        length = end - start
        if length < min_silence_seconds:
            continue
        removal = length - keep_seconds
        if removal < MIN_REMOVAL_SECONDS:
            continue
        # 残すのは両端、落とすのは真ん中。端には発話の減衰と立ち上がりが乗っている。
        half = keep_seconds / 2.0
        cuts.append((start + half, end - half))
    cuts.sort()
    keeps: list = []
    cursor = 0.0
    for cut_start, cut_end in cuts:
        if cut_start > cursor:
            keeps.append((round(cursor, 3), round(cut_start, 3)))
        cursor = max(cursor, cut_end)
    if cursor < duration:
        keeps.append((round(cursor, 3), round(duration, 3)))
    kept = sum(end - start for start, end in keeps)
    return {"keeps": keeps, "removed_seconds": round(duration - kept, 3),
            "kept_seconds": round(kept, 3), "cuts": len(cuts)}


def _select_expression(keeps: list) -> str:
    """``select``/``aselect`` に渡す条件式。区間の論理和で表す。

    ``between`` は端点を含むので、隣り合う区間の境界で同じframeが二度採られ得る。keepsは
    無音の真ん中で切った互いに素な区間なので、実際には隣接しない。
    """
    return "+".join(f"between(t,{start:.3f},{end:.3f})" for start, end in keeps)


async def apply(src: Path, dst: Path, keeps: list, *, fps: Optional[float] = None) -> dict:
    """``keeps`` の区間だけを残したmp4を ``dst`` へ書く。

    ``fps`` を渡すと先にCFRへ畳む。``setpts=N/FRAME_RATE/TB`` はframe番号から時刻を作り直す
    ので、入力がVFRのままだと詰めた後の時刻が実際のframe間隔と食い違う。
    """
    if not ffmpeg_available():
        raise RuntimeError("ffmpegが見つかりません。間の詰めにはffmpegのinstallが必要です。")
    if not keeps:
        raise RuntimeError("残す区間がありません。")
    # 保存用の正規化(get_normalize_codec)ではなくshortのcodecを使う。詰めた出力はそのまま
    # 投稿へ回るもので、要求される互換性が違う(config.get_short_codec)。
    codec = config.get_short_codec()
    encoder = await video_encoder_name(codec)
    quality = _mapped_quality(encoder, config.get_short_quality())
    expression = _select_expression(keeps)
    video_chain = ([f"fps={fps}"] if fps else []) + [
        f"select='{expression}'", "setpts=N/FRAME_RATE/TB"]
    audio_chain = [f"aselect='{expression}'", "asetpts=N/SR/TB"]
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(src),
           "-vf", ",".join(video_chain), "-af", ",".join(audio_chain),
           *_encoder_args(encoder, quality), "-c:a", "aac",
           "-movflags", "+faststart", str(dst)]
    try:
        await concat.run(
            cmd, "tighten.failed",
            {"src": str(src), "output": str(dst), "keeps": len(keeps), "encoder": encoder},
            f"{Path(src).name} の間の詰めに失敗しました")
    except BaseException:
        dst.unlink(missing_ok=True)
        raise
    if not dst.is_file():
        raise RuntimeError("間の詰めは成功しましたが出力fileがありません。")
    expected = sum(end - start for start, end in keeps)
    actual = await _duration_seconds(dst)
    info = {"path": str(dst), "keeps": len(keeps),
            "expected_seconds": round(expected, 3),
            "output_duration_seconds": actual,
            "encoder": encoder, "bytes": dst.stat().st_size}
    tolerance = config.get_clip_duration_tolerance_seconds()
    if actual is not None and abs(actual - expected) > tolerance:
        # 詰めは「残す区間の合計」がそのまま出力尺になるはずの操作である。ずれたということは
        # 区間の解釈かCFR畳み込みのどちらかが効いていないので、黙って通さない。
        logger.warning(
            "間の詰めの尺が残す区間の合計と異なります: %s（期待 %.2fs, 出力 %.2fs）",
            dst.name, expected, actual,
            extra={"event": "tighten.duration_mismatch", "ctx": info},
        )
    logger.info(
        "間の詰めが完了しました: %s（%d区間, %.2fs）", dst.name, len(keeps), expected,
        extra={"event": "tighten.done", "ctx": info},
    )
    return info


async def tighten_file(src: Path, dst: Path, *, min_silence_seconds: float,
                       keep_seconds: float, fps: Optional[float] = None) -> dict:
    """測って計画して詰める、までを1回で。落とすものが無ければ ``applied`` がFalseで返る。

    落とすものが無いときに出力を作らないのは、内容が同じfileを再encodeで作り直すことに
    なるため(画質だけが落ちる)。呼び出し側は ``applied`` を見て元のfileを使い続ける。
    """
    duration = await _duration_seconds(src)
    if duration is None:
        raise RuntimeError(f"尺を測れないため間を詰められません: {Path(src).name}")
    silences = await detect_silences(src)
    plan = plan_keeps(duration, silences, min_silence_seconds=min_silence_seconds,
                      keep_seconds=keep_seconds)
    if not plan["cuts"]:
        return {"applied": False, "path": str(src), "silences": len(silences),
                "source_duration_seconds": duration, **plan}
    result = await apply(src, dst, plan["keeps"], fps=fps)
    return {"applied": True, "silences": len(silences),
            "source_duration_seconds": duration, **plan, **result}
