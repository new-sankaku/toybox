"""Seek barのhover preview用sprite sheet生成。

1枚のJPEGに等間隔frameをtileして返す。frameを個別fileで持たない理由は、
hover中はrequestが連射されるため、file数分のHTTP round tripより1枚を
背景画像として使い回す方が桁で安い(frontendはbackground-positionでずらすだけ)。

生成は`fps=1/N,scale,tile=CxR`の1passで行う。seek+個別抽出をN回回す案も測ったが
(3.9h録画/296点で約77秒)、1passの方が実測で速く、processも1つで済む。
ただし全frame decodeは3.9h録画で192秒かかり、hover起点のrequestには重すぎた。
intervalが実keyframe間隔より十分大きい場合に限り`-skip_frame nokey`でkeyframeだけを
decodeし、同じ絵を桁違いに速く得る(3022秒の録画で実測4.6秒 対 19.4秒)。

== keyframe間隔は測る。仮定してはいけない ==

以前はここを「recorderのsegment_seconds=2秒だからkeyframe間隔も約2秒」と仮定し、
intervalが10秒以上なら安全としていた。これは誤りだった。

recorderは`-hls_time 2`を**stream copy**で流している(recorder.py)。実playlistのEXTINFは
確かに中央値1.961秒で、segmentは2秒である。しかし**segmentはkeyframeから始まっていない**
(同じ録画のmp4のkeyframe間隔は17.67秒)。segmentが2秒であることと、keyframeが2秒間隔で
あることは別で、後者は配信側のencoder設定で決まりこちらからは決められない。実測した
keyframe間隔は録画ごとに2.1〜37.6秒とばらついた。

その結果、intervalが10〜37秒の帯ではtile数ぶんのkeyframeが存在せず、`fps=1/N`が直前の
frameで埋めてtileが複製される。実録画(3022秒/interval 11秒/実keyframe間隔 最大18.16秒)
では280 tile中67枚が誤った時刻の絵になっていた。

よって固定の閾値では決められない。その録画のkeyframe間隔を実際に測り、intervalが上回る
ときだけkeyframeのみdecodeへ切り替える。測定は全走査(この録画で4.2秒=利点とほぼ同額)を
避け、尺を等分した数箇所だけを読む(実測0.39秒)。測れなかったときは推測せず通常decodeへ
倒す。誤って通常decodeを選んでも遅いだけだが、誤ってkeyframeのみを選ぶと静かに誤った
spriteがcacheへ残る。

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
# keyframe間隔を測りに行く下限のinterval。これ未満ならどの録画でもkeyframeのみdecodeは
# 選べない(実測のkeyframe間隔の下限が約2秒)ので、測定costを払わず通常decodeにする。
KEYFRAME_ONLY_MIN_INTERVAL = 10.0
# keyframe間隔の測定に使う窓の数と、1窓あたりの秒数。尺を等分した位置を読む。
# 8x30秒で3022秒の録画から0.39秒、推定値は全走査の18.16秒に対し17.68秒だった。
KEYFRAME_PROBE_WINDOWS = 8
KEYFRAME_PROBE_SPAN_SECONDS = 30.0
# intervalが「測ったkeyframe間隔 x この係数」以上のときだけkeyframeのみdecodeを選ぶ。
# 標本は尺の一部(既定で8%程度)しか見ないので、測った最大値は真の最大値の下限でしかない。
# 実録画での取りこぼしは約3%だったが、外した場合の損得が対称でないため広く取る:
# 安全側に倒れても1度だけ生成が数倍遅くなるだけで、逆に倒れると誤ったspriteがcacheに残る。
KEYFRAME_SAFETY = 1.5
# mjpegの-q:v(2=最良〜31=最低)。5でtile当たり約4KB。
JPEG_QSCALE = 5


def sprite_path(src: Path) -> Path:
    """sprite sheetのcache path。既存sidecarと同じ`<record root>/.sidecars/`配下。"""
    return sidecar_path(Path(src), SPRITE_SUFFIX)


def _meta_path(src: Path) -> Path:
    return sidecar_path(Path(src), META_SUFFIX)


def thumbnail_artifact_paths(src) -> tuple:
    """``src``のspriteとそのmetaのpath。srcを消す側がcacheを取り残さないための列挙で、
    実在確認はしない(呼び出し側がunlink時にmissing_okで吸収する)。"""
    src = Path(src)
    return (sprite_path(src), _meta_path(src))


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


async def _max_keyframe_gap(src: Path, duration: float) -> float | None:
    """標本抽出で測ったkeyframe間隔の最大値(秒)。測れなければNone。

    全走査は利点とほぼ同額のcostになるので、尺を等分した位置の短い窓だけを読む。窓と窓の
    間には当然大きな隙間が空くため、窓幅を超えるgapは窓の切れ目として捨てる(これを数えると
    どの録画も「keyframe間隔が数百秒」になり、常に通常decodeへ倒れる)。
    """
    span = KEYFRAME_PROBE_SPAN_SECONDS
    starts = [duration * (i + 0.5) / KEYFRAME_PROBE_WINDOWS
              for i in range(KEYFRAME_PROBE_WINDOWS)]
    intervals = ",".join(f"{at:.2f}%+{span:.0f}" for at in starts)
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-read_intervals", intervals,
        "-select_streams", "v:0", "-skip_frame", "nokey",
        "-show_entries", "frame=pts_time", "-of", "csv=p=0", str(src),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.warning(
            "keyframe probe failed for %s; falling back to a full decode", src.name,
            extra={"event": "thumbnails.keyframe_probe_failed",
                   "ctx": {"src": str(src), "returncode": proc.returncode,
                           "stderr": (stderr or b"").decode("utf-8", "replace")[:2000]}},
        )
        return None
    times = sorted(
        float(line) for line in out.decode("utf-8", "replace").split() if line.strip()
    )
    gaps = [b - a for a, b in zip(times, times[1:]) if b - a <= span]
    if not gaps:
        return None
    return max(gaps)


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
    """cacheの有効性を決める鍵。srcの実体だけでなく、**spriteの中身を変えうる判定条件**も
    含める。keyframeのみdecodeの可否はまさにそれで、誤った条件で作られたspriteは絵が
    複製されているのに寸法もtile数も正常なため、条件を直しても鍵が同じままだと壊れた
    cacheが永久に残る(この不具合が実際にあった)。

    含めるのは測定結果(keyframe間隔)ではなく判定条件の方である。測定結果を入れると
    cacheの照合前に毎回ffprobeを走らせることになり、hoverの連射で測定costを払い続ける。
    同じfileに対する測定は決定的なので、条件が変わらない限り結論も変わらない。"""
    stat = src.stat()
    return {"mtime": stat.st_mtime, "size": stat.st_size,
            "tile_width": TILE_WIDTH, "max_tiles": MAX_TILES,
            "columns": SPRITE_COLUMNS,
            "keyframe_min_interval": KEYFRAME_ONLY_MIN_INTERVAL,
            "keyframe_probe_windows": KEYFRAME_PROBE_WINDOWS,
            "keyframe_probe_span": KEYFRAME_PROBE_SPAN_SECONDS,
            "keyframe_safety": KEYFRAME_SAFETY}


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

        interval = grid["interval_seconds"]
        keyframe_gap = None
        if interval >= KEYFRAME_ONLY_MIN_INTERVAL:
            keyframe_gap = await _max_keyframe_gap(src, duration)
        # 測れなかった(None)ときは推測せず通常decode。誤ってkeyframeのみを選ぶと、
        # tileが複製された誤ったspriteがそのままcacheへ残る。
        keyframe_only = (keyframe_gap is not None
                         and interval >= keyframe_gap * KEYFRAME_SAFETY)
        logger.info(
            "sprite decode mode for %s: %s", src.name,
            "keyframe-only" if keyframe_only else "full",
            extra={"event": "thumbnails.decode_mode",
                   "ctx": {"src": str(src), "interval_seconds": interval,
                           "keyframe_gap_seconds": (None if keyframe_gap is None
                                                    else round(keyframe_gap, 3)),
                           "safety": KEYFRAME_SAFETY, "keyframe_only": keyframe_only}},
        )
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
