"""録画の音声から「笑い声が出ている確率」の時系列を作る(AudioSet audio tagging)。

盛り上がりの判定はこれまでコメント密度とギフトでしか測れず、配信者と参加者が実際に
笑っている瞬間は音声の中にしか無い。ここはその1本を埋める: 固定刻みで音声を切り出し、
音声taggingのmodelへ通し、笑い系classの確率列をsidecarへ残す。

== なぜCPUなのか ==

推論はonnxruntimeの **CPUExecutionProvider 固定**である。GPUは12GBしかなく
faster-whisper(転写)と超解像がそこを奪い合っている。ここが ``gpu_slot`` を取ると、
その間だけ焼き込みが待たされる — 笑い検出は「後から一括で回す解析」であって、
利用者が待っている処理ではないので、待たせる側になってはいけない。tagging modelは
tiny級(数M parameter)で、CPUでも実時間の数十倍で流せる。

== なぜ閾値を掛ける前の生確率を保存するのか ==

sidecarへ書くのは0.0〜1.0の**生確率**で、真偽値ではない。閾値は素材(配信者・BGM・
マイク)で最適値が変わり、今の既定値が正しいという根拠がまだ無い。生確率を残して
おけば、後から閾値を掃引して精度を検証でき、閾値を変えても再解析が要らない。
閾値の適用は問い合わせ側(``laugh_seconds``)にだけ置く。

複数classの確率は **max** で畳む。AudioSetは多labelで、各classの確率は独立した
sigmoidの出力なので、和を取ると1を超えるうえ「笑いに似た音が2種類ある」ことを
「もっと笑っている」と読み替えてしまう。

== Fallbackを持たない ==

無効・onnxruntime未導入・model/labels未設定・読み込み失敗・推論失敗は、いずれも
``LaughAudioError`` で返す。ここで黙って笑い抜きの結果を返すのが最悪で、「笑いが
検出されなかった区間」と「そもそも検出していない区間」が区別できなくなる。

== 実装上の決まり ==

音声の取り出しは ``hls_source.ffmpeg_source`` を必ず通す。mp4が無い録画(=.tsだけ)は
普通にあり、``Path(src)`` を直接ffmpegへ渡すとそれらの録画で機能が黙って沈黙する。
時間軸は波形/音声profileと同じ ``aresample=async=1:first_pts=0`` で、確率列のindexが
そのままplayerの再生位置に対応する。

stderrの吸い出しは ``waveform._StderrDrain`` を**共有**する(写して持たない)。stdoutを
読み切ってからstderrを読む実装は、警告がpipe bufferを埋めた時点で相互待ちになり実録画
で無限hangを再現済みで、その回避策が2箇所に分かれて片方だけ直る事態を避けたい。
"""

import asyncio
import csv
import io
import json
import logging
import math as _math
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import NamedTuple, Optional

import numpy as np

from tictok.core import cancel
from tictok.core.config import (
    get_laugh_audio_activation,
    get_laugh_audio_batch,
    get_laugh_audio_classes,
    get_laugh_audio_device,
    get_laugh_audio_enabled,
    get_laugh_audio_hop_seconds,
    get_laugh_audio_labels_path,
    get_laugh_audio_model_path,
    get_laugh_audio_threads,
    get_laugh_audio_threshold,
    get_laugh_audio_window_seconds,
)
from tictok.media import hls_source
from tictok.media.waveform import _RESAMPLE_FILTER, _StderrDrain
from tictok.paths import PROJECT_ROOT
from tictok.record.recorder import ffmpeg_available, ffmpeg_ctx, sidecar_path

logger = logging.getLogger("tictok.laugh")

LAUGH_SUFFIX = ".laugh.json"
# sidecarのschema version。窓の切り方・畳み方・保存する項を変えたら上げる。
_PROFILE_VERSION = 1
# modelが学習された取り込みrate。設定値ではなくmodelの契約なので固定する。
SAMPLE_RATE = 16000
# pipeからの1回の読み取り量(waveformと同じ約1MB)。
READ_CHUNK_BYTES = 1 << 20
_BYTES_PER_SAMPLE = 2
_FULL_SCALE = 32768.0
# 確率の丸め桁。3桁あれば閾値の掃引に足り、JSONは半分以下になる。
_PROB_DECIMALS = 3
# expのoverflow警告を出さないためのlogitのclamp。sigmoidはこの外側で飽和済み。
_LOGIT_CLAMP = 60.0
# sidecarにしか無いcache管理用の項。読み出した確率列へは混ぜない。
_CACHE_ONLY_KEYS = ("version", "mtime", "size", "segments",
                    "model", "model_size", "model_mtime")


# deviceの設定値 -> onnxruntimeのexecution provider。ここに無い値は例外にする(綴り違いを
# 黙ってCPUとして扱うと、GPUのつもりで遅いまま気付けない)。
_PROVIDERS = {"cpu": "CPUExecutionProvider", "cuda": "CUDAExecutionProvider"}


class LaughAudioError(RuntimeError):
    """笑い声検出が無効・未導入・model/labels不備・解析失敗のときに送出する。"""


class _Model(NamedTuple):
    """読み込み済みのonnxruntime session と、graphから読めた入力の制約。"""

    session: object
    input_name: str
    output_name: str
    # exportがbatchを固定している場合のその値(可変なら0)。
    fixed_batch: int
    # exportがsample数を固定している場合のその値(可変なら0)。
    fixed_samples: int
    path: str


_model: Optional[_Model] = None
_model_key = None
_model_lock = threading.Lock()
# 同一processでの並行推論を1本に束ねる。CPU推論は既にthreadを使い切っており、
# 重ねても速くならないうえ録画・転写からcoreを奪う。
_infer_lock = threading.Lock()

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


def laugh_profile_path(src) -> Path:
    """``src``の笑い確率列のsidecar path。"""
    return sidecar_path(src, LAUGH_SUFFIX)


def laugh_artifact_paths(src) -> tuple:
    """``src``の笑い検出の成果物一式。srcを消す側が取りこぼさないよう列挙で返す。"""
    return (laugh_profile_path(src),)


def laugh_available() -> bool:
    """onnxruntimeが利用可能か(実importせず存在のみ確認)。実importはnative libの
    読み込みで時間がかかるため、status確認では find_spec で済ませる。"""
    import importlib.util

    return importlib.util.find_spec("onnxruntime") is not None


def _resolve(raw: str) -> Optional[Path]:
    """設定されたpathを解決する。相対pathはproject root基準(serverは別のworking
    directoryから起動され得る)。空ならNone。"""
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _model_file() -> Optional[Path]:
    return _resolve(get_laugh_audio_model_path())


def _labels_file() -> Optional[Path]:
    return _resolve(get_laugh_audio_labels_path())


def laugh_status() -> dict:
    available = laugh_available()
    model = _model_file()
    labels = _labels_file()
    return {
        "enabled": get_laugh_audio_enabled(),
        "available": available,
        "configured": bool(
            get_laugh_audio_enabled() and available
            and model is not None and model.is_file()
            and labels is not None and labels.is_file()
        ),
        "model": model.name if model is not None else "",
        "labels": labels.name if labels is not None else "",
        "classes": get_laugh_audio_classes(),
        "window_seconds": get_laugh_audio_window_seconds(),
        "hop_seconds": get_laugh_audio_hop_seconds(),
        "threshold": get_laugh_audio_threshold(),
        "device": get_laugh_audio_device(),
    }


def _model_fingerprint() -> dict:
    """cacheの鍵に混ぜるmodelの指紋。weightsを差し替えたら確率が変わるので、
    素材が同じでもcacheは無効にしなければならない。"""
    model = _model_file()
    if model is None:
        raise LaughAudioError(
            "笑い声検出のmodelが未設定です（TICTOK_LAUGH_AUDIO_MODEL_PATH を設定してください）。"
        )
    try:
        stat = model.stat()
    except OSError as exc:
        raise LaughAudioError(f"笑い声検出のmodel fileが見つかりません: {model}") from exc
    return {"model": model.name, "model_size": stat.st_size,
            "model_mtime": round(stat.st_mtime, 3)}


def _load_labels() -> list:
    """出力indexからclass名への対応表。AudioSetの ``class_labels_indices.csv``
    (index,mid,display_name)と、JSONのlist(index順)/dict(index->名前)を読む。

    形式を推測で補わないのは、対応表がずれると「笑いのclass」として全く別の音の確率を
    読むことになり、出力を見ても気付けないため。読めない形式は例外にする。"""
    path = _labels_file()
    if path is None:
        raise LaughAudioError(
            "笑い声検出のlabel fileが未設定です（TICTOK_LAUGH_AUDIO_LABELS_PATH を設定してください）。"
        )
    if not path.is_file():
        raise LaughAudioError(f"笑い声検出のlabel fileが見つかりません: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LaughAudioError(f"笑い声検出のlabel fileを読めませんでした: {exc}") from exc

    if path.suffix.lower() == ".csv":
        rows = list(csv.DictReader(io.StringIO(text)))
        if not rows or "index" not in rows[0] or "display_name" not in rows[0]:
            raise LaughAudioError(
                f"label CSVに index / display_name の列がありません: {path}"
            )
        by_index: dict = {}
        for row in rows:
            try:
                by_index[int(row["index"])] = (row["display_name"] or "").strip().strip('"')
            except (TypeError, ValueError) as exc:
                raise LaughAudioError(f"label CSVのindexが数値ではありません: {path}") from exc
    else:
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise LaughAudioError(f"label fileがJSONとして読めません: {path}") from exc
        if isinstance(data, list):
            by_index = {i: str(name).strip() for i, name in enumerate(data)}
        elif isinstance(data, dict):
            try:
                by_index = {int(k): str(v).strip() for k, v in data.items()}
            except (TypeError, ValueError) as exc:
                raise LaughAudioError(
                    f"label JSONのkeyがindexではありません: {path}"
                ) from exc
        else:
            raise LaughAudioError(f"label JSONはlistかdictにしてください: {path}")

    if not by_index:
        raise LaughAudioError(f"label fileが空です: {path}")
    missing = [i for i in range(max(by_index) + 1) if i not in by_index]
    if missing:
        raise LaughAudioError(
            f"label fileのindexが連番ではありません（欠番 {missing[:5]} ほか{len(missing)}件）: {path}"
        )
    return [by_index[i] for i in range(max(by_index) + 1)]


def _class_indices(labels: list, classes: list) -> list:
    """設定されたclass名を出力indexへ解く。1つでも表に無ければ例外。

    無いものを黙って外すと、綴り違いのclassが1つ混じっただけで検出感度が下がり、
    「あまり笑っていない配信」に見えてしまう。"""
    if not classes:
        raise LaughAudioError(
            "笑いとみなすclassが未設定です（TICTOK_LAUGH_AUDIO_CLASSES を設定してください）。"
        )
    lookup: dict = {}
    for i, name in enumerate(labels):
        lookup.setdefault(name, i)
    missing = [name for name in classes if name not in lookup]
    if missing:
        raise LaughAudioError(
            f"label fileに無いclassが指定されています: {missing}（区切りは | です）"
        )
    return [lookup[name] for name in classes]


def _get_model() -> _Model:
    """設定されたONNX modelをCPUで読み込む(cacheする)。``LaughAudioError``で失敗を返す。"""
    if not get_laugh_audio_enabled():
        raise LaughAudioError(
            "笑い声検出が無効です（TICTOK_LAUGH_AUDIO_ENABLED=1 を設定してください）。"
        )
    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise LaughAudioError(
            "onnxruntime が未インストールです（pip install onnxruntime）。"
        ) from exc
    model_file = _model_file()
    if model_file is None:
        raise LaughAudioError(
            "笑い声検出のmodelが未設定です（TICTOK_LAUGH_AUDIO_MODEL_PATH を設定してください）。"
        )
    if not model_file.is_file():
        raise LaughAudioError(f"笑い声検出のmodel fileが見つかりません: {model_file}")
    threads = get_laugh_audio_threads()
    device = get_laugh_audio_device()
    provider = _PROVIDERS.get(device)
    if provider is None:
        raise LaughAudioError(
            f"TICTOK_LAUGH_AUDIO_DEVICE には {'/'.join(_PROVIDERS)} のいずれかを"
            f"設定してください（今の値: {device!r}）。"
        )
    model_path = str(model_file)
    key = (model_path, threads, device)
    global _model, _model_key
    with _model_lock:
        if _model is None or _model_key != key:
            started = time.monotonic()
            options = ort.SessionOptions()
            if threads > 0:
                options.intra_op_num_threads = threads
                options.inter_op_num_threads = 1
            logger.info(
                "笑い声検出のmodelを読み込みます: %s（device=%s threads=%d）",
                model_path, device, threads,
                extra={"event": "laugh.model_load_started",
                       "ctx": {"path": model_path, "device": device, "threads": threads,
                               "size_bytes": model_file.stat().st_size}},
            )
            try:
                session = ort.InferenceSession(
                    model_path, sess_options=options, providers=[provider],
                )
            except Exception as exc:
                logger.error(
                    "笑い声検出のmodel %s を読み込めませんでした", model_file.name,
                    extra={"event": "laugh.model_load_failed",
                           "ctx": {"path": model_path, "device": device,
                                   "threads": threads,
                                   "duration_ms": int((time.monotonic() - started) * 1000)}},
                    exc_info=True,
                )
                raise LaughAudioError(f"笑い声検出modelの読み込みに失敗しました: {exc}") from exc
            # **onnxruntimeは要求したproviderを作れないと黙ってCPUへ落ちる。** 実測でも
            # CUDAを指定したsessionが CPUExecutionProvider だけを名乗り、そのまま
            # 「GPUで走っている」つもりの計測値が出た(CUDA EPのDLL依存が1つ欠けていた)。
            # 落ちたことは結果を見ても分からないので、ここで名乗らせて突き合わせる。
            active = session.get_providers()
            if provider not in active:
                raise LaughAudioError(
                    f"{provider} を作れませんでした（実際に載ったのは {active}）。"
                    "onnxruntime-gpuの導入とCUDA runtimeのDLLを確認してください。"
                    "CPUで走らせる場合は TICTOK_LAUGH_AUDIO_DEVICE=cpu にしてください。"
                )
            _model = _describe(session, model_file)
            _model_key = key
            logger.info(
                "笑い声検出のmodelを準備しました: %s（%s）", model_file.name, device,
                extra={"event": "laugh.model_loaded",
                       "ctx": {"path": model_path, "device": device, "threads": threads,
                               "providers": active,
                               "fixed_batch": _model.fixed_batch,
                               "fixed_samples": _model.fixed_samples,
                               "duration_ms": int((time.monotonic() - started) * 1000)}},
            )
    return _model


def _describe(session, model_file: Path) -> _Model:
    """graphの入出力を検査して ``_Model`` を組む。

    受けるのは16kHz mono波形 ``(batch, samples)`` を入力に取るexportだけである。
    log-mel入力のexportをここで支えると、mel filterの本数・hop・窓関数といったmodel側の
    前処理をこちらが推測することになり、少しでも学習時と違えば確率は静かに壊れる。
    その形のmodelは前処理込みでexportし直してもらう。"""
    inputs = session.get_inputs()
    if len(inputs) != 1:
        raise LaughAudioError(
            f"入力が1つのmodelにしてください（このmodelの入力: {[i.name for i in inputs]}）。"
        )
    outputs = session.get_outputs()
    if not outputs:
        raise LaughAudioError("modelに出力がありません。")
    shape = list(inputs[0].shape or [])
    if len(shape) != 2:
        raise LaughAudioError(
            f"入力は16kHz monoの波形 (batch, samples) で受け取るexportにしてください"
            f"（このmodelの入力shape: {shape}）。"
        )
    fixed_batch = shape[0] if isinstance(shape[0], int) and shape[0] > 0 else 0
    fixed_samples = shape[1] if isinstance(shape[1], int) and shape[1] > 0 else 0
    return _Model(session, inputs[0].name, outputs[0].name,
                  fixed_batch, fixed_samples, str(model_file))


def _activate(raw: np.ndarray) -> np.ndarray:
    activation = get_laugh_audio_activation()
    if activation == "sigmoid":
        return 1.0 / (1.0 + np.exp(-np.clip(raw, -_LOGIT_CLAMP, _LOGIT_CLAMP)))
    if activation == "none":
        return raw
    raise LaughAudioError(
        f"TICTOK_LAUGH_AUDIO_ACTIVATION は sigmoid か none にしてください（現在 {activation!r}）。"
    )


def _batch_probs(model: _Model, windows: list, indices: list) -> list:
    """窓の束を1回のsession.runで通し、窓ごとの笑い確率(class最大)を返す。"""
    batch = np.stack(windows).astype(np.float32)
    try:
        with _infer_lock:
            raw = model.session.run([model.output_name], {model.input_name: batch})[0]
    except Exception as exc:
        raise LaughAudioError(f"笑い声検出の推論に失敗しました: {exc}") from exc
    raw = np.asarray(raw, dtype=np.float32)
    # (batch, 1, classes) で出すexportがある。中央の軸だけ落とす(classes側は畳まない)。
    if raw.ndim == 3 and raw.shape[1] == 1:
        raw = raw[:, 0, :]
    if raw.ndim != 2 or raw.shape[0] != batch.shape[0]:
        raise LaughAudioError(
            f"modelの出力shapeが (batch, classes) ではありません: {list(raw.shape)}"
        )
    if max(indices) >= raw.shape[1]:
        raise LaughAudioError(
            f"label fileのclass数({max(indices) + 1}以上)がmodelの出力数({raw.shape[1]})を"
            "超えています。modelとlabel fileの組み合わせを確認してください。"
        )
    probs = _activate(raw)
    return [float(v) for v in probs[:, indices].max(axis=1)]


def _ffmpeg_args(source) -> list:
    """音声だけをmono/16kHzのs16le rawでpipeへ出すffmpegのargv。

    ``_RESAMPLE_FILTER`` は波形と同じもので、HLS由来の音声欠落を無音で埋めて
    「sample数 = PTS上の尺」にする。これが無いと確率列のindexが尺の末尾へ向かって
    手前へずれ、笑った時刻が実際より早く報告される。"""
    return [
        "ffmpeg", "-v", "error", "-nostdin", *source.input_args, "-i", str(source.path),
        "-vn", "-map", "0:a:0", "-af", _RESAMPLE_FILTER,
        "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-",
    ]


def _scan(source, model: _Model, indices: list, win_samples: int, hop_samples: int,
          batch_size: int) -> tuple:
    """音声をpipeで受けながら窓へ切り、確率列と総sample数を返す。

    全sampleをmemoryへ載せない: 3時間の録画は16kHz float32で690MBになる。保持するのは
    「まだ窓に満たない端数 + 1 chunk」だけで、窓が揃うたびbatchへ流して捨てる。
    """
    src = source.path
    args = _ffmpeg_args(source)
    try:
        proc = subprocess.Popen(
            args, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            bufsize=READ_CHUNK_BYTES,
        )
    except OSError as exc:
        logger.error(
            "笑い声検出で %s のffmpegを起動できませんでした", src.name,
            extra={"event": "laugh.launch_failed",
                   "ctx": {"src": str(src), **ffmpeg_ctx(args), "error": str(exc)}},
            exc_info=True,
        )
        raise LaughAudioError(f"笑い声検出でffmpegを起動できませんでした: {exc}") from exc
    # pipeから読みながら進む経路なのでtimeoutは持てない(長尺の正常なdecodeを落とす)。
    # 取り消しはprocessの登録だけで届かせる — smile._scan と同じ形。
    cancel.register_process(proc)

    drain = _StderrDrain(proc.stderr)
    probs: list = []
    total = 0
    emitted = 0
    batch: list = []

    def flush() -> None:
        if batch:
            probs.extend(_batch_probs(model, batch, indices))
            batch.clear()

    try:
        buf = np.empty(0, dtype=np.float32)
        carry = b""
        # 窓が始まる前に読み飛ばすsample数(hop > window の設定でだけ0でなくなる)。
        skip = 0
        assert proc.stdout is not None
        while True:
            chunk = proc.stdout.read(READ_CHUNK_BYTES)
            if not chunk:
                break
            if carry:
                chunk = carry + chunk
            usable = len(chunk) - (len(chunk) % _BYTES_PER_SAMPLE)
            carry = chunk[usable:]
            if not usable:
                continue
            samples = np.frombuffer(
                chunk, dtype="<i2", count=usable // _BYTES_PER_SAMPLE
            ).astype(np.float32) / _FULL_SCALE
            total += samples.size
            if skip:
                dropped = min(skip, samples.size)
                samples = samples[dropped:]
                skip -= dropped
                if samples.size == 0:
                    continue
            buf = samples if buf.size == 0 else np.concatenate((buf, samples))
            while buf.size >= win_samples:
                batch.append(buf[:win_samples])
                emitted += 1
                if len(batch) >= batch_size:
                    flush()
                if hop_samples <= buf.size:
                    buf = buf[hop_samples:]
                else:
                    skip = hop_samples - buf.size
                    buf = buf[:0]
        # 末尾。窓に満たない残りも0詰めして1窓として拾う — ここを捨てると、録画の
        # 最後の数秒だけが「笑いを判定していない」区間になる。
        while emitted * hop_samples < total:
            take = buf[:win_samples]
            if take.size < win_samples:
                take = np.concatenate(
                    (take, np.zeros(win_samples - take.size, dtype=np.float32))
                )
            batch.append(take)
            emitted += 1
            if len(batch) >= batch_size:
                flush()
            buf = buf[min(hop_samples, buf.size):]
        flush()
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
            "笑い声検出で %s の音声decodeに失敗しました", src.name,
            extra={"event": "laugh.decode_failed",
                   "ctx": {"src": str(src),
                           **ffmpeg_ctx(args, proc.returncode, stderr_text=message)}},
        )
        raise LaughAudioError(f"笑い声検出の音声decodeに失敗しました: {message[:300]}")
    if total == 0:
        logger.error(
            "笑い声検出が %s から音声を取得できませんでした", src.name,
            extra={"event": "laugh.no_audio",
                   "ctx": {"src": str(src),
                           **ffmpeg_ctx(args, proc.returncode, stderr_text=message)}},
        )
        raise LaughAudioError("録画に読み取れる音声streamがありません。")
    return probs, total


def _build(src: Path, window: float, hop: float) -> dict:
    """``src``の笑い確率列を作る。Blocking(CPU/IO律速)なのでthreadから呼ぶこと。"""
    model = _get_model()
    labels = _load_labels()
    classes = get_laugh_audio_classes()
    indices = _class_indices(labels, classes)

    win_samples = int(round(window * SAMPLE_RATE))
    hop_samples = int(round(hop * SAMPLE_RATE))
    if win_samples <= 0 or hop_samples <= 0:
        raise LaughAudioError("窓長・hopは正の秒数にしてください。")
    if model.fixed_samples and model.fixed_samples != win_samples:
        raise LaughAudioError(
            f"modelは{model.fixed_samples / SAMPLE_RATE:.3f}秒固定でexportされています"
            f"（TICTOK_LAUGH_AUDIO_WINDOW_SECONDS を合わせてください）。"
        )
    batch_size = model.fixed_batch or max(1, get_laugh_audio_batch())

    started = time.monotonic()
    with hls_source.ffmpeg_source(src) as source:
        probs, total = _scan(source, model, indices, win_samples, hop_samples, batch_size)
    duration = total / SAMPLE_RATE
    profile = {
        "interval_seconds": round(hop, 3),
        "duration_seconds": round(duration, 3),
        "probs": [round(p, _PROB_DECIMALS) for p in probs],
        "window_seconds": round(window, 3),
        "hop_seconds": round(hop, 3),
        "classes": classes,
        # 生成時の既定閾値。適用はせず、後から掃引するときの出発点として残す。
        "threshold": get_laugh_audio_threshold(),
        "activation": get_laugh_audio_activation(),
        "sample_rate": SAMPLE_RATE,
        **_model_fingerprint(),
    }
    elapsed = time.monotonic() - started
    logger.info(
        "笑い声profileを作成しました: %s（音声 %.1fs, %d windows）",
        src.name, duration, len(probs),
        extra={"event": "laugh.built",
               "ctx": {"src": str(src), "windows": len(probs),
                       "duration_seconds": profile["duration_seconds"],
                       "window_seconds": profile["window_seconds"],
                       "hop_seconds": profile["hop_seconds"],
                       "classes": classes, "batch": batch_size,
                       "realtime_factor": round(duration / elapsed, 2) if elapsed > 0 else None,
                       "duration_ms": int(elapsed * 1000)}},
    )
    return profile


def _source_key(src: Path) -> dict:
    """cacheの有効性を判定する素材の指紋(波形cacheと同じ作り)。"""
    key = hls_source.fingerprint(src)
    return {**key, "mtime": round(key["mtime"], 3)}


def _key_matches(data: dict, key: dict) -> bool:
    return all(data.get(name) == value for name, value in key.items())


def _load_cache(src: Path, window: float, hop: float) -> dict:
    """有効なcacheがあれば戻り値dictを、無ければ空dictを返す。

    **閾値はcacheの鍵に含めない。** 保存してあるのは閾値を掛ける前の生確率なので、
    閾値を変えても作り直す必要が無い(それがこの形で保存している理由でもある)。
    窓長・hop・class・modelは確率そのものを変えるので鍵に含める。"""
    path = laugh_profile_path(src)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if data.get("version") != _PROFILE_VERSION:
        return {}
    if data.get("interval_seconds") != round(hop, 3):
        return {}
    if data.get("window_seconds") != round(window, 3):
        return {}
    if data.get("classes") != get_laugh_audio_classes():
        return {}
    if data.get("activation") != get_laugh_audio_activation():
        return {}
    try:
        if not _key_matches(data, _model_fingerprint()):
            return {}
        key = _source_key(src)
    except (OSError, hls_source.SourceMissing):
        return {}
    if not _key_matches(data, key):
        return {}
    probs = data.get("probs")
    if not isinstance(probs, list):
        return {}
    return {name: value for name, value in data.items()
            if name not in _CACHE_ONLY_KEYS}


def _store_cache(src: Path, profile: dict) -> None:
    """cacheを書く。書けなくても確率列自体は返せるので、失敗は警告に留める
    (次回もう一度解析が走るだけで、結果は正しい)。"""
    path = laugh_profile_path(src)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": _PROFILE_VERSION, **_source_key(src), **profile}
        tmp = path.with_suffix(f"{path.suffix}.{os.getpid()}-{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        logger.warning(
            "%s の笑い声profile cacheの書き込みに失敗しました", src.name,
            extra={"event": "laugh.cache_write_failed",
                   "ctx": {"src": str(src), "path": str(path), "error": str(exc)}},
        )


async def ensure_laugh_profile(src: Path) -> dict:
    """``src``の笑い確率列を返す(cacheがあればそれを、無ければ解析してcacheする)。

    戻り値: ``{"interval_seconds": float, "duration_seconds": float,
    "probs": list[float], ...}``。probsは0.0〜1.0の**生確率**で、閾値は掛かっていない。
    区間の判定は ``laugh_seconds`` を使うこと。

    解析はCPU/IO律速でeventloopを塞ぐため、生成部はto_threadへ逃がす。
    """
    src = Path(src)
    if not get_laugh_audio_enabled():
        raise LaughAudioError(
            "笑い声検出が無効です（TICTOK_LAUGH_AUDIO_ENABLED=1 を設定してください）。"
        )
    window = get_laugh_audio_window_seconds()
    hop = get_laugh_audio_hop_seconds()
    if window <= 0 or hop <= 0:
        raise LaughAudioError("窓長・hopは正の秒数にしてください。")
    if not hls_source.available(src):
        raise hls_source.SourceMissing()
    # cacheに当てる前にmodelの指紋を確定させる。設定が壊れている状態で古いcacheを
    # 返すと、modelを直したつもりが直っていないことに気付けない。
    _model_fingerprint()

    cached = await asyncio.to_thread(_load_cache, src, window, hop)
    if cached:
        return cached

    if not ffmpeg_available():
        raise LaughAudioError("ffmpegが見つかりません。笑い声検出にはffmpegのinstallが必要です。")

    async with _lock_for(str(src.resolve())):
        cached = await asyncio.to_thread(_load_cache, src, window, hop)
        if cached:
            return cached
        if get_laugh_audio_device() == "cpu":
            profile = await asyncio.to_thread(_build, src, window, hop)
        else:
            # GPUはこのprocessへ載せない(cuDNNの同居でserverごと落ちる)。境界の説明は
            # laugh_worker の module docstring。
            from tictok.media import laugh_worker
            profile = await asyncio.to_thread(laugh_worker.run_build, src, window, hop)
        await asyncio.to_thread(_store_cache, src, profile)
    return profile


def laugh_seconds(profile: dict, start: float, end: float,
                  threshold: Optional[float] = None,
                  exclude_spans: Optional[list] = None) -> Optional[float]:
    """``[start, end)``秒のうち笑いが出ていた秒数。区間がprofileの外なら判定不能でNone。

    確率列は ``interval_seconds`` 刻みなので、閾値を超えた刻みの数 × 刻み幅を返す。
    Noneを0で埋めないのは ``waveform.level_peak`` と同じ理由で、解析していない区間と
    「笑いが無かった区間」を混ぜると、前者が静かな区間として集計に入ってしまうため。

    ``exclude_spans`` (``[(start, end), ...]``秒)に入る刻みは数えない。コラボ中を外す
    ための口で、窓の作り方はここでは決めない — 画面の顔の数から作るなら
    ``smile.multi_face_spans``、DBの事実から作るなら呼び出し側で組む。engineが窓の
    出所を知らないのは ``smile.without_spans`` と同じ方針で、素材だけで再現できる状態を
    保つためである。

    除外はsidecarを書き換えない。窓の定義を変えても再解析は要らない(閾値と同じ扱い)。
    """
    interval = profile["interval_seconds"]
    probs = profile["probs"]
    if interval <= 0 or end <= start or start < 0:
        return None
    first = int(start / interval)
    last = min(len(probs), int(round(end / interval)))
    if first >= last or first >= len(probs):
        return None
    threshold = get_laugh_audio_threshold() if threshold is None else threshold
    excluded = _excluded_ticks(exclude_spans, interval, first, last)
    hits = sum(1 for i in range(first, last)
               if probs[i] >= threshold and i not in excluded)
    return round(hits * interval, 3)


def _excluded_ticks(spans: Optional[list], interval: float,
                    first: int, last: int) -> set:
    """``spans`` が覆う刻みindexの集合(``[first, last)`` の範囲だけ)。

    刻みは ``[i*interval, (i+1)*interval)`` を表すので、窓と少しでも重なる刻みを外す。
    中心が入るかで判定すると、刻みより短い窓が1つも外れない。"""
    if not spans:
        return set()
    ticks: set = set()
    for span_start, span_end in spans:
        if span_end <= span_start:
            continue
        lo = max(first, int(float(span_start) / interval))
        hi = min(last, int(_math.ceil(float(span_end) / interval)))
        ticks.update(range(lo, hi))
    return ticks
