"""見どころの連結出力(highlight reel)。

3時間級の録画が並ぶ運用では「この配信で何が起きたか」を通しで見る手段が無い。切り出し
(clipper)は範囲ごとに別fileを作るので、N個の見どころは N本のmp4になり結局全部開くことに
なる。ここでは同じ範囲listを**1本のmp4**へ連結する。

方式は2段のstream copy(各範囲をTS中間へ切り出し、concat demuxerで1本へ繋ぐ)。実装と、
引数順・TS中間・連結可否の照合をそう選んだ実測上の理由は :mod:`tictok.media.concat` に
ある。再encodeを一切しないので3時間の録画から数分のreelを作っても実時間は数秒で、画質も
原本のままになる。

## 前置き(lead)は残す

stream copyはkeyframe境界でしか切れないので、各範囲の頭には最大1 GOPぶんの前置きが付く。
これは捨てずにそのまま残し、実際の開始位置を戻り値で報告する。frame単位で詰めるには
再encodeが要るが、それはreelの目的(通しで俯瞰する)に対して割に合わない。

## 接合点のA/Vずれ(解決済み)

かつては接合点ごとに音と映像がずれていた。原因は連結ではなく**切り出し段の非対称**で、
``-ss`` に要求時刻を渡すと video は要求の直後のkeyframeから・audio は手前のsegment境界から
始まり、partの先頭に約2秒の音声だけの区間ができていた。concat demuxerはfileのoffsetを
file全体の尺(=長い方=audio)で決めるので、その差が接合ごとにvideoの穴として現れる。

実録画5範囲での実測(成果物から f_v(t)=映っているframeの原本時刻・f_a(t)=鳴っている音の
原本時刻を測り、その差を見た):

===================  ==========  ==========
指標                 修正前      修正後
===================  ==========  ==========
A/Vずれの最大        1,320ms     **68ms**
videoの穴(合計)      10.5秒      2.3秒(注1)
audioの穴(合計)      0.671秒     **0秒**
===================  ==========  ==========

注1: 残る2.3秒は原本自身がkeyframeごとに持つ1 frameぶん(40ms)の間隔が37箇所で、接合とは
無関係。修正後の残差は測り直すと8〜68msの幅で動く(測定側が1 frame単位でぶれる)ので、
**68ms以下**と読むこと。修正前の1,320msはpartの頭(映像が前のpartで止まっている区間)で出る
値で、partの内側では修正前も±18msだった — 症状は「連続的なずれ」ではなく「接合ごとの穴」。

方式は :mod:`tictok.media.concat` にある。当時「``loudnorm`` で先頭0.5秒がずれる」を根拠に
正規化を避けていたが、切り分けの結果 loudnorm は**完全にtiming中立**で(loudnormのみを掛けた
出力は無しの版と全点0.2ms以内で一致)、ずれていたのは同梱していた ``aresample=async=1``
の方だった。切り出し段が揃った今、``aresample`` は不要である。
"""

import contextlib
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Optional

from tictok.core import config, layout
from tictok.media.clipper import _UNSAFE_LABEL_RE, _hhmmss
from tictok.media import concat, hls_source
from tictok.record.video_overlay import _duration_seconds, ffmpeg_available

logger = logging.getLogger(__name__)


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
        if not hls_source.available(src):
            raise RuntimeError(f"録画fileが存在しません: {src.name}")
        parts.append({"src": src, "start": start, "end": end,
                      "label": item.get("label") or ""})

    out = reel_path(parts[0]["src"], parts[0]["start"], parts[-1]["end"],
                    len(parts), label)
    out.parent.mkdir(parents=True, exist_ok=True)
    # 中間fileは合計でreel本体とほぼ同じ容量になる。出力先と同じvolumeへ置いて、空き容量の
    # 判定(呼び出し側)と実際に消費する場所を一致させる。
    workdir = Path(tempfile.mkdtemp(prefix=".reel_", dir=out.parent))

    # mp4が無い録画は.tsのHLSから切る。素材は同じ物を何度も切るので、貸し出しは全部の
    # 切り出しが終わるまで開いたままにする(hls_source参照)。
    async with contextlib.AsyncExitStack() as stack:
        sources = {src: await stack.enter_async_context(hls_source.ffmpeg_source_async(src))
                   for src in dict.fromkeys(part["src"] for part in parts)}
        first = await concat.check_compatible(sources, event="reel.incompatible")
        codec = first["video"]["codec_name"]
        try:
            total = len(parts)
            for index, part in enumerate(parts):
                if on_progress is not None:
                    # 件数は括弧に入れる。段階名に混ぜると、jobの段階履歴が見どころの数だけ
                    # 別々の段階として並ぶ(media_queue.stage_phase が括弧の中を落とす)。
                    await on_progress(f"見どころを切り出し中（{index + 1} / {total}件）",
                                      int(index * 85 / total))
                dst = workdir / f"part{index:04d}.ts"
                cut = await concat.cut_part(
                    sources[part["src"]], part["start"], part["end"], dst, codec,
                    event="reel.cut_failed",
                    message=f'見どころの切り出しに失敗しました（{part["src"].name} '
                            f'{part["start"]:.1f}-{part["end"]:.1f}秒）')
                # stream copyはkeyframeでしか切れないので、実際の開始は要求より手前になる。
                # 何秒手前かは呼び出し側が利用者へ見せられるよう返す(黙って要求どおりと報告
                # すると、reelの目次と実物の時刻が食い違う)。実測値を使う: 尺の差から逆算
                # すると、audioだけが手前から入っているぶんまで前置きに数えてしまう。
                requested = part["end"] - part["start"]
                part.update({"cut": cut, "path": dst, "seconds": cut.seconds,
                             "lead_seconds": cut.lead_seconds,
                             "requested_seconds": round(requested, 3)})

            if on_progress is not None:
                await on_progress("連結中", 85)
            list_path = workdir / "concat.txt"
            await concat.concat_parts(
                [part["cut"] for part in parts], out, list_path,
                event="reel.concat_failed", message="見どころの連結に失敗しました")
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
            "連結後の尺が素材の合計と異なります: %s（素材 %.2fs, 出力 %.2fs）",
            out.name, expected, actual,
            extra={"event": "reel.duration_mismatch", "ctx": ctx},
        )
    logger.info(
        "切り出しの連結が完了しました: %s（%d parts, %d sources）",
        out.name, len(parts), len(sources),
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
