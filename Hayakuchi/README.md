# Hayakuchi

配信者向けの早口言葉Mini game。発話が正しく言えているかを判定し、
崩れたMora位置をOverlayへ表示する。

現状はGame本体の前段として、**判定Engineの選定Benchmark**のみを実装している。
配信PlatformのAPI連携は対象外。音声は配信者PCのMic入力から直接取得する前提で、
Platformの配信遅延は判定経路に入らない。

## 構成

```
Hayakuchi/
  doc/BENCHMARK.md            評価指標・収録Protocol・採用Gate
  doc/MODEL_CANDIDATES.md     Model候補の調査と実測結果
  backend/
    config/benchmark.yaml     Model ID・閾値・収録条件のSimulation定義
    config/edits.yaml         Language Model補正検出用の音声改変定義
    data/phrases.json         早口言葉Database
    hayakuchi/                Mora分解・Phoneme変換・Alignment・Scoring・指標
    hayakuchi/engines/        判定Engine Adapter
    scripts/                  Manifest生成・Benchmark実行・LM補正検出
    tests/                    Unit test / End-to-end test
```

## Setup

```bash
cd backend
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
```

Windowsは `.venv\Scripts\pip` / `.venv\Scripts\python` を使用する。

## Benchmarkの実行

手順とDataset要件は `doc/BENCHMARK.md` を参照。

```bash
python scripts/make_manifest.py --audio-dir data/wav --out data/manifest.jsonl
python scripts/run_benchmark.py
```

結果は `backend/results/` にJSONとMarkdownで出力される。

## 設計上の要点

判定に一般的な音声認識Modelを使うと、Language Modelが噛んだ発話を正解文へ補正するため、
**最も判定したい失敗が検出できない**。本Benchmarkは `lm_correction_rate` として
この現象を明示的に測り、該当Engineを失格させる。

## 実測済みの結果

CPU 4 thread、公開Corpus（Common Voice ja）での測定。詳細は `doc/MODEL_CANDIDATES.md`。

| Model | 音声改変への追従 | 遅延p50 | RTF p95 |
|---|---|---|---|
| `prj-beatrice/japanese-hubert-base-phoneme-ctc-v4` | 10/10 | 249ms（3秒前後の発話） | 0.081 |
| `kotoba-tech/kotoba-whisper-v2.0` | 5/10 | 約26,000ms | 約4〜9 |

Phoneme CTCをBase lineとして確定。**GPU不要**で応答性の要件を満たす。
