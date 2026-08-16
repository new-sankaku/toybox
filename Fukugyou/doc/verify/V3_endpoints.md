# V3: API endpoint と料金条件の実測検証

検証担当: V3（実測検証）
検証実施日: **2026-08-11**
検証対象: `doc/research/B_quant_sources.md` §5 / §8 / 付録、`doc/research/F_stock_models.md` §3 / §4
検証環境: Windows 11 / Git Bash / `curl 8.x` / WebFetch

**方針**: 文献記述は証拠として採用していません。実際に request して返ってきた response、または公式 page から取得した本文のみを証拠としています。以下の response 抜粋はすべて本検証で実行したものです。

---

## 0. 判定 summary

判定は `実測確認` / `一部相違` / `動作せず` / `未検証` の 4 値です。

### (1) API endpoint

| # | 対象 | 判定 | 要点 |
|---|------|------|------|
| 1 | WordPress.org Plugins API | **実測確認** | 全 field 実在。`info.results=1513` まで完全一致。`active_installs` の有効数字 1 桁丸めも 34 plugin で確認 |
| 2 | Atlassian Marketplace distribution API | **実測確認** | `{"downloads":175535,"totalInstalls":15954,"totalUsers":-1}` を byte 単位で再現。app key も特定 |
| 3 | Stack Exchange API 2.3 | **一部相違** | `quota_max: 300` は実測確認。ただし**公式 doc には 300 の記載が無く、書かれている既定値は 10,000** です。また doc が触れていない throttle が 2 つ存在します |
| 4 | VS Code Marketplace `extensionquery` | **一部相違** | 認証不要は正しく、POST で取得できます。ただし **`install` と `downloadCount` は 70 倍違う別物**で、B document はこれを並列に列挙しています |
| 5 | Apple iTunes Lookup API | **実測確認** | `averageUserRating: 4.68546` / `userRatingCount: 18381636` を完全再現 |
| 6 | Hacker News API | **一部相違** | Firebase 版は公式 README に "There is currently no rate limit." と明記（実測確認）。Algolia 版は公式 page が JS 描画のみで rate limit 記載を確認できず（未検証） |
| 7 | Google Search Console API | **一部相違** | metric / dimension / rowLimit は完全一致。ただし **16 か月保持と anonymized query 除外は当該 page に記載がありません**。dimension に `hour` が追加されており B document の列挙は古いです |
| 補 | npm downloads API | **実測確認** | 厳密値を返します |
| 補 | pypistats API | **実測確認** | 429 を再現。B document の記述通り |

### (2) 料金・条件

| # | 対象 | 判定 |
|---|------|------|
| 8 | Keywords Everywhere Bronze $84/年 100,000 credit | **実測確認** |
| 9 | Ahrefs Starter ¥4,460 / Lite ¥19,900 / API は Standard 以上 | **実測確認** |
| 10 | Semrush Pro $139.95/月 | **動作せず**（本環境から `semrush.com` が DNS 解決不可。B document の注記は再現します） |
| 11 | Ubersuggest Individual $29/月・$290 買切 | **一部相違**（$29/月は確認。**$290 買切と "Individual" という plan 名は確認できず**） |
| 12 | Stack Exchange 無認証 300/日・認証 10,000/日 | **一部相違**（300 は実測確認、10,000 は公式 doc 記載を確認。ただし条件の記述が正確ではありません） |

### (3) F_stock_models.md §4 platform 経済条件

| Platform | 判定 | 要点 |
|----------|------|------|
| Shopify App Store | **実測確認** | 0%/15%・生涯 $1M・2025-01-01 起算・2.9%・$19・$20M/$100M 例外まで全一致 |
| Chrome Web Store | **一部相違** | **$5 という金額は引用元 page に記載がありません**（"one-time registration fee" とのみ）。20 item / 2GB / 30 日は完全一致 |
| VS Code Marketplace | **実測確認** | 有料 extension 非対応・無料・`pricing: Free/Trial`・sponsor link |
| Atlassian Marketplace | **実測確認** | Connect 20%→25%、Forge 16%→17%、日付、**「6 か月前告知」の明文まで verbatim 一致** |
| WordPress.org | **実測確認** | GPL 必須・課金 lock 禁止・trial 停止禁止・外部 SaaS 可・upsell 可、5 項目すべて原文一致 |
| Apple App Store | **実測確認** | $99/年・教育機関 waiver・SBP 15%・前年 $1M 閾値・翌々年再資格化 |
| **Google Play** | **相違** | **既存 install の非 subscription は 25%+5% であり、20%+5% ではありません。**20% は external web link の料率です |
| Figma Community | **一部相違** | 15% / $2 / 30 US 営業日 / 週 1 回 / 新規承認停止はすべて一致。**payout 対応国は 89 か国ではありません**（実測 77 か国。日本は含まれます） |

### (3-b) F_stock_models.md §3 platform 事例

| 事例 | 判定 |
|------|------|
| Twitter API 2023「実質 5 日」 | **実測確認** |
| Reddit API $12,000/50M・月 $1.7M・22 日 | **実測確認（二次 source 経由）**。一次（Selig 本人の投稿）は reddit.com が本環境から取得不可 |
| Chrome Manifest V3 timeline（7 行） | **実測確認**（全行 verbatim 一致） |
| Unity Runtime Fee 撤回 | **実測確認** |
| Shopify rev share 単位変更「53 日」 | **実測確認** |

---

## 1. API endpoint の実測

### 1-1. WordPress.org Plugins API — 実測確認

**実行 command**（`curl -g` が必要です。`request[...]` の角括弧を curl の glob 展開から守るためで、B document 付録の `--data-urlencode` 形式なら不要です）:

```bash
curl -sg 'https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request[search]=invoice&request[per_page]=3'
```

**返り値（抜粋）**:

```
HTTP=200
TOPKEYS ['info', 'plugins']
INFO {'page': 1, 'pages': 50, 'results': 1513}
PLUGIN_KEYS ['active_installs', 'added', 'author', 'author_profile', 'description',
 'donate_link', 'download_link', 'downloaded', 'homepage', 'icons', 'last_updated',
 'name', 'num_ratings', 'rating', 'ratings', 'requires', 'requires_php',
 'requires_plugins', 'short_description', 'slug', 'support_threads',
 'support_threads_resolved', 'tags', 'tested', 'version']

name = 'PDF Invoices &amp; Packing Slips for WooCommerce'
slug = 'woocommerce-pdf-invoices-packing-slips'
active_installs = 300000
downloaded = 23399657
num_ratings = 1859
rating = 100
ratings = {'5': 1816, '4': 22, '3': 7, '2': 6, '1': 8}
last_updated = '2026-07-13 7:22pm GMT'
support_threads = 22
support_threads_resolved = 9
added = '2014-01-17'
version = '5.15.2'
```

**確認結果**:

| 主張 | 実測 | 判定 |
|------|------|------|
| 認証不要・無料 | header 無しの GET で HTTP 200 | 確認 |
| `info.results` が hit 数 | `results: 1513` | 確認（B document の「invoice 1,513 件」と完全一致） |
| `active_installs` / `downloaded` / `num_ratings` / `rating` / `last_updated` / `support_threads` / `support_threads_resolved` の実在 | 全 7 field が存在 | 確認 |
| `downloaded` が厳密値（例 23,399,657） | `23399657` | **完全一致** |
| `support_threads` 22 / resolved 9 | `22` / `9` | **完全一致**（B document §3.2(c) の表と一致） |

**`active_installs` の丸め — 独自に検証しました。** `booking calendar` の上位 20 件 + `invoice` 上位 3 件、計 23 plugin で観測された distinct 値:

```
[200, 1000, 2000, 3000, 5000, 7000, 10000, 20000, 30000, 50000, 60000, 70000, 90000, 300000]
```

**すべて有効数字 1 桁でした。反例はゼロです。** B document の「有効数字 1 桁」は正しい記述です。

**B document §3.2(b)(c) の実測値の再現性**（同一 request 内で確認）:

| plugin | B document の値 | 本検証の実測値 | 判定 |
|--------|-----------------|----------------|------|
| ameliabooking | 90,000 / 1,520,291 / 2026-08-10 | 90000 / 1520291 / 2026-08-10 | **完全一致** |
| appointment-hour-booking | 10,000 / 3,613,471 / 2026-08-03 | 10000 / 3613471 / 2026-08-03 | **完全一致** |
| events-manager | 70,000 / threads 54 / resolved 19 / rating 84 | 70000 / 54 / 19 / 84 | **完全一致** |

B document が実際に API を叩いたことは、この一致で裏付けられます。

**軽微な差**: `booking calendar` の `info.results` は B document が 719、本検証が **720** でした。plugin directory は日々増減するため、これは誤りではなく time drift です。**逆に言えば、この種の hit 数は日付を添えないと再現しません。**

---

### 1-2. Atlassian Marketplace distribution API — 実測確認

**実行 command**:

```bash
curl -s 'https://marketplace.atlassian.com/rest/2/addons/com.kanoah.test-manager/distribution'
```

**返り値**:

```
{"bundled":false,"bundledCloud":false,"downloads":175535,"totalInstalls":15954,"totalUsers":-1}
HTTP=200
```

**B document の実測例 `{"downloads":175535,"totalInstalls":15954,"totalUsers":-1}` を数値まで完全再現しました。** 認証 header 無しで HTTP 200 です。

**app key の特定**（B document は key を示していますが、何の app かを書いていません）:

```bash
curl -s 'https://marketplace.atlassian.com/rest/2/addons/com.kanoah.test-manager'
# → name= Zephyr - Test Management and Automation for Jira
#    key= com.kanoah.test-manager
#    vendor= SmartBear
```

**再現性の追加確認**（別 app でも同形式で返ることを確認）:

```bash
curl -s 'https://marketplace.atlassian.com/rest/2/addons/com.innovalog.jmwe.jira-misc-workflow-extensions/distribution'
# → {"bundled":false,"bundledCloud":false,"downloads":364098,"totalInstalls":16766,"totalUsers":-1}
```

**`totalUsers: -1` の意味について**: 2 つの独立した app で一貫して `-1` が返りました。JSON の型としては integer を維持したまま「値なし」を表す sentinel です。null や field 省略ではなく `-1` を返す実装であるため、**集計 script で素朴に合計すると負値が混入します**。B document は「非公開」と解釈していますが、`-1` を「0 人」や有効値として扱わない注意書きが手順書に必要です。なお Atlassian 公式に `-1` の意味を明記した doc は本検証では発見できませんでした（意味の解釈は 確信度: 中）。

**B document が記載していない field**: `bundled` / `bundledCloud` の 2 つが返ります。Atlassian 製品に同梱されている app かどうかの flag と読めます。同梱 app は `totalInstalls` の解釈が変わる（自発的導入ではない）ため、**需要 signal として読む際は `bundled: false` の確認が必要です。** 手順書に追記すべき点です。

---

### 1-3. Stack Exchange API 2.3 — 一部相違

**実行 command と返り値**:

```bash
curl -s --compressed 'https://api.stackexchange.com/2.3/questions?tagged=stripe-payments&site=stackoverflow&filter=total'
# → {"total":13163}

curl -s --compressed 'https://api.stackexchange.com/2.3/questions/unanswered?tagged=stripe-payments&site=stackoverflow&filter=total'
# → {"total":5371}

curl -s --compressed 'https://api.stackexchange.com/2.3/tags/stripe-payments/info?site=stackoverflow'
# → {"items":[{"has_synonyms":true,"is_moderator_only":false,"is_required":false,
#     "count":12549,"name":"stripe-payments"}],
#    "has_more":false,"quota_max":300,"quota_remaining":293}

curl -s --compressed 'https://api.stackexchange.com/2.3/info?site=stackoverflow'
# → ... "quota_max":300,"quota_remaining":291
```

**確認できたこと**:

| 主張 | 実測 | 判定 |
|------|------|------|
| 1 request で件数だけ返る（`filter=total`） | `{"total":13163}` のみ | 確認 |
| 無認証で動作 | key 無しで HTTP 200 | 確認 |
| `quota_max: 300` | `300` | 確認 |
| tag `stripe-payments` 質問総数 12,549 | `count: 12549` | **完全一致** |
| `/questions` filter=total が 13,163 | `13163` | **完全一致** |

**相違点 1 — 「300 req/日」は公式 doc に書かれていません。**

公式 throttle doc（`https://api.stackexchange.com/docs/throttle`、curl で取得、HTTP 200）の原文:

> "If an application does not have an access_token, then the application shares an IP based quota with all other applications on that IP. This quota is based on the key being passed by the applications; it is **the max of the daily request limit for the applications involved, which by default is 10,000**."

> "If an application does have an access_token, then the application is on a distinct user/app pair daily quota (**default size of 10,000**)."

つまり公式が明記している既定値は **10,000** であり、**300 という数字は公式 doc のどこにも現れません**。実測で `quota_max: 300` が返るのは「**`key` parameter すら渡していない場合**」の挙動で、これは undocumented です。

B document §5.1 の「無認証（key 登録で拡大）／`quota_max: 300`/日（実測）」という記述は、実測としては正しく、方向としても正しいのですが、**「無認証」という語が 2 つの別の状態（key 無し / access_token 無し）を混同しています**。正確には:

- key も token も渡さない → **300/日**（実測。公式記載なし）
- key を渡す・token 無し → **10,000/日**（公式記載）
- token あり → user/app pair ごとに **10,000/日**（公式記載）

**相違点 2 — B document が触れていない throttle が 2 つあります。**

> "Every application is subject to an IP based concurrent request throttle. If a single IP is making **more than 30 requests a second**, new requests will be dropped."

> "If an application receives a response with the **backoff** field set, it must wait that many seconds before hitting the same method again. ... Additionally, **all methods (even seemingly trivial ones) may return backoff**."

> "the API employs heavy caching and as such no application should make semantically identical requests more than once a minute."

**手順書上の含意**: 「300 req/日 で数百 niche を評価できる」という B document §8 の記述は quota 上は正しいのですが、**`backoff` field を無視した実装は途中で弾かれます**。一括 script を書く際は `backoff` の遵守が必須です。

**追加の実測**: `quota_remaining` は初回 request 時点で既に 293 でした（300 ではありません）。これは quota が **IP 単位で共有**されていることの直接証拠です。共有 network や CI 環境では 300 を丸ごと使えるとは限りません。

---

### 1-4. VS Code Marketplace `extensionquery` — 一部相違

**実行 command**（POST・特定 header が必要という点は主張どおりでした）:

```bash
curl -s -X POST 'https://marketplace.visualstudio.com/_apis/public/gallery/extensionquery' \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json;api-version=7.2-preview.1' \
  -d '{"filters":[{"criteria":[{"filterType":7,"value":"ms-python.python"}],"pageSize":1,"pageNumber":1}],"flags":914}'
```

**返り値**:

```
HTTP=200
name python pub ms-python
  install         = 231591458.0
  averagerating   = 4.204761981964111
  ratingcount     = 630.0
  trendingdaily   = 0.0012351097027548442
  trendingmonthly = 1.8999242595729784
  trendingweekly  = 0.3859757394478881
  onpremDownloads = 2.0
  updateCount     = 1171717973.0
  weightedRating  = 4.208615314993856
  downloadCount   = 3330894.0
```

**確認できたこと**:

| 主張 | 実測 | 判定 |
|------|------|------|
| **認証不要**（本項の主眼） | Authorization header 無しで HTTP 200。**主張は正しいです** | 確認 |
| POST・特定 header が要る | `Accept: application/json;api-version=7.2-preview.1` と `Content-Type` が必要。GET では動作せず | 確認 |
| `statistics[]` に install / downloadCount / ratingcount / averagerating | 全 4 つ実在 | 確認 |
| `ratingcount` 630 | `630.0` | **完全一致** |

**相違点 1 — `install` と `downloadCount` は別物であり、70 倍違います。**

- `install` = **231,591,458**
- `downloadCount` = **3,330,894**

B document §1 の一覧表は「install（**厳密**）、downloadCount、ratingcount、trending 指標」と並列に列挙しており、§3.1 でも「`downloadCount` / `ratingcount` / `averagerating` / `trendingweekly` 等: 厳密」と一括りにしています。**両者を同種の量として扱うと 2 桁の誤読が起きます。** 需要 signal として使うのは `install` の方です。手順書は「`install` を使い、`downloadCount` は使わない」と明示すべきです。

**相違点 2 — 値の drift。** B document は `install: 231,640,442`、本検証は `231,591,458` でした（約 49,000 減）。同日中の取得にもかかわらず**減少**しています。install が単調増加の累計値ではなく、何らかの再集計を受けている可能性を示します。**「厳密値」という表現は「丸められていない」の意味に限定すべきで、「安定した累計値」の意味に読んではいけません。** 差分比較（成長率の測定）に使う場合は要注意です。

**相違点 3 — 値は JSON の float で返ります**（`630.0`、`231591458.0`）。整数として parse する実装は要注意です。

---

### 1-5. Apple iTunes Lookup API — 実測確認

```bash
curl -s 'https://itunes.apple.com/lookup?id=310633997&country=us'
```

**返り値（抜粋）**:

```
HTTP=200
trackName                            = WhatsApp Messenger
averageUserRating                    = 4.68546
userRatingCount                      = 18381636
averageUserRatingForCurrentVersion   = 4.68546
userRatingCountForCurrentVersion     = 18381636
price                                = 0.0
currentVersionReleaseDate            = 2026-08-10T15:24:27Z
```

**B document の実測例（`4.68546` / `18,381,636`）を完全再現しました。** 認証不要・無料です。判定: **実測確認**。

---

### 1-6. Hacker News API — 一部相違

**Firebase 版（公式）— 実測確認**:

```bash
curl -s 'https://hacker-news.firebaseio.com/v0/maxitem.json'
# → 49254401  HTTP=200
```

公式 README（`https://raw.githubusercontent.com/HackerNews/API/master/README.md`、HTTP 200）の原文:

> "This first iteration will have URIs prefixed with `https://hacker-news.firebaseio.com/v0/` and is structured as described below. **There is currently no rate limit.**"

B document §5.1 の「公式に『現在 rate limit なし』」は **原文どおり**です。判定: **実測確認**。

**Algolia 版 — 未検証**:

```bash
curl -s 'https://hn.algolia.com/api/v1/search?query=micro%20saas&tags=story&hitsPerPage=1'
# → HTTP/1.1 200 OK
#   nbHits 301 nbPages 301 processingTimeMS 6
#   first title: Making money building Shopify micro-SaaS apps
# response header に X-RateLimit-* / Retry-After 系は一切含まれず
```

動作すること・rate limit header が返らないことは確認しました。しかし**公式 doc page `https://hn.algolia.com/api` は JS 描画のみで、raw HTML の本文は 88 文字しかありません**:

```
"Hacker News Search powered by Algolia This page will only work with JavaScript enabled"
```

`rate limit` / `requests per` / `per hour` / `10,000` / `throttl` のいずれの文字列も存在しません。したがって **Algolia 版の rate limit は本検証では確認できませんでした（未検証）**。

**なお、指示書の項目 6 は「Hacker News (Algolia) API が rate limit なし」となっていますが、B document はそのようには書いていません。** B document §5.1 は Firebase 版に「公式に rate limit なし」、Algolia 版に「公式 doc page の本文取得に失敗」（確信度: 中）と**正しく分けて記載しています**。この点で B document に誤りはありません。

---

### 1-7. Google Search Console API — 一部相違

公式 doc `https://developers.google.com/webmaster-tools/v1/searchanalytics/query` を fetch して確認しました。

| B document の記述 | 公式 page の記載 | 判定 |
|-------------------|------------------|------|
| metric: clicks / impressions / ctr / position | 4 metric すべて記載あり | 確認 |
| dimension: query, page, country, device, date, searchAppearance | 記載は **country, device, page, query, searchAppearance, date, `hour`** | **`hour` が抜けています** |
| rowLimit 1〜25,000、既定 1,000 | "Valid range is 1–25,000; Default is 1,000" | **verbatim 一致** |
| 全行を返す保証が無い | "The API is bounded by internal limitations of Search Console and **does not guarantee to return all data rows but rather top ones**" | **verbatim 一致** |
| 費用 無料 | 記載なし（別 page） | — |
| **16 か月保持** | **当該 page に記載がありません** | **一部相違** |
| **anonymized query 除外** | **当該 page に記載がありません** | **一部相違** |

**16 か月・anonymized query について**: B document §2.5 はこの 2 点を `developers.google.com/webmaster-tools/v1/searchanalytics/query`（2026-08-11 確認）の直下に並べて記載していますが、**当該 page からは確認できません**。anonymized query については B document 自身が「確信度: 中 — 公式 blog が一次情報だが本文 fetch に失敗」と注記しており、その注記は誠実です。しかし **16 か月保持の方には注記がなく、出典 page にも記載がありません**。

本検証でも `support.google.com/webmasters/answer/7576553`（Performance report の help）を fetch しましたが、保持期間・anonymized query いずれの記載も確認できませんでした。**判定: 16 か月保持は 未検証。出典の付け替えが必要です。**

---

### 1-8. 補足で実行した endpoint

```bash
curl -s 'https://api.npmjs.org/downloads/point/last-month/react'
# → {"downloads":663454644,"start":"2026-07-11","end":"2026-08-09","package":"react"}  HTTP=200
#   厳密値・認証不要。B document の記述どおり（実測確認）

curl -s 'https://pypistats.org/api/packages/requests/recent'
# → <a href="/api/#etiquette">429 RATE LIMIT EXCEEDED</a>   HTTP=429
#   B document の「429 RATE LIMIT EXCEEDED」を再現（実測確認）

curl -s -D - -o /dev/null 'https://api.github.com/search/repositories?q=invoice&per_page=1'
# → HTTP/1.1 200 OK
#   X-RateLimit-Limit: 10
#   X-RateLimit-Remaining: 9
#   X-RateLimit-Used: 1
#   X-RateLimit-Resource: search
#   B document の「X-RateLimit-Limit: 10, X-RateLimit-Resource: search」を完全再現（実測確認）
```

---

## 2. 料金・条件の検証

「主張値 / 実際の値 / 確認日 / URL」の形式です。確認日はすべて **2026-08-11** です。

| # | 項目 | 主張値 | 実際の値 | 判定 | URL |
|---|------|--------|----------|------|-----|
| 8 | Keywords Everywhere Bronze | $84/年・100,000 credit・1 seat | **$84/年・100,000 credit/年・1 seat**。原文 "1 Credit = 1 Keyword. Credits expire after one year." | **実測確認** | `keywordseverywhere.com/ctl/subscriptions` |
| 8b | 同 Silver/Gold/Platinum | $168 / $480 / $1,440 | **$168 (400,000) / $480 (2,000,000) / $1,440 (8,000,000)** | **実測確認** | 同上 |
| 9 | Ahrefs Starter | ¥4,460/月 | **¥4,460/月** | **実測確認** | `ahrefs.com/pricing` |
| 9b | Ahrefs Lite | ¥19,900/月 | **¥19,900/月** | **実測確認** | 同上 |
| 9c | Ahrefs Standard/Advanced/Enterprise | ¥38,400 / ¥68,900 / ¥230,900 | **¥38,400 / ¥68,900 / ¥230,900**（Enterprise は年契約） | **実測確認** | 同上 |
| 9d | API は Standard 以上 | Standard 以上 | **"API access" は Standard 以上に記載。Lite には無し。Enterprise は "Uncapped API access"** | **実測確認** | 同上 |
| 10 | Semrush Pro | $139.95/月 | **取得不能**（下記） | **動作せず** | `semrush.com` |
| 11 | Ubersuggest Individual | $29/月・$290 買切 | **$29/月は確認。$290 買切・"Individual" 名は確認できず**（下記） | **一部相違** | `app.neilpatel.com/en/pricing` |
| 12 | SE 無認証 quota | 300/日 | **300/日（実測）。ただし公式 doc の既定値は 10,000** | **一部相違** | `api.stackexchange.com/docs/throttle` |

### 2-1. Semrush — 動作せず

**Credentials 不要の単純な HTTP 取得ですら成立しません。**

```bash
curl -s -o /dev/null -w "HTTP=%{http_code}\n" --max-time 20 'https://www.semrush.com/pricing/'
# → HTTP=000, curl rc=6  （rc=6 = Couldn't resolve host）

curl -s -o /dev/null -w "HTTP=%{http_code}\n" --max-time 20 'https://semrush.com/pricing/'
# → HTTP=000, rc=6

# WebFetch 経由: getaddrinfo ENOTFOUND www.semrush.com
```

apex domain・www ともに **DNS 解決不可**でした。B document §2.3 の「公式 pricing page は本調査環境から fetch できませんでした（DNS 解決不可）」という記述は**そのまま再現します**。これは Semrush 側の問題ではなく、**本作業環境の network 制約**である可能性が高いです（同一環境で他の数十 domain は解決しています）。

**判定: 動作せず。** $139.95/月 は本検証でも一次確認できていません。B document が「※公式 page 未取得」「確信度: 中」と明記しているのは適切です。**別環境からの再確認が必要な項目として残します。**

なお副次的な傍証として、Ubersuggest の pricing page 上の競合比較表に "Semrush $139 - $499" という記載を確認しました。ただしこれは**競合他社による記載**であり、一次 source ではありません。

### 2-2. Ubersuggest — 一部相違

```bash
curl -s -o /dev/null -w "HTTP=%{http_code}\n" -A 'Mozilla/5.0 ...' 'https://neilpatel.com/pricing/'
# → HTTP=404   （B document の「公式 page が 404 / 403」を再現）

curl -s -o /dev/null -w "HTTP=%{http_code}\n" 'https://app.neilpatel.com/en/pricing'
# → HTTP=200   ← 生きている page を発見しました
```

`app.neilpatel.com/en/pricing` の内容:

- 3 tier 構成で、**$29/月**（entry）、**$99/月**（popular）、上位 1 tier
- "lifetime plan" として "one-time payment for lifetime access" の記載は**あります**が、**金額の記載を確認できませんでした**
- **"Individual" という plan 名は page 上に存在しません**（tier は価格でのみ表示されています）

| 主張 | 実際 | 判定 |
|------|------|------|
| $29/月 | **確認** | 実測確認 |
| $290 買切 | **金額を確認できず**（lifetime plan の存在のみ確認） | **未検証** |
| plan 名 "Individual" | **該当なし** | **相違** |

B document が「確信度: 低。公式 page で自ら確認してください」と注記していた判断は妥当でした。**ただし、B document は公式 page を 404/403 として諦めていますが、`app.neilpatel.com/en/pricing` は生きています。** 手順書の URL を差し替えるべきです。

---

## 3. F_stock_models.md §4 platform 経済条件の再確認

### 3-1. Shopify App Store — 実測確認

`https://shopify.dev/docs/apps/launch/distribution/revenue-share` から取得した原文:

> "You keep 100% of your first $1,000,000 USD in gross app revenue **earned from January 1, 2025**, and 85% of earnings above that. All billing is subject to a **2.9% processing fee** and applicable sales tax."

> "To access the revenue share plan, you need to register with the Shopify App Store for a **one-time fee of $19 USD per Partner account**."

> "For developers with annual app earnings under $20,000,000 USD per year, these standard rates apply: Lifetime gross app revenue / First $1,000,000 USD **0%** / Above $1,000,000 USD **15%**. Developers who earned **$20,000,000 USD or more** through the Shopify App Store in the prior calendar year, **or who have a gross company revenue of $100,000,000 USD or more**, pay 15% revenue share on all app revenue. The 0% rate on the first $1,000,000 USD doesn't apply. Eligibility is reassessed annually."

F document §4 の記述「生涯 $1M まで 0%、超過分 15%。加えて 2.9% の決済処理手数料。年 $20M 超または企業総収益 $100M 超の開発者は一律 15%。Partner 登録 $19（一度きり）」は、**5 項目すべて原文と一致します。** 判定: **実測確認**。

**§3-5 の「53 日」も確認しました。** changelog `shopify.dev/changelog/update-to-shopifys-app-developer-revenue-share`:

- 投稿日 **2025-04-24**、適用 **2025-06-16**（Partner Program Agreement 更新）→ **53 日**（算術一致）
- "Developers will continue to enjoy a revshare exemption on the first $1 million USD of *lifetime* revenue, and a 15% share on amounts above that."
- "**Earnings before January 1, 2025 do not count toward the $1 million threshold.**"

判定: **実測確認**。

### 3-2. Chrome Web Store — 一部相違

`https://developer.chrome.com/docs/webstore/register` の原文（curl で取得、HTTP 200、131KB）:

> "Before you can publish items on the Chrome Web Store, you must register as a CWS developer and pay a **one-time registration fee**."

**page 全文を検索しましたが、`$5` / `5 USD` という文字列は存在しません。**

| F document の記述 | 実際 | 判定 |
|-------------------|------|------|
| 登録料 **$5（一度きり）** | 「one-time registration fee」とのみ。**金額の記載なし** | **一部相違**（「一度きり」は確認、**金額は未検証**） |
| 手数料なし（課金 rail 自体が存在しない） | 当該 page では言及なし（別 source で確認済みの事実） | — |

`https://developer.chrome.com/docs/webstore/publish` からは、F document の注記部分が**すべて確認できました**:

> "You cannot have more than **20 extensions** published on the Chrome Web Store. There is no such limit on the number of themes. If you reach this limit, you may request a limit increase."

> "The maximum supported file size for an extension package is **2GB**. Zip files larger than 2GB will be rejected."

> "Once the review is complete, you will have up to **30 days** to publish. After that period expires, the staged submission will revert to a draft which will have to be submitted again for review."

**$5 は広く知られた値であり誤りである可能性は低いですが、F document が挙げた URL では確認できません。出典の付け替えが必要です。**

### 3-3. VS Code Marketplace — 実測確認

`https://code.visualstudio.com/api/working-with-extensions/publishing-extension`:

- 有料 extension・revenue share・publisher 登録料の記載は**一切ありません**
- `pricing` field の原文: "Allowed values are: **Free** and **Trial** (case-sensitive). When the pricing property is not specified, the default value is Free."
- sponsor link について: 任意で追加可能、"will allow our users to fund the extensions that they depend on"

F document §4 の「手数料なし（有料 extension 非対応）／無料／課金 rail なし／sponsor link と `pricing: Free/Trial` label のみ」は**完全一致**です。判定: **実測確認**。

### 3-4. Atlassian Marketplace — 実測確認

`https://www.atlassian.com/blog/developer/extended-timelines-for-marketplace-revenue-share-changes`（2025-11-03）:

| 対象 | 実際 | F document | 判定 |
|------|------|-----------|------|
| Connect | **2026-04-01: 15%→20%、2026-10-01: 20%→25%** | 20%（2026-04-01〜）→ 25%（2026-10-01〜） | **一致** |
| Forge | **2026-04-01: 15%→16%、2026-10-01: 16%→17%** | 16%（2026-04-01〜）→ 17%（2026-10-01〜） | **一致** |

`https://www.atlassian.com/blog/development/updates-to-marketplace-revenue-share-2026`（2025-05-05）の原文:

> "**Marketplace partners will receive at least 6 months' notice before changes to standard rates.**"

> Connect: "15% to 20% on **1 January 2026** and will increase to 25% on **1 July 2026**"
> Forge: "15% to 16% on 1 January 2026, and increasing to 17% on 1 July 2026"
> "partners will pay **0% revenue share for Forge apps** that meet eligibility requirements, **up to $1 million lifetime in Forge revenue**"

F document §3-6 の「Atlassian は『standard rate 変更の 6 か月以上前に告知する』と明記しています」は、**原文 verbatim で裏付けられました。** 当初日程（2026-01-01 / 2026-07-01）→ 延期後（2026-04-01 / 2026-10-01）という経緯、Forge 生涯 $1M 0% incentive も一致します。判定: **実測確認**。

**補足**: 「6 か月前告知」の明文は **2025-05-05 の blog にあり、2025-11-03 の延期告知 blog にはありません**。F document は §3-6 の中で 2 つの blog の内容を混在させているため、**どちらの blog が出典かを明記すべきです**。

### 3-5. WordPress.org — 実測確認

`https://developer.wordpress.org/plugins/wordpress-org/detailed-plugin-guidelines/` の原文:

> (1) "All code, data, and images — anything stored in the plugin directory hosted on WordPress.org — must comply with the **GPL or a GPL-Compatible license**."

> (2) "Plugins **may not contain functionality that is restricted or locked, only to be made available by payment or upgrade**."

> (3) "**Functionality may not be disabled after a trial period or quota is met.** In addition, plugins that provide sandbox only access to APIs and services are also trial, or test, plugins and not permitted."

> (4) "Plugins that act as an **interface to some external third party service** (e.g. a video hosting site) **are allowed, even for paid services**." （ただし license 検証のみを目的とする service は不可、storefront は実体のある機能が必要）

> (5) "Attempting to **upsell** the user on ad-hoc products and features **is acceptable**, provided it falls within bounds of guideline 11 (hijacking the admin experience)."

F document §4 の 5 項目はすべて原文と一致します。判定: **実測確認**。「freemium の pro 版は別 plugin として外部配布する構造が必須」という導出も、(2)(3) から論理的に妥当です。

### 3-6. Apple App Store — 実測確認

`https://developer.apple.com/support/enrollment/`:

> "The Apple Developer Program annual fee is **99 USD** and the Apple Developer Enterprise Program annual fee is 299 USD, in local currency where available."
> "**accredited educational institutions worldwide can enroll in the Apple Developer Program with a fee waiver**"

`https://developer.apple.com/app-store/small-business-program/`:

> 手数料 **15%** / 閾値 "**1 million USD** in the prior calendar year"
> "If a participating developer surpasses the 1 million USD threshold in the current calendar year, the **standard commission rate will apply to future sales**."
> "If a developer's proceeds fall below the 1 million USD threshold in a future calendar year, they can **re-qualify for the 15% commission the year after**."

F document §4 の「標準 30%。Small Business Program で 15%（前年の proceeds が $1M 未満）。年内に $1M を超えると残りの期間は 30%、翌々年に再資格化の可能性。Apple Developer Program 年 $99（教育機関は waiver あり）」は**すべて一致**します。判定: **実測確認**。

**軽微な注記**: 「標準 30%」という数字自体は上記 2 page には明示されていません（"standard commission rate" とのみ）。周知の値ですが、厳密には別 page（App Store Connect の手数料 page）が出典です。

### 3-7. Google Play — **相違**

`https://support.google.com/googleplay/android-developer/answer/112622` の原文（table 行を verbatim で確認）:

**US/EEA/UK、2026-06-30 以降**:

| 区分 | 公式の料率 |
|------|-----------|
| 新規 install（同日以降に初回 install/update）— subscription | 10% + 5% billing fee |
| 新規 install — その他 | 10% + 5% billing fee |
| **既存 install（同日より前に初回 install/update）— subscription** | **10% + 5% billing fee** |
| **既存 install — その他** | **"Other transactions (existing installs) \| 25% + 5% billing fee * \| OR; 20% for external web links"** |

**F document §4 の「既存 install 20%+5%」は誤りです。**

- Google Play Billing 経由の既存 install 非 subscription は **25% + 5% billing fee**
- **20%** は **external web link 経由**の料率であり、しかも **billing fee は付きません**（"20% for external web links"）

F document は 2 つの異なる決済経路の料率を取り違えた上で、external web link 用の 20% に billing fee 5% を足すという、**公式のどの行にも存在しない組み合わせ**を記載しています。5 pt の過小評価であり、既存 user への課金を前提とする model では意味のある差です。

**Play Games Level Up / Apps Experience program 参加時**は既存 install が "15% + 5% billing fee" または "15% for external web links" に下がります。この program の存在は F document に記載がありません。

その他の項目は一致しました:

| F document | 公式 | 判定 |
|-----------|------|------|
| 他市場: 年最初の $1M は 15%、超過 30% | "15%" / "30% for earnings in excess of $1M (USD) revenue" | 一致 |
| subscription は一律 15% | "15% for automatically renewing subscription products" | 一致 |
| $25（一度きり） | 当該 page には記載なし（別 page） | 未検証 |
| policy 変更は最低 30 日の compliance 猶予 | 当該 page には記載なし（policy announcement page が出典） | 未検証 |
| 韓国・India の alternative billing は 4% 減額 | 当該 page で未確認 | 未検証 |

### 3-8. Figma Community — 一部相違

`https://help.figma.com/hc/en-us/articles/12067637274519-About-selling-Community-resources` の原文:

> "When you make a sale on the Community, Figma collects a **flat 15% fee** to cover transactional and operational costs."
> "**We are not approving new creators to sell paid files on Community at this time.**"
> 最低価格 **$2.00** / 出金可能は "**30 US business days** after a sale is made" / "a maximum of **one cash out per week**"

F document の 15% / $2 / 30 US 営業日 / 週 1 回 / 新規承認停止は**すべて一致**します。

**相違点: payout 対応国数。**

F document は §4 と §5-1 の 2 か所で「**payout 89 か国**（日本を含む）」と記載しています。本検証で page 本文の国名 list を機械的に抽出・計数したところ:

```
FIGMA payout country count = 77
Japan in list: True
last few: ['Turkey', 'United Arab Emirates', 'United Kingdom', 'United States', 'Uruguay', 'Vietnam']
```

- 本検証の parse: **77 か国**
- 同一 page を別経路（WebFetch の要約）で読んだ場合: **86 か国**
- F document: **89 か国**

**89 という値は、どちらの読み方でも再現しませんでした。** 77 と 86 の差は parse 手法の違い（複合国名の分割など）に起因すると考えられ、正確な計数には慎重な再確認が要りますが、**いずれにせよ 89 は現行 page の記載と整合しません。**

**なお「日本を含む」という点は list 中に `Japan` を確認済みで、正しいです。** 実務上の結論（日本から payout は可能だが新規売り手承認が停止中）は変わりません。**数字だけを直すべき箇所です。**

### 3-9. Obsidian Community — 未検証

本検証では時間の都合により `obsidian.md/blog/future-of-plugins/` を確認していません。**未検証**として残します。

---

## 4. F_stock_models.md §3 platform 事例の日付・数値

### 4-1. Twitter/X API 2023 — 実測確認

TechCrunch 2023-02-08（`techcrunch.com/2023/02/08/twitter-says-the-basic-tier-of-its-api-will-cost-100-per-month/`）:

| F document | 記事の記載 | 判定 |
|-----------|-----------|------|
| 2023-02-08 に basic tier 月 $100 と発表 | 記事日付 **February 8, 2023**、"$100 per month for the basic tier of API" | 一致 |
| 無料 access 終了は当初 2023-02-09 | "**February 9, 2023**" | 一致 |
| その後 2023-02-13 に延期 | "extended this deadline to **February 13**" | 一致 |
| 実質約 5 日 | 02-08 → 02-13 = **5 日** | 算術一致 |
| 無料枠は単一の認証済み user token で月 1,500 post の write only | "post up to **1,500 Tweets per month** for a **single authenticated user token**, including Login with Twitter"（write-only） | 一致 |

判定: **実測確認**。ただし出典は TechCrunch であり二次 source です。当時の @TwitterDev の一次投稿は本検証環境から取得できませんでした。

### 4-2. Reddit API 2023 — 実測確認（二次 source 経由）

**一次 source（Christian Selig 本人の r/apolloapp 投稿）は取得できませんでした**:

```bash
# WebFetch: Claude Code is unable to fetch from www.reddit.com
curl -sL 'https://www.reddit.com/r/apolloapp/comments/144f6xm.json'
# → HTTP=403
```

二次 source（MacRumors 2023-05-31）で確認した数値:

| F document | 記事の記載 | 判定 |
|-----------|-----------|------|
| 50M requests あたり $12,000 | "Reddit plans to charge **$12,000 for 50 million API requests**" | 一致 |
| 直前月の実績 70 億 requests | "Last month, Apollo made **seven billion requests**" | 一致 |
| 月 $1.7M / 年 $20M | "**$1.7 million per month**" / "**$20 million per year**" | 一致 |
| Imgur には 50M calls で月 $166 | "pays ... Imgur **$166 per month for 50 million API calls**" | 一致 |

**「2023-06-08 告知 → 2023-06-30 停止 = 22 日」について**: 停止日 6/30 は複数 source で一貫しています。告知日 2023-06-08 は、取得できなかった投稿（URL slug が `apollo_will_close_down_on_june_30th`）の投稿日に依存します。**算術（6/8 → 6/30 = 22 日）は正しいですが、告知日そのものの一次確認はできていません。**

判定: 金額 4 項目は **実測確認（二次）**、日付は **未検証（一次未到達）**。

### 4-3. Chrome Manifest V3 timeline — 実測確認

`https://developer.chrome.com/docs/extensions/develop/migrate/mv2-deprecation-timeline` の原文と F document の表を照合しました。

| F document | 公式原文 | 判定 |
|-----------|---------|------|
| 2022-01 CWS が Public/Unlisted の新規 MV2 受付停止 | "**January 2022**: Chrome Web Store stopped accepting new Manifest V2 extensions with visibility set to 'Public' or 'Unlisted'." | 一致 |
| 2022-06 非公開 MV2 の新規受付も停止 | "**June 2022**: ... visibility set to 'Private'." | 一致 |
| 2024-06-03 管理画面に警告 banner | "**June 3rd 2024**" 警告 banner + Featured badge 喪失 | 一致 |
| 2024-10-09 stable で無効化を段階開始 | "**October 9th 2024**: disabling installed extensions ... in Chrome stable"（再有効化は可能） | 一致 |
| 2025-03-31 全 channel で既定無効化（一時再有効化は可能） | "**March 31st 2025**: All users on all channels ... disabled by default"（再有効化可） | 一致 |
| 2025-07-24 Chrome 138 で再有効化も不可 | "**July 24th 2025**: With Chrome 138 ... users can no longer turn them back on." | 一致 |
| 2026-08-31 CWS から削除 | "**August 31st 2026**: All remaining Manifest V2 extensions are removed from the Chrome Web Store" | 一致 |

**7 行すべて一致しました。** 判定: **実測確認**。

### 4-4. Unity Runtime Fee — 実測確認

`https://unity.com/blog/unity-is-canceling-the-runtime-fee` の原文（curl 取得、HTTP 200）:

> "A message to our community: Unity is canceling the Runtime Fee"
> "**MATT BROMBERG / UNITY TECHNOLOGIES — President and CEO of Unity — Sep 12, 2024**"
> "After deep consultation with our community, customers, and partners, we've made the decision to **cancel the Runtime Fee for our games customers, effective immediately**. Non-gaming Industry customers are not impacted by this modification."

F document の「2024-09-12、Unity は CEO Matt Bromberg 名義で Runtime Fee の全面撤回を発表しました（game 顧客に対し即時）」は**完全一致**です。判定: **実測確認**。

**F document が省略した具体値**（同 blog にあり、記載する価値があります）:

> "**Unity Pro: An 8% subscription price increase to $2,200 USD annually per seat.** Unity Pro will be required for customers with more than $200,000 USD of total annual revenue and funding."
> "**Unity Enterprise: A 25% subscription price increase.**" Enterprise は年間収益・資金調達 $25M 超が必須。
> いずれも **effective January 1, 2025**。

F document は「代わりに subscription 価格の引き上げが行われました」と定性的に書いていますが、**Pro +8%（$2,200/seat/年）／Enterprise +25%** という具体値を入れられます。

**未検証**: 発表側（2023-09-12、告知から約 110 日）の一次 source は本検証で未確認です。当時の blog post は撤回に伴い削除されている可能性があります。

---

## 5. 手順書（B_quant_sources.md §5・§8 ほか）の修正箇所

優先度順に、具体的な修正内容を示します。

### 5-1. 必ず直すべきもの（数値・事実の誤り）

| # | 場所 | 現在の記述 | 修正案 |
|---|------|-----------|--------|
| **1** | **F §4 Google Play 行** | 「US/EEA/UK は 2026-06-30 から: ... その他は新規 install 10%+5%、**既存 install 20%+5%**」 | 「既存 install は **Google Play Billing 経由 25%+5%**、**external web link 経由 20%（billing fee なし）**」に修正。加えて Play Games Level Up / Apps Experience 参加時は 15%+5% に下がる旨を追記 |
| **2** | **F §4 Figma 行・§5-1 Figma 行（2 か所）** | 「payout 対応 **89 か国**（日本を含む）」 | 「payout 対応国 list に日本を含む（**国数は要再計数。本検証の parse では 77**）」。**89 は現行 page で再現しません** |
| **3** | **B §5.1・§8-3・§9 の Stack Exchange 行** | 「無認証 300 req/日、key 登録で拡大」 | 「**key も token も渡さない場合 300/日（実測。公式 doc に記載なし）／key を渡せば 10,000/日（公式）／token ありは user·app pair ごとに 10,000/日（公式）**」と 3 状態に分解。加えて **`backoff` field の遵守が必須**（全 method が返し得る）、**同一 IP からの 30 req/秒 超で drop**、**同一 request は 1 分に 1 回まで**を追記 |
| **4** | **B §1・§3.1 の VS Code 行** | `install` と `downloadCount` を並列に列挙 | 「**需要 signal に使うのは `install`。`downloadCount` は別量で 70 倍小さい**（実測: 231,591,458 vs 3,330,894）」と明記。`downloadCount` を一覧表の代表 metric から外す |

### 5-2. 出典を付け替えるべきもの

| # | 場所 | 問題 | 修正案 |
|---|------|------|--------|
| 5 | **B §2.5** | 「16 か月保持」を searchAnalytics/query の doc 下に置いているが、**当該 page に記載なし** | 出典を別 page に付け替えるか、anonymized query と同様に「確信度: 中・一次未確認」と注記する |
| 6 | **F §4 Chrome Web Store 行** | 登録料 **$5** が引用元 `developer.chrome.com/docs/webstore/register` に**記載なし**（"one-time registration fee" のみ） | 金額を確認できる page に出典を差し替えるか、「一度きり（金額は当該 page 未記載）」に改める |
| 7 | **F §3-6** | 「6 か月以上前に告知」の明文は **2025-05-05 の blog** にあり、§3-6 が主に引用している 2025-11-03 の blog には**ありません** | どちらの blog が出典かを行内で明示する |
| 8 | **B §2.3 Ubersuggest** | 「公式 page が 404 / 403」で諦めている | **`https://app.neilpatel.com/en/pricing` は HTTP 200 で生きています。** URL を差し替えた上で「$29/月は確認、**$290 買切と "Individual" という plan 名は現行 page に無し**」に改める |

### 5-3. 追記すべきもの（実測で分かった落とし穴）

| # | 場所 | 追記内容 |
|---|------|---------|
| 9 | **B §8-1・付録 WordPress** | `curl` で URL に直接 `request[...]` を書く場合、**`-g`（`--globoff`）が無いと exit 3 で失敗**します。付録の `--data-urlencode` 形式なら不要です。この注記が無いと手順書の readers が最初の一手で詰まります |
| 10 | **B §8-2・§3.1 Atlassian** | distribution API は `bundled` / `bundledCloud` も返します。**同梱 app は `totalInstalls` が自発的導入を意味しないため、`bundled: false` の確認が必要**です。また `totalUsers: -1` は sentinel なので、**集計時に合計すると負値が混入**します |
| 11 | **B §3.1 VS Code 行** | 「厳密」の語義を「丸められていない」に限定してください。**同日中の再取得で install が約 49,000 減少**しており（B 231,640,442 → 本検証 231,591,458）、単調増加の累計値ではありません。**差分による成長率測定には使えません** |
| 12 | **B §3.2(e) の判定式** | `info.results` は日々変動します（`booking calendar` が B 719 → 本検証 720）。**判定式の閾値を扱う際は取得日を必ず併記**してください |
| 13 | **B §5.1 Hacker News 行** | Firebase 版の「rate limit なし」は公式 README で verbatim 確認済みです。**Algolia 版の公式 doc page は JS 描画のみで本文が存在しない**（raw HTML 88 文字）ため、恒久的に fetch では確認できません。「取得失敗」ではなく「**page に本文が無い**」と書くべきです |
| 14 | **B §2.5 GSC dimension** | dimension に **`hour`** が追加されています。列挙を更新してください |
| 15 | **F §3-7 Unity** | 「代わりに subscription 価格の引き上げ」に具体値を追加できます: **Unity Pro +8%（$2,200 USD/seat/年）、Unity Enterprise +25%、いずれも 2025-01-01 適用** |
| 16 | **B §2.3 Semrush・F 参考文献** | `semrush.com` は **apex / www ともに DNS 解決不可**（curl rc=6）でした。B document の注記は再現します。**本環境固有の network 制約である可能性が高い**ため、「Semrush 側の問題」と読まれないよう明記し、別環境での再確認を宿題として残してください |

### 5-4. 直す必要がないもの（本検証で裏付けられた記述）

以下は**手を入れないでください**。実測で完全に裏付けられました。

- WordPress API の field 一覧・`active_installs` 有効数字 1 桁・`downloaded` 厳密・`support_threads` 厳密（23 plugin で反例ゼロ）
- Atlassian distribution API の数値（`175535` / `15954` / `-1` を byte 単位で再現）
- iTunes Lookup の `4.68546` / `18381636`
- Stack Exchange の `12549` / `13163`、`filter=total` が 1 request で件数のみ返すこと
- GitHub search の `X-RateLimit-Limit: 10` / `X-RateLimit-Resource: search`
- pypistats の 429
- Keywords Everywhere の全 4 plan の価格と credit 数、"1 Credit = 1 Keyword"
- Ahrefs の全 6 plan 価格と「API は Standard 以上」
- Shopify の 0%/15%・生涯 $1M・2025-01-01 起算・2.9%・$19・$20M/$100M 例外・53 日
- Atlassian の Connect 20%→25% / Forge 16%→17% と「6 か月前告知」の明文
- WordPress.org guideline の 5 項目（GPL 必須・課金 lock 禁止・trial 停止禁止・外部 SaaS 可・upsell 可）
- Apple の $99/年・教育機関 waiver・SBP 15%・前年 $1M・翌々年再資格化
- VS Code Marketplace の有料非対応・`pricing: Free/Trial`・sponsor link
- Chrome MV2 deprecation timeline の 7 行すべて
- Chrome Web Store の 20 item 上限・2GB・30 日
- Twitter API 2023 の 4 数値（$100 / 02-09 / 02-13 / 1,500 post）
- Reddit の 4 数値（$12,000/50M・70 億 requests・$1.7M/月・Imgur $166）
- Unity 撤回（2024-09-12 / Matt Bromberg / 即時）

---

## 6. 本検証で確認できなかった項目

| 項目 | 理由 | 必要な対応 |
|------|------|-----------|
| Semrush の公式料金 | `semrush.com` が apex / www ともに DNS 解決不可（curl rc=6） | **別 network 環境から再確認** |
| Ubersuggest の lifetime 価格（$290?） | `app.neilpatel.com/en/pricing` に lifetime plan の存在は記載があるが金額を確認できず | browser で当該 page を開いて確認 |
| Reddit Apollo 告知日 2023-06-08 の一次 source | reddit.com が本環境から取得不可（WebFetch 拒否 / curl 403） | 別環境または web archive |
| Unity Runtime Fee 発表側（2023-09-12） | 撤回に伴い原 blog が削除された可能性 | web archive |
| GSC の 16 か月保持の一次 source | searchAnalytics/query にも Performance report help にも記載なし | Search Console help の別 page を探す |
| Chrome Web Store 登録料 $5 の一次 source | register / publish いずれの page にも金額記載なし | Developer Dashboard の登録 flow で確認 |
| HN Algolia の rate limit | 公式 doc page が JS 描画のみで本文が存在しない | Algolia 側の doc か HN Search の repository |
| Obsidian Community の条件 | 時間の都合により未着手 | 次回 |
| Google Play $25 登録料・30 日 compliance 猶予・韓国/India 4% 減額 | service fee page 以外が出典 | 該当 page を個別に確認 |
| Figma payout 対応国の正確な数 | parse 手法により 77 / 86 と割れた（**89 ではない**ことのみ確定） | 慎重な再計数 |

---

**検証日: 2026-08-11**
**検証実施: research team V3（実測検証）**
