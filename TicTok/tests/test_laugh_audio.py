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
    # GPUは文字起こしと超解像が取り合っているので、ここは常にCPU。
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
    """既定ではGPUを取らない。12GBは文字起こしと超解像が奪い合っており、ここが割り込むと
    焼き込みが待たされる。GPUで走らせたい場合だけ TICTOK_LAUGH_AUDIO_DEVICE=cuda に
    して、**別process**(laugh_worker)へ出す。"""
    ort = pytest.importorskip("onnxruntime")
    captured = {}

    class _Options:
        intra_op_num_threads = 0
        inter_op_num_threads = 0

    def fake_session(path, sess_options=None, providers=None):
        captured["providers"] = providers
        captured["intra"] = sess_options.intra_op_num_threads
        return types.SimpleNamespace(
            get_providers=lambda: list(providers or []),
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


# --------------------------------------------------------------------------- 窓の除外


def test_excluded_spans_are_not_counted():
    """コラボ中(顔が2つ以上)の笑いを候補から外すための口。"""
    profile = _profile(probs=[0.9] * 10)
    assert la.laugh_seconds(profile, 0.0, 10.0, threshold=0.5) == 10.0
    assert la.laugh_seconds(profile, 0.0, 10.0, threshold=0.5,
                            exclude_spans=[(2.0, 5.0)]) == 7.0
    assert la.laugh_seconds(profile, 0.0, 10.0, threshold=0.5,
                            exclude_spans=[(0.0, 10.0)]) == 0.0


def test_a_span_shorter_than_one_bin_still_removes_that_bin():
    """中心が入るかで判定すると、刻みより短い窓が1つも外れない。"""
    profile = _profile(probs=[0.9] * 10)
    assert la.laugh_seconds(profile, 0.0, 10.0, threshold=0.5,
                            exclude_spans=[(3.2, 3.4)]) == 9.0


def test_overlapping_spans_do_not_subtract_twice():
    profile = _profile(probs=[0.9] * 10)
    assert la.laugh_seconds(profile, 0.0, 10.0, threshold=0.5,
                            exclude_spans=[(1.0, 4.0), (3.0, 6.0)]) == 5.0


def test_spans_outside_the_window_and_empty_spans_change_nothing():
    profile = _profile(probs=[0.9] * 10)
    for spans in ([], None, [(20.0, 30.0)], [(5.0, 5.0)], [(6.0, 3.0)]):
        assert la.laugh_seconds(profile, 0.0, 10.0, threshold=0.5,
                                exclude_spans=spans) == 10.0


def test_excluding_everything_is_zero_seconds_not_unanalysed():
    """全部外れた区間は「笑いが0秒」であって「解析していない」ではない。Noneを返すと
    呼び出し側(_MaterialMetric)が指標ごと録画から外してしまう。"""
    profile = _profile(probs=[0.9, 0.9])
    assert la.laugh_seconds(profile, 0.0, 2.0, threshold=0.5,
                            exclude_spans=[(0.0, 2.0)]) == 0.0


# --------------------------------------------------------------------------- 検索index


def _laugh_profile(probs, interval=1.0) -> dict:
    return {"interval_seconds": interval, "probs": probs, "duration_seconds": len(probs)}


def test_laugh_windows_folds_consecutive_bins_into_one_scene():
    """1回の笑いを刻みのまま行にすると、検索結果が同じ場面で埋まる。"""
    from tictok.search.indexer import laugh_windows
    profile = _laugh_profile([0.0, 0.9, 0.9, 0.9, 0.0])
    assert laugh_windows(profile, 0.5, 0.0, 0.0) == [(1.0, 4.0, 0.9)]


def test_a_short_dip_inside_one_laugh_does_not_split_the_scene():
    """笑い声は息継ぎで確率が1〜2刻み落ちる。同じ笑いの中の出来事なのでつなぐ。"""
    from tictok.search.indexer import laugh_windows
    profile = _laugh_profile([0.9, 0.1, 0.9])
    assert laugh_windows(profile, 0.5, 2.0, 0.0) == [(0.0, 3.0, 0.9)]
    # 隙間を許さない設定では2つに割れる(畳んでいるのは設定であってlogicではない)。
    assert laugh_windows(profile, 0.5, 0.0, 0.0) == [(0.0, 1.0, 0.9), (2.0, 3.0, 0.9)]


def test_windows_shorter_than_the_minimum_are_dropped():
    """1刻みだけ閾値を超える点は録画1本で数百個出る。全部出すと本物が埋もれる。"""
    from tictok.search.indexer import laugh_windows
    profile = _laugh_profile([0.9, 0.0, 0.0, 0.9, 0.9, 0.9])
    assert laugh_windows(profile, 0.5, 0.0, 2.0) == [(3.0, 6.0, 0.9)]


def test_the_window_carries_the_strongest_probability_inside_it():
    """閾値を超えたかだけだと、はっきり笑った場面と辛うじて超えた場面が同じ顔で並ぶ。"""
    from tictok.search.indexer import laugh_windows
    assert laugh_windows(_laugh_profile([0.6, 0.95, 0.7]), 0.5, 2.0, 0.0) \
        == [(0.0, 3.0, 0.95)]


def test_nothing_over_the_threshold_is_no_windows_not_one_empty_window():
    from tictok.search.indexer import laugh_windows
    assert laugh_windows(_laugh_profile([0.1, 0.2]), 0.5, 2.0, 0.0) == []
    assert laugh_windows(_laugh_profile([]), 0.5, 2.0, 0.0) == []


class _Store:
    """indexerが触るstorageの最小面。共演窓は「1つも記録が無い」を既定にする
    (窓を持たないsessionでの索引はこれまでと同じ結果でなければならない)。"""

    def __init__(self, collab=(), battle=(), collab_observed=True):
        self.written = {}
        self.meta = None
        self.calls = []
        self._coop = {"collab": list(collab), "battle": list(battle),
                      "collab_observed": collab_observed}

    def replace_search_hits(self, recording_id, source, rows):
        self.written[source] = rows
        self.calls.append((recording_id, source, len(rows)))
        return len(rows)

    def coop_windows_for_session(self, session_id):
        return self._coop

    def next_recording_start(self, session_id, started_at):
        return None

    def set_laugh_index_meta(self, recording_id, meta):
        self.meta = meta
        return True


def test_index_laughter_writes_rows_a_person_can_choose_from(monkeypatch):
    """行の本文だけで「どれを開くか」を選べること。強さは並べ替えに使うので、本文の
    文字列とは別に数値でも持つこと(本文から読み戻すのは表示の書式を数値の出所にする)。"""
    from tictok.search import indexer
    monkeypatch.setenv("TICTOK_LAUGH_INDEX_MERGE_GAP_SECONDS", "0")
    monkeypatch.setenv("TICTOK_LAUGH_INDEX_MIN_SECONDS", "0")
    store = _Store()
    written = store.written

    recording = {"id": 7, "session_id": 3, "unique_id": "@who", "started_at": 100.0}
    count = indexer.index_laughter(store, recording,
                                   _laugh_profile([0.0, 0.8, 0.8]), threshold=0.5)
    assert count == 1
    row = written[indexer.SOURCE_LAUGH][0]
    assert (row["video_time"], row["end_time"]) == (1.0, 3.0)
    assert row["body"] == "2秒（強さ 0.80）"
    assert row["unique_id"] == "@who" and row["session_id"] == 3
    assert row["score"] == pytest.approx(0.8)
    # 種別は行の種別欄が名乗る。本文で繰り返すと、一覧の全行が同じ語で始まる。
    assert "笑い声" not in row["body"]


def test_index_laughter_replaces_the_previous_rows_for_the_recording():
    """閾値を変えて入れ直したとき、古い窓が残ると同じ場面が二重に並ぶ。"""
    from tictok.search import indexer
    store = _Store()
    recording = {"id": 7, "session_id": None, "unique_id": "@who", "started_at": 0.0}
    indexer.index_laughter(store, recording, _laugh_profile([0.1, 0.1]), threshold=0.5)
    # 1件も無くてもreplaceは呼ぶ(呼ばないと前回の窓が残る)。
    assert store.calls == [(7, indexer.SOURCE_LAUGH, 0)]


# ------------------------------------------------------- 共演中(コラボ・Battle)の除外


def _coop_recording() -> dict:
    """時間軸mapが無い録画。壁時計 -> 動画時間は素のoffsetへ縮退するので、窓の秒が
    そのまま読める(mapper自体はindex_commentsと共有で、別testが見ている)。"""
    return {"id": 7, "session_id": 3, "unique_id": "@who", "path": "no-such-file.mp4",
            "started_at": 100.0, "ended_at": 110.0}


def test_laughter_inside_a_collab_window_never_reaches_the_list(monkeypatch):
    """コラボ中の音声には相手の声が乗っており、どの笑いが配信者のものかを音から決める
    手段が無い。一覧は「この配信者が笑った場面」として読まれるので行にしない。"""
    from tictok.search import indexer
    monkeypatch.setenv("TICTOK_LAUGH_INDEX_MERGE_GAP_SECONDS", "0")
    monkeypatch.setenv("TICTOK_LAUGH_INDEX_MIN_SECONDS", "0")
    # 0-2秒と6-8秒に笑い。コラボは壁時計105-108(=動画5-8秒)。
    probs = [0.9, 0.9, 0.0, 0.0, 0.0, 0.0, 0.9, 0.9]
    store = _Store(collab=[(105.0, 108.0)])
    count = indexer.index_laughter(store, _coop_recording(), _laugh_profile(probs),
                                  threshold=0.5)
    assert count == 1
    assert [(r["video_time"], r["end_time"]) for r in store.written[indexer.SOURCE_LAUGH]]         == [(0.0, 2.0)]
    assert store.meta["collab_seconds"] == 3.0
    assert store.meta["excluded_laugh_seconds"] == 2.0


def test_a_window_is_not_merged_across_the_excluded_stretch(monkeypatch):
    """除外区間は谷ではなく切れ目。merge_gapでつなぐと共演中を跨いだ1つの窓になり、
    外したはずの秒が窓の長さへ戻ってくる。"""
    from tictok.search import indexer
    monkeypatch.setenv("TICTOK_LAUGH_INDEX_MERGE_GAP_SECONDS", "10")
    monkeypatch.setenv("TICTOK_LAUGH_INDEX_MIN_SECONDS", "0")
    probs = [0.9, 0.0, 0.0, 0.0, 0.9]
    store = _Store(collab=[(101.0, 104.0)])
    indexer.index_laughter(store, _coop_recording(), _laugh_profile(probs), threshold=0.5)
    assert [(r["video_time"], r["end_time"]) for r in store.written[indexer.SOURCE_LAUGH]]         == [(0.0, 1.0), (4.0, 5.0)]


def test_battle_windows_are_excluded_only_when_asked_for(monkeypatch):
    """Battleもコラボと同じく相手の声が乗るが、外す範囲は設定で決める。"""
    from tictok.search import indexer
    monkeypatch.setenv("TICTOK_LAUGH_INDEX_MERGE_GAP_SECONDS", "0")
    monkeypatch.setenv("TICTOK_LAUGH_INDEX_MIN_SECONDS", "0")
    probs = [0.9, 0.9]
    monkeypatch.setenv("TICTOK_LAUGH_INDEX_EXCLUDE_COOP", "coop")
    store = _Store(battle=[(100.0, 102.0)])
    assert indexer.index_laughter(store, _coop_recording(), _laugh_profile(probs),
                                  threshold=0.5) == 0
    assert store.meta["battle_seconds"] == 2.0

    monkeypatch.setenv("TICTOK_LAUGH_INDEX_EXCLUDE_COOP", "collab")
    store = _Store(battle=[(100.0, 102.0)])
    assert indexer.index_laughter(store, _coop_recording(), _laugh_profile(probs),
                                  threshold=0.5) == 1
    assert store.meta["battle_seconds"] == 0.0


def test_battle_seconds_do_not_double_count_the_overlap_with_a_collab(monkeypatch):
    """コラボとBattleは同じLinkMicの上で起きて重なり得る。そのまま足すと、外した秒の
    合計が実際より長く見える。"""
    from tictok.search import indexer
    monkeypatch.setenv("TICTOK_LAUGH_INDEX_EXCLUDE_COOP", "coop")
    store = _Store(collab=[(100.0, 106.0)], battle=[(104.0, 108.0)])
    indexer.index_laughter(store, _coop_recording(), _laugh_profile([0.0] * 10),
                           threshold=0.5)
    assert (store.meta["collab_seconds"], store.meta["battle_seconds"]) == (6.0, 2.0)


def test_a_session_from_before_collab_was_recorded_says_it_excluded_nothing(monkeypatch):
    """記録の無いことを「コラボが無かった」と読まない。外れていない索引を「外した」と
    名乗ると、共演中の笑いが配信者のものとして一覧に並び続ける。"""
    from tictok.search import indexer
    store = _Store(collab_observed=False)
    indexer.index_laughter(store, _coop_recording(), _laugh_profile([0.9, 0.9]),
                           threshold=0.5)
    assert store.meta["collab_observed"] is False
    assert store.meta["collab_seconds"] == 0.0


def test_the_conditions_of_the_index_are_recorded_on_the_recording(monkeypatch):
    """条件を残さないと、設定を変えた後も古い条件のindexが済みのまま残る
    (一括処理の済み判定がこの記録を見る)。"""
    from tictok.search import indexer
    monkeypatch.setenv("TICTOK_LAUGH_INDEX_EXCLUDE_COOP", "collab")
    store = _Store()
    indexer.index_laughter(store, _coop_recording(), _laugh_profile([0.9]), threshold=0.5)
    assert store.meta["version"] == indexer.LAUGH_INDEX_VERSION
    assert store.meta["mode"] == "collab"
    assert store.meta["threshold"] == 0.5


def test_an_unreadable_exclusion_setting_is_refused_rather_than_guessed(monkeypatch):
    """外す範囲を推測で決めると、外したつもりで外れていない索引が黙って出来上がる。"""
    from tictok.core.config import ConfigError, get_laugh_index_exclude_coop
    monkeypatch.setenv("TICTOK_LAUGH_INDEX_EXCLUDE_COOP", "collabo")
    with pytest.raises(ConfigError):
        get_laugh_index_exclude_coop()


# --------------------------------------------------------------------------- device


def test_the_device_is_cpu_unless_asked_otherwise(monkeypatch):
    monkeypatch.delenv("TICTOK_LAUGH_AUDIO_DEVICE", raising=False)
    assert config.get_laugh_audio_device() == "cpu"


def test_an_unknown_device_is_rejected_instead_of_falling_back(monkeypatch, configured):
    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_DEVICE", "gpu")
    with pytest.raises(la.LaughAudioError, match="TICTOK_LAUGH_AUDIO_DEVICE"):
        la._get_model()


def test_a_provider_that_silently_became_cpu_is_an_error(monkeypatch, configured):
    """onnxruntimeは要求したproviderを作れないと**黙ってCPUへ落ちる**(実測)。落ちたことは
    確率を見ても分からないので、名乗らせて突き合わせる。"""
    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_DEVICE", "cuda")

    class _Session:
        def get_providers(self):
            return ["CPUExecutionProvider"]

    fake = types.SimpleNamespace(
        SessionOptions=lambda: types.SimpleNamespace(),
        InferenceSession=lambda *a, **k: _Session(),
    )
    monkeypatch.setitem(__import__("sys").modules, "onnxruntime", fake)
    with pytest.raises(la.LaughAudioError, match="CUDAExecutionProvider"):
        la._get_model()


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


# 実modelの設定は**import時に控えておく**。conftestの env_guard が TICTOK_* を一掃するため、
# 収集時のskip判定(os.environを直接見る)と実行時の設定が食い違い、「modelが未設定」で落ちる。
_REAL_MODEL = os.environ.get("TICTOK_LAUGH_AUDIO_MODEL_PATH", "")
_REAL_LABELS = os.environ.get("TICTOK_LAUGH_AUDIO_LABELS_PATH", "")
_REAL_ACTIVATION = os.environ.get("TICTOK_LAUGH_AUDIO_ACTIVATION", "")
_REAL_WINDOW = os.environ.get("TICTOK_LAUGH_AUDIO_WINDOW_SECONDS", "")


@pytest.mark.skipif(
    not _REAL_MODEL or not Path(_REAL_MODEL).is_file()
    or not _REAL_LABELS or not Path(_REAL_LABELS).is_file(),
    reason="needs a real laugh-detection ONNX model (TICTOK_LAUGH_AUDIO_MODEL_PATH)",
)
def test_the_real_model_accepts_a_window_of_silence(monkeypatch):
    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_ENABLED", "1")
    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_MODEL_PATH", _REAL_MODEL)
    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_LABELS_PATH", _REAL_LABELS)
    if _REAL_ACTIVATION:
        monkeypatch.setenv("TICTOK_LAUGH_AUDIO_ACTIVATION", _REAL_ACTIVATION)
    if _REAL_WINDOW:
        monkeypatch.setenv("TICTOK_LAUGH_AUDIO_WINDOW_SECONDS", _REAL_WINDOW)
    # deviceは既定(cpu)のままにする。testが12GBのGPUを掴むとjobと衝突する。
    monkeypatch.setattr(la, "_model", None, raising=False)
    monkeypatch.setattr(la, "_model_key", None, raising=False)
    model = la._get_model()
    labels = la._load_labels()
    indices = la._class_indices(labels, config.get_laugh_audio_classes())
    window = int(round(config.get_laugh_audio_window_seconds() * la.SAMPLE_RATE))
    probs = la._batch_probs(model, [np.zeros(model.fixed_samples or window,
                                             dtype=np.float32)], indices)
    assert len(probs) == 1
    assert 0.0 <= probs[0] <= 1.0
