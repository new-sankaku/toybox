# G. 生態系別の閾値 — 実測による決定

測定日: **2026-08-11**（すべて UTC）
環境: Windows 11 / Git Bash / curl 8.12.1 / Python 3.10.9
成果物: `config/thresholds.yaml`（script が読む設定 file）

対象: `doc/MARKET_RESEARCH.md` §3 Phase 2（定量 scan・棄却用）の判定式。
現行の判定式は WordPress 生態系でしか閾値が決まっておらず、しかも **その 4 条件自体に percentile の根拠がありません**。本 document は実際に API を叩いて分布を測り、percentile から閾値を決め直した記録です。

---

## 0. 結論（先に）

| 生態系 | 閾値を決められたか | 評価可能な条件 | 実測合格率（2条件以上） |
|---|---|---|---|
| WordPress | **決められた** | 4 / 4 | 8/22 語（36%） |
| Atlassian Marketplace | **決められた**（C4 のみ不可） | 3 / 4 | 5/22 語（23%） |
| VS Code Marketplace | **決められた**（開発系 keyword で。業務系 keyword では C2 不可） | 3 / 4 | 4/20 語（20%） |
| Chrome Web Store | **一部のみ**（C1 が原理的に不可） | 2 / 4 | 1/10 語（10%） |
| Shopify | **測っていない** | — | — |

そして本測定でいちばん重要な発見は次の 2 つです。

1. **現行の「4条件のうち3つ以上」は、閾値を percentile で定義すると通過率 0/22 語になります。** 各条件を p25/p75 線で切ると 1 条件あたりの成立率は構造的に約 25% になり、条件どうしはほぼ独立（下記 §5）なので、3 条件同時成立は期待値で 1 語未満です。**gate は「2条件以上」に下げるか、条件ごとの percentile を緩めるかのどちらかが必要です。** 本 document は前者を採り、`thresholds.yaml` の `gate.min_conditions: 2` としました。
2. **現行の 4 条件は、条件ごとの厳しさが 5 倍以上ばらついていました**（§4 の percentile 位置）。「rating 80 未満」は実測 p12（極端に厳しい）、「hit 数が数百件以下」は実測 p50（ほとんど選別していない）、「6 か月以上更新停止」は実測 p93、「support 比が中央値の 2 倍」は実測 p56 です。3-of-4 という個数 rule は、この不揃いな厳しさの上に載っていました。

---

## 1. 測定方法

### 1.1 keyword

業務系 22 語（全生態系共通）:

```
invoice / booking calendar / appointment scheduling / inventory management / timesheet /
payroll / crm / expense report / contract management / quotation / purchase order /
approval workflow / digital signature / tax calculation / accounting / shipping /
subscription billing / helpdesk / asset management / document management / recruitment /
compliance audit
```

VS Code のみ、生態系内の語（開発系 20 語）を別途:

```
linter / formatter / snippets / git blame / docker / kubernetes / terraform /
database client / rest client / markdown preview / test runner / code coverage /
spell checker / refactoring / sql formatter / yaml schema / todo tracker / csv viewer /
regex / log viewer
```

VS Code に業務系 22 語を投げると評価件数の p75 が 1 件しかなく（162 件中 rating が有効なのは 6 件）、C2 の閾値を percentile で決められません。**「その生態系にとって外の語」を測っても閾値は決まらない**という当たり前の事実が数字で出たので、両方を残しています。

### 1.2 request 数（すべて上限 200/生態系 以内）

| 生態系 | request 数 | 内訳 |
|---|---|---|
| WordPress | 23 | probe 1 + keyword 22 |
| Atlassian | 187 | probe 5 + keyword 22 + versions/latest 157（unique app 数） |
| VS Code | 43 | probe 1 + 業務系 22 + 開発系 20 |
| Chrome Web Store | 90 | 検索 page 10 + 詳細 page 80 |

request 間隔は 0.8〜2.0 秒。全 request で HTTP 200、失敗ゼロ（1 件、Windows の CRLF を含んだ file から key を読ませて curl exit 3 になった試行があり、`tr -d '\r'` で修正して再実行しています）。

### 1.3 実行 command

**WordPress**（`-g` 必須。無いと角括弧が glob 展開されて exit 3）:

```bash
curl -sg -o "raw/wp/invoice.json" \
  'https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request[search]=invoice&request[per_page]=24'
```

**Atlassian**（検索 1 回で distribution / reviews まで同梱されるので、addon 個別の `/distribution` を叩く必要はありません）:

```bash
curl -s -o "raw/atl/invoice.json" \
  'https://marketplace.atlassian.com/rest/2/addons?text=invoice&limit=24'
# 更新日はこちら（後述のとおり _embedded.lastModified は使えません）
curl -s 'https://marketplace.atlassian.com/rest/2/addons/com.kanoah.test-manager/versions/latest'
# → release: {"date":"2026-08-06","releasedBy":"ZS Automation Admin","beta":false,"supported":true}
```

**VS Code**:

```bash
curl -s -X POST 'https://marketplace.visualstudio.com/_apis/public/gallery/extensionquery' \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json;api-version=7.2-preview.1' \
  -d '{"filters":[{"criteria":[{"filterType":8,"value":"Microsoft.VisualStudio.Code"},
       {"filterType":10,"value":"invoice"}],"pageSize":24,"pageNumber":1,"sortBy":0,"sortOrder":0}],
      "flags":914}'
```

`filterType 8` は対象製品の固定、`10` が検索語です。hit 総数は `results[0].resultMetadata` の `ResultCount.TotalCount` に入ります。`install` を使い、`downloadCount` は使いません（70 倍違う別物）。

**Chrome Web Store**（API が無いため HTML）:

```bash
curl -sL --compressed -A 'Mozilla/5.0 ...' 'https://chromewebstore.google.com/search/invoice'
curl -sL --compressed -A 'Mozilla/5.0 ...' 'https://chromewebstore.google.com/detail/<32文字のid>'
```

### 1.4 指標の作り方

- **経過月数** = (2026-08-11 − 最終更新日) / 30.44 日
- **rating** は評価件数 5 件未満を欠測扱い（1 件の 5 つ星で p25 が動くのを防ぐため）
- **集中度** = 上位1件の install ÷ 上位8件の install 合計
- **語別中央値** = その語の上位8件の中央値。**語単位で判定するので、閾値もこの語別中央値の分布から取ります**
- Atlassian は `bundled` / `bundledCloud` が true の app を除外（同梱は自発的導入ではない）、`totalUsers: -1` は sentinel なので使わない

---

## 2. 生の分布（percentile 表）

### 2.1 検索 hit 数（語単位）

| 生態系 | n | min | p10 | p25 | p50 | p75 | p90 | max |
|---|---|---|---|---|---|---|---|---|
| WordPress | 22 | 16 | 73 | **268.5** | 472 | 1,020 | 1,903 | 3,601 |
| Atlassian | 22 | 8 | 23 | **107.5** | 446 | 1,704 | 2,626 | 3,828 |
| VS Code（業務系） | 22 | 2 | 5 | 16 | 85 | 519 | 1,775 | 3,884 |
| VS Code（開発系） | 20 | 261 | 309 | **532** | 1,723 | 4,047 | 6,380 | 38,343 |
| Chrome | — | — | — | — | — | — | — | — |

WordPress の実測値は既存 doc の記載と一致しました（`invoice` 1,513 = 記載どおり、`booking calendar` 721 vs 記載 719〜720、`subscription billing` 857 = 記載どおり）。**hit 数は「日々変動する」と書かれていますが、少なくとも本測定と既存記載の間の変動は 0〜0.3% です。**

### 2.2 install / 導入数（上位8件 pooled）

| 生態系 | n | p10 | p25 | p50 | **p75** | p90 | max |
|---|---|---|---|---|---|---|---|
| WordPress（active_installs） | 176 | 100 | 900 | 5,000 | **52,500** | 500,000 | 10,000,000 |
| Atlassian（totalInstalls） | 176 | 4.5 | 36 | 182 | **982** | 5,420 | 34,724 |
| VS Code 業務系（install） | 130 | 4 | 12 | 68 | 520 | 10,173 | 386,410 |
| VS Code 開発系（install） | 160 | 63 | 4,268 | 138,984 | **813,364** | 5,181,974 | 70,716,225 |
| Chrome（users） | 77 | 15 | 57 | 922 | **10,000** | 58,000 | 1,000,000 |

**生態系ごとに 3 桁違います。** Atlassian の上位 app は totalInstalls が 3 桁、VS Code の上位は 5〜6 桁です。「install 1万以上」のような絶対値を生態系をまたいで使うことはできません。

### 2.3 rating（評価5件以上のみ）

| 生態系 | 尺度 | n | p10 | **p25** | p50 | p75 | p90 |
|---|---|---|---|---|---|---|---|
| WordPress | 0–100 | 152 | 78.0 | **88.0** | 94.0 | 98.0 | 100.0 |
| Atlassian | 0–5 | 108 | 3.75 | **4.284** | 4.581 | 4.750 | 5.0 |
| VS Code 業務系 | 0–5 | **6** | 4.36 | 4.44 | 4.74 | 4.96 | 5.0 |
| VS Code 開発系 | 0–5 | 85 | 3.15 | **3.833** | 4.415 | 4.750 | 5.0 |
| Chrome | 0–5 | 46 | 3.25 | **3.925** | 4.5 | 4.9 | 5.0 |

評価件数の分布（p50）は WordPress 32 件、Atlassian 9 件、VS Code 開発系 5 件、VS Code 業務系 0 件、Chrome 7 件。**VS Code に業務系の語を投げた場合、rating は標本 6 件しか無く閾値を決められません。**

### 2.4 最終更新からの経過月数

件単位（上位8件 pooled）:

| 生態系 | n | p10 | p25 | p50 | p75 | p90 | max |
|---|---|---|---|---|---|---|---|
| WordPress | 176 | 0.0 | 0.16 | 0.61 | 1.71 | 3.07 | 17.5 |
| Atlassian（release.date） | 176 | 0.03 | 0.21 | 1.31 | 8.21 | 31.9 | — |
| VS Code 業務系 | 162 | 0.58 | 3.18 | 10.59 | 52.30 | 61.48 | 90.0 |
| VS Code 開発系 | 160 | 0.82 | 2.93 | 14.34 | 52.78 | 91.18 | 123.0 |
| Chrome | 80 | 0.13 | 0.93 | 4.99 | 15.10 | 23.29 | 46.5 |

語別中央値の分布（**閾値はここから取る**）:

| 生態系 | n | p25 | p50 | **p75** | p90 |
|---|---|---|---|---|---|
| WordPress | 22 | 0.29 | 0.52 | **1.19** | 1.98 |
| Atlassian | 22 | 0.36 | 1.85 | **5.60** | 9.12 |
| VS Code 開発系 | 20 | 10.02 | 18.76 | **46.73** | 52.79 |
| Chrome | 10 | 1.60 | 3.53 | **11.28** | 12.72 |

**放置の意味が生態系ごとに 40 倍違います。** WordPress の上位 plugin は半数が 1 か月以内に更新されており、6 か月放置は p93 の裾です。VS Code は逆に中央値が 14 か月で、「6 か月放置」を持ち込むと全語が該当してしまい選別になりません。

### 2.5 集中度（上位1件 install ÷ 上位8件合計・語単位）

| 生態系 | n | p10 | p25 | p50 | p75 | p90 |
|---|---|---|---|---|---|---|
| WordPress | 22 | 0.324 | 0.642 | 0.839 | 0.945 | 0.976 |
| Atlassian | 22 | 0.288 | 0.312 | 0.500 | 0.739 | 0.799 |
| VS Code 開発系 | 20 | 0.350 | 0.573 | 0.750 | 0.861 | 0.906 |
| Chrome | 10 | 0.511 | 0.592 | 0.635 | 0.888 | 0.930 |

WordPress は中央値 0.84 で、**上位8件のうち1件が install の 8 割以上を持つのが普通**です（`digital signature` は 0.999）。集中度は測れましたが、**判定条件には採用していません**。理由は §6 に書きます。

### 2.6 不満 stock（WordPress のみ）

`support_threads / active_installs × 1000`（1,000 install あたりの thread 数）

| 単位 | n | p10 | p25 | p50 | **p75** | p90 | max |
|---|---|---|---|---|---|---|---|
| 件単位 | 176 | 0.0 | 0.0 | 0.024 | 0.333 | 1.350 | 105.7 |
| 語別中央値 | 22 | 0.0 | 0.004 | 0.043 | **0.116** | 0.332 | — |

---

## 3. 語ごとの実測値と判定

○ = 条件成立（＝候補として残る方向）。

### 3.1 WordPress

| keyword | hit数 | 上位8 install中央値 | 集中度 | rating中央値 | 更新月数中央値 | C1 | C2 | C3 | C4 |
|---|---|---|---|---|---|---|---|---|---|
| accounting | 429 | 950 | 0.87 | 98.00 | 2.3 | × | × | ○ | × |
| appointment scheduling | 332 | 40,000 | 0.30 | 89.00 | 0.2 | × | ○ | × | × |
| approval workflow | 411 | 550 | 0.99 | 97.00 | 1.2 | × | × | ○ | ○ |
| asset management | 1,946 | 455,000 | 0.78 | 92.00 | 0.4 | × | ○ | × | × |
| booking calendar | 721 | 25,000 | 0.31 | 93.00 | 0.2 | × | ○ | × | ○ |
| compliance audit | 750 | 300,000 | 0.31 | 96.00 | 0.6 | × | ○ | × | × |
| contract management | 260 | 35,500 | 0.72 | 97.00 | 0.3 | ○ | ○ | × | × |
| crm | 1,302 | 4,000 | 0.96 | 96.00 | 0.5 | × | ○ | × | × |
| digital signature | 241 | 950 | 1.00 | 83.00 | -0.0 | ○ | × | × | × |
| document management | 1,074 | 6,500 | 0.88 | 95.00 | 0.4 | × | × | × | × |
| expense report | 69 | 1,000 | 0.41 | 96.00 | 0.7 | ○ | × | × | × |
| helpdesk | 332 | 4,000 | 0.80 | 91.00 | 0.8 | × | × | × | ○ |
| inventory management | 727 | 1,500 | 0.44 | 93.00 | 0.3 | × | × | × | ○ |
| invoice | 1,513 | 5,500 | 0.75 | 94.00 | 1.1 | × | × | × | ○ |
| payroll | 29 | 200 | 0.94 | 94.00 | 2.0 | ○ | × | ○ | × |
| purchase order | 2,843 | 3,000 | 0.90 | 94.00 | 2.6 | × | ○ | ○ | × |
| quotation | 294 | 2,500 | 0.95 | 89.00 | 1.6 | × | ○ | ○ | × |
| recruitment | 111 | 3,000 | 0.98 | 95.00 | 1.4 | ○ | × | ○ | × |
| shipping | 3,601 | 50,000 | 0.96 | 91.00 | 0.1 | × | ○ | × | × |
| subscription billing | 857 | 10,000 | 0.85 | 93.00 | 0.3 | × | ○ | × | ○ |
| tax calculation | 515 | 185,000 | 0.82 | 90.00 | 0.2 | × | ○ | × | × |
| timesheet | 16 | 600 | 0.62 | 88.00 | 0.6 | ○ | × | × | × |

2 条件以上（＝残る）: approval workflow / booking calendar / contract management / payroll / purchase order / quotation / recruitment / subscription billing の 8 語。
3 条件以上: **0 語**。

### 3.2 Atlassian

| keyword | hit数 | 上位8 install中央値 | 集中度 | rating中央値 | 更新月数中央値 | C1 | C2 | C3 |
|---|---|---|---|---|---|---|---|---|
| accounting | 384 | 3 | 0.75 | 2.98 | 2.1 | × | × | × |
| appointment scheduling | 652 | 166 | 0.70 | 4.31 | 1.6 | × | ○ | × |
| approval workflow | 1,760 | 1,338 | 0.45 | 4.78 | 0.2 | × | ○ | × |
| asset management | 2,634 | 635 | 0.29 | 4.58 | 0.3 | × | × | × |
| booking calendar | 508 | 1,107 | 0.30 | 4.36 | 0.5 | × | ○ | × |
| compliance audit | 650 | 208 | 0.30 | 4.57 | 0.3 | × | × | × |
| contract management | 2,550 | 44 | 0.98 | 4.30 | 1.6 | × | × | × |
| crm | 3,828 | 412 | 0.36 | 4.38 | 3.4 | × | ○ | × |
| digital signature | 171 | 172 | 0.33 | 4.63 | 3.7 | × | × | × |
| document management | 2,944 | 724 | 0.55 | 4.66 | 0.5 | × | × | × |
| expense report | 1,537 | 3,815 | 0.29 | 4.58 | 0.5 | × | × | × |
| helpdesk | 30 | 98 | 0.56 | 4.68 | 7.2 | ○ | × | ○ |
| inventory management | 2,541 | 3,978 | 0.45 | 4.58 | 0.2 | × | ○ | × |
| invoice | 97 | 20 | 0.78 | 5.00 | 16.5 | ○ | × | ○ |
| payroll | 15 | 386 | 0.80 | 4.58 | 0.3 | ○ | ○ | × |
| purchase order | 231 | 80 | 0.55 | 4.66 | 9.8 | × | × | ○ |
| quotation | 22 | 135 | 0.25 | 4.45 | 4.5 | ○ | × | × |
| recruitment | 8 | 1 | 0.71 | — | 2.9 | ○ | × | × |
| shipping | 90 | 78 | 0.76 | 4.64 | 9.3 | ○ | ○ | ○ |
| subscription billing | 139 | 79 | 0.84 | 4.44 | 6.0 | × | ○ | ○ |
| tax calculation | 728 | 86 | 0.25 | 4.48 | 7.1 | × | × | ○ |
| timesheet | 155 | 5,034 | 0.44 | 4.56 | 0.2 | × | ○ | × |

2 条件以上: helpdesk / invoice / payroll / shipping / subscription billing の 5 語（`shipping` のみ 3 条件）。

### 3.3 VS Code（開発系 keyword）

| keyword | hit数 | 上位8 install中央値 | 集中度 | rating中央値 | 更新月数中央値 | C1 | C2 | C3 |
|---|---|---|---|---|---|---|---|---|
| code coverage | 38,343 | 17,448 | 0.64 | 4.51 | 19.2 | × | × | × |
| csv viewer | 1,914 | 984 | 0.82 | 3.84 | 1.7 | × | ○ | × |
| database client | 1,747 | 68,418 | 0.72 | 4.32 | 1.2 | × | ○ | × |
| docker | 534 | 513,116 | 0.90 | 4.48 | 52.8 | × | ○ | ○ |
| formatter | 1,482 | 2,297,600 | 0.78 | 3.83 | 34.3 | × | ○ | × |
| git blame | 6,336 | 593,036 | 0.86 | 4.58 | 3.9 | × | ○ | × |
| kubernetes | 277 | 250,668 | 0.82 | 4.65 | 37.3 | ○ | × | × |
| linter | 1,344 | 281,428 | 0.26 | 4.36 | 62.7 | × | × | ○ |
| log viewer | 3,783 | 2,228 | 0.69 | 3.92 | 18.3 | × | × | × |
| markdown preview | 6,090 | 1,825,796 | 0.41 | 4.54 | 8.3 | × | × | × |
| refactoring | 417 | 14,692 | 0.83 | 3.83 | 53.1 | ○ | × | ○ |
| regex | 313 | 12,421 | 0.87 | 5.00 | 13.4 | ○ | × | × |
| rest client | 1,698 | 160,820 | 0.47 | 4.28 | 33.2 | × | ○ | × |
| snippets | 6,780 | 4,820,072 | 0.36 | 4.28 | 47.3 | × | × | ○ |
| spell checker | 526 | 352,429 | 0.90 | 4.75 | 12.7 | ○ | × | × |
| sql formatter | 2,882 | 67,248 | 0.61 | 3.38 | 51.1 | × | ○ | ○ |
| terraform | 261 | 230,800 | 0.64 | 3.59 | 46.5 | ○ | ○ | × |
| test runner | 4,837 | 107,605 | 0.94 | 4.72 | 7.0 | × | × | × |
| todo tracker | 1,343 | 20 | 0.29 | — | 10.6 | × | × | × |
| yaml schema | 2,143 | 2,404 | 0.94 | — | 12.8 | × | × | × |

2 条件以上: docker / refactoring / sql formatter / terraform の 4 語。

### 3.4 Chrome Web Store

C1（hit 数）が測れないため 2 条件のみ。

| keyword | 上位8 users中央値 | 集中度 | rating中央値 | 更新月数中央値 | C2 | C3 |
|---|---|---|---|---|---|---|
| accounting | 56 | 0.99 | 5.00 | 16.0 | × | ○ |
| appointment scheduling | 3,500 | 0.63 | 4.60 | 1.4 | × | × |
| booking calendar | 339 | 0.59 | 4.90 | 4.7 | × | × |
| crm | 10,000 | 0.84 | 4.60 | 1.1 | ○ | × |
| document management | 5,492 | 0.92 | 4.40 | 12.3 | ○ | ○ |
| expense report | 4,000 | 0.53 | 4.30 | 2.4 | ○ | × |
| inventory management | 133 | 0.90 | 4.40 | 1.1 | ○ | × |
| invoice | 8,500 | 0.38 | 3.55 | 8.2 | ○ | × |
| purchase order | 302 | 0.65 | 4.00 | 2.1 | ○ | × |
| timesheet | 70 | 0.60 | 3.65 | 12.4 | × | ○ |

2 条件成立: document management の 1 語のみ。

---

## 4. 現行 doc の閾値が実測分布のどこにあったか

WordPress の 2026-08-11 標本での percentile 位置です。

| 現行 doc の条件 | 実測での位置 | 評価 |
|---|---|---|
| 検索 hit 数が「数百件以下」（500 と解釈） | 語別分布の **p50** | 半分を通す。棄却 gate としてほぼ機能していない |
| 上位8件に install **1万以上** | 件単位分布の **p65** | 「上位」と呼ぶには緩い |
| かつ rating **80 未満** | 件単位分布の **p12** | 極端に厳しい。install 側との厳しさが 5 倍以上ずれている |
| 6 か月以上更新停止が **2件以上** | 6 か月は件単位分布の **p93**。2 件以上を満たす語は 22 語中 3 語（14%） | 裾すぎる |
| support_threads / active_installs が **中央値の2倍** | 件単位分布の **p56** | ほぼ選別していない |

「hit 数 1,000 以下」なら p73、「12 か月以上更新停止」なら p98 でした。**現行の 4 条件は p12 から p93 までばらついた線の寄せ集めで、そこに「3つ以上」という個数 rule を掛けていた**ことになります。

---

## 5. なぜ gate を「2条件以上」にしたか

percentile で切ると各条件の成立率は構造的に約 25% になります（実測: C1 6/22、C2 11/22、C3 6/22、C4 6/22）。条件どうしの重なりを見ると:

| | C1 | C2 | C3 | C4 |
|---|---|---|---|---|
| **C1** | 6 | 1 | 2 | 0 |
| **C2** | 1 | 11 | 2 | 2 |
| **C3** | 2 | 2 | 6 | 1 |
| **C4** | 0 | 2 | 1 | 6 |

独立を仮定した期待重なりは C1∩C2 で 3.0（実測 1）、C1∩C4 で 1.6（実測 0）。**条件は冗長ではなく、むしろわずかに負の相関があります。** 独立に近い 25% の事象を 3 つ同時に要求すれば通過率は数 % で、n=22 では 0〜1 語しか出ません（実測 0 語）。

成立条件数ごとの語数:

| 生態系 | 0 | 1 | 2 | 3 | 4 |
|---|---|---|---|---|---|
| WordPress（4条件） | 1 | 13 | 8 | 0 | 0 |
| Atlassian（3条件） | 7 | 10 | 4 | 1 | — |
| VS Code 開発系（3条件） | 6 | 10 | 4 | 0 | — |
| VS Code 業務系（3条件） | 11 | 8 | 3 | 0 | — |
| Chrome（2条件） | 2 | 7 | 1 | — | — |

「2条件以上」で合格率は 10〜36%。棄却 gate として妥当な範囲に収まります。**ただしこの合格率は生態系ごとに揃っていません**（評価可能な条件数が違うため）。合格率を揃えたい場合は、`thresholds.yaml` の `min_conditions` ではなく各条件の percentile（p25/p75）を動かす方が素直です。

なお `payroll` は WordPress・Atlassian・VS Code 業務系の 3 生態系で、`subscription billing` は WordPress・Atlassian の 2 生態系で残りました。これは「複数の source で同じ入口が残った」という以上の意味を持ちません（MARKET_RESEARCH.md §3 の winner's curse の注記どおり、**通過時点の見込みは推定より必ず低い**）。

---

## 6. 集中度を条件に採用しなかった理由

集中度（上位1件 ÷ 上位8件）は全生態系で測れました（§2.5）。採用しなかったのは、**符号が決まらない**からです。

- 集中度が高い＝1 社が総取り。個人が正面から勝てないので棄却したい、と読める
- 集中度が高い＝残り 7 件が育っていない＝差別化の余地がある、とも読める

WordPress の実測では `digital signature` 0.999、`approval workflow` 0.990 と極端に高い語がある一方、`appointment scheduling` 0.295 のように分散した語もありますが、**どちらが個人参入に有利かを本測定の data だけでは決められません。** 判定に入れると符号を推測で埋めることになるため、`thresholds.yaml` には分布だけを残し、条件からは外しました。符号を決めるには Phase 3 以降（interview / pre-sale）の結果と突き合わせる必要があります。

---

## 7. 測れなかったもの・落とし穴

### 7.1 Chrome Web Store — 公開 API は存在しない

確認した endpoint と結果:

| URL | 結果 |
|---|---|
| `https://chromewebstore.google.com/_/ChromeWebStoreConsumerFeUi/data/batchexecute` | HTTP 405（GET 不可。内部 RPC で公開仕様なし） |
| `https://chrome.google.com/webstore/ajax/item` | HTTP 301（旧 endpoint。現行 store へ redirect） |
| `https://chromewebstore.google.com/search/invoice` | HTTP 200・HTML 550KB |
| `https://chromewebstore.google.com/detail/<id>` | HTTP 200・HTML 725KB |

**公開 API は見つかりませんでした。** 代替として HTML を読みましたが、以下の制約があります。

- **hit 総数の表記が無い** — 検索結果 HTML 全文を検索しても「N results」に相当する文字列が存在しません。**C1 は原理的に測れません。**
- **検索結果は初回 10 件のみ** server-side rendering。以降は lazy load。
- **user 数は丸め値** — `59,000,000 users` / `1,000,000 users` / `10,000 users` のように有効数字 1〜2 桁。閾値付近の比較は桁でしか意味を持ちません。
- **評価件数も大きい値は丸め** — `290.3K ratings`。また評価 1 件の item は "1 rating"（単数形）で、複数形前提の抽出は取りこぼします（本測定でも 80 件中いくつか欠測）。
- **users が取れなかった item が 80 件中 3 件**ありました（page 構造の違い。原因未特定）。
- 標本が 10 語 80 件と小さく、percentile の信頼性は他生態系より明確に低いです（語別中央値月数 p75 = 11.28、90%CI 4.02〜15.10）。

取れる表記形式は確認できました:
`>59,000,000 users<` / `Updated</div><div>August 4, 2026</div>` / `class="GlMWqe">4.5 out of 5` / `290.3K ratings`。

### 7.2 Atlassian の `lastModified` は更新日として使えない

search 応答の `_embedded.lastModified` は一見「最終更新日」ですが、**501 件中 230 件（45.9%）が 2 日に集中していました**（2025-12-11 が 121 件、2026-07-24 が 109 件）。marketplace 側の一括更新が混入しており、放置の signal になりません。

代わりに `/rest/2/addons/{key}/versions/latest` の `release.date` を使いました。157 app で取得して 2018-02-16〜2026-08-11 に自然に分布しており、更新日として使えます。**この差し替えをしないと Atlassian の C3 は測れたつもりで測れていません。**

### 7.3 Atlassian の C4（不満 stock）は未測定

WordPress の `support_threads` に相当する field がありません。`/rest/2/addons/{key}/reviews` で review 本文と星が取れるので「低評価 review の割合」で代替できる見込みはありますが、app ごとに 1 request 増え（157 app）、今回の 200 request/生態系 の枠に収まらないため測っていません。**推測で閾値を置くことはしていません。**

### 7.4 VS Code の rating は業務系 keyword では使えない

業務系 22 語・162 件のうち、評価 5 件以上は **6 件**（評価件数の p50 が 0、p75 が 1）。C2 の閾値を percentile で決められません。開発系 20 語では 160 件中 85 件が有効で、閾値が決まります。

その他:
- `install` と `downloadCount` は 70 倍違う別物。`install` を使うこと（既存 doc の指摘どおり）。
- statistics は評価が無い extension では `averagerating` / `ratingcount` の key 自体が現れません。欠測と 0 を区別する実装が必要です。
- 値は JSON の float で返ります。

### 7.5 WordPress

- `active_installs` は有効数字 1 桁の丸め値なので、install の percentile も丸めの格子（100 / 900 / 5,000 / 52,500）に乗ります。閾値付近の 1.2 倍差は差ではありません。
- `-g`（`--globoff`）が無いと `request[...]` の角括弧で curl が exit 3 になります。

### 7.6 標本サイズと percentile の信頼性（重要）

bootstrap（B=2000、90%CI）:

| 生態系 | 指標 | 点推定 | 90%CI | n |
|---|---|---|---|---|
| WordPress | hit 数 p25 | 268.5 | **79.5 〜 415.5** | 22 |
| WordPress | install p75 | 52,500 | 30,000 〜 72,500 | 176 |
| WordPress | rating p25 | 88.0 | 86.0 〜 90.0 | 152 |
| WordPress | 語別中央値月数 p75 | 1.19 | **0.61 〜 1.91** | 22 |
| WordPress | 語別中央値 苦情率 p75 | 0.116 | **0.060 〜 0.298** | 22 |
| Atlassian | hit 数 p25 | 107.5 | **30.0 〜 231.0** | 22 |
| Atlassian | install p75 | 982 | 594 〜 1,463 | 176 |
| Atlassian | 語別中央値月数 p75 | 5.60 | **2.89 〜 8.77** | 22 |
| VS Code 開発系 | hit 数 p25 | 532 | **313 〜 1,482** | 20 |
| VS Code 開発系 | install p75 | 813,364 | 486,527 〜 1,809,245 | 160 |
| Chrome | 語別中央値月数 p75 | 11.28 | **4.02 〜 15.10** | 10 |

**件単位の percentile（n=100〜176）は ±1.5 倍程度に収まりますが、語単位の percentile（n=10〜22）は点推定の 1/3 〜 1.6 倍まで動きます。** C1（hit 数）と C3（放置）は語単位なので、閾値は「その桁」としてしか信頼できません。語を 60〜100 語に増やせば CI は半分程度に縮みますが、それでも 2 倍差は差と見なせません（MARKET_RESEARCH.md §5.3 の方針と同じ）。

### 7.7 その他測っていないもの

- **Shopify**: 内訳非公開のため未測定。MARKET_RESEARCH.md §3 の方針（review 件数分布で代替し gate を Phase 3 に寄せる）をそのまま残しています。
- **時系列**: 本測定は 2026-08-11 の 1 時点のみ。hit 数の日次変動は既存 doc の記載値との比較で 0〜0.3% でしたが、これは変動を測ったことにはなりません。
- **rating と実際の不満の関係**: rating inflation（MARKET_RESEARCH.md §5.3、Filippas et al.）により、★の低さを不満の proxy にはできません。C2 は「上位に評価の低い大手が居る」という事実の記述に留めるべきで、「不満がある」と読み替えないでください。

---

## 8. 再測定の手順

閾値は分布から導いているので、分布が動けば閾値も動きます。再測定するときは:

1. §1.3 の command で同じ keyword 一式を取り直す（WordPress 23 / Atlassian 187 / VS Code 43 / Chrome 90 request）
2. §1.4 の定義で percentile を再計算する
3. `config/thresholds.yaml` の `meta.measured_on`・各 `percentiles`・各 `conditions[].value`・`gate.measured_pass_rate` を更新する
4. 合格率が 10〜36% から大きく外れたら、閾値ではなく **keyword 集合か生態系の選び方**を疑う

閾値を script に hard-code しないでください。`thresholds.yaml` を読む実装にしてあります。
