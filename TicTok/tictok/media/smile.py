"""録画の映像から「画面に1人だけ映っている顔の笑顔らしさ」の時系列を作る。

見どころ候補に「配信者が笑っている/喜んでいる点」を使いたい、というのがこのmoduleの
出発点である。コメントの笑い(:mod:`tictok.core.laugh_text`)と笑い声
(:mod:`tictok.media.laugh_audio`)は既にあるが、無言で笑っている瞬間はどちらにも現れない。
ここは映像側の1本を埋める: 固定刻みでframeを1枚抜き、顔検出 → 表情分類の2段へ通し、
標本ごとの確率をsidecarへ残す。

== この指標が名乗れること・名乗れないこと ==

**この検出は「配信者が笑ったか」を答えていない。** 答えているのは「その時刻のframeに顔が
ちょうど1つ映っていて、その顔が笑顔と判定された」である。両者の差は実映像で確認済みの
2点から来る:

1. **battle・collab中は画面が分割され、配信者以外の顔が同時に映る。** 相手や共演者が
   笑っていても、単純な最大値を採る実装ならそれを配信者の笑顔として報告してしまう。
2. **どの顔が配信者かを画面から決める手段が現状無い。** 分割のlayoutは1v1と多人数で
   変わり(個人マルチもteam構造で届く)、配信者の枠が常に同じ位置に来る保証は無い。
   顔の大小でも決まらない — 相手の枠の方が大きい配置は普通にある。配信者の顔写真も
   持っていないので、照合で当てることもできない。

採った方針は **顔が2つ以上見えた標本を捨てる** ことである(``scores`` に ``null`` を入れ、
``faces`` に実際の検出数を残す)。理由:

- 最大値/平均は、誰の表情か分からない値を配信者の値として名乗ることになる。この指標は
  見どころの根拠として画面に出るので、根拠が別人でしたという壊れ方が最も高くつく。
- 領域を固定して配信者の枠だけを見る案は、layoutを座標で決め打ちすることになり
  (禁止事項の hard-code そのもの)、layoutが変わった録画で静かに別人を見続ける。

**顔が1つでも配信者だとは限らない。** battle中に配信者のcameraが暗く、相手だけが検出される
状況は起こり得る。この身元の不確かさは検出だけでは解けないので、
battle・collabの窓はDB側(``collab_windows`` / battle判定)が持っている事実で外すこと。
そのための道具が :func:`without_spans` で、sidecarを作り直さずに窓内の標本を判定不能へ
落とせる。ここでDBを読まないのは、engineを素材だけで再現可能に保つためである。

顔が0個の標本も ``null`` にする。「顔が映っていない」は「笑っていない」ではない。

== なぜ全frameを見ないのか ==

3時間の録画は30fpsで32万frameある。顔検出は1枚あたり数msなので全frameでは1時間を超え、
「後から一括で回す解析」の予算に収まらない。笑顔は数秒続く表情なので、既定2秒刻みで
立ち上がりを落とす確率は低い(刻みは ``TICTOK_SMILE_SAMPLE_SECONDS``)。

== なぜCPUなのか ==

推論はonnxruntimeの **CPUExecutionProvider 固定**である。:mod:`tictok.media.laugh_audio`
と同じ理由で、GPU 12GBはfaster-whisper(転写)と超解像が奪い合っており、ここが
``gpu_slot`` を取るとその間だけ焼き込みが待たされる。顔検出modelも表情分類modelもtiny級で、
CPUでも実時間の数十倍で流せる。

== なぜ閾値を掛ける前の生確率を保存するのか ==

sidecarへ書くのは0.0〜1.0の**生確率**(または判定不能の ``null``)で、真偽値ではない。
閾値は素材(照明・カメラ・配信者)で最適値が変わり、今の既定値が正しいという根拠はまだ
無い。生確率を残しておけば後から閾値を掃引でき、閾値を変えても再解析が要らない。閾値の
適用は問い合わせ側(:func:`smile_seconds`)にだけ置く。

== Fallbackを持たない ==

無効・onnxruntime未導入・model未設定・読み込み失敗・推論失敗・graphの形が契約と違う、は
いずれも :class:`SmileError` で返す。0や中立値(0.5)を返すのが最悪で、「笑っていなかった
区間」と「そもそも判定していない区間」が区別できなくなる。

前処理の定数(mean/scale)・活性化・class順は **modelの契約**なので推測しない。既定値は
``doc/SMILE_MODEL.md`` の参照exportに合わせた設定値で、別のweightsを置くなら上書きする。

== 実装上の決まり ==

frameの取り出しは ``hls_source.ffmpeg_source`` を必ず通す。mp4が無い録画(=.tsだけ)は普通に
あり、``Path(src)`` を直接ffmpegへ渡すとそれらの録画で機能が黙って沈黙する。解像度が変わる
録画では、何も指定しないとffmpegが**開いた所の寸法**でfilter graphを固定して切替後のframeを
そこへ縮めるので(``upscale._probe_video`` の実測)、全編に現れる解像度の最大を枠に採って
``recorder._normalize_filter`` で揃える。

stderrの吸い出しは ``waveform._StderrDrain`` を**共有**する(写して持たない)。stdoutを読み
切ってからstderrを読む実装は、警告がpipe bufferを埋めた時点で相互待ちになり実録画で無限
hangを再現済みである。
"""

import asyncio
import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import NamedTuple, Optional

import numpy as np

from tictok.core import cancel, ffprobe
from tictok.core.config import (
    get_normalize_scale_mode,
    get_smile_activation,
    get_smile_bucket_seconds,
    get_smile_crop_margin,
    get_smile_enabled,
    get_smile_face_mean,
    get_smile_face_min_height_ratio,
    get_smile_face_model_path,
    get_smile_face_nms_iou,
    get_smile_face_scale,
    get_smile_face_score_activation,
    get_smile_face_score_index,
    get_smile_face_threshold,
    get_smile_fold,
    get_smile_labels,
    get_smile_mean,
    get_smile_model_path,
    get_smile_positive_classes,
    get_smile_sample_seconds,
    get_smile_scale,
    get_smile_threads,
    get_smile_threshold,
    get_smile_work_width,
)
from tictok.media import hls_source
from tictok.media.waveform import _StderrDrain
from tictok.paths import PROJECT_ROOT
from tictok.record.recorder import (
    ProgressGate,
    _normalize_filter,
    ffmpeg_available,
    ffmpeg_ctx,
    ffprobe_available,
    sidecar_path,
)

logger = logging.getLogger("tictok.smile")

SMILE_SUFFIX = ".smile.json"
# sidecarのschema version。標本の採り方・判定不能の扱い・保存する項を変えたら上げる。
_PROFILE_VERSION = 1
# 確率の丸め桁。3桁あれば閾値の掃引に足り、JSONは半分以下になる。
_PROB_DECIMALS = 3
# expのoverflow警告を出さないためのlogitのclamp。sigmoid/softmaxはこの外側で飽和済み。
_LOGIT_CLAMP = 60.0
# 正規化boxの許容上限。これを超える値が来たexportはpixel座標を出しているので、
# 黙って読み替えず失敗させる(読み替えると枠が原点付近へ潰れ、顔が消える)。
_NORMALIZED_BOX_MAX = 1.5
# 進捗logと cancel を見るframe間隔。
_PROGRESS_EVERY_FRAMES = 20
# ffprobeの上限。長尺HLSでも数十秒で返る。実体は core.ffprobe(全経路で同じ値)。
_PROBE_TIMEOUT_SECONDS = ffprobe.DEFAULT_TIMEOUT_SECONDS
# sidecarにしか無いcache管理用の項。読み出したprofileへは混ぜない。
_CACHE_ONLY_KEYS = ("version", "mtime", "size", "segments",
                    "face_model", "face_model_size", "face_model_mtime",
                    "smile_model", "smile_model_size", "smile_model_mtime")


class SmileError(RuntimeError):
    """笑顔検出が無効・未導入・model不備・graph不一致・解析失敗のときに送出する。"""


class _Detector(NamedTuple):
    """読み込み済みの顔検出session と、graphから読めた入出力の制約。

    入力は ``(batch, 3, height, width)`` の固定寸で、出力は2本 — 最終次元2のscoreと
    最終次元4の正規化box。参照exportはこの形で、box decodeをgraph内で済ませている。
    anchor decodeが必要なexport(cls/obj/bbox/kpsをstrideごとに出すもの)は**受けない**:
    priorの作り方・varianceをこちらが推測することになり、少しでも学習時と違えば枠が
    静かにずれる。
    """

    session: object
    input_name: str
    score_name: str
    box_name: str
    width: int
    height: int
    path: str


class _Classifier(NamedTuple):
    """読み込み済みの表情分類session と、graphから読めた入力の制約。"""

    session: object
    input_name: str
    output_name: str
    width: int
    height: int
    # 1ならgrayscaleへ落として渡す(FER系のexportは1chが多い)。
    channels: int
    path: str


class _Models(NamedTuple):
    detector: _Detector
    classifier: _Classifier


_models: Optional[_Models] = None
_models_key = None
_models_lock = threading.Lock()
# 同一processでの並行推論を1本に束ねる。CPU推論は既にthreadを使い切っており、重ねても
# 速くならないうえ録画・転写からcoreを奪う。
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


def smile_profile_path(src) -> Path:
    """``src``の笑顔判定列のsidecar path。"""
    return sidecar_path(src, SMILE_SUFFIX)


def smile_artifact_paths(src) -> tuple:
    """``src``の笑顔検出の成果物一式。srcを消す側が取りこぼさないよう列挙で返す。"""
    return (smile_profile_path(src),)


def smile_available() -> bool:
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


def _face_model_file() -> Optional[Path]:
    return _resolve(get_smile_face_model_path())


def _smile_model_file() -> Optional[Path]:
    return _resolve(get_smile_model_path())


def smile_status() -> dict:
    available = smile_available()
    face = _face_model_file()
    smile = _smile_model_file()
    return {
        "enabled": get_smile_enabled(),
        "available": available,
        "configured": bool(
            get_smile_enabled() and available
            and face is not None and face.is_file()
            and smile is not None and smile.is_file()
        ),
        "face_model": face.name if face is not None else "",
        "smile_model": smile.name if smile is not None else "",
        "labels": get_smile_labels(),
        "positive_classes": get_smile_positive_classes(),
        "sample_seconds": get_smile_sample_seconds(),
        "threshold": get_smile_threshold(),
        "device": "cpu",
    }


def _model_fingerprint() -> dict:
    """cacheの鍵に混ぜる2つのmodelの指紋。weightsを差し替えたら確率が変わるので、
    素材が同じでもcacheは無効にしなければならない。"""
    fingerprint = {}
    for prefix, path, setting in (
        ("face", _face_model_file(), "TICTOK_SMILE_FACE_MODEL_PATH"),
        ("smile", _smile_model_file(), "TICTOK_SMILE_MODEL_PATH"),
    ):
        if path is None:
            raise SmileError(f"笑顔検出のmodelが未設定です（{setting} を設定してください）。")
        try:
            stat = path.stat()
        except OSError as exc:
            raise SmileError(f"笑顔検出のmodel fileが見つかりません: {path}") from exc
        fingerprint[f"{prefix}_model"] = path.name
        fingerprint[f"{prefix}_model_size"] = stat.st_size
        fingerprint[f"{prefix}_model_mtime"] = round(stat.st_mtime, 3)
    return fingerprint


def _class_indices(labels: list, classes: list) -> list:
    """設定されたclass名を出力indexへ解く。1つでも表に無ければ例外。

    無いものを黙って外すと、綴り違いのclassが1つ混じっただけで笑顔が一切検出されなくなり、
    「笑わない配信者」に見えてしまう。"""
    if not classes:
        raise SmileError(
            "笑顔とみなすclassが未設定です（TICTOK_SMILE_POSITIVE_CLASSES を設定してください）。"
        )
    lookup: dict = {}
    for i, name in enumerate(labels):
        lookup.setdefault(name, i)
    missing = [name for name in classes if name not in lookup]
    if missing:
        raise SmileError(
            f"class名の表に無いclassが指定されています: {missing}（区切りは | です）"
        )
    return [lookup[name] for name in classes]


def _int_dim(value) -> int:
    """graphのshape要素が固定の正整数ならその値、可変なら0。"""
    return value if isinstance(value, int) and value > 0 else 0


def _describe_detector(session, model_file: Path) -> _Detector:
    """顔検出graphの入出力を検査して :class:`_Detector` を組む。"""
    inputs = session.get_inputs()
    if len(inputs) != 1:
        raise SmileError(
            f"顔検出modelは入力が1つのexportにしてください（このmodelの入力: "
            f"{[i.name for i in inputs]}）。"
        )
    shape = list(inputs[0].shape or [])
    if len(shape) != 4:
        raise SmileError(
            f"顔検出modelの入力は (batch, channels, height, width) にしてください"
            f"（このmodelの入力shape: {shape}）。"
        )
    channels, height, width = _int_dim(shape[1]), _int_dim(shape[2]), _int_dim(shape[3])
    if channels != 3:
        raise SmileError(
            f"顔検出modelの入力は3ch(RGB)のexportにしてください（このmodelのch数: {shape[1]}）。"
        )
    if not height or not width:
        raise SmileError(
            "顔検出modelの入力寸が可変です。letterboxの寸法が決まらないため、寸法を固定して"
            f"exportしてください（このmodelの入力shape: {shape}）。"
        )
    outputs = session.get_outputs()
    if len(outputs) != 2:
        raise SmileError(
            "顔検出modelは score と box の2出力にしてください（stride別のcls/obj/bbox/kpsを"
            "出すexportは、priorとvarianceをこちらが推測することになるため受けません）"
            f"。このmodelの出力: {[o.name for o in outputs]}"
        )
    names: dict = {}
    for out in outputs:
        oshape = list(out.shape or [])
        last = _int_dim(oshape[-1]) if oshape else 0
        if last == 2:
            names.setdefault("score", out.name)
        elif last == 4:
            names.setdefault("box", out.name)
    if "score" not in names or "box" not in names:
        raise SmileError(
            "顔検出modelの出力から score(最終次元2) と box(最終次元4) を見分けられません"
            f"（出力shape: {[list(o.shape or []) for o in outputs]}）。"
        )
    return _Detector(session, inputs[0].name, names["score"], names["box"],
                     width, height, str(model_file))


def _describe_classifier(session, model_file: Path) -> _Classifier:
    """表情分類graphの入出力を検査して :class:`_Classifier` を組む。"""
    inputs = session.get_inputs()
    if len(inputs) != 1:
        raise SmileError(
            f"表情分類modelは入力が1つのexportにしてください（このmodelの入力: "
            f"{[i.name for i in inputs]}）。"
        )
    shape = list(inputs[0].shape or [])
    if len(shape) != 4:
        raise SmileError(
            f"表情分類modelの入力は (batch, channels, height, width) にしてください"
            f"（このmodelの入力shape: {shape}）。"
        )
    channels, height, width = _int_dim(shape[1]), _int_dim(shape[2]), _int_dim(shape[3])
    if channels not in (1, 3):
        raise SmileError(
            f"表情分類modelの入力は1ch(grayscale)か3ch(RGB)にしてください"
            f"（このmodelのch数: {shape[1]}）。"
        )
    if not height or not width:
        raise SmileError(
            "表情分類modelの入力寸が可変です。顔の切り出し寸が決まらないため、寸法を固定して"
            f"exportしてください（このmodelの入力shape: {shape}）。"
        )
    outputs = session.get_outputs()
    if not outputs:
        raise SmileError("表情分類modelに出力がありません。")
    return _Classifier(session, inputs[0].name, outputs[0].name,
                       width, height, channels, str(model_file))


def _load_session(model_file: Path, threads: int, kind: str):
    """ONNX 1本をCPUで読み込む。``SmileError``で失敗を返す。"""
    import onnxruntime as ort

    started = time.monotonic()
    options = ort.SessionOptions()
    if threads > 0:
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
    logger.info(
        "笑顔検出の %s modelを読み込みます: %s（threads=%d）",
        kind, model_file, threads,
        extra={"event": "smile.model_load_started",
               "ctx": {"kind": kind, "path": str(model_file), "threads": threads,
                       "size_bytes": model_file.stat().st_size}},
    )
    try:
        session = ort.InferenceSession(
            str(model_file), sess_options=options, providers=["CPUExecutionProvider"],
        )
    except Exception as exc:
        logger.error(
            "%s model %s を読み込めませんでした", kind, model_file.name,
            extra={"event": "smile.model_load_failed",
                   "ctx": {"kind": kind, "path": str(model_file), "threads": threads,
                           "duration_ms": int((time.monotonic() - started) * 1000)}},
            exc_info=True,
        )
        raise SmileError(f"笑顔検出modelの読み込みに失敗しました（{kind}）: {exc}") from exc
    return session


def _get_models() -> _Models:
    """設定された2つのONNX modelをCPUで読み込む(cacheする)。"""
    if not get_smile_enabled():
        raise SmileError("笑顔検出が無効です（TICTOK_SMILE_ENABLED=1 を設定してください）。")
    try:
        import onnxruntime  # noqa: F401  (存在確認。実体は_load_sessionが使う)
    except ImportError as exc:
        raise SmileError(
            "onnxruntime が未インストールです（pip install onnxruntime）。"
        ) from exc
    face = _face_model_file()
    smile = _smile_model_file()
    if face is None:
        raise SmileError(
            "顔検出modelが未設定です（TICTOK_SMILE_FACE_MODEL_PATH を設定してください）。"
        )
    if smile is None:
        raise SmileError(
            "表情分類modelが未設定です（TICTOK_SMILE_MODEL_PATH を設定してください）。"
        )
    for path in (face, smile):
        if not path.is_file():
            raise SmileError(f"笑顔検出のmodel fileが見つかりません: {path}")
    threads = get_smile_threads()
    key = (str(face), str(smile), threads)
    global _models, _models_key
    with _models_lock:
        if _models is None or _models_key != key:
            detector = _describe_detector(_load_session(face, threads, "face"), face)
            classifier = _describe_classifier(
                _load_session(smile, threads, "smile"), smile)
            _models = _Models(detector, classifier)
            _models_key = key
            logger.info(
                "笑顔検出のmodelを準備しました: %s + %s（cpu）", face.name, smile.name,
                extra={"event": "smile.models_loaded",
                       "ctx": {"face_model": str(face), "smile_model": str(smile),
                               "face_input": [detector.height, detector.width],
                               "smile_input": [classifier.channels, classifier.height,
                                               classifier.width],
                               "threads": threads}},
            )
    return _models


def _softmax(raw: np.ndarray) -> np.ndarray:
    shifted = np.clip(raw - raw.max(axis=-1, keepdims=True), -_LOGIT_CLAMP, 0.0)
    exp = np.exp(shifted)
    return exp / exp.sum(axis=-1, keepdims=True)


def _activate(raw: np.ndarray, activation: str, setting: str) -> np.ndarray:
    if activation == "softmax":
        return _softmax(raw)
    if activation == "sigmoid":
        return 1.0 / (1.0 + np.exp(-np.clip(raw, -_LOGIT_CLAMP, _LOGIT_CLAMP)))
    if activation == "none":
        return raw
    raise SmileError(
        f"{setting} は softmax / sigmoid / none にしてください（現在 {activation!r}）。"
    )


def _letterbox(frame: np.ndarray, width: int, height: int) -> tuple:
    """``frame``(h, w, 3 uint8)を縦横比のまま ``width x height`` へ収め、余りを黒で埋める。

    比を無視して引き伸ばす案は採らない: 参照exportの入力は4:3で、9:16の配信frameを
    そこへ潰すと顔が横に広がり、学習時の顔と形が変わって検出率が落ちる。

    戻り値は ``(canvas, scale_x, scale_y, pad_x, pad_y)``。scaleを軸ごとに返すのは、
    寸法を整数へ丸めた後の実比率で枠をframe座標へ戻すため(共通のscaleを使うと丸めぶんだけ
    枠がずれる)。
    """
    from PIL import Image

    src_h, src_w = frame.shape[:2]
    ratio = min(width / src_w, height / src_h)
    new_w = max(1, min(width, int(round(src_w * ratio))))
    new_h = max(1, min(height, int(round(src_h * ratio))))
    resized = np.asarray(
        Image.fromarray(frame).resize((new_w, new_h), Image.BILINEAR), dtype=np.uint8)
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    pad_x, pad_y = (width - new_w) // 2, (height - new_h) // 2
    canvas[pad_y:pad_y + new_h, pad_x:pad_x + new_w] = resized
    return canvas, new_w / src_w, new_h / src_h, pad_x, pad_y


def _nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> list:
    """hard NMS。scoreの高い枠から採り、IoUが閾値を超える枠を落としたindexを返す。

    同じ顔に複数の枠が残ると「顔が2つ」と数えられ、その標本が判定不能へ落ちる。重複除去は
    検出の精度のためというより、判定を捨てすぎないために要る。
    """
    order = np.argsort(-scores)
    areas = ((boxes[:, 2] - boxes[:, 0]).clip(min=0.0)
             * (boxes[:, 3] - boxes[:, 1]).clip(min=0.0))
    keep: list = []
    while order.size:
        i = int(order[0])
        keep.append(i)
        if order.size == 1:
            break
        rest = order[1:]
        x1 = np.maximum(boxes[i, 0], boxes[rest, 0])
        y1 = np.maximum(boxes[i, 1], boxes[rest, 1])
        x2 = np.minimum(boxes[i, 2], boxes[rest, 2])
        y2 = np.minimum(boxes[i, 3], boxes[rest, 3])
        inter = (x2 - x1).clip(min=0.0) * (y2 - y1).clip(min=0.0)
        union = np.maximum(areas[i] + areas[rest] - inter, 1e-9)
        order = rest[(inter / union) <= iou_threshold]
    return keep


def _faces(detector: _Detector, frame: np.ndarray) -> list:
    """``frame``に映る顔の枠 ``[(x1, y1, x2, y2, score), ...]``(frame座標・px)。"""
    canvas, scale_x, scale_y, pad_x, pad_y = _letterbox(
        frame, detector.width, detector.height)
    mean, scale = get_smile_face_mean(), get_smile_face_scale()
    if scale == 0:
        raise SmileError("TICTOK_SMILE_FACE_SCALE に0は指定できません。")
    batch = ((canvas.astype(np.float32) - mean) / scale).transpose(2, 0, 1)[None]
    try:
        with _infer_lock:
            raw_scores, raw_boxes = detector.session.run(
                [detector.score_name, detector.box_name], {detector.input_name: batch})
    except Exception as exc:
        raise SmileError(f"顔検出の推論に失敗しました: {exc}") from exc
    scores = np.asarray(raw_scores, dtype=np.float32).reshape(-1, 2)
    boxes = np.asarray(raw_boxes, dtype=np.float32).reshape(-1, 4)
    if scores.shape[0] != boxes.shape[0]:
        raise SmileError(
            f"顔検出modelのscore数({scores.shape[0]})とbox数({boxes.shape[0]})が違います。"
        )
    index = get_smile_face_score_index()
    if not 0 <= index < 2:
        raise SmileError(
            f"TICTOK_SMILE_FACE_SCORE_INDEX は0か1にしてください（現在 {index}）。")
    if boxes.size and float(np.max(np.abs(boxes))) > _NORMALIZED_BOX_MAX:
        raise SmileError(
            "顔検出modelのboxが正規化座標(0.0〜1.0)ではありません。pixel座標を出すexportは"
            "受けません（枠を読み替えると顔が静かに消えます）。"
        )
    probs = _activate(scores, get_smile_face_score_activation(),
                      "TICTOK_SMILE_FACE_SCORE_ACTIVATION")[:, index]
    keep = probs >= get_smile_face_threshold()
    if not bool(keep.any()):
        return []
    probs, boxes = probs[keep], boxes[keep]
    # 正規化座標 → letterbox canvasのpx → frameのpx。
    boxes = boxes * np.array([detector.width, detector.height,
                              detector.width, detector.height], dtype=np.float32)
    boxes[:, 0] = (boxes[:, 0] - pad_x) / scale_x
    boxes[:, 2] = (boxes[:, 2] - pad_x) / scale_x
    boxes[:, 1] = (boxes[:, 1] - pad_y) / scale_y
    boxes[:, 3] = (boxes[:, 3] - pad_y) / scale_y
    kept = _nms(boxes, probs, get_smile_face_nms_iou())
    min_height = get_smile_face_min_height_ratio() * frame.shape[0]
    return [
        (float(boxes[i, 0]), float(boxes[i, 1]), float(boxes[i, 2]), float(boxes[i, 3]),
         float(probs[i]))
        for i in kept
        if boxes[i, 3] - boxes[i, 1] >= min_height
    ]


def _face_input(classifier: _Classifier, frame: np.ndarray, box: tuple) -> np.ndarray:
    """顔の枠を余白ぶん広げて切り出し、modelの入力寸へ整えたbatchを返す。"""
    from PIL import Image

    src_h, src_w = frame.shape[:2]
    x1, y1, x2, y2 = box[:4]
    margin = get_smile_crop_margin()
    pad_x, pad_y = (x2 - x1) * margin, (y2 - y1) * margin
    left = int(max(0, round(x1 - pad_x)))
    top = int(max(0, round(y1 - pad_y)))
    right = int(min(src_w, round(x2 + pad_x)))
    bottom = int(min(src_h, round(y2 + pad_y)))
    if right - left < 1 or bottom - top < 1:
        raise SmileError("顔の切り出し範囲が空になりました。")
    image = Image.fromarray(frame).crop((left, top, right, bottom))
    image = image.convert("L" if classifier.channels == 1 else "RGB")
    image = image.resize((classifier.width, classifier.height), Image.BILINEAR)
    scale = get_smile_scale()
    if scale == 0:
        raise SmileError("TICTOK_SMILE_SCALE に0は指定できません。")
    array = (np.asarray(image, dtype=np.float32) - get_smile_mean()) / scale
    if classifier.channels == 1:
        return array.reshape(1, 1, classifier.height, classifier.width)
    return array.transpose(2, 0, 1)[None]


def _smile_score(classifier: _Classifier, frame: np.ndarray, box: tuple,
                 indices: list, label_count: int) -> float:
    """1つの顔の「笑顔・喜び」確率。設定されたpositive classを畳んで返す。"""
    batch = _face_input(classifier, frame, box)
    try:
        with _infer_lock:
            raw = classifier.session.run(
                [classifier.output_name], {classifier.input_name: batch})[0]
    except Exception as exc:
        raise SmileError(f"表情分類の推論に失敗しました: {exc}") from exc
    raw = np.asarray(raw, dtype=np.float32).reshape(-1)
    if raw.size != label_count:
        raise SmileError(
            f"表情分類modelの出力数({raw.size})とclass名の数({label_count})が合いません。"
            "modelとTICTOK_SMILE_LABELSの組み合わせを確認してください。"
        )
    probs = _activate(raw, get_smile_activation(), "TICTOK_SMILE_ACTIVATION")
    fold = get_smile_fold()
    if fold == "sum":
        return float(min(1.0, probs[indices].sum()))
    if fold == "max":
        return float(probs[indices].max())
    raise SmileError(f"TICTOK_SMILE_FOLD は sum か max にしてください（現在 {fold!r}）。")


def _probe_duration(source) -> float:
    """尺(秒)。読めなければ ``SmileError``。

    尺は標本数の期待値(=進捗の分母)と ``duration_seconds`` に要る。推測で埋めると、
    解析していない末尾を「笑いの無かった区間」として集計へ入れることになる。
    """
    if not ffprobe_available():
        raise SmileError("ffprobeが見つかりません。笑顔検出にはffmpeg一式のinstallが必要です。")
    args = ffprobe.duration_args(source.path, source.input_args)
    try:
        result = ffprobe.run_sync(args, timeout=_PROBE_TIMEOUT_SECONDS)
    except OSError as exc:
        logger.error(
            "笑顔検出のため %s の尺を取得できませんでした", source.path.name,
            extra={"event": "smile.probe_failed",
                   "ctx": {"src": str(source.path), **ffmpeg_ctx(args)}},
            exc_info=True,
        )
        raise SmileError(f"録画の尺を取得できませんでした: {exc}") from exc
    duration = ffprobe.parse_duration(result.stdout)
    if duration is None:
        logger.error(
            "笑顔検出のため %s の尺を取得できませんでした", source.path.name,
            extra={"event": "smile.probe_failed",
                   "ctx": {"src": str(source.path),
                           **ffmpeg_ctx(args, result.returncode,
                                        stderr_text=result.stderr)}},
        )
        raise SmileError(
            f"録画の尺を取得できませんでした: {result.stderr.strip()[:300]}")
    if duration <= 0:
        raise SmileError(f"録画の尺が不正です: {duration}")
    return duration


def _work_size(source) -> tuple:
    """解析に使うframeの寸法 ``(width, height)``。

    全編に現れる解像度の**最大**を基準にする。stream headerの1組は開いた所の値でしかなく、
    混在解像度の録画では全編を代表しない(``upscale._probe_video`` の実測)。源より大きくは
    引き伸ばさない — 拡大しても顔の情報は増えず、pipeとdecodeだけが重くなる。
    """
    found = hls_source.resolutions_sync(source)
    if not found:
        raise SmileError("録画の解像度を取得できませんでした。")
    src_w = max(w for w, _ in found)
    src_h = max(h for _, h in found)
    if src_w <= 0 or src_h <= 0:
        raise SmileError(f"録画の解像度が不正です: {src_w}x{src_h}")
    out_w = min(int(get_smile_work_width()), src_w)
    if out_w <= 0:
        raise SmileError("TICTOK_SMILE_WORK_WIDTH は正の値にしてください。")
    out_h = max(2, int(round(src_h * out_w / src_w)))
    return out_w - (out_w % 2), out_h - (out_h % 2)


def _ffmpeg_args(source, interval: float, width: int, height: int) -> list:
    """固定刻みのframeをrgb24 rawでpipeへ出すffmpegのargv。

    ``_normalize_filter`` を通すのは混在解像度の録画のためで、均一な録画では縦横比のまま
    ``width x height`` へ落ちるだけになる(padは発生しない)。寸法を明示するのは、pipeから
    読む1 frameのbyte数を確定させるため。
    """
    geometry = _normalize_filter(width, height, get_normalize_scale_mode())
    return [
        "ffmpeg", "-v", "error", "-nostdin", *source.input_args, "-i", str(source.path),
        "-an", "-sn", "-map", "0:v:0",
        "-vf", f"fps=1/{interval:.6f},{geometry}",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]


def _scan(source, models: _Models, indices: list, label_count: int, interval: float,
          width: int, height: int, expected: int) -> tuple:
    """frameを1枚ずつ受けながら顔検出→表情分類を掛け、``(scores, faces)`` を返す。

    ``scores[i]`` は ``i * interval`` 秒の標本で、顔がちょうど1つ見えた標本だけが確率を、
    それ以外(0個・2個以上)は ``None`` を持つ。``faces[i]`` はその標本の検出数で、
    「映っていなかった」と「誰の顔か分からなかった」を後から区別するために残す。
    """
    src = source.path
    args = _ffmpeg_args(source, interval, width, height)
    try:
        proc = subprocess.Popen(
            args, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except OSError as exc:
        logger.error(
            "笑顔検出で %s のffmpegを起動できませんでした", src.name,
            extra={"event": "smile.launch_failed",
                   "ctx": {"src": str(src), **ffmpeg_ctx(args), "error": str(exc)}},
            exc_info=True,
        )
        raise SmileError(f"笑顔検出でffmpegを起動できませんでした: {exc}") from exc
    cancel.register_process(proc)

    drain = _StderrDrain(proc.stderr)
    frame_bytes = width * height * 3
    scores: list = []
    faces: list = []
    gate = ProgressGate()
    started = time.monotonic()
    try:
        assert proc.stdout is not None
        while True:
            buf = proc.stdout.read(frame_bytes)
            if not buf:
                break
            if len(buf) != frame_bytes:
                raise SmileError(
                    f"decode中に不完全なframeを受信しました（{len(buf)}/{frame_bytes} byte）。")
            frame = np.frombuffer(buf, dtype=np.uint8).reshape(height, width, 3)
            found = _faces(models.detector, frame)
            faces.append(len(found))
            # 顔が2つ以上見えた標本は捨てる。誰の表情か決める手段が無い状態で最大値を採ると、
            # 相手や共演者の笑顔を配信者の笑顔として名乗ることになる(module docstring参照)。
            if len(found) == 1:
                scores.append(_smile_score(models.classifier, frame, found[0],
                                           indices, label_count))
            else:
                scores.append(None)
            done = len(scores)
            if done % _PROGRESS_EVERY_FRAMES == 0:
                cancel.check_cancelled()
                total = max(expected, done)
                percent = 100.0 * done / total
                if gate.due(percent):
                    elapsed = time.monotonic() - started
                    rate = done / elapsed if elapsed > 0 else 0.0
                    logger.info(
                        "%s の笑顔検出: %d/%d samples（%.1f%%）, %.2f samples/s",
                        src.name, done, total, percent, rate,
                        extra={"event": "smile.progress_reported",
                               "ctx": {"src": str(src), "samples_done": done,
                                       "samples": total, "percent": round(percent, 2),
                                       "samples_per_second": round(rate, 3),
                                       "duration_ms": int(elapsed * 1000)}},
                    )
    finally:
        # stdoutを閉じると、まだ書き残しがあるffmpegはEPIPEで自分から落ちる。ここでkillは
        # **しない**: 正常にEOFへ達した直後のffmpegはまだ終了処理中で poll() がNoneを返す
        # ことがあり、そこをkillすると成功した解析が「decode失敗」になる。cancelされた場合の
        # killは token 側(register_process済み)が引き受ける。
        if proc.stdout is not None:
            proc.stdout.close()
        message = drain.text()
        if proc.stderr is not None:
            proc.stderr.close()
        proc.wait()
        cancel.forget_process(proc)

    # cancelはkillしたffmpegを非0終了として見せるので、decode失敗より先に見る。
    cancel.check_cancelled()
    if proc.returncode != 0:
        logger.error(
            "笑顔検出で %s の映像decodeに失敗しました", src.name,
            extra={"event": "smile.decode_failed",
                   "ctx": {"src": str(src),
                           **ffmpeg_ctx(args, proc.returncode, stderr_text=message)}},
        )
        raise SmileError(f"笑顔検出の映像decodeに失敗しました: {message[:300]}")
    if not scores:
        logger.error(
            "笑顔検出が %s からframeを取得できませんでした", src.name,
            extra={"event": "smile.no_frames",
                   "ctx": {"src": str(src),
                           **ffmpeg_ctx(args, proc.returncode, stderr_text=message)}},
        )
        raise SmileError("録画から解析できるframeを取得できませんでした。")
    return scores, faces


def _build(src: Path, interval: float) -> dict:
    """``src``の笑顔判定列を作る。Blocking(CPU/IO律速)なのでthreadから呼ぶこと。"""
    models = _get_models()
    labels = get_smile_labels()
    if not labels:
        raise SmileError(
            "表情分類のclass名が未設定です（TICTOK_SMILE_LABELS を設定してください）。")
    positive = get_smile_positive_classes()
    indices = _class_indices(labels, positive)

    started = time.monotonic()
    with hls_source.ffmpeg_source(src) as source:
        duration = _probe_duration(source)
        width, height = _work_size(source)
        expected = max(1, int(duration / interval) + 1)
        scores, faces = _scan(source, models, indices, len(labels), interval,
                              width, height, expected)
    decided = sum(1 for value in scores if value is not None)
    profile = {
        "interval_seconds": round(interval, 3),
        "duration_seconds": round(duration, 3),
        "scores": [None if value is None else round(value, _PROB_DECIMALS)
                   for value in scores],
        "faces": faces,
        "labels": labels,
        "positive_classes": positive,
        "activation": get_smile_activation(),
        "fold": get_smile_fold(),
        # 生成時の既定閾値。適用はせず、後から掃引するときの出発点として残す。
        "threshold": get_smile_threshold(),
        "work_width": width,
        "work_height": height,
        "work_width_setting": int(get_smile_work_width()),
        "face_threshold": get_smile_face_threshold(),
        "face_nms_iou": get_smile_face_nms_iou(),
        "face_min_height_ratio": get_smile_face_min_height_ratio(),
        "face_score_activation": get_smile_face_score_activation(),
        "face_score_index": get_smile_face_score_index(),
        "crop_margin": get_smile_crop_margin(),
        **_model_fingerprint(),
    }
    elapsed = time.monotonic() - started
    logger.info(
        "笑顔profileを作成しました: %s（映像 %.1fs, %d samples, 判定 %d 件）",
        src.name, duration, len(scores), decided,
        extra={"event": "smile.built",
               "ctx": {"src": str(src), "samples": len(scores), "decided": decided,
                       "duration_seconds": profile["duration_seconds"],
                       "interval_seconds": profile["interval_seconds"],
                       "coverage": round(decided / len(scores), 3) if scores else None,
                       "multi_face_samples": sum(1 for n in faces if n > 1),
                       "no_face_samples": sum(1 for n in faces if n == 0),
                       "work_width": width, "work_height": height,
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


def _settings_key(interval: float) -> dict:
    """判定列そのものを変える設定。**最終閾値は入れない** — 保存してあるのは閾値を掛ける
    前の生確率なので、閾値を変えても作り直す必要が無い(それがこの形で保存する理由)。

    顔検出側の閾値・NMS・最小寸は入れる: これらは検出数を変え、検出数は「判定不能」の
    決まり方を変えるので、確率列そのものが変わる。

    解析寸は**実寸ではなく設定値**(``work_width_setting``)で比べる。実寸は源の幅で頭打ちに
    なるので(720pの録画に1080を設定しても実寸は720)、実寸で比べると「480で解析済みの
    720p録画に640を設定した」のような、本当に作り直すべき変更を取りこぼす。逆に頭打ちの
    録画では設定を上げたときに同じ絵で1度だけ作り直しになるが、取りこぼす側へ倒すより安い。
    """
    return {
        "interval_seconds": round(interval, 3),
        "labels": get_smile_labels(),
        "positive_classes": get_smile_positive_classes(),
        "activation": get_smile_activation(),
        "fold": get_smile_fold(),
        "work_width_setting": int(get_smile_work_width()),
        "face_threshold": get_smile_face_threshold(),
        "face_nms_iou": get_smile_face_nms_iou(),
        "face_min_height_ratio": get_smile_face_min_height_ratio(),
        "face_score_activation": get_smile_face_score_activation(),
        "face_score_index": get_smile_face_score_index(),
        "crop_margin": get_smile_crop_margin(),
    }


def _load_cache(src: Path, interval: float) -> dict:
    """有効なcacheがあれば戻り値dictを、無ければ空dictを返す。"""
    path = smile_profile_path(src)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if data.get("version") != _PROFILE_VERSION:
        return {}
    if not _key_matches(data, _settings_key(interval)):
        return {}
    try:
        if not _key_matches(data, _model_fingerprint()):
            return {}
        key = _source_key(src)
    except (OSError, SmileError, hls_source.SourceMissing):
        return {}
    if not _key_matches(data, key):
        return {}
    scores = data.get("scores")
    faces = data.get("faces")
    if not isinstance(scores, list) or not isinstance(faces, list):
        return {}
    if len(scores) != len(faces):
        return {}
    return {name: value for name, value in data.items()
            if name not in _CACHE_ONLY_KEYS}


def _store_cache(src: Path, profile: dict) -> None:
    """cacheを書く。書けなくても判定列自体は返せるので、失敗は警告に留める
    (次回もう一度解析が走るだけで、結果は正しい)。"""
    path = smile_profile_path(src)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": _PROFILE_VERSION, **_source_key(src), **profile}
        tmp = path.with_suffix(f"{path.suffix}.{os.getpid()}-{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        logger.warning(
            "%s の笑顔profile cacheの書き込みに失敗しました", src.name,
            extra={"event": "smile.cache_write_failed",
                   "ctx": {"src": str(src), "path": str(path), "error": str(exc)}},
        )


async def ensure_smile_profile(src: Path) -> dict:
    """``src``の笑顔判定列を返す(cacheがあればそれを、無ければ解析してcacheする)。

    戻り値: ``{"interval_seconds": float, "duration_seconds": float,
    "scores": list[float | None], "faces": list[int], ...}``。``scores`` は0.0〜1.0の
    **生確率**で閾値は掛かっておらず、判定できなかった標本は ``None`` である。区間の
    集計は :func:`smile_seconds` / :func:`smile_coverage` を使うこと。

    解析はCPU/IO律速でeventloopを塞ぐため、生成部はto_threadへ逃がす。
    """
    src = Path(src)
    if not get_smile_enabled():
        raise SmileError("笑顔検出が無効です（TICTOK_SMILE_ENABLED=1 を設定してください）。")
    interval = get_smile_sample_seconds()
    if interval <= 0:
        raise SmileError("frameを見る間隔は正の秒数にしてください。")
    if not hls_source.available(src):
        raise hls_source.SourceMissing()
    # cacheに当てる前にmodelの指紋を確定させる。設定が壊れている状態で古いcacheを返すと、
    # modelを直したつもりが直っていないことに気付けない。
    _model_fingerprint()

    cached = await asyncio.to_thread(_load_cache, src, interval)
    if cached:
        return cached

    if not ffmpeg_available():
        raise SmileError("ffmpegが見つかりません。笑顔検出にはffmpegのinstallが必要です。")

    async with _lock_for(str(src.resolve())):
        cached = await asyncio.to_thread(_load_cache, src, interval)
        if cached:
            return cached
        profile = await asyncio.to_thread(_build, src, interval)
        await asyncio.to_thread(_store_cache, src, profile)
    return profile


def _window(profile: dict, start: float, end: float) -> Optional[list]:
    """``[start, end)``秒に入る標本のlist。区間がprofileの外ならNone。"""
    interval = profile["interval_seconds"]
    scores = profile["scores"]
    if interval <= 0 or end <= start or start < 0:
        return None
    first = int(start / interval)
    last = min(len(scores), int(round(end / interval)))
    if first >= last or first >= len(scores):
        return None
    return scores[first:last]


def smile_seconds(profile: dict, start: float, end: float,
                  threshold: Optional[float] = None) -> Optional[float]:
    """``[start, end)``秒のうち**笑顔と判定できた**秒数。区間がprofileの外ならNone。

    正確には「顔がちょうど1つ映っていて、その顔の笑顔確率が閾値以上だった標本の数 ×
    刻み幅」である。配信者本人の笑顔とは名乗れない(module docstring参照)。

    判定不能な標本(顔が0個/2個以上)は**数えない**。その結果、battle中のように判定不能が
    続く区間は実際より小さい値になる — 過小に出る側へ倒しているのは意図で、標本の割合から
    区間全体へ引き伸ばすと、観測していない時間の笑顔を作り出すことになるからである。
    どれだけ観測できたかは :func:`smile_coverage` で別に取れる。

    区間内が全て判定不能でも(解析はしているので)0.0を返し、Noneにはしない。ここをNoneに
    すると、呼び出し側の指標登録(``server._MaterialMetric``)は最初のNoneで指標ごと外すため、
    顔が写らない60秒が1つあるだけで録画全体の笑顔指標が消える。「解析していない」= None と
    「観測できた笑顔が0秒」= 0.0 の線引きはここに引く。
    """
    window = _window(profile, start, end)
    if window is None:
        return None
    threshold = get_smile_threshold() if threshold is None else threshold
    hits = sum(1 for value in window if value is not None and value >= threshold)
    return round(hits * profile["interval_seconds"], 3)


def smile_coverage(profile: dict, start: float, end: float) -> Optional[float]:
    """``[start, end)``秒の標本のうち判定できた割合(0.0〜1.0)。区間が外ならNone。

    :func:`smile_seconds` が0秒だったとき、「笑っていなかった」のか「顔が見えず判定でき
    なかった」のかはこの値だけが区別できる。
    """
    window = _window(profile, start, end)
    if window is None:
        return None
    return round(sum(1 for value in window if value is not None) / len(window), 3)


def multi_face_spans(profile: dict, min_faces: int = 2) -> list:
    """顔が ``min_faces`` 個以上映っていた区間 ``[(start, end), ...]`` (秒)を返す。

    「画面に何人映っているか」は素材そのものから読める唯一の事実で、コラボ・battleの
    区間を**DBの窓に頼らずに**外すために使う。実測でDB側の ``collab_windows`` は
    ``guests_max`` が811窓中805窓で0のまま(名簿が届かない窓ではそのまま確定する)なので、
    「何人いたか」では絞れない。こちらは1標本ごとに実際の検出数を持っている。

    隣り合う標本は連結して1つの区間にする。区間は標本の刻み幅ぶんの幅を持ち、
    ``[標本の時刻, 次の標本の時刻)`` を覆う — 標本と標本の間は観測していないが、
    2人映っている標本に挟まれた区間を単独として扱う方が誤りが大きい。

    **顔が0個の標本は含めない。** 「顔が見えない」は「複数人いる」ではなく、配信者が
    画面に映らない場面(ゲーム画面・カメラ外し)は単独配信でも普通に起きる。ここで0個を
    多人数側へ入れると、そういう配信の素材がまるごと消える。
    """
    interval = profile["interval_seconds"]
    if interval <= 0:
        raise SmileError("profileの刻み幅が不正です。")
    faces = profile.get("faces") or []
    spans: list = []
    for i, count in enumerate(faces):
        if count is None or count < min_faces:
            continue
        start, end = i * interval, (i + 1) * interval
        if spans and abs(spans[-1][1] - start) < 1e-9:
            spans[-1] = (spans[-1][0], end)
        else:
            spans.append((start, end))
    return spans


def without_spans(profile: dict, spans: list) -> dict:
    """``spans``(``[(start, end), ...]``秒)に入る標本を判定不能へ落としたprofileを返す。

    battle・collabの窓を外すためのもの。画面が分割されている間は顔が1つしか検出されなくても
    それが配信者とは限らないので、身元が怪しい区間は最初から判定不能として扱う。窓の事実は
    DB(``collab_windows`` / battle判定)側にあり、engineはそれを読まない — 素材だけで再現
    できる状態を保つため、混ぜるのは呼び出し側の責務にしている。

    sidecarは書き換えない(窓の定義が変わっても再解析は要らない)。
    """
    interval = profile["interval_seconds"]
    scores = list(profile["scores"])
    if interval <= 0:
        raise SmileError("profileの刻み幅が不正です。")
    for start, end in spans:
        if end <= start:
            continue
        first = max(0, int(float(start) / interval))
        last = min(len(scores), int(round(float(end) / interval)))
        for i in range(first, last):
            scores[i] = None
    return {**profile, "scores": scores}


def aggregate(profile: dict, bucket_seconds: Optional[float] = None,
              threshold: Optional[float] = None) -> list:
    """profileをbucket単位へ畳む。

    戻り値は ``[{"start": 秒, "smile": 秒数, "coverage": 割合, "samples": 標本数}, ...]``
    で、``start`` はbucketの先頭(録画の頭からの秒)。bucketを持っている呼び出し側は
    ``bucket_seconds`` を渡すこと(既定は ``TICTOK_SMILE_BUCKET_SECONDS``)。

    ``smile`` を秒数にしてあるのは、見どころ判定(``core.spike``)が窓内で**合計できる量**を
    要求するため。peakや平均では窓を跨いだ合計に意味が無くなる。
    """
    bucket_seconds = (get_smile_bucket_seconds() if bucket_seconds is None
                      else float(bucket_seconds))
    if bucket_seconds <= 0:
        raise SmileError("bucketの幅は正の秒数にしてください。")
    interval = profile["interval_seconds"]
    if interval <= 0:
        raise SmileError("profileの刻み幅が不正です。")
    total = len(profile["scores"]) * interval
    rows: list = []
    start = 0.0
    while start < total:
        end = start + bucket_seconds
        window = _window(profile, start, end)
        if window is None:
            break
        rows.append({
            "start": round(start, 3),
            "smile": smile_seconds(profile, start, end, threshold),
            "coverage": smile_coverage(profile, start, end),
            "samples": len(window),
        })
        start = end
    return rows
