# A: 何を調べれば当たるのかの実証的根拠

調査担当: research team A / 作成日: 2026-08-11

本書は「個人・小規模のsoftware productの成否は何で決まるか」について、査読論文・working paper・政府統計・企業の公開dataなど一次情報のみを辿って整理したものです。まとめblog・rank記事・情報商材の類は一切採用しておりません。数字を引用する際は原典に当たり、辿れなかったものは「出典不明のfolklore」と明記しております。

---

## 0. 先に結論

| # | 結論 | 確信度 | 理由 |
|---|---|---|---|
| 1 | 「どのcategoryか」より「誰が・どの顧客に対してやるか」の方が結果を説明する | 高 | 米Census全数dataと75,000〜115,000件規模のapp実測dataが同方向 |
| 2 | 起業前の**斯業経験(same-industry work experience)** は上位成果と系統的に相関する。ただし効果量は「2倍前後」であって「決定的」ではない | 高 | Azoulay et al. (Census全数)、日本公庫調査、meta分析が一致 |
| 3 | 成功例からの逆算(「成功したSaaSはこうしていた」)は統計的に無効に近い。生存bias下では**risk行動が万能薬に見える** | 高 | Denrellの形式モデル+Golder & Tellisの実証的反例 |
| 4 | TAM/SAM/SOMはmicro SaaS規模では意思決定情報をほぼ持たない | 中 | 直接の査読批判は見つからず、実測data(category間差5.6倍 vs category内差400倍)からの導出 |
| 5 | 「調査のやり方」で結果が変わるという因果証拠は存在する。ただし出たのは**やめる判断**の改善であり、売上の増加ではない | 中 | RCT 2本(116社/759社)。売上効果は極少数のfirmに依存 |
| 6 | 有名な数字の多くは原典が辿れないか、辿れても意味が違う | 高 | 個別に原典検証済(第5章) |
| 7 | 律速はmarket選択ではなく**顧客・販路の開拓**である可能性が高い | 中 | 日本公庫n=1,990で開業時・現在ともに最上位の課題 |

---

## 1. Entrepreneurship研究の実証知見

### 1.1 年齢: 「若さ」は成功要因ではない

**Azoulay, Jones, Kim, Miranda (2020), "Age and High-Growth Entrepreneurship", American Economic Review: Insights 2(1): 65-82, DOI 10.1257/aeri.20180582**

米Census BureauのIRS K-1 data・LBD・LEHD・USPTO・VC databaseをlinkした**全数に近い行政data**です。2007-2014年に米国で従業員を1人以上雇った企業のfounder 2.7百万人が対象で、self-report surveyではありません。

| 指標 | 平均founder年齢 |
|---|---|
| 全new venture (n=2.7M) | 41.9歳 |
| 上位5%成長 | 42.1歳 |
| 上位1%成長 | 43.7歳 |
| 上位0.1%成長 (1,700人) | 45.0歳 |
| 買収・IPOによるexit | 46.7歳 |
| VC付き×起業hub (1,900人) | 39.5歳 |

条件付き成功確率については「50歳のfounderは30歳のfounderよりupper-tail成長を達成する確率が1.8倍」、回帰では「50歳は30歳の約2倍」と記述されております。NAICS 4桁のindustry fixed effectを入れても傾きは緩むが方向は変わりません。

対照として、同論文Table 1が示す通り、TechCrunch受賞者の平均は29歳、雑誌の「注目起業家」listは31歳です。**選択されたsampleを見ると若く見え、全数を見ると中年である**という構図そのものが、本書第4章の生存bias/選択biasの実例です。

確信度: **高**。全数行政data・self-report非依存・複数のsuccess定義で頑健。

### 1.2 斯業経験: 効果はあるが「2倍前後」

同論文が2.5百万人のfounderを過去の雇用履歴2,000万件にlinkして測った、上位0.1%成長の達成率です。

| founderの経験 | 上位0.1%成長の達成率 |
|---|---|
| 起業先industry(2桁NAICS)に経験なし | 0.11% |
| 同2桁NAICSに3年以上 | 0.22% |
| 同4桁NAICSに3年以上 | 0.24% |
| 同6桁NAICSに3年以上 | 0.26% |

近い分野・長い経験ほど成功率が上がり、「outsiderの方が破壊的idea を出す」という仮説は棄却されております。同論文は「industry experienceを入れても年齢のfixed effectは有意に残る」とも述べており、経験だけで年齢効果を説明し切れておりません。

> **数字の注意**: web上で広く流通する「同一狭industryで3年以上の経験があると成功率が85%高い」という表現は、NBER working paper 24489本文には見当たりませんでした。本文の実数は0.11%→0.26%(約2.4倍)です。**「85%」は二次報道由来の可能性が高く、引用しない方が安全です。**

確信度: **高**(0.11%/0.26%は原典本文から直接確認)。

### 1.3 反証: human capital全体の効果量は小さい

**Unger, Rauch, Frese, Rosenbusch (2011), "Human capital and entrepreneurial success: A meta-analytical review", Journal of Business Venturing 26(3): 341-358**

70の独立sample、N=24,733のmeta分析です。human capital(学歴・経験・知識・技能)と成功の相関は **rc = .098** にとどまりました。分散にすると約1%です。

ただしmoderatorの向きが本件に効きます。

- 「教育年数・経験年数」という投入量より「knowledge/skills」という成果量の方が相関が高い
- **task-relatedness(その事業と直接関係する知識)が高いほど相関が高い**
- 若い企業ほど相関が高い

つまり「経験年数」は薄い指標で、「その顧客のその作業について何を知っているか」まで具体化して初めて効いてまいります。第1.2節と矛盾はせず、**粗い代理変数で測ると効果は消える**という警告として読むべきです。

確信度: **高**(meta分析、N大)。ただし「成功」の定義がstudy間で不統一という限界があります。

### 1.4 prior startup experience: 効くが、効いているのは「industry-yearの選択」

**Gompers, Kovner, Lerner, Scharfstein (2010), "Performance persistence in entrepreneurship", Journal of Financial Economics 96(1): 18-32**

VC出資を受けたentrepreneurについて、success = IPO到達と定義した場合の次回成功率です。

| 前回の結果 | 次回の成功確率 |
|---|---|
| 前回成功 | 30% |
| 前回失敗 | 22% |
| 初回 | 21% |

注目すべきは分解結果です。著者らは成功を「market timing skill(良いindustry×良い年に始めたこと)」と「同期他社に対するoutperformance(経営・ideaの質)」に分け、**次回成功を最もよく予測するのは前者**だと報告しております。例として、1983年創業のcomputer startupは52%がIPOに到達し、1985年創業は18%でした。しかも、industry-yearの選択が上手いentrepreneurは次回もそれが上手く、outperformanceが上手いentrepreneurは次回のindustry-year選択は上手くなりませんでした。

**この論文はuserの前提と正面から緊張関係にあります。**「いつ・どのindustryで始めるか」が持続的skillとして観測されているためです。ただし読み方には条件がございます。

- 定義しているのは「IPOに到達するVC-backed venture」であり、micro SaaS/stock型businessの分布ではございません
- 著者ら自身が、持続性の一部は実skillでなく**「成功者だと見なされることで供給者・顧客が資源を出す」という自己成就**である可能性を強調しております
- 「良いindustry-year」は事後に決まる変数であり、事前に測れる調査項目ではありません

確信度: **中**。findingは頑健ですが、対象母集団(VC-backed、IPO)が本件と大きく異なります。

### 1.5 user entrepreneurship: 実在するが、比率は生存条件付き

**Shah & Tripsas (2007), "The accidental entrepreneur", Strategic Entrepreneurship Journal 1: 123-140**
**Shah, Winston Smith, Reedy (2012), "Who Are User Entrepreneurs?", Kauffman Firm Survey**

Kauffman Firm Surveyは2004年創業の米企業4,928社を追跡したlongitudinal dataです。ここから、

- **創業5年時点で生存している**startupの10.7%がuser entrepreneur(自分が使うために作り、後で商業化した人)によるもの
- 同じく**革新的**startupに限ると46.6%

という比率が出ております。professional-user起業家の企業は、全sampleより売上計上企業の比率が約5pt高いという差も報告されておりますが、劇的な差ではございません。

> **注意**: この10.7%/46.6%は「5年生存した企業の中での比率」です。user起業の**成功率**ではなく**構成比**であり、しかも生存条件付きです。「user起業だから成功しやすい」という読み方は、このdataからは導けません。

確信度: **中**(比率自体は高い確信度。因果的な優位性については低い)。

### 1.6 spinout(前職の知識継承)

Klepper系のspinout研究では、親企業の能力が高いほどspinoutの生存・市場shareが高く、他の新規参入者より優れるという結果が繰り返し報告されております(Klepper, "Spinoffs: A review and synthesis", European Management Review 2009; Agarwal et al., "Knowledge Transfer Through Inheritance", Academy of Management Journal 2004)。第1.2節のindustry experience効果と同じ方向です。

確信度: **中**(industry限定の研究が多く、software個人開発への外挿は保証されません)。

### 1.7 日本の一次data

**日本政策金融公庫総合研究所「2024年度新規開業実態調査」(2024年11月27日)**
調査時点2024年8月、対象は同公庫が2023年4-9月に融資した開業1年以内の企業7,658社、回収1,990社(回収率26.0%)。

| 項目 | 値 |
|---|---|
| 開業時の平均年齢 | 43.6歳(1991年38.9歳から一貫して上昇) |
| 勤務経験あり | 97.9%(平均20.8年) |
| **斯業経験あり** | **83.1%(平均14.7年 / 中央値14.0年)** |
| 経営経験あり | 12.5% |
| 事業を決めた理由1位 | 「これまでの仕事の経験や技能を生かせるから」47.0% |
| 現在の採算状況「黒字基調」 | 67.3% |
| 予想月商達成(100%以上) | 59.6% |
| 開業時に苦労したこと | 資金繰り・資金調達59.2% / **顧客・販路の開拓48.1%** |
| 現在苦労していること | **顧客・販路の開拓47.7%** / 資金繰り37.0% |

米Censusの結果(中年・斯業経験)が日本でも同じ形で観測されております。加えて、**「顧客・販路の開拓」だけが開業時から現在まで首位付近に居座り続ける**という点が本件に効きます。資金繰りは開業後に下がりますが、販路は下がりません。

限界: 対象が公庫の融資先であり、無借金・超小規模・副業型は過小代表です。回収率26.0%のnon-response biasもございます。

確信度: **高**(調査要領・n・設問が公開されている)。ただし母集団の偏りは明示的に扱う必要があります。

副業型については同公庫「起業と起業意識に関する調査」が、事業時間で「起業家(週35時間以上)」と「パートタイム起業家(35時間未満)」を分けており、2023年度調査ではパートタイム起業家の37.7%が正社員勤務者、起業費用は「費用がかからなかった」が52.6%で最多でした。

---

## 2. 「market選択」対「実行・distribution」

### 2.1 horse(事業)側の証拠

**Kaplan, Sensoy, Strömberg (2009), "Should Investors Bet on the Jockey or the Horse?", Journal of Finance 64(1): 75-115**

business planからIPO・上場企業に至るまでのVC出資50社を追跡した研究です。

- **事業のline(何を誰に売るか)は驚くほど安定している**。変更した少数の企業でも、変更時期の中央値はIPOの7年前
- 一方で経営陣の入れ替えは大きい。IPO時点でfounderがCEOなのはVC-backedで49%、非VC-backedで61%
- 結論: marginでは、強い経営teamより強い事業に賭けるべき

**ただしこの論文には自ら認める決定的な制約がございます。** 著者らは本文で「論文の目的は企業がどう進化するかを見ることなので、失敗した企業を除外するのは自然である」と明記しております。sampleは全社が最終的に上場した企業です。**「成功した企業は事業を変えていない」という観察から「事業を変えないことが成功要因」を導くのは、まさに第4章で扱う生存biasの構造**です。失敗企業の中に「事業を変えなかった」ものがどれだけあるかは、この設計では原理的に見えません。

確信度: **低〜中**。findingは面白いが、因果の向きに関しては設計が答えを出せておりません。

### 2.2 実行・調査手続き側の因果証拠 (RCT)

**Camuffo, Cordova, Gambardella, Spina (2020), "A Scientific Approach to Entrepreneurial Decision Making: Evidence from a Randomized Control Trial", Management Science 66(2): 564-586**

- 応募202社のうち初期stage 164社から**無作為に**116社をItalyのtraining programに選抜、約1年・16時点のpanel
- treatment/control**両群**が「market feedbackの取り方」の一般training 10 sessionを受講
- treatment群のみ、ideaを**反証可能な仮説の集合**として定式化し、科学者のように厳密に検証する方法を追加で教育
- 結果: treatment群はperformanceが高く、**別のideaへpivotしやすく**、drop outは増えなかった

| 群 | 売上>0のfirm数 | 非ゼロ観測の平均売上 | 中央値 |
|---|---|---|---|
| treatment | 9社 | 約€7,800 | 約€1,300 |
| control | 8社 | 約€900 | 約€500 |

**反証・限界**: 116社中、期間中に売上が立ったのは合計17社(treatment 9・control 8)だけです。売上のeffectは事実上この17社、非ゼロ観測107件に依存しており、効果量の解釈は慎重であるべきです。「firmが売上を出す確率」自体はほぼ同じ(9対8)で、差が出たのは金額側です。

**Camuffo, Gambardella, et al. (2024), "A scientific approach to entrepreneurial decision-making: Large-scale replication and extension", Strategic Management Journal 45(6): 1209-1237**

4本のRCT・計759社の大規模replicationです。ここで頑健に出たのは、

- **ideaの打ち切り(idea termination)を増やす**方向の効果
- radical pivotへの**非線形**な効果(「何度も」でも「ゼロ」でもなく「少数回」に寄る)

でした。機序として著者らは「実行可能なideaの探索効率の向上」と「methodic doubt(自分の仮説以外のscenarioがあり得ると認識すること)」を挙げております。

**本件への含意**: 調査手法の改善が因果的に効くことは示されました。しかし出た効果は主に**「早く見切る」**であり、「当たりを引き当てる」ではございません。調査の目的関数を「良い領域を見つける」でなく「悪い仮説を安く殺す」に置き換えるべき、という強い示唆です。

確信度: **中〜高**(RCT・大規模replicationあり。ただし対象はItaly/UK等の初期stage startupで、個人のstock型businessではない)。

### 2.3 探索行動そのものが行われていないという事実

**Bennett & Chatterji (2023), "The entrepreneurial process: Evidence from a nationally representative survey", Strategic Management Journal**

米国の全国代表sample調査です。

- 過去5年に事業ideaを持ったことがある米国人は約1/3。動機の大半はlifestyle面であり、大きな機会の追求ではない
- **起業を検討した人の半数未満しか、「競合をInternetで検索する」「友人に相談する」といった最低costの手順すら踏んでいない**

つまり実務上の競争relevantな基準は「精緻な市場分析をしたか」ではなく、「最低限の検証を1つでも回したか」という極めて低い水準にあります。

確信度: **中**(全国代表sampleだがself-report)。

### 2.4 distribution側の実測: RevenueCat

**RevenueCat, "State of Subscription Apps 2026"(115,000+ apps / $16B+ revenue / 10億件超のtransaction)および同2025年版(75,000 apps / $10B+)**

これは自社platformを通る実transactionのdataであり、surveyではございません。個人・小規模のsubscription product分布として現状もっとも信頼できる公開dataの1つです。

| 指標 | 値 |
|---|---|
| launch後2年で月$1,000到達 | 17.3% |
| launch後2年で月$10,000到達 | 4.6% |
| $1K→$10Kの脱落 | 約75% |
| MRR成長 中央値 | 前年比 +5.3% |
| MRR成長 上位10% | +306%以上 |
| MRR成長 下位10% | -33%超の縮小 |
| **新規appの上位5%の1年目売上 / 下位25%** | **約400倍**(2025年版。前年は200倍) |
| 2020年より前にlaunchしたappが占める売上share | 69% |
| 2025年以降にlaunchしたappの売上share | 3% |

そして**実行variable**の効果が同じdataで測られております。

| 実行variable | 差 |
|---|---|
| hard paywall vs freemium (D35 conversion) | 10.7% vs 2.1%(約5倍) |
| hard paywall vs low-priced freemium (D14 収益/install) | $2.32 vs $0.27(8.6倍) |
| trial 17-32日 vs 4日以下 (trial→有料) | 42.5% vs 25.5%(1.7倍) |
| 北米 vs 印/東南亜 (1年目のRLTV) | $32 vs $14(2.3倍) |

確信度: **高**(実transaction・大規模)。ただし母集団はmobile subscription appであり、B2B web SaaSではございません。

### 2.5 判定

「market選択が結果を説明するか」に対して、本調査の範囲で言えることは以下です。

- **VC-backed×IPO到達という母集団では、industry-yearの選択が最強の予測変数**である(Gompers et al.)
- **個人〜小規模のsubscription productの母集団では、categoryによる差(最大5.6倍、後述)は同一category内の差(400倍)に対して桁違いに小さい**(RevenueCat)
- **日本の新規開業では、開業時から継続して首位の障害は「顧客・販路の開拓」**(日本公庫)

母集団が違えば答えが違う、というのが正直な結論です。userの目的関数(個人・stock型・非VC)に最も近い母集団のdataは、**market選択より実行・distribution側を支持**しております。

確信度: **中**(母集団を揃えた直接比較の研究が存在しないため、複数dataからの総合判断)。

---

## 3. TAM/SAM/SOMの妥当性

### 3.1 一次情報の状況

正直に申し上げますと、**TAM/SAM/SOMの予測妥当性を検証した査読論文は本調査では発見できませんでした。** 検索で上位に来るのはconsulting会社・SaaS vendorのcontent marketing記事ばかりで、source規律上いずれも採用できません。「TAMは有効/無効」を一次情報で直接主張することは、現時点ではできないと明記いたします。

その代わり、周辺の一次dataからTAMの情報量を評価いたします。

### 3.2 category間の分散はcategory内の分散に対して桁違いに小さい

RevenueCat 2026の「2年以内に月$10,000到達」を、category別に並べます。

| category | 到達率 | 月$1K到達までの中央値日数 |
|---|---|---|
| Gaming | 8.9%(最高) | 32日(最速) |
| Photo & Video | 7.3% | - |
| 全体 | 4.6% | 58日 |
| Business | 1.6%(最低) | 113日(最遅) |

**category間の最大差は 8.9 / 1.6 = 約5.6倍**です。一方、**同一集団内の上位5%と下位25%の売上差は約400倍**でした。

これはuserが自身の需要調査tool(5市場35,995件)で得た「category間の分散≈0、category内の分散が全域」という分散分解と、独立なdataで整合いたします。**「どのcategoryか」を測っても、結果の分散のごく一部しか説明できません。** TAMはcategory側の変数ですので、micro SaaS規模ではTAM単独で意思決定情報を持たない、という評価になります。

なお、5.6倍は「ゼロ」ではございません。**category選択は「効かない」のではなく「効き方が小さすぎて、実行の差に容易に飲み込まれる」**という表現が正確です。

### 3.3 「1%取れば」の算術が成立しない構造的理由

Golder & Tellis (1993)(第4.2節)が示す通り、categoryのleaderはpioneerではなく、平均13年遅れて参入した早期leaderです。TAMを根拠にした参入の暗黙前提「大きい市場なら端を取れる」は、**shareが誰にどう配分されるかを一切説明していない**という点で、そもそも予測modelとして不完全です。RevenueCatの「2020年より前にlaunchしたappが売上の69%を占める」も同じ構造で、installed baseとdistributionが配分を決めております。

### 3.4 micro SaaS規模でTAMを測る意味

以下の理由で、本件の意思決定にはほぼ寄与しないと評価いたします。

1. 個人が到達できる顧客数の上限は、market sizeではなく**自分が接続できるchannelの規模**で決まる。TAMはこれを測っていない
2. 必要売上が月数十万円regimeでは、必要顧客数は数十〜数百です。この規模はほぼどのcategoryのTAMからも到達可能であり、TAMの大小が制約にならない
3. 分散分解の結果、TAMが属するcategory次元の説明力が小さい(3.2節)

確信度: **中**。査読済の直接批判が無いため、実測dataからの導出に留まります。逆に「TAMが有効である」という一次証拠も見つかりませんでした。

---

## 4. 生存bias(survivorship bias)

### 4.1 なぜ「成功したSaaSはこうしていた」が調査手法として弱いのか

**Denrell (2003), "Vicarious Learning, Undersampling of Failure, and the Myths of Management", Organization Science 14(2): 227-243**

形式modelによる論証です。観測できる組織は、大部分を淘汰した選択過程の**生存者**です。書籍・business pressは成功組織に強く偏るため、sampleは失敗をunder-sampleします。

Denrellの核心的な結果は、単なる「偏りがある」ではございません。

> **母集団全体では performance と無関係なrisky practiceが、生存者のsampleの中では performance と正の相関を持つように見える。**

理由は素直です。risky practiceは結果の分散を拡げます。分散が大きい行動を採った組織は、上位にも下位にも多く現れます。下位が消えて上位だけが残ると、「その行動を採った組織は成績が良い」ように見えます。**「成功企業の共通点」を数えるという手続きそのものが、リスクの高い行動を推奨する方向に系統的に歪む**わけです。

これはuserが検討しているような「成功したmicro SaaSの共通点を集める」型の調査を、直接的に無効化する議論です。

確信度: **高**(形式的に証明されている+第4.2節の実証的裏付けあり)。

### 4.2 実証的な反例: pioneer advantageは生存biasの産物だった

**Golder & Tellis (1993), "Pioneer Advantage: Marketing Logic or Marketing Legend?", Journal of Marketing Research 30(2): 158-170**

第4.1節が実際に起きた事例です。それまでpioneer advantage(先行者優位)は「一般的現象」とされておりましたが、根拠となっていたPIMS・ASSESSOR databaseは**生存企業しか含んでいませんでした**。しかも「自社がpioneerか」を単一回答者のself-reportで分類しており、pioneerが消えた後は生き残った企業が自分をpioneerだと認識してしまいます。

著者らは50 category・約500 brandを歴史分析で再構成し、以下を得ました。

| 結果 | 値 |
|---|---|
| market pioneerの失敗率 | **47%** |
| pioneerが長期的にshare leaderであり続けたcategory | **50中4だけ** |
| 早期market leaderのpioneerに対する参入遅れ | 平均13年 |

**先行者優位という「業界の常識」は、失敗したpioneerを数え損ねたことによる人工物でした。** 同じ手続き上の欠陥は、現代の「成功したSaaSの共通点」listにそのまま存在します。

確信度: **高**(方法論的に明示的、広く追試・引用されている)。

### 4.3 business書の系統的批判

**Rosenzweig (2007), "The Halo Effect ...and the Eight Other Business Delusions That Deceive Managers", Free Press**

*In Search of Excellence*・*Built to Last*・*Good to Great* 等を対象にした批判です。halo effect(結果が良い企業には、あらゆる属性が良く見える)により、回顧的interviewとbusiness press記事を材料にした研究のdataは汚染されている、という指摘です。Rosenzweigはこれを Feynman の言う "cargo cult science"(科学の外見を持つ物語)と呼んでおります。

**本件への含意**: 「成功したindie hackerのinterview」は、halo effectと生存biasの両方を同時に浴びております。事実(価格、release日、channel)は使えますが、**当人による因果の説明(「〜したから伸びた」)は証拠として扱えません**。

確信度: **高**。

### 4.4 本書が引用した研究自体にも生存biasがある

公平を期すため明記いたします。

| 研究 | 生存bias/選択biasの所在 |
|---|---|
| Kaplan et al. (2009) | sample全社が上場済。失敗企業を明示的に除外していると本文に記載 |
| Shah et al. (2012) | 10.7%/46.6%は「創業5年時点で生存している企業の中での比率」 |
| Gompers et al. (2010) | 母集団がVC出資済、成功の定義がIPO |
| CB Insights (2014) | 公開post-mortemを書いた創業者のみ。自己帰属biasあり(第5.2節) |
| MicroConf 調査 | 自ら回答したbootstrapper。休止・撤退者は回答しない |
| 日本公庫 調査 | 融資を受けられた企業のみ、回収率26.0% |
| Azoulay et al. (2020) | **相対的に最も軽い**。米国の全新設雇用主企業を対象とした行政data |
| RevenueCat | **軽い**。ただしRevenueCatを使うほどには真面目なappに限られる(zeroに近い層は過小) |

生存biasから完全に自由なdataはございません。**「何が母集団から落ちているか」を毎回書き出す**のが現実的な運用です。

---

## 5. 有名な数字の出典検証

### 5.1 「startupの90%は失敗する」

**判定: 出典不明のfolklore。**

原典を辿ろうとした結果、この数字に対応する一次調査が見つかりませんでした。「1975年のDun & Bradstreet報告を記者が誤読したのが起源」という説明がweb上にございますが、**その説明自体もblog由来で一次確認ができておりません**(つまり、folkloreの起源譚もfolkloreです)。

代わりに使える一次統計は以下です。

**U.S. Bureau of Labor Statistics, Business Employment Dynamics (BED)** の1994年cohort(569,387事業所)

| 経過 | 生存率 |
|---|---|
| 1年後 | 79.6% |
| 2年後 | 68.1% |
| 15年後(1994年3月開設→2009年) | 約26% |

**日本**: 「創業10年後の生存率6.3%」という数字が日本語圏で広く流通しております。国立国会図書館の**レファレンス協同データベース**に、この数字の裏付けを探した司書の調査記録が残っております(管理番号 1000355744)。結論は「**該当する数値は発見できず**」でした。実際に中小企業白書が示す値は以下です。

| 出典 | 値 |
|---|---|
| 中小企業白書 2016年版 | 10年生存率 約72% |
| 中小企業白書 2017年版 | 5年生存率 81.7% |
| 中小企業白書 2023年版 | 起業5年の生存率 80.7% |

**「10年で9割が消える」も「6.3%」も、日本の公式統計とは整合いたしません。**

確信度: **高**(NDLの司書による調査記録という、検証行為そのものの記録が存在する)。

なお、定義の問題が大きく効きます。BEDや中小企業白書が測るのは「事業所/企業の存続」であり、「投資家に十分な return を返したか」ではございません。後者で測れば当然もっと厳しい数字になります。

### 5.2 CB Insights「42% no market need」

**判定: 原典は実在。ただし多くの引用が文脈を落としている。**

原典: CB Insights, *The Top 20 Reasons Startups Fail*, 2014年9月25日公開。PDF一次確認済。

| 順位 | 理由 | 割合 |
|---|---|---|
| #1 | market needが無い(問題を探しているsolutionを作った) | **42%** |
| #2 | 資金が尽きた | 29% |
| #3 | teamが適切でない | - |
| #4 | 競合に負けた | 19% |
| #5 | 価格/costの問題 | - |
| #19 | burn out | 8% |
| #20 | 必要なpivotをしなかった | 7% |

**確認できた重要な制約**:

1. **N = 101**。101件の公開post-mortemのみです
2. **合計は100%を大きく超えます**。原文が「多くのstartupが複数の理由を挙げているため、chartの合計は100%にならない(大きく超える)」と明記しております。したがって「42%のstartupがmarket needの欠如**で**失敗した」ではなく、「101件のpost-mortemのうち42%が理由の1つとしてそれに**言及した**」が正しい読み方です
3. **sampleは自己選択**です。廃業後に公開の反省文を書いた創業者だけが含まれます
4. 原文は「**There is certainly no survivorship bias here**(ここには生存biasは無い)」と述べておりますが、これは不正確です。失敗企業のみを見ている点で生存biasはございませんが、**「post-mortemを書いた失敗企業」に限定した選択bias**と、**自分の失敗理由を自己申告する帰属bias**が残ります。失敗の分母(post-mortemを書かずに消えたstartup)は取れておりません

**より新しいCB Insightsの集計**(2023年以降に公開廃業した VC-backed startup 431社、理由特定できた385社、調達総額$17.5B・中央値$11M)では順位が変わっております。

| 理由 | 割合 |
|---|---|
| 資本が尽きた | 70% |
| product-market fitが悪い | 43% |
| timing/macro | 29% |
| unit economicsが持続不能 | 19% |

やはり合計は100%を超えます。**「42%」を2026年の意思決定根拠に使うのは、12年前・N=101・自己申告の数字を使うことになります。**

確信度: **高**(原典PDFを直接確認)。

### 5.3 「VC-backed startupの75%が失敗する」(Shikhar Ghosh)

**判定: 半folklore。査読論文として発表されておらず、原典は新聞記事。**

出所は Deborah Gage, "The Venture Capital Secret: 3 Out of 4 Start-Ups Fail", *The Wall Street Journal*, 2012年9月20日。Harvard Business SchoolのShikhar Ghoshが、2004-2010年に$1M以上を調達したVC-backed企業2,000社超を調べた結果として報じられました。

問題点:

- **査読論文・working paperとして公刊されておりません**。方法・定義・sampleを第三者が検証できません
- 同記事内でNational Venture Capital Associationの推定(完全失敗は25-30%)と大きく食い違っております。差の主因は「失敗」の定義(元本を返せない/清算する/計画を下回る)ですが、どの定義でどの数字かが原典で明確ではありません

引用する場合は「WSJ 2012年報道、原論文は非公開」と必ず添えるべきです。

確信度: **中**(報道の存在は確実。数字の検証可能性は無い)。

### 5.4 「レッドオーシャンを避けよ」/ Blue Ocean Strategy

**判定: 方法論として弱い。かつ、実証は逆向きの証拠も持っている。**

Kim & MauborgneのBlue Ocean Strategyは、成功事例のみを事後的に選んで分析しており、同じ戦略を採って失敗した企業の数が示されておりません。これは第4章の生存biasそのものです。(この批判自体については、独立した査読論文形式の反証研究を本調査では特定できておりません。以下の反証は別系統のdataから提示いたします。)

**反証となる一次研究**: organizational ecologyのdensity dependence理論です(Hannan & Carroll, *Dynamics of Organizational Populations*, Oxford University Press 1992; Carroll & Swaminathan, *American Journal of Sociology* 1991、米国の醸造所7,709件の全history data)。

同種組織のdensity(密度)は、**低密度域では legitimation(そういう事業が存在すると認知されること)が支配し、創業率を上げ死亡率を下げます**。競争が支配するのは高密度域に入ってからです。つまり「誰もいない市場」は、優位ではなく**そもそも顧客がcategoryを認識していない**という不利を伴います。米国dataでは legitimation が全国規模で働き、競争は地域規模で働くという結果も出ております。

**Golder & Tellis (1993)** も同方向です。pioneerの47%が失敗し、長期leaderになったのは50中4 categoryのみでした。**「誰もいない海」を最初に泳ぐことは、実証的には有利ではございません。**

確信度: **中〜高**(density dependenceは大規模な歴史dataで繰り返し検証済。ただし対象は醸造所・新聞社等の伝統的industryであり、softwareへの外挿は慎重に)。

### 5.5 「founder-market fit」

**判定: VCのfolklore用語。ただし裏付けとなる実証は別に存在する。**

用語の出所はChris Dixonのblogですが、Dixon自身が「David Lee(SV Angel)が founder/market fit と呼ぶもの」と帰属しており、学術的定義や測定尺度はございません。

ただし内容に対応する実証は本書第1章に揃っております(Azoulay et al.のindustry experience、Klepper系のspinout、Shah et al.のuser entrepreneurship、日本公庫の斯業経験83.1%)。**用語ではなく、これらの実証を直接引くべきです。**

### 5.6 その他、検証したが辿れなかった数字

| よく見る数字 | 判定 |
|---|---|
| 「同一狭industryで3年以上の経験があると成功率85%増」 | Azoulay et al.の原典本文に無し。実数は0.11%→0.26%。**二次報道の変形と判断** |
| 「日本の起業10年後生存率6.3%」 | NDL レファレンス協同データベースが裏付けを発見できず(第5.1節) |
| 「startupの90%が失敗」 | 一次出典を特定できず |
| 「micro SaaSの平均MRRは$1,735」等の具体的数値 | 出所がcontent farm/affiliate記事のみ。**採用せず** |

---

## 6. 調査の設計原則(7条)

以上から導かれる、市場調査の設計原則です。各条に根拠と確信度を付しております。

### 第1条: 分析単位をcategoryでなく「自分 × 特定顧客群 × 特定作業」に置く

category次元の説明力は小さいことが、userの自前調査(35,995件)とRevenueCat(115,000 app)の2つの独立したdataで確認されております。category間5.6倍に対しcategory内400倍です。categoryを測る調査は、労力あたりの情報量が構造的に低くなります。
根拠: 第3.2節 / 確信度: **高**

### 第2条: 探索の起点をfounderの既存知識(斯業経験)に固定する

最も再現性のある予測変数は、行政全数dataでも日本の公的調査でも「起業する事業と近い分野での実務経験」です。ただし効果量は2倍前後で、決定打ではございません。「経験年数」ではなく **task-relatedness(その顧客のその作業について何を知っているか)** の水準まで具体化して初めて効きます。
根拠: 第1.2節・第1.3節・第1.7節 / 確信度: **高**

### 第3条: 調査は「観察」ではなく「反証可能な予測」の形にする

事前にframeworkを立て、仮説を明示し、厳密に検証する群だけが有意な差を出した、というRCT証拠が存在します。**予測を書かずに情報を集める行為には、因果的な効果が確認されておりません。**
根拠: 第2.2節 / 確信度: **中〜高**

### 第4条: 調査の目的関数を「当たりを見つける」でなく「外れを安く殺す」に置く

759社のreplicationで頑健に出た効果は、売上増でなく **idea termination の増加** と **pivot回数の非線形な最適化** でした。調査の成功指標は「有望な領域を何個見つけたか」ではなく「何個を、どれだけ安く、確信を持って捨てられたか」とすべきです。
根拠: 第2.2節 / 確信度: **中〜高**

### 第5条: 成功例からの逆算を禁止する。使うなら必ず失敗側の分母を取る

生存者のみのsampleでは、母集団で無関係なrisky practiceが有効に見えることが形式的に示されており(Denrell)、実際にpioneer advantageという「常識」がこの機序で作られていたことが実証されております(Golder & Tellis)。成功者の**事実**(価格・時期・channel)は使えますが、成功者の**因果説明**は証拠になりません。
根拠: 第4章 / 確信度: **高**

### 第6条: market sizeでなく「到達可能なchannel」を実測する

日本の新規開業で、開業時(48.1%)から現在(47.7%)まで一貫して首位に居座る障害は「顧客・販路の開拓」です。同時に、実測dataでは価格設計・paywall・trial長といった**実行variableに2〜8.6倍の効果**が観測されております。調査項目としては、TAMの推定より「この顧客群に自分がどのchannelで、何人に、何円で届くか」の実測の方が意思決定情報を持ちます。
根拠: 第1.7節・第2.4節 / 確信度: **中**

### 第7条: 引用する数字は原典に当たる。辿れない数字は使わず、使うなら folklore と明記する

本調査で検証した6つの有名な数字のうち、原典が確認できたのは2つ(CB Insights 42%、Golder & Tellis 47%)だけで、うち1つは文脈が広く誤って伝わっておりました。日本語圏の「6.3%」に至っては、国会図書館の司書が探しても発見できておりません。
根拠: 第5章 / 確信度: **高**

---

## 7. この面から言える調査設計への示唆

- **userの既存結論(category選択を測っても情報が無い)は、独立した外部dataで支持されます。** RevenueCat 115,000 appでcategory間差5.6倍・category内差400倍。需要調査toolをボツにした判断は、実証的に正しかったと評価できます。この結論を再検討する必要はございません。
- **ただし「category差はゼロ」ではなく「小さすぎて実行差に飲まれる」が正確です。** 調査を「categoryを選ぶため」でなく「実行variableを事前に見積もるため」に再設計すれば、同じ調査基盤が生き返る可能性がございます(例: 価格帯、既存代替手段のswitching cost、到達channelの有無)。
- **調査の起点は市場側でなくfounder側に置くべきです。** 全数行政dataでも日本の公的調査でも、再現する予測変数は斯業経験です(米: 上位0.1%到達率 0.11%→0.26%、日: 開業者の83.1%が斯業経験あり・事業決定理由1位が「仕事の経験を生かせる」47.0%)。「自分が何を知っているか」の棚卸しが、市場のscreeningより先に来ます。
- **調査の出力は「有望リスト」でなく「棄却リスト」にすべきです。** 759社RCTで頑健に出た効果はidea terminationでした。「N個中M個を、根拠を書いて捨てた」という形式で成果を測る設計を推奨いたします。
- **成功事例の収集を調査手法として採用しないでください。** Denrellの形式的結果により、この手続きは体系的にrisky practiceを推奨する方向に歪みます。pioneer advantageという業界常識が実際にこの機序で作られていた実例(pioneer失敗率47%、長期leaderは50中4)がございます。
- **TAM/SAM/SOMは本件では省略して差し支えありません。** 予測妥当性を示す一次証拠が存在せず、かつcategory次元の説明力が小さいことが分かっているためです。省略の判断は、「TAMが無効という証拠がある」ではなく「TAMが有効という証拠が無く、代替指標の方が説明力が高い」という根拠で行うのが正確です。
- **「顧客・販路の開拓」を独立の調査対象として立ててください。** 日本の一次調査で、開業前から開業後まで下がらない唯一の障害です。市場を選ぶ調査と、届け方を調べる調査は別物として設計すべきです。
- **数字を使う際は必ず原典を確認してください。** 本調査の範囲でも、広く流通する数字の過半は原典が辿れないか、文脈が失われておりました。特に「90%失敗」「6.3%」「85%」は使用を避けることを推奨いたします。

---

## 参考文献

### 査読論文・working paper

- Azoulay, P., Jones, B. F., Kim, J. D., Miranda, J. (2020). "Age and High-Growth Entrepreneurship." *American Economic Review: Insights* 2(1): 65-82. DOI 10.1257/aeri.20180582. https://www.aeaweb.org/articles?id=10.1257%2Faeri.20180582
- 同 NBER Working Paper No. 24489 (2018年4月, 全文PDF). https://www.nber.org/system/files/working_papers/w24489/w24489.pdf
- 同 U.S. Census Bureau CES Working Paper 18-23. https://ideas.repec.org/p/cen/wpaper/18-23.html
- Gompers, P., Kovner, A., Lerner, J., Scharfstein, D. (2010). "Performance persistence in entrepreneurship." *Journal of Financial Economics* 96(1): 18-32. https://econpapers.repec.org/RePEc:eee:jfinec:v:96:y:2010:i:1:p:18-32 / 全文PDF (2009年1月草稿, Federal Reserve Bank of New York) https://www.newyorkfed.org/medialibrary/media/research/economists/kovner/performance_persistence.pdf
- Kaplan, S. N., Sensoy, B. A., Strömberg, P. (2009). "Should Investors Bet on the Jockey or the Horse? Evidence from the Evolution of Firms from Early Business Plans to Public Companies." *The Journal of Finance* 64(1): 75-115. https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2008.01429.x / 2007年8月草稿PDF http://angelcapitalassociation.org/data/Documents/Resources/AngelGroupResarch/1d%20-%20Resources%20-%20Research/28%20RSCH_-_Should_Investors_Bet_on_the_Jockey_or_the_Horse_8.07.pdf
- Camuffo, A., Cordova, A., Gambardella, A., Spina, C. (2020). "A Scientific Approach to Entrepreneurial Decision Making: Evidence from a Randomized Control Trial." *Management Science* 66(2): 564-586. DOI 10.1287/mnsc.2018.3249. https://pubsonline.informs.org/doi/10.1287/mnsc.2018.3249 / 全文PDF https://gwern.net/doc/economics/2019-camuffo.pdf
- Camuffo, A., Gambardella, A., et al. (2024). "A scientific approach to entrepreneurial decision-making: Large-scale replication and extension." *Strategic Management Journal* 45(6): 1209-1237. https://ideas.repec.org/a/bla/stratm/v45y2024i6p1209-1237.html
- Bennett, V. M., Chatterji, A. K. (2023). "The entrepreneurial process: Evidence from a nationally representative survey." *Strategic Management Journal*. DOI 10.1002/smj.3077. https://sms.onlinelibrary.wiley.com/doi/abs/10.1002/smj.3077 / 2017年草稿PDF https://sites.duke.edu/ronniechatterji/files/2017/08/10_TheEntrepreneurialProcess_BennettChatterji_UpdatedAugust11th2017.pdf
- Unger, J. M., Rauch, A., Frese, M., Rosenbusch, N. (2011). "Human capital and entrepreneurial success: A meta-analytical review." *Journal of Business Venturing* 26(3): 341-358. 全文PDF https://strathprints.strath.ac.uk/35466/1/Unger_Rauch_Frese_Rosenbusch_2011.pdf
- Brinckmann, J., Grichnik, D., Kapsa, D. (2010). "Should entrepreneurs plan or just storm the castle? A meta-analysis on contextual factors impacting the business planning-performance relationship in small firms." *Journal of Business Venturing* 25(1): 24-40. https://econpapers.repec.org/RePEc:eee:jbvent:v:25:y:2010:i:1:p:24-40
- Shah, S. K., Tripsas, M. (2007). "The accidental entrepreneur: the emergent and collective process of user entrepreneurship." *Strategic Entrepreneurship Journal* 1: 123-140. https://sms.onlinelibrary.wiley.com/doi/abs/10.1002/sej.15 / HBS Working Paper 04-054 https://www.hbs.edu/ris/Publication%20Files/04-054_8e7593dc-8676-47b6-8676-2631877322c6.pdf
- Denrell, J. (2003). "Vicarious Learning, Undersampling of Failure, and the Myths of Management." *Organization Science* 14(2): 227-243. DOI 10.1287/orsc.14.2.227.15164. https://pubsonline.informs.org/doi/10.1287/orsc.14.2.227.15164
- Golder, P. N., Tellis, G. J. (1993). "Pioneer Advantage: Marketing Logic or Marketing Legend?" *Journal of Marketing Research* 30(2): 158-170. 全文PDF https://gtellis.net/wp-content/uploads/2020/09/pioneering-advantage-marketing-logic-or-marketing-legend.pdf
- Carroll, G. R., Swaminathan, A. (1991). "Density Dependent Organizational Evolution in the American Brewing Industry from 1633 to 1988." https://journals.sagepub.com/doi/10.1177/000169939103400301
- Klepper, S. (2009). "Spinoffs: A review and synthesis." *European Management Review* 6. https://onlinelibrary.wiley.com/doi/10.1057/emr.2009.18
- Agarwal, R., Echambadi, R., Franco, A. M., Sarkar, M. B. (2004). "Knowledge Transfer Through Inheritance: Spin-Out Generation, Development, and Survival." *Academy of Management Journal*. https://journals.aom.org/doi/10.5465/20159599
- Guzman, J., Stern, S. "The State of American Entrepreneurship." NBER Working Paper No. 22095 (2016) / *American Economic Journal: Economic Policy* (2020). https://www.nber.org/papers/w22095

### 書籍

- Bhidé, A. (2000). *The Origin and Evolution of New Businesses*. Oxford University Press. https://global.oup.com/academic/product/the-origin-and-evolution-of-new-businesses-9780195131444 (1989年Inc. 500創業者調査で、71%が前職で遭遇したideaを複製・修正したものと報告)
- Rosenzweig, P. (2007). *The Halo Effect ...and the Eight Other Business Delusions That Deceive Managers*. Free Press.
- Hannan, M. T., Carroll, G. R. (1992). *Dynamics of Organizational Populations: Density, Legitimation, and Competition*. Oxford University Press. https://global.oup.com/academic/product/dynamics-of-organizational-populations-9780195071917
- Eisenmann, T. (2021). *Why Startups Fail: A New Roadmap for Entrepreneurial Success*. Currency. (470名の創業者を対象とする独自調査と24件のcase studyに基づく6つの失敗patternを提示。HBR記事: https://hbr.org/2021/05/why-start-ups-fail)

### 政府・公的統計

- U.S. Bureau of Labor Statistics, Business Employment Dynamics (BED). 1994年cohort(569,387事業所)の生存率: 1年後79.6%、2年後68.1%。https://www.bls.gov/bdm/entrepreneurship/entrepreneurship.htm / BLS発表資料(NABE 2025) https://nabe.com/common/Uploaded%20files/EMS%202025/Friesenhahn_v2.pdf
- U.S. Bureau of Labor Statistics, "Business Employment Dynamics Twentieth Anniversary" (2024). https://www.bls.gov/spotlight/2024/business-employment-dynamics-twentieth-anniversary/home.htm
- 日本政策金融公庫総合研究所「2024年度新規開業実態調査」(2024年11月27日). https://www.jfc.go.jp/n/findings/pdf/kaigyo_241127_1.pdf
- 日本政策金融公庫総合研究所「起業と起業意識に関する調査」. https://www.jfc.go.jp/n/findings/pdf/kigyouishiki_250120_1.pdf
- 国立国会図書館 レファレンス協同データベース「企業生存率が10年後6.3%の裏付けが欲しい」(管理番号 1000355744). https://crd.ndl.go.jp/reference/entry/index.php?id=1000355744&page=ref_view
- 中小企業庁『中小企業白書』2016年版 / 2017年版 / 2023年版. https://www.chusho.meti.go.jp/pamflet/hakusyo/

### 企業の公開data・報告書

- RevenueCat, "State of Subscription Apps 2026"(115,000+ apps / $16B+ revenue / 10億件超のtransaction). https://www.revenuecat.com/state-of-subscription-apps
- RevenueCat, "State of Subscription Apps 2025"(75,000 apps / $10B+ revenue). https://www.revenuecat.com/state-of-subscription-apps-2025
- Shah, S. K., Winston Smith, S., Reedy, E. J. (2012). "Who Are User Entrepreneurs? Findings on Innovation, Founder Characteristics, and Firm Characteristics." Kauffman Firm Survey, Ewing Marion Kauffman Foundation. https://www.kauffman.org/wp-content/uploads/2019/12/whoareuserentrepreneurs.pdf / SSRN https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2018517
- CB Insights, *The Top 20 Reasons Startups Fail* (2014年9月25日, N=101). https://s3-us-west-2.amazonaws.com/cbi-content/research-reports/The-20-Reasons-Startups-Fail.pdf
- CB Insights, "Why Startups Fail: Top Reasons"(2023年以降に廃業したVC-backed 431社). https://www.cbinsights.com/research/report/startup-failure-reasons-top/
- MicroConf, "State of Independent SaaS"(2020年10月調査, 招待約25,000名・回答673名・完答534名). https://microconf.com/state-of-indie-saas
- Gage, D. "The Venture Capital Secret: 3 Out of 4 Start-Ups Fail." *The Wall Street Journal*, 2012年9月20日. (Shikhar Ghoshによる調査。査読論文としては未公刊)
