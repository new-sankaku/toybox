"""切り抜きに添える字幕file(sidecar)。

切り出したmp4の隣へ同じ名前で ``.srt`` / ``.vtt`` / ``.ass`` を置く。焼き込みと違って
**映像は書き換えない**ので、文言の直し・書体の変更・位置の調整が後からいくらでも効く。

== 時刻の原点は「要求した開始位置」ではない ==

文字起こしの時刻は元録画のmedia軸(PTS秒)である。切り抜きは元録画の一部なので、原点を引かずに
添えると開始位置ぶん丸ごとずれる。引くのは :func:`tictok.media.clipper.make_clip` が実測して
返す ``actual_start_seconds`` — **成果物の先頭が指す元録画の時刻**であって、要求した開始
位置ではない。stream copyの切り出しは要求より手前のkeyframeから始まるので、両者は数秒違う
(実録画で最大6.1秒、過去には37.6秒の例)。要求値を引くと、その差がそのまま全cueのズレになる。

== 素材版は「元録画」だけ ==

焼き込み出力・Up出力は全編を再encodeした別のfileで、文字起こしの時刻がそのまま載っている保証は
無い(:mod:`tictok.record.subtitles` の冒頭)。それらから切った切り抜きへは書き出さない —
合っているように見えて合っていない字幕は、誤りを検出する手段が無い。

== 先頭の錨 ==

頭が無音の切り抜きでは先頭cueが0秒から始まらない。字幕fileをNLEのtimelineへ**dragで置くと
先頭cueが落とした位置へ吸着する**実装があり(DaVinci Resolve)、その無音ぶんだけ全cueが早くなる。
0秒へ空のcueを置くと先頭cueの位置が成果物の先頭と一致するので、どの入れ方でも同じ結果になる
(:func:`tictok.record.subtitles.anchor_cue`)。cue listを持つsrt/vttにだけ効く。

== 装飾 ==

``.ass`` は焼き込みのテロップpreset(:mod:`tictok.record.telop_styles`)をそのまま持つ。
色・縁・発光・影武者・出入りの動き・字間・傾き・折り返し・画面上の位置まで、焼き込んだ物と
同じ層構成で出る(組み立ては :func:`tictok.record.video_overlay.subtitle_ass_document` の
1箇所しかない)。読ませる側にpresetの書体が入っていることが前提なので、書体名と同梱fileの
在り処を結果で名乗る。``.srt`` / ``.vtt`` は書式そのものが装飾を持たない素の文字で、NLEや
投稿siteへ渡す用途になる。

表示単位への分割(:func:`tictok.record.subtitles.split_for_display`)は全書式に掛ける。
whisperのsegmentは1件が数十秒になることがあり、そのまま出すと1枚が画面へ居座る間ずっと
別の言葉が喋られる。焼き込みと同じ割り方にしておけば、どの書式で出しても文の切れ目は同じに
なる(録画丸ごとの書き出しは分割しない — あちらは原稿としても使うため)。
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

from tictok.record import subtitles
from tictok.record import video_overlay

logger = logging.getLogger(__name__)

# 書き出せる書式 -> (拡張子, media type, 文字encode)。srt/vttは録画丸ごとの書き出しと
# 同じ定義を使う(同じ拡張子で別のmedia typeを名乗ると、配信する側で食い違う)。
FORMATS = {
    "srt": subtitles.EXPORT_FORMATS["srt"],
    "vtt": subtitles.EXPORT_FORMATS["vtt"],
    # ASSはSSA v4+。text/x-ssaはlibass系のplayerとNLEが受ける綴り。
    "ass": (".ass", "text/x-ssa; charset=utf-8", "utf-8"),
}

# 切り抜きの置き場に現れる字幕fileの拡張子。一覧・配信・削除がこれを見る。
SUBTITLE_EXTENSIONS = tuple(suffix for suffix, _type, _enc in FORMATS.values())

# 書き出さなかった理由。画面はこれを見て「なぜ出ていないか」を名乗る(黙って0件にしない)。
REASON_NO_TRANSCRIPT = "no_transcript"
REASON_TIMEMAP_STALE = "timemap_stale"
REASON_VARIANT = "not_source_variant"
REASON_NO_SEGMENTS = "no_segments"
REASON_NO_ORIGIN = "no_origin"

REASON_MESSAGES = {
    REASON_NO_TRANSCRIPT: "この録画の文字起こしがないため字幕fileは出していません。",
    REASON_TIMEMAP_STALE: "文字起こしの時刻が現行の時刻mapで作られていないため"
                          "字幕fileは出していません（再文字起こしが必要です）。",
    REASON_VARIANT: "焼き込み出力・Up出力から切った切り抜きには字幕fileを出せません"
                    "（時刻が合う保証があるのは元録画だけです）。",
    REASON_NO_SEGMENTS: "この範囲に書き出せる発話がありませんでした。",
    REASON_NO_ORIGIN: "切り抜きの実開始位置を測れなかったため字幕fileは出していません。",
}


def parse_formats(value) -> tuple:
    """設定値(csv)を書式のtupleへ。未知の綴りは落とさず送出する。

    黙って捨てると「ass と書いたのに出ない」が理由なしで起きる。設定側は選択肢で縛って
    いるので、ここへ未知の値が来るのは綴りの誤りだけである。"""
    names = [part.strip().lower() for part in str(value or "").split(",")]
    out: list = []
    for name in names:
        if not name:
            continue
        if name not in FORMATS:
            raise ValueError(f"未知の字幕書式です: {name}")
        if name not in out:
            out.append(name)
    return tuple(out)


def formats_from_settings(settings) -> tuple:
    return parse_formats(settings.get("clip_subtitle_formats"))


def enabled_by_settings(settings) -> bool:
    return bool(int(settings.get("clip_subtitles") or 0))


def anchor_by_settings(settings) -> bool:
    return bool(int(settings.get("clip_subtitle_anchor") or 0))


def _skip(reason: str) -> dict:
    return {"written": [], "files": [], "segments": 0,
            "reason": reason, "message": REASON_MESSAGES[reason]}


def _write_text(path: Path, body: str, encoding: str) -> None:
    """必ずtmp経由で置き換える。書いている途中で落ちた回に、半分だけの字幕fileが完成品の
    顔をして残るのを避ける(切り抜きの中間と同じ作法)。"""
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(body, encoding=encoding, newline="\n")
    os.replace(tmp, path)


async def write_for_clip(clip: dict, transcript: Optional[dict], settings,
                         *, formats: tuple, variant: str = "source") -> dict:
    """切り出したmp4の隣へ字幕fileを置く。書けない場合は理由を返す(例外にはしない)。

    ``clip`` は :func:`tictok.media.clipper.make_clip` の戻り値そのもの。原点も実尺も
    あちらが実測した値を使う — ここで測り直すと、成果物と食い違った時にどちらが正しいか
    誰も言えなくなる。
    """
    if variant != "source":
        return _skip(REASON_VARIANT)
    if not transcript or not (transcript.get("segments") or []):
        return _skip(REASON_NO_TRANSCRIPT)
    if not subtitles.timemap_current(transcript.get("timemap_version")):
        # 版が古い文字起こしは尺が伸びるほど後ろへずれる。ズレたまま添えると、外部の道具では
        # 「それらしいが合っていない字幕」にしか見えない。
        return _skip(REASON_TIMEMAP_STALE)
    origin = clip.get("actual_start_seconds")
    if origin is None:
        return _skip(REASON_NO_ORIGIN)

    out = Path(clip["path"])
    # 実尺はmake_clipが測った値。測れなかった回(ffprobeが無い等)は打ち切らない — 推測で
    # 窓を閉じるより、末尾に余分なcueが残る方が実害が小さい(playerは尺の外を出さない)。
    duration = clip.get("output_duration_seconds")
    window = subtitles.slice_segments(transcript.get("segments"), float(origin), duration)
    box = subtitles.layout_from_settings(settings)
    display = subtitles.split_for_display(
        window, max_seconds=box["max_seconds"], max_chars=box["max_chars"],
        per_line=box["per_line"], wrap_lines=box["wrap_lines"])
    if not display:
        return _skip(REASON_NO_SEGMENTS)

    cfg = video_overlay.overlay_settings(settings)
    # 錨のcueはcue listを持つ書式(srt/vtt)にだけ効く。ASSは開始時刻が絶対値として読まれる
    # ので吸着しない。
    anchor = anchor_by_settings(settings)
    written: list = []
    files: list = []
    style_info: dict = {}
    for name in formats:
        suffix, _media_type, encoding = FORMATS[name]
        path = out.with_suffix(suffix)
        if name == "ass":
            body, style_info = await _render_ass(out, display, duration, cfg)
        elif name == "srt":
            body = subtitles.to_srt(display, duration,
                                    box["per_line"], box["wrap_lines"], anchor=anchor)
        else:
            body = subtitles.to_vtt(display, duration,
                                    box["per_line"], box["wrap_lines"], anchor=anchor)
        if not body.strip():
            continue
        await asyncio.to_thread(_write_text, path, body, encoding)
        written.append(name)
        files.append(path.name)

    anchored = bool(anchor and subtitles.anchor_cue(subtitles.usable_segments(display, duration)))
    logger.info(
        "切り抜きへ字幕fileを添えました: %s（%s / %d件 / 原点 %.3f秒 / 錨 %s）",
        out.name, ",".join(written) or "なし", len(display), float(origin),
        "あり" if anchored else "なし",
        extra={"event": "clip.subtitles_written",
               "ctx": {"output": str(out), "formats": written, "files": files,
                       "segments": len(display), "origin_seconds": round(float(origin), 3),
                       "duration_seconds": duration, "anchor": anchored, **style_info}},
    )
    return {"written": written, "files": files, "segments": len(display),
            "origin_seconds": round(float(origin), 3), "anchor": anchored,
            "reason": "", "message": "", **style_info}


async def _render_ass(out: Path, display: list, duration, cfg: dict) -> tuple:
    """装飾つきASSと、読ませる側が要る書体の素性を返す。

    座標系は成果物の**実寸**。焼き込みのように解像度を上げ直したりはしない — この字幕は
    出来上がったmp4へ重ねられるので、寸法が違えばplayerが比で伸縮して位置がずれる。
    """
    width, height, _fps = await video_overlay._probe_dimensions(out)
    body, stats = await video_overlay.subtitle_ass_document(display, width, height, cfg, duration)
    style = video_overlay.telop_style(cfg)
    font_path = await asyncio.to_thread(video_overlay.ensure_telop_font, style)
    return body, {
        "width": width,
        "height": height,
        "font_size": stats.get("font_size"),
        "style": style.key,
        "style_label": style.label,
        "font_family": style.font_family,
        # 読ませる側にこの書体が無いと、装飾は残っても字面だけ別物になる。同梱fileの
        # 在り処まで名乗って、installできる状態にしておく。
        "font_file": style.font_file or "",
        "font_path": str(font_path) if font_path else "",
    }
