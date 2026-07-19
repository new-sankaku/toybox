"""Seek barのhover preview用sprite sheet生成。

1枚のJPEGに等間隔frameをtileして返す。frameを個別fileで持たない理由は、
hover中はrequestが連射されるため、file数分のHTTP round tripより1枚を
背景画像として使い回す方が桁で安い(frontendはbackground-positionでずらすだけ)。

生成は`fps=1/N,scale,tile=CxR`の1passで行う。seek+個別抽出をN回回す案も測ったが
(3.9h録画/296点で約77秒)、1passの方が実測で速く、processも1つで済む。
ただし全frame decodeは3.9h録画で192秒かかり、hover起点のrequestには重すぎた。
intervalがkeyframe間隔(recorderのsegment_seconds=2秒相当)より十分大きい場合に限り
`-skip_frame nokey`でkeyframeだけをdecodeし、同じ絵を23秒で得ている。
短い録画はintervalが小さくkeyframeを取りこぼしうるので通常decodeのままで、
そもそも尺が短く時間もかからない。

尺は数分〜3時間超まで幅があるため、intervalとgridはdurationから決め、
総tile数はMAX_TILESで頭打ちにしてsprintが無制限に肥大するのを防ぐ。
"""

import asyncio
import json
import logging
import math
from pathlib import Path

from tictok.record.recorder import sidecar_dir, sidecar_path
from tictok.record.video_overlay import ffmpeg_available, ffprobe_available

logger = logging.getLogger(__name__)

SPRITE_SUFFIX = ".thumbs.jpg"
META_SUFFIX = ".thumbs.json"

# tile 1枚の横幅。縦動画(TikTokの主流)で120x213程度、横長ならこの幅に合わせて縦が縮む。
TILE_WIDTH = 120
# aspectが取れない/壊れている場合に使う既定比(9:16)。
DEFAULT_ASPECT = 9 / 16
# 総tile数の上限。3.9h録画でも1200x6420px/約1.2MBに収まり、これ以上増やすと
# sprite転送量がhover pre-fetchの利点を食い潰す。
MAX_TILES = 300
# gridの列数。TILE_WIDTH x SPRITE_COLUMNS = 1200pxで、JPEGの寸法上限にも余裕がある。
SPRITE_COLUMNS = 10
# 最小interval。これより細かくしても隣のtileがほぼ同じ絵になる。
MIN_INTERVAL_SECONDS = 2.0
# keyframeのみdecodeに切り替える閾値。segment境界のkeyframe間隔(約2秒)に対して
# 十分な余裕がある場合だけ、取りこぼしなくkeyframeを拾える。
KEYFRAME_ONLY_MIN_INTERVAL = 10.0
# mjpegの-q:v(2=最良〜31=最低)。5でtile当たり約4KB。
JPEG_QSCALE = 5


def sprite_path(src: Path) -> Path:
    """sprite sheetのcache path。既存sidecarと同じ`<record root>/.sidecars/`配下。"""
    return sidecar_path(Path(src), SPRITE_SUFFIX)


def _meta_path(src: Path) -> Path:
    return sidecar_path(Path(src), META_SUFFIX)


# 同一fileへの同時生成を防ぐ。hoverは連射されるので、素通しだと同じ3.9h録画に
# ffmpegが何本も並ぶ。
_locks: dict[str, asyncio.Lock] = {}


def _lock_for(key: str) -> asyncio.Lock:
    lock = _locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key] = lock
    return lock


async def _probe(src: Path) -> tuple[float, int, int]:
    """(duration秒, width, height)。取得できなければRuntimeError。"""
    if not ffprobe_available():
        raise RuntimeError("ffprobeが見つかりません。sprite生成にはffmpeg一式のinstallが必要です。")
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-show_entries", "format=duration",
        "-of", "json", str(src),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, stderr = await proc.communicate()
    try:
        data = json.loads(out.decode("utf-8", "replace"))
        stream = data["streams"][0]
        width, height = int(stream["width"]), int(stream["height"])
        duration = float(data["format"]["duration"])
    except (ValueError, KeyError, IndexError) as exc:
        message = (stderr or b"").decode("utf-8", "replace").strip()
        logger.error(
            "thumbnail probe failed for %s", src.name,
            extra={"event": "thumbnails.probe_failed",
                   "ctx": {"src": str(src), "returncode": proc.returncode,
                           "stderr": message[:2000]}},
        )
        raise RuntimeError(f"録画の情報を取得できませんでした: {message[:300]}") from exc
    if duration <= 0 or width <= 0 or height <= 0:
        raise RuntimeError("録画の尺または解像度が不正です。")
    return duration, width, height


def _grid(duration: float, width: int, height: int) -> dict:
    """尺と解像度からinterval・grid・tile寸法を決める。"""
    interval = max(MIN_INTERVAL_SECONDS, math.ceil(duration / MAX_TILES))
    # fpsフィルタは0, interval, 2*interval... を出すので、末尾の端数区間は数えない。
    count = max(1, min(MAX_TILES, int(duration // interval)))
    columns = min(SPRITE_COLUMNS, count)
    rows = math.ceil(count / columns)
    aspect = (width / height) if height else DEFAULT_ASPECT
    # mjpegはyuv420pなので両辺を偶数に丸める。
    tile_h = max(2, int(round(TILE_WIDTH / aspect)))
    tile_h -= tile_h % 2
    tile_w = TILE_WIDTH - (TILE_WIDTH % 2)
    return {"columns": columns, "rows": rows, "count": count,
            "interval_seconds": float(interval),
            "tile_width": tile_w, "tile_height": tile_h,
            "duration_seconds": duration}


def _signature(src: Path) -> dict:
    stat = src.stat()
    return {"mtime": stat.st_mtime, "size": stat.st_size,
            "tile_width": TILE_WIDTH, "max_tiles": MAX_TILES,
            "columns": SPRITE_COLUMNS}


def _cached(src: Path, signature: dict) -> dict | None:
    """cacheが今のsrc・今の定数と一致していればmetaを返す。"""
    sprite, meta = sprite_path(src), _meta_path(src)
    if not (sprite.is_file() and meta.is_file()):
        return None
    try:
        payload = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if payload.get("signature") != signature:
        return None
    return payload.get("sprite")


async def ensure_sprite(src: Path) -> dict:
    """srcのsprite sheetを用意し、gridのmetaを返す。2回目以降はcacheを返す。"""
    src = Path(src)
    if not src.is_file():
        raise RuntimeError("録画fileが存在しません。")

    async with _lock_for(str(src)):
        signature = _signature(src)
        cached = _cached(src, signature)
        if cached is not None:
            return cached

        if not ffmpeg_available():
            raise RuntimeError("ffmpegが見つかりません。sprite生成にはffmpegのinstallが必要です。")

        duration, width, height = await _probe(src)
        grid = _grid(duration, width, height)
        out = sprite_path(src)
        sidecar_dir(src).mkdir(parents=True, exist_ok=True)

        keyframe_only = grid["interval_seconds"] >= KEYFRAME_ONLY_MIN_INTERVAL
        pre_input = ["-skip_frame", "nokey"] if keyframe_only else []
        vf = (f"fps=1/{grid['interval_seconds']:.6f},"
              f"scale={grid['tile_width']}:{grid['tile_height']},"
              f"tile={grid['columns']}x{grid['rows']}")
        cmd = ["ffmpeg", "-v", "error", "-y", *pre_input, "-i", str(src),
               "-an", "-sn", "-vf", vf, "-frames:v", "1",
               "-q:v", str(JPEG_QSCALE), str(out)]

        loop = asyncio.get_running_loop()
        started = loop.time()
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        elapsed = loop.time() - started
        if proc.returncode != 0 or not out.is_file():
            message = (stderr or b"").decode("utf-8", "replace").strip()
            logger.error(
                "thumbnail sprite failed for %s", src.name,
                extra={"event": "thumbnails.failed",
                       "ctx": {"src": str(src), "returncode": proc.returncode,
                               "keyframe_only": keyframe_only, "vf": vf,
                               "stderr": message[:2000]}},
            )
            raise RuntimeError(f"サムネイルの生成に失敗しました: {message[:300]}")

        sprite = {"path": str(out), **grid}
        _meta_path(src).write_text(
            json.dumps({"signature": signature, "sprite": sprite}, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info(
            "thumbnail sprite built: %s (%d tiles, %.1fs)", out.name, grid["count"], elapsed,
            extra={"event": "thumbnails.built",
                   "ctx": {"src": str(src), "output": str(out),
                           "count": grid["count"], "columns": grid["columns"],
                           "rows": grid["rows"], "interval_seconds": grid["interval_seconds"],
                           "tile_width": grid["tile_width"], "tile_height": grid["tile_height"],
                           "duration_seconds": duration, "keyframe_only": keyframe_only,
                           "elapsed_seconds": round(elapsed, 2),
                           "size_bytes": out.stat().st_size}},
        )
        return sprite
