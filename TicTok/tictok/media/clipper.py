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

== smart cut(``smart=True``) ==

「要求どおりのIN点」と「原本画質」は、既定のstream copyでは両立しない。smart cutは
**先頭の1 GOPだけを再encodeし、残りは原本のpacketをそのまま複製して連結する**。3時間の録画から
10分を切っても再encodeするのは最初の数秒だけなので、実時間はcopyに近く、失われる画質は
先頭GOPに限られる。方式と実測の根拠は :mod:`tictok.media.concat`(TS中間・引数順・連結可否の
照合)と :mod:`tictok.media.keyframes`(keyframe走査・狙点・着地検証)にある。

判断の要点:

- **codecは原本のprobe結果から決める。** ``config.get_normalize_codec()`` は使えない — 既定が
  av1で、head=AV1 / tail=H.264 になり接合が必ず壊れる。``video_encoder_name`` は要求codecが
  出せないと黙ってlibx264へ落ちるので、返ってきたencoderのcodec familyを照合して**継承しない**。
  profile/level/pix_fmtも原本へ合わせ、最後に ``concat.check_compatible`` で照合して、
  合っていなければ連結せず失敗させる
- **headに ``-noaccurate_seek`` は付けない。** headはvideo/audio両方を復号するので、上に書いた
  非対称(video=keyframeから / audio=要求位置から)は起きない。既定のaccurate seekが要求位置
  ちょうどから始めてくれる
- **headの音声はcopyではなくAACへ再encodeし、``-ar``/``-ac`` を原本に合わせる。** GOP途中から
  copyできる音声packetは無く、rate/channelが原本と違えば連結の照合で落ちる
- **音量正規化はこの経路に足さない。** 別途の実測で、切り出し段のA/V不揃い(各partで音声が
  映像より103〜384ms短い)が未解決だと分かっている。それを直す前に正規化を足すと、原因の切り
  分けができなくなる
- **着地は必ず実測して検証する。** HLS入力は任意時刻に対し12%の確率で要求より後ろの
  keyframeへ着地し、内容を最大1.789秒失う(実録画の密sweep)。しかも失敗は
  ``Output file is empty`` の0 byte fileで終わることがあり、終了コードには出ない。tailの先頭
  ptsを ``keyframes.first_packet`` で測り、狙ったkeyframeと1 frame以内で一致しなければ
  **RuntimeErrorで失敗させる**(copyへ黙って倒すと、利用者は要求どおりのIN点だと思って
  内容の欠けた出力を受け取る)
- **中間fileは出力と同じdirに置く。** 別volumeのtempに置くと、原本と同容量級の中間が
  system driveを食う

軸の扱いが入口で違う点だけ注意する(いずれも実測):

- ``-ss`` はffmpegがcontainer start_timeを足すので、**media軸の秒をそのまま渡す**
- ``-to`` は ``-copyts`` 下では出力packetのtimestamp(=container軸)と比べられるので、
  **``media_offset`` を足して渡す**。足さないとその分だけ尾が短くなる(実測1.4667秒)
- tailの尾は ``-to`` の指定より2 frameほど伸びる(B-frameの並べ替え待ちぶん、実測0.067秒)。
  IN点は正確でもOUT点はstream copyの粒度に留まる
"""

import asyncio
import logging
import re
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from tictok.core import cancel, config, layout
from tictok.media import concat, hls_source, keyframes
from tictok.record import audio_norm
from tictok.record.video_overlay import (
    _encoder_args,
    _encoder_family,
    _mapped_quality,
    _duration_seconds,
    ffmpeg_available,
    video_encoder_name,
)

logger = logging.getLogger(__name__)

# file名に使えない文字と制御文字だけを落とす。検索語をそのままlabelにするため、
# 日本語を落とすと(検索語はほぼ日本語なので)labelが常に空になり用を成さない。
_UNSAFE_LABEL_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')

# ffprobeが出すprofile名 -> ffmpegの ``-profile:v`` が受け取る綴り。原本と同じprofileでheadを
# 焼かないと連結の照合で落ちる(mp4のavcCは先頭fileのものが1つだけ書かれるため、食い違えば
# 後半が復号できない)。表に無い綴りは推測せず失敗させる。
PROFILE_ARGS = {
    "h264": {"baseline": "baseline", "constrained baseline": "baseline",
             "main": "main", "high": "high", "high 10": "high10",
             "high 4:2:2": "high422", "high 4:4:4 predictive": "high444"},
    "hevc": {"main": "main", "main 10": "main10", "rext": "rext"},
}


def _hhmmss(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    h, rest = divmod(int(seconds), 3600)
    m, s = divmod(rest, 60)
    return f"{h:02d}{m:02d}{s:02d}"


def clip_path(src: Path, start: float, end: float, label: Optional[str] = None,
              suffix: str = "") -> Path:
    """出力path。同じ範囲・同じ版で作り直すと同じfileを上書きする。

    ``suffix`` は版の印(``overlay`` なら ``....overlay.mp4``)。全尺の焼き込み出力と同じ
    語彙を使うので、file名だけで中身の素性が分かる。既定は空で従来と同名。
    """
    streamer = layout.streamer_of(src.stem)
    target_dir = layout.clips_dir(layout.record_root_of(src), streamer)
    name = f"{src.stem}_{_hhmmss(start)}-{_hhmmss(end)}"
    if label:
        safe = _UNSAFE_LABEL_RE.sub("_", label).strip(" ._")[:40]
        if safe:
            name = f"{name}_{safe}"
    if suffix:
        name = f"{name}.{suffix}"
    return target_dir / f"{name}.mp4"


def _profile_arg(codec: str, profile) -> str:
    """原本のprofile名を ``-profile:v`` の綴りへ直す。表に無ければ推測せず失敗させる。"""
    name = (PROFILE_ARGS.get(codec) or {}).get(str(profile or "").strip().lower())
    if not name:
        raise RuntimeError(
            f"原本のprofile（{profile}）に合わせられないため、この録画はsmart cutできません。")
    return name


async def _smart_encoder(codec: str) -> str:
    """原本のcodecを出せるencoder。``video_encoder_name`` のlibx264 fallbackは継承しない。

    あちらは要求codecが出せないとき黙ってlibx264を返す。それをheadに使うと
    head=H.264 / tail=原本codec の組み合わせになり、連結の照合で落ちる(落ちなければ
    再生できないfileが出る)。ここで先に止めて、encodeの時間を捨てずに済ませる。"""
    encoder = await video_encoder_name(codec)
    if _encoder_family(encoder) != codec:
        raise RuntimeError(
            f"原本のcodec（{codec}）を出せるencoderがこの環境にありません"
            f"（{encoder}が選ばれました）。smart cutは原本と同じcodecでしか繋げません。")
    return encoder


def _head_args(source, params: dict, start: float, until: float, dst: Path,
               encoder: str, quality: int) -> list:
    """先頭GOPを再encodeしてTS中間へ書くffmpeg command。

    ``-ss``/``-t`` は入力側に置く。``-t`` を出力側に置くと ``-copyts`` 経路で空出力になる実測が
    あり(doc/CLIP_TIMEBASE.md §2)、入力側の方が音声の尺も厳密だった。``-noaccurate_seek`` は
    **付けない** — headは両streamを復号するので、既定のaccurate seekが要求位置ちょうどから
    始めてくれる。"""
    video, audio = params["video"], params["audio"]
    codec = video["codec_name"]
    args = ["ffmpeg", "-v", "error", "-y",
            "-ss", f"{start:.3f}", "-t", f"{until - start:.3f}",
            *source.input_args, "-i", str(source.path),
            *_encoder_args(encoder, quality)]
    if video.get("pix_fmt"):
        args += ["-pix_fmt", video["pix_fmt"]]
    args += ["-profile:v", _profile_arg(codec, video.get("profile"))]
    # levelはH.264だけ原本の値をそのまま渡せる(ffprobeの13=level 1.3がそのままlevel_idc)。
    # HEVCのgeneral_level_idcは30倍の別scaleなので、合わせずに照合へ任せる。
    if codec == "h264" and video.get("level"):
        args += ["-level", str(video["level"])]
    args += ["-c:a", "aac"]
    if audio.get("sample_rate"):
        args += ["-ar", str(audio["sample_rate"])]
    if audio.get("channels"):
        args += ["-ac", str(audio["channels"])]
    return args + ["-muxdelay", "0", "-muxpreload", "0", "-f", "mpegts", str(dst)]


def _tail_args(source, aim: float, end: float, dst: Path, codec: str) -> list:
    """接合点以降を原本のままTS中間へ複製するffmpeg command。

    ``-ss`` はmedia軸の秒をそのまま渡す(ffmpegがcontainer start_timeを足す)。``-to`` は
    ``-copyts`` 下でcontainer軸のtimestampと比べられるので ``media_offset`` を足す。
    ``-muxdelay 0 -muxpreload 0`` はmpegts muxerが既定で乗せる約1.4秒のinitial offsetを外す
    ためで、これが乗ったままだと着地の実測値を読み違える(いずれも実測)。"""
    return ["ffmpeg", "-v", "error", "-y",
            "-ss", f"{aim:.3f}", *source.input_args, "-i", str(source.path),
            "-to", f"{end + source.media_offset:.3f}", "-copyts",
            "-c", "copy", "-bsf:v", concat.ANNEXB_FILTERS[codec],
            "-muxdelay", "0", "-muxpreload", "0", "-f", "mpegts", str(dst)]


def _next_boundary(keys: list, k, end: float):
    """``k`` の次のkeyframe。範囲の終端までに無ければ ``end``。

    ``end`` で代用してよいのは、走査窓が ``[start, end)`` そのもので「``k`` と ``end`` の間に
    keyframeが無い」と分かっているときだけである。"""
    for key in keys:
        if key > k:
            return key if float(key) < end else end
    return end


def _smart_plan(keys: list, start: float, end: float, frame: float) -> tuple:
    """``(接合するkeyframe, その次の境界, 縮退の種類)``。

    縮退は失敗ではない。``single_gop`` は範囲が1 GOPに収まる場合で、全体を再encodeする以外に
    要求どおりのIN点にできない。``start_on_keyframe`` は要求INが既にkeyframe上(差が1 frame
    未満)で、再encodeするheadが1 frameも作れない場合。どちらも報告した上で実行する。"""
    k = keyframes.first_at_or_after(keys, start)
    if k is None or float(k) >= end:
        return None, None, "single_gop"
    boundary = _next_boundary(keys, k, end)
    if float(k) - start < frame:
        return k, boundary, "start_on_keyframe"
    return k, boundary, None


async def _verify_has_video(part: Path, ctx: dict) -> None:
    """partの先頭にkeyframeのvideo packetが在ることだけを確かめる。

    ここで**時刻は見ない**。再encodeしたheadの先頭ptsは0ではなく、B-frameの並べ替え待ちぶん
    後ろにずれる(実測0.100秒=3 frame)。muxerが負のDTSを避けるために全体をずらすためで、
    異常ではない。headの開始位置はaccurate seekが保証し、尺の齟齬は出力全体の尺の照合に出る。

    見ているのは中身の有無である。0 byte出力は ``Output file is empty`` で終わり、ffmpegの
    終了コードには出ない(実測)。"""
    pts, is_key = await keyframes.first_packet(part)
    if pts is None or not is_key:
        logger.error(
            "smart cutの中間fileの先頭に映像keyframeがありません", extra={
                "event": "clip.smart_part_empty",
                "ctx": {**ctx, "first_pts": None if pts is None else float(pts),
                        "first_packet_is_keyframe": is_key}},
        )
        raise RuntimeError(
            f"切り出しの中間fileに映像が入りませんでした（{part.name}）。")


async def _verify_landing(part: Path, expected: float, media_offset: float,
                          frame: float, ctx: dict) -> float:
    """tailが本当に ``expected`` から始まっているかを実測し、違えば失敗させる。

    HLS入力は任意時刻に対し12%の確率で要求より後ろのkeyframeへ着地し、内容を最大1.789秒失う
    (実録画の密sweep)。さらに ``Output file is empty`` で0 byte fileが残る場合があり、
    ffmpegの終了コードには出ない。**copyへ倒さずここで失敗させる**: 黙って倒すと、利用者は
    要求どおりのIN点だと思って内容の欠けた出力を受け取る。"""
    pts, is_key = await keyframes.first_packet(part)
    landed = None if pts is None else float(pts) - media_offset
    if landed is None or not is_key or abs(landed - expected) > frame:
        logger.error(
            "smart cutが意図したkeyframeに着地しませんでした", extra={
                "event": "clip.smart_landing_mismatch",
                "ctx": {**ctx, "expected_seconds": round(expected, 3),
                        "landed_seconds": None if landed is None else round(landed, 3),
                        "first_packet_is_keyframe": is_key,
                        "frame_seconds": round(frame, 6)}},
        )
        if landed is None:
            raise RuntimeError(
                "切り出しの尾側に映像が1 packetも入りませんでした"
                f"（{expected:.3f}秒から複製する予定でした）。")
        raise RuntimeError(
            f"切り出しの尾側が狙った位置から始まりませんでした（要求 {expected:.3f}秒 / "
            f"実際 {landed:.3f}秒、差 {landed - expected:+.3f}秒）。"
            "この範囲は要求どおりのIN点では切り出せません。"
        )
    return landed


async def _copy_clip(source, start: float, end: float, out: Path, output_args) -> object:
    """再encodeせずに ``[start, end)`` を出す。TS中間を1つ経由する2段。

    1段で ``-ss start -i src -to end -copyts -c copy`` と書くと、実録画(HLS)では
    **映像が要求の直後のkeyframeから始まり、音声は手前のsegment境界から始まる**。実測では
    要求30秒の切り出しが「先頭1.99秒は音声だけ(映像なし)」で出て、要求した頭0.7秒ぶんの映像を
    失っていた。しかも尺は要求どおりに見えるので ``keyframe_lead_seconds`` は0と報告される。

    :func:`tictok.media.concat.cut_part` は狙点を要求以前のkeyframeへ寄せて着地を検証し、
    :func:`tictok.media.concat.concat_parts` の窓が音声だけの区間を落とす。1 partしか無いので
    「連結」は実質的に窓を効かせるためのmux段で、その段が唯一のmuxになる — 音量を正規化する
    ときはここで音声を焼く。

    中間fileは出力とほぼ同容量になるので、出力先と同じvolumeへ置く。"""
    codec = await concat.video_codec(source)
    if codec not in concat.ANNEXB_FILTERS:
        raise RuntimeError(f"切り出しに対応していない映像codecです: {codec}")
    work = Path(tempfile.mkdtemp(prefix=".clip_", dir=out.parent))
    try:
        cut = await concat.cut_part(
            source, start, end, work / "part0000.ts", codec,
            event="clip.cut_failed",
            message=f"切り出しに失敗しました（{Path(source.path).name} "
                    f"{start:.1f}-{end:.1f}秒）")
        await concat.concat_parts(
            [cut], out, work / "parts.txt", output_args=tuple(output_args),
            event="clip.remux_failed", message="切り出しのmuxに失敗しました")
    except BaseException:
        out.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if not out.is_file():
        raise RuntimeError("切り出しは成功しましたが出力fileがありません。")
    return cut


async def _smart_clip(src: Path, start: float, end: float, out: Path) -> dict:
    """先頭GOPだけを再encodeし、残りを原本のまま複製して1本へ繋ぐ。"""
    duration = end - start
    with hls_source.ffmpeg_source(src) as source:
        params = await concat.probe_stream_params(source)
        codec = params["video"]["codec_name"]
        if codec not in concat.ANNEXB_FILTERS:
            raise RuntimeError(f"smart cutに対応していない映像codecです: {codec}")
        audio_codec = params["audio"]["codec_name"]
        if audio_codec != "aac":
            raise RuntimeError(
                f"音声がAACでない録画（{audio_codec}）はsmart cutできません。"
                "headの音声はAACで焼くため、原本と繋がりません。")
        frame = float(await keyframes.avg_frame_seconds(source))
        # 走査窓は切り出す範囲そのもの。接合点(startの直後のkeyframe)とその次の境界は必ず
        # この中にあり、無ければ「範囲が1 GOPに収まる」ことが確定する。
        try:
            keys = await keyframes.video_keyframes(source, start, duration)
        except keyframes.NoKeyframes:
            keys = []
        k, boundary, degenerate = _smart_plan(keys, start, end, frame)
        base = {"src": str(src), "output": str(out), "start": start, "end": end,
                "degenerate": degenerate}

        work = Path(tempfile.mkdtemp(prefix=".smartcut-", dir=out.parent))
        head = work / "part0.ts"
        tail = work / "part1.ts"
        encoder = "copy"
        landed = None
        try:
            # tailを先に切って着地を検めるのは、駄目な範囲にencodeの時間を払わないため。
            if k is not None:
                aim = float(keyframes.exact_target(k, boundary))
                await concat.run(
                    _tail_args(source, aim, end, tail, codec),
                    "clip.smart_tail_failed",
                    {**base, "keyframe_seconds": float(k), "seek_target_seconds": aim},
                    f"切り出し（尾側）に失敗しました（{src.name}）",
                )
                landed = await _verify_landing(
                    tail, float(k), source.media_offset, frame,
                    {**base, "seek_target_seconds": aim, "part": str(tail)})
            if degenerate != "start_on_keyframe":
                until = end if k is None else float(k)
                encoder = await _smart_encoder(codec)
                quality = _mapped_quality(encoder, config.get_normalize_quality())
                await concat.run(
                    _head_args(source, params, start, until, head, encoder, quality),
                    "clip.smart_head_failed",
                    {**base, "until": until, "encoder": encoder, "quality": quality},
                    f"切り出し（先頭GOPの再encode）に失敗しました（{src.name}）",
                )
                await _verify_has_video(head, {**base, "part": str(head)})
            parts = [p for p, needed in ((head, degenerate != "start_on_keyframe"),
                                         (tail, k is not None)) if needed]
            if len(parts) > 1:
                await concat.check_compatible(
                    {p: hls_source.Source(p, (), False, 0.0) for p in parts},
                    event="clip.smart_incompatible")
            await concat.concat_parts(
                parts, out, work / "parts.txt", event="clip.smart_concat_failed",
                message=f"切り出しの連結に失敗しました（{src.name}）")
        except BaseException:
            out.unlink(missing_ok=True)
            raise
        finally:
            shutil.rmtree(work, ignore_errors=True)

    size = out.stat().st_size
    actual = await _duration_seconds(out)
    head_seconds = 0.0 if degenerate == "start_on_keyframe" else (
        duration if k is None else float(k) - start)
    info = {
        "path": str(out),
        "filename": out.name,
        "bytes": size,
        "start": start,
        "end": end,
        "mode": "smart",
        "precise": False,
        "encoder": encoder,
        "normalized": False,
        "output_duration_seconds": actual,
        # 先頭GOPを再encodeしているので前置きは無い。測って0であり、未測定のNoneとは違う。
        "keyframe_lead_seconds": 0.0,
        "actual_start_seconds": start,
        "degenerate": degenerate,
        "head_seconds": round(head_seconds, 3),
        # 接合点の原本上の時刻(media軸)。縮退single_gopでは接合そのものが無い。
        "join_seconds": None if k is None else round(float(k), 3),
        "copied_seconds": 0.0 if k is None else round(end - float(k), 3),
    }
    ctx = {**info, "landed_seconds": None if landed is None else round(landed, 3)}
    tolerance = config.get_clip_duration_tolerance_seconds()
    if actual is not None and abs(actual - duration) > tolerance:
        logger.warning(
            "smart cutの切り抜きの尺が要求と異なります: %s（要求 %.2fs, 出力 %.2fs）",
            out.name, duration, actual,
            extra={"event": "clip.duration_mismatch", "ctx": ctx},
        )
    logger.info(
        "切り抜きの書き出しが完了しました: %s（%.2f-%.2f, 先頭 %.2fs は %s で再encode, copy %.2fs）",
        out.name, start, end, info["head_seconds"], encoder, info["copied_seconds"],
        extra={"event": "clip.smart_exported", "ctx": ctx},
    )
    return info


async def make_clip(src: Path, start: float, end: float, label: Optional[str] = None,
                    precise: bool = False, normalize: Optional[dict] = None,
                    smart: bool = False) -> dict:
    """[start, end)をmp4へ切り出し、出力pathを返す。

    ``normalize`` に audio_norm.targets() を渡すと音声だけを再encodeして音量を揃える。
    映像は既定どおりstream copyのままなので、正規化しても切り出しの速さは変わらない。
    録画はHLS由来のVFRで、音声filterだけを足すと同期が崩れるため、audio_norm側で
    aresample=async=1を必ず前段に置いている。
    """
    if not ffmpeg_available():
        raise RuntimeError("ffmpegが見つかりません。切り出しにはffmpegのinstallが必要です。")
    duration = float(end) - float(start)
    if duration <= 0:
        raise RuntimeError("終了位置は開始位置より後にしてください。")

    out = clip_path(src, start, end, label)
    out.parent.mkdir(parents=True, exist_ok=True)

    if smart:
        # 併用は受け付けない。preciseは全編再encode(smartと目的が重複する)で、正規化は
        # 切り出し段のA/V不揃いが未解決のためこの経路に足せない(module docstring参照)。
        if precise:
            raise RuntimeError("smart cutとframe精度の再encodeは同時に指定できません。")
        if normalize:
            raise RuntimeError("smart cutでは音量の正規化を行えません。")
        return await _smart_clip(src, float(start), float(end), out)

    # mp4が無い録画は.tsのHLSから切る。切り出しはstream copyなので、どちらを読んでも
    # 出てくるpacketは同じ(hls_source参照)。
    with hls_source.ffmpeg_source(src) as source:
        if normalize:
            # loudnormは192kHzを出すので、sourceの実rateを測って出力をそこへ戻す。
            rate = await asyncio.to_thread(audio_norm.probe_sample_rate, source.path)
            audio_args = audio_norm.encode_args(**normalize, sample_rate=rate)
        else:
            audio_args = ["-c:a", "aac"]
        # 正規化しないstream copyは従来どおり全streamをそのまま複製する(-c copy)。音声だけを
        # 差し替えるときだけ映像を名指しでcopyする。
        copy_args = (["-c:v", "copy", *audio_args] if normalize else ["-c", "copy"])
        read_args = [*source.input_args, "-i", str(source.path)]

        cut = None
        if precise:
            codec = config.get_normalize_codec()
            encoder = await video_encoder_name(codec)
            quality = _mapped_quality(encoder, config.get_normalize_quality())
            # -ssを-iの後ろに置くとdecodeしてから捨てるためframe精度で切れる。
            codec_args = ["-ss", f"{start:.3f}", "-t", f"{duration:.3f}"] \
                + _encoder_args(encoder, quality) + audio_args
            cmd = ["ffmpeg", "-v", "error", "-y", *read_args, *codec_args,
                   "-movflags", "+faststart", str(out)]
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
                    "%s の切り抜きの書き出しに失敗しました（%.2f-%.2f）", src.name, start, end,
                    extra={"event": "clip.failed",
                           "ctx": {"src": str(src), "start": start, "end": end,
                                   "precise": precise, "encoder": encoder,
                                   **audio_norm.describe(normalize),
                                   "returncode": proc.returncode,
                                   "stderr": message[:2000]}},
                )
                raise RuntimeError(f"切り出しに失敗しました: {message[:300]}")
        else:
            encoder = "copy"
            cut = await _copy_clip(source, float(start), float(end), out,
                                   copy_args if normalize else ("-c", "copy"))

    size = out.stat().st_size
    # 音声だけを再encodeする経路は、filterがsampleを詰めたり落としたりすると尺が動く。
    # 指定と実測が離れていないかを毎回測って記録する(判定不能なときは捏造せずNone)。
    actual = await _duration_seconds(out)
    # stream copyはkeyframeからしか始められないので、実際の内容は要求より手前から始まる。
    # 何秒手前かは**実測した着地**から出す。尺の差から逆算すると、audioだけが手前から入って
    # いるぶん(実測で約2秒)まで前置きに数え、内容を失った回は0と報告してしまう。
    lead = None if cut is None else cut.lead_seconds
    tolerance = config.get_clip_duration_tolerance_seconds()
    ctx = {"src": str(src), "output": str(out), "start": start, "end": end,
           "duration_seconds": duration, "output_duration_seconds": actual,
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
            "切り抜きの尺が要求と異なります: %s（要求 %.2fs, 出力 %.2fs）",
            out.name, duration, actual,
            extra={"event": "clip.duration_mismatch", "ctx": ctx},
        )
    logger.info(
        "切り抜きの書き出しが完了しました: %s（%.2f-%.2f, %s）", out.name, start, end, encoder,
        extra={"event": "clip.exported", "ctx": ctx},
    )
    return {
        "path": str(out),
        "filename": out.name,
        "bytes": size,
        "start": start,
        "end": end,
        "mode": "precise" if precise else "copy",
        "precise": precise,
        "encoder": encoder,
        "normalized": bool(normalize),
        "output_duration_seconds": actual,
        # 実際の内容開始。stream copyでは要求より手前のkeyframeになる(preciseでは要求どおり)。
        "keyframe_lead_seconds": None if lead is None else round(lead, 3),
        "actual_start_seconds": start if lead is None else round(start - lead, 3),
    }
