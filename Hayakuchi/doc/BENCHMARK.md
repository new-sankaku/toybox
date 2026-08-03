# 判定Engine Benchmark

## 目的

早口言葉Mini gameの判定Engineを選定するための評価基盤。
「言えているか」の判定は一般的な音声認識ではなく、**正解Textが既知の発音検証**として扱う。
そのため、認識率（WER）ではなくGame体験に直結する指標で比較する。

## 測定する指標

| 指標 | 定義 | 重要な理由 |
|---|---|---|
| AUC | Accuracy Scoreを用いたOK/NGの分離性能 | 閾値に依存しない素の分離力 |
| EER | FARとFRRが一致する点の誤り率 | Engine間比較の単一指標 |
| FRR@FAR | 目標FAR以下に抑えたときの誤Reject率 | **配信体験への影響が最大**。正しく言えたのにFAIL判定されると場が壊れる |
| LM補正率 | NG音声に対しEngineが正解文と完全一致を返した割合 | Language Model内蔵Modelの失格判定に使う |
| 誤り位置精度 | 崩れたMora位置を許容範囲内で当てた割合 | Overlayの誤り位置表示とReplay演出に必要 |
| 遅延p50/p95 | 1発話あたりの推論所要時間 | Game応答性の実測値 |
| RTF | 推論時間 / 音声長 | 1.0を超えるEngineはReal timeで追従できない |

Accuracyは `1 - 編集距離 / 正解Mora数` で算出する。二値ではなく連続値で保持し、
閾値はBenchmark結果から後決めする。

## Dataset

### 規模の目安

| 軸 | 目安 | 備考 |
|---|---|---|
| 話者 | 8名以上 | 性別・年齢・地域Accentを分散させる |
| Phrase | 16句（`backend/data/phrases.json`） | 難易度1〜5、音韻的な崩れ方が異なるものを収録 |
| OK Sample | 話者×Phrase×2 take | 正しく言い切れたもの |
| NG Sample | 話者×Phrase×2 take | 噛んだもの |

OKとNGは概ね同数にする。極端に偏るとFAR/FRRの推定が不安定になる。

### NG Sampleの集め方

**自然発生した噛みを最優先で採用する。** 意図的な誤読は音響的に不自然で、
実運用の噛みとは分布が異なるため、これだけで構成してはならない。

1. 制限時間を設けて高速読みを連続で繰り返させ、自然に発生した失敗をそのまま採用する
2. 判定が難しい境界例（滑舌が甘い、Moraが繋がった、僅かに濁った）を意識的に残す
3. 補助的に、明確なMora入れ替え・脱落を意図的に発話したものを加える

境界例を除外すると実力より良い数値が出る。**難しいSampleを残すことがBenchmarkの価値**になる。

### 収録条件

音源は静音環境・単一Mic・16kHz以上のMono WAVで1本だけ収録する。
Noise、BGM回り込み、Voice Changer相当のPitch shift、過大入力は
`backend/config/benchmark.yaml` の `conditions` でSimulationする。
乱数はSample IDとCondition IDから決定的に導出するため、OSが変わっても結果は一致する。

### File名規約

```
{speaker_id}__{phrase_id}__{label}{連番}.wav
例: s01__nama_mugi__ok01.wav / s01__tokkyo_kyoka__ng03.wav
```

### 注釈

NG Sampleには `error_mora_index`（最初に崩れたMoraのIndex、0始まり）を人手で付与する。
未注釈のNG Sampleは誤り位置精度の集計対象から外れる。

## 実行手順

```bash
cd Hayakuchi/backend
python -m venv .venv
.venv/bin/pip install -r requirements.txt          # Windowsは .venv\Scripts\pip

python scripts/make_manifest.py --audio-dir data/wav --out data/manifest.jsonl
# data/manifest.jsonl の error_mora_index を注釈する
python scripts/run_benchmark.py
```

Modelを動かすEngineを使う場合は `requirements-model.txt` を追加でinstallし、
`config/benchmark.yaml` の該当Engineの `enabled` と `model_id` を設定する。

### Harnessの動作確認

実収録が揃う前に経路を確認する場合のみ使用する。

```bash
python scripts/make_selftest_dataset.py
python scripts/run_benchmark.py --config config/benchmark.selftest.yaml --stem selftest
```

合成信号を用いるため、ここで得られる数値はEngineの精度ではない。
Manifest読み込み・Condition適用・指標集計・Report出力が通ることのみを確認する。

## Engine

| adapter | 位置づけ |
|---|---|
| `hf_ctc` | CTC音響ModelをGreedy復号。Language Modelを介さないため補正が起きない。本命候補 |
| `seq2seq_asr` | Decoder側にLanguage Modelを内包。LM補正率を実測し失格を確認するControl群 |
| `replay` | 書き起こしを再生。人手書き起こしを流し込み、人間の判定上限をBaselineとして測る |

`replay` に人手書き起こしを与えたときの数値が、この判定方式の**上限**になる。
実Modelの数値は必ずこれと並べて読む。

## 採用判断のGate（暫定値）

実測前の仮置きであり、Benchmark結果を見て確定させる。

| 指標 | 暫定基準 |
|---|---|
| LM補正率 | 0.05以下（超過は無条件で不採用） |
| FRR@FAR5% | 0.10以下 |
| 誤り位置精度（±1 Mora） | 0.80以上 |
| RTF p95 | 0.35以下 |
| Voice Changer条件でのEER劣化 | 清音源比 +0.05以内 |

RTFに余裕を持たせるのは、実機の応答時間が推論だけで決まらないためである。
Mic buffer 10〜30ms、VADによる発話終端検出 200〜300ms、Overlay描画 50ms未満が
推論時間に加算される。判定表示までを1秒以内に収めるには推論を数百ms以下に抑える必要がある。

## 既知の限界

- 収録条件はSimulationであり、実際のVoice Changer製品の特性とは一致しない。
  最終判断の前に実機を通した音声で再測定する
- 話者数が少ない段階の数値は分散が大きい。話者単位のCross validationを行うまで確定値として扱わない
- 現状の判定はMora列の編集距離のみを見ている。音響的な確信度（GOP相当）を
  Scoreに組み込む改良は、Baselineが確定してから検討する
