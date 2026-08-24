# 工程

作成 2026-08-24 / 対応: `doc/METHOD.md`（何を・なぜ）、`doc/SOURCES.md`（情報源）

`tools/run_pipeline.py` で0〜6を順に流せます。**途中で失敗したらそこで止まります。** 後続を代替値で進めません。

---

## 0. 全体

| 工程 | program | 入力 | 出力 | 機械 / 人 |
|---|---|---|---|---|
| **0 検索語の発見** | `discover_queries.py` | `config/discovery.yaml`（**検索語ではなく定義**） | `config/queries_auto-<種別>-YYYYMMDD.txt` | 機械 |
| 0b 日本語の語の発見 | `discover_jp_terms.py` | `config/categories.yaml` | `config/jp_terms_auto-YYYYMMDD.yaml`（**提案。自動反映しません**） | 機械＋人の採否 |
| 1 収集 | `collect_cases.py` | `config/queries_*.txt` | `log/cases-YYYYMMDD.jsonl` | 機械 |
| 2 価格の証拠 | `fetch_pricing.py` | 工程1の出力 | `log/pricing-YYYYMMDD.jsonl` | 機械 |
| 3 条件照合 | `screen_cases.py` | `config/screen.yaml` | `log/screen-YYYYMMDD.json` | 機械 |
| 4 日本側の実測 | `jp_market_check.py` | `config/categories.yaml` | `log/jp-market-YYYYMMDD.json` | 機械 |
| 5 転用 | `transfer_matrix.py` | 工程3の出力＋`config/industries_jp.txt` | `log/transfer-YYYYMMDD.md` | **空欄を人が埋める** |
| 6 一覧化 | `build_report.py` | 工程1〜4の出力 | `log/report-YYYYMMDD.md` | 機械 |
| 7 読解・分類 | — | 工程6の出力 | 判断 | **人**（`METHOD.md` §3・§7） |

**同じ日に何度実行しても、同じ file に併合されます。** 重複は `case_id` と URL で落とします。

---

## 0. 検索語の発見（人は語を書きません）

```bash
python tools/discover_queries.py --kind product
python tools/discover_queries.py --kind failure
python tools/discover_queries.py --kind product --dry-run   # 語を書き出さずに試す
```

- algorithm と、採否の指標を種別で変える理由は `doc/METHOD.md` §5A にあります。
- **出力の語には、採用理由の実測値が必ず付きます**（`log/discovery-<種別>-*.json`）。
- 採用0語で落ちた場合、**閾値を緩める前に母集団（`config/discovery.yaml` の `corpus`）を広げてください。** 閾値から緩めると、後の工程すべてが弱い語に乗ります。
- 1回の実行で使う request 数は `config/discovery.yaml` の `budget` で頭打ちにしています。

## 0b. 日本語の語の発見

```bash
python tools/discover_jp_terms.py --only billing compliance --limit 2
```

- Qiita の tag を語の単位として使います（日本語には分かち書きが無いため）。
- **`config/categories.yaml` へ自動反映しません。** 提案 file を人が見て採否を決めます。
- **現時点で最も弱い部分です。** tag は技術名に偏るため、業務の語はあまり出ません。

## 1. 収集

```bash
python tools/collect_cases.py --queries config/queries_auto-product-YYYYMMDD.txt --kind product
python tools/collect_cases.py --queries config/queries_auto-failure-YYYYMMDD.txt --kind failure
```

- **失敗事例の収集を飛ばさないでください。** `build_report.py` は失敗事例が0件だと警告を出します。
- 人が書いた語で回したい場合だけ `config/queries_product.txt` を使います（`run_pipeline.py --no-discover`）。
- `--min-points` は雑音を切るための下限です。下げるほど件数は増えますが、読む量も増えます。

## 2. 価格の証拠

```bash
python tools/fetch_pricing.py --limit 30 --min-points 100
```

- robots.txt を見て、許可されている場合だけ取りに行きます。1事例あたり最大2 request です。
- 価格 page への link を本文から探して、1回だけ追いかけます。
- **JavaScript で描く site の価格は取れません。** 取れなかったものは「未取得」、取れて一致が無かったものは「証拠なし」として区別して残します。

## 3. 条件照合

```bash
python tools/screen_cases.py
```

- 条件は `config/screen.yaml` にあります。**program 側に閾値はありません。**
- 出力は「4軸中N軸該当」までです。採否は書きません。
- 対象外の印（暗号資産・hardware・個人向けのみ）は**削除ではなく印**です。後から見直せます。

## 4. 日本側の実測

```bash
python tools/jp_market_check.py --only billing field_ops --limit 2
QIITA_TOKEN=xxxx python tools/jp_market_check.py --only billing booking compliance doc_generation --limit 4
```

- **Qiita は認証なしで 60 request/時です。** 残数 header を見て、足りなくなったらその場で止めて「未測定」として残します。
- 1分類あたり Qiita は 5 request 程度を使います。`--only` で絞って回してください。
- 出力の `limits` に、その数字で言えないことを書き込んでいます。**表だけを切り出して使わないでください。**

## 5. 転用

```bash
python tools/transfer_matrix.py --top 5
python tools/transfer_matrix.py --top 5 --hypothesis   # LLM の下書きが要る場合
```

- 既定は**空欄の worksheet** です。program は転用先を決めません。
- `--hypothesis` を付けると LLM が下書きを書きますが、出力は `transfer-hypotheses-*.md` という別 file になり、全行が「仮説（未検証）」です。**証拠の file に混ぜないでください。**
- LLM の provider と model は `config/llm.yaml` に書きます。API key は環境変数です。**未設定なら、代替に切り替えずその場で止まります。**

## 6. 一覧化

```bash
python tools/build_report.py --top 40
```

- 新しい判定はしません。既に測った数字を並べ替えるだけです。
- **§5「欠損の記録」を必ず読んでください。** 未取得の件数が多いほど、一覧の上位は弱い証拠に依っています。

---

## 7. 1周の回し方

1. 工程0〜6 を流す（`python tools/run_pipeline.py`）
2. `log/report-*.md` の**失敗事例の節から先に読む**（§3 の型に分類する）
3. 上位の事例の価格 page を人が開いて、Stock性の○×を確かめる
4. `log/transfer-*.md` の空欄を埋める。**「不明」が残る行は、その検証を先にやる**
5. 埋まった行のうち、最も安く真偽が分かるものを1つ選び、実際に人に会って聞く
6. 分かったことで **`config/screen.yaml` の条件（＝何を positive と呼ぶか）** と `config/categories.yaml` を書き換え、次の周へ

**2周目以降は検索語が変わります。** ただし書き換えるのは条件であって、語ではありません。**語は条件から機械が導き直します。**

---

## 8. 注意

- **一覧が長くなること自体は成果ではありません。** 件数は増やせます。増やしても決定には近づきません。
- **工程5の空欄を埋めずに工程1へ戻らないでください。** 収集のやり直しは、最も気持ちよく、最も進まない作業です。
