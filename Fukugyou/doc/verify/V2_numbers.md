# V2: 定量数値の敵対的検証

検証日: 2026-08-11 / 担当: V2（敵対的検証）
方針: 既存 document を信用せず、原典に直接当たっております。原典に到達できなかったものは値の一致に関わらず「未確認」としております。標本の定義（何件・どの規模・いつ・どう集めたか）が原典で確認できない数値は、値が合っていても実務上「使用不可」と評価しております。

制約の開示: 本 session は WebSearch の予算を使い切っていたため、検索は DuckDuckGo の HTML endpoint 経由で行い、原典の PDF は PyMuPDF で local 抽出いたしました。`web.archive.org` は当方の tool からも到達できませんでした（E document の報告と一致）。

---

## 1. 判定 summary

| # | 主張の数値 | 判定 | 原典での実際の値 | 一言 |
|---|---|---|---|---|
| 1 | 約 140 億 page のうち 96.55% が Google 流入ゼロ | **確認** | 96.55% / 約 140 億 page / 2023-12-01 | caveat（index 全体 3,408 億 page の一部・keyword 6.51 億）も原典に明記されており、document の記述と一致します |
| 2 | ChartMogul 2025（約 3,500 社）で月 $50 未満 tier は GRR 23% / NRR 32%、月 $250 超は 70% / 85% | **部分的に不正確** | 値は 4 つとも一致。ただし**この表は AI-native 製品のみ**（filter 前で約 200 社）であり、3,500 社の数値ではございません | 値は正しく、母集団の名乗りが誤りです。`D §5.1` は正しく限定していますが、手順書 `MARKET_RESEARCH.md:233` が限定を落としております |
| 3 | ChartMogul 2023（2,100 社超）で customer churn 中央値が月 3〜4% で安定。ARR 30 万ドル未満は分析から除外 | **誤り** | 2023 report に**月次 churn の数値は一切存在しません**。全 metric が 12 か月 cohort です。$300k 除外は ARPA/ASP 別図表のみで、ARR 別図表には `<$300k` 帯が掲載されております | 二重の誤りです。詳細は §2-3 |
| 4 | 非公開で「二度と雇わない」と答えた発注者の 28.4% が公開では 4★ 以上 | **確認** | 28.4%（NBER WP 25857, 2019-05 / *Marketing Science* 2022） | 本文を verbatim で確認済みです。ただし論文内に「4 or more」「more than 4」の表記揺れがございます |
| 5 | Kloss & Kunter (2016), n=253。「hypothetical 性と最小抵抗への着目により偏る」かつ「BDM と比較可能な予測品質」 | **部分的に不正確** | 結論 2 点は publisher の abstract で verbatim 確認。**n=253 は原典で確認できておりません** | 結論は生き残り、標本定義は落ちます。§2-5 の扱いをご参照ください |
| 6 | METR RCT: 16 人 / 246 件、19% 遅い、事前 +24%、事後 +20% | **確認** | 16 developers / 246 tasks / 19% slower / forecast 24% / post-hoc 20%（arXiv:2507.09089） | 全数値一致です。ただし METR 自身の 2026-02 の post は同結果を「20% slowdown」と丸めております |
| 7 | Acquire.com の profit multiple 中央値 3.9x（2024・2025）。標本件数の記載無し | **確認** | 「In both 2024 and 2025, SaaS businesses sold at a median profit multiple of 3.9x」。平均 low-to-mid 4x、平均 81 日。**件数の記載は確かにございません** | 「件数非開示」という document の自己申告まで含めて正しいです |
| 8 | Stripe verified 済み Indie Hackers 製品の 54% が収益ゼロ、月 $8,333 超は 5% | **確認** | 「more than 54% of the products are not making any revenue at all」「Only around 5% ... exceeding ~$8,333」 | 出典特定済み: Scraping Fish、937 製品、2022-07-16 snapshot。Indie Hackers 公式ではなく**第三者による scraping** です |
| 9 | SparkToro 検証で GA 相関は最良 0.79 / 最悪 0.50 | **確認** | 最良 Semrush 0.790 / 最悪 Ahrefs 0.504。641 site / 7,692 site-month | 値・標本とも一致します。ただし最悪値の Ahrefs は organic のみを測る指標で、SparkToro 自身が unfair と認めております |
| 10 | Ahrefs 自社実測で median 乖離 49.52% | **確認** | 「the median deviation turned out to be 49.52%」/ 1,635 random websites / 2022-05-03 / US GSC vs US organic 推定 | 原典 URL は `ahrefs.com/blog/traffic-estimations-accuracy/`。**B document の出典表にこの URL が欠落**しております |
| 11 | Google Trends の同一 query 再取得間の相関が 0.496 まで低下 | **確認** | Table 1 Panel (a) Brazil: 0.496 / 0.545 / 0.564、Panel (b) US: 0.655 / 0.516 / 0.575 | 6 値すべて完全一致。ただし対象語は **popular 側**の "GDP Growth" であり、低頻度 query の数値ではございません（§2-11） |
| 12 | JILPT No.245: n=11,358、平均 92,445 円 / 中央値 50,000 円、5 万円未満が 4 割超 | **確認** | 図表 2-4-21「計 n=11,358 ... 平均値 92,445 / 中央値 50,000」。5 万円未満は 4.7+8.9+10.2+10.5+6.9 = **41.2%** | 完全一致です。本調査で最も検証に耐えた数値の一つです |
| 13 | 総務省 令和 4 年: 副業者 305 万人、比率 4.8%、正規 2.5% | **確認** | 「副業がある者は 305 万人」（実数 304.9 万人）、「4.8％」、「正規の職員・従業員」は 2.5%、非正規 7.2% | 完全一致。ただし分母は**非農林業従事者**であり、全有業者ではございません |
| 14 | CB Insights: 原典 PDF 作成日 2016、n=101、#1 が 42%。現在は n=431 で「資金枯渇 70% / PMF 不良 43%」 | **確認** | PDF metadata `creationDate: D:20160727163319`、「101 startup failure post-mortems」、「a notable 42% of cases」。現行 page は 2026-03-05 更新 / 431 社（理由特定 385 社）/ 70% / 43% | 両方とも実在いたします。§3-A に A document との日付不整合を記載しております |
| 15 | Kevin Kelly 2008-04-27、財務 data を集められた creator は 7 人 | **確認** | 2008-04-27。「hard financial information from seven creators」「there are very few artists making their entire living selling directly to True Fans」「The few that are, are selling high-priced goods」 | 完全一致です |
| 16 | Sean Ellis 原文（2009 年 5 月）に「over 40% ... very disappointed」はあるが、40% の根拠となる標本・分析・分布は原典に無い | **確認** | 2009-05-18 の post に「If however, you find that over 40% of your users are saying that they would be 'very disappointed'」。標本数・分析・分布の記載は**ございません** | 「記載が無い」という否定的主張まで確認できました。ただし §3-D に C document の矛盾を記載しております |
| 17 | pioneer の平均 13 年後に early leader が参入 | **部分的に不正確** | 「early leaders entered 13 years after market pioneers」は正しい。ただし**「19 years in pre-World War II ... and five years in post-World War II categories」** | 13 年は戦前 category に引きずられた平均です。現代の digital 製品に当てる数字は **5 年**の側です |
| 18 | Blue Ocean 108 社: 86% が line extension で売上 62% / 利益 39%、14% が blue ocean で売上 38% / 利益 61%。抽出方法は非公開 | **未確認（原典に到達できず）** | 二次情報は 86/14・38%・61% で一致 | 原典は書籍 Kim & Mauborgne (2005) の Figure 1-2 で、当方から全文に到達できませんでした。§2-18 に二次情報の出所を明記しております |

判定内訳: 確認 12 / 部分的に不正確 3 / 誤り 1 / 未確認 1 + §3 に追加報告 6 件。

---

## 2. 各項目の詳細

### #2 ChartMogul 2025 の価格帯別 retention — 母集団の名乗りが誤りです

原典（`chartmogul.com/reports/saas-retention-the-ai-churn-wave/`）で確認した内容:

- 標本: 約 3,500 社を website scraping で分類（B2B SaaS 約 2,700 / B2C SaaS 約 600 / AI-native 約 200）
- retention 算出対象: **ARR $250k 以上**。理由は「historical retention data is less reliable for very early-stage startups with few customers」
- 期間: 2025 年 1〜9 月の annualized retention
- 価格帯別の表: `>$250/month → GRR 70% / NRR 85%`、`$50-$249 → 45% / 61%`、`<$50 → 23% / 32%`

**値は 4 つとも一致いたしました。**しかし当該 section の見出しは "Easy to buy, easy to cancel?" であり、本文は「AI-native products that sell for >$250 per month see 70% GRR and 85% NRR」と明示しております。**この表は AI-native 製品のみの数値**でございます。

さらに厳しく見るべき点として、次の 3 つが確認できませんでした。

1. **有効標本数が不明です。** AI-native は filter 前で約 200 社ですが、ARR $250k 以上に絞った後の残存数を原典は開示しておりません。これを 3 つの価格帯に割ると、1 帯あたりの n は 2 桁前半まで落ちる可能性がございます。GRR 23% という極端値は、この n の小ささと整合いたします。
2. **GRR / NRR の定義が report 内に明示されておりません。** 「2025 年の annualized rate」以上の記述がなく、cohort の取り方が確認できません。
3. AI-native は 1 月の GRR 中央値 27% から 9 月に 40% へ改善しており、**期間内で大きく動いている系列**です。年間 1 点の値として引用すること自体に無理がございます。

`D_competition_pricing.md` の §5.1 は、表の見出しを「AI-native 製品の価格帯別 retention(2025)」とし、さらに注記で約 200 社であることを明記しております。**D document 側は正確です。**誤っているのは summary 表（`D:71`）と手順書 `MARKET_RESEARCH.md:233` で、こちらは「ChartMogul 2025（約 3,500 社）で、月 $50 未満 tier は」と書いており、母集団を 17 倍に誇張した形になっております。

### #3 ChartMogul 2023 の月次 churn — 原典に存在いたしません

原典 PDF（`saas-retention-report-2023.pdf`、43 page）を全文抽出して検証いたしました。

**(a) 月 3〜4% という customer churn 中央値は、この report に存在いたしません。**

- 全文検索で "monthly churn" "churn rate" の median 値は 0 件でした。
- この report の retention 定義は明示的に**年次**です。第 1 章に「# of paying customers left from paying customers one year ago ÷ # of paying customers one year ago」と定義されており、「typically over 12 months」とも書かれております。
- Methodology（p.42）: 「We analyzed anonymized and aggregated data from ChartMogul to calculate all aggregates. We only considered companies active for the full 12 months when calculating the aggregates. Unless stated otherwise, we calculated aggregates over the year 2022.」

参考までに、原典の年次値から月次へ換算いたしますと次の通りです（換算は当方が行ったものであり、原典の数値ではございません）。

| ARR 帯 | 年次 customer retention 中央値 | 月次換算 churn |
|---|---|---|
| `<$300k` | 54.8% | 約 4.9% / 月 |
| `$15-30m` | 62.5% | 約 3.9% / 月 |

つまり「月 3〜4%」に相当するのは**最大規模帯**であり、中央値でも個人規模帯でもございません。手順書の「月 3% churn は中央値」は、規模を取り違えた引用でございます。

**(b) 「ARR 30 万ドル未満は分析から除外」も不正確です。**

除外注記 `Note: Excludes companies <$300k ARR` は、**ARPA 別・ASP 別の図表に個別に付されているもの**でございます。ARR 別の図表には `<$300k` という band が明示的に存在し、benchmark が公表されております（executive summary p.3、第 2〜4 章）。

したがって手順書 `MARKET_RESEARCH.md:284` の「ARR 30 万ドル未満の SaaS の churn benchmark は ChartMogul が分析から除外しており公表されていない」は、**事実に反します**。正しくは以下が公表されております。

| `<$300k` ARR 帯（年次） | 25th | 中央値 | 75th | 90th |
|---|---|---|---|---|
| Customer Retention | 36.6% | 54.8% | 72.2% | 87% |
| Gross Revenue Retention | 35.1% | 53.6% | 72.6% | 87% |
| Net Revenue Retention | 37.8% | 57.6% | 79.2% | 98.2% |

なお `E_source_hygiene.md:269` の「ARR 30 万ドル未満は**一部**分析から除外」という書き方は正確です。誤っているのは手順書側でございます。

**(c) 「実 billing data」という表現について。** 原典の自称は「anonymized and aggregated data from ChartMogul」でございます。ChartMogul は subscription analytics platform ですので実質的に billing data 由来ではございますが、原典がその語で名乗ってはいない点は記録しておきます（2024 年版 "The New Normal" は "billing data" と名乗っております）。

### #4 Reputation Inflation 28.4%

原典（NBER Working Paper 25857, 2019 年 5 月）本文を確認いたしました。

> A starting point is the divergence between public and private feedback scores: **28.4% of those employers that privately report that they would definitely not hire the same worker in the future, publicly assign them 4 or more stars out of 5.** The reverse essentially never happens

p.17 に分布の内訳もございます。「Definitely No」を選んだ発注者のうち 29.1% が公開では 1★、15.7% が 4.75〜5.00 帯、そして 28.4% が 4★ 超という構成です。

留意点を 2 つ挙げます。

- 論文内で表記が揺れております。序論は "4 or more stars"、p.17 は "more than 4 stars" でございます。document の「4★ 以上」は序論に従った表現で、許容範囲と判断いたします。
- platform 名は論文中で匿名化されており、標本の期間・件数は当該箇所には明示されておりません。「28.4%」の分母は「私的に Definitely No と答えた発注者」であり、全 review ではございません。この点は引用時に落とさないでください。

### #5 Kloss & Kunter (2016)

publisher（IABE、DOI: EJM-16-2.4）の abstract で、結論 2 点を verbatim 確認いたしました。

> The Van Westendorp Price Sensitivity Meter yields biased results because of its hypothetical nature and its focus on minimum customer resistance.

> the authors find it to be a method of high predictive quality for eliciting willingness-to-pay since the measurement results are comparable to those of the incentive-aligned Becker-DeGroot-Marschak mechanism.

**document が両論併記している点は正確でございます。**一方を落として引用しますと原典の歪曲になりますので、この併記は維持してください。

ただし **n=253 は確認できておりません。** ResearchGate は 403、Semantic Scholar API は 429 で、原典本文に到達できませんでした。冒頭の方針に従い、この標本定義は「未確認」でございます。検証方針上は「値が合っていても標本定義が確認できない数値は使用不可」ですので、**本文中の "n=253" は削除するか「標本数は未確認」と明記する**ことを推奨いたします。結論部分（両論併記）は publisher の abstract で確認済みですので、そのまま使用可能です。

### #6 METR RCT

arXiv:2507.09089 の abstract で全数値を確認いたしました。16 developers / 246 tasks / 「allowing AI actually increases completion time by 19%」/ 事前予測は 24% 短縮 / 事後自己評価は 20% 短縮。

軽微な点として、原典の語は "tasks" であり "issues" ではございません。abstract は「developers provide lists of realistic tasks from repositories they maintain」と述べており、「実 issue 246 件」という言い換えは概ね妥当ですが、厳密には「本人が保守する repository の実 task 246 件」でございます。

### #9 SparkToro

原典で確認した相関値（GA の Users を真値とした場合）:

| tool | 相関 |
|---|---|
| Semrush | 0.790（最良） |
| Datos | 0.720 |
| SimilarWeb | 0.659 |
| Ahrefs | 0.504（最悪） |

標本は 641 site / 7,692 site-month（当初 1,053 site から clean 後）でございます。document の「最良 0.79・最悪 0.50」は正しい丸めです。

ただし**最悪値には強い注釈が必要**です。Ahrefs は organic 検索のみを測る指標を全 traffic と比較されており、SparkToro 自身が unfair な比較と認めております。`D:37` はこれを開示しておりますが、手順書 `MARKET_RESEARCH.md:214` は開示しておりません。「最悪 0.50」を単独で出しますと、Ahrefs に対する不当な評価になります。

### #11 Google Trends 0.496

原典 PDF（arXiv:2104.03065, Medeiros & Pires）Table 1 を抽出し、6 値すべての完全一致を確認いたしました。

| | S1-S2 | S1-S3 | S2-S3 |
|---|---|---|---|
| Panel (a) Brazil | **0.496** | 0.545 | 0.564 |
| Panel (b) US | 0.655 | 0.516 | 0.575 |

標本の定義: 検索語 "GDP Growth"、US と Brazil、2009 年 1 月〜2019 年 1 月、同一条件で取得した 3 sample。`B:114` の記述と完全に一致いたします。

**ただし論旨の当て方に問題がございます。**原典はこの語を明示的に popular 側に位置づけております。

> The table shows that the correlation between two different Google Trends sample can be as low as 0.496, **even when we consider a relatively popular topic in Economics.**

原典が低頻度語の例として挙げているのは "Refined Petroleum" であり、0.496 は**比較的 popular な語の値**でございます。したがって「低頻度 query は使い物にならない。相関が 0.496 まで落ちる」という並べ方は、根拠の当て方が逆でございます。正しくは「**popular な語ですら 0.496 まで落ちる。低頻度語はさらに悪い**」であり、この方が主張は強くなります。`B:114` は語が popular であることを明記しておりますが、`B:25` と手順書 `MARKET_RESEARCH.md:202` は明記しておりません。

もう 1 点、原典は解決策も提示しております。7 sample の平均を取れば相関は Brazil 0.92 / US 0.95 まで回復いたします。「使えない」で止めますと原典の主眼（proper use の提案）を落とすことになります。

### #17 Golder & Tellis の 13 年

原典 PDF を抽出し、abstract と本文の両方で確認いたしました。

> early market leaders have much greater long-term success and enter an average of **13 years** after pioneers.（abstract）

> early leaders entered 13 years after market pioneers. **The time lag was 19 years in pre-World War II product categories and five years in post-World War II categories.**（本文）

標本は約 500 brand / 50 product category、手法は historical analysis です。Table 7 の early market leader の failure rate は 8%、market share 28%（36 cases）で、`D:14` の記述と一致いたします。

**「13 年」を無条件に引用するのは不適切でございます。**13 年は戦前 category（19 年）に引き上げられた平均であり、戦後 category では 5 年です。現代の software 製品に当てる場合、5 年の側が実態に近く、しかも原典はこの分割を同じ段落で明記しております。手順書 `MARKET_RESEARCH.md:17` と `D:234` は 13 年のみを引用しており、原典より甘い（後発に有利な）結論を提示している状態です。

### #18 Blue Ocean 108 社 — 未確認

原典は書籍 Kim & Mauborgne, *Blue Ocean Strategy* (2005) の Figure 1-2 と考えられますが、当方から全文に到達できませんでした。公式 site（`blueoceanstrategy.com/what-is-blue-ocean-strategy/`）には 108 社の記述は無く、代わりに「a decade-long study of more than 150 strategic moves spanning more than 30 industries over 100 years」という別の標本記述がございました。**公式 site が名乗る標本と、document が引用する 108 社は別物**です。

到達できた二次情報は以下 3 件で、数値は相互に一致しております。

- `public.summaries.com/files/1-page-summary/blue-ocean-strategy.pdf` — 「86-percent of new product launches were line extensions and only 14-percent were attempting to create blue ocean markets」「38-percent of total revenues and 61-percent of total profits」
- `strategicmanagementinsight.com/tools/blue-ocean-strategy/` — 「14% of the launches that aimed at creating blue oceans contributed to 38% of the revenue and 61% of the total profits」（108 社の分析として言及）
- `www.ukessays.com/guides/blue-ocean-strategy-guide.php` — 同旨

いずれも書籍の要約であり、独立した検証ではございません。売上 62% / 利益 39% は 100 からの引き算で導かれる値です。

**抽出方法が非公開であるという document の主張については、到達可能な範囲で反証が見つかりませんでした**（公式 site にも二次情報にも sample frame の記載がございません）。document の結論の向きは支持されますが、原典未到達である以上、判定は「未確認」といたします。なお、標本の単位は「108 社」ではなく「108 社の事業立ち上げ（launches）」である可能性が高く、引用時はこの点にご注意ください。

---

## 3. 対象表に無い追加報告

### A. CB Insights 原典の公開日が A document と E document で食い違っております

- `A_evidence.md:393` / `A:570`: 「2014 年 9 月 25 日公開」
- `E_source_hygiene.md:14` / `E:406`: 「PDF の作成日は 2016 年」

当方が PDF metadata を直接読んだ結果は `creationDate: D:20160727163319-04'00'`、`creator: Adobe InDesign CC 2015 (Macintosh)` でございました。**E の記述（PDF 作成日 2016-07-27）が正確**です。blog 記事の初出が 2014 年で PDF が 2016 年に再生成された可能性はございますが、A document は「PDF 一次確認済」と書いた上で 2014 年と述べており、確認内容と記述が整合いたしません。どちらかに統一してください。

### B. Ahrefs 49.52% study の URL が B document の出典表に存在いたしません

`B_quant_sources.md` は 49.52% を 3 箇所（`:42`, `:174`, `:583`）で使っておりますが、末尾の出典表（`:715-716`）には Ahrefs の pricing と keyword generator しか載っておらず、**当該 study の URL がございません**。二次情報（`techbusinessnews.com.au`）も原典 link を持たずに孤立して流通している数値でございます。

原典を特定いたしました。**`https://ahrefs.com/blog/traffic-estimations-accuracy/`（2022-05-03、1,635 random websites、US GSC 実測 vs US organic 推定、median deviation 49.52%）**。出典表に追記してください。

なお、Ahrefs の後続記事（`ahrefs.com/blog/keyword-traffic-estimations-update/`）は「The last time we studied the accuracy of our search traffic estimations, we got a median deviation of 49.52%」と過去形で言及し、その後 estimation を更新したと述べております。**2022 年時点の値であり、現行の精度ではない可能性がございます。**

### C. E document の「METR が自 study を historical と label した」は過剰な主張です

`E:217` と `E:422` は、METR が 2026-02-24 の post で自身の 2025 年 study を historical と label したと述べ、それを「訂正履歴がある」good example として挙げております。

当該 post（`metr.org/blog/2026-02-24-uplift-update/`、2026-02-24）を確認いたしましたが、**historical という label 付けは行っておりません**。post が述べているのは、(a) 過去の結果の紹介（「found the use of AI tools caused a 20% slowdown ... using data from February to June 2025」）、(b) 新 experiment が selection bias で信頼できないこと、(c) 「it is likely that developers are more sped up from AI tools now — in early 2026 — compared to our estimates from early 2025」という見通しでございます。過去結果を否定・撤回してはおらず、baseline として使い続けております。

「陳腐化の可能性を自ら述べた」までが正確で、「historical と label した」は言い過ぎでございます。source hygiene を説く document 自身の引用が緩んでいる箇所ですので、優先的に修正すべきと考えます。

### D. C document が Sean Ellis の 40% に「約 100 社」という標本を付与しております

`C_discovery.md:1286`: 「Sean Ellis が約 100 社を benchmark した経験に基づき、2009 年に blog で公開」

当方が原典（startup-marketing.com、2009-05-18 の post）で確認した限り、**標本数の記載はございません**。これは E document（`E #16` / 手順書 `:288`）の「原典に標本・分析・分布の記載なし」と真正面から矛盾いたします。「約 100 社」の出所は特定できませんでした。C document 側の記述を削除するか、出典を示してください。

### E. METR の 19% と 20% の使い分け

論文 abstract は 19%、METR 自身の blog は 20% と丸めております。document 群は 19%（論文値）を使っており正しいのですが、二次情報で 20% を見た際に「別の数字だ」と誤認しないよう、両方が同一 study であることを注記されることを推奨いたします。

### F. 総務省 4.8% の分母

`E:426` と手順書は「副業者比率 4.8%」とのみ記載しておりますが、原典の定義は「**非農林業従事者**に占める副業がある者の割合」でございます。全有業者（6,706 万人）を分母にすると 4.5% となり、値が変わります。分母の明記を推奨いたします。

---

## 4. 手順書 `doc/MARKET_RESEARCH.md` の修正指示

以下、行番号と修正内容を具体的に記載いたします。**必須**は事実誤認、**推奨**は誤読を招く記述でございます。

### 必須 1: `:68` — ChartMogul の churn（誤りが 2 つ入っております）

現状:
> **月 3% churn は「理想」ではなく「中央値」**（ChartMogul 2023、2,100 社超の実 billing data）。ただし ARR 30 万ドル未満は分析から除外されており、**個人規模帯の benchmark は存在しない**（`E #8`）。

修正案:
> **churn の benchmark は年次で読む。**ChartMogul 2023（2,100 社超、2022 年 1 年分の集計 data）は retention を **12 か月 cohort** で定義しており、月次 churn の中央値は公表しておりません。ARR `<$300k` 帯の年次 customer retention 中央値は **54.8%**（月次換算で約 4.9% の churn）で、個人規模帯の benchmark は**存在します**。ARR 30 万ドル未満の除外は ARPA 別・ASP 別の図表に限られ、ARR 別図表には `<$300k` 帯が掲載されております（`V2 #3`）。

### 必須 2: `:284` — 「公表されていない」の削除

現状:
> | ARR 30 万ドル未満の SaaS の churn benchmark | ChartMogul が分析から除外しており**公表されていない** |

この行は事実に反しますので、削除するか次に差し替えてください。

> | 個人規模（ARR 数万ドル）の SaaS の churn benchmark | ChartMogul の最小 band は `<$300k` ARR。これより小さい規模帯の benchmark は存在しません |

### 必須 3: `:233` — ChartMogul 2025 の母集団

現状:
> ChartMogul 2025（約 3,500 社）で、月 $50 未満 tier は GRR 23% / NRR 32%、月 $250 超 tier は GRR 70% / NRR 85%。

修正案（母集団を AI-native に限定し、n の不明を明記）:
> ChartMogul 2025 の **AI-native 製品**（分類時点で約 200 社、うち ARR $250k 以上のみを算入。有効 n は非開示）で、月 $50 未満 tier は GRR 23% / NRR 32%、月 $250 超 tier は GRR 70% / NRR 85%。AI-native は 2025 年 1 月から 9 月にかけて GRR 中央値が 27% → 40% と大きく動いており、単年の点として扱わないでください。

同じ修正を `D_competition_pricing.md:71` の summary 表にも適用してください（`D §5.1` 本体は既に正確です）。

### 必須 4: `:17` — Golder & Tellis の 13 年

現状:
> 長期の勝者は **pioneer の平均 13 年後に参入した early market leader**

修正案:
> 長期の勝者は **pioneer より後に参入した early market leader**（平均 13 年後。ただし原典は「戦前 category で 19 年・戦後 category で 5 年」と分割しており、現代の digital 製品に当てるなら **5 年**の側です）

同じ注記を `D_competition_pricing.md:234` にも追加してください。

### 必須 5: `:229` — Kloss & Kunter の n=253

現状:
> 唯一の incentive-aligned 比較実験（Kloss & Kunter 2016, n=253）

`n=253` は原典で確認できておりません。次のいずれかにしてください。

> 唯一の incentive-aligned 比較実験（Kloss & Kunter 2016, *European Journal of Management* 16(2), 45-54。標本数は当方で未確認）

### 推奨 1: `:202` — Google Trends 0.496 の当て方

現状は「低頻度 query は使えません」→「0.496 まで落ちる」の順で、0.496 が低頻度語の値であるかのように読めます。原典では popular 語の値ですので、順序を入れ替えると主張が強くなります。

修正案:
> **Google Trends は同じ query でも取得のたびに値が変わります。**"GDP Growth" という比較的 popular な語ですら、同一条件 3 sample 間の相関が **0.496** まで落ちた実測がございます（Medeiros & Pires 2021, arXiv:2104.03065, Table 1）。低頻度語はこれより悪化いたします。原典は 7 sample の平均を取れば相関が 0.92〜0.95 まで回復すると示しており、単発取得の値を根拠にしないでください。用途は季節性と増減の方向だけです。

### 推奨 2: `:214` — SparkToro の「最悪 0.50」

「最悪 0.50」は Ahrefs（organic のみ）を全 traffic と比較した結果で、SparkToro 自身が unfair と認めております。次の一文を追加してください。

> なお最悪値の 0.504 は Ahrefs で、organic 検索のみを測る指標が全 traffic と比較されたためです（SparkToro 自身が unfair な比較と開示）。標本は 641 site / 7,692 site-month です。

### 推奨 3: `:235` — Indie Hackers 分布の出所

「Stripe verified 済み Indie Hackers 製品の 54% は収益ゼロ」に出所と時点がございません。数値自体は原典で確認できましたので、括弧書きを追加してください。

> （Scraping Fish による第三者 scraping、937 製品、2022-07-16 時点の snapshot）

### 推奨 4: `:201` — Ahrefs 49.52% の出典と時点

> Ahrefs は自社実測で median 乖離 49.52%（`ahrefs.com/blog/traffic-estimations-accuracy/`、2022-05-03、1,635 site、US organic）。**2022 年時点の値**であり、Ahrefs は以後 estimation を更新したと述べております。

あわせて `B_quant_sources.md` の出典表（`:715` 付近）に当該 URL を追加してください。

### 推奨 5: `:203` — 28.4% の分母

「非公開で『二度と雇わない』と答えた発注者の 28.4%」という現行表現は正確です。分母が「全 review」ではなく「私的に Definitely No と答えた発注者」であることが読み取れますので、**この表現を維持**してください（要約時に「28.4% の review が inflate されている」と縮めますと誤りになります）。

### 推奨 6: 副業者比率の分母

`:60` 前後および `E:426` の「副業者比率 4.8%」に、分母が**非農林業従事者**である旨を追記してください。

---

## 5. 検証に使用した原典

| # | 原典 | 到達方法 |
|---|---|---|
| 1 | ahrefs.com/blog/search-traffic-study/ | 直接取得 |
| 2 | chartmogul.com/reports/saas-retention-the-ai-churn-wave/ | 直接取得（2 回、表の限定文言を追加確認） |
| 3 | chartmogul.com/reports/saas-retention-report/saas-retention-report-2023.pdf | PDF を PyMuPDF で全 43 page 抽出 |
| 3 補 | chartmogul.com/reports/saas-retention-the-new-normal/ | 直接取得（3.5% / 7% の出所確認） |
| 4 | nber.org/system/files/working_papers/w25857/w25857.pdf | PDF を PyMuPDF で全 50 page 抽出 |
| 5 | iabe.org/IABE-DOI/article.aspx?DOI=EJM-16-2.4 | 直接取得（abstract のみ。本文は 403 / 429 で未到達） |
| 6 | arxiv.org/abs/2507.09089 | 直接取得 |
| 6 補 | metr.org/blog/2026-02-24-uplift-update/ | 直接取得 |
| 7 | blog.acquire.com/acquire-com-biannual-acquisition-multiples-report-jan-2026/ | 直接取得 |
| 8 | scrapingfish.com/blog/indie-hackers-revenue | 直接取得 |
| 9 | sparktoro.com/blog/which-3rd-party-traffic-estimate-best-matches-google-analytics/ | 直接取得 |
| 10 | ahrefs.com/blog/traffic-estimations-accuracy/ | DuckDuckGo 経由で特定後、直接取得 |
| 11 | arxiv.org/pdf/2104.03065 | PDF を PyMuPDF で全 18 page 抽出、Table 1 を直接読解 |
| 12 | jil.go.jp/institute/research/2024/documents/0245.pdf | PDF を PyMuPDF で全 362 page 抽出、図表 2-4-21 を直接読解 |
| 13 | stat.go.jp/data/shugyou/2022/pdf/kgaiyou.pdf | PDF を PyMuPDF で全 72 page 抽出、p.15 を直接読解 |
| 14 | s3-us-west-2.amazonaws.com/cbi-content/research-reports/The-20-Reasons-Startups-Fail.pdf | PDF を PyMuPDF で抽出、metadata も確認 |
| 14 補 | cbinsights.com/research/report/startup-failure-reasons-top/ | 直接取得 |
| 15 | kk.org/thetechnium/the-case-agains/ | 直接取得 |
| 16 | startup-marketing.com/2009/05/ | 直接取得（月別 archive page 経由。個別 post の permalink は 404） |
| 17 | gtellis.net/.../pioneering-advantage-marketing-logic-or-marketing-legend.pdf | PDF を PyMuPDF で全 14 page 抽出 |
| 18 | — | **原典未到達**。公式 site と二次要約 3 件のみ |
