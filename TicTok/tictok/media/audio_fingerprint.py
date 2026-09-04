"""音の指紋(constellation hash)で、短い動画が長い録画のどこから来たのかを当てる。

TikTok本体のhighlightは「録画のどこか」を切り出した動画だが、切り出し位置はどこにも
書かれていない。位置さえ判れば、その区間に居たgift eventをDBから引けて「誰が投げたか」
が決まる。ここはその位置を出す層である。

**なぜ映像でなく音か。** highlightは再encodeされ、拡大・crop され、演出が重畳されている
可能性がある。映像のhashはそのどれにも弱い。音は再encode(AAC)を通っても波形の骨格が
残り、画面に何が乗ろうと変わらない。同じ理由で、比較は波形そのものではなく
**spectrogramのpeakの配置**で行う ―― 音量正規化やbitrate差では動かない量だからである。

段取りは2段。

  1. 粗い位置決め(:func:`align`)  spectrogram peakのpairをhash化し、query側とdb側で
     一致したhashの時間差をhistogramに積む。同じ音なら差は1点へ集中し、無関係なら平坦に
     散る。**この「単峰が立つか」が一致の判定そのもの**で、hopの23msが分解能になる。
  2. 追い込み(:func:`refine_offset`)  粗い位置の周りだけ、5ms刻みのenergy envelopeで
     相互相関を取る。frame単位の切り出しに要る精度(±5ms)はここで出す。

生波形の相互相関を最初からやらないのは、5,940秒の録画に対しては計算量が現実的でない
のと、探索範囲が全域のときは音量差やcodecの位相ずれで偽の山が立つためである。
"""
from __future__ import annotations

import logging
import subprocess
import threading
from pathlib import Path
from typing import NamedTuple, Optional, Sequence

import numpy as np

logger = logging.getLogger(__name__)

# 源はHE-AAC。11kHz以上はSBRが合成した帯域で、元の情報ではない(scripts/audio_ab.py)。
# 11,025Hzまで落とせばNyquistが5.5kHzになり、指紋は実在する情報だけで作られる。
SAMPLE_RATE = 11025
FFT_SIZE = 1024                 # 92.9ms窓
HOP = 256                       # 23.2ms刻み。粗い位置決めの分解能はこれで決まる
FRAME_SECONDS = HOP / SAMPLE_RATE

# peakとみなす近傍(frame数 x bin数)。ここを広げるとpeakは減って速くなるが、
# 短いqueryでは票が足りなくなる。
PEAK_RADIUS_T = 6
PEAK_RADIUS_F = 12
# 1秒あたりに残すpeakの上限。密度を止めないと、拍手や歓声の区間だけでhashが爆発して
# db側のhash1本あたりの出現数が上限に当たり、逆に票が消える。
PEAKS_PER_SECOND = 24
# 無音の底でpeakを拾わないための下限(chunk内のmagnitudeのpercentile)。
PEAK_FLOOR_PERCENTILE = 75.0

# hashにするpairの条件。dtの下限を1にするのは同一frame内のpairが時間情報を持たないため。
FAN_OUT = 6
MIN_DT_FRAMES = 1
MAX_DT_FRAMES = 64              # 1.49秒

# 1つのhashがdb側でこれ以上出るなら、その音は「どこにでもある」ので票を投じさせない。
MAX_HASH_OCCURRENCES = 400

# refine段のenvelopeの刻みと、粗い位置の周りを探す幅。
ENVELOPE_MS = 5.0
REFINE_WINDOW_SECONDS = 1.5


class Fingerprint(NamedTuple):
    """1本の音の指紋。``hashes`` と ``times`` は同じ長さで、i番目が対になる。

    ``times`` はframe番号(1 frame = :data:`FRAME_SECONDS` 秒)で、hashのpairの**先頭側**の
    位置である。db側は :func:`sort_by_hash` でhash順に並べ替えてから使う。"""
    hashes: np.ndarray          # uint32
    times: np.ndarray           # int32
    frames: int                 # 元の音のframe総数
    peaks: int

    @property
    def seconds(self) -> float:
        return self.frames * FRAME_SECONDS


class Alignment(NamedTuple):
    """queryがdbのどこから来たかの判定。

    ``offset_seconds`` は「queryの0秒がdbの何秒か」。``votes`` はその位置へ集まった一致
    hash数、``ratio`` は2位(±2 frame離れた最大)との比で、**単峰がどれだけ際立っているか**を
    表す。一致していない組み合わせではratioが1に近づく。"""
    offset_seconds: float
    votes: int
    ratio: float
    matched_hashes: int
    query_hashes: int

    @property
    def matched_ratio(self) -> float:
        return self.matched_hashes / self.query_hashes if self.query_hashes else 0.0


# ===== 音の取り出し =====

def decode_args(path, input_args: Sequence[str] = (), start: Optional[float] = None,
                duration: Optional[float] = None, sample_rate: int = SAMPLE_RATE) -> list:
    """mono PCMをstdoutへ吐かせるffmpegの引数。

    ``-ss`` は必ず ``-i`` の後ろへ置く。録画はHLS stream-copy由来のVFRで、入力側 ``-ss`` は
    尺の計算を壊す(doc/CLIP_TIMEBASE.md)。映像は捨てるので出力側seekでも十分速い。

    **``aresample=async=1`` は外してはいけない。** 録画の音声には配信の切れ目ぶんの穴が
    空いており、素で復号すると出てくるPCMは「実在する音を詰めただけの列」になる。つまり
    PCM上の秒数が時刻軸の秒数より穴のぶんだけ短くなる ―― 実測で5,940秒の録画が5,935.7秒
    (-4.7秒)になり、1,740秒地点の一致位置が1,735.3秒と報告された。async=1は穴を無音で
    埋めて時刻軸へ貼り付けるので、指紋のframe番号がそのまま録画の秒になる。この軸で出た
    offsetだけが、DBの秒(``time_axis='media'``)や時刻mapperと同じ物差しに載る。"""
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
            *input_args, "-i", str(path)]
    if start is not None:
        args += ["-ss", f"{start:.6f}"]
    if duration is not None:
        args += ["-t", f"{duration:.6f}"]
    args += ["-vn", "-sn", "-dn", "-map", "0:a:0",
             "-af", "aresample=async=1:first_pts=0",
             "-f", "s16le", "-ac", "1", "-ar", str(sample_rate), "-"]
    return args


def _drain(stream, sink: list) -> None:
    try:
        sink.append(stream.read())
    except Exception:  # noqa: BLE001 - 読めなければ診断が減るだけ
        pass


def iter_pcm(args: Sequence[str], chunk_samples: int):
    """ffmpegのPCM出力をchunkで流す。float32(-1..1)のmono。

    stderrは別threadで並行に吸う。pipe(64KB)が埋まると相互待ちでhangする実例がある
    (波形生成で600秒超)。bufsizeは既定(-1)のままにすること。"""
    proc = subprocess.Popen(list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    err: list = []
    pump = threading.Thread(target=_drain, args=(proc.stderr, err), daemon=True)
    pump.start()
    want = chunk_samples * 2
    stdout = proc.stdout
    if stdout is None:                       # PIPEを指定しているので起きないが、型の穴を塞ぐ
        raise RuntimeError("ffmpegのstdoutを開けませんでした。")
    try:
        while True:
            buf = stdout.read(want)
            if not buf:
                break
            yield np.frombuffer(buf, dtype="<i2").astype(np.float32) / 32768.0
    finally:
        stdout.close()
        code = proc.wait()
        pump.join(timeout=5.0)
        if code != 0:
            message = (err[0].decode("utf-8", "replace").strip() if err else "")
            raise RuntimeError(f"ffmpegが音声を取り出せませんでした (rc={code}): {message[-500:]}")


def decode_pcm(args: Sequence[str]) -> np.ndarray:
    """短い音を丸ごとfloat32で読む。長い録画には使わない(:func:`iter_pcm` を使う)。"""
    parts = list(iter_pcm(args, 1 << 20))
    return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)


# ===== 指紋 =====

def _max_filter_1d(a: np.ndarray, radius: int, axis: int) -> np.ndarray:
    """``a`` の各点を、その軸方向 ±radius の最大値へ置き換える(端は縁で埋める)。"""
    if radius <= 0:
        return a
    pad = [(0, 0)] * a.ndim
    pad[axis] = (radius, radius)
    padded = np.pad(a, pad, mode="edge")
    view = np.lib.stride_tricks.sliding_window_view(padded, 2 * radius + 1, axis=axis)
    return view.max(axis=-1)


def _spectrogram(samples: np.ndarray) -> np.ndarray:
    """log magnitude spectrogram。frames x bins のfloat32。"""
    frames = 1 + (len(samples) - FFT_SIZE) // HOP
    if frames <= 0:
        return np.zeros((0, FFT_SIZE // 2 + 1), dtype=np.float32)
    view = np.lib.stride_tricks.sliding_window_view(samples, FFT_SIZE)[::HOP][:frames]
    window = np.hanning(FFT_SIZE).astype(np.float32)
    spec = np.fft.rfft(view * window, axis=-1)
    return np.log1p(np.abs(spec).astype(np.float32))


def _peaks(spec: np.ndarray, base_frame: int) -> tuple:
    """spectrogramの局所最大を拾い、密度を :data:`PEAKS_PER_SECOND` で抑える。"""
    if spec.size == 0:
        return np.zeros(0, np.int32), np.zeros(0, np.int16)
    local = _max_filter_1d(_max_filter_1d(spec, PEAK_RADIUS_T, 0), PEAK_RADIUS_F, 1)
    floor = float(np.percentile(spec, PEAK_FLOOR_PERCENTILE))
    t_idx, f_idx = np.nonzero((spec >= local) & (spec > floor))
    if t_idx.size == 0:
        return np.zeros(0, np.int32), np.zeros(0, np.int16)
    strength = spec[t_idx, f_idx]
    # 1秒ごとに強い順へ間引く。区間で切るのは、強い区間が弱い区間のpeakを全部押し流さない
    # ようにするため(全体で上位N件を採るとそうなる)。
    per_second = int(round(1.0 / FRAME_SECONDS))
    bucket = t_idx // per_second
    order = np.lexsort((-strength, bucket))
    bucket = bucket[order]
    rank = np.arange(bucket.size) - np.searchsorted(bucket, bucket, side="left")
    keep = order[rank < PEAKS_PER_SECOND]
    keep = keep[np.argsort(t_idx[keep], kind="stable")]
    return (t_idx[keep].astype(np.int32) + base_frame, f_idx[keep].astype(np.int16))


def _hashes(times: np.ndarray, bins: np.ndarray) -> tuple:
    """時間順のpeak列から (hash, 先頭peakの時刻) を作る。

    pairの相手は「時間順で次のK個」に採る。peakは既に間引かれているので、これは古典的な
    target zoneの近似として十分に働く。"""
    out_h, out_t = [], []
    for k in range(1, FAN_OUT + 1):
        if times.size <= k:
            break
        t1, t2 = times[:-k], times[k:]
        f1, f2 = bins[:-k].astype(np.uint32), bins[k:].astype(np.uint32)
        dt = (t2 - t1).astype(np.int64)
        ok = (dt >= MIN_DT_FRAMES) & (dt <= MAX_DT_FRAMES)
        if not ok.any():
            continue
        h = ((f1[ok] & 0x3FF) << 22) | ((f2[ok] & 0x3FF) << 12) | (dt[ok].astype(np.uint32) & 0xFFF)
        out_h.append(h.astype(np.uint32))
        out_t.append(t1[ok].astype(np.int32))
    if not out_h:
        return np.zeros(0, np.uint32), np.zeros(0, np.int32)
    h = np.concatenate(out_h)
    t = np.concatenate(out_t)
    order = np.argsort(t, kind="stable")
    return h[order], t[order]


def fingerprint_stream(args: Sequence[str], chunk_seconds: float = 240.0) -> Fingerprint:
    """ffmpegの引数を受け取り、流しながら指紋を作る。長い録画はこちらを使う。

    **frameの格子は音の先頭から ``HOP`` 刻みで一意に決まっていなければならない。** chunkへ
    持ち越すのは「次のframeの開始位置より後ろ」だけで、既に消費したsampleを重ねて渡しては
    いけない。重ねると次chunkの先頭frameが格子から外れ、frame番号が実際より進む ―― 60秒
    chunkで4 frame(93ms)ずつ溜まり、1,740秒地点で2.1秒の誤りになった(実測)。

    chunkの継ぎ目では局所最大の近傍が片側だけ欠けるので、境界付近のpeakは僅かに揺れる。
    票は数千単位で入るため影響しないが、chunkは無闇に小さくしない。"""
    chunk_samples = int(chunk_seconds * SAMPLE_RATE)
    carry = np.zeros(0, dtype=np.float32)
    base = 0
    peak_t, peak_f = [], []
    for block in iter_pcm(args, chunk_samples):
        samples = np.concatenate((carry, block)) if carry.size else block
        spec = _spectrogram(samples)
        if spec.shape[0]:
            t, f = _peaks(spec, base)
            peak_t.append(t)
            peak_f.append(f)
            base += spec.shape[0]
        carry = samples[spec.shape[0] * HOP:]
    times = np.concatenate(peak_t) if peak_t else np.zeros(0, np.int32)
    bins = np.concatenate(peak_f) if peak_f else np.zeros(0, np.int16)
    # chunkごとにbase frameを足しているので既に昇順だが、間引きの都合で同点があり得る。
    order = np.argsort(times, kind="stable")
    times, bins = times[order], bins[order]
    h, t = _hashes(times, bins)
    return Fingerprint(h, t, base, int(times.size))


def sort_by_hash(fp: Fingerprint) -> Fingerprint:
    """db側として使うためhash順に並べ替える。"""
    order = np.argsort(fp.hashes, kind="stable")
    return fp._replace(hashes=fp.hashes[order], times=fp.times[order])


# ===== 突き合わせ =====

def align(query: Fingerprint, db: Fingerprint) -> Optional[Alignment]:
    """queryがdbのどこから来たかを返す。一致hashが1本も無ければ None。

    ``db`` は :func:`sort_by_hash` 済みであること。"""
    if query.hashes.size == 0 or db.hashes.size == 0:
        return None
    lo = np.searchsorted(db.hashes, query.hashes, side="left")
    hi = np.searchsorted(db.hashes, query.hashes, side="right")
    counts = hi - lo
    counts[counts > MAX_HASH_OCCURRENCES] = 0
    total = int(counts.sum())
    if total == 0:
        return None
    # 一致した各hashについて、db側の出現位置ぶんだけqueryの時刻を繰り返し、差を取る。
    q_times = np.repeat(query.times, counts)
    starts = np.repeat(lo, counts)
    within = np.arange(total) - np.repeat(np.cumsum(counts) - counts, counts)
    deltas = db.times[starts + within] - q_times
    shift = int(-deltas.min())
    votes = np.bincount(deltas + shift)
    best = int(votes.argmax())
    peak = int(votes[best])
    near = slice(max(0, best - 2), best + 3)
    rival = votes.copy()
    rival[near] = 0
    second = int(rival.max()) if rival.size else 0
    return Alignment(
        offset_seconds=(best - shift) * FRAME_SECONDS,
        votes=peak,
        ratio=(peak / second) if second else float(peak),
        matched_hashes=int((counts > 0).sum()),
        query_hashes=int(query.hashes.size),
    )


def envelope(samples: np.ndarray, sample_rate: int = SAMPLE_RATE,
             frame_ms: float = ENVELOPE_MS) -> np.ndarray:
    """energy envelope(frameごとのRMS)。追い込みの相互相関はこの上で行う。"""
    step = max(1, int(sample_rate * frame_ms / 1000.0))
    n = len(samples) // step
    if n == 0:
        return np.zeros(0, dtype=np.float32)
    block = samples[:n * step].reshape(n, step)
    return np.sqrt((block.astype(np.float32) ** 2).mean(axis=1))


def refine_offset(query_pcm: np.ndarray, db_pcm: np.ndarray, db_pcm_start: float,
                  sample_rate: int = SAMPLE_RATE, frame_ms: float = ENVELOPE_MS) -> tuple:
    """envelopeの相互相関で offset を詰める。返り値は (秒, 相関係数)。

    ``db_pcm`` は粗い位置の前後に余裕を取って切り出した録画側の音、``db_pcm_start`` は
    その先頭が録画の何秒かである。"""
    q = envelope(query_pcm, sample_rate, frame_ms)
    d = envelope(db_pcm, sample_rate, frame_ms)
    if q.size == 0 or d.size < q.size:
        return db_pcm_start, 0.0
    q = q - q.mean()
    qn = float(np.linalg.norm(q))
    if qn == 0:
        return db_pcm_start, 0.0
    # 各lagで正規化相関を出す。lag数はREFINE_WINDOWぶんしかないので素直に回してよい。
    lags = d.size - q.size + 1
    csum = np.concatenate(([0.0], np.cumsum(d.astype(np.float64))))
    csq = np.concatenate(([0.0], np.cumsum(d.astype(np.float64) ** 2)))
    win_sum = csum[q.size:] - csum[:lags]
    win_sq = csq[q.size:] - csq[:lags]
    mean = win_sum / q.size
    var = np.maximum(win_sq - q.size * mean ** 2, 1e-12)
    corr = np.correlate(d, q, mode="valid") - mean * q.sum()
    score = corr / (np.sqrt(var) * qn)
    best = int(np.argmax(score))
    return db_pcm_start + best * frame_ms / 1000.0, float(score[best])


def probe_source(path: Path, input_args: Sequence[str] = ()) -> Fingerprint:
    """便宜関数: pathを丸ごと指紋にする。"""
    return fingerprint_stream(decode_args(path, input_args))
