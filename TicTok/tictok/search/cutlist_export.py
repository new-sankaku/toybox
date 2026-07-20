"""cut listをNLEへ渡す形式へ書き出す。

mp4を書き出さずに範囲情報だけを渡せば、再encodeもdisk消費もなくNLE上で原本を参照した
まま微調整できる。切り出しmp4は素材を単体で扱いたいとき用で、編集へ渡す本線はこちら。

== timecodeとframe rate ==
EDLもFCPXMLもframeを最小単位に持つ形式で、秒からframe番号への換算にはsourceの実fpsが
要る。録画はHLS stream-copy由来で配信ごとにfpsが違う(30 / 29.97 / 60 の実例がある)ため、
既定値を決め打ちするとNLE上の位置が素材ごとに系統的にずれる。よってfpsはffprobeで実測し、
測れない素材が混ざる場合はEDL/FCPXMLを書き出さずに止める(推測値で位置を作らない)。
CSVは秒をそのまま持つので実測できなくても正しく、timecode列だけを空で出す。

fpsが29.97(30000/1001)系のときはdrop frame timecodeで書く。non-dropのlabelは実経過時間から
毎時3.6秒ずれていくため、実時間で位置を読む用途では誤りやすい。frameの同定はどちらでも
一意なので、FCM行と区切り記号(';')をlabel方式と一致させることが要件になる。

== EDLと混在fps ==
CMX3600 EDLはlist全体で1つのtimebaseしか持たない。fpsの違う素材を1本のEDLへ混ぜると、
片方のsource timecodeがNLE側で別のframe数として解釈され位置がずれる。回避策が形式側に
無いため、混在時はerrorにして書き出さない(fpsごとに分けて出すか、素材ごとにformatを
持てるFCPXMLを使う)。

== 録画がVFRである件 ==
録画はHLS stream-copy由来のVFRで、公称fpsと実測frame間隔は完全には一致しない。よって
EDL/FCPXMLの位置はframe単位の厳密さまでは保証しない。秒を無損失で持てるCSVが最も誤差が
無いので、用途に応じて選べるよう3形式を並べている。
"""

import asyncio
import csv
import io
import json
import logging
import shutil
from fractions import Fraction
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import escape, quoteattr

logger = logging.getLogger(__name__)

# FCPXMLのversion。1.10はFCP 10.6 / DaVinci Resolve 18以降が読める。
FCPXML_VERSION = "1.10"

# drop frameの対象となるNTSC系分数fps(1001分母)。それ以外は常にnon-drop。
_NTSC_DENOMINATOR = 1001


class CutlistExportError(RuntimeError):
    """frame基準の形式へ書き出せないとき(fps未解決・fps混在など)に送出する。"""


def _ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


async def _probe_media(path: Path) -> Optional[dict]:
    """素材のfps(有理数)・解像度・尺・音声構成をffprobeで実測する。

    fpsはr_frame_rateの分数表記をそのまま有理数で保持する。floatへ落とすと29.97が
    30000/1001へ戻らず、FCPXMLのframeDurationが表現できない。測れない場合は捏造せず
    Noneを返し、呼び出し側が形式ごとに扱いを決める。"""
    if not _ffprobe_available():
        logger.warning(
            "ffprobe not found; cutlist timecode cannot be resolved",
            extra={"event": "cutlist.probe_unavailable", "ctx": {"path": str(path)}},
        )
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
    except OSError:
        logger.warning(
            "ffprobe failed to start for %s", path, exc_info=True,
            extra={"event": "cutlist.probe_failed", "ctx": {"path": str(path)}},
        )
        return None
    if proc.returncode != 0:
        logger.warning(
            "ffprobe returned %d for %s", proc.returncode, path,
            extra={"event": "cutlist.probe_failed",
                   "ctx": {"path": str(path), "returncode": proc.returncode,
                           "stderr": (err or b"").decode("utf-8", "replace")[:500]}},
        )
        return None
    try:
        info = json.loads(out.decode("utf-8", "replace"))
    except ValueError:
        logger.warning(
            "ffprobe output was not JSON for %s", path, exc_info=True,
            extra={"event": "cutlist.probe_failed", "ctx": {"path": str(path)}},
        )
        return None

    video = next((s for s in info.get("streams") or []
                  if s.get("codec_type") == "video"), None)
    if video is None:
        logger.warning(
            "no video stream in %s", path,
            extra={"event": "cutlist.probe_no_video", "ctx": {"path": str(path)}},
        )
        return None
    fps = _parse_rate(video.get("r_frame_rate"))
    if fps is None:
        logger.warning(
            "unusable r_frame_rate %r in %s", video.get("r_frame_rate"), path,
            extra={"event": "cutlist.probe_no_fps",
                   "ctx": {"path": str(path), "r_frame_rate": video.get("r_frame_rate")}},
        )
        return None

    audio = next((s for s in info.get("streams") or []
                  if s.get("codec_type") == "audio"), None)
    duration = None
    raw_duration = (info.get("format") or {}).get("duration")
    if raw_duration is not None:
        try:
            duration = float(raw_duration)
        except (TypeError, ValueError):
            duration = None
    return {
        "fps": fps,
        "width": _as_int(video.get("width")),
        "height": _as_int(video.get("height")),
        "duration": duration,
        "audio_channels": _as_int((audio or {}).get("channels")),
        "audio_rate": _as_int((audio or {}).get("sample_rate")),
    }


def _as_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_rate(token) -> Optional[Fraction]:
    """ffprobeの ``30000/1001`` / ``30/1`` を有理数へ。0除算や0/0はNone。"""
    if not token:
        return None
    try:
        rate = Fraction(str(token))
    except (ValueError, ZeroDivisionError):
        return None
    return rate if rate > 0 else None


async def resolve_timebases(cuts: list) -> list:
    """各cutへ素材の実測情報(``media``)を付けたlistを返す。同一fileは1回だけ測る。

    測れなかったcutの ``media`` はNone。ここでは落とさず、frame基準の形式側で
    「解決できない素材がある」として止める。"""
    probed: dict = {}
    out = []
    for cut in cuts:
        item = dict(cut)
        path = cut.get("path")
        if path:
            if path not in probed:
                probed[path] = await _probe_media(Path(path))
            item["media"] = probed[path]
        else:
            item["media"] = None
        out.append(item)
    return out


# ---- timecode ---------------------------------------------------------------

def _frames(seconds: float, fps: Fraction) -> int:
    return int(round(max(0.0, float(seconds)) * float(fps)))


def is_drop_frame(fps: Fraction) -> bool:
    """NTSC系の分数fps(29.97 / 59.94)だけがdrop frameの対象。整数fpsは常にnon-drop。"""
    return fps.denominator == _NTSC_DENOMINATOR


def _timecode(seconds: float, fps: Fraction) -> str:
    """秒をtimecodeへ。frame番号は実fpsで数え、labelはdrop/non-dropの規則で振る。"""
    return _timecode_frames(_frames(seconds, fps), fps)


def _timecode_frames(frames: int, fps: Fraction) -> str:
    """frame番号をtimecodeへ。累積位置は秒へ戻さずframeのまま渡すこと(往復で1 frame
    ずれることがある)。"""
    nominal = int(round(float(fps)))
    if nominal <= 0:
        raise CutlistExportError("frame rateが不正です。")
    if is_drop_frame(fps):
        return _drop_frame_label(frames, nominal, fps)
    return _label(frames, nominal, ":")


def _label(frames: int, nominal: int, sep: str) -> str:
    f = frames % nominal
    total_seconds = frames // nominal
    s = total_seconds % 60
    m = (total_seconds // 60) % 60
    h = total_seconds // 3600
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{f:02d}"


def _drop_frame_label(frames: int, nominal: int, fps: Fraction) -> str:
    """SMPTE drop frame。毎分先頭のframe番号を2つ(59.94なら4つ)飛ばし、10分ごとに
    飛ばさないことで、labelを実経過時間へ寄せる。frame自体は落とさない(labelの規則)。"""
    dropped = nominal // 15  # 29.97 -> 2, 59.94 -> 4
    frames_per_10min = int(round(float(fps) * 600))
    frames_per_min = nominal * 60 - dropped
    tens, rest = divmod(frames, frames_per_10min)
    adjusted = frames + dropped * 9 * tens
    if rest > dropped:
        adjusted += dropped * ((rest - dropped) // frames_per_min)
    return _label(adjusted, nominal, ";")


# ---- CSV --------------------------------------------------------------------

def to_csv(cuts: list) -> str:
    """秒をそのまま持つ一覧。誤差が無く、表計算でもscriptでも扱える。

    timecode列はfpsを実測できたcutだけ埋める(埋められない行を既定fpsで埋めると、
    表としては揃うが値は根拠の無い位置になる)。"""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["unique_id", "filename", "path", "start_seconds", "end_seconds",
                     "duration_seconds", "fps", "start_timecode", "end_timecode", "label"])
    for cut in cuts:
        duration = cut["end"] - cut["start"]
        media = cut.get("media")
        fps = media["fps"] if media else None
        writer.writerow([
            cut["unique_id"],
            cut.get("filename") or "",
            cut.get("path") or "",
            f"{cut['start']:.3f}",
            f"{cut['end']:.3f}",
            f"{duration:.3f}",
            f"{float(fps):.6f}" if fps else "",
            _timecode(cut["start"], fps) if fps else "",
            _timecode(cut["end"], fps) if fps else "",
            cut.get("label") or "",
        ])
    return buffer.getvalue()


# ---- EDL (CMX3600) ----------------------------------------------------------

def _timeline_rate(cuts: list) -> Fraction:
    """list全体のtimebase。EDLは1つしか持てないので、混在は書き出さずに止める。"""
    rates = {}
    missing = []
    for cut in cuts:
        media = cut.get("media")
        if not media:
            missing.append(cut.get("filename") or cut.get("path") or cut["unique_id"])
            continue
        rates.setdefault(media["fps"], []).append(
            cut.get("filename") or cut.get("path") or cut["unique_id"]
        )
    if missing:
        raise CutlistExportError(
            "frame rateを実測できない素材があるためtimecodeを出せません"
            f"（{len(missing)}件、例: {missing[0]}）。fileの実体を確認してください。"
        )
    if not rates:
        raise CutlistExportError("書き出す対象がありません。")
    if len(rates) > 1:
        listed = "、".join(f"{float(r):.3f}fps: {len(v)}件" for r, v in rates.items())
        raise CutlistExportError(
            f"frame rateの異なる素材が混在しています（{listed}）。EDLはlist全体で1つの"
            "frame rateしか持てないため、配信者を絞って出す（unique_ids）か、素材ごとに"
            "frame rateを持てるFCPXMLを使ってください。"
        )
    return next(iter(rates))


def to_edl(cuts: list, title: str = "tictok_cutlist") -> str:
    """CMX3600 EDL。record側は各clipを順に並べた連番timelineとして書く。

    ``cuts`` は resolve_timebases を通したもの(各cutに ``media``)であること。"""
    fps = _timeline_rate(cuts)
    fcm = "DROP FRAME" if is_drop_frame(fps) else "NON-DROP FRAME"
    lines = [f"TITLE: {title}", f"FCM: {fcm}", ""]
    record_frames = 0
    for index, cut in enumerate(cuts, start=1):
        record_in = record_frames
        # record側はclipを隙間なく並べる。source側のframe数をそのまま足していくことで、
        # 秒へ戻して数え直すより1 frameのずれ込みが起きない。
        record_frames += max(0, _frames(cut["end"], fps) - _frames(cut["start"], fps))
        lines.append(
            f"{index:03d}  AX       AA/V  C        "
            f"{_timecode(cut['start'], fps)} {_timecode(cut['end'], fps)} "
            f"{_timecode_frames(record_in, fps)} {_timecode_frames(record_frames, fps)}"
        )
        lines.append(f"* FROM CLIP NAME: {cut.get('filename') or ''}")
        if cut.get("path"):
            lines.append(f"* SOURCE FILE: {cut['path']}")
        if cut.get("label"):
            lines.append(f"* COMMENT: {cut['label']}")
        lines.append("")
    return "\n".join(lines)


# ---- FCPXML -----------------------------------------------------------------

def _fcp_time(frames: int, fps: Fraction) -> str:
    """frame数をFCPXMLの有理秒表記へ。1 frame = denominator/numerator 秒。

    frameDurationの整数倍でない値はFCP/Resolveが読み込み時に丸めるため、時刻は必ず
    frame数から組み立てる(秒をそのまま小数で書かない)。"""
    if frames == 0:
        return "0s"
    return f"{frames * fps.denominator}/{fps.numerator}s"


def to_fcpxml(cuts: list, name: str = "tictok_cutlist") -> str:
    """FCPXML。素材ごとにformat(frame rate/解像度)を持てるので、fpsが混在していても
    それぞれの実測値で書ける。sequenceのtimebaseは最も多くのcutが属するfpsを使う。

    ``cuts`` は resolve_timebases を通したもの(各cutに ``media``)であること。"""
    missing = [c for c in cuts if not c.get("media")]
    if missing:
        first = missing[0]
        raise CutlistExportError(
            "frame rateを実測できない素材があるためFCPXMLを出せません"
            f"（{len(missing)}件、例: {first.get('filename') or first.get('path')}）。"
            "fileの実体を確認してください。"
        )
    if not cuts:
        raise CutlistExportError("書き出す対象がありません。")

    # formatは(fps, 幅, 高さ)ごとに1つ。同じ素材を何度切っても資源は共有する。
    formats: dict = {}
    assets: dict = {}
    resources: list = []
    issued = 0

    def _next_id() -> str:
        # id連番はresourceの「行数」ではなく発行数で採る(assetは複数行を書くため)。
        nonlocal issued
        issued += 1
        return f"r{issued}"

    def _format_id(media: dict) -> str:
        key = (media["fps"], media["width"], media["height"])
        if key not in formats:
            fid = _next_id()
            formats[key] = fid
            fps = media["fps"]
            attrs = [f'id="{fid}"',
                     f'frameDuration="{fps.denominator}/{fps.numerator}s"']
            if media["width"] and media["height"]:
                attrs.append(f'width="{media["width"]}" height="{media["height"]}"')
            resources.append("    <format " + " ".join(attrs) + "/>")
        return formats[key]

    def _asset_id(cut: dict) -> str:
        path = cut.get("path") or ""
        if path in assets:
            return assets[path]
        media = cut["media"]
        fid = _format_id(media)
        aid = _next_id()
        assets[path] = aid
        fps = media["fps"]
        # 素材全体の尺。測れない場合は捏造せずdurationを省く(FCPXMLでは任意属性)。
        attrs = [f'id="{aid}"',
                 f"name={quoteattr(Path(path).stem if path else cut['unique_id'])}",
                 'start="0s"', f'format="{fid}"', 'hasVideo="1"']
        if media["duration"] is not None:
            attrs.append(f'duration="{_fcp_time(_frames(media["duration"], fps), fps)}"')
        if media["audio_channels"]:
            attrs.extend(['hasAudio="1"', 'audioSources="1"',
                          f'audioChannels="{media["audio_channels"]}"'])
            if media["audio_rate"]:
                attrs.append(f'audioRate="{media["audio_rate"]}"')
        resources.append("    <asset " + " ".join(attrs) + ">")
        if path:
            resources.append(
                "      <media-rep kind=\"original-media\" "
                f"src={quoteattr(Path(path).as_uri())}/>"
            )
        resources.append("    </asset>")
        return aid

    # sequenceのtimebaseはcut数が最多のfps(同数なら先着)。clip側は自分のformatを持つ。
    counts: dict = {}
    for cut in cuts:
        counts[cut["media"]["fps"]] = counts.get(cut["media"]["fps"], 0) + 1
    seq_fps = max(counts, key=lambda rate: (counts[rate], -float(rate)))

    clips = []
    offset_frames = 0
    for cut in cuts:
        media = cut["media"]
        aid = _asset_id(cut)
        fid = _format_id(media)
        # 長さはtimelineのtimebaseで、素材内の開始位置は素材自身のtimebaseで数える。
        # 尺0のclipは形式上不正なので最低1 frameへ切り上げる。
        duration_frames = max(1, _frames(cut["end"] - cut["start"], seq_fps))
        start_frames = _frames(cut["start"], media["fps"])
        attrs = [f'ref="{aid}"',
                 f"name={quoteattr(cut.get('filename') or cut['unique_id'])}",
                 f'offset="{_fcp_time(offset_frames, seq_fps)}"',
                 f'start="{_fcp_time(start_frames, media["fps"])}"',
                 f'duration="{_fcp_time(duration_frames, seq_fps)}"',
                 f'format="{fid}"']
        offset_frames += duration_frames
        clip = "            <asset-clip " + " ".join(attrs)
        if cut.get("label"):
            clips.append(clip + ">")
            clips.append(f"              <note>{escape(cut['label'])}</note>")
            clips.append("            </asset-clip>")
        else:
            clips.append(clip + "/>")

    # sequenceのformatは、そのfpsで登録済みのformatをそのまま流用する(clipの走査で
    # 必ず1つは登録されている)。
    seq_format = formats[next(k for k in formats if k[0] == seq_fps)]
    tc_format = "DF" if is_drop_frame(seq_fps) else "NDF"
    quoted_name = quoteattr(name)
    return "\n".join([
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!DOCTYPE fcpxml>",
        f'<fcpxml version="{FCPXML_VERSION}">',
        "  <resources>",
        *resources,
        "  </resources>",
        "  <library>",
        f"    <event name={quoted_name}>",
        f"      <project name={quoted_name}>",
        f'        <sequence format="{seq_format}" tcStart="0s" tcFormat="{tc_format}"'
        f' duration="{_fcp_time(offset_frames, seq_fps)}">',
        "          <spine>",
        *clips,
        "          </spine>",
        "        </sequence>",
        "      </project>",
        "    </event>",
        "  </library>",
        "</fcpxml>",
        "",
    ])
