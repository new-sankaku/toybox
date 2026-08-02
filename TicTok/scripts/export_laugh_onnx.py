"""笑い声検出(AudioSet audio tagging)のONNXを、**波形入力**でexportする。

``tictok/media/laugh_audio.py`` が受けるのは16kHz monoの生波形 ``(batch, samples)`` を
入力に取るONNXだけである(``_describe``)。一方、CED系の公開weightsはどれもmel入力で、
mel front-endはmodelの外(``CedFeatureExtractor``)に居る。melの本数・hop・窓関数・dB化を
tictok側が推測で書くと、学習時と少しでも違ったときに確率が静かに壊れ、出力を見ても
気付けない — だから **mel front-endをgraphへ取り込んで再exportする** のがこのscriptの仕事。

doc/LAUGH_AUDIO_MODEL.md の「再export」節の実施版である。

== 何を確定させたか ==

前処理は推測せず、model repositoryの ``preprocessor_config.json`` から読む
(``AutoFeatureExtractor``)。``top_db`` だけは ``feature_extraction_ced.py`` の
``AmplitudeToDB(top_db=120)`` にhard-codeされていて設定に出てこないので、こちらも定数で
持ち、後段のparity checkで一致を確かめる。

**出力は既に確率である。** ``CedForAudioClassification.forward_head`` は
``pooling="mean"`` の枝で ``.sigmoid()`` を掛けて返す。したがって設定は
``TICTOK_LAUGH_AUDIO_ACTIVATION=none``。ここでsigmoidを二重に掛けると値が
[0.5, 0.73] へ潰れるだけで、結果を見ても誤りに気付けない(doc参照)。

== 固定窓でexportする理由 ==

窓長(samples)は**固定**、batchだけ可変でexportする。CEDは
``time_pos_embed[:, :, :, :t]`` で位置埋め込みを入力長に合わせて切り、mel frameが
``target_length``(1012 frame ≒ 10.12秒)を超えると入力を分割する枝を持つ。可変長のまま
traceするとこれらの分岐がtrace時の値で焼き付き、別の長さを渡したときに黙って別物の
graphとして動く。engine側は ``fixed_samples`` を読んで
``TICTOK_LAUGH_AUDIO_WINDOW_SECONDS`` と突き合わせ、食い違えば例外にするので、固定に
しておけば「exportした長さ以外では動かない」ことが実行前に分かる。

== dB floorをbatchで共有しない ==

torchaudioの ``AmplitudeToDB(top_db=...)`` は、floorを
``x.amax(dim=(-3, -2, -1)) - top_db`` で作る。入力が ``(batch, mel, frame)`` のときこの
amaxは**batch全体の最大**になるため、同じ窓でも一緒にbatchへ入った他の窓次第で特徴量が
変わる。model cardの用例は1 clipずつ渡す形なので、学習・評価時の意味は「clipごとのfloor」
である。ここでは窓ごとにfloorを取る(``dim=(-2, -1)``)。結果としてbatch sizeを変えても
確率が動かなくなる — engineは ``TICTOK_LAUGH_AUDIO_BATCH`` を自由に変えるので、これは
正しさの条件でもある。

== 使い方 ==

runtimeには不要な依存(transformers / torchaudio)を使うので、このscriptは解析serverでは
なく手元で1度だけ走らせる:

    pip install transformers torchaudio
    python scripts/export_laugh_onnx.py --out models/laugh

出力は3つ:
    ced_tiny_waveform_<窓長>s.onnx   波形入力のONNX
    labels.json                      出力indexからclass名(model同梱のid2label)
    EXPORT.md                        exportの実測値・設定の写し

labelは **読み込んだmodelの ``config.id2label`` をそのまま** 書き出す。CEDはここが紛らわしい:
repositoryの ``config.json`` に入っているid2labelは表記が短い(index 21 が ``Chuckle`` )が、
``CedConfig.__init__`` が読み込み時にAudioSet公式の ``class_labels_indices.csv`` で
**上書きする** ため、実際に効くのは公式表記(index 21 = ``Chuckle, chortle``)である。
config.jsonを直接読んでlabel fileを作ると、並びは同じでも綴りが食い違い、
``TICTOK_LAUGH_AUDIO_CLASSES`` の名前解決が落ちる。
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# CEDの既定repository。--model で差し替えられる(weightsをhard-codeしない方針)。
DEFAULT_MODEL = "mispeech/ced-tiny"
# feature_extraction_ced.py の AmplitudeToDB(top_db=120) の写し。設定に出てこないので
# ここで持つ。値がずれれば parity check が落ちる。
TOP_DB = 120.0
# AmplitudeToDB(stype="power") の定数。10*log10(clamp(x, min=amin))。
_DB_MULTIPLIER = 10.0
_AMIN = 1e-10
# 笑いとみなすclass。``TICTOK_LAUGH_AUDIO_CLASSES`` の既定と同じ並びで、EXPORT.mdへ
# そのまま書き出す。``Baby laughter``(index 17)は入れない — 乳児の声は配信の笑いとは
# 別の場面である(doc/LAUGH_AUDIO_MODEL.md)。
LAUGH_CLASSES = ("Laughter", "Giggle", "Snicker", "Belly laugh", "Chuckle, chortle")
# parity(torch参照経路 vs ONNX)の許容差。確率は0〜1なので絶対差で見る。
PARITY_TOLERANCE = 1e-4
# STFTのexportに要るopset。
OPSET = 17


def _import_deps():
    """export専用の依存をここで読む。未installなら何が足りないかを名指しで返す。"""
    missing = []
    try:
        import torch
    except ImportError:
        torch = None
        missing.append("torch")
    try:
        import torchaudio
    except ImportError:
        torchaudio = None
        missing.append("torchaudio")
    try:
        import transformers
    except ImportError:
        transformers = None
        missing.append("transformers")
    if missing:
        raise SystemExit(
            "exportに必要なpackageが未installです: %s\n"
            "  pip install %s" % (", ".join(missing), " ".join(missing))
        )
    return torch, torchaudio, transformers


def build_wrapper(torch, torchaudio, model, extractor):
    """mel front-end + 分類modelを1つの ``nn.Module`` へ包む。

    forward は ``(batch, samples)`` の16kHz mono波形(full scale ±1.0)を受け、
    ``(batch, classes)`` の確率を返す。

    == STFTをconv1dで書く理由 ==

    ``torchaudio.transforms.MelSpectrogram`` をそのままtraceすると
    ``torch.stft(return_complex=True)`` に当たり、opset 17のexporterが
    「STFT does not currently support complex types」で落ちる(実測)。そこで窓掛けDFTを
    **固定重みのconv1d**として書き下す。これは近似ではなく同じ式で、実際に等しいことは
    後段のparity check(model cardの経路との突き合わせ)が確かめる。

    窓とmel filterbankは自分で作らず、``MelSpectrogram`` が持っているbuffer
    (``spectrogram.window`` / ``mel_scale.fb``)をそのまま使う。窓関数の周期・mel scaleの
    式・正規化をこちらで書き直せば、それはまさにdocが禁じている「推測で前処理を補う」に
    なる。"""
    reference_mel = torchaudio.transforms.MelSpectrogram(
        sample_rate=extractor.sampling_rate,
        n_fft=extractor.n_fft,
        win_length=extractor.win_size,
        hop_length=extractor.hop_size,
        f_min=extractor.f_min,
        f_max=extractor.f_max,
        n_mels=extractor.feature_size,
        center=extractor.center,
    )
    n_fft = int(extractor.n_fft)
    window = reference_mel.spectrogram.window.detach()
    if window.numel() != n_fft:
        # win_length < n_fft のときtorch.stftは窓を中央寄せでzero詰めする。今のCEDは
        # win_size == n_fft なので発生しないが、黙って別の詰め方をすると特徴量が
        # ずれるので、起きたらexportを止める。
        raise SystemExit(
            f"win_length {window.numel()} と n_fft {n_fft} が違います。"
            "窓の詰め方を書き足してからexportしてください。"
        )
    if not extractor.center:
        raise SystemExit("center=False のexportは未対応です（padの入れ方が変わります）。")

    n_freqs = n_fft // 2 + 1
    k = torch.arange(n_freqs, dtype=torch.float64).unsqueeze(1)
    n = torch.arange(n_fft, dtype=torch.float64).unsqueeze(0)
    angle = 2.0 * torch.pi * k * n / n_fft
    win64 = window.to(torch.float64).unsqueeze(0)
    # X[k] = Σ x[n]·w[n]·exp(-j2πkn/N) を実部・虚部の2本のconvへ分ける。
    basis = torch.cat([torch.cos(angle) * win64, -torch.sin(angle) * win64], dim=0)
    basis = basis.to(torch.float32).unsqueeze(1)

    class WaveformTagger(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.register_buffer("basis", basis)
            self.register_buffer("fb", reference_mel.mel_scale.fb.detach().clone())
            self.model = model

        def forward(self, waveform):
            padded = torch.nn.functional.pad(
                waveform.unsqueeze(1), (n_fft // 2, n_fft // 2), mode="reflect")
            frames = torch.nn.functional.conv1d(padded, self.basis,
                                                stride=extractor.hop_size)
            real, imag = frames[:, :n_freqs], frames[:, n_freqs:]
            # power=2.0 のspectrogram(振幅の2乗)。MelSpectrogramの既定と同じ。
            power = real * real + imag * imag
            spec = torch.matmul(power.transpose(-1, -2), self.fb).transpose(-1, -2)
            spec = _DB_MULTIPLIER * torch.log10(torch.clamp(spec, min=_AMIN))
            # floorは窓ごと(batchで共有しない)。module docstringの「dB floor」節を参照。
            floor = spec.amax(dim=(-2, -1), keepdim=True) - TOP_DB
            spec = torch.maximum(spec, floor)
            return self.model(spec).logits

    wrapper = WaveformTagger()
    wrapper.eval()
    return wrapper


def reference_probs(torch, model, extractor, waveform):
    """model cardどおりの経路(feature extractor -> model)で確率を出す。parityの基準。

    1本ずつ渡すのはtorchaudio側のdB floorがbatchで結合しているためで、こちらが
    「学習・評価時の意味」の側である。"""
    out = []
    for row in waveform:
        features = extractor(row.numpy(), sampling_rate=extractor.sampling_rate,
                             return_tensors="pt")
        with torch.no_grad():
            out.append(model(**features).logits)
    return torch.cat(out, dim=0)


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help="Hugging Faceのmodel id、またはlocal directory")
    parser.add_argument("--out", default="models/laugh", help="出力先directory")
    parser.add_argument("--window-seconds", type=float, default=2.0,
                        help="1回の推論が見る長さ。TICTOK_LAUGH_AUDIO_WINDOW_SECONDS と"
                             "同じ値にすること(engineが突き合わせて検査する)")
    parser.add_argument("--parity-batch", type=int, default=4,
                        help="parity checkに使う窓数")
    args = parser.parse_args(argv[1:])

    torch, torchaudio, _ = _import_deps()
    from transformers import AutoFeatureExtractor, AutoModelForAudioClassification

    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = PROJECT_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"model を読み込みます: {args.model}")
    extractor = AutoFeatureExtractor.from_pretrained(args.model, trust_remote_code=True)
    model = AutoModelForAudioClassification.from_pretrained(args.model,
                                                            trust_remote_code=True)
    model.eval()

    sample_rate = int(extractor.sampling_rate)
    samples = int(round(args.window_seconds * sample_rate))
    frames = samples // extractor.hop_size + (1 if extractor.center else 0)
    max_frames = int(model.config.target_length)
    if frames > max_frames:
        raise SystemExit(
            f"窓長 {args.window_seconds} 秒 は mel frame {frames} で、modelの"
            f" target_length {max_frames} ({max_frames * extractor.hop_size / sample_rate:.2f} 秒)"
            " を超えます。超える入力はmodel内部で分割され、その分岐がtraceで焼き付きます。"
        )
    print(f"窓長 {args.window_seconds} 秒 = {samples} samples / mel {frames} frame"
          f"（上限 {max_frames} frame）")

    wrapper = build_wrapper(torch, torchaudio, model, extractor)

    # parityと形状確認に使う入力。無音だとdB floorが効かず前処理の差が出ないので雑音を使う。
    generator = torch.Generator().manual_seed(0)
    probe = torch.randn(args.parity_batch, samples, generator=generator) * 0.1

    onnx_path = out_dir / f"ced_tiny_waveform_{args.window_seconds:g}s.onnx"
    print(f"ONNXへexportします: {onnx_path}")
    torch.onnx.export(
        wrapper, (probe[:1],), str(onnx_path),
        input_names=["waveform"], output_names=["probs"],
        # batchだけ可変。samplesを可変にしない理由はmodule docstringの「固定窓」節。
        dynamic_axes={"waveform": {0: "batch"}, "probs": {0: "batch"}},
        opset_version=OPSET,
    )

    print("exportしたgraphを検査します（engineと同じ CPUExecutionProvider）")
    import onnxruntime as ort
    session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    inputs = session.get_inputs()
    if len(inputs) != 1 or len(inputs[0].shape) != 2:
        raise SystemExit(f"入力が (batch, samples) になっていません: "
                         f"{[(i.name, i.shape) for i in inputs]}")
    onnx_probs = session.run(None, {inputs[0].name: probe.numpy()})[0]

    reference = reference_probs(torch, model, extractor, probe).numpy()
    diff = float(abs(onnx_probs - reference).max())
    print(f"参照経路との最大差: {diff:.3e}（許容 {PARITY_TOLERANCE:.0e}）")
    if diff > PARITY_TOLERANCE:
        raise SystemExit(
            "ONNXの出力がmodel cardの経路と一致しません。前処理の写し違いです。"
            "この状態のfileを設定へ入れてはいけません（確率が壊れていても出力を見て"
            "気付けません）。"
        )

    # batchを変えても同じ窓が同じ確率になること。dB floorをbatchで共有していれば崩れる。
    single = session.run(None, {inputs[0].name: probe.numpy()[:1]})[0]
    batch_diff = float(abs(single[0] - onnx_probs[0]).max())
    print(f"batch非依存性の差: {batch_diff:.3e}")
    if batch_diff > PARITY_TOLERANCE:
        raise SystemExit("batch sizeで確率が変わります。dB floorがbatchで結合しています。")

    labels = [model.config.id2label[i] for i in range(len(model.config.id2label))]
    if onnx_probs.shape[-1] != len(labels):
        raise SystemExit(f"出力class数 {onnx_probs.shape[-1]} と id2label {len(labels)} が"
                         "一致しません。")
    labels_path = out_dir / "labels.json"
    labels_path.write_text(json.dumps(labels, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    print(f"label file: {labels_path}（{len(labels)} class）")

    missing = [name for name in LAUGH_CLASSES if name not in labels]
    if missing:
        raise SystemExit(
            f"笑いとみなすclassが対応表にありません: {missing}\n"
            "このmodelのlabelは別の綴りです。labels.json を見て "
            "TICTOK_LAUGH_AUDIO_CLASSES を合わせてください。"
        )
    print("笑い系のclass: "
          + ", ".join(f"{labels.index(name)}:{name}" for name in LAUGH_CLASSES))

    notes = out_dir / "EXPORT.md"
    notes.write_text(
        "# 笑い声検出ONNXのexport記録\n\n"
        f"- 生成: `scripts/export_laugh_onnx.py`\n"
        f"- 元model: `{args.model}`\n"
        f"- 窓長: {args.window_seconds:g} 秒 = {samples} samples（固定）\n"
        f"- mel: {extractor.sampling_rate}Hz / {extractor.feature_size} mel /"
        f" n_fft {extractor.n_fft} / win {extractor.win_size} / hop {extractor.hop_size}"
        f" / f_min {extractor.f_min} / f_max {extractor.f_max} / center {extractor.center}"
        f" / top_db {TOP_DB:g}\n"
        f"- 出力: 確率（modelが sigmoid 済み）→ `TICTOK_LAUGH_AUDIO_ACTIVATION=none`\n"
        f"- opset: {OPSET}\n"
        f"- 参照経路との最大差: {diff:.3e}\n"
        f"- batch非依存性の差: {batch_diff:.3e}\n\n"
        "## .env\n\n"
        "```\n"
        "TICTOK_LAUGH_AUDIO_ENABLED=1\n"
        f"TICTOK_LAUGH_AUDIO_MODEL_PATH={onnx_path.relative_to(PROJECT_ROOT).as_posix()}\n"
        f"TICTOK_LAUGH_AUDIO_LABELS_PATH={labels_path.relative_to(PROJECT_ROOT).as_posix()}\n"
        "TICTOK_LAUGH_AUDIO_CLASSES=" + "|".join(LAUGH_CLASSES) + "\n"
        "TICTOK_LAUGH_AUDIO_ACTIVATION=none\n"
        f"TICTOK_LAUGH_AUDIO_WINDOW_SECONDS={args.window_seconds:g}\n"
        "```\n",
        encoding="utf-8")
    print(f"設定の写し: {notes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
