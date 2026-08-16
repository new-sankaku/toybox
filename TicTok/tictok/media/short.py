"""short(縦の短尺動画)1本を、素材から投稿できる形まで通す。

段は4つで、どれを通すかは型(clip_presets)が決める:

1. **切り出し** — 焼く要素が1つでもあれば範囲焼き込み(再encode・frame精度)、無ければ
   smart cut。どちらもIN点は要求どおりに着地する。既定のstream copyを使わないのは、
   keyframe境界の前置きが最大37秒付くことがあり(実測)、それは「30秒頼んで67秒」になる
   ということだからである。
2. **間の詰め** — :mod:`tictok.media.tighten`。焼き込みの**後**でしか行えない。
3. **高画質化** — 既存のUp出力をそのまま使う。配信元の解像度は低いので、投稿前に上げる。
4. **検品** — :mod:`tictok.media.clip_gate`。落ちたものは成果物として名乗らせない。

## 型は焼き込みの設定を横取りする

焼き込みは13項目の設定から絵を決める。shortだけ別の描画経路を作ると、同じ設定から2つの
見た目が生まれる。ここでやるのは**設定の値を差し替えること**だけで、描画そのものは全尺の
焼き込みと同一の経路を通る(:class:`ShortSettings`)。

## 表紙は原本から撮る

表紙は成果物ではなく**原本**の該当時刻から撮る。成果物から撮ると、間の詰めで時刻がずれた
ぶんを写し直す必要があり、写し損ねると「別の瞬間の表紙」が黙って出る。原本の絶対時刻は
題名生成が選んだ行のsegment開始そのものなので、写し替えが1つも要らない。
"""

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Optional

from tictok.core import config
from tictok.media import clip_gate, tighten
from tictok.media.clipper import STILL_EXT, clip_path, make_clip, still_path
from tictok.media.still import capture_still
from tictok.record.upscale import UpscaleError, ensure_upscaled, upscale_output_path
from tictok.record.video_overlay import (
    _CODEC_CHOICES,
    codec_family,
    ffmpeg_available,
    render_clip_overlay,
    video_encoder_name,
)

logger = logging.getLogger(__name__)

# 焼き込みの設定 key と、型のどの列がそれを決めるか。ここに無いkeyは全て元の設定のまま
# 通る(書体・font size・アイコン寸法など、shortでも同じ見た目にしたいもの)。
_OVERLAY_FROM_PRESET = {
    "video_overlay_subtitles": "subtitles",
    "video_overlay_comments": "comments",
    "video_overlay_gifts": "gifts",
    "video_overlay_score_bar": "score_bar",
    "video_output_normalize_audio": "normalize_audio",
}

# 型が焼く要素を1つも立てていなければ、焼き込み経路そのものを通さない。
_DRAWING_COLUMNS = ("subtitles", "comments", "gifts", "score_bar")

# 進捗の配分。段ごとの実測costではなく「利用者が待つ体感の重さ」で割る。
_PCT_CUT = 55
_PCT_TIGHTEN = 70
_PCT_UPSCALE = 95


def codec_setting_value(family: str) -> int:
    """codec family名 → ``video_overlay_codec`` の設定値。表に無ければ auto(0)。

    :func:`tictok.record.video_overlay.codec_family` の逆で、対応表は向こうの1つだけを
    参照する(2つ持つと片方だけ増えたときに黙ってautoへ落ちる)。
    """
    for value, name in _CODEC_CHOICES.items():
        if name == family:
            return value
    return 0


class ShortSettings:
    """焼き込みの設定を、型(clip_presets)の指定で上書きして見せる薄い層。

    元の設定objectは変更しない。焼き込みは ``settings.get(key)`` しか使わないので、この
    classがそのkeyだけを差し替えれば、描画経路は自分が特別扱いされていることを知らずに
    済む(=全尺の焼き込みと同じ絵が出る)。
    """

    def __init__(self, settings, preset: dict) -> None:
        self._settings = settings
        self._preset = preset
        self._overrides = self._build(settings, preset)

    @staticmethod
    def _build(settings, preset: dict) -> dict:
        overrides = {key: int(preset.get(column) or 0)
                     for key, column in _OVERLAY_FROM_PRESET.items()}
        # 投稿へ回る出力なので、保存用のcodecではなくshortのcodecで焼く。ここで揃えて
        # おかないと、後段でもう一度encodeし直すか、AV1のまま投稿へ出すかの二択になる。
        overrides["video_overlay_codec"] = codec_setting_value(config.get_short_codec())
        overrides["video_overlay_quality"] = config.get_short_quality()
        # 字幕は投稿先のUIが被る帯を避ける。設定値をそのまま使うと、縦画面では下端の
        # 操作UIの裏へ入ることがある。
        overrides["video_overlay_subtitle_position_percent"] = _safe_position(
            settings.get("video_overlay_subtitle_position_percent"), preset)
        return overrides

    def get(self, key):
        # 引数の形は ``Settings.get`` に合わせる(既定値を受け取らない)。既定値つきの
        # signatureにすると、設定keyの綴りを間違えても静かにNoneが返る。
        if key in self._overrides:
            return self._overrides[key]
        return self._settings.get(key)

    def __getitem__(self, key):
        return self.get(key)


def _safe_position(value, preset: dict) -> int:
    """字幕の縦位置(上端からの%)を、型の安全域の内側へ収める。"""
    top = float(preset.get("safe_top_percent") or 0.0)
    bottom = 100.0 - float(preset.get("safe_bottom_percent") or 0.0)
    if bottom <= top:
        # 安全域が画面を食い尽くしている。丸めずに元の値を通し、判断を利用者へ返す
        # (勝手に中央へ寄せると、設定が効いていないように見える)。
        return int(value or 0)
    return int(round(min(max(float(value or 0), top), bottom)))


def draws_anything(preset: dict) -> bool:
    """型が焼く要素を1つでも立てているか。偽なら焼き込み経路を通さない。"""
    return any(int(preset.get(column) or 0) for column in _DRAWING_COLUMNS)


def short_path(src: Path, start: float, end: float, label: Optional[str] = None) -> Path:
    """shortの出力path。切り出し・範囲焼き込みと同じ置き場・同じ名前の規約に従う。"""
    return clip_path(src, start, end, label, suffix="short")


def sidecar_path(out: Path) -> Path:
    """題名・説明・hashtag・検品結果を書くJSON。mp4と同じ名前で拡張子だけが違う。

    DBではなくfileにするのは、成果物と一緒に動かせるようにするためである。切り出しの置き場
    は録画の所在で決まり(work / final)、録画が移送されると一緒に移る — 台帳をDBに持つと、
    その移動のたびにpathを追いかける必要が出る。
    """
    return out.with_suffix(".json")


def _stage_adapter(report):
    """job側の ``report(段階名, %)`` を、焼き込みが呼ぶ ``StageCb(%, 段階名)`` へ橋渡しする。

    2つの層で引数の順が逆である(:data:`tictok.core.progress.StageCb` は ``(int, str)``、
    ``media_queue`` のreportは ``(str, int)``)。そのまま渡すと %の位置へ文字列が入って
    TypeErrorになるが、**進捗の送出は例外を飲む**(``JobProgress._emit``)ので、jobは正常に
    終わったまま進捗だけが黙って止まる。実測でも成果物は出来ていた。
    """
    if report is None:
        return None

    async def _stage(pct: int, text: str) -> None:
        await report(text, pct)

    return _stage


async def cut_scene(src: Path, out: Path, start: float, end: float, preset: dict,
                    label: Optional[str], overlay: Optional[dict], report) -> dict:
    """1段目。焼く要素があれば範囲焼き込み、無ければsmart cut。出力は ``out`` に置く。

    short(1シーン)と作品(:mod:`tictok.media.work`・Nシーン)の両方がここを通る。片方だけ別の
    描画経路を持たせると、同じ型から2つの見た目が生まれる。
    """
    if draws_anything(preset):
        if overlay is None:
            raise RuntimeError(
                "この型は焼き込みを要求していますが、焼き込みに渡す材料がありません。")
        settings = ShortSettings(overlay["settings"], preset)
        result = await render_clip_overlay(
            str(src), overlay["started_at"], overlay.get("ended_at"),
            overlay.get("events") or [], settings, str(out), start, end,
            battles=overlay.get("battles"), on_progress=_stage_adapter(report),
            transcript=overlay.get("transcript"))
        return {"mode": "overlay", "cached": bool(result.get("cached")),
                "keyframe_lead_seconds": 0.0}
    # 全編を再encodeする(precise)。smart cutを使わないのは、それが速いからではなく**壊れた
    # 音声を出すから**である: この録画の音声はHE-AAC(SBR)で、smart cutは先頭だけをAAC-LCへ
    # 焼いて残りを原本のpacketのまま繋ぐため、1つのtrackにLCの構成情報とHEのframeが同居する。
    # 実測したsmart cut成果物は復号error率77%(「Number of bands exceeds limit」)で、映像は
    # 正常なぶん再生するまで気付けない。
    #
    # shortは15〜90秒なので全編再encodeでも数秒で、投稿先がどのみちもう一度encodeする。
    # 原本のpacketを保つ価値(素材出し)はここには無い。
    result = await make_clip(src, start, end, label, precise=True,
                             codec=config.get_short_codec(),
                             quality=config.get_short_quality(), suffix="short")
    produced = Path(result["path"])
    if produced != out:
        # 同じdirの中で名前を付け替えるだけ(copyではないので容量は増えない)。
        out.parent.mkdir(parents=True, exist_ok=True)
        produced.replace(out)
    return {"mode": "precise", "cached": False,
            "keyframe_lead_seconds": result.get("keyframe_lead_seconds")}


async def tighten_scene(src: Path, out: Path, preset: dict) -> dict:
    """2段目。無音の真ん中を落として繋ぐ。型が詰めない指定なら何もしない。

    戻り値の ``path`` が次段の入力である。詰めなかった回は入力をそのまま返す — 詰めた結果を
    使うかどうかを呼び出し側それぞれが判断する形にすると、片方だけ ``applied`` を見落として
    詰める前のfileを進める事故が起きる。
    """
    if not int(preset.get("tighten") or 0):
        return {"step": "tighten", "applied": False, "removed_seconds": 0.0, "cuts": 0,
                "keeps": [], "path": src}
    result = await tighten.tighten_file(
        src, out,
        min_silence_seconds=float(preset["tighten_min_silence_seconds"]),
        keep_seconds=float(preset["tighten_keep_seconds"]),
        fps=config.get_short_fps())
    return {"step": "tighten", "applied": result["applied"],
            "removed_seconds": result["removed_seconds"], "cuts": result["cuts"],
            # 残した区間。効果音を置く時刻を、詰めた後の軸へ写すのに要る
            # (:func:`tictok.media.sfx.remap_to_output`)。詰めなかった回は空。
            "keeps": result.get("keeps") or [],
            "path": out if result["applied"] else src}


async def _upscale(path: Path, on_progress) -> Path:
    encoder = await video_encoder_name(codec_family(
        codec_setting_value(config.get_short_codec())))
    return await asyncio.to_thread(
        ensure_upscaled, str(path), encoder, config.get_short_quality(), on_progress, None)


async def make_short(src: Path, *, start: float, end: float, preset: dict,
                     label: Optional[str] = None, overlay: Optional[dict] = None,
                     cover_seconds: Optional[float] = None,
                     subtitle_lines: Optional[int] = None,
                     on_progress: Optional[Callable] = None) -> dict:
    """範囲1つを short 1本にする。戻り値には検品の結果まで入る。

    ``overlay`` は焼き込みに渡す材料(``settings`` / ``started_at`` / ``ended_at`` /
    ``events`` / ``battles`` / ``transcript``)。型が何も焼かない指定なら不要。

    検品に落ちても**例外にはしない**。落ちたことは戻り値の ``gate`` に入る — 失敗にすると
    一括生成が1本の不合格で止まり、残りの範囲が作られなくなる。
    """
    if not ffmpeg_available():
        raise RuntimeError("ffmpegが見つかりません。shortの生成にはffmpegのinstallが必要です。")
    start, end = float(start), float(end)
    if end <= start:
        raise RuntimeError("終了位置は開始位置より後にしてください。")

    async def report(stage: str, pct: int) -> None:
        if on_progress is not None:
            await on_progress(stage, pct)

    out = short_path(src, start, end, label)
    out.parent.mkdir(parents=True, exist_ok=True)
    # 中間は出力と同じvolumeへ置く。容量の判定と実際に消費する場所を一致させるため
    # (reel / clipper と同じ決め方)。
    workdir = Path(tempfile.mkdtemp(prefix=".short_", dir=out.parent))
    steps: list = []
    try:
        async def cut_progress(stage: str, pct: int) -> None:
            await report(stage, int(pct * _PCT_CUT / 100))

        staged = workdir / "cut.mp4"
        cut = await cut_scene(src, staged, start, end, preset, label, overlay, cut_progress)
        steps.append({"step": "cut", **cut})
        current = staged

        if int(preset.get("tighten") or 0):
            await report("間を詰めています", _PCT_CUT)
        tight = await tighten_scene(current, workdir / "tight.mp4", preset)
        current = Path(tight.pop("path"))
        if int(preset.get("tighten") or 0):
            steps.append(tight)

        if int(preset.get("upscale") or 0):
            await report("高画質化しています", _PCT_TIGHTEN)

            def on_frames(done: float, total: float) -> None:
                # 同期callback。%だけを段階名へ載せる(frame位置はUp出力側のlogが持つ)。
                return None

            try:
                upscaled = await _upscale(current, on_frames)
            except UpscaleError as exc:
                raise RuntimeError(f"高画質化に失敗しました: {exc}") from exc
            steps.append({"step": "upscale", "path": str(upscaled)})
            current = Path(upscaled)

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

    cover = None
    if cover_seconds is not None:
        # 表紙は原本の絶対時刻から撮る(module docstring「表紙は原本から撮る」)。
        cover_out = still_path(src, float(cover_seconds), label, suffix="cover")
        try:
            shot = await capture_still(src, float(cover_seconds), cover_out)
            cover = {"path": str(cover_out), "at_seconds": shot.get("at_seconds")}
        except RuntimeError:
            # 表紙が撮れないことでshortを失敗にはしない。撮れなかったことを記録する。
            logger.warning(
                "shortの表紙を撮れませんでした: %s（%.2f秒）", src.name, float(cover_seconds),
                exc_info=True,
                extra={"event": "short.cover_failed",
                       "ctx": {"src": str(src), "at_seconds": float(cover_seconds)}},
            )

    gate = await clip_gate.check(out, preset=preset, subtitle_lines=subtitle_lines)
    result = {
        "path": str(out),
        "filename": out.name,
        "bytes": out.stat().st_size if out.is_file() else 0,
        "start": round(start, 3),
        "end": round(end, 3),
        "requested_seconds": round(end - start, 3),
        "preset_id": preset.get("id"),
        "preset_name": preset.get("name"),
        "steps": steps,
        "cover": cover,
        "gate": gate,
        "output_duration_seconds": gate.get("seconds"),
    }
    await report("完了", 100)
    logger.info(
        "shortを生成しました: %s（%.1f秒, 検品%s）", out.name, gate.get("seconds") or 0.0,
        "合格" if gate["ok"] else "不合格",
        extra={"event": "short.exported",
               "ctx": {k: v for k, v in result.items() if k != "gate"}},
    )
    return result
