# B: 定量的な需要 signal の data source と、その読み方

確認日: **2026-08-11**（料金・API 仕様はすべてこの日に確認した値です）
調査範囲: 個人（月数千円〜数万円）が実際に access できる data source の棚卸し、各々の bias・限界・正しい読み方

---

## 0. この文書の前提と結論の要旨

### 0.1 なぜ「category の需要」でなく「入口単位の需要」なのか

過去に 5 市場 35,995 件を全走査して category 間の分散 ≈ 0 だった件は、統計的に見て当然の結果です。理由は本文書 §7.1 で扱う **search query の power law** にあります。

- 個々の query 需要は power law（Zipf 則に近い形）で分布します。
- power law 分布を category 単位で平均すると、平均値は分布の裾（tail）に支配され、しかも category ごとの裾の形はほぼ同じになります。
- つまり **「category 平均」は設計上ほぼ定数になる量**であり、そこに分散を期待するのは誤りです。分散は category **内**の query 単位にしか存在しません。

したがって本文書は一貫して「**特定の入口（検索語・機能・場面）1 つに対して、何人がいま困っているか**」を測る道具として data source を評価します。

### 0.2 結論の要旨

| # | 結論 | 確信度 |
|---|---|---|
| 1 | search volume は「単一の真値」が存在しない推定量です。tool 間の乖離は誤差でなく**定義の違い**であり、複数 tool の平均を取っても真値に近づきません | 高 |
| 2 | Google Trends の**低頻度 query は使い物になりません**。同一 query の再取得間の相関が 0.496 まで落ちる実測があります（§2.2） | 高 |
| 3 | **Marketplace の install 数は、search volume より遥かに信頼できる需要 signal** です。推定値でなく実測値であり、しかも「金を払う直前まで行った人の数」だからです | 高 |
| 4 | ★の低さを不満の proxy にするのは**部分的にしか妥当でありません**。rating inflation により、同じ不満が年を追うごとに高い★に化けます（§4） | 高 |
| 5 | 個人にとって最も費用対効果が高いのは **WordPress plugin API / VS Code Marketplace API / Atlassian Marketplace API / Stack Exchange API / Hacker News API** の 5 つで、いずれも**無料・認証不要・rate limit も実用範囲**です | 高 |
| 6 | 公的統計（e-Stat・BLS・Census・Eurostat）は無料で API があり品質も高いが、**入口単位の需要測定には粒度が粗すぎて使えません**。用途は「市場規模の分母」と「顧客数の上限」の確認に限定すべきです | 高 |

---

## 1. 総合一覧表

（詳細は各章。費用は 2026-08-11 時点、税抜・表示通貨のまま）

| 名前 | 何が測れるか | 取得方法 | 費用 | 更新頻度 | 主な bias | 使いどころ | 確信度 |
|---|---|---|---|---|---|---|---|
| Google Keyword Planner | 検索語の月間平均検索数（広告費なしでは range） | Google Ads 管理画面 / Google Ads API | 無料（ただし exact 値には広告出稿が事実上必要） | 月次 | 広告目的の keyword grouping、丸め、bucket 化 | 検索語の桁数を掴む最初の一手 | 高 |
| Google Trends | 相対的な検索関心の時系列（0-100） | Web UI / 非公式 library / 公式 API（alpha, 申請制） | 無料 | 日次〜 | **sampling 誤差**、正規化、privacy 由来の 0 埋め | 季節性と「増えているか減っているか」だけ | 高 |
| Google Search Console | **自サイトの実測** impression / click / position | 公式 API（Search Analytics） | 無料 | 日次 | 自サイト分のみ、anonymized query 欠落、16 か月保持 | 仮説検証の唯一の真値。landing page を先に作る前提 | 高 |
| Ahrefs | search volume, keyword ideas, 競合 traffic 推定 | Web UI / API（Standard 以上） | Starter ¥4,460/月、Lite ¥19,900/月〜 | 月次 | clickstream panel の外挿。自社実測で median 乖離 49.52% | 予算が許すなら keyword の広がりを見る | 中 |
| Semrush | 同上 | Web UI / API（別料金） | Pro $139.95/月〜（※公式 page 未取得） | 月次 | 同上＋自社に有利な自社研究 | 同上 | 中 |
| Keywords Everywhere | search volume, CPC, 12 か月 trend | browser 拡張 / API | Bronze $84/年（100,000 credit） | 月次 | 元 data source 非公開 | **個人予算では最有力**。1 credit = 1 keyword | 高 |
| Ubersuggest | search volume, keyword ideas | Web UI | Individual $29/月・$290 買切（※二次情報） | 月次 | 精度検証情報が乏しい | 予算最下限の選択肢 | 低 |
| **WordPress plugin API** | active_installs（丸め）、downloaded（**厳密**）、rating、num_ratings、**support_threads** | `api.wordpress.org` GET、認証不要 | **無料** | 日次 | WP 生態系のみ。install は 1 桁丸め | **競合の薄さ判定に最良**。§3.2 | 高 |
| **VS Code Marketplace API** | install（**厳密**）、downloadCount、ratingcount、trending 指標 | `extensionquery` POST、認証不要 | **無料** | 準 real-time | developer 母集団に偏る | 開発者向け tool の需要測定 | 高 |
| **Atlassian Marketplace API** | downloads・totalInstalls（**厳密**）、review、価格 | `marketplace.atlassian.com/rest/2/` GET、認証不要 | **無料** | 日次 | Jira/Confluence 導入企業のみ | **B2B・有料前提**の需要が測れる稀な場所 | 高 |
| Chrome Web Store | user 数（**強い丸め**）、★、review 数 | HTML scraping のみ（公開 API 無し） | 無料（自作 scraper） | 週次 | 「週間 active user」で丸め幅が大きい | 桁の把握のみ。差分比較には不適 | 高 |
| Shopify App Store | ★（JSON-LD）、review 数 | HTML scraping | 無料 | 不明 | install 数は非公開 | 競合の★と review 文面のみ | 中 |
| Notion template gallery | ratingValue / reviewCount（JSON-LD） | HTML scraping | 無料 | 不明 | 販売数非公開 | 補助的 | 中 |
| Figma Community | 公開 API 無し、HTML も JS 描画で raw には数値無し | headless browser が必要 | 無料（手間大） | 不明 | 取得困難 | 優先度低 | 中 |
| Salesforce AppExchange | listing 情報 | HTML（動的）、公開 API 無し | 無料（手間大） | 不明 | 取得困難 | 優先度低 | 低 |
| Apple App Store | averageUserRating・userRatingCount（**厳密**） | iTunes Lookup API、認証不要 | **無料** | 日次 | download 数は非公開 | mobile 隣接領域の確認 | 高 |
| G2 / Capterra | review 本文、機能別 rating | **scraping は ToS 違反** | 閲覧は無料 | 随時 | rating inflation、vendor 誘導 review | **手動閲覧に限定**。§4.4 | 高 |
| Trustpilot | review 本文 | Data Solutions（商談） | 要見積 | 随時 | 星の分布が二極化しやすい | 個人予算では不適 | 中 |
| **Stack Overflow / Stack Exchange API** | tag 別質問数、未回答数、質問文全文 | `api.stackexchange.com/2.3/`、認証不要 | **無料**（無認証 300 req/日、key 登録で拡大） | 準 real-time | 2023 以降 LLM により投稿減少 | **「解決されていない問題」の直接証拠** | 高 |
| Stack Exchange Data Explorer / BigQuery | 同上を SQL で | SEDE Web / BigQuery public dataset | SEDE 無料、BigQuery は月 1 TiB 無料・以降 $6.25/TiB | 四半期〜 | 同上 | 大量集計が必要なとき | 中 |
| **Hacker News (Firebase API)** | 全 item（story/comment）、score、時刻 | `hacker-news.firebaseio.com/v0/`、認証不要 | **無料・rate limit 記載無し** | real-time | 技術者・英語圏に強く偏る | 「Show HN」の反応で需要の温度感 | 高 |
| Hacker News (Algolia Search) | 全文検索 | `hn.algolia.com/api/v1/` | 無料 | real-time | 同上 | 過去の類似 product 探索 | 中 |
| GitHub API | issue 本文、star、更新停止 repo | `api.github.com`、認証推奨 | 無料（無認証 60 req/時、PAT 5,000 req/時、search は 10 req/分） | real-time | OSS 利用者に偏る | 「既存 OSS の未解決 issue」＝ 需要 | 高 |
| GH Archive | GitHub 全 public event の履歴（2011-02-12〜） | JSON.gz 直 DL / BigQuery | 無料（BigQuery 分は従量） | 毎時 | 同上 | 経時変化を見るとき | 高 |
| Reddit Data API | subreddit の投稿・comment | OAuth 必須 | 非商用 100 QPM 無料 / 商用は $0.24 per 1,000 calls（※二次情報） | real-time | subreddit 文化に強く依存 | 「困りごとの生の言葉」収集 | 中 |
| Discord / Slack | 会話 | **scraping は ToS 違反**（Discord 明示） | — | — | — | **自ら参加して読む**以外に手段無し | 高 |
| e-Stat（日本政府統計） | 各種公的統計 | 公式 API（要 user 登録） | **無料** | 統計により異なる | 粒度が粗い、公表 lag | 市場規模の分母 | 高 |
| 総務省 通信利用動向調査 | 世帯・企業の IT 利用率 | e-Stat / CSV | 無料 | 年次 | 標本調査（世帯 40,592・企業 6,040） | 日本の普及率の根拠 | 高 |
| 経済産業省 電子商取引市場調査 | EC 市場規模・EC 化率 | PDF / Web | 無料 | 年次 | 推計値、公表は約 1 年 lag | 市場規模の分母 | 高 |
| US BLS API | 雇用・物価等の時系列 | `api.bls.gov/publicAPI/v2/` | 無料（無登録は制限あり） | 月次 | 米国のみ | 米国市場の分母 | 高 |
| US Census API | 1,795 dataset（2026-08-11 時点） | `api.census.gov` | 無料 | 各種 | 同上 | 同上 | 高 |
| Eurostat API | EU 統計 | `ec.europa.eu/eurostat/api/dissemination/` | 無料・認証不要 | 各種 | EU のみ | EU 市場の分母 | 高 |
| npm downloads API | package の DL 数（**厳密**） | `api.npmjs.org/downloads/` | 無料 | 日次 | CI による水増しが混入 | JS 生態系の需要 | 高 |
| PyPI (pypistats) | package の DL 数 | `pypistats.org/api/` | 無料（**rate limit 厳しめ**） | 日次 | 同上 | Python 生態系の需要 | 中 |

---

## 2. 検索需要

### 2.1 Google Keyword Planner

**公式が認めている限界**（Google Ads Help, `support.google.com/google-ads/answer/3022575`, 2026-08-11 確認）:

> "Your search volume statistics are rounded. This means that when you get keyword ideas for multiple locations, the search volumes might not add up as you'd expect."

> "Keep in mind that historical stats like average monthly searches are only shown for exact matches."

**押さえるべき点:**

| 論点 | 実態 | 確信度 |
|---|---|---|
| 広告費なしでの精度劣化 | 「Avg. monthly searches」列が `1K – 10K` のような range 表示になります。1,300 回/月 と 9,400 回/月 が同じ帯に落ちるため、**入口単位の優先順位付けには使えません** | 高 |
| exact 値の解放条件 | Google は閾値を公開していません。二次情報では日額 $5-10 程度の出稿で解放されるとする報告が複数ありますが、**公式の裏付けはありません** | 中（現象）/ 低（金額） |
| bucket 化 | Keyword Planner の値は連続値でなく**離散的な bucket** に丸められています。Authoritas 社が 6,000 万 keyword を分析し「約 60 個の既定 bucket」と報告しています（最下位 bucket は 0, 10, 20, 30…、最上位は 7,480,000）。これは vendor blog ですが、実 data に基づく分析であり内容は再現可能です | 中 |
| bucket の副作用 | 実需要が動いても bucket をまたがない限り値が動きません。**「3 か月値が変わらない」は安定ではなく解像度不足**です | 中 |
| keyword grouping | Google は広告目的で類似語を統合します。「請求書 作成」「請求書 作成 無料」が同一 volume で返ることがあり、**入口の細かさが潰れます** | 中 |

**正しい読み方:** Keyword Planner は「この入口は 3 桁か 4 桁か 5 桁か」を判定する道具です。それ以上の分解能を期待してはいけません。

### 2.2 Google Trends — 最も誤用されている data source

**公式の説明**（Google Trends Help, `support.google.com/trends/answer/4365533`, 2026-08-11 確認）:

> "Each data point is divided by the total searches of the geography and time range it represents to compare relative popularity."

> "While only a sample of Google searches are used in Google Trends, this is sufficient because we handle billions of searches per day."

> "To protect your privacy, we incorporate statistical noise that includes small and random fluctuations that don't represent actual search behavior."

> "[Google Trends] is not a scientific poll and shouldn't be confused with polling data."

**査読・preprint による定量的な限界:**

| 論点 | 実測値 | 出典 |
|---|---|---|
| **同一 query の再取得間の相関** | 同じ term・同じ期間・同じ地域で 3 回取得した series 間の相関が **Brazil で 0.496 / 0.545 / 0.564、US で 0.655 / 0.516 / 0.575**。対象は「GDP Growth」という比較的 popular な語 | Medeiros & Pires (2021), arXiv:2104.03065, Table 1 |
| **改善策** | 7 sample の平均どうしなら相関は **US 0.95 / Brazil 0.92** まで上昇。「多数 sample を取って平均せよ」が著者の結論 | 同上 |
| 低頻度語ほど悪化 | 「検索頻度が低い語ほど、また Google 利用者が少ない地域ほど、sample 間の差は大きくなる」 | 同上 |
| **0 埋め（zero-inflation）** | privacy 閾値により低 volume が 0 に落ちる。個別 keyword で **30-99% が 0**、99% 超のものもある。特に state / city 粒度で深刻。さらに **2024 年初頭に 0 の割合が 40% 増加** | arXiv:2504.07032v2 |
| cache の挙動 | 同日中の同一 query は server cache により同一結果。**UTC 0 時に cache が reset され新しい sample が引かれる** | 同上 |
| data 品質の一般論 | 「Google Trends の精度不足は sampling 過程に由来する」 | Cebrián & Domenech (2023), *Applied Economics Letters* 30(6), 811-815 |
| 一貫性の回復手法 | 必要な sample 数を決める尺度を提案 | Cebrián & Domenech (2024), *Technological Forecasting and Social Change* 202 |

**副業 micro SaaS 文脈での含意（重要）:**

「入口単位の需要」を測ろうとすると、対象は必然的に**低頻度の具体的な語**になります。そしてそれこそが Google Trends が最も壊れる領域です。

> **Google Trends は、あなたが本当に測りたい語では機能しません。**

Google Trends の正しい用途は 3 つに限定してください。

1. **季節性の把握**（振幅が大きい語のみ）
2. **数年 scale の増減方向**（絶対値でなく符号のみ）
3. **2 語以上の相対比較**（同一 request 内で比較した場合のみ。別 request の値は正規化基準が違うため比較不能）

**公式 Trends API（alpha）:** 2025-07-24 に発表され、2026-08-11 時点でも**申請制の alpha のまま**です（`developers.google.com/search/apis/trends`）。直近 5 年の rolling window、日次/週次/月次/年次集計、国・sub-region 対応。UI と違い **0-100 に再 scale されない一貫した scale** を返すため、複数 request の結合・比較が可能になります。これは UI の最大の欠点を潰す改善ですが、**現時点で個人が確実に使える前提で計画してはいけません**。

### 2.3 有償 SEO tool の実費用（2026-08-11 公式 page 確認）

**Ahrefs**（`ahrefs.com/pricing`、日本からの access のため JPY 表示）:

| plan | 月額 | 内容 | API |
|---|---|---|---|
| Starter | ¥4,460 | 機能限定 | 無し |
| Lite | ¥19,900 | 5 project, 750 tracked keyword | 無し |
| Standard | ¥38,400 | 20 project, 2,000 tracked keyword | 有り |
| Advanced | ¥68,900 | 50 project, 5,000 tracked keyword | 有り |
| Enterprise | ¥230,900 | 年契約、API 無制限 | 有り |

無料の **Ahrefs Keyword Generator**（`ahrefs.com/keyword-generator`）は account 無しで keyword idea と volume 推定を返します。「80 億 query の database」「clickstream data による推定」と公式が明記しています。日次上限の記載は公式 page にありません（確信度: 中）。

**Keywords Everywhere**（`keywordseverywhere.com/ctl/subscriptions`）— **個人予算では最有力**:

| plan | 年額 (USD) | credit/年 | seat |
|---|---|---|---|
| Bronze | $84 | 100,000 | 1 |
| Silver | $168 | 400,000 | 3 |
| Gold | $480 | 2,000,000 | 10 |
| Platinum | $1,440 | 8,000,000 | 20 |

公式 FAQ: "One credit gets you the volume, cpc, competition & 12 month trend data for one keyword."

→ **Bronze $84/年（月 700 円相当）で 100,000 keyword** を評価できます。月数千円という予算制約に対して、これが最も直接的な解です。ただし **volume の元 data source を公式が明示していません**（確信度: 高＝明示が無いこと自体が確認済み）。

**Semrush:** 公式 pricing page は本調査環境から fetch できませんでした（DNS 解決不可）。二次情報では Pro $139.95 / Guru $249.95 / Business $499.95（月払い）。**確信度: 中**。個人予算を大きく超えるため、実務上は検討外です。

**Ubersuggest:** Individual $29/月・$290 買切という情報が広く流通していますが、確認できた source が affiliate 汚染された比較記事のみでした。**確信度: 低。公式 page で自ら確認してください。**

### 2.4 search volume は実需要とどれだけ相関するか

ここは affiliate 汚染が最も激しい領域です。**入手できた研究はすべて tool vendor 自身によるもの**であり、独立した査読研究は見つかりませんでした。以下は利害関係を明示した上で提示します。

| 研究 | 実施主体 | 内容 | 結果 | 利害 |
|---|---|---|---|---|
| Semrush volume study (2022) | **Semrush**（当事者） | 匿名化 GSC data を真値とし、10,000 keyword で各 tool の近さを比較（US, 2021Q4-2022Q1） | Semrush が最も近かった割合が最大（33% で完全一致との報告） | **自社が 1 位という結論。強い利害** |
| Ahrefs traffic estimation study | **Ahrefs**（当事者） | 1,635 site の US organic traffic 推定 vs GSC | **自社の median 乖離 49.52%** | 自社に不利な数字を出しており、その分だけ信頼可 |

**この 2 つから引き出せる、利害に依存しない結論:**

> Ahrefs が**自社に不利な形で** median 乖離 49.52% を公表しているという事実は、「この種の推定は概ね 2 倍/半分のずれを含む」ことの下限として使えます。search volume 推定を「±50% の量」として扱ってください。

**含意:** 2 つの入口の volume 推定が 2 倍差なら、それは**差があると言えません**。10 倍差なら言えます。**入口の選別には桁単位の差しか使ってはいけません。**

### 2.5 Google Search Console — 唯一の実測値

`developers.google.com/webmaster-tools/v1/searchanalytics/query`（2026-08-11 確認）:

- 返す metric: clicks / impressions / ctr / position
- dimension: query, page, country, device, date, searchAppearance
- rowLimit: 1〜25,000（既定 1,000）、`startRow` で paging
- 費用: 無料
- 制約: 「内部的な制限があり、全行を返すことは保証しない」と公式が明記

**限界:** 自サイト分のみ、data 保持は 16 か月、そして **anonymized query**（少数 user しか出していない query）は表から除外されます（**確信度: 中** — Google 公式 blog "A deep dive into Search Console performance data filtering and limits" (2022-10) が一次情報ですが、本調査では本文 fetch に失敗しました）。

**それでも GSC が決定的に重要な理由:** これは推定でなく**実測**です。§8 の実行順序で述べる通り、GSC を回せる状態を作ること自体が需要調査の最終形です。

---

## 3. Marketplace 内の data

**この章が本文書で最も重要です。** search volume が「±50% の推定量」であるのに対し、marketplace の install 数は**実測値**であり、しかも「無料であれ有料であれ、導入という行動を取った人の数」です。行動 data は表明選好 data より遥かに強い証拠です。

### 3.1 各 store が公開する数値の定義と丸めの実態（自ら API を叩いて確認）

以下はすべて 2026-08-11 に本調査で実際に request し、返り値を確認した結果です。

| store | 数値 | 丸め | 認証 | 確信度 |
|---|---|---|---|---|
| **WordPress plugin directory** | `active_installs` | **強い丸め**（実測: 600 / 900 / 1,000 / 2,000 / 5,000 / 30,000 / 300,000 / 1,000,000 — 有効数字 1 桁） | 不要 | 高（実測） |
| 同上 | `downloaded` | **厳密**（例: 23,399,657） | 不要 | 高（実測） |
| 同上 | `rating` | 0-100 の整数（★ではない） | 不要 | 高（実測） |
| 同上 | `num_ratings` / `support_threads` / `support_threads_resolved` | **厳密** | 不要 | 高（実測） |
| **VS Code Marketplace** | `install` | **厳密**（例: 231,640,442） | 不要 | 高（実測） |
| 同上 | `downloadCount` / `ratingcount` / `averagerating` / `trendingweekly` 等 | **厳密**（averagerating は float） | 不要 | 高（実測） |
| **Atlassian Marketplace** | `downloads` / `totalInstalls` | **厳密**（例: downloads 175,535, totalInstalls 15,954） | 不要 | 高（実測） |
| 同上 | `totalUsers` | **`-1`（非公開）** | 不要 | 高（実測） |
| **Chrome Web Store** | user 数 | **強い丸め**（実測: `16,000,000 users`）。公開 API 無し、HTML から抽出するしかない | — | 高（実測） |
| 同上 | 定義 | 「**週間** active user」＝ 過去 7 日以内に Chrome を開いた導入者。累計 install 数ではない | — | 中（二次情報） |
| **Shopify App Store** | `ratingValue`（JSON-LD） | 小数（例: 4.9）。`reviewCount` は raw HTML に無し。install 数は非公開 | — | 中（実測: ratingValue のみ確認） |
| **Notion template gallery** | `ratingValue` / `reviewCount`（JSON-LD） | 実測: `"ratingValue":4.975`, `"reviewCount":40`。販売数は非公開 | — | 高（実測） |
| **Figma Community** | 公開 API 無し。listing HTML（750KB）に install 数の平文なし＝ JS 描画 | headless browser 必須 | — | 高（実測） |
| **Salesforce AppExchange** | 動的描画。安定した公開 endpoint を確認できず | — | — | 低 |
| **Apple App Store** | `averageUserRating` / `userRatingCount` | **厳密**（例: 4.68546 / 18,381,636）。iTunes Lookup API、認証不要 | 不要 | 高（実測） |

**Chrome Web Store の丸め幅**（二次情報、確信度: 中）: 10 万未満は 1,000 単位、10 万〜100 万は 10,000 単位、100 万〜1,000 万は 100,000 単位、1,000 万超は「10M+」で頭打ち。

> **重要:** Chrome Web Store の丸め幅は、あなたが狙う規模（数千〜数万 user）では **user 数の 10-30%** に達します。つまり **Chrome Web Store の数値で「成長しているか」を判定することはできません**。桁を見るためだけに使ってください。

### 3.2 install 数 / review 数 / 更新日から「需要」と「競合の薄さ」をどう読むか

#### (a) review 数を需要の proxy にしてはいけない

2026-08-11 に VS Code Marketplace API から実測した ratio です。

| extension | install | rating 数 | rating 数 / install |
|---|---:|---:|---:|
| Python (ms-python) | 231,640,442 | 630 | **0.00027%** |
| Prettier | 70,705,524 | 491 | 0.00069% |
| Code Spell Checker | 17,928,848 | 311 | 0.00173% |
| Draw.io Integration | 4,053,810 | 161 | 0.00397% |
| vscode-pdf | 12,939,797 | 127 | 0.00098% |

**読み方:**

- review を書く率は **1 万人に 1 人未満**で、しかも extension 間で **15 倍近くばらつきます**。
- したがって **review 数から install 数を推定することはできません**（比例定数が安定しない）。
- 逆に言えば **review 数が 2 桁の product が、100 万 user を抱えている可能性は十分にあります**。「review が少ない＝ niche ＝ 参入余地あり」という読みは**誤りです**。

#### (b) WordPress plugin directory の「二重指標」を使う（本文書独自の読み方）

WordPress は **install（丸め）と downloaded（厳密）の両方**を返す稀な store です。この 2 つの比を取ると、丸めを跨いで意味のある情報が出ます。

2026-08-11 実測（検索語 `booking calendar` / `gdpr consent` より抜粋）:

| plugin | active_installs | downloaded | **DL / install** | 更新日 | 解釈 |
|---|---:|---:|---:|---|---|
| wp-consent-api | 200,000 | 967,380 | **4.8** | 2026-06-18 | 比が低い＝ 新しい or 更新が少ない。**現役の install がほぼ全て** |
| ameliabooking | 90,000 | 1,520,291 | 16.9 | 2026-08-10 | 健全 |
| appointment-hour-booking | 10,000 | 3,613,471 | **361** | 2026-08-03 | 比が極端に高い＝ **かつて大量に導入されたが現在 1 万しか残っていない**。離脱が起きている領域 |
| uk-cookie-consent | 80,000 | 2,954,782 | 36.9 | 2026-01-09 | 更新が 7 か月停滞、rating 72（低い）＝ **放置されつつある競合** |

> `downloaded / active_installs` は**更新回数 ＋ 離脱**の合成量です。同じ niche 内で比べたとき、この比が突出して高く、かつ更新日が古く、かつ rating が低い plugin は「**多くの人が入れて、多くの人が捨てた**」ことを意味します。これは**需要は実在したが既存解が満たしていない**という、最も価値の高い signal です。

#### (c) support_threads の未解決率（最も過小評価されている signal）

WordPress plugin API は `support_threads` と `support_threads_resolved` を**厳密な整数で**返します。2026-08-11 実測:

| plugin | active_installs | threads | resolved | **未解決率** | rating |
|---|---:|---:|---:|---:|---:|
| events-manager | 70,000 | 54 | 19 | **65%** | 84 |
| complianz-gdpr | 1,000,000 | 52 | 26 | 50% | 94 |
| yith-woocommerce-subscription | 7,000 | 2 | 0 | 100%（n 小） | **60** |
| woocommerce-gateway-stripe | 700,000 | 61 | 55 | 10% | **62** |
| woocommerce-pdf-invoices-packing-slips | 300,000 | 22 | 9 | 59% | 100 |

**読み方:**

- `support_threads` は**直近 2 か月の値**です（WordPress.org の仕様）。つまり **rate（流量）であり、stock ではありません**。install 数で割ると「1 万 install あたり何件の困りごとが今月発生しているか」になり、**store を跨いで比較可能な唯一の不満指標**になります。
- ★や rating と違い、**support thread は inflation しません**。人は誰かを傷つけまいとして★を甘くしますが（§4）、困っているときに質問を書くかどうかにその力学は働きません。
- `woocommerce-gateway-stripe`（700,000 install, rating **62**, 未解決率 10%）は特に示唆的です。**大量に使われ、support は回っているのに、評価は低い。**「動くが満足していない」＝ 代替品の余地がある典型です。

#### (d) 更新日の読み方

| 更新日 | 読み | 注意 |
|---|---|---|
| 6 か月以上停止 ＋ install 数千以上 ＋ rating 低 | **最良の参入 signal**。需要は証明済み、供給が劣化 | 「動いているから更新不要」な単機能 tool もあるため、issue / support thread と併読 |
| 週次更新 ＋ install 数十万 | 資金の入った competitor | 個人で正面から戦うべきではない |
| 更新頻繁 ＋ install 数百 | 作者が需要を勘違いしている可能性 | **その niche に需要が無い証拠**として使えます |

#### (e) 「競合の薄さ」の判定式

単一の指標で決めてはいけません。以下の 4 条件のうち **3 つ以上**を満たす niche を候補にしてください。

1. 検索 hit 数が数百件以下（WordPress API の `info.results`。実測例: `invoice` 1,513 件 / `booking calendar` 719 件 / `subscription billing` 857 件）
2. 上位 8 件の中に **install 1 万以上かつ rating 80 未満**の plugin が存在する
3. 上位 8 件の中に **6 か月以上更新停止**のものが 2 件以上ある
4. `support_threads / active_installs` が同 category 中央値の 2 倍以上

### 3.3 store 別の適性

| store | 個人 micro SaaS 向きか | 理由 |
|---|---|---|
| **Atlassian Marketplace** | **◎** | **有料 app が当然の生態系**。導入者は企業で、決裁が通る。しかも downloads / totalInstalls が**厳密値**で公開されており、需要が直接読めます。個人にとって最も見落とされている場所です |
| **WordPress plugin directory** | **◎** | data 品質が最良（§3.2）。ただし**無料文化が強く、有料化の壁が高い**。freemium 前提の設計が必要 |
| **VS Code Marketplace** | ○ | data は厳密だが、**開発者は金を払わない層**として有名。install は伸びても収益化が難しい |
| **Shopify App Store** | ○ | 顧客が EC 事業者＝ 支払意欲が高い。ただし **install 数が非公開**で需要測定が困難。★と review 文面のみ |
| Chrome Web Store | △ | 丸めが強く需要測定に不向き。収益化 model も弱い |
| Figma / Notion / AppExchange | △ | data 取得が困難。優先度を下げてください |

---

## 4. Review mining と rating inflation

### 4.1 ★の低さを不満の proxy にするのは妥当か — 結論から

**部分的にしか妥当ではありません。** 具体的には:

- **同一時点・同一 store 内での相対比較** → 妥当（確信度: 高）
- **時系列比較（今年の★ vs 3 年前の★）** → **不当**（確信度: 高）
- **★の絶対水準を「満足度」と読む** → **不当**（確信度: 高）
- **store を跨いだ★の比較** → 不当（確信度: 中）

### 4.2 根拠: Filippas, Horton & Golden (2022)

Filippas, A., Horton, J. J., & Golden, J. M., "Reputation Inflation," *Marketing Science*, 2022. 以下は論文本文（working paper 版, 2021-10-03）から直接抽出した数値です。

| 発見 | 数値 |
|---|---|
| 対象 | **5 つの online marketplace**。うち 1 つ（online labor market）で transaction 単位の詳細 data による分解を実施 |
| 満点比率 | 近年、**評価された worker の 85% が満点**。かつ「満点を受け取る割合は **6 年間で 33% → 85%**」に上昇 |
| 平均★の推移 | **2007 年初頭 3.74 → 2016 年 5 月 4.85** |
| **inflation 寄与** | 「6 年間の score 上昇の **50% 超が inflation による**」。point estimate は **67.7%**（別 sample では 56.6%） |
| **同じ言葉の★が年々上がる** | 受け取った仕事を **"terrible"** と書いた employer が付ける公開 score は、**2008 年 平均 1.4 星 → 2015 年 平均 2.4 星** |
| **私的 feedback との乖離** | 私的評価では **"Probably Not" 8.3% ＋ "Definitely Not" 6.6% ＝ 約 14.9% が否定的**。同時期の**公開**評価で 3 星以下は **4% 未満**（Fig 1a 実測: 約 3.8%） |
| 方向性 | 私的 feedback の平均は**低下**していたのに、同じ取引の公開 feedback の平均は**上昇**していた |
| 下限性 | 手法は「代替指標も inflation する場合、下限を与える」設計。**67.7% は控えめな値** |

**"terrible" と書いた人の★が 1.4 → 2.4 に上がった**という発見が、本論点の核心です。

> **不満の量が同じでも、★は年々甘くなります。** ★を不満の proxy にすると、**古い product ほど不満が多く見え、新しい product ほど満足に見える**という系統誤差が入ります。「★が低い競合を探す」戦略は、実際には「**古い competitor を探す**」戦略になっています。

なお論文は他 marketplace の同種の状況も引用しています: eBay の中央値 seller は positive feedback 100%、10 percentile でも 98.21%（Nosko & Tadelis 2015）。UberX Chicago は 2017 年初頭の乗車の約 90% が満点（Athey et al. 2019）。

### 4.3 では何を見るべきか

★の水準でなく、**inflation の影響を受けない量**を見てください。

| 使うべき指標 | 理由 | 取得元 |
|---|---|---|
| **★の分布形（特に 1★ の絶対数）** | 平均は inflation するが、「わざわざ 1★ を付けた人」は強い不満の存在を意味します。WordPress API は `ratings` として 1〜5 の内訳を返します | WP API / iTunes Lookup |
| **support thread の未解決率** | §3.2(c)。社会的圧力が働かない | WP API |
| **GitHub の open issue と最終 comment 日** | 「報告されたが放置されている」＝ 不満の stock | GitHub API |
| **Stack Overflow の未回答質問数** | 同上。しかも「回避策すら存在しない」ことの証拠 | Stack Exchange API |
| **review 本文の中の "wish"/"can't"/"doesn't"/「〜できない」** | ★でなく言葉。§4.5 | 各 store |
| **同一 cohort 内の相対★** | 同時期に公開された product 同士なら inflation 量が近く、比較が成立します | — |

### 4.4 G2 / Capterra / Trustpilot の法的制約（重要）

**G2 の Terms of Use**（`legal.g2.com/terms-of-use`, 2026-08-11 確認）は scraping を明示的に禁じています:

> "you will not, without G2's express prior written consent: (a) access, collect, copy, scrape, harvest, cache, index, store, archive, or otherwise extract any content or data from the Site"

> 使用手段として "automated, programmatic, or mechanical means (including robots, spiders, crawlers, scrapers, headless browsers, data-mining tools, or similar technologies)" を列挙

さらに、抽出した content を "train, test, validate, fine-tune, evaluate, or improve any machine-learning model, generative AI system" に使うことも禁じています。集計値（"Derived Data"）についても "You obtain no rights in or to any Derived Data" と明記。

**Discord** も同様に、bot / scraper による message の mine・scrape を Developer Policy で禁じています（確信度: 中 — 一次 URL の fetch に失敗、二次情報による）。

**Capterra**（Gartner Digital Markets 運営）の ToS は本調査で本文を取得できませんでした（確信度: 低）。同種の禁止条項がある前提で扱ってください。

**Trustpilot** は "Data Solutions" として review database への access を提供していますが、価格は公開されておらず商談が必要です（`developers.trustpilot.com`, 2026-08-11 確認）。個人予算では現実的ではありません。

> **実務上の結論:** G2 / Capterra / Trustpilot は「**自分で読む**」に限定してください。自動収集は ToS 違反であり、IP block・法的措置が明記されています。副業の初手で法的 risk を負う理由はありません。
>
> 代わりに **§3 の marketplace API（すべて認証不要・公開・利用制限なし）と §5 の community API** を使ってください。data 品質でも劣りません。

### 4.5 review から unmet need を抽出する手法（学術的裏付けのある方法）

Timoshenko, A. & Hauser, J. R., "Identifying Customer Needs from User-Generated Content," *Marketing Science*, 38(1), 1-20, 2019.

**この論文の要点:**

- 従来の customer need 抽出は interview / focus group に依存していました。
- UGC（review 等）でも、**professional analyst が experiential interview で抽出した need と同等の insight が得られる**ことを示しました（対象: oral care 製品）。
- ただし **UGC の大半は非情報的か重複**であり、そのまま読むのは非効率です。著者らは (1) CNN で非情報的 sentence を除去、(2) 密な sentence embedding を clustering して重複を除去、という 2 段の絞り込みを提案しています。

**個人が今日できる形に落とすと:**

1. 対象 niche の competitor 5-10 件について、全 review を収集（**API がある store のみ。G2 等は手動**）
2. 3★以下 + 4★以上の両方を対象にする（4-5★ の review にも "wish it could…" が大量に含まれます — これは rating inflation の裏返しで、**甘い★を付けた人ほど本文に本音を書きます**）
3. 「〜できない」「〜がない」「〜だったら」「wish」「can't」「doesn't support」「workaround」を含む文だけ抽出
4. embedding で clustering し、cluster ごとに**代表 1 文だけを読む**（Timoshenko & Hauser の手法の簡易版）
5. cluster の**大きさ**でなく**出現 product 数**で優先順位を付ける（1 product にしか出ない不満はその product 固有の bug、複数 product に出る不満は**構造的な unmet need**）

step 5 が肝です。単一 product の review だけを読むと bug 報告に埋もれます。

---

## 5. Community signal

### 5.1 取得可否・費用・合法性の一覧

| source | API | 認証 | 費用 | rate limit（2026-08-11 実測 or 公式） | 合法性 | 確信度 |
|---|---|---|---|---|---|---|
| **Hacker News (公式 Firebase)** | `hacker-news.firebaseio.com/v0/` | 不要 | 無料 | **公式に「現在 rate limit なし」** | 公開 API | 高 |
| Hacker News (Algolia) | `hn.algolia.com/api/v1/` | 不要 | 無料 | 公式 doc page の本文取得に失敗 | 公開 API | 中 |
| **Stack Exchange API 2.3** | `api.stackexchange.com/2.3/` | 不要（key 登録で拡大） | 無料 | **無認証で `quota_max: 300`/日（実測）** | 公開 API、CC BY-SA | 高 |
| Stack Exchange Data Explorer | Web SQL | 要 SE account | 無料 | query 実行時間制限 | 公開 | 中 |
| Stack Overflow BigQuery public dataset | BigQuery | 要 GCP | **月 1 TiB 無料、以降 $6.25/TiB** | — | 公開 | 中 |
| **GitHub REST API** | `api.github.com` | 推奨 | 無料 | **無認証 60 req/時、PAT 5,000 req/時、GitHub App 5,000〜12,500 req/時、search は無認証 10 req/分（実測: `X-RateLimit-Limit: 10`, `X-RateLimit-Resource: search`）** | 公開 API | 高 |
| **GH Archive** | JSON.gz / BigQuery | 不要 | 無料 | — | 公開 | 高 |
| Reddit Data API | `oauth.reddit.com` | **OAuth 必須** | 非商用 無料 / 商用 $0.24 per 1,000 calls（最低 commit 有り） | 認証済 100 QPM / 無認証 10 QPM（10 分平均） | 要 ToS 遵守 | 中 |
| Pushshift | **終了** | — | — | — | — | 高 |
| Product Hunt API | GraphQL | 要 token | 無料 | 15 分あたり complexity 6,250 / その他 endpoint 450 req | 公開 API | 中 |
| Discord | Bot API | — | — | — | **message の scrape / mine を Developer Policy で禁止** | 中 |
| Slack | Web API | workspace 単位 | — | — | 参加している workspace のみ | 中 |

### 5.2 Reddit — 2023 年以降に何が変わったか

**確信度: 中**（redditinc.com / support.reddithelp.com がいずれも本調査環境から fetch 不可のため、二次情報に依存しています。**実装前に必ず公式 Data API Terms を自ら確認してください**）。

- **2023-06-01** に有償化が施行されました。
- **無料枠:** OAuth 認証済み client で **100 QPM**（query per minute）。無認証は **10 QPM**。制限は user 単位でなく **OAuth client ID 単位**で、10 分の移動平均で評価されるため短時間の burst は許容されます。
- **商用枠:** $0.24 per 1,000 calls。最低 commit が存在するとの情報があります（月 $12,000 規模＋ 約 5,000 万 call の割当）。**個人が商用枠に入る選択肢は事実上ありません。**
- **Pushshift は終了しました。** 2023 年以前は Reddit の全履歴を一括取得できましたが、現在は不可能です。過去 data を前提とした調査設計は成立しません。

**個人にとっての現実解:** 非商用・100 QPM の範囲で、狙う subreddit の投稿を定期取得して local に貯めるところまでです。100 QPM は 1 request あたり 100 件取得できるので、**1 分間に 1 万投稿**まで読めます。個人規模なら十分です。

### 5.3 Stack Overflow — 「解決されていない問題」の直接証拠

2026-08-11 実測（`api.stackexchange.com/2.3/`, 無認証）:

| query | 結果 |
|---|---|
| tag `stripe-payments` の質問総数 | **12,549** |
| tag `stripe-payments` の質問数（`/questions` filter=total） | **13,163** |
| 全文検索 `"stripe webhook"` の hit 数 | **1,574** |
| 無認証 quota | **300 req/日** |

**読み方:**

- `/2.3/tags/{tag}/info` の `count` は**その tag が付いた質問の総数**であり、**厳密値**です。
- `/2.3/questions/unanswered` と `/2.3/questions` の差が「**未解決の問題の stock**」です。
- **`filter=total` を使うと 1 request で件数だけ返る**ため、300 req/日 でも数百 niche を評価できます。これが最も効率的な使い方です。

**重大な注意（確信度: 中）:** 2023 年以降、LLM の普及により Stack Overflow の投稿数は大きく減少しています。したがって:

- **絶対数の時系列比較は成立しません**（減少が需要減なのか投稿行動の変化なのか区別できません）
- **同一時点での tag 間の相対比較は依然として有効です**
- 「最近の質問が少ない」を「問題が解決された」と読んではいけません

### 5.4 GitHub — 未解決 issue が最も直接的な需要 signal

- 無認証 60 req/時 は実用外です。**Personal Access Token を取れば 5,000 req/時**になります（無料）。
- **search API だけは別 quota** で、実測で **10 req/分**（無認証）。認証時は 30 req/分（公式 doc）。
- **GH Archive**（`gharchive.org`）は 2011-02-12 以降の全 public event を毎時 JSON.gz で公開しており、BigQuery public dataset としても利用可能です。**月 1 TiB の BigQuery 無料枠内で相当な分析ができます。**

**読み方（優先順）:**

1. **「star が多い ＋ 最終 commit が古い ＋ open issue が多い」repo** — 需要が証明済みで供給が止まった領域。最良の signal
2. **「同じ issue が複数 repo に立っている」** — 構造的な unmet need（§4.5 step 5 と同じ論理）
3. star 数単独 — **最弱の signal**。star は「後で見る」の bookmark であり、利用でも支払意欲でもありません

### 5.5 Hacker News

公式 API（`hacker-news.firebaseio.com/v0/`）は **認証不要・rate limit の記載なし・無料**で、全 item（story, comment, job, Ask HN, poll）と user profile を返します。`/maxitem` と `/updates` により差分取得も可能です。

**使い道:** 「Show HN」への反応（score と comment の内容）は、**同種の product を作った人が実際にどう受け止められたか**の記録です。search volume が測れない新奇な入口ほど、ここが唯一の証拠になります。

**bias:** 技術者・英語圏・SF Bay Area 文化に極端に偏ります。**HN で受けたものが一般市場で受ける保証はまったくありません。** 逆方向（HN で無反応でも一般市場では需要がある）も頻繁に起きます。

---

## 6. 公的・準公的統計

### 6.1 日本

| source | 内容 | 取得 | 費用 | 更新 |
|---|---|---|---|---|
| **e-Stat（政府統計の総合窓口）** | 政府統計全般 | 公式 API（要 user 登録） | **無料** | 統計により異なる |
| 総務省 通信利用動向調査 | 世帯・企業の情報通信 service 利用状況 | e-Stat / CSV | 無料 | 年次（統計法に基づく一般統計調査、平成 2 年〜） |
| 経済産業省 電子商取引に関する市場調査 | BtoB / BtoC EC 市場規模、EC 化率 | PDF（`meti.go.jp`） | 無料 | 年次（平成 10 年度〜） |
| 総務省 情報通信白書 | 各種 data 集 | Web / CSV | 無料 | 年次 |

**e-Stat API の利用規約**（`e-stat.go.jp/api/terms-of-use`, 2026-08-11 確認）:

- 第 7 条: 「利用者は、本機能を利用したサービスを提供する場合には、別途定める方法により、本機能を利用している出所等を明示するものとします」→ **出典明記が義務**
- 第 8 条: 「短時間における大量のアクセスその他本機能の運用に支障を与える行為」を禁止
- 第 5 条 3 項: 「アクセス制限をかけることがあります」→ **数値上限は非公開**
- 第 10 条: 正確性等の保証なし
- **商用利用を明示的に禁じる条項はありません**（確信度: 中 — 明示の禁止が無いことを確認、明示の許可も無い）

**直近の公表状況（2026-08-11 時点）:**

- 令和 7 年 通信利用動向調査: 令和 7 年 8 月末時点の調査。世帯 40,592 世帯・企業 6,040 企業が対象。結果は情報通信統計 database および e-Stat に CSV で公開
- 令和 6 年度 電子商取引に関する市場調査: **令和 7 年（2025 年）8 月 26 日公表**

> **注意:** 経産省 EC 市場調査は「令和 6 年度」の結果が「令和 7 年 8 月」公表です。**約 1 年の lag** があります。2026-08 時点で最新のものも、実態としては 2024 年度の数字です。

### 6.2 海外（すべて 2026-08-11 に実際に request し、動作を確認）

| source | endpoint | 認証 | 動作確認 |
|---|---|---|---|
| **US BLS** | `api.bls.gov/publicAPI/v2/timeseries/data/{seriesID}` | 無認証で動作（登録すると上限拡大） | **✓ 成功**（2026 年 6 月までの月次値を返却） |
| **US Census** | `api.census.gov/data.json` ほか | 無認証で動作 | **✓ 成功**（**1,795 dataset** を確認） |
| **Eurostat** | `ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{dataset}` | 不要 | **✓ 成功**（JSON-stat 形式、2026-04-17 更新） |

いずれも**無料・認証不要（または無料登録）**で、個人事業 regime で何の障害もなく使えます。

### 6.3 公的統計の正しい使いどころ（と、使ってはいけないところ）

**使ってよい:**

| 用途 | 例 |
|---|---|
| **TAM の分母** | 「日本の従業員 100 人未満の企業数」から顧客数の上限を出す |
| **前提の検証** | 「その業種の企業は本当に PC を業務で使っているか」を通信利用動向調査で確認 |
| **地域・年齢の構成比** | 対象 segment の絶対数 |
| **市場が縮小していないかの確認** | EC 化率の推移 |

**使ってはいけない:**

> 公的統計から「どの入口に需要があるか」を導くことは**できません**。粒度が業種・世帯・製品 category 単位であり、あなたが測りたい「特定機能・特定場面」より 3-4 桁粗いためです。
>
> **これは §0.1 で述べた過去の失敗と同じ構造です。** 公的統計を入口選定に使うと、再び「category 間の分散 ≈ 0」に到達します。公的統計は**入口を決めた後に、その入口の分母を確認する**ために使ってください。順序を逆にしないでください。

---

## 7. 統計的な落とし穴

### 7.1 power law 分布 — 過去の失敗の直接の原因

**確認できた事実:**

| 事実 | 出典・確信度 |
|---|---|
| Google の検索の **約 15% は、これまで一度も検索されたことのない新規 query** | Google 自身が複数回表明（2007 年は 25%、以降 15% で安定）。確信度: 中（Google 公式表明の二次報道） |
| Keyword Planner の volume は約 60 個の離散 bucket に丸められている | Authoritas 社が 6,000 万 keyword を分析。vendor blog だが実 data 分析。確信度: 中 |
| 大多数の keyword は月 10 検索以下 | 二次情報。確信度: 低（数値は tool の database 構成に依存するため、そのまま信用すべきではありません） |

**統計的な含意（ここは data でなく論理です。確信度: 高）:**

1. power law（あるいは log-normal）分布では、**平均は代表値になりません**。平均は少数の巨大値に引きずられ、中央値と桁で乖離します。
2. **category を跨いで平均を取ると、power law の指数がどの category でも似ているため、平均もまた似た値になります。** これが「分散 ≈ 0」の正体です。data の問題でも tool の問題でもなく、**集計操作そのものの問題**です。
3. 正しい扱いは以下です:
   - 平均でなく **log 変換した上での分布**を見る
   - あるいは **上位 k 件の値そのもの**を見る（category 内の頭）
   - **category を単位にした集計をそもそも行わない**

> **実務上の指針:** 「category ごとに指標を集計して比較する」設計は、power law が支配する領域では**必ず失敗します**。次回は「**個々の入口を、集計せずに、そのまま順位付けする**」設計にしてください。

### 7.2 sampling 誤差（Google Trends 固有）

§2.2 の通り、同一 query の再取得間の相関が **0.496** まで落ちます。

**対処法（Medeiros & Pires 2021 の提案）:**

- **7 sample 以上を別々に取得して平均する**（相関 0.92-0.95 まで回復）
- 取得は **UTC 0 時をまたいで**行う（同日中は cache が返るため、同じ sample しか得られません）
- **popular な語では問題は小さい**が、あなたが測りたい入口は定義上 popular ではありません

**やってはいけないこと:** 1 回だけ取得した Trends の grafik を見て「この語は伸びている / 落ちている」と判断すること。相関 0.5 の系列で傾きを論じても意味がありません。

### 7.3 seasonality

- Google 自身が「Web traffic is influenced by seasonality, current events, and a number of other factors」と明記しています（Keyword Planner Help）。
- **Keyword Planner の「Avg. monthly searches」は 12 か月平均**です。季節性が強い語では、繁忙期の実値が平均の 3-5 倍になることは珍しくありません。
- **判断すべきこと:**
  - 「年 1 回だけ需要が立つ入口」は micro SaaS として成立しにくい（月額課金の解約率が跳ねます）
  - 逆に**確定申告・年末調整・決算**のような予測可能な季節性は、供給が薄くなりやすい狙い目でもあります
- **最低限:** 12 か月の推移を見ずに volume の平均値だけで判断しないでください。Keywords Everywhere は 1 credit で 12 か月 trend も返すため、これは追加費用なしで実行できます。

### 7.4 keyword cannibalization / grouping

- Google Keyword Planner は広告目的で類似 keyword を統合します。その結果、**異なる意図の語が同じ volume で返ります**。
- tool 間でも grouping 方針が異なります（Semrush は Google と同様に grouping、Moz / Ahrefs は grouping しない、という報告があります。確信度: 低 — 出典が Semrush 側の記述）。
- **含意:** 「A の volume 1,000、B の volume 1,000」を見て「同じ需要」と読むのは危険です。**片方は 5 語の統合値、片方は単一語かもしれません。**
- **対処:** volume でなく **SERP（実際の検索結果）を見る**こと。異なる意図の語は SERP の構成が変わります。これは無料で、しかも tool の推定より確実です。

### 7.5 tool 間の推定値の乖離

| 比較 | 乖離幅 | 出典 |
|---|---|---|
| Ahrefs の traffic 推定 vs GSC 実測 | **median 49.52%**（1,635 site） | Ahrefs 自身 |
| 同じ study 内の Semrush | median 68.36% | 同上（Ahrefs 実施のため利害あり） |

**読み方:**

- **これは「どちらが正しいか」の話ではありません。** clickstream panel の外挿という共通の手法上、両者とも構造的に ±50% 程度の誤差を持ちます。
- **複数 tool の平均を取っても改善しません。** 誤差が独立でなく（同種の panel data に由来）、系統的だからです。
- **正しい対処は「桁でしか判断しない」ことです。** §2.4 の通り、2 倍差は差ではありません。

### 7.6 sample size と multiple comparisons

**過去の失敗（35,995 件走査）に直結する論点です。**

1. **35,995 件を走査して「最も見込みのある入口」を選ぶ**という行為は、**35,995 回の仮説検定**と等価です。
2. 有意水準 5% で 35,995 回検定すれば、**真に何も無くても約 1,800 件が「有意」に見えます**。
3. つまり「全走査して上位を取る」設計は、**上位に来たものが noise である確率が極めて高い**という性質を持ちます。

**対処法:**

| 方法 | 内容 |
|---|---|
| **hold-out** | 走査で候補を出したら、**別 data source・別期間で再確認する**。search volume で選んだ候補を marketplace の install 数で検証する、など。source が独立していれば noise は再現しません |
| **事前登録** | 走査する**前に**「何を満たしたら採用するか」を数値で書き出す。走査結果を見てから基準を決めると、必ず noise を拾います |
| **候補数を絞る** | 35,995 件でなく、**先に定性的な理由で 50 件まで絞ってから**定量評価する。検定回数を 3 桁減らせば multiple comparisons の問題は実質消えます |
| **効果量で切る** | p 値でなく**桁**で切る（§2.4, §7.5）。noise は桁を動かしません |

> **最も重要な指針:** 網羅的な走査は「候補を作る」ためには有効ですが、「**候補を選ぶ**」ためには使えません。選択は必ず**独立した第 2 の証拠**で行ってください。

### 7.7 その他の bias 一覧

| bias | 説明 | 対処 |
|---|---|---|
| **survivorship bias** | marketplace で見えるのは「生き残った product」だけ。失敗して取り下げられた product は見えません。「competitor が少ない = 需要がある未開拓地」ではなく「**皆が試して撤退した地**」の可能性があります | GH Archive で archived / 削除された repo を見る。Hacker News で過去の類似 product の議論を検索する |
| **selection bias（生態系）** | VS Code の data は開発者の、WordPress の data は WP 利用者の需要しか表しません | 複数生態系で同じ signal が出るか確認する |
| **rating inflation** | §4 | ★でなく 1★ の絶対数・support thread を見る |
| **表明選好 vs 顕示選好** | search volume は「調べた」だけ、install は「入れた」、有料 install は「払った」。**後者ほど強い証拠**です | Atlassian Marketplace（有料前提）の重み付けを上げる |
| **CI による水増し** | npm / PyPI の download 数には CI の自動 install が大量に含まれます | 絶対値でなく**同 category 内の相対**で見る。週末に落ちる pattern があれば CI 主体 |
| **英語圏 bias** | HN / GitHub / Stack Overflow はいずれも英語圏に偏ります。日本市場の需要は測れません | 日本語 data は e-Stat と日本語検索需要でしか測れません。**両方測ってください** |

---

## 8. 個人が最初に押さえるべき data source 5 つ

以下は「無料 or 月 700 円相当」「認証不要 or 無料登録」「入口単位の解像度がある」「行動 data である」の 4 条件で選びました。

### 1. WordPress plugin directory API — **競合の薄さ判定の主力**

`https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request[search]=...`

**理由:** 認証不要・無料・rate limit 実質なし。そして**唯一「install（丸め）と downloaded（厳密）と support_threads（厳密）」を同時に返す store** です。§3.2 の 3 つの読み方（DL/install 比、support 未解決率、更新停滞）はここでしか実行できません。検索 hit 数（`info.results`）で niche の混雑度も一発で分かります。

**最初の一手:** 候補 niche 20 個について `info.results` と上位 8 件の install / rating / 更新日を取得し、§3.2(e) の 4 条件で篩にかけてください。1 時間で終わります。

### 2. Atlassian Marketplace REST API — **「金を払う需要」が読める唯一の場所**

`https://marketplace.atlassian.com/rest/2/addons/{key}/distribution`

**理由:** 認証不要で `downloads` と `totalInstalls` が**厳密値**で返ります（実測: 175,535 / 15,954）。そして何より、**この生態系では有料 app が当然**です。導入者は企業で、決裁が通っています。WordPress や VS Code のような「無料が当たり前」の生態系と違い、**支払意欲の存在を前提にできる**点が決定的です。個人開発者から最も見落とされている場所でもあります。

### 3. Stack Exchange API 2.3 — **「未解決の問題」の直接証拠**

`https://api.stackexchange.com/2.3/questions?tagged=...&site=stackoverflow&filter=total`

**理由:** 認証不要・無料・`filter=total` なら 1 request で件数だけ返るため、**300 req/日 の無認証枠でも数百 niche を評価できます**。「質問総数」と「未回答数」の差は、**誰も答えを持っていない問題の量**です。これは rating inflation の影響を受けず、search volume のような推定でもありません。

**注意:** 2023 年以降 LLM により投稿が減少しているため、**時系列でなく同時点の tag 間相対比較**に限定してください。

### 4. Keywords Everywhere（Bronze $84/年） — **検索需要の実用的な下限価格**

**理由:** 月 700 円相当で **100,000 keyword** の volume / CPC / 12 か月 trend が引けます。Ahrefs Lite（¥19,900/月）の 1/28 の費用で、入口の桁を判定するには十分です。**CPC が同時に取れる**点が地味に重要で、CPC が高い語は「その需要に金が動いている」ことの証拠になります（volume より支払意欲に近い量です）。

**使い方の制約:** §2.4 の通り、**桁でしか判断しないでください**。2 倍差は差ではありません。

### 5. Google Search Console — **唯一の実測値。最後に必ずここへ来る**

`https://www.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query`

**理由:** 1〜4 はすべて**他人の data からの推測**です。GSC だけが**あなたの仮説に対する実測**を返します。無料、API あり、query 単位で impression / click / position が取れます。

**運用:** landing page を 1 枚作り、狙う入口の語で index させ、**impression が立つかどうか**を見てください。impression 0 なら、その入口はあなたの想定した言葉で検索されていません。これは search volume tool がどれだけ大きな数字を返しても覆せない事実です。

**限界の認識:** 16 か月保持、anonymized query は表から除外、全行取得の保証なし。

---

### この 5 つを、この順序で使う

```
[1] WordPress API + [3] Stack Exchange API   → 候補 niche を 20〜50 に絞る（無料・1〜2 時間）
              ↓
[4] Keywords Everywhere                      → 入口の桁を確認（$84/年・数十分）
              ↓
[2] Atlassian Marketplace API                → 「金が動いているか」を確認（無料）
              ↓
        landing page を 1 枚作る
              ↓
[5] Google Search Console                    → 実測（無料・2〜4 週間）
```

**この順序が重要な理由:** §7.6 の multiple comparisons 対策そのものです。**同じ data source で候補を作り、同じ data source で選ぶ**と noise を拾います。上の flow は各段階で**独立した source**に切り替わるため、noise は次の段階を通過できません。

そして最後の GSC は、**推定でなく実測**です。ここまで来て impression が立たなければ、その入口は存在しません。逆に impression が立てば、それ以前のすべての推定が外れていても、需要は実在します。

---

## 9. 参考文献

### 査読論文・preprint

| 出典 | 発行主体 | 年 | URL |
|---|---|---|---|
| Filippas, A., Horton, J. J., & Golden, J. M. "Reputation Inflation." *Marketing Science* | INFORMS | 2022 | https://pubsonline.informs.org/doi/abs/10.1287/mksc.2022.1350 |
| 同上（working paper 全文。本調査で本文を直接抽出） | NBER w25857 / 著者 site | 2021 | https://apostolos-filippas.com/papers/inflation.pdf |
| Timoshenko, A. & Hauser, J. R. "Identifying Customer Needs from User-Generated Content." *Marketing Science* 38(1), 1-20 | INFORMS | 2019 | https://pubsonline.informs.org/doi/10.1287/mksc.2018.1123 |
| 同上（MIT open access 版） | MIT DSpace | 2018 | https://dspace.mit.edu/bitstream/handle/1721.1/124203/Timoshenko_Hauser%20Customer%20Needs%20from%20UGC%20June%202018.pdf |
| Medeiros, M. C. & Pires, H. F. "The Proper Use of Google Trends in Forecasting Models." arXiv:2104.03065（本調査で本文・Table 1 を直接抽出） | PUC-Rio | 2021 | https://arxiv.org/abs/2104.03065 |
| Cebrián, E. & Domenech, J. "Is Google Trends a quality data source?" *Applied Economics Letters* 30(6), 811-815 | Taylor & Francis | 2023 | https://doi.org/10.1080/13504851.2021.2023088 |
| Cebrián, E. & Domenech, J. "Addressing Google Trends inconsistencies." *Technological Forecasting and Social Change* 202 | Elsevier | 2024 | https://doi.org/10.1016/j.techfore.2024.123258 |
| "Restoring the Forecasting Power of Google Trends with Statistical Preprocessing." arXiv:2504.07032v2 | arXiv | 2025 | https://arxiv.org/html/2504.07032v2 |
| Choi, H. & Varian, H. "Predicting the Present with Google Trends." *Economic Record* 88(s1), 2-9 | Wiley | 2012 | https://doi.org/10.1111/j.1475-4932.2012.00809.x |

### 公式 document・料金 page（すべて 2026-08-11 確認）

| 内容 | URL |
|---|---|
| Google Trends のデータについて（正規化・sampling・noise） | https://support.google.com/trends/answer/4365533 |
| Keyword Planner の検索数統計（丸め・exact match） | https://support.google.com/google-ads/answer/3022575 |
| Google Trends API (alpha) 公式 doc | https://developers.google.com/search/apis/trends |
| Google Trends API 発表 blog（2025-07） | https://developers.google.com/search/blog/2025/07/trends-api |
| Google Ads API developer token access levels | https://developers.google.com/google-ads/api/docs/access-levels |
| Search Console Search Analytics API | https://developers.google.com/webmaster-tools/v1/searchanalytics/query |
| Search Console performance data の filtering と limits | https://developers.google.com/search/blog/2022/10/performance-data-deep-dive |
| Ahrefs 料金（JPY 表示） | https://ahrefs.com/pricing |
| Ahrefs 無料 Keyword Generator | https://ahrefs.com/keyword-generator |
| Keywords Everywhere 料金 | https://keywordseverywhere.com/ctl/subscriptions |
| G2 Terms of Use（scraping 禁止条項） | https://legal.g2.com/terms-of-use |
| Trustpilot developer portal | https://developers.trustpilot.com/ |
| WordPress.org Plugins API | https://api.wordpress.org/plugins/info/1.2/ |
| Chrome Web Store API（自己 item の publish 管理のみ） | https://developer.chrome.com/docs/webstore/api |
| GitHub REST API rate limits | https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api |
| Hacker News 公式 API | https://github.com/HackerNews/API |
| Hacker News Algolia Search API | https://hn.algolia.com/api |
| GH Archive | https://www.gharchive.org/ |
| BigQuery 料金 | https://cloud.google.com/bigquery/pricing |
| Product Hunt API rate limits | https://api.producthunt.com/v2/docs/rate_limits/headers |
| Discord Developer Policy | https://support-dev.discord.com/hc/en-us/articles/8563934450327-Discord-Developer-Policy |
| e-Stat API | https://www.e-stat.go.jp/api/ |
| e-Stat API 利用規約 | https://www.e-stat.go.jp/api/terms-of-use |
| 総務省 令和 7 年 通信利用動向調査 | https://www.soumu.go.jp/menu_news/s-news/01tsushin02_02000183.html |
| 総務省 通信利用動向調査 menu | https://www.soumu.go.jp/johotsusintokei/statistics/statistics05.html |
| 経済産業省 令和 6 年度 電子商取引に関する市場調査（令和 7 年 8 月公表） | https://www.meti.go.jp/press/2025/08/20250826005/20250826005-a.pdf |
| 経済産業省 電子商取引実態調査 | https://www.meti.go.jp/policy/it_policy/statistics/outlook/ie_outlook.html |
| US BLS Public Data API | https://api.bls.gov/publicAPI/v2/ |
| US Census API | https://api.census.gov/data.json |
| Eurostat dissemination API | https://ec.europa.eu/eurostat/api/dissemination/ |

### 本調査で自ら request し、返り値を確認した endpoint（2026-08-11）

| endpoint | 確認内容 |
|---|---|
| `api.wordpress.org/plugins/info/1.2/` | `active_installs` は有効数字 1 桁に丸め、`downloaded` / `num_ratings` / `support_threads` は厳密。認証不要 |
| `marketplace.visualstudio.com/_apis/public/gallery/extensionquery` | `install` / `downloadCount` / `ratingcount` / `averagerating` / `trending*` すべて厳密。認証不要 |
| `marketplace.atlassian.com/rest/2/addons/{key}/distribution` | `downloads` / `totalInstalls` 厳密、`totalUsers: -1`（非公開）。認証不要 |
| `chromewebstore.google.com/detail/...` | HTML 内に `16,000,000 users` の丸め表記。公開 API 無し |
| `apps.shopify.com/{app}` | JSON-LD に `"ratingValue":4.9`。`reviewCount` は raw HTML に無し |
| `notion.com/templates/{slug}` | JSON-LD に `"ratingValue":4.975`, `"reviewCount":40` |
| `figma.com/community/plugin/{id}` | 750KB の JS app。raw HTML に install 数の平文無し |
| `itunes.apple.com/lookup?id=` | `averageUserRating: 4.68546`, `userRatingCount: 18,381,636`（厳密）。認証不要 |
| `api.stackexchange.com/2.3/` | 無認証で `quota_max: 300`/日。`filter=total` で件数のみ取得可 |
| `api.github.com/search/repositories` | `X-RateLimit-Limit: 10`, `X-RateLimit-Resource: search`（無認証） |
| `api.npmjs.org/downloads/point/last-month/{pkg}` | 厳密な DL 数。認証不要 |
| `pypistats.org/api/packages/{pkg}/recent` | **429 RATE LIMIT EXCEEDED**（rate limit が厳しい） |
| `api.bls.gov/publicAPI/v2/timeseries/data/{id}` | 無認証で成功 |
| `api.census.gov/data.json` | 1,795 dataset |
| `ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{ds}` | JSON-stat 形式で成功。認証不要 |

### 本調査で確認できなかった項目（伝聞であり、実装前に自ら確認が必要）

| 項目 | 理由 | 確信度 |
|---|---|---|
| Semrush の公式料金 | `semrush.com` が本調査環境から DNS 解決不可。二次情報のみ | 中 |
| Reddit Data API の正確な料金・rate limit | `redditinc.com` / `support.reddithelp.com` がいずれも fetch 不可（403 / block）。二次情報のみ | 中 |
| Ubersuggest の公式料金 | 公式 page が 404 / 403。確認できた source が affiliate 記事のみ | **低** |
| Capterra の Terms of Use 本文 | 本文取得に失敗 | 低 |
| Chrome Web Store の user 数丸め幅の正確な閾値 | Google の公式記載を確認できず | 中 |
| Keyword Planner の exact 値解放に必要な広告費 | Google は非公開。金額は伝聞 | 低 |
| Google Search Console の anonymized query の正確な定義と閾値 | 公式 blog は特定できたが本文の fetch に失敗 | 中 |
| Ahrefs 無料 Keyword Generator の日次上限 | 公式 page に記載なし | 中 |

---

## 10. 付録: 検証済みの request 例

いずれも認証不要・無料で、そのまま実行できます（2026-08-11 動作確認済み）。

```bash
# WordPress: niche の混雑度と上位競合
curl -sG 'https://api.wordpress.org/plugins/info/1.2/' \
  --data-urlencode 'action=query_plugins' \
  --data-urlencode 'request[search]=invoice' \
  --data-urlencode 'request[per_page]=8'
# → info.results = 1513（hit 数）, 各 plugin の active_installs / downloaded /
#    num_ratings / rating / last_updated / support_threads(_resolved)

# Atlassian: 有料 app の実導入数
curl -s 'https://marketplace.atlassian.com/rest/2/addons/com.kanoah.test-manager/distribution'
# → {"downloads":175535,"totalInstalls":15954,"totalUsers":-1}

# VS Code Marketplace: 厳密な install 数
curl -s -X POST 'https://marketplace.visualstudio.com/_apis/public/gallery/extensionquery' \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json;api-version=7.2-preview.1' \
  -d '{"filters":[{"criteria":[{"filterType":7,"value":"ms-python.python"}],"pageSize":1,"pageNumber":1}],"flags":914}'
# → statistics[] に install / downloadCount / ratingcount / averagerating / trending*

# Stack Overflow: 件数だけを 1 request で（quota 節約）
curl -s --compressed 'https://api.stackexchange.com/2.3/questions?tagged=stripe-payments&site=stackoverflow&filter=total'
# → {"total":13163}
curl -s --compressed 'https://api.stackexchange.com/2.3/questions/unanswered?tagged=stripe-payments&site=stackoverflow&filter=total'
# → 差分が「未解決の問題の stock」

# Apple App Store: 厳密な rating 数
curl -s 'https://itunes.apple.com/lookup?id=310633997&country=us'
# → averageUserRating / userRatingCount

# Hacker News: rate limit なし
curl -s 'https://hacker-news.firebaseio.com/v0/maxitem.json'
```

---

**確認日: 2026-08-11**
**調査実施: research team B（定量的な需要 signal）**
