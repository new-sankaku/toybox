# 笑い声検出のmodel入手と配置

切り出し候補の指標「笑い声(音声)」(`clip_candidate_laugh_audio`)は、録画の音声をAudioSetの
audio tagging modelへ通して笑い系classの確率列を作る。実装は `tictok/media/laugh_audio.py`、
候補APIへの配線は `tictok/server.py` の `_MATERIAL_METRICS`。

**weightsはこのrepositoryに含めない。** 利用者が入手して置き、pathを設定で指す(AI高画質化の
超解像weightsと同じ方式)。自動downloadは持たない。

## engineが受け付けるONNXの契約

`laugh_audio._describe` が起動時に検査する。ここを満たさないONNXは例外で弾かれる
(推測で前処理を補うと、学習時と少しでも違えば確率が静かに壊れるため)。

| 項目 | 要求 |
| --- | --- |
| 入力 | **1つだけ**。shapeは2次元 `(batch, samples)` |
| 入力の中身 | 16kHz mono、float32、full scaleが±1.0の**生波形** |
| 出力 | `(batch, classes)`(`(batch, 1, classes)` も可。中央の軸だけ落とす) |
| 活性化 | `TICTOK_LAUGH_AUDIO_ACTIVATION` で明示。logits出力なら `sigmoid`、確率出力なら `none` |
| 実行 | CPU固定(`CPUExecutionProvider`)。GPUは転写と超解像が取り合っている |

窓長を固定してexportした場合、`fixed_samples` と
`TICTOK_LAUGH_AUDIO_WINDOW_SECONDS × 16000` が一致しないと例外になる(既定は2.0秒 = 32000)。

## 重要: 上流の公開ONNXはそのままでは使えない(確認済み)

CED系の公開ONNXはいずれも**mel入力**で、上記の契約(波形入力)を満たさない。

- `RicherMans/CED` の `export_onnx.py` は入力 `feats` = `(1, n_mels, max_frames)`、出力 `prob`。
  波形は受けない。([export_onnx.py](https://raw.githubusercontent.com/RicherMans/CED/main/export_onnx.py))
- `mispeech/ced-tiny` の `model.onnx` も同様で、`CedForAudioClassification.forward(input_values, ...)`
  はmelを受け取り、mel計算はmodelの外(`CedFeatureExtractor`)で行われる。
  ([modeling_ced.py](https://huggingface.co/mispeech/ced-tiny/raw/main/modeling_ced.py))

したがって手順は「downloadして指す」ではなく、**mel front-endをgraphへ含めて再exportする**の
1手間が入る。melの計算をtictok側に持たせない判断は `laugh_audio._describe` のdocstringのとおり
(mel filter本数・hop・窓関数をこちらが推測することになり、ずれても出力を見て気付けない)。

## 入手元

### 1. weights (どれか1つ)

| 入手元 | 中身 | license | 確認状況 |
| --- | --- | --- | --- |
| [mispeech/ced-tiny](https://huggingface.co/mispeech/ced-tiny) | PyTorch(`model.safetensors`)+ 前処理・modelのpython code、`model.onnx`(mel入力) | **Apache-2.0**(model card記載) | 確認済み。再exportの土台として最も扱いやすい |
| [RicherMans/CED](https://github.com/RicherMans/CED) | 学習・export一式(`audiotransformer_tiny_mAP_4814.pt` をZenodoから取得) | **GPL-3.0**(repository) | 確認済み。codeを取り込む場合はGPLの伝播に注意 |
| [k2-fsa/sherpa-onnx-ced-tiny-audio-tagging-2024-04-19](https://huggingface.co/k2-fsa/sherpa-onnx-ced-tiny-audio-tagging-2024-04-19) | `model.onnx` 22.3MB / `model.int8.onnx` 6.13MB / `class_labels_indices.csv` 14.7kB | **未確認**(pageにlicense表記なし) | fileの存在は確認済み。**入力形式は未検証**(sherpa-onnx側が特徴量をC++で作る構成なのでmel入力と推定) |

CED-tinyは約6M〜10M parameter・16kHz・64次元mel・527 class(AudioSet)。CPUで実時間の数十倍で
流せる規模なので、この用途(後から一括で回す解析)に足りる。

### 2. label file (必須)

出力indexとclass名の対応表。**weightsと対で持つこと**(出力順はweightsごとに違う)。

- AudioSet公式: `http://storage.googleapis.com/us_audioset/youtube_corpus/v1/csv/class_labels_indices.csv`
- license: dataset CSVは **CC BY 4.0**、ontologyは CC BY-SA 4.0
  ([AudioSet download](https://research.google.com/audioset/download.html))
- 確認済み(2026-07-26に実際に取得): header は `index,mid,display_name`、527 class。
  笑い系は index 16〜21 で、`display_name` は既定設定の綴りと完全一致する:

  | index | display_name |
  | --- | --- |
  | 16 | `Laughter` |
  | 17 | `Baby laughter` |
  | 18 | `Giggle` |
  | 19 | `Snicker` |
  | 20 | `Belly laugh` |
  | 21 | `Chuckle, chortle` |

`laugh_audio._load_labels` はこのCSV(index / display_name列)と、JSONのlist(index順)・
dict(index→名前)を読む。indexが連番でないfileは例外にする(対応表がずれると別の音の確率を
「笑い」として読むことになり、出力を見ても気付けない)。

### 3. onnxruntime

```
pip install onnxruntime
```

GPU版は入れない。ここがGPUを取ると焼き込み・転写が待たされる。

## 再export(mel front-endを含める)

**未確認: 以下は未実行の手順である。** 実施する場合は、export後に必ず
`onnxruntime` でloadして入力shapeが `(batch, 32000)` になっていることと、既知の笑い音源で
`Laughter` の確率が上がることを確認してから設定へ入れること。

要点は3つ。

1. mel front-end(`torchaudio.transforms.MelSpectrogram` 相当)とmodelを1つの `nn.Module` で
   包み、`forward(waveform) -> logits` にする。
2. melのparameterは `mispeech/ced-tiny` の `config.json` と揃える(確認済みの値):
   **16kHz / 64 mel / n_fft 512 / hop 160 / 0〜8000Hz**。学習時と1つでも違うと確率が壊れる。
3. `torch.onnx.export` は `opset_version=17` 以上(STFTのexportに必要)。
   `dynamic_axes` でbatchを可変にすると、`TICTOK_LAUGH_AUDIO_BATCH` が効くようになる。
   固定でexportした場合はexport時のbatchと窓長が優先される。

出力が確率(sigmoid済み)なら `TICTOK_LAUGH_AUDIO_ACTIVATION=none`、logitsなら `sigmoid`。
**二重掛けは値が [0.5, 0.73] へ潰れるだけで、結果を見ても気付けない。** exportした本人が
どちらなのかを知っているので、推測せずここへ書き残すこと。

## 配置と設定

置き場所は任意(pathで指す)。`models/` はgitignore済みなので、超解像weightsと同じくここが素直。
相対pathはproject root基準で解決される(`laugh_audio._resolve`)。

```
models/laugh/ced_tiny_waveform.onnx
models/laugh/class_labels_indices.csv
```

`.env`:

```
TICTOK_LAUGH_AUDIO_ENABLED=1
TICTOK_LAUGH_AUDIO_MODEL_PATH=models/laugh/ced_tiny_waveform.onnx
TICTOK_LAUGH_AUDIO_LABELS_PATH=models/laugh/class_labels_indices.csv
TICTOK_LAUGH_AUDIO_CLASSES=Laughter|Giggle|Snicker|Belly laugh|Chuckle, chortle
TICTOK_LAUGH_AUDIO_ACTIVATION=sigmoid
```

| env | 既定 | 意味 |
| --- | --- | --- |
| `TICTOK_LAUGH_AUDIO_ENABLED` | 0 | engineの有効化。0のままなら候補側をONにしても失敗する |
| `TICTOK_LAUGH_AUDIO_MODEL_PATH` | (空) | ONNX file |
| `TICTOK_LAUGH_AUDIO_LABELS_PATH` | (空) | label file |
| `TICTOK_LAUGH_AUDIO_CLASSES` | `Laughter\|Giggle\|Snicker\|Belly laugh\|Chuckle, chortle` | 笑いとみなすclass。区切りは `\|`(class名自体がカンマを含むため) |
| `TICTOK_LAUGH_AUDIO_WINDOW_SECONDS` | 2.0 | 1回の推論が見る長さ |
| `TICTOK_LAUGH_AUDIO_HOP_SECONDS` | 1.0 | 確率列の刻み(=時間分解能) |
| `TICTOK_LAUGH_AUDIO_THRESHOLD` | 0.35 | 笑い有りとみなす確率の下限。sidecarは閾値**前**の生確率なので変更に再解析は不要 |
| `TICTOK_LAUGH_AUDIO_BATCH` | 32 | 1回の推論へ渡す窓数 |
| `TICTOK_LAUGH_AUDIO_THREADS` | 0 | onnxruntimeのintra-op thread数(0=既定)。録画中に回すなら絞る |
| `TICTOK_LAUGH_AUDIO_ACTIVATION` | sigmoid | `sigmoid` か `none` |

`Baby laughter`(index 17)は既定に入れていない。乳児の声は配信の笑いとは別の場面である。

候補側の設定(設定画面「切り出し」categoryから変更可):

| 設定 | 既定 | 意味 |
| --- | --- | --- |
| `clip_candidate_laugh_audio` | 0 | 笑い声を候補の判定に使う |
| `clip_candidate_laugh_audio_weight` | 1.0 | z-scoreに掛ける倍率 |
| `clip_candidate_laugh_audio_min_seconds` | 3.0 | 窓内の笑い秒数の下限(これ未満の窓は候補にしない) |

下限は必須である。笑い声の系列もほとんどの窓が0秒で標準偏差が極小になるため、下限が無いと
「ほとんど笑わない配信の1刻み」が大きなz-scoreを叩いて候補を占領する(`core/spike.py`)。

## 動作確認と失敗の見え方

`clip_candidate_laugh_audio=1` にして録画の切り出し候補を開く。

- 成功: 候補表に「笑い声」列(秒数)が出る。根拠が笑い声だった候補はbadgeが `笑い声N秒`。
- **model未配置・engine無効・解析失敗: 候補APIは503で理由を返す。** 笑い0秒の候補一覧を
  黙って返すことはしない(「笑いが検出されなかった」と「そもそも検出していない」が区別
  できなくなるため)。
- 確率列が録画の一部しか覆えない場合は、その録画では笑い声指標を**外す**(0で埋めない)。
  画面では「—」になり、logへ `clip.material_metric_skipped` が残る。

初回は録画の音声を最後まで読む。結果は録画ごとのsidecar
(`<録画>.laugh.json`)へ残り、以後は再利用する。cacheの鍵は素材の指紋・窓長・hop・class・
activation・**modelの指紋**で、閾値は鍵に含まれない(閾値を変えても再解析は要らない)。

## 未確認の事項

- sherpa-onnx repositoryのlicense表記(pageに無い)と、その `model.onnx` の実際の入力名・shape。
- 上記の再export手順(未実行)。
- CED-tinyの笑いclassが**配信素材**でどの程度当たるか。既定の閾値0.35は根拠がまだ無い
  出発点で、そのために生確率を保存している(後から閾値を掃引して検証できる)。
  コメント由来の笑い(`clip_candidate_laugh_comment`)は実DB 84 sessionで測って既定を決めて
  あるが、こちらは未測定である。
