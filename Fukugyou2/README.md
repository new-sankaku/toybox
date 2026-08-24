# Fukugyou2 — 題材探しの自動化

**目的:** 継続課金で積み上がり（Stock型）、提供の中核を機械が回せる副業の題材を、**既に製品化された事例から**選びます。

**この folder がやること:** 検索語の自動発見 → 事例（成功・失敗の両方）の収集 → 条件照合 → 日本市場への当てはめ → 他業界への転用 worksheet → 一覧化。
**この folder がやらないこと:** 採否の決定、価格の決定、事例の要約。**決めるのは人です**（`doc/METHOD.md` §5 規律8）。

**製品化事例の検索語は人が書きません。** 人が書くのは「何を positive と呼ぶか」の定義だけで、
検索語は母集団から機械が作り、実測の歩留まりで採否を決めます（`doc/METHOD.md` §5A）。
**失敗事例側は人が書いた定義から出発します**（Hacker News に撤退報告の構造 tag が無いためです）。

---

## 使い方

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux  : source .venv/bin/activate
pip install -r requirements.txt

python tools/run_pipeline.py
```

test を回す場合:

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q
```

個別に流す場合は `doc/PIPELINE.md` を見てください。

```bash
python tools/discover_queries.py --kind product      # 検索語を data から作る
python tools/discover_queries.py --kind failure
python tools/collect_cases.py --queries config/queries_auto-product-YYYYMMDD.txt --kind product
python tools/collect_cases.py --queries config/queries_auto-failure-YYYYMMDD.txt --kind failure
python tools/fetch_pricing.py --limit 30 --min-points 100
python tools/screen_cases.py
python tools/jp_market_check.py --only billing field_ops --limit 2
python tools/transfer_matrix.py --top 5
python tools/build_report.py
```

読むのは `log/report-YYYYMMDD.md` と `log/transfer-YYYYMMDD.md` の2つです。

---

## 構成

```
config/    条件・分類・業界・情報源・発見・LLM 設定（閾値は全部ここ。code に埋めません）
           queries_auto-*.txt は工程0 が書き出す検索語です（人が書いた語ではありません）
tools/     工程0〜6 の program（venv 前提、Windows / Linux 両対応、標準 library のみ＋PyYAML）
tests/     pytest。純関数・設定の整合・robots の解釈・条件照合を検査します
doc/       METHOD.md（何を・なぜ・発見 algorithm）/ PIPELINE.md（工程）
           SOURCES.md（情報源と上限）/ ENGINEERING.md（道具としての現在地と不足）
log/       出力。file 名に取得日が入ります。raw/ に生 response、runs/ に実行の記録を残します
```

| program | 役割 |
|---|---|
| `discover_queries.py` | **検索語を母集団から作り、実測で採否を決める**（人は語を書きません） |
| `discover_jp_terms.py` | 日本語の語を Qiita の tag から広げる（提案のみ。自動反映しません） |
| `collect_cases.py` | Hacker News から事例を集める（**失敗事例も**） |
| `fetch_pricing.py` | 事例の site を見て価格表の証拠を採る（robots.txt 尊重） |
| `screen_cases.py` | 4軸の条件に何件該当したかを出す（採否は書かない） |
| `jp_market_check.py` | 分類ごとに 日本語圏 / 英語圏 の言及量を数える |
| `transfer_matrix.py` | 事例 × 業界 の worksheet を作る（`--hypothesis` で LLM 下書き） |
| `build_report.py` | ここまでを1枚の markdown にまとめる |
| `run_pipeline.py` | 上を順に流す |

---

## 出力の読み方

一覧の軸の記号は **S**=Stock性 **A**=AI自動化性 **P**=証拠性 **B**=法人が払うか です（定義は `doc/METHOD.md` §4）。

- **4軸該当は「当たり」ではありません。** 「2段目の証拠がある候補」という意味です。証拠の1段目（自分が受け取った金）は機械では出ません。
- **価格の証拠の「未取得」と「証拠なし」は別物です。** 未取得が多いほど、上位は弱い証拠に依っています。
- **§5「欠損の記録」を飛ばさないでください。**
- **失敗事例の節から先に読んでください。** 撤退理由の型は `doc/METHOD.md` §3 にあります。

---

## 現時点の実測（2026-08-24）

| | 実測 |
|---|---|
| 収集した事例 | 411件（製品化 253 / 失敗・撤退 158） |
| 価格 page | 取得 8件 / 取りに行っていない 403件（うち継続課金の表示あり 2件） |
| 4軸該当 | **0件** / 3軸 11件 / 2軸 71件 |
| 日本側を測った分類 | 6分類（自動発見の提案語は検証を通ったもの1語のみ） |

**この数字はまだ判断材料ではありません。** それどころか、Agent によるレビューで
**上位に並んでいた事例が誤検出だったこと**が分かっています（`doc/ENGINEERING.md` §0）。
原価を継続課金と読んでいたためで、打ち消し語の導入で4軸該当は0件になりました。
**判定を「語の一致」から「抽出値」に変えるまで、この一覧は候補の生成にも足りません。**

---

## 限界

`doc/METHOD.md` §6 に全部書いています。要点だけ:

- 言及の件数は需要ではありません
- Qiita / Zenn は技術者に偏るため、**非 IT 業界の需要は数字に出ません**
- Hacker News の点数は人気であり、金ではありません
- 画面を JavaScript で描く site の価格は取れません

**機械は候補を絞るところまでです。最後は人が会って聞くまで、何も確定しません。**

道具としての不足（情報源が1本であること、取り逃しの量を測っていないこと）と、
その解消の順序は **`doc/ENGINEERING.md`** に書いています。**現時点の一覧は候補の生成には使えますが、
「他に無い」という主張には使えません。**
