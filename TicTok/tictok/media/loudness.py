"""録画の音量を再生時に揃えるためのgain曲線を、音を書き換えずに作る。

== なぜ音を書き換えないのか ==

録画の原本は素材(.ts)で、mp4はそこから作り直せる派生物である。素材を正規化して置き換えると
素の音声はどこにも残らない。加えて素材は約2秒刻みのsegmentで、one-pass loudnormは3秒先読みの
動的normalizerなので、先読み窓より短い単位に切って個別に掛けるとgainの状態が2秒ごとにresetされ、
境界ごとに音量が跳ねる。全長を連続decodeして切り直せば直せるが、それは``hls_pack``がbyte連結で
守っているsegmentの同一性と ``segments.json`` のwall軸を壊す。

そこで**音そのものは1 byteも触らず、当てるべきgainの時系列だけ**をsidecarへ持つ。再生側は
GainNodeでこれを当てる。原本は無傷のまま、HLS再生でもmp4再生でも同じ曲線が効く。

== 何を測るか ==

ffmpegの ``ebur128`` (EBU R128の参照実装)と ``astats`` を1本のfilter chainへ並べ、0.1秒ごとに
short-termラウドネス(S, 3秒窓)と区間の最大sample level(P)を取る。``ametadata`` は**1本だけ**に
すること — 同じstdoutへ2本流すと、それぞれが別のbufferを持つため行が途中で混ざる(実際に
``frame:568level=-27.9`` という壊れた行を踏んだ)。astats側は ``measure_overall`` でPeak_levelに
絞り、1 frameあたり8行に抑える。実測は2.9時間の録画で19秒・23MB。

== どう曲線にするか ==

1. **Sを窓の中心へ戻す**。ebur128のSは ``[t-3s, t]`` を測った値なので、そのまま当てると常に
   1.5秒遅れる。
2. **R128と同じgateを掛ける**。無音や間まで目標へ持ち上げると、息継ぎがすべて増幅される。
   絶対gate(-70 LUFS)と相対gate(統合ラウドネス-10 LU)を外れた区間は、直前の有効なgainを保持する。
3. **peakで頭を押さえる**。``天井 - (3秒窓のPの最大)`` を上限に取る。窓は中心揃えなので
   ``P[i] <= 窓max[i]`` が常に成り立ち、**適用後のsample peakが天井を超えないことが構成上
   保証される**(実測でもちょうど天井に張り付く)。再生側にlimiterが要らないのはこのため。
4. **slewで滑らかにする**。逆方向passで「下げ」を先回りさせ、順方向passで「戻り」を抑える。
   一極のsmoothingでは下げが後追いになり、天井の保証が崩れる。

実測(2.9時間の録画・30分抜粋を実際に音へ適用してebur128で測り直した値):

| | 統合ラウドネス | 短期音量の広がり(p90-p10) | sample peak | true peak |
| --- | --- | --- | --- | --- |
| 元音声 | -26.4 LUFS | 9.6 LU | 0.00 dBFS(clip) | +0.6 dBFS |
| **gain曲線** | -16.6 | **8.3** | **-1.50** | -1.2 |
| loudnorm one-pass | -14.3 | 6.8 | -1.04 | -1.5 |

録画全体(2.9時間)では広がり 17.1 -> 9.4 LU。loudnormに一歩届かないのは**原理的な差**で、
あちらは波形を書き換えるlimiterを持つためcrest factorを詰められる。こちらはgainだけなので
peakの分だけ持ち上げられない。音を書き換えない選択の代償がこの差である。

天井は ``audio_normalize_true_peak`` を共有するが、ここで測るのはsample peakなので、実際の
true peakは上表のとおり0.3 dBほど上に出る(-1.5指定で実測-1.2)。full scaleまではまだ1.2 dB
あるので、再生でclipすることはない。

Fallbackは持たない: ffmpeg不在・音声stream無し・decode失敗はいずれもRuntimeError。gainを
0 dBで返して「揃えたつもり」にすると、揃っていない音を揃ったものとして聞かせることになる。
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

from tictok.core import cancel
from tictok.media import hls_source
from tictok.media.waveform import _StderrDrain, _key_matches, _source_key
from tictok.record.recorder import ffmpeg_available, ffmpeg_ctx, sidecar_path

logger = logging.getLogger(__name__)

GAIN_SUFFIX = ".gain.json"
# sidecarのschema version。刻み・gateの掛け方・slewの向きを変えたら上げる(旧cacheを無効化)。
_CURVE_VERSION = 1

# 測定の時間刻み。0.1秒は表示用波形(waveform.WAVE_BUCKET_SECONDS)・声profileと同じで、
# 画面側が3つを同じindexで引ける。曲線はこの刻みのまま配るので補間誤差を持たない。
STEP_SECONDS = 0.1
# 測定のsample rate。EBU R128の実装が前提にする値で、asetnsamplesの1 frame = 4800 sampleが
# ちょうどSTEP_SECONDSになる。
MEASURE_RATE = 48000
# ebur128のshort-term窓。仕様で3秒に決まっている。Sを窓の中心へ戻す量もここから出す。
SHORT_TERM_SECONDS = 3.0
# 音が在ると見なさない下限(EBU R128の絶対gate)。
ABSOLUTE_GATE_LUFS = -70.0
# 統合ラウドネスからの相対gate(EBU R128)。間や無音を目標へ持ち上げないための線。
RELATIVE_GATE_LU = 10.0
# peakの上限を取る窓。short-termと同じ幅にするのは、押さえる速さを測っている音量の速さへ
# 合わせるため。中心揃えなので窓は自分自身のframeを必ず含み、天井の保証が成立する。
PEAK_WINDOW_SECONDS = SHORT_TERM_SECONDS
# gainを下げる速さ / 戻す速さ(dB/秒)。下げは逆方向passなので「何秒前から下がり始めるか」でもある
# (21.6 dBの落差で3.6秒)。実測では6.0/2.0と3.0/1.5で広がりが9.4対9.5 LUと差が無かったため、
# 先回りの短い方を採る。
ATTACK_DB_PER_SECOND = 6.0
RELEASE_DB_PER_SECOND = 2.0
# 曲線の丸め桁。0.1 dBは聞き分けられないが、testが値を突き合わせられるよう2桁残す。
_GAIN_DECIMALS = 2

_build_locks: dict = {}
_build_locks_guard = threading.Lock()


def gain_curve_path(src) -> Path:
    """``src``のgain曲線cacheのsidecar path。"""
    return sidecar_path(Path(src), GAIN_SUFFIX)


def gain_artifact_paths(src) -> tuple:
    """この録画のgain曲線を構成するfile。sweepと一括の「済み」判定が実在を見る先。

    1つしか無いがtupleで返すのは、波形(表示用と絶対level)・サムネ(sheetとindex)・声と同じ形で
    扱えるようにするため(``voice_artifact_paths``と同じ理由)。"""
    return (gain_curve_path(src),)


def curve_params(settings) -> dict:
    """設定から曲線の目標値を取り出す。有効/無効の判断は呼び出し側が行う。

    目標ラウドネスと天井は音量正規化(``record.audio_norm``)と同じ設定を読む。同じ「どこへ
    揃えるか」を経路ごとに別の値で持つと、再生で聞いた音と出力した音の高さが食い違う。
    """
    return {
        "target_lufs": float(settings.get("audio_normalize_lufs")),
        "ceiling_dbfs": float(settings.get("audio_normalize_true_peak")),
        "max_boost_db": float(settings.get("playback_gain_max_boost_db")),
        "max_cut_db": float(settings.get("playback_gain_max_cut_db")),
    }


def _measure_args(source) -> list:
    """0.1秒ごとのshort-termラウドネスと区間peakを吐かせるffmpeg引数。

    ``ametadata`` を1本に絞り、astats側を ``measure_overall`` でPeak_levelだけにするのが要点。
    key指定の ``ametadata`` を2本並べて同じstdoutへ流すと、filterごとに別のbufferを持つため
    行が途中で混ざる。``aresample`` の指定は波形生成と同じ理由 — 録画はHLS由来で音声に欠落が
    あり、埋めないとsample数が尺より短くなって曲線が末尾へ向かってずれる。
    """
    return [
        "ffmpeg", "-v", "error", "-nostdin", *source.input_args, "-i", str(source.path),
        # 映像/字幕は捨てて音声1本だけ。-vnだけだと他stream選択でmuxerが迷う。
        "-vn", "-map", "0:a:0",
        "-af", (f"aresample=async=1:first_pts=0:osr={MEASURE_RATE},"
                f"asetnsamples=n={int(MEASURE_RATE * STEP_SECONDS)}:p=0,"
                "astats=metadata=1:reset=1:measure_perchannel=none:measure_overall=Peak_level,"
                "ebur128=metadata=1,"
                "ametadata=mode=print:file=-"),
        "-f", "null", "-",
    ]


def _parse_metadata(stdout) -> tuple:
    """ametadataの出力を読み進め、``(S, P, 統合ラウドネス)`` を返す。

    1 frameが ``frame:`` 行とkey行の塊で来るので、次の ``frame:`` を見た時点で1つ確定させる。
    Peak_levelは無音frameで ``-inf`` になるため、数として扱える下限へ落とす(0倍でなく、
    「聞こえるものが無い」を表す値)。全量をmemoryへ載せないよう行単位で読む。
    """
    short_term: list = []
    peaks: list = []
    integrated = None
    started = False
    cur_s = cur_p = None

    def flush() -> None:
        short_term.append(ABSOLUTE_GATE_LUFS - 1.0 if cur_s is None else cur_s)
        peaks.append(-120.0 if cur_p is None else cur_p)

    for raw in stdout:
        line = raw.decode("utf-8", "replace")
        if line.startswith("frame:"):
            if started:
                flush()
            started = True
            cur_s = cur_p = None
        elif line.startswith("lavfi.r128.S="):
            cur_s = float(line.split("=", 1)[1])
        elif line.startswith("lavfi.r128.I="):
            integrated = float(line.split("=", 1)[1])
        elif line.startswith("lavfi.astats.Overall.Peak_level="):
            value = line.split("=", 1)[1].strip()
            # 無音区間は-inf、音声streamの端ではnanが出ることがある。どちらも「peakは無い」。
            cur_p = -120.0 if value.lstrip("-").lower() in ("inf", "nan") else float(value)
    if started:
        flush()
    return (np.array(short_term, dtype=np.float64),
            np.array(peaks, dtype=np.float64),
            integrated)


def _measure(source) -> tuple:
    """ffmpegを1本回して ``(S, P, 統合ラウドネス)`` を測る。"""
    args = _measure_args(source)
    try:
        proc = subprocess.Popen(
            args, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except OSError as exc:
        logger.error(
            "gain曲線の測定で %s のffmpegを起動できませんでした", source.path.name,
            extra={"event": "loudness.launch_failed",
                   "ctx": {"src": str(source.path), **ffmpeg_ctx(args), "error": str(exc)}},
            exc_info=True,
        )
        raise RuntimeError(f"gain曲線の測定でffmpegを起動できませんでした: {exc}") from exc
    # 読みながら進む経路なのでtimeoutは持てない(長尺の正常な測定を落とす)。取り消しは
    # processの登録だけで届かせる — waveform._decode_fine_peaks と同じ形。
    cancel.register_process(proc)
    drain = _StderrDrain(proc.stderr)
    try:
        result = _parse_metadata(proc.stdout)
    finally:
        cancel.forget_process(proc)
        if proc.stdout is not None:
            proc.stdout.close()
        message = drain.text()
        if proc.stderr is not None:
            proc.stderr.close()
        proc.wait()

    if proc.returncode != 0:
        logger.error(
            "gain曲線の測定で %s のdecodeに失敗しました", source.path.name,
            extra={"event": "loudness.measure_failed",
                   "ctx": {"src": str(source.path),
                           **ffmpeg_ctx(args, proc.returncode, stderr_text=message)}},
        )
        raise RuntimeError(f"gain曲線の測定に失敗しました: {message[:300]}")
    if result[0].size == 0:
        logger.error(
            "gain曲線の測定で %s の音声を取得できませんでした", source.path.name,
            extra={"event": "loudness.no_audio",
                   "ctx": {"src": str(source.path),
                           **ffmpeg_ctx(args, proc.returncode, stderr_text=message)}},
        )
        raise RuntimeError("録画に読み取れる音声streamがありません。")
    return result


def _hold(values: np.ndarray, keep: np.ndarray) -> np.ndarray:
    """``keep``がFalseの区間を直前の有効値で埋める(先頭は最初の有効値で遡って埋める)。

    無音や間でgainを動かさないための保持。ここを0埋めや素通しにすると、息継ぎのたびに
    gainが最大まで持ち上がって戻る「呼吸」が出る。
    """
    if not keep.any():
        # 有効な区間が1つも無い録画(全編が無音)。揃える相手が居ないので素通し。
        return np.zeros(values.size)
    index = np.where(keep, np.arange(values.size), 0)
    np.maximum.accumulate(index, out=index)
    out = values[index]
    first = int(np.argmax(keep))
    out[:first] = values[first]
    return out


def _window_max(values: np.ndarray, seconds: float) -> np.ndarray:
    """中心揃えの移動最大。窓が自分自身のframeを必ず含むので、これを上限に使えば
    ``適用後 = values + gain <= 天井`` が構成上成り立つ。"""
    width = max(1, int(round(seconds / STEP_SECONDS)))
    pad = width // 2
    padded = np.pad(values, (pad, width - 1 - pad), mode="edge")
    return np.lib.stride_tricks.sliding_window_view(padded, width).max(axis=1)


def _slew(limit: np.ndarray) -> np.ndarray:
    """``limit``を超えない範囲で、下げを先回りさせ戻りを抑えた曲線にする。

    逆方向passが「この先で下げ切るために、今どこまで下げておく必要があるか」を決め、順方向
    passが戻る速さを抑える。どちらも値を下げる向きにしか動かさないので、``結果 <= limit`` が
    保たれる — peakの天井がそのまま守られるのはこの性質による。因果的な一極smoothingでは
    下げが後追いになり、この保証が消える。
    """
    out = limit.astype(np.float64, copy=True)
    attack = ATTACK_DB_PER_SECOND * STEP_SECONDS
    release = RELEASE_DB_PER_SECOND * STEP_SECONDS
    for i in range(out.size - 2, -1, -1):
        ceiling = out[i + 1] + attack
        if out[i] > ceiling:
            out[i] = ceiling
    for i in range(1, out.size):
        ceiling = out[i - 1] + release
        if out[i] > ceiling:
            out[i] = ceiling
    return out


def build_curve(short_term: np.ndarray, peaks: np.ndarray, integrated, params: dict) -> np.ndarray:
    """測定値からgain曲線(dB, ``STEP_SECONDS``刻み)を作る。module docstringの4段そのまま。"""
    lag = int(round(SHORT_TERM_SECONDS / 2 / STEP_SECONDS))
    # 1. Sを窓の中心へ戻す。末尾のlagぶんは最後の値で埋める(先の音は存在しない)。
    centred = np.concatenate([short_term[lag:], np.full(min(lag, short_term.size),
                                                        short_term[-1])])[:short_term.size]
    # 2. R128と同じgate。統合ラウドネスが取れない録画(3秒未満)は絶対gateだけで判断する。
    relative = (ABSOLUTE_GATE_LUFS if integrated is None
                else max(ABSOLUTE_GATE_LUFS, integrated - RELATIVE_GATE_LU))
    active = (centred > ABSOLUTE_GATE_LUFS) & (centred > relative)
    desired = _hold(np.clip(params["target_lufs"] - centred,
                            -params["max_cut_db"], params["max_boost_db"]), active)
    # 3. peakで頭を押さえる。
    headroom = params["ceiling_dbfs"] - _window_max(peaks, PEAK_WINDOW_SECONDS)
    # 4. slewで滑らかにする。
    return _slew(np.minimum(desired, headroom))


def _load_cache(src: Path, params: dict) -> dict:
    """有効なcacheがあれば戻り値dictを、無ければ空dictを返す。

    目標値もkeyに含める。目標を変えたのに前の曲線を返すと、設定を変えても音が変わらない。"""
    try:
        data = json.loads(gain_curve_path(src).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if data.get("version") != _CURVE_VERSION:
        return {}
    if data.get("step_seconds") != STEP_SECONDS:
        return {}
    if any(data.get(name) != round(value, 3) for name, value in params.items()):
        return {}
    try:
        key = _source_key(src)
    except (OSError, hls_source.SourceMissing):
        return {}
    if not _key_matches(data, key):
        return {}
    gains = data.get("gains")
    if not isinstance(gains, list):
        return {}
    return {"step_seconds": STEP_SECONDS,
            "duration_seconds": float(data.get("duration_seconds", 0.0)),
            **{name: data[name] for name in params},
            "gains": gains}


def _store_cache(src: Path, result: dict) -> None:
    """cacheを書く。書けなくても曲線自体は返せるので、失敗は警告に留めて送出しない
    (次回ffmpegが再度走るだけで、結果は正しい)。waveform._store_cacheと同じ流儀。"""
    path = gain_curve_path(src)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": _CURVE_VERSION, **_source_key(src), **result}
        # tmp名にpidとthread idを混ぜる。固定名だと同じ録画を同時に書いた際、
        # 片方のreplaceがもう片方のtmpを消してFileNotFoundErrorになる。
        tmp = path.with_suffix(f"{path.suffix}.{os.getpid()}-{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        logger.warning(
            "%s のgain曲線cacheの書き込みに失敗しました", src.name,
            extra={"event": "loudness.cache_write_failed",
                   "ctx": {"src": str(src), "path": str(path), "error": str(exc)}},
        )


def _lock_for(key: str) -> asyncio.Lock:
    """src pathごとのlock。同じ録画への並行生成を1本に束ねるためだけに使う。"""
    with _build_locks_guard:
        lock = _build_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _build_locks[key] = lock
        return lock


def _build(src: Path, params: dict) -> dict:
    started = time.monotonic()
    # mp4が無い録画は.tsのHLSから読む。音声は同じstreamなので、どちらから読んでも同じ値が出る。
    with hls_source.ffmpeg_source(src) as source:
        short_term, peaks, integrated = _measure(source)
    gains = build_curve(short_term, peaks, integrated, params)
    result = {
        "step_seconds": STEP_SECONDS,
        "duration_seconds": round(gains.size * STEP_SECONDS, 3),
        **{name: round(value, 3) for name, value in params.items()},
        "integrated_lufs": None if integrated is None else round(integrated, 2),
        "gains": [round(float(v), _GAIN_DECIMALS) for v in gains],
    }
    logger.info(
        "gain曲線を生成しました: %s（音声 %.1fs, gain %.1f〜%.1f dB）",
        src.name, result["duration_seconds"], float(gains.min()), float(gains.max()),
        extra={"event": "loudness.built",
               "ctx": {"src": str(src), "points": int(gains.size),
                       "duration_seconds": result["duration_seconds"],
                       "integrated_lufs": result["integrated_lufs"],
                       "gain_min_db": round(float(gains.min()), 2),
                       "gain_max_db": round(float(gains.max()), 2),
                       "gain_median_db": round(float(np.median(gains)), 2),
                       "elapsed_seconds": round(time.monotonic() - started, 2)}},
    )
    return result


async def ensure_gain_curve(src: Path, params: dict) -> dict:
    """``src``のgain曲線を返す(cacheがあればそれを、無ければ生成してcacheする)。

    戻り値: ``{"step_seconds": float, "duration_seconds": float, "gains": list[float],
    "target_lufs": float, "ceiling_dbfs": float, ...}``。gainsは ``step_seconds`` ごとのdB。

    測定はCPU/IO律速でeventloopを塞ぐため、生成部はto_threadへ逃がす。
    """
    src = Path(src)
    if not hls_source.available(src):
        raise hls_source.SourceMissing()

    cached = await asyncio.to_thread(_load_cache, src, params)
    if cached:
        return cached

    if not ffmpeg_available():
        raise RuntimeError("ffmpegが見つかりません。gain曲線の生成にはffmpegのinstallが必要です。")

    # 同一fileへの並行requestを1本に束ねる。測定はcontainerを丸ごと読むため、重複実行は
    # diskを占有して再生のstreamingまで巻き添えにする(waveformで実測済み)。lock取得後に
    # cacheを見直すのは、待っている間に先行requestが生成を終えているため。
    async with _lock_for(str(src.resolve())):
        cached = await asyncio.to_thread(_load_cache, src, params)
        if cached:
            return cached
        result = await asyncio.to_thread(_build, src, params)
        await asyncio.to_thread(_store_cache, src, result)
    return result
