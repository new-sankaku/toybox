"""TS中間を経由したstream copyの切り出しと連結。

reel(見どころの連結)と切り出し(clipper)が同じ機構を使うため、両者の共通層としてここに置く。
方式と、その方式を選んだ実測上の理由は以下のとおり。

## なぜ中間をmp4ではなくTSにするか

TSは任意のtimestampを許す。実測ではmp4中間だと連結時にNon-monotonic DTSが多発した
(TS中間では0件)。またAnnex BのTSはIDRごとにSPS/PPSがin-bandで付くので、異なる素材を
並べてもTS段では破綻しない。

## 切り出しの引数順

``-ss <aim> -i <src> -to <end> -copyts`` を使う。理由は実測に基づく:

- **出力側 -ss は使えない**。stream copyの出力側seekは最初のkeyframeが来るまでvideo packetを
  捨てるため、GOPより短い範囲は**映像が1 frameも入らない**(実録画の一例ではkeyframe間隔が
  17.7秒あり、10秒の切り出しが音声だけのmp4になった)。実測では、先頭packetがちょうど狙点の
  keyframeであってもそれを落とす(:mod:`doc/CLIP_TIMEBASE` §8)。
- ``-ss K -i src -t D`` 形式は、Kがkeyframeから僅かでも手前へずれると1 GOPぶん手前へ飛び、
  尺が倍近くなる(0.0003秒の丸めで16.3秒が33.9秒になる実例を確認)。keyframe位置を秒で
  持ち回る形は脆い。

## ``-ss`` を要求時刻そのものへ渡してはいけない

実録画(HLS入力、keyframe間隔約1.96秒)で ``-ss`` に要求時刻を渡した実測では、

- **video は要求時刻の「直後」のkeyframeから始まる**(要求 container 301.402 に対し 302.082。
  直前のkeyframe 300.121 は実在するのに落ちる) → **要求した範囲の映像を最大1 GOP失う**
- **audio は要求時刻より手前のsegment境界から始まる**(300.053)

この非対称が「連結物のA/Vずれ」の実体である。partの先頭に**約2秒の音声だけの区間**ができ、
concat demuxerはfileのoffsetをfile全体の尺(=長い方=audio)で決めるため、接合ごとにvideoへ
約2秒の穴が空く(6 partの実測で合計10.4秒)。

そこで ``-ss`` には要求時刻ではなく :func:`tictok.media.keyframes.seek_target` の狙点
(要求以前の最後のkeyframe ``k`` と1つ手前 ``k_prev`` の中点)を渡す。上の着地規則なら ``k`` に、
合成clipで観測した規則(要求未満で最後のkeyframe)なら ``k_prev`` に着地し、**どちらでも要求
時刻より手前**なので要求した範囲を失わない。着地は毎回実測して検証する。

## audioの前置きは連結時に落とす

``-ss`` を ``k`` へ寄せてもaudioはさらに手前のsegment境界から入る(実測1.99秒)。stream copyで
audio packetを落とす手段は出力側 ``-ss`` しか無く、それは狙点のkeyframeまで落とすので使えない。
代わりに**concat demuxerの ``inpoint``/``outpoint`` で両streamを同じ窓へ揃える**。

窓の始点をどこへ置くかは :func:`_inpoint_for` にまとめてある(**audio packetの境界ちょうど**、
かつvideo先頭より1 frame以上手前)。実測では、この2条件を満たしたときだけ成果物のA/Vずれが
**17ms以下**になる。境界の途中に置くと75ms先行し、際に置くと映像streamが消える。

## 連結の可否は必ず事前に照合する

concat demuxerのstream copyは全fileのcodec parameterが一致していることが前提で、解像度や
H.264 profileが違うものを繋ぐと再生できない動画が出来る。mp4のavcC(codec設定)は先頭fileの
ものが1つだけ書かれるため、後半が復号できなくなる。実DBには同一session内でも profile が
Main と High で食い違う録画が存在するため、連結前に必ず照合し、**違えば明示的に失敗**させる
(黙って再encodeへ倒すと、利用者は原本画質のつもりで再encode物を受け取る)。
"""

import asyncio
import json
import logging
import math
from pathlib import Path
from statistics import median
from typing import NamedTuple, Optional

from tictok.core import cancel, config, ffprobe
from tictok.media import keyframes

logger = logging.getLogger(__name__)

# 中間fileの軸を入力のcontainer軸と同じにする。mpegts muxerは既定で約1.4秒のinitial offsetを
# 乗せるため、これが無いと ``inpoint`` に渡す値と中間fileの実timestampが1.4秒食い違う。
MUX_NO_OFFSET = ("-muxdelay", "0", "-muxpreload", "0")

# 窓の始点を1 audio packetずつ下げて連結をやり直す上限。始点を際に置くと先頭のkeyframeが
# 落ちるが、落ちる閾値は素材で動くので推測せず最小から試す(:func:`_inpoint_for`)。
# 3回でaudio 3 packet(実測48kHz HE-AACで約128ms)ぶん下がる。そこまで下げても映像が入らない
# なら原因は別なので、黙って下げ続けずに失敗させる。
WIDEN_ATTEMPTS = 3

# mp4/movのlength-prefixed NALをAnnex Bへ直すbitstream filter。TS中間に入れるため必須。
# 未知のcodecは黙って素通しにせず落とす: 変換が要るのに掛けなければTSは壊れる。
ANNEXB_FILTERS = {"h264": "h264_mp4toannexb", "hevc": "hevc_mp4toannexb"}

# 連結の可否を決めるstream parameter。avcC(mp4のcodec設定)は先頭fileのものが1つだけ書かれる
# ので、ここが食い違う素材を繋ぐと後半が復号できない。levelまで見るのは、同じprofileでも
# levelが違えばSPSが違い、strictなhardware decoderが後半で詰まるため。
VIDEO_KEYS = ("codec_name", "width", "height", "resolutions", "pix_fmt", "profile", "level")
AUDIO_KEYS = ("codec_name", "sample_rate", "channels")

VIDEO_LABELS = {"codec_name": "映像codec", "width": "幅", "height": "高さ",
                "resolutions": "配信中に切り替わった解像度の数",
                "pix_fmt": "pixel format", "profile": "profile", "level": "level"}
AUDIO_LABELS = {"codec_name": "音声codec", "sample_rate": "sample rate",
                "channels": "channel数"}


async def run(cmd: list, event: str, ctx: dict, message: str) -> None:
    """ffmpegを1回走らせる。失敗はRuntimeErrorにし、途中の取り消しも尊重する。"""
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


async def _probe(cmd: list, src) -> str:
    """ffprobeを1回走らせて標準出力を返す。失敗はRuntimeErrorにし、取り消しも尊重する。"""
    result = await ffprobe.run(cmd)
    if not result.ok:
        detail = result.stderr.strip()
        logger.error(
            "連結する素材 %s の解析に失敗しました", Path(src).name,
            extra={"event": "concat.probe_failed",
                   "ctx": {"src": str(src), "returncode": result.returncode,
                           "stderr": detail[:2000]}},
        )
        raise RuntimeError(f"素材を解析できませんでした: {Path(src).name}")
    return result.stdout


async def probe_codec_params(source) -> dict:
    """srcの先頭video/audio streamのparameterを、ffprobe 1回ぶんだけで返す。取れない項目は
    捏造せずNoneのまま残す。

    ``probe_stream_params`` と違い解像度の全種類を採らない(=録画全編のkeyframe走査をしない)。
    そのぶん ``width``/``height`` はstream headerの1組、``resolutions`` は未測定のNoneなので、
    **連結の可否を決める照合には使えない**。原本と同じ設定でencodeし直すために要る値
    (pix_fmt / profile / level / sample_rate / channels)はここで揃うので、照合をしない
    呼び出し(smart cutのhead再encode)はこちらを使う。"""
    src = source.path
    text = await _probe(
        ["ffprobe", "-v", "error", *source.input_args,
         "-show_streams", "-of", "json", str(src)], src)
    streams = json.loads(text).get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        raise RuntimeError(f"映像streamがありません: {src.name}")
    if audio is None:
        raise RuntimeError(f"音声streamがありません: {src.name}")
    return {
        "video": {k: video.get(k) for k in VIDEO_KEYS},
        "audio": {k: audio.get(k) for k in AUDIO_KEYS},
    }


async def probe_stream_params(source) -> dict:
    """srcの先頭video/audio streamのparameterを返す。取れない項目は捏造せずNoneのまま残す
    (Noneは他fileのNone以外と一致しないので、照合は自然に失敗する)。

    幅と高さだけはstream headerの値を使わない。あれは1組しか出ず、混在解像度の録画では
    開いた所の値でしかないので、全編に現れる解像度の最大を採る。``resolutions``(種類数)も
    並べて比べるのは、包む枠が同じでも中で切り替わる素材は連結できないため — avcCは
    先頭fileのものが1つだけ書かれるので、切替後は復号できなくなる。"""
    # 循環importを避けるためここでimportする(hls_sourceはこのmoduleを使う下流ではないが、
    # media package内の依存の向きを一方向に保つ)。
    from tictok.media import hls_source

    params = await probe_codec_params(source)
    video = params["video"]
    found = await hls_source.resolutions(source)
    return {
        "video": {
            **video,
            "width": max((w for w, _ in found), default=video["width"]),
            "height": max((h for _, h in found), default=video["height"]),
            "resolutions": len(found) or None,
        },
        "audio": params["audio"],
    }


def mismatch_reasons(first: dict, other: dict) -> list:
    """firstを基準に、otherの食い違う項目を日本語で並べる。"""
    reasons = []
    for kind, keys, labels in (("video", VIDEO_KEYS, VIDEO_LABELS),
                               ("audio", AUDIO_KEYS, AUDIO_LABELS)):
        for key in keys:
            want, got = first[kind][key], other[kind][key]
            if want != got:
                reasons.append(f"{labels[key]} {want} と {got}")
    return reasons


async def check_compatible(sources: dict, *, event: str = "concat.incompatible") -> dict:
    """全素材のparameterを取り、1つでも食い違えば連結せずに失敗させる。

    ``sources`` は {Path: source} の並び。先頭を基準にする。戻り値は基準のparameter。"""
    infos = {}
    for src, source in sources.items():
        infos[src] = await probe_stream_params(source)
    first_src = next(iter(sources))
    first = infos[first_src]
    codec = first["video"]["codec_name"]
    if codec not in ANNEXB_FILTERS:
        raise RuntimeError(f"連結に対応していない映像codecです: {codec}")
    for src in list(sources)[1:]:
        reasons = mismatch_reasons(first, infos[src])
        if not reasons:
            continue
        logger.warning(
            "連結する素材の形式が揃っていません: %s と %s", first_src.name, src.name,
            extra={"event": event,
                   "ctx": {"first": str(first_src), "other": str(src),
                           "first_params": first, "other_params": infos[src],
                           "reasons": reasons}},
        )
        raise RuntimeError(
            f"素材の形式が揃っていないため連結できません（{first_src.name} と {src.name}: "
            f"{ '、'.join(reasons) }）。同じ形式の録画だけを選ぶか、先に再mp4化してください。"
        )
    return first


class Span(NamedTuple):
    """1 streamの実測span。時刻はそのfile自身の軸。"""

    first: float
    last: float
    frame: float
    packets: int

    @property
    def end(self) -> float:
        """最後のpacketが提示し終わる時刻。"""
        return self.last + self.frame


class CutPart(NamedTuple):
    """切り出した中間file1つと、その実測値。

    ``inpoint``/``outpoint`` は :func:`concat_parts` が連結時に両streamを揃えるための窓で、
    どちらもこのfile自身の軸(=入力のcontainer軸)。``seconds`` はその窓の長さなので、連結後の
    尺の期待値はこれの合計になる。"""

    path: Path
    video: Span
    audio: Span
    inpoint: float
    outpoint: float
    media_start: float
    lead_seconds: float

    @property
    def seconds(self) -> float:
        return self.outpoint - self.inpoint


async def stream_spans(path: Path, input_args=()) -> dict:
    """先頭video/audio streamのpacket時刻から実測spanを返す。

    container の ``duration`` を使わない。あれは**長い方のstream**の尺なので、audioだけが
    2秒手前から始まっているpartでも「11.5秒」と答え、A/Vの食い違いをそのまま隠す。

    ``pts`` が ``N/A`` のpacketはMPEG-TSでは正常に混ざる(実測で全packetの約2.4%)。位置を
    決められないpacketなので数えない — ``float()`` に渡して例外にすると、正常な素材を壊れて
    いると誤診する。

    1 packetの秒数は ``duration_time`` ではなく**実測ptsの差の中央値**を採る。可変frame rate
    の録画では ``duration_time`` が入らない packet があり、平均は欠落やgapに引きずられる。"""
    spans = {}
    for kind, selector in (("video", "v:0"), ("audio", "a:0")):
        text = await _probe(
            ["ffprobe", "-v", "error", *input_args, "-select_streams", selector,
             "-show_packets", "-show_entries", "packet=pts_time", "-of", "json", str(path)],
            path)
        times = sorted(
            float(row["pts_time"])
            for row in (json.loads(text).get("packets") or [])
            if row.get("pts_time") not in (None, "N/A"))
        if not times:
            spans[kind] = None
            continue
        deltas = [b - a for a, b in zip(times, times[1:])]
        spans[kind] = Span(times[0], times[-1], float(median(deltas)) if deltas else 0.0,
                           len(times))
    return spans


async def _aim_before(source, start: float, end: float, window: float):
    """``start`` を失わずに始めるための ``-ss`` の狙点(media軸)と、狙ったkeyframe。

    走査は ``[start - window, end]``。手前だけでは足りない: 通常入力の狙点は ``k`` と**次の**
    keyframeの中点なので、``k`` の後ろも要る。範囲の中に次のkeyframeが無ければ、範囲の終端を
    境界として使う(``keyframes.exact_target`` の言う「``k`` より後ろで、間にkeyframeが無いと
    分かっている時刻」)。

    HLS入力で ``k`` が素材の最初のkeyframeなら、その半分を狙う。手前のkeyframeが無いので
    中点が取れず、``k`` ちょうどを渡すと丸めで1 GOP飛ぶ恐れがある。"""
    at = max(0.0, start - window)
    keys = await keyframes.video_keyframes(source, at, max(end - at, start - at + 1e-3))
    before = [k for k in keys if float(k) <= start]
    if not before:
        raise keyframes.NoKeyframes(
            f"要求開始の手前{window:.0f}秒にkeyframeが1つもありませんでした"
            f"（{Path(source.path).name} {start:.1f}秒）。走査窓を広げてください。")
    k = before[-1]
    k_prev = before[-2] if len(before) > 1 else None
    if getattr(source, "is_hls", False):
        if k_prev is None:
            return float(k) / 2, k
        return float(keyframes.seek_target(k, k_prev, None, True)), k
    k_next = next((key for key in keys if key > k), None)
    return float(keyframes.exact_target(k, k_next if k_next is not None else end)), k


def _inpoint_for(video: Span, audio: Span, back: int = 0) -> float:
    """連結時に両streamを揃える窓の始点。**audio packetの境界ちょうど**で、video先頭の手前。

    **境界ちょうどに置くこと。** 境界の途中(video先頭から半packet手前など)に置くと、成果物の
    **音が映像より約75ms先行する**。置く位置を1msから21msまで変えても75msは動かず、
    ``+genpts`` の有無でも動かない。packet境界に置いた版だけがずれを**17ms**へ落とした。
    境界の途中を渡すと、そこから始まらないaudio packetが窓の始点へ寄せられ、そのぶん音が
    早く鳴るためと見られる。

    **余裕は最小に留めること。** video先頭との差(=残るaudioの前置き)がそのまま残存ずれの
    上限になる。実測でも余裕20〜25msの版が最も小さかった。

    ただし際に置くとvideo先頭のkeyframeが落ちる。GOPが1つしか入らないpartでは、それは
    **映像streamが丸ごと消える**ことを意味する(合成素材で実測: frame 33ms・余裕15msで映像
    0 packet、余裕40msで182 packet)。閾値は素材で動くので**最小から始めて、出力に映像が
    無ければ ``back`` を増やして1 packetずつ下げる**(:func:`concat_parts`)。推測した固定の
    余裕で済ませると、素材によって黙って映像を失う。

    audioがvideoより後ろから始まる素材(落とす前置きが無い)では、keyframeを残す位置だけ確保する。
    """
    step = audio.frame if audio.frame > 0 else video.frame
    if step <= 0:
        raise RuntimeError("packet間隔を測れなかったため連結の窓を決められません。")
    if audio.frame <= 0 or audio.first >= video.first:
        return video.first - step * (back + 1)
    steps = math.ceil((video.first - audio.first) / audio.frame) - 1 - back
    return audio.first + max(0, steps) * audio.frame


async def cut_part(source, start: float, end: float, dst: Path, codec: str,
                   *, event: str = "concat.cut_failed",
                   message: Optional[str] = None) -> CutPart:
    """[``start`` 以前の最後のkeyframe, ``end``)をTSの中間fileへ複製する。

    ``start`` / ``end`` はどちらもmedia軸(0始まり)で受ける。**同じcommandの中で ``-ss`` と
    ``-to`` の軸が違う**ので、``-to`` にだけ container start_time を足し戻す:

    - ``-ss`` は **media軸**。ffmpegがcontainer start_timeを足して解釈する
    - ``-to`` は **container軸**(``-copyts`` 下)。media軸の値をそのまま渡すと、末尾が
      container start_time ぶん早く切れる

    実測(実録画・HLS入力、container start_time 1.43秒): media軸で 100→110 を要求して
    ``-to 110`` を渡すと、内容は media 98.6〜**108.7** で終わり、要求した末尾1.43秒が落ちる。
    ``-to 111.43`` を渡すと media 110.2 まで入る。

    この非対称は ``-muxdelay 0 -muxpreload 0`` を付けずに測ると見えない: mpegts muxerが
    既定で約1.4秒のinitial offsetを足すため、偶然ちょうど打ち消して「media軸だ」と読める。
    その ``-muxdelay 0 -muxpreload 0`` は**常に付ける**: 中間fileの軸を入力のcontainer軸へ
    揃えておかないと、``inpoint`` に渡す実測値が1.4秒ずれる。

    ``-ss`` へ要求時刻をそのまま渡さない理由と、audioの前置きを連結時に落とす理由はmodule
    docstringにある。着地は毎回検証し、要求より後ろへ着いたら**失敗させる** — 黙って通すと
    要求した場面の頭が欠けた出力を、要求どおりだと思って受け取ることになる。
    """
    src = source.path
    media_offset = float(getattr(source, "media_offset", 0.0) or 0.0)
    # container軸へ直す。HLSのsegmentは0始まりではない(実測1.4秒級)。mp4入力では0なので無害。
    to_container = float(end) + media_offset
    aim, k = await _aim_before(source, float(start), float(end),
                               float(config.get_clip_keyframe_scan_seconds()))
    ctx = {"src": str(src), "start": start, "end": end, "to_container": to_container,
           "media_offset": media_offset, "aim_seconds": round(aim, 3),
           "keyframe_seconds": round(float(k), 3), "output": str(dst)}
    await run(
        ["ffmpeg", "-v", "error", "-y",
         "-ss", f"{aim:.3f}", *source.input_args, "-i", str(src),
         "-to", f"{to_container:.3f}", "-copyts",
         "-c", "copy", "-bsf:v", ANNEXB_FILTERS[codec], *MUX_NO_OFFSET,
         "-f", "mpegts", str(dst)],
        event, ctx,
        message or f"切り出しに失敗しました（{src.name} {start:.1f}-{end:.1f}秒）",
    )
    spans = await stream_spans(dst)
    video, audio = spans["video"], spans["audio"]
    if video is None or audio is None:
        raise RuntimeError(
            f"切り出した中間fileに{'映像' if video is None else '音声'}が入りませんでした"
            f"（{src.name} {start:.1f}-{end:.1f}秒）。")
    media_start = video.first - media_offset
    if media_start > float(start) + video.frame:
        logger.error(
            "切り出しが要求した開始位置より後ろに着地し内容が失われました",
            extra={"event": "concat.cut_landed_late",
                   "ctx": {**ctx, "landed_seconds": round(media_start, 3),
                           "frame_seconds": round(video.frame, 6),
                           "video_packets": video.packets}},
        )
        raise RuntimeError(
            f"切り出しが要求より後ろから始まりました（要求 {start:.3f}秒 / 実際 "
            f"{media_start:.3f}秒）。この範囲は要求どおりには切り出せません。")
    inpoint = _inpoint_for(video, audio)
    outpoint = min(video.end, audio.end)
    if outpoint <= inpoint:
        raise RuntimeError(
            f"切り出した中間fileに映像と音声の重なりがありません（{src.name} "
            f"{start:.1f}-{end:.1f}秒）。")
    return CutPart(dst, video, audio, inpoint, outpoint, media_start,
                   round(max(0.0, float(start) - media_start), 3))


def _concat_line(item) -> str:
    """concat demuxerのfile行(必要なら ``inpoint``/``outpoint`` 付き)。

    ``CutPart`` を渡すと窓を書き、``Path`` を渡すとfile全体を使う。smart cutは自分で作った
    head/tailを繋ぐだけで揃える窓が無いので、後者で呼ぶ。"""
    path = item.path if isinstance(item, CutPart) else Path(item)
    # file行はsingle quoteで囲まれるので、path中のquoteは閉じ扱いになる。中間fileの名前は
    # 呼び出し側が付ける part0000.ts 形式なので、実際には現れない。
    line = f"file '{path.as_posix()}'\n"
    if isinstance(item, CutPart):
        line += f"inpoint {item.inpoint:.6f}\noutpoint {item.outpoint:.6f}\n"
    return line


async def video_codec(source) -> str:
    """先頭video streamのcodec名。Annex Bのbitstream filterを選ぶためだけに使う。

    :func:`probe_stream_params` は解像度の全種類を採るため録画1本のkeyframeを全走査する。
    codec名1つが要るだけの場所でそれを払わない。"""
    text = await _probe(
        ["ffprobe", "-v", "error", *source.input_args, "-select_streams", "v:0",
         "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(source.path)],
        source.path)
    codec = text.strip().splitlines()[0].strip() if text.strip() else ""
    if not codec:
        raise RuntimeError(f"映像codecを読めませんでした: {Path(source.path).name}")
    return codec


async def concat_parts(parts: list, out: Path, list_path: Path, *,
                       output_args=("-c", "copy"),
                       event: str = "concat.failed",
                       message: str = "連結に失敗しました") -> None:
    """中間fileを1本のmp4へ連結する。``parts`` は :class:`CutPart` かPathの並び。

    ``CutPart`` の窓(``inpoint``/``outpoint``)は、partの先頭に付いたaudioだけの区間を落として
    videoと同じ範囲へ揃えるためのもの。これを渡さないと、concat demuxerが次のfileへ与える
    offsetがfile全体の尺(=長い方=audio)で決まるため、接合ごとにvideoへ穴が空く。

    ``output_args`` は既定でstream copy。音声だけを再encodeする経路(切り出しの音量正規化)は
    ここへ ``-c:v copy -c:a ...`` を渡す — 切り出しは1 partなので、この段が唯一のmux段になる。"""
    ctx = {"output": str(out), "parts": len(parts), "output_args": list(output_args)}
    attempt = parts
    for back in range(WIDEN_ATTEMPTS + 1):
        list_path.write_text("".join(_concat_line(item) for item in attempt),
                             encoding="utf-8")
        # +genptsは中間fileの絶対timestamp(copyts由来)を連結側で振り直させる。
        await run(
            ["ffmpeg", "-v", "error", "-y", "-fflags", "+genpts",
             "-f", "concat", "-safe", "0", "-i", str(list_path),
             *output_args, "-movflags", "+faststart", str(out)],
            event, {**ctx, "inpoint_back": back}, message,
        )
        missing = await _missing_streams(out)
        if not missing:
            return
        widened = [item._replace(inpoint=_inpoint_for(item.video, item.audio, back + 1))
                   if isinstance(item, CutPart) else item for item in attempt]
        if back == WIDEN_ATTEMPTS or widened == attempt:
            logger.error(
                "連結後の出力にstreamが入っていません: %s", out.name,
                extra={"event": event, "ctx": {**ctx, "missing": missing,
                                               "inpoint_back": back}},
            )
            raise RuntimeError(
                f"連結後の出力に{'と'.join(missing)}が入りませんでした（{out.name}）。")
        logger.warning(
            "連結で先頭のkeyframeが落ちたため範囲を音声packet 1個分だけ前へ広げます",
            extra={"event": "concat.inpoint_widened",
                   "ctx": {**ctx, "missing": missing, "inpoint_back": back + 1}},
        )
        attempt = widened


async def _missing_streams(out: Path) -> list:
    """出力に入らなかったstreamの日本語名。両方在れば空。

    ``inpoint`` が際どいとconcat demuxerは先頭のkeyframeを落とし、GOPが1つしか入らないpartでは
    **映像streamが出力から丸ごと消える**(合成素材で実測)。ffmpegはこれをerrorにしないので、
    確かめない限り「音だけのmp4」が成功として渡る。"""
    text = await _probe(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
         "-of", "csv=p=0", str(out)], out)
    kinds = {line.strip() for line in text.splitlines() if line.strip()}
    return [label for kind, label in (("video", "映像"), ("audio", "音声"))
            if kind not in kinds]
