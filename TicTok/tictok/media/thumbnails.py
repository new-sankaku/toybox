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

== 解像度が変わる録画では filter graph を作り直させない ==

配信側の解像度は配信中に変わる(実測: 640x1280 → 720x1280 → 640x1280)。ffmpegは入力の
frame寸法が変わると **filter graph全体を作り直す**(入力option ``reinit_filter`` の既定は1)。
``tile`` は指定枚数を貯めてから1枚出す蓄積型なので、作り直しのたびに貯めた分が捨てられ、
``-frames:v 1`` は**最後の作り直し以降**だけが入ったsheetを掴む。頭の「変更時刻÷interval」枚が
丸ごと抜けて全体がその枚数ぶん前へ詰まり、足りない末尾は ``tile`` のEOF flushで黒く埋まる。

実測(3.68時間・interval 45秒・最後の変更が2481秒): tile *i* に (i+55)*45秒 の絵が入り、
末尾55枚(10755秒以降)が黒。**前段に ``scale`` を置いても効かない** — 作り直しは入力側で
起きるので、scaleへ届く前にgraphごとresetされる。``-reinit_filter 0`` で作り直しを止めれば
``scale`` が寸法差を吸収し、``tile`` の蓄積も ``fps`` の起点も生き残る。

尺は数分〜3時間超まで幅があるため、intervalとgridはdurationから決め、
総tile数はMAX_TILESで頭打ちにしてsprintが無制限に肥大するのを防ぐ。
"""

import asyncio
import json
import logging
import math
from pathlib import Path

from tictok.core import cancel, ffprobe
from tictok.media import hls_source
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
# 解像度が変わっても filter graph を作り直させない入力option(module docstring参照)。
# 作り直すと `tile` の蓄積が捨てられ、spriteが丸ごとずれて末尾が黒くなる。
NO_GRAPH_REINIT = ("-reinit_filter", "0")


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


async def _probe_duration(source) -> float:
    """尺(秒)。取得できなければRuntimeError。

    寸法はここでは取らない。``stream=width,height`` は1組しか返さず、混在解像度の録画では
    その1組が全編を代表しないため、tileのaspectを開いた所の値だけで決めてしまう
    (``_widest`` を参照)。"""
    if not ffprobe_available():
        raise RuntimeError("ffprobeが見つかりません。sprite生成にはffmpeg一式のinstallが必要です。")
    result = await ffprobe.run(
        ffprobe.duration_args(source.path, source.input_args))
    duration = ffprobe.parse_duration(result.stdout)
    if duration is None:
        message = result.stderr.strip()
        logger.error(
            "thumbnail生成のため %s の情報を取得できませんでした", source.path.name,
            extra={"event": "thumbnails.probe_failed",
                   "ctx": {"src": str(source.path), "returncode": result.returncode,
                           "stderr": message[:2000]}},
        )
        raise RuntimeError(f"録画の情報を取得できませんでした: {message[:300]}")
    if duration <= 0:
        raise RuntimeError("録画の尺または解像度が不正です。")
    return duration


async def _widest(source) -> tuple[int, int]:
    """tileのaspectを決める寸法。録画に現れる解像度の幅と高さそれぞれの最大。

    vfの ``scale`` は全frameを同じtile寸法へ揃えるので、寸法を1組のprobeで決めると、
    切替後のframeがそのaspectへ引き伸ばされる。両方を包む枠から比を採れば、混在した
    どのframeも同じ歪み方をしない。"""
    found = await hls_source.widest_resolution(source)
    if found is None or found[0] <= 0 or found[1] <= 0:
        raise RuntimeError("録画の尺または解像度が不正です。")
    return found


async def _no_keyframe_gap() -> float | None:
    """測らなかったことを「測れなかった」と同じNoneで表す。どちらも通常decodeへ倒れる。"""
    return None


async def _max_keyframe_gap(source, duration: float) -> float | None:
    """標本抽出で測ったkeyframe間隔の最大値(秒)。測れなければNone。

    全走査は利点とほぼ同額のcostになるので、尺を等分した位置の短い窓だけを読む。窓と窓の
    間には当然大きな隙間が空くため、窓幅を超えるgapは窓の切れ目として捨てる(これを数えると
    どの録画も「keyframe間隔が数百秒」になり、常に通常decodeへ倒れる)。

    窓は ``開始%終了`` の**絶対時刻**で渡す。尺で指定する ``開始%+尺`` は、実HLSに混ざる
    pts=N/Aのpacketで1 packet読んだ時点で打ち切られ、0 frameしか返らない(実測: 3.1時間の
    録画で 0 frame 対 128 frame)。0 frameはNone(=測れなかった)として全frame decodeへ倒れる
    ため、故障は「遅いだけ」の形でしか現れない。``media/keyframes.py`` も同じ理由で絶対時刻。

    返ってきたframeにも ``pts=N/A`` は混ざる(seek直後の先頭など。実測: 同じ3.1時間の録画で
    128 keyframe中1本、他の録画では0本と出る回・出ない回がある)。位置を決められないframeなので
    数えない — ``float()`` へ渡すと走査ごと ``ValueError`` になり、spriteのjobも
    ``/api/recordings/{id}/thumbnails`` も落ちる(実測: 8回)。``best_effort_timestamp`` に
    替えても同じframeがN/Aなので、``media/concat.py`` と同じく除外する以外に手は無い。
    落とした前後のgapは繋がって広く出るが、広い側は全frame decodeへ倒れるだけで、誤った
    spriteは作らない。
    """
    span = KEYFRAME_PROBE_SPAN_SECONDS
    starts = [duration * (i + 0.5) / KEYFRAME_PROBE_WINDOWS
              for i in range(KEYFRAME_PROBE_WINDOWS)]
    intervals = ",".join(f"{at:.2f}%{at + span:.2f}" for at in starts)
    result = await ffprobe.run([
        "ffprobe", "-v", "error", *source.input_args, "-read_intervals", intervals,
        "-select_streams", "v:0", "-skip_frame", "nokey",
        "-show_entries", "frame=pts_time", "-of", "csv=p=0", str(source.path),
    ])
    if not result.ok:
        logger.warning(
            "%s のkeyframeを走査できないため全体のdecodeに切り替えます",
            source.path.name,
            extra={"event": "thumbnails.keyframe_probe_failed",
                   "ctx": {"src": str(source.path), "returncode": result.returncode,
                           "stderr": result.stderr[:2000]}},
        )
        return None
    times = sorted(
        float(line) for line in result.stdout.split()
        if line.strip() and line != "N/A"
    )
    gaps = [b - a for a, b in zip(times, times[1:]) if b - a <= span]
    if not gaps:
        return None
    return max(gaps)


def _interval_seconds(duration: float) -> float:
    """tileの間隔。尺だけで決まる — 解像度を待たずにkeyframe走査の要否を判断できる。"""
    return max(MIN_INTERVAL_SECONDS, math.ceil(duration / MAX_TILES))


def _grid(duration: float, width: int, height: int) -> dict:
    """尺と解像度からinterval・grid・tile寸法を決める。"""
    interval = _interval_seconds(duration)
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
    同じfileに対する測定は決定的なので、条件が変わらない限り結論も変わらない。

    srcの指紋はhls_sourceが出す。mp4が在る録画では今までの ``src.stat()`` と同じ値なので、
    既存のspriteのcacheはそのまま生き続ける。mp4が無い録画では素材(.ts)そのものを数える —
    playlistのstatはsegmentの入れ替わりを映さないので、鍵にすると当たり続けてしまう。"""
    return {**hls_source.fingerprint(src),
            "tile_width": TILE_WIDTH, "max_tiles": MAX_TILES,
            "columns": SPRITE_COLUMNS,
            "keyframe_min_interval": KEYFRAME_ONLY_MIN_INTERVAL,
            "keyframe_probe_windows": KEYFRAME_PROBE_WINDOWS,
            "keyframe_probe_span": KEYFRAME_PROBE_SPAN_SECONDS,
            "keyframe_safety": KEYFRAME_SAFETY,
            "graph_reinit": False}


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

    async with _lock_for(str(src)):
        signature = _signature(src)
        cached = _cached(src, signature)
        if cached is not None:
            return cached

        if not ffmpeg_available():
            raise RuntimeError("ffmpegが見つかりません。sprite生成にはffmpegのinstallが必要です。")

        async with hls_source.ffmpeg_source_async(src) as source:
            duration = await _probe_duration(source)
            interval = _interval_seconds(duration)
            # 寸法の走査とkeyframe間隔の測定はどちらもkeyframeを読むだけで、互いに依存しない。
            # 直列にすると長時間録画で両方の待ち時間を足すことになるので並べて走らせる。
            widest, keyframe_gap = await asyncio.gather(
                _widest(source),
                (_max_keyframe_gap(source, duration)
                 if interval >= KEYFRAME_ONLY_MIN_INTERVAL else _no_keyframe_gap()),
            )
            width, height = widest
            grid = _grid(duration, width, height)
            out = sprite_path(src)
            sidecar_dir(src).mkdir(parents=True, exist_ok=True)

            # 測れなかった(None)ときは推測せず通常decode。誤ってkeyframeのみを選ぶと、
            # tileが複製された誤ったspriteがそのままcacheへ残る。
            keyframe_only = (keyframe_gap is not None
                             and interval >= keyframe_gap * KEYFRAME_SAFETY)
            logger.info(
                "%s のsprite decode mode: %s", src.name,
                "keyframe-only" if keyframe_only else "full",
                extra={"event": "thumbnails.decode_mode",
                       "ctx": {"src": str(src), "interval_seconds": interval,
                               "keyframe_gap_seconds": (None if keyframe_gap is None
                                                        else round(keyframe_gap, 3)),
                               "safety": KEYFRAME_SAFETY, "keyframe_only": keyframe_only,
                               "hls": source.is_hls, "width": width, "height": height}},
            )
            pre_input = ["-skip_frame", "nokey"] if keyframe_only else []
            vf = (f"fps=1/{grid['interval_seconds']:.6f},"
                  f"scale={grid['tile_width']}:{grid['tile_height']},"
                  f"tile={grid['columns']}x{grid['rows']}")
            cmd = ["ffmpeg", "-v", "error", "-y", *pre_input, *NO_GRAPH_REINIT,
                   *source.input_args, "-i", str(source.path),
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
            # 全frame decodeは3.9h録画で192秒かかる。timeoutは付けない(正常な長時間走査を
            # 落とす)が、取り消しは効かなければならないのでprocessだけ登録する。
            cancel.register_process(proc)
            try:
                _, stderr = await proc.communicate()
            finally:
                cancel.forget_process(proc)
            elapsed = loop.time() - started
            if proc.returncode != 0 or not out.is_file():
                message = (stderr or b"").decode("utf-8", "replace").strip()
                logger.error(
                    "%s のthumbnail spriteの生成に失敗しました", src.name,
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
                "thumbnail spriteを生成しました: %s（%d tiles, %.1fs）",
                out.name, grid["count"], elapsed,
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
