"""highlightと録画から代表frameを1枚だけ切り出す —— **突き合わせを目で確かめるため**。

なぜ要るのか
------------
照合の結果として画面に並ぶのはgift名とgifterの**文字列だけ**である。実際に「別人のfileへ
別人のgiftが入る」誤りが起きたが、文字列だけを見ている限り人には気付けない。**行に鹿が
映っていて名前が「Goal Highlight」なら一目で判る。** 検証の面・gift演出の表・書き出しの下見が
どれも同じ1枚を並べられるように、口をここ1つにする。

画面はffmpegを呼べない。URLの組み立ても画面にはさせない
(:func:`tictok.api.routes.highlights.highlight_frame_url` が唯一の出所)。

時間軸
------
``at`` は**highlight自身の時間軸の秒**である。録画側のframeを採るときも入口は同じ軸で、
gift演出(``media_start``)を通してmedia軸へ写す —— **画面に2つの軸を持たせない**。軸を2つ渡す口に
すると、いつか片方だけがmedia秒で呼ばれ、それらしい別の場面が並んで「一致している」ように
見える(そうなっても絵は出るので誰も気付かない)。

録画側の ``-ss`` はHLSのmedia軸そのままでよい。HLSの時刻軸 = media軸だからである
(doc/HIGHLIGHT_MATCH.md、``hls_source.ffmpeg_source``)。

cache
-----
1画面に20〜60枚並ぶので、cacheが無いと開くたびにffmpegを数十回起こすことになる。素材は
不変(highlightのfileもfinalize済みの録画も書き換わらない)なので、**一度切ったframeは
そのまま使い回せる**。それでも鍵にはfileのbytesとmtimeを混ぜる —— 同じ名前で中身が
差し替わったとき(利用者がhighlightを置き直したとき)に古い絵を出さないため。

置き場は ``<work root>/.sidecars/highlight_frames/`` の1箇所。素材のfolderへ書かないのは、
そこが**利用者が自分でmp4を置く場所**だからで、こちらが作ったjpgを混ぜてよい場所ではない。
work root固定にするのは :func:`tictok.core.layout.clip_output_dir` と同じ理由である。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from tictok.core import ffprobe, layout
from tictok.media import hls_source
from tictok.record.recorder import SIDECAR_DIRNAME

logger = logging.getLogger("tictok.media")

FRAME_DIRNAME = "highlight_frames"

# ===== 時間軸へ敷くfilmstrip =====
# 1枚のJPEGへ等間隔frameをtileしたsprite。**hoverの1枚とは役目が違う** —— hoverは
# 「指した秒に何が映っているか」を1枚で答える物で、こちらは軸そのものを絵で埋めて
# 「どこで場面が変わるか」を目で追わせる物である。1枚ずつのfileで敷くと、軸1本を描く
# のに数十のHTTP往復が要る(録画側が既にspriteにしているのと同じ理由)。
#
# tileの横幅(px)。軸の本体は実測で40〜100pxしか背が無く、縦動画(9:16)ならこの幅で
# 足りる。大きくしてもsheetのbytesが増えるだけで、敷いた絵は同じ大きさに縮む。
STRIP_TILE_WIDTH = 80
# tileの間隔(秒)。gift演出ズームはgift演出±2秒(実測10秒前後)を軸の全幅へ拡げる場所で、
# 「映像が切り替わり終わる秒」を目で詰めるのに使う —— そこで隣のtileが同じ絵になると
# 敷く意味が無い。
STRIP_STEP_SECONDS = 0.25
# tile数の上限。highlightは実測6〜61秒だが、上限が無いとsheetだけが際限なく育つ。
# これを超える尺は間隔を伸ばして収める(絵は粗くなるが、軸は端まで埋まる)。
STRIP_MAX_TILES = 320
# gridの列数。80px x 16 = 1280pxで、JPEGの寸法上限にも余裕がある。
STRIP_COLUMNS = 16
# sheetのJPEG品質(ffmpegの -q:v)。1 tileが80px幅まで縮んだ絵なので、1枚物(4)より
# 落としてよい。落とした分がそのままsheetのbytes(=最初の1往復)に効く。
STRIP_QUALITY = 6
# sheetを作るのに待つ上限(秒)。60秒のmp4を全frame decodeしても実測1秒未満だが、
# 返らないより「敷けない」を選ぶのは1枚物と同じ。
STRIP_TIMEOUT_SECONDS = 60

# 一覧に並べるthumbの横幅(px)。縦は縦横比から決める(highlightは720x1280の縦なので、
# 横240なら縦426になる)。小さめにしてあるのは、この絵の仕事が「鹿かジェット機かを
# 見分ける」ことであって鑑賞ではないからで、20〜60枚が同時に載る面に大きい絵は要らない。
DEFAULT_WIDTH = 240
# 1枚だけ大きく見たいときの上限。これを超える指定は弾く —— 原寸を超えて引き伸ばした絵は
# 情報が増えないのに、cacheのfileだけが増える。
MAX_WIDTH = 1080
# JPEGの品質(ffmpegの -q:v。2が最良で31が最悪)。4は「圧縮の跡が判らない」線である。
JPEG_QUALITY = 4

# frameを切るのに待つ上限(秒)。highlightは60秒以下なので一瞬で返るが、録画側は数時間の
# HLSをseekするので伸びる。人が画面の前で待つ操作なので、返らないより「出ない」を選ぶ。
HIGHLIGHT_TIMEOUT_SECONDS = 20
RECORDING_TIMEOUT_SECONDS = 60


class FrameUnavailable(RuntimeError):
    """その位置のframeが出せなかった。理由をそのまま文言に持つ。"""


def cache_dir() -> Path:
    return layout.work_root() / SIDECAR_DIRNAME / FRAME_DIRNAME


def normalize_width(width: Optional[int]) -> int:
    """要求された横幅を採れる値へ。未指定は既定、範囲外はValueError。

    黙って丸めない —— 丸めると、画面は指定が効いていると思ったまま別の大きさを受け取る。"""
    if width is None:
        return DEFAULT_WIDTH
    value = int(width)
    if not 0 < value <= MAX_WIDTH:
        raise ValueError(f"幅は1以上{MAX_WIDTH}以下で指定してください。")
    return value


def _signature(src: Path) -> str:
    """素材の同一性。実体が在ればbytesとmtimeまで混ぜ、無ければpathだけで決める。

    highlightのfileは**利用者が同じ名前で置き直し得る**ので、bytes/mtimeまで混ぜないと
    古い絵が出続ける。

    録画側では実体が無いことが普通である —— 原本は .ts で、mp4は消えていることが多い
    (``hls_source``)。これは「在るはずの物が無い」ではなく既定の状態なので、ここでは
    失敗させない。録画の素材はfinalize後に書き換わらないので、pathだけで同一性は保てる。"""
    try:
        stat = src.stat()
        raw = f"{src.resolve().as_posix()}|{stat.st_size}|{int(stat.st_mtime)}"
    except OSError:
        raw = src.as_posix()
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def frame_path(src: Path, at: float, width: int, kind: str) -> Path:
    """その1枚のcache path。同じ(素材, 秒, 幅)なら必ず同じfileを指す。"""
    return cache_dir() / (
        f"{kind}_{_signature(src)}_{int(round(at * 1000))}ms_w{width}.jpg")


def _run(args: list, dst: Path, at: float, timeout: int, what: str = "") -> None:
    """ffmpegを走らせて ``dst`` へ**原子的に**置く。

    同じ絵を2つのrequestが同時に要求することは一覧では普通に起きる。中間へ書いてから
    replaceすれば、片方が書いている途中のfileをもう片方が読むことがない。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=".frame_", suffix=".jpg", dir=dst.parent)
    os.close(handle)
    temp = Path(temp_name)
    try:
        done = subprocess.run([*args, str(temp)], capture_output=True, text=True,
                              timeout=timeout)
        if done.returncode != 0 or not temp.is_file() or temp.stat().st_size == 0:
            # 尺を超えた位置では ffmpeg が「1 packetも来なかった」と言って落ちる
            # (rc=1でstderrに *received no packets*)。0 byteのfileを絵として返すと、
            # 画面には壊れた画像箱が並ぶ。**理由はlogへ丸ごと残す** —— 画面へ返す文言に
            # ffmpegの生の行を混ぜると、人が読むべき「どこを指したか」が埋もれる。
            logger.warning(
                "frameを切り出せませんでした（rc=%s / %.3f秒）: %s",
                done.returncode, at, done.stderr.strip(),
                extra={"event": "highlight.frame_failed",
                       "ctx": {"at": at, "rc": done.returncode,
                               "args": args, "stderr": done.stderr.strip()}},
            )
            raise FrameUnavailable(
                what or
                f"{at:.3f}秒のframeを切り出せませんでした（素材の尺の外か、壊れています）。")
        os.replace(temp, dst)
    finally:
        temp.unlink(missing_ok=True)


def _scale(width: int) -> str:
    # 縦は縦横比から決める。-2 は「偶数へ丸めた自動」で、JPEGのchroma subsamplingが
    # 奇数の縦を嫌うため -1 ではなくこちらを使う。
    return f"scale={width}:-2:flags=lanczos"


def highlight_frame(src: Path, at: float, width: int) -> Path:
    """highlightの ``at`` 秒のframe(jpg)。cacheに在ればそれを返す。

    ``-ss`` を ``-i`` の**前**に置く。highlightは60秒以下なので後ろに置いても実用上は
    変わらないが、録画側と同じ形にしておく方が、片方だけ直されて別の場所が出る事故が
    起きにくい。"""
    dst = frame_path(src, at, width, "hl")
    if dst.is_file():
        return dst
    _run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-ss", f"{at:.3f}",
          "-i", str(src), "-frames:v", "1", "-vf", _scale(width),
          "-q:v", str(JPEG_QUALITY), "-f", "image2"],
         dst, at, HIGHLIGHT_TIMEOUT_SECONDS)
    return dst


def recording_frame(src: Path, media_at: float, width: int) -> Path:
    """録画の **media軸** ``media_at`` 秒のframe(jpg)。

    mp4が無ければHLSの .ts から読む(``hls_source``)。原本は .ts で、mp4は消えていることが
    多い —— mp4だけを見に行くと、突き合わせの済んだ録画の大半でframeが出ない。

    ``-ss`` はmedia軸そのままで渡す。HLSの時刻軸がmedia軸だからで、``media_offset`` を
    足してはいけない(あれはcontainer軸の絶対時刻へ直すための値である)。"""
    dst = frame_path(src, media_at, width, "rec")
    if dst.is_file():
        return dst
    with hls_source.ffmpeg_source(src) as source:
        _run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-ss", f"{media_at:.3f}",
              *source.input_args, "-i", str(source.path), "-frames:v", "1",
              "-vf", _scale(width), "-q:v", str(JPEG_QUALITY), "-f", "image2"],
             dst, media_at, RECORDING_TIMEOUT_SECONDS)
    return dst


def strip_paths(src: Path) -> tuple:
    """そのhighlightのsprite sheetとその仕様のcache path。

    鍵に間隔とtile幅まで混ぜる —— 定数を変えた日に、古い刻みで焼いたsheetが新しい仕様を
    名乗ったまま敷かれると、絵と秒が静かにずれる(画面はtileの番号でしか秒を知らない)。"""
    key = (f"strip_{_signature(src)}_w{STRIP_TILE_WIDTH}"
           f"_s{int(round(STRIP_STEP_SECONDS * 1000))}ms")
    return cache_dir() / f"{key}.jpg", cache_dir() / f"{key}.json"


def _strip_source_shape(src: Path) -> tuple:
    """素材の尺と、現れる最大の解像度。どちらか読めなければ FrameUnavailable。

    解像度は1組だけ読む書き方をしない —— highlightはmontageで、継ぎ足されたgift演出ごとに
    解像度が違い得る。現れる最大の縦横比でtileを焼けば、どのgift演出も潰れずに収まる。"""
    duration = ffprobe.duration_seconds_sync(src)
    if duration is None or duration <= 0:
        raise FrameUnavailable("素材の尺が読めませんでした。")
    probe = ffprobe.run_sync(ffprobe.keyframe_resolution_args(src))
    sizes = ffprobe.parse_resolution_csv(probe.stdout)
    if not sizes:
        raise FrameUnavailable("素材の解像度が読めませんでした。")
    width = max(w for w, _ in sizes)
    height = max(h for _, h in sizes)
    if width <= 0 or height <= 0:
        raise FrameUnavailable("素材の解像度が読めませんでした。")
    return duration, width, height


def _strip_grid(duration: float, width: int, height: int) -> dict:
    """尺と解像度からtileの間隔・grid・tile寸法を決める。"""
    interval = max(STRIP_STEP_SECONDS, duration / STRIP_MAX_TILES)
    # fpsフィルタが出すのは 0, interval, 2*interval ... なので、末尾の端数は数えない。
    count = max(1, min(STRIP_MAX_TILES, int(duration // interval)))
    columns = min(STRIP_COLUMNS, count)
    rows = -(-count // columns)
    # scale=W:-2 が縦を偶数へ丸めるので、画面へ渡す寸法も同じ丸め方で出す。
    tile_height = max(2, int(round(STRIP_TILE_WIDTH * height / width / 2)) * 2)
    return {"count": count, "columns": columns, "rows": rows,
            "interval_seconds": float(interval),
            "tile_width": STRIP_TILE_WIDTH, "tile_height": tile_height,
            "duration_seconds": float(duration)}


def highlight_strip(src: Path) -> dict:
    """そのhighlightのsprite sheetを用意して仕様を返す。cacheに在ればそれを返す。

    仕様(tileの間隔・grid・寸法)はsheetと**対で**cacheへ残す。画面はtileの番号からしか秒を
    知らないので、仕様を後から測り直す作りにすると、焼いたときと違う数で読まれる余地が残る。
    """
    sheet, meta = strip_paths(src)
    if sheet.is_file() and meta.is_file():
        try:
            spec = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            spec = None
        if isinstance(spec, dict) and spec.get("count"):
            return dict(spec)
    duration, width, height = _strip_source_shape(src)
    grid = _strip_grid(duration, width, height)
    vf = (f"fps=1/{grid['interval_seconds']:.6f},"
          f"scale={STRIP_TILE_WIDTH}:-2:flags=lanczos,"
          f"tile={grid['columns']}x{grid['rows']}")
    _run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(src),
          "-vf", vf, "-frames:v", "1", "-q:v", str(STRIP_QUALITY), "-f", "image2"],
         sheet, 0.0, STRIP_TIMEOUT_SECONDS,
         what="コマを焼けませんでした（素材が壊れているか、読めません）。")
    meta.write_text(json.dumps(grid, ensure_ascii=False), encoding="utf-8")
    logger.info("filmstripを焼きました（%d枚 / %.2f秒刻み）: %s",
                grid["count"], grid["interval_seconds"], sheet.name,
                extra={"event": "highlight.strip_built",
                       "ctx": {"src": str(src), "count": grid["count"],
                               "interval_seconds": grid["interval_seconds"]}})
    return grid
