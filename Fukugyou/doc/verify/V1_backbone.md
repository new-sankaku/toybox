# V1: 骨格主張の敵対的検証

検証担当: adversarial verification / 作成日: 2026-08-11
検証対象: `doc/research/A_evidence.md`、`doc/research/C_discovery.md`（および波及先として `doc/MARKET_RESEARCH.md`、`doc/research/D_competition_pricing.md`）

## 本検証の手段と制約（先に申し上げます）

- 本session は WebSearch の予算を使い切っておりましたため、**検索は一切使用せず、URL 直接取得（WebFetch）と PDF の local 抽出（`pdftotext -layout`）のみ**で検証しております。
- PDF は WebFetch が local に保存したものを `pdftotext` で全文 text 化し、`grep` で原典文字列を目視確認しております。**「document 側の表現が原典にあるか」は、原典 text 上で該当行を出力して確認**いたしました。
- 取得できなかった source（Wiley 403 / AEA 403 / 中小企業庁 PDF）は、その旨を明記し「未確認」といたします。

---

## 判定 summary

| # | 主張の要約 | 判定 | 確信度 | 一言 |
|---|---|---|---|---|
| 1 | category 間 5.6倍 / category 内 400倍（RevenueCat 約115,000 app） | **部分的に不正確** | 高 | 400倍は原典に実在（ただし2025年版・75,000 app）。**5.6倍は原典に無く、別 agent の計算による派生値**。しかも2値は次元も母集団も異なり、並置は分散分解として成立しません |
| 2 | Camuffo et al. 2020、116社・約1年・16時点の RCT | **確認** | 高 | abstract に逐語で一致。A の売上表（9社/8社、€7,800/€1,300、€900/€500、107観測）も本文と完全一致 |
| 3 | 2024年 replication（759社・4 RCT）の頑健な効果は売上でなく idea termination と radical pivot への非線形効果 | **確認** | 高 | abstract に termination と非線形 pivot のみ。**売上・performance への言及は abstract に一切ありません** |
| 4 | pioneer の約半数が失敗、long-term leader は平均13年後に参入 | **確認** | 高 | abstract に逐語。「50中4」も本文に逐語で確認 |
| 5 | pioneer 失敗率 47% に対し **early follower** は 8% | **部分的に不正確** | 高 | 47% は確認。8% も原典にありますが **early leader（早期 market leader）** の値で、**early follower ではありません**。しかも成果で定義された集団の値です |
| 6 | 生存者 sample では母集団で無関係な risky practice が有効に見える（Denrell） | **確認** | 高 | Denrell (2003) *Organization Science* の abstract に逐語で存在 |
| 7 | 斯業経験の上位0.1%到達率 0.11% → 0.26% | **確認** | 高 | NBER WP 24489 本文に逐語。Table 6 の Panel A〜C とも一致 |
| 8 | 50歳は30歳の1.8倍／回帰では約2倍、平均41.9歳、上位0.1%は45.0歳 | **確認** | 高 | 4値すべて本文に逐語で存在 |
| 9 | 「同一狭 industry 3年以上で成功率85%高い」は原典本文に無い | **確認（範囲限定）** | 中〜高 | NBER WP 24489 全文抽出に "85" は0件。**ただし AER:Insights 掲載版は 403 で未確認** |
| 10 | metatheme は6件で出現（→12件で足りる根拠） | **確認（数値）／外挿は要注意** | 高 | 逐語一致。ただし測っているのは theme の出現であって意思決定の十分性ではありません（後述） |
| 11 | 「顧客・販路の開拓」が開業時48.1%・現在47.7%で**首位**の障害 | **部分的に不正確** | 高 | 数値・n=1,990・回収率26.0% はすべて逐語一致。**しかし開業時の首位は「資金繰り、資金調達」59.2%** で、顧客・販路は2位です |
| 12 | 10年72% / 5年81.7% / 起業5年80.7% | **確認（間接）** | 中〜高 | 3値とも頁番号付きで裏付け。ただし白書 PDF 本体は未取得で、CRD 記録経由の確認です |
| 13 | NDL レファレンス協同データベース 管理番号 1000355744、結論は「該当する数値は発見できず」 | **部分的に不正確** | 高 | 記録は実在。**しかし管理番号は「中央－1－００二一七五一」、提供館は さいたま市立中央図書館**。結論の文言も引用形と異なります |
| 14 | Kauffman: 5年生存企業の10.7%が user entrepreneur、革新的に限ると46.6% | **確認** | 高 | 逐語一致。「survive to age five」条件も原典が明示 |

---

## 各主張の検証

### #1 category 間 5.6倍 vs category 内 400倍 — 部分的に不正確

**原典1**: RevenueCat, "State of Subscription Apps 2026" — https://www.revenuecat.com/state-of-subscription-apps/

取得できた記述（category 別の2年以内 $10K 到達率）:

| category | $1K到達 | $10K到達 |
|---|---|---|
| Gaming | 20.0% | **8.9%** |
| Photo & Video | 21.4% | 7.3% |
| Business | 14.7% | **1.6%** |
| 全体 | 17.3% | 4.6% |

> "only 4.6% of newly-launched apps reach $10K in monthly revenue within two years."

dataset は "over 115,000 apps" / "more than $16 billion in revenue" / "more than a billion transactions" で、A の記述と一致いたします。

**判定の核心**: **「5.6倍」という数値は report のどこにも登場いたしません。** 8.9 ÷ 1.6 = 5.5625 を別 agent が自ら計算した**派生値**です。A_evidence 第3.2節は「category 間の最大差は 8.9 / 1.6 = 約5.6倍です」と計算過程を明示しており、この点では誠実です。しかし第0章の結論表・第1条・第7章では「RevenueCat 115,000 app で category 間差5.6倍」と、**あたかも原典の記述であるかのように**要約されております。これは原典の記述ではございません。

**原典2**: RevenueCat, "State of Subscription Apps 2025" — https://www.revenuecat.com/state-of-subscription-apps-2025/

400倍は**実在**いたします。逐語:

> "At $8,880 the top 5% of newly launched apps make over 400x as much money after their first year, compared to the bottom 25% who make no more than $19."

dataset は "75,000 subscription apps tracking $10B+ in revenue"。

**より重大な欠陥（別 agent が自覚していない点）**: この2値の並置は、分散分解として成立いたしません。

1. **量の次元が違います。** 5.6倍は「$10K 到達**確率**の比」、400倍は「1年目**売上水準**の percentile 比」です。確率の比と金額の比を「category 間 vs category 内」として比較することは、単位の異なる量を割り算しているのと同じです。
2. **母集団と版が違います。** 5.6倍は2026年版（115,000 app）、400倍は2025年版（75,000 app）由来です。A の参考文献欄と第7章は400倍を「115,000 app」に紐づけており、出典の取り違えがございます。
3. **正しい比較の形**: category 間を測るなら category 別の**売上分布**（例: category 中央値の比）を、category 内を測るなら同一 category 内の percentile 比を取り、同じ次元で比べる必要がございます。現状の比較は「category 内の分散が桁違いに大きい」という結論を支持する証拠として使えません。

なお、A_evidence 第2.4節の RevenueCat 表は**他の7値すべてが原典と一致**しております（17.3% / 4.6% / 中央値 +5.3% / 上位10% +306% / 下位10% -33% / 2020年以前 launch が69% / 2025年以降が3%）。逐語:

> "Half of all apps grew MRR by at least 5.3% YoY" / "the top 10% grew 306%+" / "apps launched before 2020 generate 69% of all subscription revenue" / "Apps launched in 2025 or later (aka, the vibe coding era) account for just 3%"

ただし表中の「$1K→$10K の脱落 約75%」も派生値（1 − 4.6/17.3 = 73.4%）であり、原典の記述ではございません。「前年は200倍」も未確認です。

---

### #2 Camuffo, Cordova, Gambardella, Spina (2020) — 確認

**原典**: https://gwern.net/doc/economics/2019-camuffo.pdf を local 保存し `pdftotext` で全文抽出。*Management Science*、doi 10.1287/mnsc.2018.3249、Received 2017-09-05 / Accepted 2018-10-16 / Published Online in Advance 2019-08-08。

abstract 逐語:

> "The panel sample of our randomized control trial includes **116 Italian startups and 16 data points over a period of about one year**. Both the treatment and control groups receive **10 sessions of general training** on how to obtain feedback from the market and gauge the feasibility of their idea. ... We find that entrepreneurs who behave like scientists **perform better, are more likely to pivot to a different idea, and are not more likely to drop out** than the control group in the early stages of the startup."

本文 §6.3 逐語（A_evidence の売上表を完全に裏付けます）:

> "17 firms earn positive revenue (9 in the treatment group and 8 in the control group)" / "The 17 firms with positive revenue in our sample correspond to **107 of our 1,865 observations**: 85 observations of the 9 firms in the treatment group versus 22 observations of the 8 firms in the control group." / "the average and median revenue for the 85 nonzero observations in the treatment group are about **7,800 and 1,300 euros**, respectively; for the 22 nonzero observations in the control group, they are about **900 and 500 euros**, respectively."

また「応募202社→初期 stage 164社→116社を無作為選抜」も本文（"Of the 202 applicants for the program, 164..." / "capped enrollment in the training program at 116 startups randomly selected from the 164 startups"）で確認いたしました。

**判定: 確認。** A_evidence 第2.2節は、限界の記述（17社依存、firm が売上を出す確率は9対8でほぼ同じ）を含めて原典に忠実です。本検証で最も精度の高い記述でした。

---

### #3 2024年 large-scale replication — 確認（結論を左右する点として重要）

**原典**: Camuffo, Gambardella, Messinese, Novelli, Paolucci, Spina (2024), *Strategic Management Journal* 45(6): 1209-1237, doi **10.1002/smj.3580**。

Wiley 本体（https://onlinelibrary.wiley.com/doi/10.1002/smj.3580）は **HTTP 403** で本文取得不可。そのため Crossref 登録 abstract（https://api.crossref.org/works/10.1002/smj.3580）と RePEc（https://ideas.repec.org/a/bla/stratm/v45y2024i6p1209-1237.html）の2経路で abstract を突き合わせております。両者は一致いたしました。

**Research Summary の内容**: "a large-scale replication of Camuffo and colleagues in 2020, involving **759 firms in four randomized control trials**"、効果は **idea termination（idea の打ち切り）への正の効果**、および **strategic pivot への非線形効果**（treated は「pivot ゼロ」でも「絶えず変更」でもなく **few strategic shifts** に寄る）。機序は探索効率の向上と、"alternative scenarios from the ones that they theorize" を認識する methodic doubt。

**Managerial Summary**: "entrepreneurial practices can benefit from a scientific approach to decision-making"、"heightened idea termination and measured strategy modifications"。

**ご依頼の切り分けへの回答**: 「売上に効果が無かった」でも「売上効果は測れたが少数 firm 依存」でもなく、**abstract は売上・revenue・performance を一切主張しておりません**。abstract が前面に出す頑健な結果は termination と pivot の非線形性のみです。したがって A_evidence 第2.2節・第4条の「頑健に出たのは売上増でなく idea termination」という記述は、**原典 abstract の枠組みと正確に一致**いたします。

**ただし C_discovery に不整合がございます（追加発見）。** `C_discovery.md:249` は同論文の結果として

> 「treatment 群は control 群より **6,999.327 euro 多く稼いだ（p = .030）**」

を第一の bullet として掲げております。この数値は **Wiley 403 のため未確認**です。C 自身が確信度「中・原典頁未確認」と付しており、その自己申告は誠実です。しかし小数点以下3桁まで持つ回帰係数を、abstract が言及すらしない量として **箇条書きの筆頭**に置くのは、原典の重心と逆の印象を与えます。A（売上でない）と C（売上が出た）で同一論文の要約が食い違っており、**手順書に採るべきは A の側**です。

---

### #4 Golder & Tellis (1993) pioneer 失敗・13年 — 確認

**原典**: https://gtellis.net/wp-content/uploads/2020/09/pioneering-advantage-marketing-logic-or-marketing-legend.pdf（JSTOR scan、*Journal of Marketing Research* 30(2), May 1993, pp. 158-170）。WebFetch では本文抽出に失敗いたしましたが、保存された PDF を `pdftotext -layout` で全文 text 化して確認いたしました。

abstract 逐語（原文の字間潰れをそのまま示します）:

> "Approximately 500 brands in 50 product categories are analyzed. The results show that **almost half of market pioneers fail** and their mean market share is much lower than that found in other studies. Also, **early market leaders have much greater long-term success and enter an average of 13 years after pioneers.**"

本文（Nature of Leadership 節）逐語:

> "The proposition of a long-lived market share leadership for pioneers is supported in **only four of the 50 product categories** studied."

本文（Early Leaders 節）逐語:

> "early leaders enter product categories many years after the market pioneer. In the product categories studied, early leaders entered **13 years after market pioneers**. The time lag was 19 years in pre-World War II product categories and five years in post-World War II categories."

**判定: 確認。** A_evidence 第4.2節の3値（47% / 50中4 / 平均13年）はすべて原典に存在いたします。

補足として、13年には**強い時代差**がございます（戦前 category 19年、戦後 category **5年**）。「後発参入の平均遅れは13年」を現代の software に適用する際、より近いのは戦後の5年です。`D_competition_pricing.md:234` の「後発参入の平均遅れは13年。『もう遅い』という感覚には実証的根拠が薄い」は、この時代差を落としており、主張を強く出しすぎております。

---

### #5 47% / 8% — 部分的に不正確（**修正必須**）

47% は本文に逐語で存在いたします:

> "Table 4 shows the failure rate of market pioneers to be **47%**." / "By so doing, we found a failure rate of 47% for pioneers, which is closer to the failure rate of 33 to 35% found in the Booz, Allen & Hamilton (1982) study of new products."

**8% も原典に存在いたします。しかし帰属先が違います。** 本文 Early Leaders 節、Table 7（"CHARACTERISTICS OF EARLY MARKET LEADERS"、Total: failure rate 8% / market share 28% / percentage of leaders 53% / 36 cases）に対応する逐語:

> "We define the early leader as the firm that is **the market share leader during the early growth phase** of the product life cycle. Table 7 indicates the performance of these firms. Note that early leaders are currently leaders in more than half of the product categories studied and **have very low failure rates (8%)**."

**したがって 8% は "early leader（早期 market leader）" の失敗率であり、"early follower（早期追随者）" の失敗率ではございません。** この2語は本論文では明確に別概念です。"early follower" は本論文が批判している **PIMS database の自己申告 category 名**として登場するだけで（"an informant in each business classifies it as one of the pioneers, an early follower, or a late entrant"）、Golder & Tellis 自身は early follower の失敗率を報告しておりません。

**さらに重要な論理的欠陥**: early leader は「成長初期に share 首位だった企業」という、**結果によって定義された集団**です。首位に立てた企業だけを集めれば失敗率が低いのは半ば定義的であり、これは本書第4章が批判している生存 bias／選択 bias と同じ構造です。**「pioneer 47% に対し early follower 8% だから後発参入が安全」という推論は、本書自身の第5条に違反しております。**

**該当箇所**:
- `doc/MARKET_RESEARCH.md:225`「pioneer の失敗率 47% に対し early follower は 8% という実証があります。**既存市場への後発参入は、避けるべき状態ではなく既定の戦略です。**」
- `doc/research/D_competition_pricing.md:14`「市場 pioneer の失敗率47%に対し early follower は8%」
- `doc/research/D_competition_pricing.md:226`「market pioneer の**失敗率47%**、early follower は**8%**」

なお `A_evidence.md` は表（第4.2節）に 8% を載せておらず、この誤りは A ではなく D と MARKET_RESEARCH.md 側にございます。

---

### #6 Denrell の formal model — 確認

**文献の特定**: Denrell, J. (2003). "Vicarious Learning, Undersampling of Failure, and the Myths of Management." *Organization Science* 14: 227-243. doi 10.1287/orsc.14.2.227.15164。Crossref 登録 abstract（https://api.crossref.org/works/10.1287/orsc.14.2.227.15164）で確認。

abstract 中の該当記述（逐語）:

> "**risky practices, even if they are unrelated to performance in the full population of organizations, may seem to be positively related to performance in a sample of survivors.**"

**判定: 確認。** 主張 #6 は原典 abstract の記述と語義まで一致いたします。A_evidence 第4.1節の引用（「母集団全体では performance と無関係な risky practice が、生存者の sample の中では performance と正の相関を持つように見える」）は正確な翻訳です。本書の中で最も正確に引用されている箇所の1つでした。

**軽微な不一致**: A_evidence は 14**(2)** と表記、Crossref の metadata は issue **3** を返します（DOI 文字列は "14.2.227" で巻2を示唆）。原典 PDF は paywall のため号数を確定できませんでした。実害はございませんが、号数は確認のうえ確定させることを推奨いたします。

---

### #7 0.11% → 0.26% — 確認

**原典**: NBER Working Paper No. 24489（https://www.nber.org/system/files/working_papers/w24489/w24489.pdf）を local 保存し `pdftotext` で全文抽出。

本文逐語:

> "For achieving a 1 in 1,000 highest-growth firm, having no experience in the 2-digit level industry leads to a success rate of **0.11%**, while having at least three years of experience in the start-up's industry shows success rates that rise from **0.22%** (2-digit NAICS experience) to **0.24%** (4-digit NAICS experience) to **0.26%** (6-digit NAICS experience)."

Table 6（Panel A〜C）の該当行も抽出し、本文と整合することを確認いたしました。

**判定: 確認。** A_evidence 第1.2節の4値はすべて原典本文に存在いたします。

---

### #8 1.8倍 / 約2倍 / 41.9歳 / 45.0歳 — 確認

本文逐語:

> "the mean age for the entrepreneurs at founding is **41.9**. The mean founder age for the 1 in 1,000 highest growth new ventures is **45.0**."

> "Conditional on starting a firm, a **50-year-old founder is 1.8 times more likely to achieve upper-tail growth than a 30-year-old founder.**"

「回帰では約2倍」に対応する記述も2箇所で確認いたしました:

> "a founder at age 50 is **approximately twice** as likely to experience a successful exit compared to a founder at..." / "a founder at age 50 is approximately twice as likely of achieving upper-tail..."

さらに斯業経験についても:

> "success at **twice the rate** as founders with no experience in the 2-digit industry."

**判定: 確認。** 4値すべて逐語で存在いたします。

---

### #9 「85%」の不在 — 確認（範囲限定。手段を明記します）

**確認した範囲と手段**:
1. NBER WP 24489 の PDF を local 保存し、`pdftotext -layout` で全文を text 化（120,785 bytes、表・脚注・参考文献を含む）。
2. 正規表現 `\b85\b|85 ?%|85 percent` で全文検索 → **hit 0件**。
3. 併せて `twice|two times|double` を検索し、経験効果の記述が「約2倍」「125%上昇」の形でのみ現れることを確認。

**近縁の記述（誤伝の起点である可能性）**:

> "prior employment in the specific sector predicts a vastly higher probability of an upper-tail growth outcome or successful exit, with **success rates rising up to 125%**."

「125% 上昇」が二次報道の過程で「85% 高い」に変形した可能性は指摘できますが、これは推測であり証拠はございません。

**確認できていない範囲（重要）**: **AER:Insights 掲載版（2(1): 65-82）は取得できておりません。** https://pubs.aeaweb.org/doi/pdfplus/10.1257/aeri.20180582 は HTTP 403 でした。WP は掲載版より分量が多い（付録・追加表を含む）ため、WP に無い数値が掲載版のみに現れる可能性は低いと考えられますが、**「両方を確認した」とは申せません**。

**判定: 確認（範囲限定）。** 「NBER WP 24489 本文に85%は存在しない」は確定。「AER:Insights 版にも存在しない」は未確認です。A_evidence 第1.2節・第5.6節は「NBER working paper 24489本文には見当たりませんでした」と WP に限定して書いており、**この限定は正確**です。手順書側でも同じ限定を保つべきです。

---

### #10 Guest, Bunce & Johnson (2006) の「6件」 — 数値は確認、外挿は要注意

**原典 metadata**: Crossref（https://api.crossref.org/works/10.1177/1525822X05279903）。*Field Methods* 18(1): 59-82、著者 Greg Guest, Arwen Bunce, Laura Johnson。書誌は C_discovery の記載と完全一致いたします。

abstract 逐語:

> "**saturation occurred within the first twelve interviews, although basic elements for metathemes were present as early as six interviews.**"

標本の性質（abstract より）: "sixty in-depth interviews with women in West Africa"。

**「6件」が何の context の数値か**: 飽和（saturation）到達点は **12件**です。6件は「**metatheme の基本要素（basic elements）が既に現れていた**」時点であって、飽和点ではございません。C_discovery 1.8.8 の記述（「最初の12件で飽和」「metatheme の基本要素は6件の時点で既に出現」）は、この区別を正しく保っております。

**software product の顧客 interview への外挿可能性（評価）**:

外挿には以下の断絶がございます。手順書で「早期中止基準」として使う場合、**種類の異なる外挿**になっている点を明記すべきです。

1. **測っている量が違います。** Guest が測ったのは「codebook 上の code / theme が新規に出現しなくなる点」、すなわち**記述の網羅性**です。手順書が必要としているのは「事業判断を下してよいだけの情報が揃った点」、すなわち**意思決定の十分性**です。theme が出尽くすことと、go/no-go を誤らない確率が十分になることは別物です。
2. **母集団の同質性が桁違いです。** 対象は西 Africa 2カ国の、同一の研究 protocol で募集された女性群で、極めて同質です。B2B software の顧客は業種・企業規模・決裁構造で分散が大きく、C_discovery 自身が指摘するとおり segment ごとに必要件数が発生いたします。
3. **目的関数が違います。** 質的研究の飽和は「取りこぼしを避ける」ための保守的な基準です。事業判断で6件で止めることは、**逆方向**（早く切る）に使うことになります。同じ数字を逆向きの目的に使うと、保証の向きが失われます。
4. **手法が違います。** Guest の60件は訓練された調査者による構造化された in-depth interview で、codebook の inter-coder 一致まで管理されております。副業 engineer が単独で行う interview は、この統制を欠きます。統制が緩いほど、必要件数は増えます。

**判定: 数値は確認。ただし「6件で早期中止してよい」という運用は、Guest の結果からは導けません。** 「6件で theme の骨格が見え始めるので一度立ち止まって書き出す」という C_discovery の**現行の書き方（中止でなく中間点検）は妥当**です。Phase 3 の**中止**基準の唯一の根拠として使うのであれば、根拠として弱く、「12件を既定とし、6件は中間 review 点」に留めることを推奨いたします。

---

### #11 「顧客・販路の開拓」48.1% / 47.7% — 部分的に不正確

**原典**: 日本政策金融公庫総合研究所「2024年度新規開業実態調査」PDF（https://www.jfc.go.jp/n/findings/pdf/kaigyo_241127_1.pdf）を local 保存し `pdftotext -layout -enc UTF-8` で抽出。

逐語:

> 「(4) 回 収 数　1,990社（回収率26.0％）」

> 「○　開業時に苦労したことは、「資金繰り、資金調達」（59.2％）、「顧客・販路の開拓」（48.1％）、「財務・税務・法務に関する〔知識の不足〕」…」

> 「○　現在苦労していることは、「顧客・販路の開拓」（47.7％）や「資金繰り、資金調達」（37.0％）が多い（図－24）。」

> 「開業時に苦労したことは、「資金繰り、資金調達」が59.2％と**最も多く**、次いで「顧客・販路の開拓」が48.1％、「財務・税務・法務に関する知識の不足」が36.7％となっている（図－23）。」

**判定: 数値は完全一致。しかし「首位」が誤りです。** 開業時の首位は「資金繰り、資金調達」59.2% であり、「顧客・販路の開拓」48.1% は **2位**です。首位なのは「現在」だけです。

- `A_evidence.md:140` の本文「『顧客・販路の開拓』だけが開業時から現在まで**首位付近**に居座り続ける」は**正確**です。
- `A_evidence.md:504`（第6条）「開業時(48.1%)から現在(47.7%)まで**一貫して首位に居座る**障害は『顧客・販路の開拓』です」は**誤り**です。同一文書内で表現が食い違っております。

**追加の細部**: 図表上の n は設問ごとに異なり、当該2問は 2024年度 **n=1,943**（開業時）/ **n=1,934**（現在）です。全体の n=1,990 とは別です。「n=1,990 で48.1%」と書くと厳密には不正確になります。

---

### #12 中小企業白書の生存率 — 確認（間接）

中小企業庁の白書 PDF は本 session でも取得できませんでした（C_discovery も 403 を報告しております）。そのため **#13 の CRD 記録が頁番号付きで引用している内容**をもって確認といたします。司書が現物を参照して頁を特定した記録であり、二次情報としては強い部類ですが、当方が白書本体を開いたわけではございません。

CRD 記録の逐語:

> 「・『中小企業白書　2017年版』中小企業庁／編　日経印刷　2017年　p109 　起業後の企業生存率の国際比較　0年～5年の生存率。**5年の生存率は81.7%**」
> 「・『中小企業白書　2016年版』 中小企業庁／編　日経印刷　2016年　p418　起業の生存率と長寿企業　1年～36年の生存率。**10年の生存率は72%**」

2023年版についても同記録が「『中小企業白書 2023年版』p.2-198　日本における起業5年の生存率は**80.7%**の記述」を挙げております。

**判定: 確認（間接）。** 3値とも裏付けられました。確信度は「中〜高」（原本未取得のため）。

---

### #13 NDL レファレンス協同データベースの記録 — 部分的に不正確

**原典**: https://crd.ndl.go.jp/reference/entry/index.php?id=1000355744&page=ref_view

記録は**実在**し、当該 URL で取得できました。しかし A_evidence の記述には3点の不正確がございます。

| A_evidence の記述 | 原典 | 判定 |
|---|---|---|
| 「管理番号 1000355744」 | **管理番号は「中央－1－００二一七五一」**。1000355744 は CRD の entry ID（URL の `id=`）です | **誤り**（label の取り違え） |
| 「国立国会図書館の…司書の調査記録」 | **提供館は さいたま市立中央図書館**。NDL は CRD の運営者であって、この記録の作成者ではありません | **誤解を招く**（第5.1節の確信度根拠に「NDL の司書による調査記録」と書かれており、権威付けが実態より強くなっております） |
| 結論は「**該当する数値は発見できず**」 | 回答プロセス中の記述は「**ただ、根拠となるデータはなさそう。**」。回答 field 自体は白書2点を提示するのみで、否定的結論を宣言してはおりません | **部分的に不正確**（趣旨は同じですが、鉤括弧付きの引用形で提示されており、逐語引用ではありません） |

補足として、6.3% の出所も記録から特定できました。日経ビジネス online の記事「『創業20年後の生存率0.3％』を乗り越えるには」中の「創業から5年後は15.0％、10年後は6.3％」です（事例作成日 2024年03月05日、調査種別: 文献紹介）。

**判定: 部分的に不正確。** 「6.3% の裏付けが公的統計に見つからない」という**実質的主張は支持されます**が、管理番号・提供館・結論文言の3点は修正が必要です。

---

### #14 Kauffman Firm Survey の 10.7% / 46.6% — 確認

**原典**: https://www.kauffman.org/wp-content/uploads/2019/12/whoareuserentrepreneurs.pdf を local 保存し `pdftotext -layout` で抽出。

逐語（Executive summary）:

> "we provide the first documentation of the prevalence of user entrepreneurship in the United States: **10.7 percent of all startups and 46.6 percent of innovative startups founded in the United States that survive to age five are founded by users.**"

逐語（Introduction）:

> "Using longitudinal data on the early years of **4,928 U.S. firms founded in 2004** and collected through the Kauffman Firm Survey, we show that **10.7 percent of all startups founded in the United States that survive to age five are founded by users**, and **46.6 percent of startups founded around an innovative product or service that survive to age five are founded by users**."

生存条件についても原典が明示しております:

> "firms is limited to the subset of firms that survived to age five (i.e., firms founded in 2004 that survived at least through 2009). As a result, we are unable [to assess] ... the survival of user-founded firms versus other types"

**判定: 確認。** A_evidence 第1.5節の数値・母集団・「構成比であって成功率ではない」という注意書きは、いずれも原典に忠実です。原典自身が「user 起業家企業の生存率を他 type と比較することはできない」と明記しており、A の注意書きはこの制約を正しく引き継いでおります。

---

## 検証中に発見した、対象表に無い誤り

1. **`A_evidence.md:504`（第6条）の「一貫して首位」** — 上記 #11 のとおり誤り。同一文書の第1.7節本文（「首位付近」）と矛盾しております。
2. **`C_discovery.md:249` の「6,999.327 euro 多く稼いだ（p = .030）」** — Wiley 403 のため**未確認**。かつ SMJ 2024 の abstract は売上効果に言及しないため、この数値を要約の筆頭に置くと原典の重心を誤って伝えます。A と C で同一論文の要約が食い違っている状態です。
3. **`D_competition_pricing.md:234` の「後発参入の平均遅れは13年」** — 数値は正しいものの、原典が併記する時代差（戦前19年 / **戦後5年**）が落ちております。software への外挿では戦後値の方が近いため、「もう遅いという感覚に根拠が薄い」という結論の強さは原典が支える水準を超えております。
4. **RevenueCat の「前年は200倍」（`A_evidence.md:222`）** — 2025年版の400倍は確認できましたが、その前年版の200倍は**未確認**です。
5. **RevenueCat の「$1K→$10K の脱落 約75%」（`A_evidence.md:218`）** — 原典の記述ではなく、17.3% と 4.6% からの派生値です（実測は73.4%）。表中で原典値と派生値が区別なく並んでおります。
6. **Denrell の巻号** — A_evidence は 14(2)、Crossref metadata は issue 3。未解決の軽微な不一致です。

---

## この検証結果が手順書に与える影響

### 壊れた主張と、必要な修正

**(a) 最重要: `doc/MARKET_RESEARCH.md:225` の「early follower 8%」は削除または全面書き換えが必要です。**

現行文:
> 「pioneer の失敗率 47% に対し early follower は 8% という実証があります。**既存市場への後発参入は、避けるべき状態ではなく既定の戦略です。**」

問題は2重です。第一に **early follower ではなく early leader** の値です。第二に、early leader は「成長初期に share 首位を取れた企業」という**成果で定義された集団**であり、その低失敗率を後発参入一般の安全性の根拠にすることは、本手順書自身が第5条で禁じている生存 bias そのものです。

推奨する書き換え:
> 「Golder & Tellis (1993) は、市場 pioneer の47%が失敗し、長期的に share leader であり続けた category は50中4だけであったと報告しております。長期の leader は pioneer の平均13年後（戦後 category では5年後）に参入した企業でした。**したがって『先に入ること』自体に優位の実証はありません。**（注: 同論文の early market leader の失敗率8%は、成長初期に首位を取れた企業のみを集めた値であり、後発参入一般の失敗率ではございません）」

同じ修正を `D_competition_pricing.md:14` と `:226` にも適用する必要がございます。

**(b) `A_evidence.md` 第1条・第7章および `MARKET_RESEARCH.md` の「category 間5.6倍 vs category 内400倍」は、根拠の格を下げる必要があります。**

- 5.6倍は**原典の記述ではなく派生値**であること、400倍は**2025年版・75,000 app 由来**（2026年版・115,000 app ではない）ことを明記してください。
- より本質的に、**確率の比と金額の比を並べているため、分散分解として機能しておりません。** 「category 間の説明力が小さい」という結論自体は、user の自前調査（35,995件）という**独立した証拠**が支えております。RevenueCat の2値は「傍証」に格下げし、結論の主柱は自前調査側に置くことを推奨いたします。
- 現行第1条は「2つの独立した data で確認されております」と書いておりますが、RevenueCat 側が上記の欠陥を持つため、**「2つで確認」という表現は使えません**。

**(c) `A_evidence.md:504`（第6条）の「一貫して首位」を「開業時2位・現在首位」に修正してください。**

第6条の論旨（販路が下がらない障害である）は維持できます。ただし「開業時の最大の障害は資金繰り59.2%」という事実は、副業・低資本の micro SaaS では資金繰り制約が構造的に小さいことの裏返しでもあり、**むしろ手順書に有利な材料**です。正確に書いた方が主張が強くなります。

**(d) `A_evidence.md` 第5.1節の NDL 関連記述を修正してください。**

- 「管理番号 1000355744」→「レファレンス協同データベース 事例 ID 1000355744（管理番号 中央－1－００二一七五一、提供館: さいたま市立中央図書館）」
- 「結論は『該当する数値は発見できず』でした」→「回答プロセスに『ただ、根拠となるデータはなさそう。』と記されております」
- 確信度の根拠から「NDL の司書」という表現を外してください（実際は市立図書館の司書です）。実質は変わりませんが、権威の実態と表記を合わせるべきです。

**(e) `C_discovery.md` 1.7 節の SMJ 2024 要約を、A の記述に合わせて並べ替えてください。**

「6,999.327 euro」を筆頭から外し、abstract が主張する idea termination と非線形 pivot を先に置いたうえで、euro 値は「原典頁未確認・abstract に言及なし」と注記してください。現状は、手順書が「調査の目的関数を売上でなく棄却に置く」（第4条）と決めた根拠を、C 側が自ら弱めております。

**(f) Phase 3 の早期中止基準「6件」を、中止基準から中間点検基準に格下げすることを推奨いたします。**

Guest らの6件は「metatheme の基本要素の出現」であって飽和点ではなく、同質な母集団に対する記述の網羅性の話です。**12件を既定、6件は書き出して立ち止まる点**という C_discovery 現行の運用文はそのまま妥当ですので、手順書側が6件を「中止してよい」根拠として引き継いでいる場合のみ、修正が必要です。

### 壊れなかった（そのまま使える）主張

以下は原典で逐語確認でき、手順書の柱として維持して差し支えございません。

- **Camuffo 2020 の RCT 設計と売上表**（#2）— 限界の記述まで含めて原典に忠実。本書中で最も正確な箇所です。
- **SMJ 2024 の「頑健な効果は idea termination」**（#3）— abstract の重心と一致。**第4条（外れを安く殺す）の根拠は堅牢です。**
- **Golder & Tellis の 47% / 50中4 / 13年**（#4）— すべて逐語確認。**第5条の実証的裏付けは堅牢です。**
- **Denrell の formal 結果**（#6）— abstract に語義まで一致。**第5条の理論的裏付けは堅牢です。**
- **Azoulay et al. の 0.11%→0.26%、1.8倍、41.9歳、45.0歳**（#7・#8）— すべて逐語確認。**第2条の根拠は堅牢です。**
- **「85%」を使わない判断**（#9）— WP 全文に不在を確認。ただし「NBER WP 24489 本文には」という**限定表現を必ず保ってください**。AER:Insights 版は未確認です。
- **日本公庫の 48.1% / 47.7% / n=1,990 / 回収率26.0%**（#11）— 数値は完全一致（「首位」の語のみ要修正）。
- **中小企業白書の 72% / 81.7% / 80.7%**（#12）— 頁付きで裏付け。
- **Kauffman の 10.7% / 46.6% と生存条件の注意書き**（#14）— 逐語確認。

### 検証できなかった項目（手順書で使う場合は「未確認」と明記が必要）

| 項目 | 理由 |
|---|---|
| SMJ 2024 の「6,999.327 euro（p=.030）」 | Wiley HTTP 403 |
| AER:Insights 掲載版に「85%」が無いこと | AEA HTTP 403（WP のみ確認） |
| 中小企業白書 本体の頁記述 | 中小企業庁 PDF 取得不可（CRD 記録経由の間接確認） |
| RevenueCat「前年は200倍」 | 該当版を未取得 |
| Denrell の号数（14(2) か 14(3) か） | 原典 PDF が paywall |
