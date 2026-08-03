# 判定Engine候補の調査

公開Modelと公開Corpusを調査し、実機で測定した結果をまとめる。
数値の再現手順は `doc/BENCHMARK.md` を参照。

## 前提となる判定方式

正解Textが既知のため、これは音声認識ではなく**発音検証**である。
判定Engineに求める性質は認識率ではなく、以下の2点になる。

1. 実際に鳴っている音をそのまま返すこと（言語的な尤もらしさで補正しないこと）
2. 発話単位が細かいこと（Mora単位よりPhoneme単位の方が崩れを捉えられる）

## Model候補

| Model | 出力単位 | Vocab | 規模 | License | 評価 |
|---|---|---|---|---|---|
| `prj-beatrice/japanese-hubert-base-phoneme-ctc-v4` | Phoneme | 48 | 94M | Apache-2.0 | **本命**。OpenJTalk系Phoneme 48種のみ。漢字も単語も持たないため補正が原理的に起きない |
| `vumichien/wav2vec2-large-xlsr-japanese-hiragana` | Kana | 86 | 315M | Apache-2.0 | 対抗。Hiragana のみのVocabで補正されにくい。Mora単位 |
| `jonatasgrosman/wav2vec2-large-xlsr-53-japanese` | 漢字かな交じり | 2341 | 315M | Apache-2.0 | **不適**。VocabにKanjiを含み、CTC Head自体が表記を学習している。Kana変換も曖昧 |
| `kotoba-tech/kotoba-whisper-v2.0` | Text | BPE | 756M | Apache-2.0 | Control群。DecoderがLanguage Modelそのもの |
| `reazon-research/reazonspeech-nemo-v2` | Text | BPE | - | Apache-2.0 | 未評価。NeMo形式のためAdapter追加が必要 |
| `rinna/japanese-wav2vec2-base` | - | - | 95M | Apache-2.0 | 事前学習のみでCTC Headなし。自前Fine tuning時のBase候補 |

`prj-beatrice` のPhoneme CTCは、Voice Changer「Beatrice」の開発過程で
ReazonSpeech v2 と pyopenjtalk 系Labelを用いて学習されたもの。
Voice Changer用途を前提としたModelであるため、VTuber層への適合という点でも都合が良い。

Vocabは以下の48種で、この体系に合わせて正解KanaをPhonemeへ変換する
（`backend/hayakuchi/phoneme.py`）。

```
a i u e o I U k g s z t d n h b p m y r w f j v N cl sh ch ts
ky gy hy by py my ny ry fy ty dy kw gw pau sil
```

`I` `U` は無声化母音。話者と発話速度で揺れるため `i` `u` へ正規化して比較する。

## 測定結果

### 実行環境

CPU 4 thread（GPU不使用）、音源はCommon Voice ja test（16kHz Mono変換）。

### 応答性

24回測定（8音源 × 3回、Warm up除外）。

| Model | 音声長 | 遅延p50 | 遅延p95 | RTF p50 | RTF p95 |
|---|---|---|---|---|---|
| `prj-beatrice` Phoneme CTC | 3.1〜7.0秒 | 346ms | 472ms | **0.065** | **0.081** |
| `prj-beatrice` Phoneme CTC | 4.5秒未満のみ | **249ms** | **268ms** | - | - |
| `kotoba-whisper-v2.0` | 4.2〜7.0秒 | 約26,000ms | 約63,000ms | 約4〜9 | - |

早口言葉は概ね3秒前後のため、Phoneme CTCの**推論は約250ms**に収まる。
VADの発話終端検出200〜300ms、Mic buffer 10〜30ms、Overlay描画50ms未満を加えても
判定表示まで1秒以内に収まり、**GPUなしで成立する**。

Seq2Seq ModelはCPUでRTF 4〜9であり、補正の問題を措いてもReal timeで追従できない。
採用Gateの `RTF p95 0.35以下` に対し、Phoneme CTCは0.081で通過、Seq2Seqは大幅に超過する。

### 出力の忠実性

Phoneme CTCは表記ではなく実際の発音を返す。

| 正解文 | 出力 |
|---|---|
| きのうは八時間寝ました | `k i n o o w a h a ch i j i k a N n e m a sh I t a` |
| 田中さんの奥さんは大学の先生です | `t a n a k a s a N n o o k U s a N w a d a i g a k u n o s e N s e e d e s U` |

「きのう」を `k i n o o`、「先生」を `s e N s e e` と返しており、
表記ではなく発音を出力していることが確認できる。判定に必要な性質である。

さらに、Common Voice の1件では話者が言い直した箇所を
`s a N w a w a w a t a sh i` と重複したまま出力した。
**言い淀みを平滑化せずそのまま返す**ことの実例である。

### Language Model補正の検出

正解Textを使わず、音声側を改変して出力が追従するかを見る
（`scripts/run_lm_bias_check.py`）。改変前後で出力が変わらないEngineは、
鳴っている音ではなく言語的な尤もらしさを返している。

同一音源・同一改変での直接比較（Common Voice 5件 × 改変2種）:

| Model | 改変が出力に反映された数 | 反映率 |
|---|---|---|
| `prj-beatrice` Phoneme CTC | **10 / 10** | **1.00** |
| `kotoba-whisper-v2.0` | 5 / 10 | 0.50 |

Phoneme CTCは全ての改変に追従した。実例（40%地点を180ms欠落）:

```
改変前: k i m u r a s a N w a w a w a t a sh i n i sh a N sh i N o ...
改変後: k i m u r a s a N w a w a w a t a sh i       sh a N sh i N o ...
```

欠落した `n i` がそのまま出力から消えている。

一方Seq2Seqは、音声を改変しても出力が変化しない事例が半数を占めた。
最も明確な例は 4.2秒の音源で、**改変前・欠落・重複の3条件すべてで同一の文**を返した。

```
原文    : 木村さんに電話を貸してもらいました
改変前  : 木村さんに電話を貸してもらいました
欠落180ms: 木村さんに電話を貸してもらいました   ← 音は変わっている
重複180ms: 木村さんに電話を貸してもらいました   ← 音は変わっている
```

同じ音源に対しPhoneme CTCは `d e N w a o k a sh I t e` → `d e N k a sh I t e`、
`m o r a i m a sh I t a` → `m o r a i r a i m a sh I t a` と、
欠落と重複の両方を正しく出力している。**音は確かに変わっており、
Seq2Seqがそれを言語的に埋め戻している**ことの直接的な証拠である。

さらにSeq2Seqは、改変していない音源に対しても
「写真」を「上司」、「パック」を「バック」と、
文として自然だが実際の発音とは異なる出力を返した。
早口言葉の判定では、この性質がそのまま誤判定になる。

### 現時点の結論

`prj-beatrice/japanese-hubert-base-phoneme-ctc-v4` をBase lineとして確定させる。
Language Model補正と応答性という、収録データ無しで判定できる2つのGateを
Seq2Seqが明確に落とし、Phoneme CTCが明確に通過した。

未確定なのは、収録データが無いと測れない指標である。

- 実際の噛みに対するFRR@FAR（判定の納得感）
- Voice Changer経由での劣化
- 誤り位置精度

## Corpus候補

| Corpus | 内容 | 読み | License | 用途 |
|---|---|---|---|---|
| **ITAコーパス** | 424文（音素Balance文） | **Katakana読み付き** | Public Domain（文章） | 較正用の正解文。音声は配布者ごとにLicenseが異なる |
| Common Voice ja | 読み上げ | 漢字かな交じり | CC0 | Engine挙動確認、LM補正検出 |
| JSUT basic5000 | 読み上げ | 漢字かな交じり | 非商用は無償、商用は要問い合わせ | **商用前提では要注意** |
| ReazonSpeech | 大規模 | 漢字かな交じり | CDLA-Sharing-1.0 | 学習用途。評価には過大 |

**ITAコーパスが重要**なのは、424文すべてにKatakana読みが付属し、
Public Domainで再配布に制約がない点である。漢字かな交じり文しか持たない
他Corpusは、正解Mora列を得るために形態素解析器が必要になる。

ITAコーパスの読み424文すべてが `hayakuchi/phoneme.py` の変換表で
Phoneme列へ変換できることを確認済み（Testで固定）。音素Balance文であるため、
この網羅性は日本語のMora全体をほぼ覆っていることを意味する。

音声はつくよみちゃん・あみたろ等がITAコーパスの読み上げを無償配布しているが、
**Licenseは配布者ごとに異なる**ため、利用前に各配布元の規約確認が必要。

## 早口言葉音声について

早口言葉に特化した公開音声Datasetは見つからなかった。
噛みを含む音声は自前収録が必要になるが、以下の段階に分けられる。

1. **段階0（収録不要・実施済み）** — 公開Corpusへ音声改変を加え、
   Engineが音の変化に追従するかを検証する。Language Model補正の検出はこれで足りる
2. **段階1（収録必要）** — 実際の噛み、特に判定が割れる境界例。
   ここは公開Datasetでは代替できない

段階0で候補を絞ってから段階1の収録に入ることで、収録のやり直しを避けられる。
