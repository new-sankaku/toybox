"""笑い声検出(tictok/media/laugh_audio.py)。

weightsが要るのは実推論だけなので、ここで見るのはweights無しでも確かめられる4点:

  1. ffmpegのargv — 16kHz/mono/s16le で、mp4が無い録画では**採用集合のplaylist**を読む
  2. 前処理 — 窓の切り出し位置・末尾の0詰め・batchの束ね方
  3. 確率の畳み方 — 多labelなのでclass間はmax、activationは設定どおり
  4. sidecarの形 — 何が鍵で何が鍵でないか(閾値は鍵ではない)

実modelを通す1件だけは TICTOK_LAUGH_AUDIO_MODEL_PATH が実在するときにのみ走る。
"""
import io
import json
import os
import types
from pathlib import Path

import numpy as np
import pytest

from tictok.core import config
from tictok.media import hls_source
from tictok.media import laugh_audio as la
from tictok.record import recorder as rec

from tests.test_hls_source import build_recording


# --------------------------------------------------------------------------- 道具


class _FakeProc:
    """ffmpegの代わり。stdoutにPCMを、stderrに警告を持つ。"""

    def __init__(self, pcm: bytes, stderr: bytes = b"", returncode: int = 0):
        self.stdout = io.BytesIO(pcm)
        self.stderr = io.BytesIO(stderr)
        self.returncode = returncode

    def wait(self):
        return self.returncode


class _FakeSession:
    """onnxruntime.InferenceSessionの代わり。runへ来たbatchの形を記録する。"""

    def __init__(self, classes=4, fn=None):
        self.classes = classes
        self.fn = fn
        self.batches: list = []

    def run(self, output_names, feed):
        batch = feed["waveform"]
        self.batches.append(np.asarray(batch).copy())
        if self.fn is not None:
            return [self.fn(np.asarray(batch))]
        return [np.zeros((batch.shape[0], self.classes), dtype=np.float32)]


def _model(session) -> la._Model:
    return la._Model(session, "waveform", "logits", 0, 0, "fake.onnx")


def _pcm(values) -> bytes:
    return np.asarray(values, dtype="<i2").tobytes()


def _source(path) -> types.SimpleNamespace:
    return types.SimpleNamespace(path=Path(path), input_args=(), is_hls=False,
                                 media_offset=0.0)


@pytest.fixture
def configured(monkeypatch, tmp_path):
    """有効化 + 極小の窓/hop。窓32 sample・hop16 sampleで前処理だけを見る。"""
    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_ENABLED", "1")
    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_WINDOW_SECONDS", "0.002")
    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_HOP_SECONDS", "0.001")
    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_ACTIVATION", "none")
    model = tmp_path / "laugh.onnx"
    model.write_bytes(b"onnx")
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps(["Speech", "Laughter", "Music", "Giggle"]),
                      encoding="utf-8")
    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_MODEL_PATH", str(model))
    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_LABELS_PATH", str(labels))
    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_CLASSES", "Laughter|Giggle")
    monkeypatch.setattr(la, "_model", None, raising=False)
    monkeypatch.setattr(la, "_model_key", None, raising=False)
    return types.SimpleNamespace(model=model, labels=labels)


# --------------------------------------------------------------------------- config


def test_classes_are_split_on_pipe_so_a_comma_in_a_class_name_survives(monkeypatch):
    monkeypatch.delenv("TICTOK_LAUGH_AUDIO_CLASSES", raising=False)
    assert "Chuckle, chortle" in config.get_laugh_audio_classes()

    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_CLASSES", " Laughter | Belly laugh |")
    assert config.get_laugh_audio_classes() == ["Laughter", "Belly laugh"]


def test_the_feature_is_off_and_unconfigured_by_default(monkeypatch):
    for name in ("TICTOK_LAUGH_AUDIO_ENABLED", "TICTOK_LAUGH_AUDIO_MODEL_PATH",
                 "TICTOK_LAUGH_AUDIO_LABELS_PATH"):
        monkeypatch.delenv(name, raising=False)
    status = la.laugh_status()
    assert status["enabled"] is False
    assert status["configured"] is False
    assert status["model"] == ""
    # GPUは転写と超解像が取り合っているので、ここは常にCPU。
    assert status["device"] == "cpu"


# --------------------------------------------------------------------------- labels


def test_labels_are_read_from_the_audioset_csv(tmp_path, monkeypatch):
    csv_path = tmp_path / "class_labels_indices.csv"
    csv_path.write_text(
        'index,mid,display_name\n'
        '0,/m/09x0r,"Speech"\n'
        '1,/m/01j3sz,"Laughter"\n'
        '2,/t/dd00135,"Chuckle, chortle"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_LABELS_PATH", str(csv_path))
    assert la._load_labels() == ["Speech", "Laughter", "Chuckle, chortle"]


def test_labels_are_read_from_a_json_index_map(tmp_path, monkeypatch):
    path = tmp_path / "labels.json"
    path.write_text(json.dumps({"1": "Laughter", "0": "Speech"}), encoding="utf-8")
    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_LABELS_PATH", str(path))
    assert la._load_labels() == ["Speech", "Laughter"]


def test_a_label_file_with_a_gap_is_rejected(tmp_path, monkeypatch):
    path = tmp_path / "labels.json"
    path.write_text(json.dumps({"0": "Speech", "2": "Laughter"}), encoding="utf-8")
    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_LABELS_PATH", str(path))
    with pytest.raises(la.LaughAudioError):
        la._load_labels()


def test_a_missing_label_file_is_an_error_not_an_empty_table(tmp_path, monkeypatch):
    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_LABELS_PATH", str(tmp_path / "nope.csv"))
    with pytest.raises(la.LaughAudioError):
        la._load_labels()

    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_LABELS_PATH", "")
    with pytest.raises(la.LaughAudioError):
        la._load_labels()


def test_a_class_that_is_not_in_the_label_file_is_an_error(monkeypatch):
    labels = ["Speech", "Laughter"]
    assert la._class_indices(labels, ["Laughter"]) == [1]
    # 綴り違いを黙って落とすと検出感度だけが下がり、出力を見ても気付けない。
    with pytest.raises(la.LaughAudioError):
        la._class_indices(labels, ["Laughter", "Laughther"])
    with pytest.raises(la.LaughAudioError):
        la._class_indices(labels, [])


# --------------------------------------------------------------------------- ffmpeg argv


def test_the_decode_command_takes_only_audio_at_the_models_sample_rate(make_recording):
    _, mp4 = make_recording()
    args = la._ffmpeg_args(_source(mp4))

    assert args[0] == "ffmpeg"
    assert "-vn" in args
    assert args[args.index("-map") + 1] == "0:a:0"
    assert args[args.index("-ac") + 1] == "1"
    assert args[args.index("-ar") + 1] == str(la.SAMPLE_RATE) == "16000"
    assert args[args.index("-f") + 1] == "s16le"
    # 波形と同じ穴埋め。これが無いと確率列のindexが末尾へ向かって手前へずれる。
    assert args[args.index("-af") + 1] == la._RESAMPLE_FILTER


def test_a_recording_without_an_mp4_is_read_from_its_segments(tmp_root, monkeypatch,
                                                              configured):
    """mp4の無い録画が普通にある。Path(src)直読みだとそこで黙って沈黙する。"""
    mp4, session = build_recording(tmp_root, with_mp4=False)
    captured = {}

    def fake_popen(args, **kwargs):
        captured["args"] = args
        raise OSError("blocked")

    monkeypatch.setattr(la.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(la, "_get_model", lambda: _model(_FakeSession()))

    with pytest.raises(la.LaughAudioError):
        la._build(mp4, 2.0, 1.0)

    args = [str(a) for a in captured["args"]]
    index = args.index("-i")
    playlist = args[index + 1]
    assert playlist.startswith(str(session)) and playlist.endswith(".m3u8")
    assert hls_source.CURATED_PREFIX in playlist, "captureのindex.m3u8を直接渡している"
    for option in rec.HLS_INPUT_ARGS:
        assert option in args[:index], f"{option} が -i より前にない"


# --------------------------------------------------------------------------- 窓の切り出し


def _first_sample_as_logit(batch: np.ndarray) -> np.ndarray:
    """窓の先頭sampleをclass 1(Laughter)のlogitへそのまま載せる。
    窓の**開始位置**が期待どおりかを、返ってきた確率だけで言い当てられるようにする。"""
    out = np.zeros((batch.shape[0], 4), dtype=np.float32)
    out[:, 1] = batch[:, 0] * 32768.0
    return out


def test_windows_start_on_the_hop_grid_and_the_tail_is_zero_padded(monkeypatch,
                                                                   configured, tmp_path):
    session = _FakeSession(fn=_first_sample_as_logit)
    total = 100
    proc = _FakeProc(_pcm([i + 1 for i in range(total)]))
    monkeypatch.setattr(la.subprocess, "Popen", lambda *a, **k: proc)

    probs, decoded = la._scan(_source(tmp_path / "x.mp4"), _model(session),
                              [1, 3], 32, 16, 3)

    assert decoded == total
    # 100 sample / hop 16 → 開始位置 0,16,...,96 の7窓。末尾は0詰めで拾う。
    assert len(probs) == 7
    assert [round(p) for p in probs] == [1, 17, 33, 49, 65, 81, 97]
    tail = session.batches[-1][-1]
    assert tail.shape == (32,)
    assert tail[4:].tolist() == [0.0] * 28, "尾の窓を0で埋めていない"


def test_windows_are_run_in_batches_of_the_configured_size(monkeypatch, configured,
                                                           tmp_path):
    session = _FakeSession()
    proc = _FakeProc(_pcm([1] * 100))
    monkeypatch.setattr(la.subprocess, "Popen", lambda *a, **k: proc)

    la._scan(_source(tmp_path / "x.mp4"), _model(session), [1], 32, 16, 3)

    assert [b.shape for b in session.batches] == [(3, 32), (3, 32), (1, 32)]


def test_a_hop_wider_than_the_window_skips_across_chunk_boundaries(monkeypatch,
                                                                   configured, tmp_path):
    """hopが窓より長い(疎sampling)設定では、窓と窓の間のsampleを読み飛ばす。
    その読み飛ばしがpipeのchunkをまたぐと、窓の開始位置が静かにずれ得る。"""
    monkeypatch.setattr(la, "READ_CHUNK_BYTES", 100)
    session = _FakeSession(fn=_first_sample_as_logit)
    monkeypatch.setattr(la.subprocess, "Popen",
                        lambda *a, **k: _FakeProc(_pcm([i + 1 for i in range(200)])))

    probs, total = la._scan(_source(tmp_path / "x.mp4"), _model(session), [1], 32, 64, 3)

    assert total == 200
    assert [round(p) for p in probs] == [1, 65, 129, 193]


def test_a_chunk_that_ends_mid_sample_does_not_shift_the_grid(monkeypatch, configured,
                                                              tmp_path):
    """s16leは2 byte/sample。chunkが奇数byteで切れた回に端数を持ち越さないと、
    以降の窓が半sampleずつずれて確率列全体が意味を失う。"""
    monkeypatch.setattr(la, "READ_CHUNK_BYTES", 51)
    session = _FakeSession(fn=_first_sample_as_logit)
    monkeypatch.setattr(la.subprocess, "Popen",
                        lambda *a, **k: _FakeProc(_pcm([i + 1 for i in range(100)])))

    probs, total = la._scan(_source(tmp_path / "x.mp4"), _model(session), [1], 32, 16, 4)

    assert total == 100
    assert [round(p) for p in probs] == [1, 17, 33, 49, 65, 81, 97]


def test_a_fixed_batch_export_overrides_the_configured_batch(monkeypatch, configured,
                                                             make_recording):
    _, mp4 = make_recording()
    session = _FakeSession()
    fixed = la._Model(session, "waveform", "logits", 2, 0, "fake.onnx")
    monkeypatch.setattr(la, "_get_model", lambda: fixed)
    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_BATCH", "32")
    monkeypatch.setattr(la.subprocess, "Popen",
                        lambda *a, **k: _FakeProc(_pcm([1] * 100)))

    la._build(mp4, 0.002, 0.001)

    assert [b.shape[0] for b in session.batches] == [2, 2, 2, 1]


def test_a_window_length_the_export_does_not_accept_is_an_error(monkeypatch,
                                                                configured,
                                                                make_recording):
    _, mp4 = make_recording()
    fixed = la._Model(_FakeSession(), "waveform", "logits", 0, 16000, "fake.onnx")
    monkeypatch.setattr(la, "_get_model", lambda: fixed)
    with pytest.raises(la.LaughAudioError):
        la._build(mp4, 2.0, 1.0)


def test_decode_failure_and_silence_are_errors_not_an_empty_profile(monkeypatch,
                                                                    configured, tmp_path):
    monkeypatch.setattr(la.subprocess, "Popen",
                        lambda *a, **k: _FakeProc(b"", b"boom", returncode=1))
    with pytest.raises(la.LaughAudioError):
        la._scan(_source(tmp_path / "x.mp4"), _model(_FakeSession()), [1], 32, 16, 4)

    monkeypatch.setattr(la.subprocess, "Popen", lambda *a, **k: _FakeProc(b""))
    with pytest.raises(la.LaughAudioError):
        la._scan(_source(tmp_path / "x.mp4"), _model(_FakeSession()), [1], 32, 16, 4)


def test_stderr_is_drained_while_stdout_is_read(monkeypatch, configured, tmp_path):
    """stdoutを読み切ってからstderrを読む形は実録画で無限hangを再現済み。
    警告がpipe bufferより大きくても解析が終わることを見る。"""
    proc = _FakeProc(_pcm([1] * 64), stderr=b"warning\n" * 20000)
    monkeypatch.setattr(la.subprocess, "Popen", lambda *a, **k: proc)

    probs, total = la._scan(_source(tmp_path / "x.mp4"), _model(_FakeSession()),
                            [1], 32, 16, 4)

    assert total == 64 and len(probs) == 4


# --------------------------------------------------------------------------- 確率の畳み方


def test_multiple_classes_are_folded_with_max_not_a_sum(monkeypatch, configured):
    raw = np.array([[0.0, 2.0, 0.0, 3.0]], dtype=np.float32)
    session = _FakeSession(fn=lambda batch: raw)
    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_ACTIVATION", "none")

    probs = la._batch_probs(_model(session), [np.zeros(32, dtype=np.float32)], [1, 3])

    assert probs == [3.0], "多labelの確率を足している"


def test_logits_become_probabilities_through_the_configured_activation(monkeypatch,
                                                                       configured):
    raw = np.array([[0.0, 0.0, 0.0, 0.0]], dtype=np.float32)
    session = _FakeSession(fn=lambda batch: raw)
    window = [np.zeros(32, dtype=np.float32)]

    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_ACTIVATION", "sigmoid")
    assert la._batch_probs(_model(session), window, [1]) == [0.5]

    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_ACTIVATION", "softmax")
    with pytest.raises(la.LaughAudioError):
        la._batch_probs(_model(session), window, [1])


def test_a_label_file_wider_than_the_model_output_is_an_error(monkeypatch, configured):
    session = _FakeSession(fn=lambda batch: np.zeros((batch.shape[0], 2), dtype=np.float32))
    with pytest.raises(la.LaughAudioError):
        la._batch_probs(_model(session), [np.zeros(32, dtype=np.float32)], [7])


def test_an_output_that_is_not_batch_by_classes_is_an_error(monkeypatch, configured):
    session = _FakeSession(fn=lambda batch: np.zeros((3, 3, 3), dtype=np.float32))
    with pytest.raises(la.LaughAudioError):
        la._batch_probs(_model(session), [np.zeros(32, dtype=np.float32)], [1])


def test_a_batch_one_classes_output_is_squeezed_not_rejected(monkeypatch, configured):
    session = _FakeSession(
        fn=lambda batch: np.full((batch.shape[0], 1, 4), 1.0, dtype=np.float32))
    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_ACTIVATION", "none")
    assert la._batch_probs(_model(session), [np.zeros(32, dtype=np.float32)], [1]) == [1.0]


# --------------------------------------------------------------------------- model検査


def test_only_a_waveform_input_export_is_accepted():
    """log-mel入力を支えるとmel filter数・hop・窓関数をこちらが推測することになり、
    学習時と少しでも違えば確率が静かに壊れる。受けない方を選ぶ。"""
    mel = types.SimpleNamespace(get_inputs=lambda: [
        types.SimpleNamespace(name="mel", shape=[1, 64, 1001])],
        get_outputs=lambda: [types.SimpleNamespace(name="logits")])
    with pytest.raises(la.LaughAudioError):
        la._describe(mel, Path("m.onnx"))

    wave = types.SimpleNamespace(get_inputs=lambda: [
        types.SimpleNamespace(name="waveform", shape=["batch", 32000])],
        get_outputs=lambda: [types.SimpleNamespace(name="logits")])
    described = la._describe(wave, Path("m.onnx"))
    assert described.fixed_batch == 0 and described.fixed_samples == 32000


def test_loading_the_model_reports_every_missing_prerequisite(monkeypatch, tmp_path):
    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_ENABLED", "0")
    with pytest.raises(la.LaughAudioError, match="無効"):
        la._get_model()

    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_ENABLED", "1")
    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_MODEL_PATH", "")
    with pytest.raises(la.LaughAudioError, match="未設定"):
        la._get_model()

    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_MODEL_PATH", str(tmp_path / "absent.onnx"))
    with pytest.raises(la.LaughAudioError, match="見つかりません"):
        la._get_model()


def test_the_model_runs_on_the_cpu_provider_only(monkeypatch, configured):
    """GPUは転写と超解像が12GBを奪い合っている。ここが取ると焼き込みが待たされる。"""
    ort = pytest.importorskip("onnxruntime")
    captured = {}

    class _Options:
        intra_op_num_threads = 0
        inter_op_num_threads = 0

    def fake_session(path, sess_options=None, providers=None):
        captured["providers"] = providers
        captured["intra"] = sess_options.intra_op_num_threads
        return types.SimpleNamespace(
            get_inputs=lambda: [types.SimpleNamespace(name="waveform",
                                                      shape=["b", "n"])],
            get_outputs=lambda: [types.SimpleNamespace(name="logits")])

    monkeypatch.setattr(ort, "SessionOptions", _Options)
    monkeypatch.setattr(ort, "InferenceSession", fake_session)
    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_THREADS", "2")

    la._get_model()

    assert captured["providers"] == ["CPUExecutionProvider"]
    assert captured["intra"] == 2


# --------------------------------------------------------------------------- sidecar


def _profile(**over) -> dict:
    profile = {
        "interval_seconds": 1.0,
        "duration_seconds": 4.0,
        "probs": [0.05, 0.9, 0.4, 0.02],
        "window_seconds": 2.0,
        "hop_seconds": 1.0,
        "classes": ["Laughter", "Giggle"],
        "threshold": 0.35,
        "activation": "sigmoid",
        "sample_rate": la.SAMPLE_RATE,
    }
    profile.update(over)
    return profile


@pytest.fixture
def cacheable(configured, monkeypatch):
    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_ACTIVATION", "sigmoid")
    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_WINDOW_SECONDS", "2.0")
    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_HOP_SECONDS", "1.0")
    return configured


def test_the_sidecar_stores_raw_probabilities_and_reloads_them(make_recording, cacheable):
    _, mp4 = make_recording()
    profile = _profile()
    la._store_cache(mp4, {**profile, **la._model_fingerprint()})

    written = json.loads(la.laugh_profile_path(mp4).read_text(encoding="utf-8"))
    assert written["probs"] == profile["probs"]
    assert written["version"] == la._PROFILE_VERSION
    assert written["model"] == cacheable.model.name
    assert all(0.0 <= p <= 1.0 for p in written["probs"])

    assert la._load_cache(mp4, 2.0, 1.0) == profile


def test_changing_only_the_threshold_keeps_the_cache(make_recording, cacheable,
                                                     monkeypatch):
    """閾値を掛ける前の確率を保存しているのは、後から閾値を掃引するため。
    閾値の変更で解析がやり直しになるなら、その狙いが成立していない。"""
    _, mp4 = make_recording()
    la._store_cache(mp4, {**_profile(), **la._model_fingerprint()})

    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_THRESHOLD", "0.8")
    assert la._load_cache(mp4, 2.0, 1.0)["probs"] == _profile()["probs"]


def test_the_cache_follows_the_window_classes_activation_and_model(make_recording,
                                                                   cacheable, monkeypatch):
    _, mp4 = make_recording()
    la._store_cache(mp4, {**_profile(), **la._model_fingerprint()})
    assert la._load_cache(mp4, 2.0, 1.0)

    assert la._load_cache(mp4, 2.0, 0.5) == {}
    assert la._load_cache(mp4, 3.0, 1.0) == {}

    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_CLASSES", "Laughter")
    assert la._load_cache(mp4, 2.0, 1.0) == {}
    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_CLASSES", "Laughter|Giggle")

    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_ACTIVATION", "none")
    assert la._load_cache(mp4, 2.0, 1.0) == {}
    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_ACTIVATION", "sigmoid")

    # weightsを差し替えたら確率が変わる。素材が同じでも当ててはいけない。
    cacheable.model.write_bytes(b"different weights")
    assert la._load_cache(mp4, 2.0, 1.0) == {}


def test_the_cache_follows_the_material(make_recording, cacheable):
    _, mp4 = make_recording()
    la._store_cache(mp4, {**_profile(), **la._model_fingerprint()})
    assert la._load_cache(mp4, 2.0, 1.0)

    mp4.write_bytes(b"\x00" * 4096)
    assert la._load_cache(mp4, 2.0, 1.0) == {}


def test_a_stale_schema_version_invalidates_the_sidecar(make_recording, cacheable):
    _, mp4 = make_recording()
    la._store_cache(mp4, {**_profile(), **la._model_fingerprint()})
    path = la.laugh_profile_path(mp4)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["version"] = la._PROFILE_VERSION + 1
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert la._load_cache(mp4, 2.0, 1.0) == {}


def test_the_sidecar_is_listed_as_an_artifact_of_the_recording(make_recording):
    _, mp4 = make_recording()
    assert la.laugh_profile_path(mp4) in la.laugh_artifact_paths(mp4)
    assert la.laugh_profile_path(mp4).name.endswith(la.LAUGH_SUFFIX)


# --------------------------------------------------------------------------- 閾値の適用


def test_laugh_seconds_counts_the_bins_over_the_threshold():
    profile = _profile(probs=[0.05, 0.9, 0.4, 0.02])
    assert la.laugh_seconds(profile, 0.0, 4.0, threshold=0.35) == 2.0
    assert la.laugh_seconds(profile, 0.0, 4.0, threshold=0.95) == 0.0
    assert la.laugh_seconds(profile, 1.0, 2.0, threshold=0.35) == 1.0


def test_laugh_seconds_uses_the_configured_threshold_by_default(monkeypatch):
    profile = _profile(probs=[0.4, 0.4])
    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_THRESHOLD", "0.9")
    assert la.laugh_seconds(profile, 0.0, 2.0) == 0.0
    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_THRESHOLD", "0.3")
    assert la.laugh_seconds(profile, 0.0, 2.0) == 2.0


def test_laugh_seconds_clamps_the_window_to_the_profile():
    profile = _profile(probs=[0.9, 0.9])
    assert la.laugh_seconds(profile, 0.0, 900.0, threshold=0.35) == 2.0


def test_laugh_seconds_returns_none_where_nothing_was_analysed():
    """解析していない区間を0秒と答えると、「笑いが無かった」区間として集計に入る。"""
    profile = _profile(probs=[0.9, 0.9])
    assert la.laugh_seconds(profile, 10.0, 12.0) is None
    assert la.laugh_seconds(profile, 1.0, 1.0) is None
    assert la.laugh_seconds(profile, -1.0, 1.0) is None


def test_a_scaled_hop_changes_the_seconds_each_bin_is_worth():
    profile = _profile(interval_seconds=0.5, probs=[0.9, 0.9, 0.0, 0.9])
    assert la.laugh_seconds(profile, 0.0, 2.0, threshold=0.35) == 1.5


# --------------------------------------------------------------------------- 入口


async def test_the_entry_point_refuses_to_run_while_disabled(make_recording, monkeypatch):
    _, mp4 = make_recording()
    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_ENABLED", "0")
    with pytest.raises(la.LaughAudioError):
        await la.ensure_laugh_profile(mp4)


async def test_the_entry_point_reports_a_recording_with_no_material_as_missing(
        tmp_root, configured):
    mp4, session = build_recording(tmp_root, with_mp4=False)
    for seg in session.glob("seg*.ts"):
        seg.unlink()
    with pytest.raises(hls_source.SourceMissing):
        await la.ensure_laugh_profile(mp4)


async def test_the_entry_point_returns_a_matching_sidecar_without_decoding(
        make_recording, cacheable, monkeypatch):
    _, mp4 = make_recording()
    la._store_cache(mp4, {**_profile(), **la._model_fingerprint()})

    def forbidden(*args, **kwargs):
        raise AssertionError("cacheがあるのにffmpegを起こしている")

    monkeypatch.setattr(la.subprocess, "Popen", forbidden)
    assert (await la.ensure_laugh_profile(mp4))["probs"] == _profile()["probs"]


async def test_a_broken_model_setting_is_not_masked_by_a_valid_sidecar(
        make_recording, cacheable):
    """modelを直したつもりで直っていないことに気付けるよう、cacheより先に設定を見る。"""
    _, mp4 = make_recording()
    la._store_cache(mp4, {**_profile(), **la._model_fingerprint()})
    cacheable.model.unlink()
    with pytest.raises(la.LaughAudioError):
        await la.ensure_laugh_profile(mp4)


async def test_the_end_to_end_build_writes_the_sidecar(make_recording, configured,
                                                       monkeypatch):
    _, mp4 = make_recording()
    session = _FakeSession(fn=lambda batch: np.full((batch.shape[0], 4), 0.75,
                                                    dtype=np.float32))
    monkeypatch.setattr(la, "_get_model", lambda: _model(session))
    monkeypatch.setattr(la.subprocess, "Popen",
                        lambda *a, **k: _FakeProc(_pcm([1000] * 160)))
    monkeypatch.setattr(la, "ffmpeg_available", lambda: True)

    profile = await la.ensure_laugh_profile(mp4)

    assert profile["interval_seconds"] == 0.001
    assert profile["window_seconds"] == 0.002
    assert profile["duration_seconds"] == round(160 / la.SAMPLE_RATE, 3)
    assert profile["probs"] == [0.75] * 10
    assert la.laugh_profile_path(mp4).is_file()
    # 2回目はcacheに当たり、ffmpegは起こさない。
    monkeypatch.setattr(la.subprocess, "Popen",
                        lambda *a, **k: pytest.fail("cacheに当たっていない"))
    assert (await la.ensure_laugh_profile(mp4))["probs"] == profile["probs"]


# --------------------------------------------------------------------------- 実model


@pytest.mark.skipif(
    not os.environ.get("TICTOK_LAUGH_AUDIO_MODEL_PATH")
    or not Path(os.environ["TICTOK_LAUGH_AUDIO_MODEL_PATH"]).is_file(),
    reason="needs a real laugh-detection ONNX model (TICTOK_LAUGH_AUDIO_MODEL_PATH)",
)
def test_the_real_model_accepts_a_window_of_silence(monkeypatch):
    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_ENABLED", "1")
    model = la._get_model()
    labels = la._load_labels()
    indices = la._class_indices(labels, config.get_laugh_audio_classes())
    window = int(round(config.get_laugh_audio_window_seconds() * la.SAMPLE_RATE))
    probs = la._batch_probs(model, [np.zeros(model.fixed_samples or window,
                                             dtype=np.float32)], indices)
    assert len(probs) == 1
    assert 0.0 <= probs[0] <= 1.0
