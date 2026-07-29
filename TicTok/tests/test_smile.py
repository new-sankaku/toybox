"""笑顔検出(tictok/media/smile.py)。

weightsが要るのは実推論だけなので、ここで見るのはweights無しでも確かめられる5点:

  1. ffmpegのargv — rgb24 rawの固定刻みで、mp4が無い録画では**採用集合のplaylist**を読む
  2. 顔検出の座標 — letterboxで潰さず、枠がframe座標へ正しく戻るか
  3. **顔が複数の標本を捨てる**方針 — 最大値も平均も採らず、表情分類すら呼ばない
  4. 集約 — 秒数の数え方、判定不能の扱い、窓がprofileの外のときのNone
  5. model不在・graph不一致で**必ず失敗する**こと(0や中立値を返さない)

実modelを通す1件だけは TICTOK_SMILE_FACE_MODEL_PATH / TICTOK_SMILE_MODEL_PATH が実在する
ときにのみ走る。
"""
import io
import json
import os
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from tictok.media import hls_source
from tictok.media import smile as sm

from tests.test_hls_source import build_recording


# --------------------------------------------------------------------------- 道具


class _FakeProc:
    """ffmpegの代わり。stdoutにrgb24 rawを、stderrに警告を持つ。"""

    def __init__(self, raw: bytes, stderr: bytes = b"", returncode: int = 0):
        self.stdout = io.BytesIO(raw)
        self.stderr = io.BytesIO(stderr)
        self.returncode = returncode

    def poll(self):
        return self.returncode

    def kill(self):
        raise AssertionError("正常終了したffmpegをkillしている")

    def wait(self):
        return self.returncode


class _FakeSession:
    """onnxruntime.InferenceSessionの代わり。要求された出力名の順で返す。"""

    def __init__(self, inputs: list, outputs: list, fn=None):
        self._inputs = [types.SimpleNamespace(name=name, shape=shape)
                        for name, shape in inputs]
        self._outputs = [types.SimpleNamespace(name=name, shape=shape)
                         for name, shape in outputs]
        self.fn = fn
        self.feeds: list = []

    def get_inputs(self):
        return self._inputs

    def get_outputs(self):
        return self._outputs

    def run(self, output_names, feed):
        self.feeds.append({name: np.asarray(value).copy()
                           for name, value in feed.items()})
        produced = self.fn(np.asarray(list(feed.values())[0]))
        return [produced[name] for name in output_names]


def _detector(boxes=(), probs=(), width=320, height=240) -> sm._Detector:
    """固定の検出結果を返す顔検出。``boxes`` はletterbox canvas基準の正規化座標。"""
    anchors = max(1, len(boxes))
    score = np.zeros((1, anchors, 2), dtype=np.float32)
    box = np.zeros((1, anchors, 4), dtype=np.float32)
    for i, (rect, prob) in enumerate(zip(boxes, probs)):
        box[0, i] = rect
        score[0, i, 1] = prob
        score[0, i, 0] = 1.0 - prob
    session = _FakeSession(
        [("input", [1, 3, height, width])],
        [("scores", [1, anchors, 2]), ("boxes", [1, anchors, 4])],
        fn=lambda batch: {"scores": score, "boxes": box},
    )
    return sm._describe_detector(session, Path("face.onnx"))


def _classifier(logits, classes=8, size=64) -> sm._Classifier:
    session = _FakeSession(
        [("Input3", [1, 1, size, size])],
        [("Plus692_Output_0", [1, classes])],
        fn=lambda batch: {
            "Plus692_Output_0": np.asarray(logits, dtype=np.float32).reshape(1, -1)},
    )
    return sm._describe_classifier(session, Path("smile.onnx"))


def _frame(width=90, height=160) -> np.ndarray:
    """rgb24 rawのframe1枚ぶん。frombufferと同じread-onlyなarrayで渡す。"""
    return np.frombuffer(b"\x40" * (width * height * 3), dtype=np.uint8).reshape(
        height, width, 3)


def _source(path) -> types.SimpleNamespace:
    return types.SimpleNamespace(path=Path(path), input_args=(), is_hls=False,
                                 media_offset=0.0)


# 「happiness だけが高い」logits(参照exportのclass順: neutral, happiness, ...)。
_HAPPY = [0.0, 8.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
_NEUTRAL = [8.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


@pytest.fixture
def configured(monkeypatch, tmp_path):
    """有効化 + 2つのmodel fileを実在させる(中身は読まない)。"""
    monkeypatch.setenv("TICTOK_SMILE_ENABLED", "1")
    face = tmp_path / "face.onnx"
    face.write_bytes(b"onnx-face")
    smile = tmp_path / "smile.onnx"
    smile.write_bytes(b"onnx-smile")
    monkeypatch.setenv("TICTOK_SMILE_FACE_MODEL_PATH", str(face))
    monkeypatch.setenv("TICTOK_SMILE_MODEL_PATH", str(smile))
    monkeypatch.setattr(sm, "_models", None, raising=False)
    monkeypatch.setattr(sm, "_models_key", None, raising=False)
    return types.SimpleNamespace(face=face, smile=smile)


# --------------------------------------------------------------------------- 既定


def test_the_feature_is_off_and_unconfigured_by_default(monkeypatch):
    for name in ("TICTOK_SMILE_ENABLED", "TICTOK_SMILE_FACE_MODEL_PATH",
                 "TICTOK_SMILE_MODEL_PATH"):
        monkeypatch.delenv(name, raising=False)
    status = sm.smile_status()
    assert status["enabled"] is False
    assert status["configured"] is False
    assert status["face_model"] == "" and status["smile_model"] == ""
    # GPUは転写と超解像が12GBを取り合っている。ここは常にCPU。
    assert status["device"] == "cpu"


def test_the_default_positive_class_is_only_happiness():
    """surpriseは驚き顔で喜びとは限らない。既定で拾うと見どころが驚きで埋まる。"""
    from tictok.core import config

    assert config.get_smile_positive_classes() == ["happiness"]
    assert config.get_smile_labels()[1] == "happiness"


# ------------------------------------------------------------------ model不在で失敗


def test_every_missing_prerequisite_is_reported_not_defaulted(monkeypatch, tmp_path):
    monkeypatch.setenv("TICTOK_SMILE_ENABLED", "0")
    with pytest.raises(sm.SmileError, match="無効"):
        sm._get_models()

    monkeypatch.setenv("TICTOK_SMILE_ENABLED", "1")
    monkeypatch.setenv("TICTOK_SMILE_FACE_MODEL_PATH", "")
    monkeypatch.setenv("TICTOK_SMILE_MODEL_PATH", "")
    with pytest.raises(sm.SmileError, match="未設定"):
        sm._get_models()

    face = tmp_path / "face.onnx"
    face.write_bytes(b"onnx")
    monkeypatch.setenv("TICTOK_SMILE_FACE_MODEL_PATH", str(face))
    with pytest.raises(sm.SmileError, match="未設定"):
        sm._get_models()

    monkeypatch.setenv("TICTOK_SMILE_MODEL_PATH", str(tmp_path / "absent.onnx"))
    with pytest.raises(sm.SmileError, match="見つかりません"):
        sm._get_models()


def test_a_missing_onnxruntime_is_an_error_not_a_silent_skip(monkeypatch, configured):
    monkeypatch.setitem(sys.modules, "onnxruntime", None)
    with pytest.raises(sm.SmileError, match="onnxruntime"):
        sm._get_models()


def test_the_fingerprint_refuses_to_describe_an_unconfigured_model(monkeypatch, tmp_path):
    monkeypatch.setenv("TICTOK_SMILE_FACE_MODEL_PATH", "")
    with pytest.raises(sm.SmileError):
        sm._model_fingerprint()

    monkeypatch.setenv("TICTOK_SMILE_FACE_MODEL_PATH", str(tmp_path / "gone.onnx"))
    monkeypatch.setenv("TICTOK_SMILE_MODEL_PATH", str(tmp_path / "gone2.onnx"))
    with pytest.raises(sm.SmileError):
        sm._model_fingerprint()


async def test_the_entry_point_refuses_to_run_while_disabled(make_recording, monkeypatch):
    _, mp4 = make_recording()
    monkeypatch.setenv("TICTOK_SMILE_ENABLED", "0")
    with pytest.raises(sm.SmileError):
        await sm.ensure_smile_profile(mp4)


async def test_the_entry_point_fails_when_the_model_is_not_placed(make_recording,
                                                                 monkeypatch):
    """modelが無い録画で「笑顔0秒」を返すと、笑わない配信者として集計へ入る。"""
    _, mp4 = make_recording()
    monkeypatch.setenv("TICTOK_SMILE_ENABLED", "1")
    monkeypatch.setenv("TICTOK_SMILE_FACE_MODEL_PATH", "")
    monkeypatch.setenv("TICTOK_SMILE_MODEL_PATH", "")
    with pytest.raises(sm.SmileError, match="未設定"):
        await sm.ensure_smile_profile(mp4)


async def test_the_entry_point_reports_a_recording_with_no_material_as_missing(
        tmp_root, configured):
    mp4, session = build_recording(tmp_root, with_mp4=False)
    for seg in session.glob("seg*.ts"):
        seg.unlink()
    with pytest.raises(hls_source.SourceMissing):
        await sm.ensure_smile_profile(mp4)


# --------------------------------------------------------------------------- graph検査


def test_a_detector_that_needs_anchor_decoding_is_rejected():
    """stride別のcls/obj/bboxを出すexportを受けると、priorとvarianceをこちらが推測する
    ことになり、少しでも学習時と違えば枠が静かにずれる。"""
    raw = _FakeSession(
        [("input", [1, 3, 640, 640])],
        [(f"{head}_{stride}", [1, 100, 4]) for head in ("cls", "obj", "bbox")
         for stride in (8, 16, 32)],
    )
    with pytest.raises(sm.SmileError, match="2出力"):
        sm._describe_detector(raw, Path("m.onnx"))


def test_a_detector_with_a_dynamic_input_size_is_rejected():
    dynamic = _FakeSession([("input", [1, 3, "h", "w"])],
                           [("scores", [1, 10, 2]), ("boxes", [1, 10, 4])])
    with pytest.raises(sm.SmileError, match="可変"):
        sm._describe_detector(dynamic, Path("m.onnx"))


def test_the_detector_outputs_are_told_apart_by_their_last_dimension():
    """出力名に依存しない: exportごとに名前は違うが、scoreは2列・boxは4列である。"""
    described = sm._describe_detector(
        _FakeSession([("input", [1, 3, 240, 320])],
                     [("boxes", ["b", 4420, 4]), ("scores", ["b", 4420, 2])]),
        Path("m.onnx"))
    assert (described.score_name, described.box_name) == ("scores", "boxes")
    assert (described.width, described.height) == (320, 240)

    ambiguous = _FakeSession([("input", [1, 3, 240, 320])],
                             [("a", [1, 10, 5]), ("b", [1, 10, 7])])
    with pytest.raises(sm.SmileError, match="見分けられません"):
        sm._describe_detector(ambiguous, Path("m.onnx"))


def test_the_classifier_channel_count_and_size_come_from_the_graph():
    gray = sm._describe_classifier(
        _FakeSession([("Input3", [1, 1, 64, 64])], [("out", [1, 8])]), Path("m.onnx"))
    assert (gray.channels, gray.width, gray.height) == (1, 64, 64)

    rgb = sm._describe_classifier(
        _FakeSession([("x", ["b", 3, 48, 48])], [("out", [1, 7])]), Path("m.onnx"))
    assert rgb.channels == 3

    with pytest.raises(sm.SmileError, match="grayscale"):
        sm._describe_classifier(
            _FakeSession([("x", [1, 4, 64, 64])], [("out", [1, 8])]), Path("m.onnx"))


# --------------------------------------------------------------------------- 顔検出


def test_boxes_map_back_to_frame_coordinates_through_the_letterbox(configured):
    """9:16のframeを4:3の入力へ潰すと顔が横に広がって検出率が落ちる。letterboxした
    ぶんの余白と縮尺を戻さないと、枠が画面の別の場所を指す。"""
    frame = _frame(90, 160)
    # frame座標 (30,40)-(60,100) を 320x240 canvasへ写した正規化座標。
    detector = _detector(boxes=[(137 / 320, 60 / 240, 182 / 320, 150 / 240)], probs=[0.9])

    found = sm._faces(detector, frame)

    assert len(found) == 1
    x1, y1, x2, y2, score = found[0]
    assert (round(x1), round(y1), round(x2), round(y2)) == (30, 40, 60, 100)
    assert score == pytest.approx(0.9)


def test_faces_below_the_score_threshold_are_not_counted(configured, monkeypatch):
    frame = _frame()
    detector = _detector(boxes=[(0.4, 0.2, 0.5, 0.5), (0.6, 0.2, 0.7, 0.5)],
                         probs=[0.9, 0.2])
    assert len(sm._faces(detector, frame)) == 1

    monkeypatch.setenv("TICTOK_SMILE_FACE_THRESHOLD", "0.95")
    assert sm._faces(detector, frame) == []


def test_faces_too_small_to_read_an_expression_are_not_counted(configured, monkeypatch):
    """映り込んだ写真やポスターを顔として数えると、配信者1人の標本まで「顔が複数」で
    捨てることになる。"""
    frame = _frame(90, 160)
    # 高さ 0.02 * 240px = 4.8 canvas px ≒ 3.2 frame px。既定の下限(frame高の6%=9.6px)未満。
    detector = _detector(boxes=[(0.4, 0.20, 0.5, 0.22)], probs=[0.9])
    assert sm._faces(detector, frame) == []

    monkeypatch.setenv("TICTOK_SMILE_FACE_MIN_HEIGHT_RATIO", "0.0")
    assert len(sm._faces(detector, frame)) == 1


def test_duplicate_boxes_on_one_face_are_merged(configured):
    """同じ顔に枠が2つ残ると「顔が2つ」と数えられ、その標本が判定不能へ落ちる。"""
    frame = _frame()
    detector = _detector(
        boxes=[(0.40, 0.20, 0.50, 0.50), (0.405, 0.205, 0.505, 0.505)],
        probs=[0.9, 0.85])
    assert len(sm._faces(detector, frame)) == 1


def test_two_separate_faces_are_both_reported(configured):
    frame = _frame()
    detector = _detector(boxes=[(0.05, 0.20, 0.15, 0.50), (0.80, 0.20, 0.90, 0.50)],
                         probs=[0.9, 0.9])
    assert len(sm._faces(detector, frame)) == 2


def test_a_detector_emitting_pixel_boxes_is_an_error_not_reinterpreted(configured):
    """pixel座標を正規化座標として読むと枠が原点付近へ潰れ、顔が静かに消える。"""
    frame = _frame()
    detector = _detector(boxes=[(120.0, 40.0, 180.0, 140.0)], probs=[0.9])
    with pytest.raises(sm.SmileError, match="正規化座標"):
        sm._faces(detector, frame)


def test_the_face_score_column_is_configurable(configured, monkeypatch):
    """[背景, 顔]の列を取り違えると検出が全反転し、顔の無い録画に見えるだけで気付けない。"""
    frame = _frame()
    detector = _detector(boxes=[(0.4, 0.2, 0.5, 0.5)], probs=[0.9])
    assert len(sm._faces(detector, frame)) == 1

    monkeypatch.setenv("TICTOK_SMILE_FACE_SCORE_INDEX", "0")
    assert sm._faces(detector, frame) == []

    monkeypatch.setenv("TICTOK_SMILE_FACE_SCORE_INDEX", "3")
    with pytest.raises(sm.SmileError):
        sm._faces(detector, frame)


# --------------------------------------------------------------------------- 表情分類


def test_the_positive_classes_are_folded_as_configured(configured, monkeypatch):
    frame = _frame()
    box = (10.0, 20.0, 40.0, 60.0)
    # softmaxで happiness=0.5, surprise=0.25, neutral=0.25 になるlogits。
    logits = [np.log(0.25), np.log(0.5), np.log(0.25), -50, -50, -50, -50, -50]
    classifier = _classifier(logits)

    assert sm._smile_score(classifier, frame, box, [1], 8) == pytest.approx(0.5, abs=1e-3)

    # 排他多classでは「どれかである確率」は和。maxは複数指定したときだけ差が出る。
    monkeypatch.setenv("TICTOK_SMILE_POSITIVE_CLASSES", "happiness|surprise")
    assert sm._smile_score(classifier, frame, box, [1, 2], 8) == pytest.approx(0.75,
                                                                              abs=1e-3)
    monkeypatch.setenv("TICTOK_SMILE_FOLD", "max")
    assert sm._smile_score(classifier, frame, box, [1, 2], 8) == pytest.approx(0.5,
                                                                              abs=1e-3)
    monkeypatch.setenv("TICTOK_SMILE_FOLD", "mean")
    with pytest.raises(sm.SmileError, match="TICTOK_SMILE_FOLD"):
        sm._smile_score(classifier, frame, box, [1, 2], 8)


def test_an_unknown_activation_is_an_error(configured, monkeypatch):
    monkeypatch.setenv("TICTOK_SMILE_ACTIVATION", "logsoftmax")
    with pytest.raises(sm.SmileError, match="TICTOK_SMILE_ACTIVATION"):
        sm._smile_score(_classifier(_HAPPY), _frame(), (10.0, 20.0, 40.0, 60.0), [1], 8)


def test_a_label_list_that_does_not_match_the_model_output_is_an_error(configured):
    """class名の数と出力数が違えば、別の表情の確率を笑顔として読むことになる。"""
    with pytest.raises(sm.SmileError, match="class名の数"):
        sm._smile_score(_classifier(_HAPPY, classes=8), _frame(),
                        (10.0, 20.0, 40.0, 60.0), [1], 7)


def test_a_class_that_is_not_in_the_label_list_is_an_error():
    labels = ["neutral", "happiness"]
    assert sm._class_indices(labels, ["happiness"]) == [1]
    # 綴り違いを黙って落とすと笑顔が一切検出されず、笑わない配信者に見える。
    with pytest.raises(sm.SmileError):
        sm._class_indices(labels, ["happines"])
    with pytest.raises(sm.SmileError):
        sm._class_indices(labels, [])


def test_the_crop_is_widened_and_fed_at_the_model_input_size(configured, monkeypatch):
    """検出枠は目〜口に寄っており、そのまま切ると学習画像(額と顎を含む)と画角が合わない。"""
    monkeypatch.setenv("TICTOK_SMILE_CROP_MARGIN", "0.5")
    classifier = _classifier(_HAPPY)
    sm._smile_score(classifier, _frame(90, 160), (20.0, 40.0, 40.0, 80.0), [1], 8)

    batch = classifier.session.feeds[-1]["Input3"]
    assert batch.shape == (1, 1, 64, 64), "modelの入力寸へ整えていない"


# --------------------------------------------------------- 顔が複数のときの方針(要点)


def _scan_frames(monkeypatch, detector, classifier, count, width=90, height=160,
                 interval=2.0):
    monkeypatch.setattr(
        sm.subprocess, "Popen",
        lambda *a, **k: _FakeProc(b"\x40" * (width * height * 3 * count)))
    return sm._scan(_source(Path("x.mp4")), sm._Models(detector, classifier),
                    [1], 8, interval, width, height, count)


def test_a_frame_with_two_faces_is_discarded_not_maxed(configured, monkeypatch):
    """battle・collab中は相手や共演者の顔も映る。最大値を採ると、別人の笑顔を配信者の
    笑顔として名乗ることになる — 見どころの根拠が別人でしたという壊れ方は最も高くつく。"""
    detector = _detector(boxes=[(0.05, 0.20, 0.15, 0.50), (0.80, 0.20, 0.90, 0.50)],
                         probs=[0.9, 0.9])
    classifier = _classifier(_HAPPY)

    scores, faces = _scan_frames(monkeypatch, detector, classifier, 3)

    assert scores == [None, None, None]
    assert faces == [2, 2, 2]
    assert classifier.session.feeds == [], "顔が複数なのに表情分類を呼んでいる"


def test_a_frame_with_no_face_is_undecided_not_zero(configured, monkeypatch):
    """顔が映っていないことは「笑っていない」ことではない。"""
    detector = _detector(boxes=[(0.4, 0.2, 0.5, 0.5)], probs=[0.1])
    classifier = _classifier(_HAPPY)

    scores, faces = _scan_frames(monkeypatch, detector, classifier, 2)

    assert scores == [None, None]
    assert faces == [0, 0]
    assert classifier.session.feeds == []


def test_a_frame_with_exactly_one_face_is_scored(configured, monkeypatch):
    detector = _detector(boxes=[(0.4, 0.2, 0.5, 0.5)], probs=[0.9])
    classifier = _classifier(_HAPPY)

    scores, faces = _scan_frames(monkeypatch, detector, classifier, 2)

    assert faces == [1, 1]
    assert all(value is not None and value > 0.9 for value in scores)
    assert len(classifier.session.feeds) == 2


def test_an_incomplete_frame_is_an_error_not_a_short_profile(configured, monkeypatch):
    detector = _detector(boxes=[(0.4, 0.2, 0.5, 0.5)], probs=[0.9])
    monkeypatch.setattr(sm.subprocess, "Popen",
                        lambda *a, **k: _FakeProc(b"\x40" * (90 * 160 * 3 + 7)))
    with pytest.raises(sm.SmileError, match="不完全なframe"):
        sm._scan(_source(Path("x.mp4")), sm._Models(detector, _classifier(_HAPPY)),
                 [1], 8, 2.0, 90, 160, 2)


def test_decode_failure_and_an_empty_video_are_errors(configured, monkeypatch):
    detector = _detector(boxes=[(0.4, 0.2, 0.5, 0.5)], probs=[0.9])
    models = sm._Models(detector, _classifier(_HAPPY))

    monkeypatch.setattr(sm.subprocess, "Popen",
                        lambda *a, **k: _FakeProc(b"", b"boom", returncode=1))
    with pytest.raises(sm.SmileError, match="decode"):
        sm._scan(_source(Path("x.mp4")), models, [1], 8, 2.0, 90, 160, 1)

    monkeypatch.setattr(sm.subprocess, "Popen", lambda *a, **k: _FakeProc(b""))
    with pytest.raises(sm.SmileError, match="frame"):
        sm._scan(_source(Path("x.mp4")), models, [1], 8, 2.0, 90, 160, 1)


def test_a_cancelled_job_reports_the_cancel_not_a_decode_failure(configured, monkeypatch):
    """cancelはffmpegをkillするので、非0終了は本物のdecode失敗と見分けが付かない。
    先にtokenを見ないと、利用者のcancelがerror扱いのops_eventとして残る。"""
    from tictok.core import cancel

    detector = _detector(boxes=[(0.4, 0.2, 0.5, 0.5)], probs=[0.9])
    # killされたffmpegと同じ形(非0終了・出力なし)。
    monkeypatch.setattr(sm.subprocess, "Popen",
                        lambda *a, **k: _FakeProc(b"", b"", returncode=1))
    token = cancel.CancelToken("job-1")
    token.cancel()
    with cancel.token_scope(token):
        with pytest.raises(cancel.JobCancelled):
            sm._scan(_source(Path("x.mp4")),
                     sm._Models(detector, _classifier(_HAPPY)), [1], 8, 2.0, 90, 160, 1)


def test_stderr_is_drained_while_stdout_is_read(configured, monkeypatch):
    """stdoutを読み切ってからstderrを読む形は実録画で無限hangを再現済み。"""
    detector = _detector(boxes=[(0.4, 0.2, 0.5, 0.5)], probs=[0.9])
    monkeypatch.setattr(
        sm.subprocess, "Popen",
        lambda *a, **k: _FakeProc(b"\x40" * (90 * 160 * 3), b"warning\n" * 20000))

    scores, faces = sm._scan(_source(Path("x.mp4")),
                             sm._Models(detector, _classifier(_HAPPY)),
                             [1], 8, 2.0, 90, 160, 1)
    assert len(scores) == 1 and faces == [1]


# --------------------------------------------------------------------------- ffmpeg argv


def test_the_decode_command_samples_frames_as_raw_rgb(make_recording):
    _, mp4 = make_recording()
    args = sm._ffmpeg_args(_source(mp4), 2.0, 480, 854)

    assert args[0] == "ffmpeg"
    assert "-an" in args and "-sn" in args
    assert args[args.index("-map") + 1] == "0:v:0"
    assert args[args.index("-f") + 1] == "rawvideo"
    assert args[args.index("-pix_fmt") + 1] == "rgb24"
    chain = args[args.index("-vf") + 1]
    assert chain.startswith("fps=1/2.000000,"), "固定刻みのsamplingになっていない"
    # 混在解像度の録画でも全frameが同じ寸法で出る(pipeのbyte数が確定する)。
    assert "480:854" in chain


def test_a_recording_without_an_mp4_is_read_from_its_segments(tmp_root, monkeypatch,
                                                             configured):
    """mp4の無い録画が普通にある。Path(src)直読みだとそこで黙って沈黙する。"""
    mp4, session = build_recording(tmp_root, with_mp4=False)
    captured = {}

    def fake_popen(args, **kwargs):
        captured["args"] = args
        raise OSError("blocked")

    monkeypatch.setattr(sm.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(sm, "_get_models", lambda: sm._Models(
        _detector(boxes=[(0.4, 0.2, 0.5, 0.5)], probs=[0.9]), _classifier(_HAPPY)))
    monkeypatch.setattr(sm, "_probe_duration", lambda source: 10.0)
    monkeypatch.setattr(sm, "_work_size", lambda source: (90, 160))

    with pytest.raises(sm.SmileError):
        sm._build(mp4, 2.0)

    args = [str(a) for a in captured["args"]]
    index = args.index("-i")
    playlist = args[index + 1]
    assert playlist.startswith(str(session)) and playlist.endswith(".m3u8")
    assert hls_source.CURATED_PREFIX in playlist, "captureのindex.m3u8を直接渡している"
    from tictok.record import recorder as rec

    for option in rec.HLS_INPUT_ARGS:
        assert option in args[:index], f"{option} が -i より前にない"


def test_the_work_size_follows_the_widest_resolution(monkeypatch, configured):
    """混在解像度の録画でstream headerの1組を採ると、低い側で開いた録画は画素を捨てる。"""
    monkeypatch.setenv("TICTOK_SMILE_WORK_WIDTH", "480")
    monkeypatch.setattr(hls_source, "resolutions_sync",
                        lambda source: {(320, 640), (720, 1280)})
    assert sm._work_size(_source(Path("x.mp4"))) == (480, 852)

    # 源より大きくは引き伸ばさない(顔の情報は増えず、pipeとdecodeだけ重くなる)。
    monkeypatch.setattr(hls_source, "resolutions_sync", lambda source: {(240, 426)})
    assert sm._work_size(_source(Path("x.mp4"))) == (240, 426)

    monkeypatch.setattr(hls_source, "resolutions_sync", lambda source: set())
    with pytest.raises(sm.SmileError, match="解像度"):
        sm._work_size(_source(Path("x.mp4")))


# --------------------------------------------------------------------------- 集約


def _profile(**over) -> dict:
    profile = {
        "interval_seconds": 2.0,
        "duration_seconds": 20.0,
        "scores": [0.9, 0.1, None, 0.8, 0.2, None, None, 0.95, 0.0, 0.6],
        "faces": [1, 1, 2, 1, 1, 0, 3, 1, 1, 1],
        "labels": ["neutral", "happiness"],
        "positive_classes": ["happiness"],
        "activation": "softmax",
        "fold": "sum",
        "threshold": 0.5,
        "work_width": 480,
        "work_height": 854,
        "work_width_setting": 480,
        "face_threshold": 0.7,
        "face_nms_iou": 0.3,
        "face_min_height_ratio": 0.06,
        "face_score_activation": "none",
        "face_score_index": 1,
        "crop_margin": 0.15,
    }
    profile.update(over)
    return profile


def test_smile_seconds_counts_only_the_samples_over_the_threshold():
    profile = _profile()
    # 0.9 / 0.8 / 0.95 / 0.6 の4標本 x 2秒。
    assert sm.smile_seconds(profile, 0.0, 20.0, threshold=0.5) == 8.0
    assert sm.smile_seconds(profile, 0.0, 20.0, threshold=0.94) == 2.0
    assert sm.smile_seconds(profile, 0.0, 4.0, threshold=0.5) == 2.0


def test_smile_seconds_uses_the_configured_threshold_by_default(monkeypatch):
    profile = _profile(scores=[0.6, 0.6], faces=[1, 1])
    monkeypatch.setenv("TICTOK_SMILE_THRESHOLD", "0.9")
    assert sm.smile_seconds(profile, 0.0, 4.0) == 0.0
    monkeypatch.setenv("TICTOK_SMILE_THRESHOLD", "0.5")
    assert sm.smile_seconds(profile, 0.0, 4.0) == 4.0


def test_undecidable_samples_are_not_counted_as_smiling_nor_extrapolated():
    """標本の割合から窓全体へ引き伸ばすと、観測していない時間の笑顔を作り出す。"""
    profile = _profile(scores=[0.9, None, None, None], faces=[1, 2, 2, 0],
                       duration_seconds=8.0)
    assert sm.smile_seconds(profile, 0.0, 8.0, threshold=0.5) == 2.0
    assert sm.smile_coverage(profile, 0.0, 8.0) == 0.25


def test_a_window_with_nothing_decidable_is_zero_seconds_not_none():
    """ここをNoneにすると、呼び出し側の指標登録は最初のNoneで指標ごと外すため、顔が
    写らない60秒が1つあるだけで録画全体の笑顔指標が消える。"""
    profile = _profile(scores=[None, None], faces=[2, 2], duration_seconds=4.0)
    assert sm.smile_seconds(profile, 0.0, 4.0) == 0.0
    assert sm.smile_coverage(profile, 0.0, 4.0) == 0.0


def test_smile_seconds_returns_none_where_nothing_was_analysed():
    """解析していない区間を0秒と答えると、「笑いが無かった」区間として集計に入る。"""
    profile = _profile()
    assert sm.smile_seconds(profile, 100.0, 120.0) is None
    assert sm.smile_coverage(profile, 100.0, 120.0) is None
    assert sm.smile_seconds(profile, 4.0, 4.0) is None
    assert sm.smile_seconds(profile, -2.0, 4.0) is None


def test_smile_seconds_clamps_the_window_to_the_profile():
    profile = _profile(scores=[0.9, 0.9], faces=[1, 1], duration_seconds=4.0)
    assert sm.smile_seconds(profile, 0.0, 900.0, threshold=0.5) == 4.0


def test_a_finer_interval_changes_the_seconds_each_sample_is_worth():
    profile = _profile(interval_seconds=0.5, scores=[0.9, 0.9, 0.0, 0.9],
                       faces=[1, 1, 1, 1], duration_seconds=2.0)
    assert sm.smile_seconds(profile, 0.0, 2.0, threshold=0.5) == 1.5


def test_aggregate_folds_the_profile_into_buckets():
    profile = _profile()
    rows = sm.aggregate(profile, bucket_seconds=10.0, threshold=0.5)

    assert [row["start"] for row in rows] == [0.0, 10.0]
    # 前半: 0.9, 0.1, None, 0.8, 0.2 → 4秒 / coverage 0.8
    assert rows[0] == {"start": 0.0, "smile": 4.0, "coverage": 0.8, "samples": 5}
    # 後半: None, None, 0.95, 0.0, 0.6 → 4秒 / coverage 0.6
    assert rows[1] == {"start": 10.0, "smile": 4.0, "coverage": 0.6, "samples": 5}


def test_aggregate_defaults_to_the_configured_bucket_width(monkeypatch):
    monkeypatch.setenv("TICTOK_SMILE_BUCKET_SECONDS", "20.0")
    rows = sm.aggregate(_profile())
    assert len(rows) == 1 and rows[0]["samples"] == 10

    monkeypatch.setenv("TICTOK_SMILE_BUCKET_SECONDS", "0")
    with pytest.raises(sm.SmileError):
        sm.aggregate(_profile())


def test_without_spans_drops_the_battle_and_collab_windows():
    """画面が分割されている間は顔が1つでも配信者とは限らない。身元が怪しい区間は
    最初から判定不能として扱えるようにしておく(sidecarは書き換えない)。"""
    profile = _profile()
    masked = sm.without_spans(profile, [(0.0, 6.0), (14.0, 16.0)])

    assert masked["scores"][:3] == [None, None, None]
    assert masked["scores"][7] is None
    assert masked["scores"][3] == 0.8
    assert profile["scores"][0] == 0.9, "元のprofileを書き換えている"
    assert sm.smile_coverage(masked, 0.0, 20.0) == 0.4
    # 窓が逆順・範囲外でも壊れない。
    assert sm.without_spans(profile, [(9.0, 9.0), (500.0, 600.0)])["scores"] \
        == profile["scores"]


# --------------------------------------------------------------------------- sidecar


@pytest.fixture
def cacheable(configured, monkeypatch):
    monkeypatch.setenv("TICTOK_SMILE_SAMPLE_SECONDS", "2.0")
    monkeypatch.setenv("TICTOK_SMILE_LABELS", "neutral|happiness")
    monkeypatch.setenv("TICTOK_SMILE_POSITIVE_CLASSES", "happiness")
    return configured


def test_the_sidecar_stores_raw_scores_and_reloads_them(make_recording, cacheable):
    _, mp4 = make_recording()
    profile = _profile()
    sm._store_cache(mp4, {**profile, **sm._model_fingerprint()})

    written = json.loads(sm.smile_profile_path(mp4).read_text(encoding="utf-8"))
    assert written["scores"] == profile["scores"]
    assert written["version"] == sm._PROFILE_VERSION
    assert written["face_model"] == cacheable.face.name
    assert written["smile_model"] == cacheable.smile.name

    assert sm._load_cache(mp4, 2.0) == profile


def test_changing_only_the_threshold_keeps_the_cache(make_recording, cacheable,
                                                     monkeypatch):
    """閾値を掛ける前の確率を保存しているのは、後から閾値を掃引するため。"""
    _, mp4 = make_recording()
    sm._store_cache(mp4, {**_profile(), **sm._model_fingerprint()})

    monkeypatch.setenv("TICTOK_SMILE_THRESHOLD", "0.8")
    assert sm._load_cache(mp4, 2.0)["scores"] == _profile()["scores"]


def test_the_cache_follows_everything_that_changes_the_scores(make_recording, cacheable,
                                                              monkeypatch):
    _, mp4 = make_recording()
    sm._store_cache(mp4, {**_profile(), **sm._model_fingerprint()})
    assert sm._load_cache(mp4, 2.0)

    assert sm._load_cache(mp4, 1.0) == {}

    for name, value in (("TICTOK_SMILE_POSITIVE_CLASSES", "neutral"),
                        ("TICTOK_SMILE_ACTIVATION", "sigmoid"),
                        ("TICTOK_SMILE_FOLD", "max"),
                        ("TICTOK_SMILE_CROP_MARGIN", "0.4"),
                        # 顔検出側の閾値は検出数を変え、検出数は判定不能の決まり方を変える。
                        ("TICTOK_SMILE_FACE_THRESHOLD", "0.5"),
                        ("TICTOK_SMILE_FACE_NMS_IOU", "0.5"),
                        ("TICTOK_SMILE_FACE_MIN_HEIGHT_RATIO", "0.1"),
                        ("TICTOK_SMILE_FACE_SCORE_INDEX", "0"),
                        ("TICTOK_SMILE_WORK_WIDTH", "320")):
        monkeypatch.setenv(name, value)
        assert sm._load_cache(mp4, 2.0) == {}, f"{name} の変更でcacheが当たっている"
        monkeypatch.delenv(name)

    assert sm._load_cache(mp4, 2.0)

    # weightsを差し替えたら確率が変わる。素材が同じでも当ててはいけない。
    cacheable.smile.write_bytes(b"different weights")
    assert sm._load_cache(mp4, 2.0) == {}


def test_the_cache_compares_the_work_width_setting_not_the_capped_actual_size(
        make_recording, cacheable, monkeypatch):
    """実寸は源の幅で頭打ちになる(240pの録画に480を設定しても実寸は240)。実寸で比べると
    「480で解析済みの720p録画に640を設定した」という本当に作り直すべき変更を取りこぼす。"""
    _, mp4 = make_recording()
    sm._store_cache(mp4, {**_profile(work_width=240, work_height=426),
                          **sm._model_fingerprint()})
    assert sm._load_cache(mp4, 2.0)

    monkeypatch.setenv("TICTOK_SMILE_WORK_WIDTH", "640")
    assert sm._load_cache(mp4, 2.0) == {}


def test_the_cache_follows_the_material(make_recording, cacheable):
    _, mp4 = make_recording()
    sm._store_cache(mp4, {**_profile(), **sm._model_fingerprint()})
    assert sm._load_cache(mp4, 2.0)

    mp4.write_bytes(b"\x00" * 4096)
    assert sm._load_cache(mp4, 2.0) == {}


def test_a_stale_schema_version_invalidates_the_sidecar(make_recording, cacheable):
    _, mp4 = make_recording()
    sm._store_cache(mp4, {**_profile(), **sm._model_fingerprint()})
    path = sm.smile_profile_path(mp4)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["version"] = sm._PROFILE_VERSION + 1
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert sm._load_cache(mp4, 2.0) == {}


def test_a_sidecar_whose_scores_and_faces_disagree_is_rejected(make_recording, cacheable):
    """標本ごとの検出数は「映っていなかった」と「誰か分からなかった」を区別する唯一の
    情報なので、片方だけ欠けたsidecarは読まない。"""
    _, mp4 = make_recording()
    sm._store_cache(mp4, {**_profile(faces=[1, 1]), **sm._model_fingerprint()})
    assert sm._load_cache(mp4, 2.0) == {}


def test_the_sidecar_is_listed_as_an_artifact_of_the_recording(make_recording):
    _, mp4 = make_recording()
    assert sm.smile_profile_path(mp4) in sm.smile_artifact_paths(mp4)
    assert sm.smile_profile_path(mp4).name.endswith(sm.SMILE_SUFFIX)


# --------------------------------------------------------------------------- 入口


async def test_the_entry_point_returns_a_matching_sidecar_without_decoding(
        make_recording, cacheable, monkeypatch):
    _, mp4 = make_recording()
    sm._store_cache(mp4, {**_profile(), **sm._model_fingerprint()})

    def forbidden(*args, **kwargs):
        raise AssertionError("cacheがあるのにffmpegを起こしている")

    monkeypatch.setattr(sm.subprocess, "Popen", forbidden)
    assert (await sm.ensure_smile_profile(mp4))["scores"] == _profile()["scores"]


async def test_a_broken_model_setting_is_not_masked_by_a_valid_sidecar(
        make_recording, cacheable):
    """modelを直したつもりで直っていないことに気付けるよう、cacheより先に設定を見る。"""
    _, mp4 = make_recording()
    sm._store_cache(mp4, {**_profile(), **sm._model_fingerprint()})
    cacheable.face.unlink()
    with pytest.raises(sm.SmileError):
        await sm.ensure_smile_profile(mp4)


async def test_the_end_to_end_build_writes_the_sidecar(make_recording, cacheable,
                                                       monkeypatch):
    _, mp4 = make_recording()
    detector = _detector(boxes=[(0.40, 0.20, 0.50, 0.60)], probs=[0.9])
    classifier = _classifier([0.0, 8.0])
    monkeypatch.setattr(sm, "_get_models",
                        lambda: sm._Models(detector, classifier))
    monkeypatch.setattr(sm, "_probe_duration", lambda source: 6.0)
    monkeypatch.setattr(sm, "_work_size", lambda source: (90, 160))
    monkeypatch.setattr(sm.subprocess, "Popen",
                        lambda *a, **k: _FakeProc(b"\x40" * (90 * 160 * 3 * 3)))
    monkeypatch.setattr(sm, "ffmpeg_available", lambda: True)

    profile = await sm.ensure_smile_profile(mp4)

    assert profile["interval_seconds"] == 2.0
    assert profile["duration_seconds"] == 6.0
    assert profile["faces"] == [1, 1, 1]
    assert all(value > 0.99 for value in profile["scores"])
    assert profile["work_width"] == 90 and profile["work_height"] == 160
    assert sm.smile_profile_path(mp4).is_file()
    assert sm.smile_seconds(profile, 0.0, 6.0, threshold=0.5) == 6.0
    # 2回目はcacheに当たり、ffmpegは起こさない。
    monkeypatch.setattr(sm.subprocess, "Popen",
                        lambda *a, **k: pytest.fail("cacheに当たっていない"))
    assert (await sm.ensure_smile_profile(mp4))["scores"] == profile["scores"]


# --------------------------------------------------------------------------- 実model


@pytest.mark.skipif(
    not os.environ.get("TICTOK_SMILE_FACE_MODEL_PATH")
    or not os.environ.get("TICTOK_SMILE_MODEL_PATH")
    or not Path(os.environ["TICTOK_SMILE_FACE_MODEL_PATH"]).is_file()
    or not Path(os.environ["TICTOK_SMILE_MODEL_PATH"]).is_file(),
    reason="needs the real ONNX models (TICTOK_SMILE_FACE_MODEL_PATH / TICTOK_SMILE_MODEL_PATH)",
)
def test_the_real_models_accept_a_blank_frame(monkeypatch):
    """graphの契約(入出力の形・正規化box)が実weightsで満たされているかだけを見る。
    無地のframeに顔は無いので、検出0件が正しい。"""
    pytest.importorskip("onnxruntime")
    monkeypatch.setenv("TICTOK_SMILE_ENABLED", "1")
    models = sm._get_models()
    assert sm._faces(models.detector, _frame(360, 640)) == []
