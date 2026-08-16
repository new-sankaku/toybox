"""グループ(切り抜きの棚)1件を、投稿できるmp4 1本にする。

既存には出口が2つあり、どちらも「複数シーンの完成品」にならなかった。:mod:`tictok.media.reel`
はNシーンを受けるがstream copyで繋ぐだけで仕上げを1つも通らず、:mod:`tictok.media.short` は
仕上げを全部持つが入口が1シーンしかない。ここはその2つを繋ぐ段である。

reelは残す。素材を通しで俯瞰するのに数秒で出ることがreelの価値で、仕上げを通せばその速さが
失われる。用途が違うので出口も別にする。

## 時刻軸が2つに割れる

演出をどの段へ置くかは好みではなく、**その要素が何の時刻を持っているか**で決まる。

* テロップ・コメント・ギフトは**原本の時刻**を持つ。シーンごとに元の録画も位置も違うので、
  連結してからまとめて焼くことはできない → シーンの段(:func:`tictok.media.short.cut_scene`)
* 転換・効果音・BGMは**連結して初めて存在する**。原本にその時刻は無い → 作品の段(この後)

副次的に、焼き込みのfilter graphへ演出を積まずに済む。既存の焼き込みは個人マルチの描画で
32KB上限に接触した実績があり、同じgraphへ足すと壊れる。

## 高画質化は作品全体へ1回だけ

:func:`tictok.media.short.make_short` はシーンごとにUp出力を掛ける。1シーンならそれで正しいが、
Nシーンで同じことをすると**GPU時間がシーン数倍**になる。Up出力は実時間の数倍かかる段なので、
ここでは連結の後に1回だけ掛ける。

## 中間はTS

連結はconcat demuxerのstream copyで、中間をmp4にするとNon-monotonic DTSが多発する
(:mod:`tictok.media.concat`)。シーンの成果物はmp4なので、繋ぐ前にTSへ**再多重化**する
(再encodeではないので画質も時間も失わない)。

シーンは全て自分で焼いた物なので、窓の始点は書かない(``keep_start=True``)。両streamが同じ
位置から始まり落とす前置きが無いためで、始点を詰めると先頭keyframeの際に来て逆にそれを落とす。

## 形式は揃っていることを確かめる

全シーンを同じencoder設定で焼くので、出来上がるpartの形式は揃っている**はず**である。だが
「はず」で繋ぐと、揃っていなかった回に後半が復号できないmp4が黙って出る(mp4のavcCは先頭
fileのものが1つだけ書かれる)。安いので毎回照合し、違えば明示的に失敗させる。

解像度が違うシーンを**揃えて**繋ぐ処理はまだ無い。入れるまでは、跨いだ録画の解像度が違う
グループはここで止まる。黙って片方へ寄せるより、止めて理由を名乗る方を採る。
"""

import asyncio
import hashlib
import json
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Callable, NamedTuple, Optional

from tictok.core import config, layout
from tictok.media import clip_gate, concat, hls_source, sfx, short
from tictok.media.clipper import _UNSAFE_LABEL_RE, _hhmmss
from tictok.record.upscale import UpscaleError, ensure_upscaled, upscale_output_path
from tictok.record.video_overlay import (
    codec_family,
    ffmpeg_available,
    video_encoder_name,
)

logger = logging.getLogger(__name__)

# シーンcacheの置き場(``_clips/<配信者>/`` の直下)。dot始まりなのは、成果物を並べる画面が
# ここを覗かないようにするため(:mod:`tictok.api.routes.clips` の ``CACHE_DIRS``)。
SCENE_CACHE_DIR = ".scenes"

# 進捗の配分。段ごとの実測costではなく「利用者が待つ体感の重さ」で割る。シーンの段が大半を
# 占めるのは、そこだけが**シーンの数だけ**再encodeを繰り返すためである。
_PCT_SCENES = 70
_PCT_CONCAT = 76
_PCT_UPSCALE = 96


class _PlainSource(NamedTuple):
    """自分で焼いたfileを :mod:`tictok.media.concat` の probe へ渡すための最小の口。

    HLSのcurated playlistを開く :mod:`tictok.media.hls_source` と同じ形(``path`` と
    ``input_args``)だけを持つ。中間partはただのfileなので、貸し出しも解放も要らない。
    """

    path: Path
    input_args: tuple = ()


def work_path(src: Path, start: float, end: float, count: int,
              label: Optional[str] = None) -> Path:
    """作品の出力path。置き場と名前の規約は切り出し・reelと同じ(``CLIP_OUTPUT.md``)。

    ``src`` は先頭シーンの録画。作品は複数の録画を跨げるが、置き場は1つに決めないといけない
    ので先頭に従う(reelと同じ決め方)。同じ並びで作り直すと同じfileを上書きする。
    """
    streamer = layout.streamer_of(src.stem)
    target_dir = layout.clip_output_dir(streamer)
    name = f"{src.stem}_work{count}_{_hhmmss(start)}-{_hhmmss(end)}"
    if label:
        safe = _UNSAFE_LABEL_RE.sub("_", label).strip(" ._")[:40]
        if safe:
            name = f"{name}_{safe}"
    return target_dir / f"{name}.work.mp4"


def sidecar_path(out: Path) -> Path:
    """題名・説明・検品結果を書くJSON。mp4と同じ名前で拡張子だけが違う。

    DBではなくfileにするのは、成果物と一緒に動かせるようにするためである(shortと同じ)。
    """
    return out.with_suffix(".json")


def scene_cache_dir(src: Path) -> Path:
    """シーンcacheの置き場。作品の出力先と同じvolume・同じ配信者dirの下に置く。

    成果物と同じ場所に置くのは、片方だけを別のdriveへ移せない(移すと次のcache判定が必ず
    外れる)ためと、容量の判定と実際に消費する場所を一致させるためである。出力先が一時保存先
    固定になったので、cacheもそこに留まる — 成果物が最終保存先へ移ってもcacheは付いていかない
    (移動の対象は成果物だけ)。焼き直しは常に一時保存先で走るため、それでcacheは当たり続ける。
    """
    streamer = layout.streamer_of(src.stem)
    return layout.clip_output_dir(streamer) / SCENE_CACHE_DIR


def _scene_stem(src: Path, start: float, end: float) -> str:
    """cache fileの名前。切り出しと同じ ``開始-終了`` の綴りで、実体がどの範囲か読める。"""
    return f"{src.stem}_{_hhmmss(start)}-{_hhmmss(end)}"


def _part_signature(cut: Path, preset: dict, codec: str) -> str:
    """出来上がったTS partが今の指定で作られた物かを判定する指紋。

    入力(=切り出し・焼き込みの出力)はsize+mtimeで見る。焼き込みは自前の署名cacheを持って
    いて(:func:`tictok.record.video_overlay._signature` — 設定・event・文字起こし・時刻mapまで
    見る30版ぶんの無効化知識がある)、その判断で焼き直されればfileが変わる。ここでその
    判断をもう一度組み立て直さないのは、2つの実装が必ず食い違うためである。
    """
    stat = cut.stat()
    payload = {
        "version": 1,
        "cut": [stat.st_size, stat.st_mtime_ns],
        "codec": codec,
        # 間の詰めはこの段で掛ける。設定が変われば同じ切り出しから別のpartが出る。
        "tighten": int(preset.get("tighten") or 0),
        "tighten_min_silence_seconds": float(preset.get("tighten_min_silence_seconds") or 0),
        "tighten_keep_seconds": float(preset.get("tighten_keep_seconds") or 0),
        "fps": config.get_short_fps(),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cut_signature(src: Path, start: float, end: float, codec: str) -> str:
    """焼き込みを通さない切り出し(precise)のcache指紋。

    焼き込み経路はこれを使わない — あちらは自前の署名cacheを持ち、設定・event・文字起こしまで
    見るので、ここで素材と範囲だけを見る指紋を重ねると**設定を変えても古い出力が返る**。
    """
    payload = {
        "version": 1,
        "source": hls_source.fingerprint(src, prefer_hls=True),
        "start": round(float(start), 3),
        "end": round(float(end), 3),
        "codec": codec,
        "quality": config.get_short_quality(),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _read_meta(meta: Path, artifact: Path, signature: str) -> Optional[dict]:
    """cacheが今の指定で作られた物なら、その時の記録を返す。違えば None。

    実体と署名の**両方**を見る。署名だけを見ると、fileを消した後でもcache hitと判定して
    存在しない物を繋ごうとする。記録まで持つのは、間の詰めで何秒落としたかが期待尺の計算に
    要るためで、cache hitのたびに測り直せない値だからである。
    """
    if not artifact.is_file():
        return None
    try:
        payload = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if payload.get("signature") == signature else None


def _write_meta(meta: Path, signature: str, **detail) -> None:
    meta.write_text(json.dumps({"signature": signature, **detail}, ensure_ascii=False),
                    encoding="utf-8")


def scene_cache_state(src: Path, start: float, end: float, preset: dict,
                      codec: str) -> dict:
    """このシーンの中間が既に在るか。**下見のための事実であって、予言ではない。**

    ``part_ready`` が真でも「焼き直さない」とは限らない。焼き込み経路のcache判定は
    :mod:`tictok.record.video_overlay` が持っており、設定・event・文字起こし・時刻mapのどれかが
    変わっていれば切り出しから焼き直される — それはこの関数からは分からない(判定を組み直せば
    必ず本物と食い違う)。名乗れるのは「前回作った中間が今も在る」までである。

    file名の綴りは書き出し側と同じ規約に従うので、``.scenes`` を開けばどのシーンの中間かが
    名前から読める。
    """
    cache_dir = scene_cache_dir(src)
    stem = _scene_stem(src, start, end)
    cut_out = cache_dir / f"{stem}.cut.mp4"
    part_out = cache_dir / f"{stem}.part.ts"
    state = {"cut_ready": cut_out.is_file(), "part_ready": False,
             "cache_bytes": 0}
    for path in (cut_out, part_out):
        if path.is_file():
            state["cache_bytes"] += path.stat().st_size
    if state["cut_ready"]:
        state["part_ready"] = _read_meta(
            cache_dir / f"{stem}.part.json", part_out,
            _part_signature(cut_out, preset, codec)) is not None
    return state


async def _to_ts(src: Path, dst: Path, codec: str) -> None:
    """出来上がったシーンのmp4を、連結できるTSへ再多重化する。再encodeはしない。

    ``-muxdelay 0 -muxpreload 0`` は必ず付ける。mpegts muxerは既定で約1.4秒のinitial offsetを
    乗せるため、これが無いと連結側が実測する時刻が1.4秒ずれる(:mod:`tictok.media.concat`)。
    """
    await concat.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(src),
         "-c", "copy", "-bsf:v", concat.ANNEXB_FILTERS[codec], *concat.MUX_NO_OFFSET,
         "-f", "mpegts", str(dst)],
        "work.remux_failed",
        {"src": str(src), "output": str(dst), "codec": codec},
        f"シーンを連結できる形へ直せませんでした（{src.name}）",
    )


async def _require_uniform(parts: list) -> None:
    """全partの形式が揃っていることを確かめる。1つでも違えば繋がずに失敗させる。

    全シーンを同じencoder設定で焼くので通常は揃っている。それでも毎回見るのは、揃っていな
    かった回に**後半が復号できないmp4**が黙って出るためである(avcCは先頭fileのものが1つだけ
    書かれる)。照合はstream headerの1組で足りる — partは自分で焼いた単一解像度のfileなので、
    録画全編のkeyframeを走査して解像度の種類を数える必要が無い。
    """
    infos = []
    for part in parts:
        infos.append(await concat.probe_codec_params(_PlainSource(part.path)))
    for index, info in enumerate(infos[1:], start=1):
        reasons = concat.mismatch_reasons(infos[0], info)
        if not reasons:
            continue
        logger.warning(
            "作品のシーンの形式が揃っていません: %s と %s",
            parts[0].path.name, parts[index].path.name,
            extra={"event": "work.incompatible",
                   "ctx": {"first": str(parts[0].path), "other": str(parts[index].path),
                           "first_params": infos[0], "other_params": info,
                           "scene": index, "reasons": reasons}},
        )
        raise RuntimeError(
            f"シーン{index + 1}の形式が他と揃っていないため繋げません（{'、'.join(reasons)}）。"
            "解像度の違う録画を跨いだグループはまだ作品にできません。"
        )


def _telop_times(item: dict, keeps, offset: float) -> list:
    """このシーンで字幕が出る時刻を、**作品の時刻軸**で返す。

    文字起こしsegmentの ``start`` はmedia軸(元録画のPTS秒)へ再map済みなので、シーンの頭を引けば
    そのまま切り出しの中の位置になる。詰めた区間へ落ちた行は写し先が無いので捨てる
    (:func:`tictok.media.sfx.remap_to_output` が None を返す)。

    文字起こしを持たない・字幕を焼かないシーンでは空。焼いていないのに音だけ鳴らすと、何に対する
    音なのかが画面から読めない。
    """
    overlay = item.get("overlay") or {}
    transcript = overlay.get("transcript") or {}
    start, end = float(item["start"]), float(item["end"])
    times = []
    for segment in transcript.get("segments") or []:
        at = segment.get("start")
        if at is None or not (start <= float(at) < end):
            continue
        local = sfx.remap_to_output(float(at) - start, keeps)
        if local is not None:
            times.append(offset + local)
    return times


async def _upscale(path: Path, codec: str) -> Path:
    encoder = await video_encoder_name(codec_family(short.codec_setting_value(codec)))

    def on_frames(done: float, total: float) -> None:
        # 同期callback。frame位置はUp出力側のlogが持つので、ここでは何もしない。
        return None

    return await asyncio.to_thread(
        ensure_upscaled, str(path), encoder, config.get_short_quality(), on_frames, None)


async def _scene_part(item: dict, preset: dict, label: Optional[str], codec: str,
                      workdir: Path, index: int, report) -> tuple:
    """1シーンを、連結にそのまま使えるTS partまで仕上げる。既に在れば作り直さない。

    **変わったシーンだけ焼き直せること**が要る。端を0.5秒直すたびに全シーンを焼き直す形
    だと、直すのを人がやめる。cacheの単位を作品ではなくシーンにするのはそのためである。

    焼き込み経路のcache判定は :func:`tictok.record.video_overlay.render_clip_overlay` に
    任せる。あちらは設定・event・文字起こし・時刻mapまで見る署名を持ち、そこに30版ぶんの無効化
    知識が積まれている。ここで組み直せば必ず食い違い、**設定を変えたのに古い絵が返る**という
    最も気付きにくい形で壊れる。ここが自分で判定するのは焼き込みを通さない切り出しだけ。
    """
    src, start, end = item["src"], item["start"], item["end"]
    cache_dir = scene_cache_dir(src)
    cache_dir.mkdir(parents=True, exist_ok=True)
    stem = _scene_stem(src, start, end)
    cut_out = cache_dir / f"{stem}.cut.mp4"
    cut_meta = cache_dir / f"{stem}.cut.json"
    part_out = cache_dir / f"{stem}.part.ts"
    part_meta = cache_dir / f"{stem}.part.json"

    if short.draws_anything(preset):
        # 焼き込みは自前のcacheを持つ。安定したpathを渡すだけで、変わっていなければ
        # 即座に返る(戻り値の ``cached`` がそれを名乗る)。
        cut = await short.cut_scene(src, cut_out, start, end, preset,
                                    item["label"] or label, item["overlay"], report)
    else:
        signature = _cut_signature(src, start, end, codec)
        hit = _read_meta(cut_meta, cut_out, signature)
        if hit is not None:
            cut = {"mode": "precise", "cached": True,
                   "keyframe_lead_seconds": hit.get("keyframe_lead_seconds")}
        else:
            cut = await short.cut_scene(src, cut_out, start, end, preset,
                                        item["label"] or label, None, report)
            _write_meta(cut_meta, signature,
                        keyframe_lead_seconds=cut.get("keyframe_lead_seconds"))

    signature = _part_signature(cut_out, preset, codec)
    hit = _read_meta(part_meta, part_out, signature)
    if hit is not None:
        tight = {"step": "tighten", "cached": True, "applied": hit.get("applied"),
                 "removed_seconds": hit.get("removed_seconds"), "cuts": hit.get("cuts"),
                 # 残した区間はcacheにも持つ。効果音の時刻をここから写すので、cache hitの
                 # 回にだけ写し替えができない、という形にはしない。
                 "keeps": hit.get("keeps") or []}
        return cut, tight, part_out

    # 詰めの中間は作品ごとの作業dirへ。これはcacheしない — 次に要るのはTSの方で、mp4を
    # 残しても同じ物を2つ持つだけになる。
    tight = await short.tighten_scene(cut_out, workdir / f"tight{index:04d}.mp4", preset)
    tightened = Path(tight.pop("path"))
    # 記録を先に落としてから、実体はtmp経由で置き換える。出力pathへ直接書くと、途中で
    # 落ちた回に**断片が正しいpartの顔をして残る**: 署名は前回成功時のまま在るので、指定を
    # 元へ戻した次の回に断片へcache hitして、切れたシーンを繋いだ作品が黙って出る。
    part_meta.unlink(missing_ok=True)
    tmp = part_out.with_name(part_out.name + ".tmp")
    try:
        await _to_ts(tightened, tmp, codec)
        tmp.replace(part_out)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    _write_meta(part_meta, signature, applied=tight["applied"],
                removed_seconds=tight["removed_seconds"], cuts=tight["cuts"],
                keeps=tight.get("keeps") or [])
    return cut, {**tight, "cached": False}, part_out


async def make_work(scenes: list, *, preset: dict, label: Optional[str] = None,
                    on_progress: Optional[Callable] = None) -> dict:
    """Nシーンを1本の作品にする。戻り値には検品の結果まで入る。

    ``scenes`` は ``{"src": Path, "start": 秒, "end": 秒, "label": 任意,
    "overlay": 焼き込みの材料 or None}`` の並び。**並べ替えはしない** — 呼び出し側が渡した
    順(グループの ``position``)がそのまま尺順になる。時刻順へ整えないのは、並びが人の意思
    そのものだからである。

    ``overlay`` はシーンごとに持つ。作品が複数の録画を跨ぐと、eventも文字起こしも録画ごとに違う
    ものになるためで、1つを使い回すと2本目以降のコメントが全く別の配信のものになる。

    検品に落ちても**例外にはしない**。落ちたことは戻り値の ``gate`` に入る。
    """
    if not ffmpeg_available():
        raise RuntimeError("ffmpegが見つかりません。作品の書き出しにはffmpegのinstallが必要です。")
    if not scenes:
        raise RuntimeError("作品にするシーンがありません。")
    codec = config.get_short_codec()
    if codec not in concat.ANNEXB_FILTERS:
        # AV1は繋げない。保存用の正規化(既定AV1)と投稿用のcodecを分けている理由がここで効く。
        raise RuntimeError(
            f"作品の連結に対応していない映像codecです: {codec}。"
            "TICTOK_SHORT_CODEC をh264かhevcにしてください。")

    items = []
    for index, scene in enumerate(scenes):
        src = Path(scene["src"])
        start, end = float(scene["start"]), float(scene["end"])
        if end <= start:
            raise RuntimeError(
                f"シーン{index + 1}の終了位置が開始位置より前です（{start:.1f}-{end:.1f}秒）。")
        items.append({"src": src, "start": start, "end": end,
                      "label": scene.get("label") or "",
                      "overlay": scene.get("overlay")})

    out = work_path(items[0]["src"], items[0]["start"], items[-1]["end"], len(items), label)
    out.parent.mkdir(parents=True, exist_ok=True)
    # 中間は出力と同じvolumeへ置く。容量の判定と実際に消費する場所を一致させるため
    # (reel / clipper / short と同じ決め方)。
    workdir = Path(tempfile.mkdtemp(prefix=".work_", dir=out.parent))
    total = len(items)
    steps: list = []

    async def report(stage: str, pct: int) -> None:
        if on_progress is not None:
            await on_progress(stage, pct)

    # 効果音は「置ける場所」しか使わない。テロップの音は**字幕を焼いたシーン**にしか
    # 置かない — 焼いていないのに音だけ鳴ると、何に対する音か画面から読めない。
    wants_sfx = bool(int(preset.get("sfx") or 0))
    assets = sfx.ensure_assets(("transition", "telop")) if wants_sfx else {}
    joints: list = []
    telop_times: list = []
    timeline = 0.0

    try:
        parts = []
        for index, item in enumerate(items):
            base = int(index * _PCT_SCENES / total)
            span = _PCT_SCENES / total

            async def scene_progress(stage: str, pct: int, _base=base, _span=span,
                                     _index=index) -> None:
                # 件数は括弧に入れる。段階名に混ぜるとシーンの数だけ別々の段階として
                # jobの履歴に並ぶ(media_queue.stage_phase が括弧の中を落とす)。
                await report(f"{stage}（{_index + 1} / {total}シーン）",
                             min(_PCT_SCENES, _base + int(pct * _span / 100)))

            cut, tight, part_path = await _scene_part(
                item, preset, label, codec, workdir, index, scene_progress)
            steps.append({"scene": index, "src": str(item["src"]),
                          "start": round(item["start"], 3), "end": round(item["end"], 3),
                          "cut": cut, "tighten": tight})
            # 自分で焼いたpartなので窓の始点は書かない(module docstring)。
            part = await concat.window_part(part_path, keep_start=True)
            parts.append(part)
            # 効果音を置く時刻は**作品の軸**でしか意味を持たない。partの実尺を積むことで
            # しかその軸は得られないので、ここで採る(要求した尺ではない — 間の詰めと
            # keyframe境界で実尺は要求と違う)。
            if wants_sfx:
                telop_times.extend(
                    _telop_times(item, tight.get("keeps") or [], timeline))
                if index:
                    joints.append(timeline)
            timeline += part.seconds

        await report("シーンを繋いでいます", _PCT_SCENES)
        await _require_uniform(parts)
        joined = workdir / "joined.mp4"
        await concat.concat_parts(
            parts, joined, workdir / "concat.txt",
            event="work.concat_failed", message="シーンの連結に失敗しました")
        current = joined

        if int(preset.get("upscale") or 0):
            await report("高画質化しています", _PCT_CONCAT)
            try:
                current = Path(await _upscale(current, codec))
            except UpscaleError as exc:
                raise RuntimeError(f"高画質化に失敗しました: {exc}") from exc
            steps.append({"step": "upscale", "path": str(current)})

        if wants_sfx:
            await report("効果音を入れています", _PCT_UPSCALE)
            # **最後に掛ける。** 高画質化の前に混ぜると、あちらのencodeで音がもう1世代
            # 重なる。映像は複製のままなので、この段の費用は音のencodeだけである。
            plan = sfx.plan_cues(joints=joints, telops=telop_times,
                                 duration=timeline)
            if plan["cues"]:
                mixed = workdir / "sfx.mp4"
                detail = await sfx.apply(current, mixed, plan["cues"], assets)
                current = mixed
                # 件数だけでなく**時刻**まで残す。件数は「置いたつもり」しか語らず、成果物を
                # 測って合っているかを後から確かめる手段が無くなる。
                steps.append({"step": "sfx", **detail, "dropped": plan["dropped"],
                              "at": [c["at"] for c in plan["cues"]]})
            else:
                # 置ける場所が1つも無い作品は在り得る(1シーン・字幕なし)。黙って通す。
                steps.append({"step": "sfx", "cues": 0, "counts": {},
                              "dropped": plan["dropped"]})

        await report("仕上げています", _PCT_UPSCALE)
        # 最終段の実体を出力名へ移す。同じvolume内なのでrenameで済む。
        current.replace(out)
        # Up出力は入力の隣へ ``.up.mp4`` を作る。中間dirごと消えるので残骸は出ないが、
        # 出力先に同名が居座っていた場合だけは片付ける(次回のcache判定が誤る)。
        stale = upscale_output_path(out)
        if stale.is_file() and stale != out:
            stale.unlink(missing_ok=True)
    except BaseException:
        out.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    requested = sum(item["end"] - item["start"] for item in items)
    # 期待尺は「範囲の合計 − 間の詰めで落とした合計」。切り出しも詰めもframe精度なので、
    # 成果物はこれと一致しなければならない。**両trackが揃って短く終わった**回を捕まえられる
    # のはこの比較だけである(片側だけなら検品の truncated が拾う)。
    removed = sum(float(step["tighten"]["removed_seconds"] or 0.0)
                  for step in steps if "tighten" in step)
    gate = await clip_gate.check(out, preset=preset, scenes=len(items),
                                 expected_seconds=max(0.0, requested - removed))
    result = {
        "path": str(out),
        "filename": out.name,
        "bytes": out.stat().st_size if out.is_file() else 0,
        "scenes": len(items),
        # 要求した範囲の合計と、間の詰めで落とした合計。両方を返すのは、画面が
        # 「90秒のつもりが72秒」を説明できるようにするためである。
        "requested_seconds": round(requested, 3),
        "tightened_seconds": round(removed, 3),
        # 焼き直さずに済んだシーンの数。これが出ていないと、cacheが効いているのか毎回
        # 全部焼いているのかを、所要時間の体感でしか判断できない。
        "reused_scenes": sum(1 for step in steps
                             if step.get("cut", {}).get("cached")
                             and step.get("tighten", {}).get("cached")),
        "output_duration_seconds": gate.get("seconds"),
        "preset_id": preset.get("id"),
        "preset_name": preset.get("name"),
        "steps": steps,
        "gate": gate,
    }
    await report("完了", 100)
    logger.info(
        "作品を書き出しました: %s（%dシーン, %.1f秒, 検品%s）",
        out.name, len(items), gate.get("seconds") or 0.0,
        "合格" if gate["ok"] else "不合格",
        extra={"event": "work.exported",
               "ctx": {k: v for k, v in result.items() if k != "gate"}},
    )
    return result
