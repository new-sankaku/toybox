"""見どころの連結出力(highlight reel)。

3時間級の録画が並ぶ運用では「この配信で何が起きたか」を通しで見る手段が無い。切り出し
(clipper)は範囲ごとに別fileを作るので、N個の見どころは N本のmp4になり結局全部開くことに
なる。ここでは同じ範囲listを**1本のmp4**へ連結する。

## 方式: 2段のstream copy

1. 各範囲を MPEG-TS の中間fileへ切り出す(``-c copy``)
2. concat demuxerで中間fileを1本のmp4へ連結する(``-c copy``)

再encodeを一切しないので3時間の録画から数分のreelを作っても実時間は数秒で、画質も原本の
ままになる。中間をmp4ではなくTSにするのは、TSが任意のtimestampを許すためで、実測では
mp4中間だと連結時にNon-monotonic DTSが多発した(TS中間では0件)。

## 切り出しの引数順

``-ss <start> -i <src> -to <end> -copyts`` を使う。理由は実測に基づく:

- **出力側 -ss(clipper方式)は使えない**。stream copyの出力側seekは最初のkeyframeが来るまで
  video packetを捨てるため、GOPより短い範囲は**映像が1 frameも入らない**(実録画の一例では
  keyframe間隔が17.7秒あり、10秒の切り出しが音声だけのmp4になった)。
- ``-ss K -i src -t D`` 形式は、Kがkeyframeから僅かでも手前へずれると1 GOPぶん手前へ飛び、
  尺が倍近くなる(0.0003秒の丸めで16.3秒が33.9秒になる実例を確認)。keyframe位置を秒で
  持ち回る形は脆い。
- ``-ss start -i src -to end -copyts`` は「startの直前のkeyframeからendまで」を過不足なく
  出す。keyframeを自前で探す必要が無く、丸めにも影響されない。

stream copyはkeyframe境界でしか切れないので、各範囲の頭には最大1 GOPぶんの前置き(lead)が
付く。これは捨てずにそのまま残し、実際の開始位置を戻り値で報告する。frame単位で詰めるには
再encodeが要るが、それはreelの目的(通しで俯瞰する)に対して割に合わない。

## 音量の正規化はここでは行わない

範囲ごとに ``loudnorm`` を掛ける形(clipperと同じやり方)を実装して実測したところ、各範囲の
**先頭およそ0.5秒だけ音がずれる**(以降は一致する)。``-copyts`` で絶対timestampを保った入力
に対して音声filter graphを通すと、映像のkeyframe位置と音声の復号開始位置の差を
``aresample=async=1`` が埋めにかかるためで、stream copyのままなら全域でlag 0.001秒未満に
収まることを同じ素材で確認している。ずれた音を黙って出すより出さない方を採る。録画ごとの
音量差を均す必要が出たら、範囲ごとではなく連結後のreelへ1回だけ掛ける形にすること。

## 素材が揃わないとき

concat demuxerのstream copyは全fileのcodec parameterが一致していることが前提で、解像度や
H.264 profileが違うものを繋ぐと再生できない動画が出来る。実DBには同一session内でも profile
が Main と High で食い違う録画が存在するため、連結前に必ず照合し、**違えば明示的に失敗**
させる(黙って再encodeへ倒すと、利用者は原本画質のつもりで再encode物を受け取る)。
"""

import asyncio
import json
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Optional

from tictok.core import cancel, config, layout
from tictok.media.clipper import _UNSAFE_LABEL_RE, _hhmmss
from tictok.record.video_overlay import _duration_seconds, ffmpeg_available

logger = logging.getLogger(__name__)

# mp4/movのlength-prefixed NALをAnnex Bへ直すbitstream filter。TS中間に入れるため必須。
# 未知のcodecは黙って素通しにせず落とす: 変換が要るのに掛けなければTSは壊れる。
_ANNEXB_FILTERS = {"h264": "h264_mp4toannexb", "hevc": "hevc_mp4toannexb"}

# 連結の可否を決めるstream parameter。avcC(mp4のcodec設定)は先頭fileのものが1つだけ書かれる
# ので、ここが食い違う素材を繋ぐと後半が復号できない。levelまで見るのは、同じprofileでも
# levelが違えばSPSが違い、strictなhardware decoderが後半で詰まるため。
_VIDEO_KEYS = ("codec_name", "width", "height", "pix_fmt", "profile", "level")
_AUDIO_KEYS = ("codec_name", "sample_rate", "channels")

_VIDEO_LABELS = {"codec_name": "映像codec", "width": "幅", "height": "高さ",
                 "pix_fmt": "pixel format", "profile": "profile", "level": "level"}
_AUDIO_LABELS = {"codec_name": "音声codec", "sample_rate": "sample rate",
                 "channels": "channel数"}


async def _probe_streams(src: Path) -> dict:
    """srcの先頭video/audio streamのparameterを返す。取れない項目は捏造せずNoneのまま残す
    (Noneは他fileのNone以外と一致しないので、照合は自然に失敗する)。"""
    cmd = ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(src)]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        message = (stderr or b"").decode("utf-8", "replace").strip()
        logger.error(
            "reel probe failed for %s", src.name,
            extra={"event": "reel.probe_failed",
                   "ctx": {"src": str(src), "returncode": proc.returncode,
                           "stderr": message[:2000]}},
        )
        raise RuntimeError(f"素材を解析できませんでした: {src.name}")
    streams = json.loads(stdout.decode("utf-8", "replace")).get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        raise RuntimeError(f"映像streamがありません: {src.name}")
    if audio is None:
        raise RuntimeError(f"音声streamがありません: {src.name}")
    return {
        "video": {k: video.get(k) for k in _VIDEO_KEYS},
        "audio": {k: audio.get(k) for k in _AUDIO_KEYS},
    }


def _mismatch_reasons(first: dict, other: dict) -> list:
    """firstを基準に、otherの食い違う項目を日本語で並べる。"""
    reasons = []
    for kind, keys, labels in (("video", _VIDEO_KEYS, _VIDEO_LABELS),
                               ("audio", _AUDIO_KEYS, _AUDIO_LABELS)):
        for key in keys:
            want, got = first[kind][key], other[kind][key]
            if want != got:
                reasons.append(f"{labels[key]} {want} と {got}")
    return reasons


async def _probe_sources(sources: list) -> dict:
    """全素材のparameterを取り、1つでも食い違えば連結せずに失敗させる。"""
    infos = {}
    for src in sources:
        infos[src] = await _probe_streams(src)
    first_src = sources[0]
    first = infos[first_src]
    codec = first["video"]["codec_name"]
    if codec not in _ANNEXB_FILTERS:
        raise RuntimeError(f"連結に対応していない映像codecです: {codec}")
    for src in sources[1:]:
        reasons = _mismatch_reasons(first, infos[src])
        if not reasons:
            continue
        logger.warning(
            "reel sources are not concat-compatible: %s vs %s", first_src.name, src.name,
            extra={"event": "reel.incompatible",
                   "ctx": {"first": str(first_src), "other": str(src),
                           "first_params": first, "other_params": infos[src],
                           "reasons": reasons}},
        )
        raise RuntimeError(
            f"素材の形式が揃っていないため連結できません（{first_src.name} と {src.name}: "
            f"{ '、'.join(reasons) }）。同じ形式の録画だけを選ぶか、先に再mp4化してください。"
        )
    return first


def reel_path(src: Path, start: float, end: float, count: int,
              label: Optional[str] = None) -> Path:
    """出力path。同じ範囲listで作り直すと同じfileを上書きする(clipperと同じ決め方)。"""
    streamer = layout.streamer_of(src.stem)
    target_dir = layout.clips_dir(layout.record_root_of(src), streamer)
    name = f"{src.stem}_reel{count}_{_hhmmss(start)}-{_hhmmss(end)}"
    if label:
        safe = _UNSAFE_LABEL_RE.sub("_", label).strip(" ._")[:40]
        if safe:
            name = f"{name}_{safe}"
    return target_dir / f"{name}.mp4"


async def _run(cmd: list, event: str, ctx: dict, message: str) -> None:
    cancel.check_cancelled()
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
        detail = (stderr or b"").decode("utf-8", "replace").strip()
        logger.error(
            "%s", message,
            extra={"event": event,
                   "ctx": {**ctx, "returncode": proc.returncode, "stderr": detail[:2000]}},
        )
        raise RuntimeError(f"{message}: {detail[:300]}")


async def _cut_part(src: Path, start: float, end: float, dst: Path, codec: str) -> float:
    """[直前のkeyframe, end)をTSの中間fileへ複製し、その実尺(秒)を返す。"""
    await _run(
        ["ffmpeg", "-v", "error", "-y",
         "-ss", f"{start:.3f}", "-i", str(src), "-to", f"{end:.3f}", "-copyts",
         "-c", "copy", "-bsf:v", _ANNEXB_FILTERS[codec], "-f", "mpegts", str(dst)],
        "reel.cut_failed",
        {"src": str(src), "start": start, "end": end, "output": str(dst)},
        f"見どころの切り出しに失敗しました（{src.name} {start:.1f}-{end:.1f}秒）",
    )
    written = await _duration_seconds(dst)
    if written is None:
        raise RuntimeError(f"切り出した中間fileの尺を測れませんでした（{src.name}）。")
    return written


async def make_reel(items: list, *, label: Optional[str] = None,
                    on_progress: Optional[Callable] = None) -> dict:
    """複数の範囲を1本のmp4へ連結し、結果を返す。

    ``items`` は ``{"src": Path, "start": 秒, "end": 秒, "label": 任意}`` の並び。並べ替えは
    しない: 呼び出し側が意図した順(時刻順とは限らない)をそのまま尺順にする。
    """
    if not ffmpeg_available():
        raise RuntimeError("ffmpegが見つかりません。連結にはffmpegのinstallが必要です。")
    if not items:
        raise RuntimeError("連結する範囲がありません。")

    parts = []
    for item in items:
        src = Path(item["src"])
        start, end = float(item["start"]), float(item["end"])
        if end <= start:
            raise RuntimeError("終了位置は開始位置より後にしてください。")
        if not src.is_file():
            raise RuntimeError(f"録画fileが存在しません: {src.name}")
        parts.append({"src": src, "start": start, "end": end,
                      "label": item.get("label") or ""})

    sources = list(dict.fromkeys(part["src"] for part in parts))
    first = await _probe_sources(sources)
    codec = first["video"]["codec_name"]

    out = reel_path(parts[0]["src"], parts[0]["start"], parts[-1]["end"],
                    len(parts), label)
    out.parent.mkdir(parents=True, exist_ok=True)
    # 中間fileは合計でreel本体とほぼ同じ容量になる。出力先と同じvolumeへ置いて、空き容量の
    # 判定(呼び出し側)と実際に消費する場所を一致させる。
    workdir = Path(tempfile.mkdtemp(prefix=".reel_", dir=out.parent))

    try:
        total = len(parts)
        for index, part in enumerate(parts):
            if on_progress is not None:
                await on_progress(f"({index + 1}/{total}) 見どころを切り出し中",
                                  int(index * 85 / total))
            dst = workdir / f"part{index:04d}.ts"
            written = await _cut_part(part["src"], part["start"], part["end"], dst, codec)
            # stream copyはkeyframeでしか切れないので、実際の開始は要求より手前になる。
            # 何秒手前かは呼び出し側が利用者へ見せられるよう返す(黙って要求どおりと報告
            # すると、reelの目次と実物の時刻が食い違う)。
            requested = part["end"] - part["start"]
            part.update({"path": dst, "seconds": written,
                         "lead_seconds": round(max(0.0, written - requested), 3),
                         "requested_seconds": round(requested, 3)})

        if on_progress is not None:
            await on_progress("連結中", 85)
        list_path = workdir / "concat.txt"
        # concat demuxerのfile行はsingle quoteで囲まれるので、path中のquoteは閉じ扱いになる。
        # 中間fileの名前はここで作った part0000.ts なので、実際には現れない。
        list_path.write_text(
            "".join(f"file '{part['path'].as_posix()}'\n" for part in parts),
            encoding="utf-8")
        # +genptsは中間fileの絶対timestamp(copyts由来)を連結側で振り直させる。
        await _run(
            ["ffmpeg", "-v", "error", "-y", "-fflags", "+genpts",
             "-f", "concat", "-safe", "0", "-i", str(list_path),
             "-c", "copy", "-movflags", "+faststart", str(out)],
            "reel.concat_failed",
            {"output": str(out), "parts": len(parts)},
            "見どころの連結に失敗しました",
        )
    except BaseException:
        out.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    if not out.is_file():
        raise RuntimeError("連結は成功しましたが出力fileがありません。")
    size = out.stat().st_size
    actual = await _duration_seconds(out)
    expected = sum(part["seconds"] for part in parts)
    requested = sum(part["requested_seconds"] for part in parts)
    lead = sum(part["lead_seconds"] for part in parts)
    ctx = {"output": str(out), "parts": len(parts), "sources": len(sources),
           "expected_seconds": round(expected, 3),
           "requested_seconds": round(requested, 3), "lead_seconds": round(lead, 3),
           "output_duration_seconds": actual, "size_bytes": size}
    # 期待尺は「要求した範囲の合計」ではなく「切り出した中間fileの合計」。前者と比べると
    # keyframeぶんの前置きを常に誤差として数えることになり、本物の欠落を隠す。
    if actual is not None and abs(actual - expected) > config.get_clip_duration_tolerance_seconds():
        logger.warning(
            "reel duration differs from its parts: %s (%.2fs of parts, %.2fs written)",
            out.name, expected, actual,
            extra={"event": "reel.duration_mismatch", "ctx": ctx},
        )
    logger.info(
        "reel exported: %s (%d parts, %d sources)", out.name, len(parts), len(sources),
        extra={"event": "reel.exported", "ctx": ctx},
    )
    if on_progress is not None:
        await on_progress("完了", 100)
    return {
        "path": str(out),
        "filename": out.name,
        "bytes": size,
        "parts": [{"src": str(part["src"]), "start": part["start"], "end": part["end"],
                   "label": part["label"], "seconds": round(part["seconds"], 3),
                   "requested_seconds": part["requested_seconds"],
                   "lead_seconds": part["lead_seconds"]}
                  for part in parts],
        "sources": [str(src) for src in sources],
        # 要求の合計と、keyframe境界のせいで前に付いた合計。GOPの長い録画では前置きが
        # 要求より長くなることがある(実録画で30秒の範囲に37秒の前置きが付いた例あり)ので、
        # 画面が「90秒のつもりが134秒」を説明できるよう両方返す。
        "requested_seconds": round(requested, 3),
        "lead_seconds": round(lead, 3),
        "output_duration_seconds": actual,
    }
