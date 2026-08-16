# E: 情報源の質を見分ける — 煽り記事・folklore の解体

作成日: 2026-08-11 / 全 URL の確認日: 2026-08-11

---

## 0. この文書の使い方と、最初にお伝えすべき結論

この文書は「副業・起業・SaaS 周辺の情報を、何を根拠に採否するか」を決めるための道具です。担当範囲は (1) 情報空間の汚染の実測、(2) 流通している folklore の原典検証、(3) 煽り記事の判別 checklist、(4) 信頼できる source list、(5) evidence hierarchy、(6) 受け手の作法、の 6 つです。

先に、この調査で最も効いた発見を 5 つ挙げます。

1. **「1,000 true fans」は、提唱者本人が 7 週間後に反証記事を書いています。** Kevin Kelly は 2008-03-04 に "1000 True Fans" を出し、2008-04-27 に "The Case Against 1000 True Fans" を出して「True Fans だけで生計の全部を立てている artist は極めて少ない」と自ら書きました。日本語圏でも英語圏でも、この後編を併記した記事をほぼ見かけません。
2. **「CB Insights: 失敗理由 1 位は no market need 42%」は、原典は実在しますが n=101 の自己申告 post-mortem で、PDF の作成日は 2016 年です。** そして CB Insights 自身が現在（2026-03-05 更新）は n=431 で「資金枯渇 70% / product-market fit 不良 43%」という別の数字を出しています。2026 年に 42% を現在形で引用している記事は、10 年前の数字を更新せず使い回しています。
3. **「副業で月 30 万円」系の記事の統計的位置**: 日本の副業者 11,358 人の実測で、副業月収の**中央値は 5 万円**、平均 9.2 万円、5 万円未満が 4 割超です（JILPT 2024）。さらに、正規雇用者のうち副業をしている人は **2.5%** しかいません（総務省 就業構造基本調査 2022）。
4. **「AI で誰でも作れる」に対する唯一の実測 RCT は逆の結果です。** METR の RCT で、熟練 developer は AI 使用時に **19% 遅く**なり、しかも本人たちは「20% 速くなった」と感じていました。体感は反証になりません。
5. **書いても読まれません。** Ahrefs の 140 億 page 調査で、**96.55% の page が Google からの流入ゼロ**です。「SEO で集客」を前提にした事業計画は、この分母を見てから立てるべきです。

そして、この調査自体の限界を先に開示します。

- `web.archive.org` は当方の tool から取得できませんでした（明示的に blocked）。Sean Ellis の 2009 年原文の全文確認は、月別 archive page 経由の間接確認に留まっています。
- `bls.gov` / `ftc.gov` / `chusho.meti.go.jp` / SSRN / Springer は当方の fetcher に対し 403 を返しました。これらは URL のみ提示し、数値は二次情報として明示的に区別しています。
- `baremetrics.com` は DNS 解決に失敗しました（`getaddrinfo ENOTFOUND`）。かつて実 data 開示の代表例だった Open Startups は、現在は当てにできない可能性が高いですが、断定はしません。
- a16z の "1,000 True Fans? Try 100"（Li Jin）は 2 通りの URL いずれも 404 でした。**原典に到達できず**、この主張は本文書では扱いません。

---

## 1. 情報空間の汚染 — 実測 data

### 1.1 AI 生成 content の量

| 対象 | 測定結果 | 標本・方法 | 出典・発行年 | 確信度 |
|---|---|---|---|---|
| 新規 web page 全般 | **74.2%** が AI 生成 content を含む。内訳は pure AI 2.5% / pure human 25.8% / 混在 71.7% | 2025 年 4 月に crawler が発見した英語 page 90 万件（1 domain 1 page）。自社検出器 bot_or_not | Ahrefs, 2025 | 中 |
| Google 検索上位 20 件 | 2025-09 時点 **17.31%**（2025-07 に 19.56% で最高、2019-02 は 2.27%） | 情報検索 intent の keyword 500 件、2 か月ごと、Internet Archive の snapshot から本文抽出 | Originality.ai（継続調査） | 中 |
| Wikipedia 新規記事（英語） | **5% 超**が AI 生成として flag される | 2024-08 作成の英語記事。GPTZero と Binoculars の 2 検出器を、GPT-3.5 以前の記事で false positive 1% になるよう閾値校正 | Brooks, Eggert, Peskoff, arXiv:2410.08044, 2024 | 高 |
| AI content farm 型の news site | **3,749 site**（16 言語） | 4 条件すべてを満たす site を人手で認定 | NewsGuard AI Tracking Center（2026-06-23 更新） | 高 |

**注意（重要）**: 上の 1 行目と 2 行目は「検出器の出力」であり、真の値ではありません。Ahrefs は自ら「完璧な AI content 検出器は存在しない」「訓練 data の偏り、部分的な AI 使用の検出困難、humanize tool への脆弱性」を明記しています。Originality.ai は自社検出器の精度を「99%、false positive 0.5〜1.5%」と称していますが、これは**提供元の自己申告**であり、独立検証を確認できませんでした。

一方、3 行目の Wikipedia 論文だけは方法論の質が明確に高いです。**「GPT-3.5 以前に書かれた記事で false positive が 1% になるよう閾値を校正し、その上で下限を語る」**という設計だからです。この差が、そのまま「査読研究」と「vendor の marketing 調査」の差です。

→ **運用上の帰結**: AI 検出器の出力を、個別の記事の採否判断に使ってはいけません。母集団の傾向を語る材料としてのみ使い、個別記事は後述の checklist（構造的 signal）で判断してください。

### 1.2 検索結果そのものの質

Bevendorff, Wiegmann, Potthast, Stein "Is Google Getting Worse? A Longitudinal Investigation of SEO Spam in Search Engines"（ECIR 2024, Springer LNCS 14608, pp. 56-71）は、Google / Bing / DuckDuckGo を **7,392 件の product review query** で 1 年間監視しました。結論は「全 search engine が高度に最適化された affiliate content に対して重大な問題を抱えており、その割合は ClueWeb22 を baseline とした web 全体の代表値より高い」「web 上の product review のうち affiliate marketing を使うのは一部に過ぎないのに、**検索結果の大半は affiliate**である」というものです。

確信度: 高（査読済み国際会議、縦断調査）。ただし当方は Springer / 著者 PDF の本文取得に失敗しており（403 / PDF 解析不可）、abstract と複数の二次報告からの確認に留まります。**確信度を「高」としているのは方法論と査読の質に対してであり、当方の一次確認の完全性に対してではありません。**

なぜこれが副業に効くかというと、「product review 系の検索結果は affiliate に占拠されている」という構造は、そのまま「〇〇 SaaS 比較」「副業 tool おすすめ」の検索結果に当てはまるからです。市場調査で competitor を検索したときに最初に出てくる比較記事は、比較のために書かれたものではなく、成果報酬のために書かれたものだと考えるのが既定値です。

### 1.3 Google 自身が何を問題視したか（公式 document）

Google の spam policy と rater guideline は、汚染の輪郭を運営側の言葉で定義している点で価値があります。

**Search spam policies（`developers.google.com/search/docs/essentials/spam-policies`）**

- **Scaled content abuse**: "Scaled content abuse is when many pages are generated for the primary purpose of manipulating search rankings and not helping users."
- **Site reputation abuse**: "Site reputation abuse is a tactic where third-party content is published on a host site mainly because of that host's already-established ranking signals."
- **Expired domain abuse**: 期限切れ domain を買い、旧 site の権威を利用して低品質 content を上位化する行為。

**March 2024 core update（`blog.google/products/search/google-search-update-march-2024/`）**: Google は「今回の update と従来の取り組みの組み合わせで、低品質・非独自 content を検索結果から **40%** 削減する」と announce し、2024-04-19 時点で **45%** 削減を達成したと更新しました。

**Search Quality Rater Guidelines（General Guidelines, 2025-09-11 版）**: 実際の rater 向け document に、次の記述があります。

> "Pages and websites made up of content created at scale with no original content or added value for users, should be rated **Lowest**, no matter how they are created. Even if you are unsure of the method of creation, e.g. whether or not the page is created using generative AI tools, you should still use the **Lowest** rating when you strongly suspect scaled content abuse."

> "Websites and pages should be created to help people. If that is not the case, a rating of **Lowest** may be warranted."

ここから読み取るべきは、**Google は「AI で書いたか」を問題にしておらず、「規模で作られ、独自性と付加価値が無いか」を問題にしている**という点です。「AI 記事は penalize される」という言説は半分だけ正しく、判定軸を取り違えています。

### 1.4 affiliate 媒体の incentive 構造 — 規制当局が明文で認めています

消費者庁「アフィリエイト広告等に関する検討会 報告書」（令和 4 年 2 月 15 日）は、次のように書いています。

> 「アフィリエイト広告においては、一般的に広告主ではないアフィリエイターが表示物を作成・掲載するため、広告主による表示物の管理が行き届きにくいという特性や、**アフィリエイターが成果報酬を求めて虚偽誇大広告を行うインセンティブが働きやすい**という特性があるとされており、また、消費者にとっては、**アフィリエイト広告であるか否かが外見上判別できない場合もある**ため、不当な表示が行われるおそれがある」

同報告書はさらに、運用の実態としてこう記録しています。

> 「アフィリエイト広告については、広告主が行うキャンペーン数や提携するアフィリエイターの数が多い場合には膨大な数となる。また、アフィリエイト広告は、容易に変更ができることから、アフィリエイターによっては 1 日のうち複数回アフィリエイト広告を更新する者もいる。その結果、**一般的に広告主はアフィリエイト広告の掲載後に全ての表示内容の確認を行ってない**」

市場規模は、矢野経済研究所の推計で 2020 年度 約 3,258 億円 → 2024 年度 約 4,951 億円と引用されています。

**これは「affiliate 記事は嘘」という意味ではありません。**「誇大表示側に金銭 incentive が構造的にかかっており、掲載後の検証は事実上行われていない」という、規制当局による構造の記述です。読み手として持つべき既定値はこれで十分です。

### 1.5 表示規制の穴 — 誰が縛られていないか

- **日本のステマ規制**（景品表示法の指定告示、令和 5 年 10 月 1 日施行）: 消費者庁の説明によれば、**規制対象は事業者（広告主）のみ**で、依頼を受けた influencer や blogger 等の第三者は規制対象外です。つまり「広告なのに広告と書いていない副業系 blog」を、書いた本人の責任として取り締まる仕組みは日本には無いということです。
- **米国 FTC の Rule on the Use of Consumer Reviews and Testimonials**（最終規則 2024-08-14 公表、2024-10-21 施行）: 偽 review・偽 testimonial（AI 生成の偽 review を含む）の作成・売買、特定の sentiment を書かせる対価付与、自社支配の「独立 review site」偽装、review 抑圧、SNS 影響力指標の売買を禁止。知りつつ違反した者への民事制裁金は 1 件あたり 51,744 ドル（毎年 inflation 調整）。当方は ftc.gov 本文の取得に 403 で失敗し、複数の法律事務所 alert からの確認に留まります（確信度: 中）。

→ **帰結**: 「PR 表記が無い＝広告ではない」は成り立ちません。日本では書き手側に表記義務が無いためです。

### 1.6 そもそも読まれない — 分母の話

Ahrefs（2023-12-01）は Content Explorer の **約 140 億 page** を対象に調べ、**96.55% の page が Google から流入ゼロ**と報告しました。著者自身が caveat を明記しています。(a) 140 億 page は index 全体（推定 3,408 億 page）の一部で「質の高い」側に偏っている、(b) traffic 推定は 6.51 億 keyword に依存し、超 long-tail の流入は拾えていない。

つまり「実際にはもう少し高いかもしれないが、大多数の page が読まれないという結論は変わらない」という趣旨です。確信度: 中〜高（自社 index 由来だが、caveat の開示が誠実で方向性は堅い）。

---

## 2. Folklore 検証表

判定 label の意味:
- **原典あり・妥当** — 原典を確認し、主張が原典と data の両方に整合します。
- **原典あり・誇張** — 原典は実在しますが、流通時に条件・時点・分母が落ちています。
- **原典あり・反証あり** — 原典は実在し、より質の高い data がそれを否定しています。
- **原典に到達できず** — 引用の連鎖を辿り切れませんでした。folklore として扱ってください。

| # | よく言われる主張 | 原典はあるか | 実際の data は何を言っているか | 判定 | 確信度 |
|---|---|---|---|---|---|
| 1 | 「startup の 90% が失敗する」 | **到達できず**。連鎖は Failory → Startup Genome 2019 → Small Biz Trends で行き止まり、そこから先の一次 data がありません。Startup Genome 2019 自体の記述は「12 人に 1 人しか成功しない」であり「90%」ではありません | 定義次第で 30〜95% に振れます。Shikhar Ghosh（HBS）は「予測未達を失敗とすれば 90〜95%、資産清算・投資家が大半を失うことを失敗とすれば 30〜40%」としています。米 BLS の establishment 生存率は 1 年 約 79%、5 年 約 50%、10 年 約 33% | **原典に到達できず**。「90%」は定義を明示しない限り無意味 | 高 |
| 2 | 「CB Insights: 失敗理由 1 位は no market need 42%」 | **あり**。"The Top 20 Reasons Startups Fail"（PDF 作成日 2016-07-27、本文に「101 startup failure post-mortems」）。#1 が 42%、#2「Ran out of cash」29%、#4「Get outcompeted」19% | 標本は**公開 post-mortem を書いた 101 社の自己申告**です。しかも CB Insights 自身が現在（2026-03-05）は n=431（2023 年以降に閉鎖した VC 出資企業）で「資金枯渇 70% / product-market fit 不良 43% / timing・macro 29% / unit economics 19%」と公表しています | **原典あり・誇張**（時点が 10 年古く、標本が自己選択） | 高 |
| 3 | 「red ocean を避けて blue ocean へ」 | **数字はあり、標本の裏付けは公開されていません**。Kim & Mauborgne は 108 社の事業立ち上げを調査したとし、86% が既存空間の line extension で売上 62%・利益 39%、残り 14% が blue ocean 創出で売上 38%・**利益 61%** としています | 108 社が誰か、どう抽出したか、期間はいつかが公表されておらず、第三者が再現できません。学術側の批判は「成功事例のみを分析した survivorship bias」「hypothesis も proof も無く理論ではない」に集中しています。当方が取得できた査読論文（Butt 2024, IJBM 19(6)）は Porter の positioning 論との対比という**概念的**な反証で、実証的反証ではありません | **原典あり・誇張**（数字は存在するが検証不能） | 中 |
| 4 | 「先行者利益がある／早く出した者が勝つ」 | **あり、そして明確に否定されています**。Golder & Tellis "Pioneer Advantage: Marketing Logic or Marketing Legend?" *Journal of Marketing Research* 30(2), 1993, pp. 158-170 | 約 500 brand / 50 product category を歴史分析。abstract より: "almost half of market pioneers fail and their mean market share is much lower than that found in other studies. Also, early market leaders have much greater long-term success and **enter an average of 13 years after pioneers**"。著者は先行研究が pioneer 有利に見えた理由を 3 つ挙げます — PIMS / ASSESSOR database が**生存者のみを含む**こと、単一回答者の**自己申告**で pioneer を分類していること、そして「pioneer が消えた後、同じ市場の成功企業が自分を pioneer だと見なすようになる」こと | **原典あり・反証あり**。folklore が誤り | 高 |
| 5 | 「MVP を 2 週間で作って市場に出せ」 | 「MVP」の原典はあり、**「2 週間」は原典に存在しません**。Eric Ries, "Minimum Viable Product: a guide"（2009-08-03） | Ries の定義は "that version of a new product which allows a team to collect the maximum amount of validated learning about customers with the least effort" で、期間の規定はありません。彼自身の IMVU の MVP は **6 か月**かかっており、別の 2 週間の feature については「かけ過ぎだった」と評しています。Ries は MVP が "decidedly not formulaic" だと明記しています | **原典あり・誇張**（期間は後付けの創作） | 高 |
| 6 | 「1,000 true fans で食える」 | **あり、かつ提唱者本人による反証もあり**。Kevin Kelly, "1000 True Fans"（2008-03-04）／"The Case Against 1000 True Fans"（2008-04-27） | 原典は「1 fan が年 100 ドル × 1,000 人＝年 10 万ドル」という**思考実験**で、実証 data はありません（Ruth Towse 1995 の芸術家所得研究を引くのみ）。Kelly は本人が「これは fortune ではなく living だ」と限定しています。反証記事では、True Fans model で実際に生計を立てている creator の財務 data を 7 人分しか集められず、**生計の全部**を賄えている者は「絵画のような高単価品を売る者」に限られ、"there are very few artists making their entire living selling directly to True Fans" と結論しました。さらに Jaron Lanier の「新 media 環境だけで生計を立てた musician は 1 人もいない」という主張に対し、Kelly は反例を募集した上で "If none are offered, I surrender the case to Jaron" と書いています | **原典あり・反証あり**（反証者が提唱者本人） | 高 |
| 7 | 「product-market fit は Sean Ellis test の 40% で測れる」 | **あり**。Sean Ellis, startup-marketing.com, 2009 年 5 月。原文の該当箇所: "If however, you find that over 40% of your users are saying that they would be 'very disappointed' without your product, there is a great chance you can build a successful business" | **原典に、40% の根拠となる標本・分析・分布は示されていません。** 「約 100 社の観察に基づく」という説明は二次情報でのみ流通しており、当方は原典側での裏付けを確認できませんでした（web.archive.org が当方から取得不可のため、月別 archive page 経由の間接確認）。批判として Tristan Kromer（Kromatic, 2014-04-08 / 2023-08-03 更新）は、40% 超は false positive を出すと指摘します — 回答者は「解決の約束」に反応しうる、40% 未満は PMF 不在を示唆するが 40% 超は PMF を意味しない（十分条件ではない）、market size を全く見ていない | **原典あり・誇張**（threshold の実証的裏付けが原典に無い。判定の道具としてではなく、「40% 未満なら赤信号」という**片側の**指標として使うのが妥当） | 中〜高 |
| 8 | 「SaaS の理想 churn は月 3% 以下」 | 「理想」の原典は特定できませんでしたが、**実測 data は存在します**。ChartMogul SaaS Benchmarks Report 2023（2,100 社超、2023-03 までの 12 か月、実 billing data） | 同 report は「product market fit を得て成長するにつれ、customer churn の中央値はまず低下し、その後**月 3〜4% で安定する**」としています。つまり月 3% は**理想ではなく中央値**です。別報告（SaaS Retention Report、2,500 社超、2021〜2024 の上期）では、NRR 100% 以上の企業群の churn 中央値が約 3.5%、低 NRR 群は 7% で倍。なお ChartMogul は ARR 30 万ドル未満の企業を一部分析から除外しており、**最小規模帯の benchmark は公表されていません** | **原典あり・誇張**（数値自体は実測と整合するが、「理想」ではなく「中央値」。個人 SaaS の規模帯の data は存在しない） | 中〜高 |
| 9 | 「niche に絞れば勝てる」 | **到達できず**。この主張を直接支持する査読研究の原典を、今回の調査では特定できませんでした | 隣接する堅い証拠は #4 の Golder & Tellis で、そこでの勝者は「pioneer」でも「niche 特化」でもなく **early market leader**（pioneer の平均 13 年後に参入）です。「絞る」ことの効用と「小さいまま終わる」ことの区別を data で示した source を、当方は見つけられませんでした | **原典に到達できず**。folklore として扱ってください | 中（「見つからなかった」ことの確信度） |
| 10 | 「AI で誰でも SaaS が作れる時代」 | 主張側に data 出典はありません。**反対側に実測 RCT があります**。METR, "Measuring the Impact of Early-2025 AI on Experienced Open-Source Developer Productivity"（2025-07-10, arXiv:2507.09089） | 熟練 open-source developer 16 人 / 実 issue 246 件を、AI 使用可否で無作為割付。結果は **AI 使用時に 19% 遅い**。事前予測は「24% 速くなる」、事後の自己評価は「20% 速くなった」。**測定と体感が逆を向きました。** 著者は generalization について極めて慎重で、「AI が大多数の developer を速くしていないことの証拠ではない」「この developer 集団と repository 種別を超えて一般化しない」と明記しています。METR 自身が現在この結果を historical と label し、現行の tool や workflow を必ずしも反映しないとしています | **原典あり・反証あり**（ただし反証も限定条件付き。正しい読み方は「AI が遅くする」ではなく「**生産性の体感は測定の代わりにならない**」） | 高 |
| 11 | 「副業で月 30 万円／月 100 万円」 | 個別事例には原典がありますが、**分布の原典は公的統計側にあります** | JILPT 調査 series No.245「副業者の就労に関する調査」（2024-07、調査実施 2022-10、副業者 n=11,358、web monitor 調査）: 副業の 1 か月あたり収入は**平均 92,445 円 / 中央値 50,000 円**。最頻帯は「5 万円以上 10 万円未満」30.0%、**5 万円未満が 4 割超**。本業が正社員の層では平均 100,526 円 / 中央値 50,000 円。副業の理由は「収入を増やしたいから」54.5%、「1 つの仕事だけでは収入が少なくて、生活自体ができないから」38.2%。／総務省「令和 4 年就業構造基本調査」（2023-07-21 公表）: 副業がある者は **305 万人**、副業者比率 **4.8%**、うち**正規の職員・従業員では 2.5%** | **原典あり・誇張**。「月 30 万円」は分布の上端の話であり、中位の副業者の 6 倍です。記事が分布を示さず金額だけを出す場合、それは統計ではなく広告です | 高 |
| 12 | 「SEO で集客すればよい」 | — | Ahrefs（2023-12-01、約 140 億 page）: **96.55% の page が Google からの流入ゼロ**。加えて Bevendorff et al.（ECIR 2024）は product review 領域の検索結果が affiliate に占拠されていることを示しています。個人が新規に参入して勝つ前提には、この 2 つの分母が乗ります | **原典あり・妥当**（ただし「SEO は無駄」ではなく「既定値は流入ゼロであり、それを覆す理由の説明が必要」という意味） | 中〜高 |
| 13 | 「Google は AI 記事を penalize する」 | **半分正しい** | Google の spam policy は「どう作られたかに関わらず（no matter how it's created）」規模生成・非独自・無付加価値を問題にしています。rater guidelines も "no matter how they are created" と明記した上で Lowest を指示します。つまり判定軸は **AI か人間かではなく、規模・独自性・付加価値**です。実効も出ており、March 2024 core update 後に低品質・非独自 content を 45% 削減したと Google 自身が公表しています | **原典あり・誇張**（判定軸の取り違え） | 高 |
| 14 | 「review 記事は実際に使った人が書いている」 | — | 消費者庁が「アフィリエイターが成果報酬を求めて虚偽誇大広告を行う incentive が働きやすい」「一般的に広告主は掲載後に全ての表示内容の確認を行ってない」と明記（2022-02-15）。日本のステマ規制（2023-10-01 施行）の**規制対象は広告主のみ**で、書き手側に表記義務はありません。米国は 2024-10-21 施行の FTC 規則で偽 review・対価付き sentiment 誘導を禁止し、知情違反に 1 件 51,744 ドルの制裁金 | **原典あり・反証あり**。既定値を「実体験である」から「成果報酬である」に置き換えてください | 高 |

### 検証の結果、妥当だったもの（都合よく解体しなかった項目）

- **#12（SEO の分母）** は folklore ではなく、data に支持されます。
- **#8（月 3% churn）** は「理想」という言葉遣いが不正確なだけで、数値自体は実 billing data の中央値と一致します。
- **「科学的 approach は entrepreneur の成果を改善する」** — これは folklore ではなく、実際に RCT があります。Camuffo, Cordova, Gambardella, Spina, *Management Science*（online 2019-08-08, doi:10.1287/mnsc.2018.3249）は Italy の startup 116 社・約 1 年・16 時点の RCT で、「theory を立てて仮説を厳密に test する」訓練を受けた群は成果が良く、pivot しやすく、早期の脱落は増えなかったと報告しました。ただし**続報で結論の一部が変わっています**: 同 group の大規模 replication（Camuffo et al., *Strategic Management Journal* 45(6), 2024, pp. 1209-1237, 759 社・4 RCT）では「**idea termination への正の効果**」が観測され、radical pivot への非線形効果が示されました。つまり「脱落は増えない」が「駄目な idea を早くたたむようになる」に更新されています。**良質な証拠でも改訂されるという事実そのものが、単発の記事を信じない理由です。**

---

## 3. 煽り記事の判別 checklist（そのまま運用する形）

使い方: 記事を開いたら上から順に見て、**赤 signal が 2 つ以上あればその記事の数字は採用しない**。黄は 3 つで赤 1 つ扱い。所要は 1 記事あたり 60〜90 秒です。

### A. 数字の身元（最優先。ここだけで大半が落ちます）

| # | signal | 色 | 根拠 |
|---|---|---|---|
| A1 | 数字に出典 link が無い | 赤 | 検証不能な数字は数字ではありません |
| A2 | 出典 link を踏むと別のまとめ記事・別の blog に着く | 赤 | #1 の「90%」がこの形で行き止まりました |
| A3 | 標本数（n）が書かれていない | 赤 | #2 の 42% は n=101 の自己申告と知って初めて意味が決まります |
| A4 | 期間・調査時点が書かれていない | 赤 | #2 は 2016 年の PDF が 2026 年に現在形で流通しています |
| A5 | 分母が書かれていない（「〇% が成功」の母集団が不明） | 赤 | 「90% 失敗」は定義次第で 30〜95% に動きます |
| A6 | 平均だけで中央値・分布が無い | 黄 | 副業月収は平均 9.2 万・中央値 5 万で、印象が倍違います |
| A7 | 「調査によると」「海外のデータでは」で調査名が無い | 赤 | — |
| A8 | 記事の公開日はあるが、引用元の発行年が無い | 黄 | — |

### B. 利害（誰が得をするか）

| # | signal | 色 | 根拠 |
|---|---|---|---|
| B1 | 本文中の product link が ASP domain を経由する（a8.net, moshimo, valuecommerce, linksynergy, amazon.co.jp の `tag=` 等） | 黄（単独では黒ではありません） | 消費者庁が誇大表示 incentive を明記。ただし affiliate＝嘘ではありません |
| B2 | affiliate link が結論部より**前**に置かれている | 赤 | 判断材料を出す前に click させる設計です |
| B3 | 「PR」「広告」表記が無いのに、特定 1 product へ強く誘導する | 黄 | 日本のステマ規制は広告主のみを縛るため、表記が無いことは無 incentive の証拠になりません |
| B4 | 記事の終端が LINE 登録・無料 seminar・note 有料版・「詳しくは公式へ」 | 赤 | 記事本体が情報ではなく lead 獲得の道具です |
| B5 | 比較記事なのに「勝者」が固定で、劣後 product の具体的欠点が書かれていない | 赤 | 比較の体裁をとった単品広告です |
| B6 | 「限定」「今だけ」「あと〇名」 | 赤 | 情報の価値に期限は無く、販売にだけ期限があります |

### C. 著者

| # | signal | 色 | 根拠 |
|---|---|---|---|
| C1 | 著者名が無い、または「編集部」のみ | 赤 | Google の rater guideline も content creator の特定を評価軸に置きます |
| C2 | 実績が「月商〇〇万円」だけで、法人・service 名・公開 data のいずれも辿れない | 赤 | 検証不能な実績は実績ではありません |
| C3 | 一次体験の痕跡が無い（実際の screenshot、失敗、金額、日付、固有名詞） | 赤 | Google の self-assessment: "Does your content clearly demonstrate first-hand expertise ... expertise that comes from having actually used a product or service" |
| C4 | 著者への連絡手段・訂正窓口が無い | 黄 | 訂正できない媒体は訂正しません |

### D. 記事の構造

| # | signal | 色 | 根拠 |
|---|---|---|---|
| D1 | 更新日が無い、または「2026 年最新」と書いてあるのに本文の最新言及が数年前 | 赤 | — |
| D2 | 成功例のみで失敗例・不採用理由が無い | 赤 | survivorship bias。Golder & Tellis が実証した通り、生存者だけを見ると結論が反転します |
| D3 | 「〇〇選」「完全ガイド」で網羅的だが、どの項目も 3 行 | 黄 | Google の red flag: "Are you mainly summarizing what others have to say without adding much value?" |
| D4 | 同一 site 内の記事の構成・長さ・見出しが機械的に均一 | 黄 | NewsGuard の AI content farm 認定 4 条件の 1 つ（人的 review の欠如） |
| D5 | 公開頻度が 1 日数十本 | 赤 | 同上（"produce dozens of articles a day"） |
| D6 | comment 欄・言及先が閉じており、外部からの反論経路が無い | 黄 | 誤りが表に出ない構造です |
| D7 | 「誰でも」「簡単に」「たった〇日で」「〇〇するだけ」 | 赤 | 分布の存在を否定する語です。中央値 5 万円の世界で「誰でも 30 万」は分布の主張として偽です |

### E. AI 生成らしさ（**単独では絶対に使わない**弱い signal）

D4・D5 と併せて初めて意味を持ちます。文体だけで断定してはいけません。

- 「〜とは」「メリット・デメリット」「まとめ」の定型三段構成
- 固有名詞・具体的数値・日付が極端に少ない
- 「重要です」「不可欠です」「〜と言えるでしょう」の多用
- 見出しだけ具体的で本文が一般論

**AI 検出器 tool の出力を根拠にしないでください。** 提供元の精度は自己申告であり、Ahrefs 自身が「完璧な検出器は存在しない」と明記し、学術研究（Wikipedia 論文）ですら false positive 1% に校正した上で「下限」しか語りません。

### 判定を機械的にする

```
赤 signal を数える。
  赤 >= 2  → この記事の数字は採用しない（記事自体は読んでよい。仮説の種にはなる）
  赤 == 1  → 数字は原典に当たれた分だけ採用
  赤 == 0 かつ 黄 <= 2 → 採用候補。ただし原典 link を 1 回は踏む
```

**重要な使い分け**: この checklist は「その記事の**数字**を採用してよいか」の判定です。「読む価値があるか」の判定ではありません。赤だらけの記事でも、「こういう商材が売られている」「こういう不満が語られている」という**観察対象**としては価値があります。数字と観察を混ぜないでください。

---

## 4. 信頼できる source の list

### 4.1 なぜ信頼できるか — 判定基準（5 条件）

分野別の list に入る前に、基準を先に置きます。以下 5 つのうち **4 つ以上**を満たす source を「信頼できる」と扱います。個々の名前ではなく、この基準こそが再利用可能な資産です。

1. **生成過程が書いてある** — 誰が、いつ、どうやって、どの母集団から集めたか。
2. **分母と期間が明示されている** — n と観測窓。
3. **反証可能である** — raw data・sample frame・code のいずれかが出ている、または第三者が再現できる手順が書いてある。（Blue Ocean の 108 社はここで落ちます）
4. **訂正履歴がある** — 誤りを訂正した記録が公開されている。（Camuffo らが自分の 2020 年の結論を 2024 年に更新したのが good example。METR が自 study を historical と label したのも同様）
5. **利害が開示されており、かつ利害に逆らう結論も出す** — 自社に不利な数字を出したことがあるか。（Kevin Kelly が自説の反証記事を書いたのが典型）

### 4.2 分野別 list

**査読 journal（経営・marketing・経済）**

| source | 何に使うか | 備考 |
|---|---|---|
| *Journal of Marketing Research* | 参入順序、brand、価格 | Golder & Tellis 1993 の掲載誌 |
| *Marketing Science* | 需要推定、価格、広告効果 | — |
| *Management Science* | 意思決定、entrepreneurship の RCT | Camuffo et al. 2020 |
| *Strategic Management Journal* | 戦略、replication | Camuffo et al. 2024 |
| *Journal of Business Venturing* | 起業家行動、失敗研究 | — |
| *American Economic Review* / *Journal of Political Economy* | 労働・産業組織 | — |
| ECIR / SIGIR / WWW（情報検索の国際会議） | 検索品質、spam | Bevendorff et al. 2024 |

使い方: **Google Scholar で「被引用数」ではなく「その後の replication があるか」を見てください。** 単発の有名論文より、追試された地味な論文が強いです。

**working paper（査読前。使ってよいが「速報」扱い）**

- NBER Working Papers（`nber.org/papers`）
- SSRN（`papers.ssrn.com`）
- arXiv（`arxiv.org` cs.CY / econ.GN / cs.SE）— METR の study もここ
- 注意: 査読前です。「査読を通っていない」ことを明記した上で使ってください。

**公的統計（日本）**

| source | URL | 何が取れるか |
|---|---|---|
| e-Stat（政府統計の総合窓口） | `e-stat.go.jp` | 全省庁統計の入口。table 単位で download 可能 |
| 総務省統計局 就業構造基本調査 | `stat.go.jp/data/shugyou/` | 副業者数・副業者比率・雇用形態別（5 年ごと、直近 令和 4 年） |
| JILPT（労働政策研究・研修機構） | `jil.go.jp` | 副業の月収分布・平均・中央値（調査 series No.245） |
| 国税庁 民間給与実態統計調査 | `nta.go.jp` | 給与所得の分布 |
| 中小企業庁 中小企業白書 | `chusho.meti.go.jp/pamflet/hakusyo/` | 開業率・廃業率・生存率（**当方の fetcher は 403。要手動確認**） |
| 消費者庁 | `caa.go.jp` | 表示規制、affiliate 広告、ステマ規制、措置命令の実例 |
| 国民生活センター | `kokusen.go.jp` | 副業・情報商材の相談実態（**当方が試した URL は 404。site 内検索で要確認**） |

**公的統計（米国）**

| source | URL | 何が取れるか |
|---|---|---|
| US Census Business Formation Statistics (BFS) | `census.gov/econ/bfs/` | 事業所開業申請の週次・月次 |
| US Census Business Dynamics Statistics (BDS) | `census.gov/programs-surveys/bds.html` | 企業の年齢別・規模別の参入退出 |
| BLS Business Employment Dynamics | `bls.gov/bdm/` | establishment の生存率（1 年 約 79% / 5 年 約 50% / 10 年 約 33%）。**当方の fetcher は 403** |
| Federal Reserve SHED | `federalreserve.gov/consumerscommunities/shed.htm` | 家計の経済状況。2025 年版は約 13,000 人（2025-10 実施、2026-05-13 公表）。**ただし 2025 年版に gig work の収入節は見当たりませんでした** |
| IRS Statistics of Income | `irs.gov/statistics` | 申告 base の所得分布 |

**platform 実測 data（第三者が観測している）**

| source | 何が取れるか | 利害と限界 |
|---|---|---|
| ChartMogul SaaS Benchmarks / Retention Report | 実 billing data 由来の churn・NRR・成長率（2,100〜2,500 社） | 自社顧客 base のため、ChartMogul を使う規模・種類の SaaS に偏ります。ARR 30 万ドル未満は一部分析から除外 |
| Ahrefs 各種 study | crawl / index 由来の web 全体の傾向 | SEO tool 販売が本業。caveat の開示は誠実 |
| NewsGuard AI Tracking Center | AI content farm の site 数と認定基準 | 認定は人手。基準が公開されている点が強い |
| Originality.ai 検索結果調査 | 検索上位の AI content 比率の時系列 | **AI 検出器の販売元**。検出器の精度は自己申告。時系列の形は参考になりますが、水準は割り引いて読んでください |

**実 data を開示している企業**

| source | 何が出ているか | 確認状況 |
|---|---|---|
| Buffer Open（`buffer.com/open`） | MAU 239,753 / MRR 220 万ドル / ARR 2,600 万ドル / ARPU 27.26 ドル、給与、株主向け月次報告（直近 2025-12） | **2026-08-11 に稼働確認済み**。open metrics 開示の現行 best example |
| Baremetrics Open Startups | かつての複数社の live 指標 | **`baremetrics.com` が DNS 解決に失敗。現存を確認できませんでした。参照しないでください** |
| Indie Hackers products | 個人 SaaS の売上 | **502 で確認できず。売上は原則として本人の自己申告であり、検証済み data ではありません** |

**実務家の判定基準（名前ではなく基準で選んでください）**

以下を**すべて**満たす個人だけを「実務家 source」として扱います。

1. 数字を継続的に（単発でなく）開示している
2. 失敗と撤退も同じ粒度で書いている
3. 測り方（定義・期間・除外条件）を書いている
4. 収益の主たる source が「その情報を売ること」ではない
5. 過去の主張を訂正した記録がある

**4 が最重要です。** 副業の作り方を教えることで生計を立てている人の副業論は、本人が正直でも構造的に偏ります（消費者庁が affiliate について書いた incentive 構造と同じ論理です）。

---

## 5. Evidence hierarchy（市場調査向け）

| 層 | 種類 | 何に使ってよいか | 何に使ってはいけないか |
|---|---|---|---|
| 1 | **自分の実験 data**（自分の landing page、自分の広告、自分の顧客への課金） | 意思決定の最終根拠。「作るか / やめるか」 | 他人の市場への一般化 |
| 2 | **実測された platform data**（ChartMogul の billing data、Ahrefs の crawl、Stripe の決済） | 相場観の設定、自分の数字が異常かの判定 | 「この benchmark に届けば成功」という目標化（母集団が自分と違います） |
| 3 | **査読研究**（replication があるものを優先） | 因果の方向、bias の名前、既定値の設定 | 個別 product の意思決定（外的妥当性が足りません） |
| 4 | **公的統計** | 分母・分布・上限の把握。「月 30 万は分布のどこか」 | 因果の説明（相関しか無い場合が大半） |
| 5 | **企業の report（利害あり）** | 業界の構造理解、仮説の種 | 数字の直接引用（分母と除外条件を必ず読むこと） |
| 6 | **実務家の実 data 開示** | 経路の具体像（何をいつやったか） | 確率の推定（n=1 です） |
| 7 | **逸話・体験談** | 質問の発見。「何に困っているか」 | 数字の根拠 |
| 8 | **出典なき記事** | 「こういう言説が流通している」という観察 | 一切の根拠 |

### 層をまたぐときの禁止事項

- **上の層と下の層が矛盾したら、上を採ってください。** 例外はありません。下の層に「でも現場では」という反論があっても、それは層 7 です。
- **層 3〜5 の数字を層 1 の代わりに使わないでください。** benchmark は「自分の数字を解釈する物差し」であって「目標」ではありません。ChartMogul の churn 中央値 3〜4% は、ChartMogul を使う規模の SaaS の話であり、個人 SaaS の話ではありません。
- **層 7 を層 1 と誤認しないでください。** 他人の体験談は、あなたの実験ではありません。
- **層をまたぐ引用の連鎖に注意してください。** 層 8 の記事が層 3 の論文を引用していても、その記事は層 8 のままです。原典に当たった瞬間に層 3 に上がります。

---

## 6. 情報を受け取る側の作法

### 6.1 数字を見たら必ず問う 7 つの質問

1. **標本は誰ですか。**（n はいくつ、どの母集団から、どう選ばれたか）
2. **期間はいつですか。**（調査時点と、記事の公開日は別物です）
3. **誰が集めましたか。**（当事者の自己申告か、第三者の観測か）
4. **分母は何ですか。**（「成功率 10%」の分母は全起業家か、VC 出資企業か、post-mortem を書いた人か）
5. **中央値はいくつですか。**（平均だけの提示は、分布を隠す最も一般的な手口です）
6. **誰が得をしますか。**（この数字が広まると、誰の売上が増えますか）
7. **反証はどこにありますか。**（この主張を否定する data を、著者は探した形跡がありますか）

質問 5 と 6 が特に効きます。今回の検証で、**副業月収**（平均 9.2 万 vs 中央値 5 万）と **AI 生産性**（体感 +20% vs 実測 −19%）の 2 件は、この 2 問だけで結論が変わりました。

### 6.2 原典への辿り方（具体手順）

**手順 A: 引用の連鎖を遡る（所要 3〜10 分）**

1. 記事内の数字の直近の出典 link を踏みます。
2. 着いた先が「別のまとめ記事」なら、そこでさらに出典を探します。
3. **これを 3 hop まで**行い、原典（論文・報告書・公式統計）に着かなければ**その数字を捨てます**。
   - 実例: 「90% 失敗」は Failory → Startup Genome 2019 → Small Biz Trends で行き止まりでした。3 hop で着かない典型です。
4. 原典に着いたら、**abstract ではなく method 節**を読みます。n・期間・母集団・除外条件の 4 つだけ確認すれば十分です。

**手順 B: 原典が特定の論文だと分かっている場合**

1. Google Scholar（`scholar.google.com`）で題名を検索します。
2. 著者個人 site（`*.edu` / 研究室 page）に PDF が置いてあることが多いです。今回も Golder & Tellis は `gtellis.net` で全文が取れました。
3. 出版社 site が有料でも、著者版・大学 repository 版（`openaccess.city.ac.uk` のような機関 repository）が公開されている場合が大半です。Camuffo et al. 2024 はこれで取れました。
4. **「この論文を引用している」を必ず見てください。** 後年の replication で結論が変わっていることがあります（Camuffo 2020 → 2024 がまさにそれです）。

**手順 C: 記事が消えている／改変されている場合**

- Wayback Machine（`web.archive.org/web/*/対象URL`）で過去 version を見ます。
- 用途: (a) 「2026 年最新」と称する記事が実は 2019 年から中身が変わっていないことの確認、(b) 削除された主張の確認、(c) 数字がいつ書き換えられたかの確認。
- **注意**: 当方の tool からは web.archive.org に到達できませんでした。この手順は人手で行ってください。

**手順 D: PDF が読めないとき**

公的統計や報告書の PDF は、機械抽出に失敗することがよくあります（今回、消費者庁・総務省・JILPT・CB Insights の PDF はすべて通常の取得では読めず、PyMuPDF での text 抽出が必要でした）。手元で読む場合は browser の text 検索より、PDF viewer の全文検索のほうが確実です。

### 6.3 記録の作法

原典に当たった数字は、その場で次の形で控えてください。後から「あの数字どこだっけ」を繰り返さないためです。

```
主張: 副業の月収中央値は 5 万円
数値: 中央値 50,000 円 / 平均 92,445 円 / n=11,358
標本: web monitor 調査、2022-10-03〜10-13 実施、18〜64 歳の有職者
出典: JILPT 調査シリーズ No.245「副業者の就労に関する調査」2024-07
URL: https://www.jil.go.jp/institute/research/2024/documents/0245.pdf (p.52)
確認日: 2026-08-11
限界: web monitor 調査のため無作為標本ではない。総務省の副業者比率 4.8% に対し
      本調査の 6.0% は上振れしており、副業者が過剰代表の可能性
```

**限界を書く欄を必ず設けてください。** 限界を書けない数字は、まだ理解していない数字です。

---

## 7. 参考文献（すべて 2026-08-11 確認）

### 情報空間の汚染

- Ahrefs, "What Percentage of New Content Is AI-Generated?" — https://ahrefs.com/blog/what-percentage-of-new-content-is-ai-generated （2025 年、90 万 page、74.2%）
- Ahrefs, "96.55% of Content Gets No Traffic From Google" — https://ahrefs.com/blog/search-traffic-study/ （2023-12-01、約 140 億 page）
- Originality.AI, "Amount of AI Content in Google Search Results — Ongoing Study" — https://originality.ai/ai-content-in-google-search-results
- Originality.AI, "2025: Year in Review" — https://originality.ai/blog/year-in-review-2025
- Brooks, C., Eggert, S., Peskoff, D., "The Rise of AI-Generated Content in Wikipedia", arXiv:2410.08044（2024-10-10） — https://arxiv.org/abs/2410.08044
- Bevendorff, J., Wiegmann, M., Potthast, M., Stein, B., "Is Google Getting Worse? A Longitudinal Investigation of SEO Spam in Search Engines", ECIR 2024 — https://link.springer.com/chapter/10.1007/978-3-031-56063-7_4 （当方は 403。dblp: https://dblp.org/rec/conf/ecir/BevendorffWPS24.html）
- NewsGuard, "AI Tracking Center" — https://www.newsguardtech.com/special-reports/ai-tracking-center/ （2026-06-23 更新、3,749 site）

### Google の公式 document

- Google, "Spam policies for Google web search" — https://developers.google.com/search/docs/essentials/spam-policies
- Google, "Google Search update March 2024" — https://blog.google/products/search/google-search-update-march-2024/ （40% 目標 → 2024-04-19 に 45% 達成）
- Google, "Updating our site reputation abuse policy"（2024-11） — https://developers.google.com/search/blog/2024/11/site-reputation-abuse
- Google, "Creating helpful, reliable, people-first content" — https://developers.google.com/search/docs/fundamentals/creating-helpful-content
- Google, "General Guidelines"（Search Quality Rater Guidelines, 2025-09-11 版） — https://guidelines.raterhub.com/searchqualityevaluatorguidelines.pdf

### 広告・表示規制

- 消費者庁「アフィリエイト広告等に関する検討会 報告書」令和 4 年 2 月 15 日 — https://www.caa.go.jp/notice/entry/027592/ （PDF: https://www.cao.go.jp/consumer/iinkai/2022/367/doc/20220303_shiryou1.pdf）
- 消費者庁「ステルスマーケティングは景品表示法違反となります」（令和 5 年 10 月 1 日施行） — https://www.caa.go.jp/policies/policy/representation/fair_labeling/stealth_marketing/
- FTC, "Federal Trade Commission Announces Final Rule Banning Fake Reviews and Testimonials"（2024-08-14、施行 2024-10-21） — https://www.ftc.gov/news-events/news/press-releases/2024/08/federal-trade-commission-announces-final-rule-banning-fake-reviews-testimonials （当方は 403。Federal Register: https://www.federalregister.gov/documents/2024/08/22/2024-18519/trade-regulation-rule-on-the-use-of-consumer-reviews-and-testimonials）

### folklore の原典

- CB Insights, "The Top 20 Reasons Startups Fail"（PDF 作成日 2016-07-27、n=101） — https://s3-us-west-2.amazonaws.com/cbi-content/research-reports/The-20-Reasons-Startups-Fail.pdf
- CB Insights, "Why Startups Fail: Top 9 Reasons"（2026-03-05 更新、n=431） — https://www.cbinsights.com/research/report/startup-failure-reasons-top/
- Golder, P. N., Tellis, G. J., "Pioneer Advantage: Marketing Logic or Marketing Legend?", *Journal of Marketing Research* 30(2), 1993, pp. 158-170 — https://gtellis.net/wp-content/uploads/2020/09/pioneering-advantage-marketing-logic-or-marketing-legend.pdf
- Kelly, K., "1000 True Fans"（2008-03-04） — https://kk.org/thetechnium/1000-true-fans/
- Kelly, K., "The Case Against 1000 True Fans"（2008-04-27） — https://kk.org/thetechnium/the-case-agains/
- Ellis, S., startup-marketing.com 2009 年 5 月 archive — https://www.startup-marketing.com/2009/05/
- Kromer, T., "Product Market Fit Survey: Why the 40% Test Gives False Positives"（2014-04-08 / 2023-08-03 更新） — https://kromatic.com/blog/false-positives-and-product-market-fit/
- Ries, E., "Minimum Viable Product: a guide"（2009-08-03） — https://www.startuplessonslearned.com/2009/08/minimum-viable-product-guide.html
- Butt, M. A., "Blue Ocean Strategy: Thesis and Antithesis", *International Journal of Business and Management* 19(6), 2024, pp. 199-208 — https://doi.org/10.5539/ijbm.v19n6p199
- nanoglobals, "Is It True That 90% of Startups Fail?"（引用連鎖の追跡） — https://nanoglobals.com/startup-failure-rate-myths-origin/

### 実証研究

- Camuffo, A., Cordova, A., Gambardella, A., Spina, C., "A Scientific Approach to Entrepreneurial Decision Making: Evidence from a Randomized Control Trial", *Management Science*（online 2019-08-08, doi:10.1287/mnsc.2018.3249, n=116） — https://gwern.net/doc/economics/2019-camuffo.pdf
- Camuffo, A., Gambardella, A., Messinese, D., Novelli, E., Paolucci, E., Spina, C., "A scientific approach to entrepreneurial decision-making: Large-scale replication and extension", *Strategic Management Journal* 45(6), 2024, pp. 1209-1237（n=759、4 RCT） — https://openaccess.city.ac.uk/id/eprint/32437/
- Becker, J., Rush, N., Barnes, E., Rein, D., "Measuring the Impact of Early-2025 AI on Experienced Open-Source Developer Productivity", METR（2025-07-10, arXiv:2507.09089） — https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/
- METR, "We are Changing our Developer Productivity Experiment Design"（2026-02-24、上記結果を historical と label） — https://metr.org/blog/2026-02-24-uplift-update/

### 統計・benchmark

- 総務省統計局「令和 4 年就業構造基本調査 結果の概要」（2023-07-21） — https://www.stat.go.jp/data/shugyou/2022/pdf/kgaiyou.pdf （副業者 305 万人、副業者比率 4.8%、正規 2.5%）
- JILPT 調査シリーズ No.245「副業者の就労に関する調査」（2024-07、n=11,358） — https://www.jil.go.jp/institute/research/2024/documents/0245.pdf （p.52 に月収分布：平均 92,445 円 / 中央値 50,000 円）
- ChartMogul, "SaaS Benchmarks Report"（2,100 社超、〜2023-03 の 12 か月） — https://chartmogul.com/reports/saas-benchmarks-report/
- ChartMogul, "The SaaS Retention Report: The New Normal for SaaS"（2,500 社超、2021〜2024 上期） — https://chartmogul.com/reports/saas-retention-the-new-normal/
- Buffer Open — https://buffer.com/open （2026-08-11 稼働確認、MRR 220 万ドル / ARR 2,600 万ドル）
- Federal Reserve, "Economic Well-Being of U.S. Households in 2025"（2026-05-13 公表、約 13,000 人） — https://www.federalreserve.gov/publications/files/2025-report-economic-well-being-us-households-202605.pdf
- e-Stat 政府統計の総合窓口 — https://www.e-stat.go.jp/

### 到達できなかった source（記録）

| 対象 | 状況 |
|---|---|
| web.archive.org 全般 | 当方の tool から取得不可（明示的に blocked）。Sean Ellis 2009 原文の全文確認ができませんでした |
| bls.gov（Business Employment Dynamics） | HTTP 403。生存率の数値は二次情報経由 |
| ftc.gov | HTTP 403。FTC 規則の内容は法律事務所 alert 経由 |
| chusho.meti.go.jp（中小企業白書） | HTTP 403。開業率・廃業率・生存率を一次確認できませんでした |
| SSRN / Springer Link | HTTP 403 / 認証 redirect |
| a16z "1,000 True Fans? Try 100"（Li Jin） | 2 通りの URL いずれも 404。**原典に到達できず、本文書では扱っていません** |
| baremetrics.com（Open Startups） | DNS 解決失敗。現存を確認できませんでした |
| indiehackers.com/products | HTTP 502。売上表示の検証可否を確認できませんでした |
| 国民生活センター 副業・情報商材の相談件数 | 試行した URL が 404。**日本の副業詐欺の実数を一次 source で示せませんでした** |
| Kim & Mauborgne の 108 社の sample frame | **そもそも公開されていない**と判断。第三者による再現は不可能です |

---

## 8. 一枚で持ち歩く要約

**捨ててよい数字**: 出典 link が無い / 3 hop で原典に着かない / n が無い / 期間が無い / 平均だけ。

**既定値として持つべき事実**:
- 新規 web page の 7 割超が AI 生成 content を含み、page の 96.55% は検索流入ゼロです。
- product review 系の検索結果は affiliate に占拠されており、誇大表示側に金銭 incentive がかかることを規制当局が明記しています。日本では書き手側に表記義務がありません。
- 副業月収の中央値は 5 万円、正社員の副業実施率は 2.5% です。
- 「先行者が勝つ」は査読研究で否定され、勝つのは平均 13 年後に入る early leader です。
- 「1,000 true fans」は提唱者本人が 7 週間後に反証しました。
- 生産性の体感は測定の代わりになりません（+20% と感じて −19% でした）。

**最も安い検証**: 数字を見たら「中央値は？」「誰が得する？」の 2 問だけ投げてください。今回の検証で結論が変わった件のほとんどが、この 2 問で落ちました。
