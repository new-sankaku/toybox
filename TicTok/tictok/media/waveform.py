"""録画mp4のseek bar下に敷く音声波形(peak envelope)を作る。

表示に要るのはbucketごとの「最大振幅」だけなので、映像は一切decodeせず音声のみを
mono/低sample rateへ落としてs16le rawでpipe受けする。3時間級の録画が常在するため、
全sampleをmemoryへ載せる/PythonでloopするのはNG:
  - decodeはpipeから固定chunkで逐次読みし、chunk単位でnumpyへ渡す。
  - 縮約はreshape+maxのvector演算のみ。frame単位のPython loopは無い。
中間表現として ``FINE_FRAME_MS`` 刻みのpeak列を持ち、最後に要求bucket数へ
maximum.reduceatで畳む。こうすると再生時間に依らずmemoryが尺に比例するだけ(3時間で
数MB)に収まり、bucket数の決定にffprobeの尺を先読みする必要も無い。

結果はrecorderと同じsidecar置き場(.sidecars)へJSONでcacheし、srcのmtime+sizeと
bucket数が一致する限りffmpegを再実行しない。

Fallbackは持たない: ffmpeg不在・音声stream無し・decode失敗はいずれもRuntimeErrorで
返し、無音波形のような「それらしい嘘」は返さない(誤認の元になるため)。
"""

import asyncio
import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path

import numpy as np

from tictok.record.recorder import ffmpeg_available, ffmpeg_ctx, sidecar_path

logger = logging.getLogger(__name__)

WAVEFORM_SUFFIX = ".waveform.json"
# cache schemaのversion。縮約方法や正規化を変えたら上げる(旧cacheを無効化するため)。
_CACHE_VERSION = 1

# 波形表示に必要なのは振幅の包絡だけで音質は不要。8kHzでも数千bucketの包絡は変わらず、
# decode量(=所要時間)は元の48kHzの1/6で済む。
SAMPLE_RATE = 8000
# 中間peakの時間分解能。20msなら3時間で54万点(float32で約2MB)に収まり、
# 数千bucketへ畳んでも1bucketあたり十分な標本数が残る。
FINE_FRAME_MS = 20
FINE_FRAME_SAMPLES = SAMPLE_RATE * FINE_FRAME_MS // 1000
# pipeからの1回の読み取り量。大きすぎるとchunk単位の一時arrayが太り、小さすぎると
# syscallとnumpy呼び出しの回数が増える。約1MB(≒64秒ぶん)が両者の折り合い。
READ_CHUNK_BYTES = 1 << 20
_BYTES_PER_SAMPLE = 2
_FULL_SCALE = 32768.0
# 数値の丸め桁。JSONのbyte数を約半分にでき、表示上の差は出ない。
_PEAK_DECIMALS = 4
# 波形のx軸はplayerの再生位置と一致しなければならない。録画はHLS由来でaudioに欠落区間が
# あり、素で読むと「decodeできたsample数」が尺より短くなる(実測: 4546秒の録画で4377秒、
# 169秒ぶんの詰まり)。そのままだと波形が末尾へ向かって最大3%手前へずれる。async=1が
# 欠落を無音で埋め、first_pts=0が先頭の空きを埋めるので、sample数 = PTS上の尺になる。
_RESAMPLE_FILTER = "aresample=async=1:first_pts=0"
# 保持するstderrのbyte数上限。診断に要るのは末尾だけで、破損streamの録画は同じ警告を
# 数十MB吐くことがあるため、全量をmemoryへ溜めない。
_STDERR_KEEP_BYTES = 16384


def waveform_path(src) -> Path:
    """``src``の波形cacheのsidecar path。"""
    return sidecar_path(src, WAVEFORM_SUFFIX)


def _source_key(src: Path) -> dict:
    """cacheの有効性を判定するsrcの指紋。hashは3時間/12GBのfileを毎回全読みすることに
    なるので使わず、mtime+sizeで判定する(録画は追記でなく差し替えで更新される)。"""
    stat = src.stat()
    return {"mtime": round(stat.st_mtime, 3), "size": stat.st_size}


def _load_cache(src: Path, buckets: int) -> dict:
    """有効なcacheがあれば戻り値dictを、無ければ空dictを返す。bucket数までkeyに含めるのは、
    別解像度の要求へ既存cacheを畳み直すと境界がbucketの整数倍でない限り近似になり、
    表示位置が微妙にずれるため。"""
    path = waveform_path(src)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if data.get("version") != _CACHE_VERSION or data.get("buckets") != buckets:
        return {}
    try:
        key = _source_key(src)
    except OSError:
        return {}
    if data.get("mtime") != key["mtime"] or data.get("size") != key["size"]:
        return {}
    peaks = data.get("peaks")
    if not isinstance(peaks, list) or len(peaks) != buckets:
        return {}
    return {
        "buckets": buckets,
        "duration_seconds": float(data.get("duration_seconds", 0.0)),
        "peaks": peaks,
    }


_build_locks: dict = {}
_build_locks_guard = threading.Lock()


def _lock_for(key: str) -> asyncio.Lock:
    """src pathごとのlock。同じ録画への並行生成を1本に束ねるためだけに使う。"""
    with _build_locks_guard:
        lock = _build_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _build_locks[key] = lock
        return lock


def _store_cache(src: Path, result: dict) -> None:
    """cacheを書く。書けなくても波形自体は返せるので、失敗は警告に留めて送出しない
    (次回ffmpegが再度走るだけで、結果は正しい)。"""
    path = waveform_path(src)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": _CACHE_VERSION, "sample_rate": SAMPLE_RATE,
                   **_source_key(src), **result}
        # tmp名にpidとthread idを混ぜる。固定名だと同じ録画を同時に書いた際、
        # 片方のreplaceがもう片方のtmpを消してFileNotFoundErrorになる。
        tmp = path.with_suffix(f"{path.suffix}.{os.getpid()}-{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        logger.warning(
            "waveform cache write failed for %s", src.name,
            extra={"event": "waveform.cache_write_failed",
                   "ctx": {"src": str(src), "path": str(path), "error": str(exc)}},
        )


class _StderrDrain:
    """ffmpegのstderrを専用threadで吸い出し、末尾だけを保持する。

    stdoutを読み切ってからstderrを読む実装だと、警告がOSのpipe buffer(既定64KB)を
    埋めた時点でffmpegがstderr書き込みでblockし、stdoutが止まってこちらもblockする
    相互待ちになる。実録画(H.264の破損frameを含むHLS由来のmp4)では警告がMB単位に達し、
    実際に無限hangを再現したため、読み出しは必ず並行に行う。
    """

    def __init__(self, stream) -> None:
        self._stream = stream
        self._tail = b""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            while True:
                chunk = self._stream.read(4096)
                if not chunk:
                    break
                self._tail = (self._tail + chunk)[-_STDERR_KEEP_BYTES:]
        except (OSError, ValueError):
            return

    def text(self) -> str:
        self._thread.join(timeout=5.0)
        return self._tail.decode("utf-8", "replace").strip()


def _fine_peaks(proc: "subprocess.Popen") -> np.ndarray:
    """s16le pipeを逐次読みし、``FINE_FRAME_SAMPLES``ごとのpeak(絶対値の最大)列を返す。

    frame境界に満たない端数はcarryへ持ち越し、次chunkの先頭と連結してから畳む。
    int16のままabsを取ると-32768が符号反転で溢れるのでint32へ広げてから評価する。
    """
    blocks: list = []
    carry = b""
    frame_bytes = FINE_FRAME_SAMPLES * _BYTES_PER_SAMPLE
    assert proc.stdout is not None
    while True:
        chunk = proc.stdout.read(READ_CHUNK_BYTES)
        if not chunk:
            break
        if carry:
            chunk = carry + chunk
        usable = len(chunk) - (len(chunk) % frame_bytes)
        carry = chunk[usable:]
        if not usable:
            continue
        samples = np.frombuffer(chunk, dtype="<i2", count=usable // _BYTES_PER_SAMPLE)
        frames = samples.reshape(-1, FINE_FRAME_SAMPLES).astype(np.int32)
        peak = np.maximum(frames.max(axis=1), -frames.min(axis=1))
        blocks.append(peak.astype(np.float32))
    if carry:
        # 末尾の半端frameも1frameとして拾う(尾の数十msが欠けるのを防ぐ)。
        samples = np.frombuffer(carry, dtype="<i2",
                                count=len(carry) // _BYTES_PER_SAMPLE).astype(np.int32)
        if samples.size:
            blocks.append(np.array([max(samples.max(), -samples.min())], dtype=np.float32))
    if not blocks:
        return np.empty(0, dtype=np.float32)
    return np.concatenate(blocks)


def _reduce(fine: np.ndarray, buckets: int) -> np.ndarray:
    """fine peak列を厳密にbuckets個へ畳む。

    bucket境界は等分位置``i*n//buckets``で、n>=bucketsなら間隔が必ず1以上になるため
    reduceatが空区間(直後の値をそのまま返す挙動)を作らない。縮約は
    ``np.maximum.reduceat``の一括呼び出しで、区間ごとのloopは張らない。fineがbucketsより
    短い録画(数秒もの)では畳めないので、逆に最近傍indexで引き伸ばす。どちらの経路でも
    bucket数は要求どおりになる。
    """
    n = fine.size
    if n >= buckets:
        starts = (np.arange(buckets, dtype=np.int64) * n) // buckets
        return np.maximum.reduceat(fine, starts)
    idx = np.minimum((np.arange(buckets, dtype=np.int64) * n) // buckets, n - 1)
    return fine[idx]


def _decode_fine_peaks(src: Path) -> np.ndarray:
    """ffmpegで音声のみをmono/``SAMPLE_RATE``へdecodeし、fine peak列を返す。"""
    args = [
        "ffmpeg", "-v", "error", "-nostdin", "-i", str(src),
        # 映像/字幕は捨てて音声1本だけ。-vnだけだと他stream選択でmuxerが迷う。
        "-vn", "-map", "0:a:0", "-af", _RESAMPLE_FILTER,
        "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-",
    ]
    try:
        proc = subprocess.Popen(
            args, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            bufsize=READ_CHUNK_BYTES,
        )
    except OSError as exc:
        logger.error(
            "waveform ffmpeg launch failed for %s", src.name,
            extra={"event": "waveform.launch_failed",
                   "ctx": {"src": str(src), **ffmpeg_ctx(args), "error": str(exc)}},
            exc_info=True,
        )
        raise RuntimeError(f"波形生成でffmpegを起動できませんでした: {exc}") from exc

    drain = _StderrDrain(proc.stderr)
    try:
        fine = _fine_peaks(proc)
    finally:
        if proc.stdout is not None:
            proc.stdout.close()
        message = drain.text()
        if proc.stderr is not None:
            proc.stderr.close()
        proc.wait()

    if proc.returncode != 0:
        logger.error(
            "waveform decode failed for %s", src.name,
            extra={"event": "waveform.decode_failed",
                   "ctx": {"src": str(src),
                           **ffmpeg_ctx(args, proc.returncode, stderr_text=message)}},
        )
        raise RuntimeError(f"波形生成の音声decodeに失敗しました: {message[:300]}")
    if fine.size == 0:
        logger.error(
            "waveform decode produced no audio for %s", src.name,
            extra={"event": "waveform.no_audio",
                   "ctx": {"src": str(src),
                           **ffmpeg_ctx(args, proc.returncode, stderr_text=message)}},
        )
        raise RuntimeError("録画に読み取れる音声streamがありません。")
    return fine


def _build(src: Path, buckets: int) -> dict:
    started = time.monotonic()
    fine = _decode_fine_peaks(src)
    duration = fine.size * FINE_FRAME_MS / 1000.0
    peaks = _reduce(fine, buckets)
    # 全尺のpeakで割る「表示用」正規化。full scale固定で割ると入力levelの低い配信が
    # 一様に潰れて包絡が読めなくなるため、seek bar下の表示にはこちらが要る。
    loudest = float(fine.max())
    if loudest > 0.0:
        peaks = peaks / loudest
    result = {
        "buckets": buckets,
        "duration_seconds": round(duration, 3),
        "peaks": [round(float(v), _PEAK_DECIMALS) for v in peaks],
    }
    logger.info(
        "waveform built: %s (%.1fs audio, %d buckets)", src.name, duration, buckets,
        extra={"event": "waveform.built",
               "ctx": {"src": str(src), "buckets": buckets,
                       "duration_seconds": result["duration_seconds"],
                       "fine_frames": int(fine.size),
                       "peak_full_scale": round(loudest / _FULL_SCALE, 4),
                       "sample_rate": SAMPLE_RATE,
                       "elapsed_seconds": round(time.monotonic() - started, 2)}},
    )
    return result


async def ensure_waveform(src: Path, buckets: int = 2000) -> dict:
    """``src``の波形を返す(cacheがあればそれを、無ければ生成してcacheする)。

    戻り値: ``{"buckets": int, "duration_seconds": float, "peaks": list[float]}``。
    peaksは0.0〜1.0のbucketごとのpeak振幅。

    decodeはCPU/IO律速でeventloopを塞ぐため、生成部はto_threadへ逃がす。
    """
    src = Path(src)
    buckets = int(buckets)
    if buckets <= 0:
        raise RuntimeError("bucketsは1以上にしてください。")
    if not src.is_file():
        raise RuntimeError("録画fileが存在しません。")

    cached = await asyncio.to_thread(_load_cache, src, buckets)
    if cached:
        return cached

    if not ffmpeg_available():
        raise RuntimeError("ffmpegが見つかりません。波形生成にはffmpegのinstallが必要です。")

    # 同一fileへの並行requestを1本に束ねる。3時間級では1回のdecodeがcontainerを丸ごと
    # 読むため、重複実行はdiskを占有して再生のstreamingまで巻き添えにする(実測で
    # /play が91秒待たされた)。lock取得後にcacheを見直すのは、待っている間に先行requestが
    # 生成を終えているため。
    async with _lock_for(str(src.resolve())):
        cached = await asyncio.to_thread(_load_cache, src, buckets)
        if cached:
            return cached
        result = await asyncio.to_thread(_build, src, buckets)
        await asyncio.to_thread(_store_cache, src, result)
    return result
