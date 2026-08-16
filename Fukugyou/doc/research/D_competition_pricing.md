# D: 競合(供給側)分析と、価格・単位経済の調べ方

作成日: 2026-08-11 / 全URL確認日: 2026-08-11
対象読者: 会社員のsoftware engineerが、個人で回せる規模(月数十万円〜のstock収入)のmicro SaaSを立ち上げるための市場調査method設計

---

## 0. 要旨(先に結論)

| # | 問い | 結論 | 確信度 |
|---|---|---|---|
| 1 | 外部toolで競合のtrafficは測れるか | **個人が狙う規模(月数千〜数万visit)では実質測れない。**誤差は±100%を超えることが珍しくなく、SparkToroの検証でもGA相関は最良で0.79、最悪0.50。小規模siteほど精度が落ちるという点は全検証で一致 | 高 |
| 2 | では何を測るか | **数を推定せず、離散eventの日付だけを取る。**価格改定日(Wayback CDX)、release日(changelog/GitHub)、review投稿日、求人掲載日、Form D提出日。これらは推定ではなく観測なので誤差がない | 高 |
| 3 | 競合ゼロは需要ゼロのsignalか | **多くの場合はそう。**ただし「競合ゼロ」は「発見できていない」と区別がつかない。競合ゼロを喜ぶ根拠は学術的にほぼ無い。市場pioneerの失敗率47%に対し early follower は8%(Golder & Tellis 1993, 約500 brand/50 category) | 高 |
| 4 | 「red oceanを避けよ」はfolkloreか | **かなりの程度folklore。**first mover advantageを支持する実証結果は、performance指標にmarket shareを使った研究に偏っている(VanderWerf & Mahon 1997のmeta-analysis)。Blue Ocean Strategyは成功企業のみを事後的に分析したcase studyで、survivorship biasの典型例という批判が査読文献にある | 中〜高 |
| 5 | 現実的なARR水準はどこか | **買収marketの逆算では、profit multiple 3.9x(Acquire.com中央値, 2024・2025)。**「月50万円の利益」の事業は売却時 約2,300万円相当。目標が月数十万円の粗利なら、必要ARRは概ね**$60k〜$150k(年間800万〜2,000万円)**。ただしStripe verified済みIndie Hackers製品の**54%は収益ゼロ**、5%のみが月$8,333超 | 中〜高 |
| 6 | Van Westendorpは使えるか | **単独では使わない。**唯一のincentive-aligned比較実験(Kloss & Kunter 2016, n=253)は「hypothetical性と最小抵抗への着目により偏る」と結論。一方で同論文はBDMと比較可能な予測品質とも述べており、評価は割れている。個人規模では**実価格test > Gabor-Granger > VW** の順で推奨 | 中 |
| 7 | 単位経済の目安 | **ARPAが低いほどretentionが構造的に悪化する。**ChartMogul 2025(約3,500社)ではAI-native製品で月$50未満のtierはGRR 23%/NRR 32%、月$250超のtierはGRR 70%/NRR 85%。**低単価×self-serveはchurnを価格で買っている**構造 | 高 |
| 8 | channelの空きは事前に測れるか | **部分的にしか測れない。**SEO(KD)とmarketplace検索の需要側は測れるが、供給側(そのchannelがまだ空いているか)を事前に測る信頼できるmethodは見つからなかった。KD自体もbacklink数のみのproxyで、intentも品質も見ていない | 中 |

---

## 1. 競合の実態を外から測る手法と、その誤差

### 1.1 traffic推定toolの精度検証

**これが本節で最も重要な表です。個人が参入する規模の市場では、traffic推定toolはほぼ機能しません。**

| 検証 | 実施主体/年 | 標本の定義 | ground truth | 結果 |
|---|---|---|---|---|
| Which 3rd-Party Traffic Estimate Best Matches GA? | SparkToro (Rand Fishkin) / 2022 | 応募1,053 siteから最終**641 site**、12ヶ月×641 = 7,692 site-month。Twitter/email/LinkedIn等で任意提供を募集 | Google Analytics "Users"(2020年6月〜2021年6月) | 相関係数: SEMrush **0.790** / Datos **0.720** / SimilarWeb **0.659** / Ahrefs **0.504**。誤差が**±100%を超えることが頻繁**。「50,000 visitと報告されたsiteの実測が5,000〜100,000の範囲」と明記 |
| How Accurate Are Website Traffic Estimators? | Screaming Frog / 2016 | **25 site**、英国のorganic trafficのみ、2016年2〜4月 | Google Analytics | 合計値: SimilarWeb **+17%** / Ahrefs **−17%** / SEMrush **−30%**。site平均: SimilarWeb **+1%** / Ahrefs **−36%** / SEMrush **−42%**。低traffic siteでは40%超の誤差が常態と明記 |
| 1,787 ecommerce site比較 | Omniconvert | ecommerce **1,787 site** | Google Analytics | SimilarWebがsessionを約**+94%**過大報告。大規模siteほど精度向上、小規模siteで最悪 ※本文未fetch(検索結果経由)のため確信度 中 |

**SparkToroの結論(原文の要旨)**: どのproviderも自社productへ統合できるだけの精度が無かった。推奨は「大規模siteならSimilarWeb、小規模siteならDatos」。ただし**high-confidenceな意思決定には使えない**と明言しています。

**利益相反の開示**: SparkToroは調査中にSimilarWebと密に協働しており、著者自身が比較対象企業の役員と個人的関係があると開示しています。またAhrefsは**organic検索のみ**を測る指標を比較に使われており、著者自身が「unfairな比較」と認めています。

#### 誤差の由来(なぜ小規模で外れるのか)

3rd party推定は全て**clickstream panel**(browser拡張やISP等から収集した閲覧履歴)を母集団へ外挿しています。panelが全internet利用者の1〜3%程度という推計があり、月間数千visitのsiteはpanel内に該当sampleが**0〜数件**しか無いため、外挿倍率が誤差をそのまま増幅します。この構造上、**小規模siteの推定値は「桁が合っていれば上出来」**と扱うのが妥当です。

#### 実務上の運用ルール(推奨)

| 競合の規模 | traffic推定の扱い |
|---|---|
| 月100万visit超 | 桁と前年比trendの参考にはなる。絶対値は信じない |
| 月5万〜100万visit | 順位付け(A社 > B社)には使える。倍率は信じない |
| **月5万visit未満** | **使わない。**個人が参入するmicro SaaS競合の大半はここ |

確信度: **高**(SparkToro/Screaming Frogとも小規模siteでの劣化を独立に報告)

---

### 1.2 求人掲載(job posting)からの読み取り

| 項目 | 内容 |
|---|---|
| 一次source | 競合の採用page、LinkedIn Jobs、日本ならHRMOS/Wantedly等。**掲載日と職種名だけを取る** |
| 学術用途での実績 | Lightcastは220,000超のwebsiteを集約し2010年以降4億3,500万件超の求人を保持。労働経済学のfirm-level研究で広く使用(例: 米上場378社/7,195,863件の求人を用いたgenerative AI採用分析) |
| 誤差・限界(Lightcast/Revelio自身の注記) | ① **1件の求人が複数positionを表す場合がある** ② 掲載しても採用に至らない場合がある ③ BLSの公式統計と**照合できない**(reconcilableでない) |
| micro SaaSでの実用性 | **低い。**個人〜数名規模の競合は求人を出さない。「競合が採用を始めた」= 資金流入か成長のsignalとしてbinaryに使うのが限界 |

確信度: **中**(手法の妥当性は高いが、micro SaaS規模での適用可能性が低い)

---

### 1.3 資金調達履歴 — Crunchbase/PitchBookの無料代替

| source | 何が取れるか | 費用 | 誤差・限界 |
|---|---|---|---|
| **SEC EDGAR full-text search** (sec.gov/edgar/search) | Form D: 米国企業がRegulation Dで私募増資した際の**法定開示**。会社名・調達額・round種別・署名役員。初回売却から**15日以内**に提出義務 | 無料 | **米国法人のみ。**日本・EU企業は対象外。Form Dは「募集総額」であり実際の着金額と一致しない場合がある。免除規定を使わない調達は載らない |
| 官報(日本) | 増資・減資の登記公告 | 無料 | 網羅性が低く、非公開の第三者割当は多くが捕捉できない |
| Y Combinator company directory | batch・分野・現況 | 無料 | YC出身のみ |
| AngelList / product page | 自己申告profile | 無料 | **自己申告のため検証不能** |
| Crunchbase無料tier | 基本profile | 無料 | round詳細は有料。data自体もcrowd-source由来で欠落あり |

**Form Dの最大の利点**: press報道・LinkedIn告知・Crunchbase登録より**数週間〜数ヶ月早く**public化されます。「その市場に金が入り始めたか」を最も早く知れるsourceです。

**副業判断への使い方**: 狙う領域でSeries A以上が入っている = **その市場でVC規模の成長を目指す競合が現れた**、というsignal。micro SaaSにとっては必ずしも撤退signalではなく(下位segmentが空くことが多い)、むしろ「上位が上へ抜けた」機会として読むのが妥当です。

確信度: **高**(Form Dの法的義務と提出期限は一次情報)

---

### 1.4 release頻度(changelog / GitHub)

| 手法 | 取得方法 | 誤差 |
|---|---|---|
| 公開changelog page | RSS/Atomがあれば購読。無ければWayback CDXで差分検出(下記1.5と同じ手順) | changelogは**選別された告知**であり、実際のdeploy頻度とは一致しない。放置されているchangelogは「開発停止」と誤読しやすい |
| GitHub public repo | Releases API / commit活動 | OSS部分のみ。SaaS本体がprivateなら意味を成さない |
| app storeのversion履歴 | App Store / Google Play / Chrome Web Store のupdate日 | **これは最も信頼できるrelease頻度のproxy。**storeが日付を自動記録するため、企業側の裁量が入らない |

**推奨**: micro SaaS競合の「生きているか」判定には、**changelogよりapp store/marketplaceのversion更新日**を使ってください。誤差が構造的に無い観測値です。

確信度: **高**

---

### 1.5 価格改定履歴 — Wayback Machine CDX Serverによる追跡

これは本reportで**最も費用対効果が高い手法**です。推定を挟まず、競合の価格意思決定そのものを時系列で観測できます。

**API base**: `http://web.archive.org/cdx/search/cdx` (認証不要・無料)

**主要parameter**:

| parameter | 意味 |
|---|---|
| `url` | 対象URL(query string含む場合はURL encode必須) |
| `matchType` | `exact`(既定) / `prefix` / `host` / `domain` |
| `from` / `to` | `yyyyMMddhhmmss` 形式の期間指定 |
| `output` | `json` を指定するとJSON array |
| `filter` | field単位のregex filter(例: `filter=statuscode:200`) |
| `collapse` | 隣接する重複行を畳む |
| `limit` | 件数(負値で末尾N件) |

**中核となるquery — 内容が変わったsnapshotだけを列挙する**:

```
http://web.archive.org/cdx/search/cdx?url=example.com/pricing&collapse=digest&filter=statuscode:200&output=json
```

`digest`はarchive内容のhashです。`collapse=digest` は**隣接する同一hashを畳む**ので、返る行はそのまま「pricing pageの内容が変化した日付list」になります。

**注意点(公式仕様に基づく)**:
- `collapse` は**隣接行のみ**を畳みます。A→B→Aと戻った場合、Aが2回出ます(価格を上げて戻した、という事実も検出できるので実務上は有利)。
- digestはHTML全体のhashです。価格以外(bannerやfooterのcopyright年)の変更でも新digestになります。**日付listを得た後、各snapshotを目視で確認する工程が必須**です。
- archive頻度はsiteの人気度に依存します。無名の競合は年数回しかcrawlされないことがあり、**改定日は「その日まで」の精度**にしかなりません。

**誤差の性質**: 「価格が変わった日」は**上限精度が snapshot間隔**。「価格がいくらだったか」は**誤差ゼロ**(archiveされたHTMLそのもの)。

**副業判断への使い方**:
1. 競合3〜5社のpricing pageを3〜5年分取り、価格の時系列表を作る。
2. **値上げしている競合が複数ある = 価値が認められている市場**。値下げ合戦・free tier拡張が続いている = 差別化が効かずcommodity化している市場。
3. plan名とfeature配分の変遷から、**どのfeatureが有料化に耐えたか**が読めます。これは自分のpackaging設計の直接の入力になります。

確信度: **高**(公式API仕様に基づく。実行可能性も確認済み)

---

### 1.6 review増加速度から顧客数を推定する — 誤差が大きすぎる

**結論: 絶対数の推定には使えません。増加"速度"のtrend比較にのみ使ってください。**

| 前提となる係数 | 報告値 | 出典の質 |
|---|---|---|
| app storeのreview率(review 1件あたりのdownload数) | 高価格app 1/60、$0.99 app 1/200、lite版 1/1,500 | 開発者の自己報告。**係数が25倍レンジで散る** |
| review行動のbias | 不満時 65%が投稿、満足時 49%(Apptentive調査) | vendor調査 |
| review促進promptの有無 | promptの有無でreview数が大きく変わる | 定性的記述のみ |

review率の係数が**25倍のレンジで散る**以上、review数から顧客数を出す推定は**桁の推定にもなりません**。

#### 使ってよい使い方

| 使い方 | 妥当性 |
|---|---|
| 同一platform・同一category内での**相対順位** | 妥当。同じreview率biasが両者にかかるため相殺される |
| **同一製品の**時系列でのreview増加率の変化 | 妥当。ただしreview促進campaign開始で不連続に跳ねるので、跳ねを見たら疑う |
| review数 × 係数 = 顧客数 | **不可** |

#### B2B review site(G2 / Capterra)固有のbias

- G2・Capterraはgift card等による**review投稿へのincentive付与を認めています**(sentimentへの対価は規約違反)。したがってreview数は**marketing予算の関数**でもあり、顧客数の関数ではありません。
- G2は10人未満の零細team・個人事業主のuserを構造的に取りこぼす傾向が指摘されています。**micro SaaSの主要顧客層がまさにここ**であるため、G2 profileは実態を反映しません。
- 競合のreview速度が短期間に3倍等へ跳ねた場合、campaignかlaunchのsignalとして読むのが妥当です。

※ G2/Capterraのbiasに関する記述は一次情報(platform規約)と二次情報の混在です。確信度: **中**

---

### 1.7 marketplace公開数値(最も誤差が小さい外部指標)

| platform | 公開される数値 | 精度 | より精密に取る方法 |
|---|---|---|---|
| **WordPress.org plugin directory** | active installs | **有効数字1桁に丸め**(1M+ など) | WordPress APIの `active_installs_growth` と、丸め値が変化した日(Wayback)を組み合わせ、`今週 = 先週 × (1+growth)` で逆算。1,785,543 のような精度が出るとされる。**2019年初以前公開のpluginはgrowth指標が無く適用不可** |
| **Chrome Web Store** | users | 段階的に丸め。上限threshold は 10m(超えるのは13拡張のみ) | 公式には無し。開発者dashboardのみinstall/uninstall/impression/retentionを取得可。**usersはinstall数であり、稼働userではないと公式が明記** |
| App Store / Google Play | 評価数・平均点 | download数は非公開 | 無し |

**この節が重要な理由**: WordPress plugin / Chrome拡張は、**competitorの顧客規模が公開されている稀な市場**です。参入領域としてこれらを選ぶと、市場調査の難易度が一段下がります。逆にweb SaaSは外部から規模が見えないため、調査cost が構造的に高くなります。

確信度: **高**(WordPress の丸め・Chromeのusers定義は公式仕様/公式doc)

---

### 1.8 手法別の誤差まとめ(統合表)

| 手法 | 得られるもの | 誤差の大きさ | 個人規模での実行可能性 | 推奨度 |
|---|---|---|---|---|
| Wayback CDX による価格改定履歴 | 価格の時系列(観測値) | **価格は誤差ゼロ**、日付はsnapshot間隔 | 高(無料・API有) | ★★★ |
| marketplace公開install数 | 顧客規模の桁 | 有効数字1桁(逆算で改善可) | 高 | ★★★ |
| app storeのversion更新日 | release頻度 | ゼロ(store記録) | 高 | ★★★ |
| SEC Form D | 資金流入の有無・時期・額 | 額は「募集総額」で着金と乖離しうる | 高(無料) | ★★☆ |
| review投稿日のtimeline | 顧客獲得の相対trend | 相対比較のみ有効 | 高 | ★★☆ |
| 求人掲載 | 組織拡大のbinary signal | 1件=複数枠の可能性 | 中(競合が小規模だと出ない) | ★☆☆ |
| traffic推定tool(大規模競合) | 桁とtrend | 相関0.50〜0.79、誤差±100%超も頻出 | 中(有料) | ★☆☆ |
| **traffic推定tool(小規模競合)** | — | **使用に耐えない** | — | **✗** |
| review数→顧客数の換算 | — | **係数が25倍レンジで散る** | — | **✗** |

---

## 2. 「競合が多い/少ない」の解釈

### 2.1 競合ゼロは需要ゼロのsignalか

**まず定義を分けます。**「競合ゼロ」には3つの異なる状態が混在しており、これを分けずに議論するのが誤りの元です。

| 状態 | 見分け方 | 判断 |
|---|---|---|
| (a) 誰も試していない | 検索volumeもゼロ、forum投稿もゼロ、過去の撤退事例も無い | **需要ゼロを疑うべき。**最も多いcase |
| (b) 過去に試して全滅した | 撤退したproductのlanding pageがWaybackに残る、forumに「昔○○があったが終了した」 | **構造的な理由がある。**その理由を特定できない限り参入不可 |
| (c) 見つけられていないだけ | 検索語彙が業界内でしか通じない、既存解が Excel/紙/受託 | **最も有望。**ただし「発見できていない」と(a)の区別が最難関 |

(a)と(c)を分ける実務的なtestは、**「今その仕事をしている人は、代わりに何を使っているか」を具体的に名指しできるか**です。名指しできない(=Excelとすら言えない)なら、その業務自体が存在しない可能性が高いと判断できます。

確信度: **中**(この3分類自体は本調査での整理であり、直接の実証research出典はありません)

---

### 2.2 first mover advantageの実証 — folkloreの解体

「先行者利益」は、実証研究では**測り方に強く依存する**ことが示されています。

| 研究 | 標本の定義 | 主な結果 |
|---|---|---|
| **Golder & Tellis (1993)** "Pioneer Advantage: Marketing Logic or Marketing Legend?" *Journal of Marketing Research* 30(2) | **約500 brand / 50 product category**。従来研究がsurvivorのみを含むDBに依存していた点を批判し、**historical analysis**(廃業brandも含む)を採用 | market pioneerの**失敗率47%**、early followerは**8%**。生存したpioneerの平均market shareは約10%、early market leaderは28%。early market leaderはpioneerの**平均13年後**に参入 |
| **Min, Kalwani & Robinson (2006)** *Journal of Marketing* 70(1), 15-33 | **264の新規industrial product-market** | 「really new product」で市場を作ったpioneerは生存自体が困難。「incremental innovation」で始まった市場ではpioneerのrisk は大幅に低い。**early followerのrisk は両者で変わらない** |
| **VanderWerf & Mahon (1997)** *Management Science* 43(11) | 学術文献中の**66件の実証test**のmeta-analysis | 54/66がFMAを支持。しかし**performance指標にmarket shareを使ったtestは、収益性や生存率を使ったtestより有意にFMAを見出しやすい**。個別に選んだ産業からsamplingしたtest、参入者の競争力を統制しないtestも同様 |

**この3本から導ける実務的な含意**:

1. **「先に出したから勝つ」は、market shareという指標を選んだときにだけ強く見える現象**です。生存率・収益性で測ると支持は弱くなります。副業の目的が「収益」である以上、market shareで測った先行者利益は目的関数と無関係です。
2. **本当に新しいものを最初に出す立場が最も危険**です(Min et al.)。逆に、既存の解があってその改良版で入る立場は、pioneerのrisk を負わずに済みます。
3. **後発参入の平均遅れは13年**(Golder & Tellis)。「もう遅い」という感覚には実証的根拠が薄いことになります。

確信度: **高**(いずれも査読journalの引用度の高い実証研究)

---

### 2.3 「red oceanを避けよ」の根拠 — Blue Ocean Strategyへの批判

Blue Ocean Strategy(Kim & Mauborgne)は「red oceanを避けよ」の最も影響力ある源流ですが、方法論的批判が査読文献に存在します。

| 批判点 | 内容 |
|---|---|
| **survivorship bias** | 研究対象が**成功企業のみ**。blue ocean戦略を採って失敗した事例の数は調査されていない。したがって「blue oceanなら成功する」という条件付き確率は算出されていない |
| 事後合理化 | 成功したcase を後から blue ocean枠組みで説明しており、**予測力(predictive character)を持たない**という指摘 |
| 一般化可能性 | case study中心で統計的実証が乏しく、generalityが担保されない |
| 前提の脆弱性 | 「十分な数のblue ocean marketが存在する」という前提が検証されておらず、実際のblue ocean marketは純粋に無競争であることは稀 |

主要な批判文献: Burke, van Stel & Thurik "Blue Ocean versus Competitive Strategy: Theory and Evidence" (ERIM Report Series / SSRN)、および *The International Journal of Business & Management* 掲載の "A Critique of Blue Ocean Strategies: Exploring the Limits of Creating Uncontested Markets"。

**評価**: 「red oceanを避けよ」は**実証されていない規範であり、folkloreである可能性が高い**と判断します。ただし「red oceanでも勝てる」の実証もあるわけではありません。正確には、**「競合の多寡そのものが成否をあまり説明しない」**というのが2.2の実証群から導ける最も安全な読みです。

確信度: **中〜高**(批判の存在は確実。ただしBOS支持側の実証も同様に弱いため、「どちらも実証されていない」が正確な状態)

---

### 2.4 後発参入が成功するmechanism

Golder & Tellis / Min et al. から読み取れる、後発が優位に立つ機構は次の通りです。

| mechanism | 内容 | 個人規模での実行可能性 |
|---|---|---|
| **free-rider effect** | pioneerが負担した市場教育・技術検証・規制対応のcostを負わずに済む | **高い。**「その業務にsoftwareを使う」という発想自体が既にinstallされている状態で入れる |
| **pioneerの理想点のずれ** | pioneerは需要が固まる前に設計したため、成熟後の理想点からずれる。後発は成熟後の理想点を狙える | **高い。**既存製品のreviewの★1〜★2は、まさに「理想点とのずれ」の一次情報 |
| **incumbent inertia** | 既存顧客・既存architectureに縛られ、大胆な作り替えができない | **高い。**個人開発者にlegacyは無い |
| **技術的断絶** | 前提技術が変わると、pioneerの蓄積が資産でなくなる | **中。**技術の乗り換え時期を当てる必要がある |
| **niche down** | 全体市場のleaderが採算に合わないsegmentへ特化 | **高い。**ただし後述する通り、segmentを絞ると市場規模の下限に当たる |

**「競合分析」を「差別化の入力」に変える具体的手順**:

1. 競合3〜5社のreviewから**★1〜★2のみ**を全件収集する(★4〜5は購入意思決定に無関係)。
2. 不満を「機能不足」「価格」「複雑さ」「support」「特定業種で使えない」へ分類する。
3. **「特定業種で使えない」に集中している場合のみ、niche downが有効**です。他の3つは競合が次のreleaseで潰せるため、持続的な差別化になりません。

確信度: **中**(mechanismは学術文献由来、手順は本調査での実務化提案)

---

## 3. Micro SaaS買収marketからのARR逆算

### 3.1 買収marketの実勢価格

| source | 標本の定義 | 倍率 |
|---|---|---|
| **Acquire.com** Biannual Acquisition Multiples Report (2026年1月公開、2025年data) | Acquire.com上の成約案件(匿名化された当事者提供data)。**enterprise value $10M未満**の案件が中心。**標本件数は報告書に明記されていない** | SaaSの**profit multiple中央値 3.9x**(2024年・2025年とも同値)。平均は「low-to-mid 4x」。売却までの平均**81日**。profitableなSaaSの利益率平均は2023年67%→2024年71%で以降横ばい |
| **Flippa** SaaS Valuation Multiples | Flippa成約案件。**標本件数・期間の明示なし**(page 403のため検索結果経由) | SaaS上位四分位 約**6.13x**。小規模SaaSは**profit 2.5x〜4.5x / revenue 2.0x〜3.5x**。deal size別中央値は $10K〜$100K帯 **1.68x** → $1M+帯 **2.43x** |
| **SaaS Capital** 2025 Private SaaS Company Valuations(第13回年次調査) | **1,500社超の private B2B SaaS**。募集方法は非開示 | anchorとなるpublic SaaS index **7.0x run-rate ARR**。予測値: **bootstrapped 4.8x ARR / equity-backed 5.3x ARR** |
| 公開SaaS市場(参考) | 上場SaaS | revenue multiple: 2022年平均17x → 2023-2024年 約7x → 2025年末 約5.5x |

**重要な注意 — この3つは同じものを測っていません**:

| | Acquire.com / Flippa | SaaS Capital |
|---|---|---|
| 倍率の分母 | **profit(利益)** | **ARR(売上)** |
| 対象 | EV $10M未満、多くはsolo/小team | ARR $1M〜$50M級の機関投資対象 |
| 個人副業に近いのは | **こちら** | 参考のみ |

**profit multiple 3.9x と ARR multiple 4.8x を混同しないでください。**利益率70%のSaaSなら、profit 3.9x ≒ revenue 2.7x です。個人開発SaaSの現実的な換算はAcquire.com側です。

確信度: **中〜高**(Acquire.comは標本件数非開示、Flippaは本文未取得のため)

### 3.2 逆算 — どの水準のARRが現実的か

副業の目標が「月数十万円のstock収入」である場合の逆算です。1 USD = 150円で換算しています。

| 目標(月次の税引前利益) | 年間利益 | 必要ARR(利益率70%想定) | 売却時の想定価格(profit 3.9x) |
|---|---|---|---|
| 20万円 | 240万円 | 約 **$23k** (343万円) | 約 936万円 |
| 50万円 | 600万円 | 約 **$57k** (857万円) | 約 2,340万円 |
| 100万円 | 1,200万円 | 約 **$114k** (1,714万円) | 約 4,680万円 |

**この表の使い方(逆算の本来の目的)**:

1. 「月50万円」を狙うなら、必要なのは **ARR 約860万円 = MRR 約71万円** です。
2. 平均単価月$30(4,500円)なら、**約160契約**。月$100(15,000円)なら**約48契約**。
3. **160契約と48契約では、必要なmarketing量が3倍以上違います。**単価設計は市場規模の問題ではなく、**自分が到達可能な顧客数の問題**として先に決めるべきです。
4. さらにchurnを織り込む必要があります。月churn 5%(低単価self-serveの現実値、後述5節)なら、160契約を維持するのに**月8契約の純増が必要**で、成長させるにはそれ以上。**月8件の新規獲得を継続できるchannelがあるか**が、この事業の実際の制約条件です。

**この逆算の最大の価値は、「ARR目標」ではなく「月あたり必要新規獲得数」に翻訳される点にあります。**市場規模の推定より、この数字のほうが意思決定に効きます。

確信度: **高**(算術。前提となる倍率・利益率の確信度は3.1に準じます)

---

## 4. 価格調査の手法

### 4.1 Van Westendorp Price Sensitivity Meter(PSM)

**手順**: 対象製品について4問を尋ね、累積分布の交点から価格帯を得ます。
1. 高すぎて買わない価格 2. 高いが検討する価格 3. 安いと感じる価格 4. 安すぎて品質を疑う価格

#### 方法論的批判(必読)

| 批判 | 内容 | 出典の性質 |
|---|---|---|
| **hypothetical bias** | 実際の支払いを伴わないため、回答が実購買と乖離する | Kloss & Kunter (2016) が実証比較 |
| **最小抵抗への着目による偏り** | PSMは「顧客の抵抗が最小になる点」を探す構造のため、**設定可能だった価格より低い"最適"価格を出す(lowballing)** | 同上および実務家の一致した指摘 |
| **理論的基盤の欠如** | 4問のsurveyのみで、conjoint等が持つ予測的実績の蓄積が無い | 実務家批判 |
| **文脈からの隔離** | 単一製品の価格を、**他の製品属性や競合brandから切り離して**尋ねる | 実務家批判 |
| **価格感度curveの形が分からない** | 閾値の知覚しか取れず、需要弾力性の大きさ・形状が出ない | 実務家批判 |

**唯一のincentive-aligned比較実験**: Kloss & Kunter (2016) "The Van Westendorp Price-Sensitivity Meter As A Direct Measure Of Willingness-To-Pay", *European Journal of Management* 16, 45-54。**253名の消費者**に同一製品を3手法(contingent valuation / BDM mechanism / VW PSM)で評価させた、PSMをincentive-aligned手法と比較した初の実証。

**結果は両義的です**: hypothetical性と最小抵抗への着目によりPSMは**偏った結果を出す**と結論しつつ、測定結果はincentive-alignedなBDMと**比較可能**であり、WTP抽出手法として**予測品質は高い**とも述べています。つまり「系統的にずれるが、ずれ方が安定しているので相対比較には使える」という位置づけです。

なお一般に、**incentive-aligned設定では非incentive-aligned設定より回答者の価格感度が高く出る**ことが知られており、hypothetical surveyはWTPを過大評価する方向にも働きます。VWのlowballing傾向とは逆方向の bias であるため、**両者が打ち消し合った結果としての「BDMと比較可能」である可能性**は否定できません。

確信度: **中**(査読論文はn=253の1本のみ。批判の多くは実務家由来)

### 4.2 Gabor-Granger

**手順**: 事前に定めた価格点で購入意向を尋ね、Yesなら上の価格、Noなら下の価格へ移動して閾値を特定。全回答者の閾値から**需要curveと収益最大化価格**を導出します。

| 項目 | 内容 |
|---|---|
| 出力 | 需要curve、価格弾力性、収益最大化価格 |
| 必要sample | 実務gudanceで**最低100完了**。segment別に比較するなら**segmentごとに100** |
| 限界 | ① **価格点をこちらが与える**ため、想定外の価格帯は発見できない ② 価格について尋ねられていると分かるため、**値切り目的で低く答える**誘因がある ③ 「なぜその価格か」の理由が取れない ④ 競合価格を織り込まない |

**VWとの使い分け**: 受容価格帯の見当が全く付かない探索段階はVW、**帯が決まってから収益最大化点を詰めるのがGabor-Granger**、というのが実務上の合意です。

確信度: **中**(sample size guidanceは実務家source。手法自体の記述は一致)

### 4.3 conjoint / MaxDiff

**Choice-Based Conjoint (CBC) のsample size rule of thumb**(Sawtooth Software公式):

```
n = (c × t × a) / 500
```

- `n` = 必要回答者数
- `c` = 単一属性内の**最大水準数**
- `t` = 1人あたりのchoice task数
- `a` = 1 taskあたりのconcept数(None選択肢を除く)

**worked example**(公式掲載): 属性3つ(水準3・6・4)、1 task 3 concept、1人8 task → n = (6×8×3)/500 ≈ **288名**。

**公式の但し書き**:
- 「500 exposureは大半のcaseで**最低線**。実務上は水準あたり**1,000 exposure**を見込むほうが安全」
- この式は**aggregate推定しか無かった時代のもの**で、現在主流のHierarchical Bayesによる個人単位modelingには最適ではない

**MaxDiffについては、この公式pageに guidance の記載はありません。**

#### 個人規模での実現性の評価

| 手法 | 必要sample | 個人副業での実現性 | 判定 |
|---|---|---|---|
| Van Westendorp | 100〜(segment別なら×segment数) | 中。knowledge があるcommunityで100名は現実的でない場合が多い | △ |
| Gabor-Granger | 100〜 | 中 | △ |
| CBC conjoint | **288〜(上記例)、安全側で576〜** | **低。**設計・分析にsoftware(Sawtooth/Conjointly)とcostが必要 | **✗** |
| MaxDiff | conjointに準ずる | **低** | **✗** |
| **実価格test** | 訪問者数次第 | **高** | **◎** |

**推奨**: 個人規模では**conjoint / MaxDiffは費用対効果が合いません**。1〜2名の個人がB2B micro SaaSで300名の適格回答者を集めるcostは、実価格testを回すcostより高くなります。

### 4.4 実価格test — 個人規模での第一選択

| 論点 | 実務上の作法 |
|---|---|
| 対象 | **新規訪問者のみ。**既存顧客・再訪問者を含めない |
| 期間 | 最低**4〜6週間**(conversion cycleと初期retentionを捉えるため)。年額planを含むなら**8〜12週間** |
| 既存顧客の扱い | **grandfathering**(旧価格の維持)が最も安全。価格改定時にgrandfatheringを実施した企業はchurnが少ないとの報告があります(ProfitWell) |
| 公平性risk | 同一製品で異なる価格を提示していることが発覚すると、信頼を毀損します。**法域によっては差別的価格設定の法的論点**にもなります |
| **最大の落とし穴** | **A/B testは短期のconversionを測るが、長期のretentionを測らない。**価格を下げてconversionが上がっても、3ヶ月後にchurnが増える結果は大半のtest期間に入りません |

**個人規模での現実的な代替案**: 同時並行のA/B testではなく、**時期を分けた前後比較(sequential test)**を推奨します。同一時点で異なる価格を出さないため公平性riskが無く、価格ごとの実データが取れます。季節性の交絡は残りますが、そもそも個人規模では統計的有意に達するsample が集まらないため、**A/B testの統計的厳密性は最初から達成できません**。

確信度: **中**(実務作法は複数source一致だが、査読研究ではありません)

### 4.5 競合のpricing pageから価格帯を測る手順

推定を一切含まない、確実に実行できる手順です。

| step | 作業 | 出力 |
|---|---|---|
| 1 | 競合5〜10社のpricing page URLを列挙 | URL list |
| 2 | 各URLをWayback CDX (`collapse=digest`) にかける | 内容変化日のlist |
| 3 | 各変化日のsnapshotを開き、plan名・価格・上限値・feature を表に転記 | **価格の時系列表** |
| 4 | 現行価格を**同一単位に正規化**(月額/user、月額/組織、従量単位) | 比較可能な価格list |
| 5 | 中央値・四分位・最安・最高を出す | 価格帯 |
| 6 | 「entry planの価格」と「最上位planの価格」の比(price ladder ratio)を出す | packaging設計の入力 |

**step 4が最も間違えやすい箇所です。**「$29/month」が per-user なのか per-workspace なのかで実効単価は10倍変わります。plan名の横の小さい注記まで転記してください。

**step 6の意味**: 個人開発SaaSの典型的な失敗は、**上位planを作らないこと**です。競合のladder ratio(最上位/最下位)が3〜10倍のところ、自分だけが単一価格だと、支払い意思の高い顧客から取り損ねます。

確信度: **高**(手順の実行可能性は確認済み)

---

## 5. 単位経済のbenchmark

### 5.1 retention / churn

**すべての表で標本の定義を明記しています。定義が書けないbenchmarkは掲載していません。**

#### ChartMogul(subscription analytics vendorの実data — 自己申告ではない)

| 報告書 | 標本の定義 | 主要数値 |
|---|---|---|
| **The AI Churn Wave (2025)** | ChartMogul上の**約3,500社**をwebsite scrapingで分類: B2B SaaS 約2,700 / B2C SaaS 約600 / AI-native 約200。retention算出は**ARR $250k以上**を対象。2025年1〜9月のtrend | **B2B SaaS: NRR中央値 82% / 上位四分位 97%**<br>**B2C SaaS: NRR中央値 49%**<br>**AI-native: GRR中央値 40%(1月の27%から改善) / NRR中央値 48%** |
| **The New Normal (2024)** | ChartMogul上の**2,500社超**の匿名化・集計revenue data。2021〜2024年のH1。ARPA分析は**ARR $300k以上**が条件 | NRR 100%以上の企業のcustomer churn中央値 **約3.5%**、NRR 60%未満の企業は**7%**。subscriber 12,000人超の企業でNRR 100%以上を達成したのは**6%**のみ(典型NRR 76%) |
| Retention Benchmarks (2,100社分析) | ChartMogul上の**2,100社超**。2021年 vs 2022年 | ARPA **$10/月未満**の企業でNRR 100%超を達成したのは**2.7%**。ARPA **$500/月超**では**41.1%**。NRR 100%超の企業は年成長43.6%、NRR 60%未満は13.1% |

#### AI-native製品の価格帯別retention(2025) — 本reportで最も実務的な表

| 価格帯 | GRR | NRR |
|---|---|---|
| 月 **$250超** | 70% | 85% |
| 月 **$50〜$249** | 45% | 61% |
| 月 **$50未満** | **23%** | **32%** |

**この表の意味**: 月$50未満のtierは**GRR 23%** — 1年で顧客の8割弱が離脱します。「安くして数を取る」戦略は、micro SaaSでは**獲得costを永久に払い続ける**構造になります。単価を上げることは利益率の問題ではなく、**事業が成立するかの問題**です。

※ この表はAI-native製品(約200社)のものであり、AI-nativeは一般に新しくexperimental な利用が多いため、成熟したtoolより低く出ている可能性があります。価格帯間の**相対関係**は他報告書のARPA別傾向と整合しており、そちらは確信度が高いと判断します。

#### B2B SaaS全体(Benchmarkit)

| 項目 | 数値 |
|---|---|
| 標本 | 2025年版で**500社超のB2B企業**(2024年版は約1,000社)。2024年data、2022・2023年との比較付き |
| GRR | 過去3年で **90% → 88%** へ微減 |
| NRR | **101%** |
| New CAC ratio | 新規顧客ARR $1獲得に **S&M費 $2.00**(中央値) |
| CAC payback期間 | 2022年比で中央値**+12.5%** |
| 成長率 | 中央値 **26%**(2024年)。上位四分位は60%(2023)→50%(2024)へ低下 |
| gross margin | **77%**(中央値) |
| S&M費率 / R&D費率 | **37% / 34%**(対revenue中央値) |
| ARR per FTE | **$200,000〜$300,000超**(規模による) |

#### SMB向けSaaSのchurnが高い構造的理由

**これは「product が悪いから」ではなく、顧客集合の性質です。**

| 要因 | 根拠となるdata |
|---|---|
| **顧客企業そのものが消滅する** | 米国: BLS Business Employment Dynamicsに基づき、新設事業所の1年後生存 約79%、5年後 約49%、10年後 約34%(bls.govがautomated fetchを拒否したため一次pageは未取得。確信度 **中**)<br>日本: 2023年版中小企業白書は起業後**5年後の生存率80.7%**(帝国データバンク委託調査)。ただし白書自身が「DB収録企業の特徴と収録までのlagにより、**実際の生存率より高めに算出されている可能性**」と注記 |
| 意思決定者が1人 | その1人が退職・異動すると契約ごと消える |
| 統合が浅い | 深いintegrationを組まないため**switching costが低い** |
| 予算の変動が大きい | 景気・季節の影響を直接受ける |

**日米の生存率の差(5年で49% vs 80.7%)は極めて大きく、そのまま受け取るべきではありません。**BLSは「事業所(establishment)」、白書は帝国データバンクDB収録「企業」を数えており、**母集団の定義が違います**。白書自身がbias を認めている点も踏まえ、**日本のSMB向けSaaSでも顧客消滅由来のchurnは無視できない**と考えるのが安全です。

**含意**: SMB向けは月1%程度のchurnが「顧客側の廃業」だけで発生しうるため、**product改善では下限に当たります**。この構造から逃れる方法は、(a) 顧客規模を上げる (b) 年額契約にする (c) 消滅しにくい業種を選ぶ、の3つです。

年額契約については、Paddle/ProfitWellが「年額subscriberは月額subscriberの**約1/3のchurn率**」と報告しています(全segment横断)。※ 標本定義が公開されていないため確信度 **中**。

### 5.2 conversion(free → paid, trial → paid)

| 標本 | 手法 | 数値 |
|---|---|---|
| **Kyle Poyar (OpenView) / Lenny Rachitsky / Pendo による共同survey、1,000製品超**。B2B SaaS中心だがprosumer/micro-SMBから大企業向けまで含む。募集方法・実施年は記事上で非開示 | 自己申告survey | **freemium(self-serve): Good 3〜5% / Great 6〜8%**<br>**freemium(sales-assist): Good 5〜7% / Great 10〜15%**<br>**free trial: Good 8〜12% / Great 15〜25%**<br>developer向け製品の中央値 **5%**(非developer向けの約半分) |
| OpenView 2022 Product Benchmarks(Amplitude共同)。**450社超**。ARR構成: <$1M 24% / $1-5M 22% / $5-30M 26% / $30M+ 28%。55%がproduct-ledを自認 | 自己申告survey | 突出したPLG/freemium企業は**paid広告とoutbound salesからの獲得が少ない** |

**重要な注意 — この数字は自己申告です。**「Good / Great」という提示形式自体が、回答者の自己選択と丸めを含みます。ChartMogulのようなplatform実dataではありません。確信度: **中**。

**分母の違いに注意**: freemium(2〜8%)とtrial(8〜25%)の差の大半は、**分母が違うこと**で説明できます。freemiumは全無料userが分母、trialは購入検討中の高intent userが分母です。**手法の優劣ではありません。**

### 5.3 CAC / LTV:CAC

**この節は意図的に薄くしています。**理由: 個人副業のmicro SaaSでは、CACの大部分が**自分の時間**であり、金銭CACのbenchmarkが意味を成しません。

| benchmark | 標本 | 数値 |
|---|---|---|
| New CAC ratio(B2B SaaS) | Benchmarkit、500社超、2024年data | 新規ARR $1あたり **S&M $2.00**(中央値) |
| private SaaS のNRR/GRR | SaaS Capital年次調査、1,500社超のprivate B2B SaaS | bootstrapped scale-up($3M〜$20M ARR)でNRR中央値 103% / GRR中央値 91% ※二次情報経由のため確信度 **中** |

**個人規模で代わりに測るべき指標**:

| 指標 | 定義 | なぜこちらか |
|---|---|---|
| 時間あたり獲得数 | 投下した実作業時間 ÷ 新規契約数 | 副業の真の制約は資金ではなく時間 |
| payback(時間) | 1契約の年間粗利 ÷ 時給換算した獲得cost | 「この獲得活動を続けるべきか」の判断に直結 |
| 必要月次純増数 | (目標契約数 × 月churn率) + 成長分 | 3.2節の逆算の出口。**この数字が達成不能なら事業計画が成立していない** |

確信度: **中**(benchmarkは出典あり。個人向け代替指標は本調査での提案)

---

## 6. distribution(流通)の調査

### 6.1 SEOの難易度指標(KD)の意味と限界

**Ahrefs KDの計算方法(公式)**:
1. 対象keywordの**上位10 page**を取得
2. 各pageへlinkしているwebsite数(referring domain数)を数える
3. その平均を**0〜100の対数scale**にplot

**Ahrefs自身が明示している限界**:
- 「keyword difficultyは常に**推定でしかない**。Googleは全ranking factorを開示していない」
- 「**KD指標だけには依拠できない**」— 手動のSERP分析を併用せよ
- backlinkのみを見ており、**content品質・search intentの合致・SERP feature・自site のauthority を一切考慮しない**
- referring domainの**質**は見ず、数のみ

**KDの実務的な限界(本調査の評価)**:

| 限界 | 影響 |
|---|---|
| 自sideのdomain authorityを考慮しない | **新規domainにとってはKD 5もKD 30も等しく困難**。KDは「平均的なsiteにとっての難易度」であり、authority ゼロのsiteの難易度ではない |
| intentを見ない | KDが低くても、上位が全て公式doc・比較site・大手mediaなら、個人siteに席は無い |
| tool間で計算式が違う | Ahrefs KDとSemrush KD%は別物。両者を比較してはいけない |
| **B2B nicheでは検索volume自体が小さすぎる** | 月間検索50件のkeywordはtoolで「volume 0」と表示されることがある。**micro SaaSが狙うkeywordの多くがここ** |

**推奨する代替手順**: KD数値ではなく、**上位10件の実体を目視で分類**してください。

| 上位10件の内訳 | 判定 |
|---|---|
| 個人blog・小規模siteが3件以上 | **参入余地あり** |
| 全て公式doc・大手media・比較site | 参入不可(KDが低くても) |
| 質問系site(Stack Overflow / 知恵袋)が上位 | **意図に合うcontentが存在しない = 最大の好機** |

確信度: **高**(KDの計算方法と限界はAhrefs公式の記述)

### 6.2 marketplace内SEO

**求められた「Shopifyの発見の何割がstore内検索か」という数値は、公式には見つかりませんでした。**

| 確認したこと | 結果 |
|---|---|
| Shopify Partners blog "Improving discoverability on the Shopify App Store" (2022年1月7日) | 定量的な記述は**「personalized recommendation rowによりmerchantがinstallするappの多様性が2倍になった」の1点のみ**。channel別の install 内訳は非公開 |
| shopify.dev の App Store doc | merchantはApp Storeの閲覧、admin内のrecommendation、Sidekickへの質問からappを発見する、と定性的に記述。**割合は非公開** |
| 「検索がmerchantがappを見つける主な手段」という記述 | Shopify系のcontentに存在するが、**一次資料での裏付けが取れませんでした**。確信度 **低** |

**評価**: **marketplace内の発見channelの内訳は、platform側が公開していません。**したがって「marketplace内SEOの空きを事前に測る」ことは、公式dataからは不可能です。

**代替手段(不完全だが実行可能)**:
1. 対象marketplaceのcategory内で、目標keywordを検索し**上位20件のreview数の分布**を見る。上位のreview数が全て3桁なら参入困難、2桁が混ざるなら余地あり。
2. **install数が公開されるmarketplace(WordPress / Chrome)を優先する**。1.7節の通り、これらは競合規模が観測可能な稀な市場です。

確信度: **中**(不在の確認は行いましたが、非公開情報が存在しないことの証明ではありません)

### 6.3 channel別の評価

| channel | 事前に測れるか | 測る方法 | 個人規模での適性 |
|---|---|---|---|
| **SEO** | △(需要側は測れる、供給側の空きは目視) | 検索volume + 上位10件の実体分類 | 高(時間はかかる) |
| **marketplace(WordPress/Chrome)** | ○ | 競合のactive install数が公開されている | **最高** |
| **marketplace(Shopify/その他)** | ✗ | 内訳非公開。上位のreview数分布で代替 | 中 |
| **community driven** | ✗ | 事前測定手段が無い。参加して観察するしかない | 高(自分が当事者なら) |
| **affiliate** | △ | 競合のaffiliate program の料率が公開されていれば、その市場でaffiliateが機能している証拠 | 低(個人では管理costが重い) |
| **API / integration経由** | ○ | 相手platformのdirectory掲載数・categoryの空きが観測可能 | 高 |
| **paid広告** | △ | Semrush Advertising Research等で競合のbid keywordが見えるが、**推定精度は15〜30%程度**と言われ、clickstream panel(全user の1〜3%)からの外挿。niche競合ではdataが疎で機能しない | **低**(3.2節の逆算通り、必要契約数が少ないため広告費を回収しにくい) |

**「channelの空きを事前に測れるか」への回答**:

**測れるのは需要側(そのchannelにどれだけの人がいるか)だけで、供給側(そのchannelがまだ空いているか)を事前に測る信頼できる手段は見つかりませんでした。**唯一の例外が**install数が公開されるmarketplace**で、ここだけは競合の占有度が直接観測できます。

したがって実務的には、**「channelの空きを測ってから参入する」のではなく、「測れるchannelを持つ市場を選ぶ」**のが、個人規模で取れる唯一の合理的戦略だと判断します。

確信度: **中**(不在の確認に基づく判断です)

### 6.4 Product Hunt等のlaunch channel

**信頼できる一次dataが見つかりませんでした。**検索で得られた数値(「featured launchで1,000〜5,000 visitor、10〜150 signup」等)は、いずれも出典の無いblog・比較記事由来で、本reportのsource規律に反するため**採用しません**。

Product Hunt公式は launch別の traffic/conversion統計を公開していません。**「Product Huntで何人取れるか」は事前に測れない**、というのが本調査の結論です。確信度: **中**。

---

## 7. 収益実dataが公開されているsourceと、survivorship biasの扱い

### 7.1 source list

| source | 何が公開されるか | 検証の有無 | 標本の性質 |
|---|---|---|---|
| **Baremetrics Open Startups** (baremetrics.com/open-startups) | MRR・ARR・churn率・LTV・顧客数のlive dashboard | **決済processor(Stripe / Braintree / Recurly)直結**のため自己申告ではない | **強い自己選択。**公開を選ぶのは概ね順調な企業。Buffer / Ghost等 |
| **Indie Hackers**(Stripe verified製品) | 月次revenue | Stripe連携によるverified表示あり | 同上。ただし後述の通り**分布の裾は公開されている** |
| **Stripe Atlas guides** | 起業・法人設立の手続きguide、時折benchmark記事 | Stripe自身のdata | Atlas利用企業に限定 |
| **上場SaaSのS-1 / 決算資料** | ARR・NDR・CAC・gross margin等の監査済み数値 | **監査済み。最も信頼できる** | **極端なsurvivorship bias。**IPOに到達した企業のみ。個人規模との類似性はほぼ無い |
| **ChartMogul / Benchmarkit / SaaS Capital の報告書** | 集計benchmark | ChartMogulはplatform実data、他はsurvey | 各社のtool利用企業/回答企業に限定 |
| **MicroConf State of Independent SaaS** | bootstrapped SaaSのMRR分布・churn・marketing | 自己申告survey。**要email登録** | MicroConf参加者。標本数はpage上非公開 |

### 7.2 survivorship biasの実態 — 数字で見る

**Indie Hackersのdata は、この bias の大きさを定量化できる稀な事例です。**

| 分析 | 標本の定義 | 結果 |
|---|---|---|
| Scraping Fish社の分析 | **Indie Hackers上のStripe verified製品 937件**、2022年7月16日時点のsnapshot | **54%超が収益ゼロ**。月$8,333($100k/年)超は**約5%のみ**。「outlierが完全にdataを支配している」と明記 |
| Indie Hackers上の別分析 | Stripe verified **5,079 project** | 月次revenue中央値 **$169**。月$10k超かつ月成長50%超の「breakout」は**48件 = 0.9%** ※出典はIndie Hackersのuser投稿のため確信度 **中** |

**この数字の正しい読み方 — 二重のbiasがかかっています**:

1. **上向きのbias**: Indie Hackersに製品を登録し、かつStripeを連携する人は、既にある程度本気で取り組んでいる層です。着手すらしなかった人、登録前に諦めた人は数に入りません。
2. **下向きのbias**: 収益ゼロの54%には、**まだlaunch前・実験段階の製品が大量に含まれます**。「失敗率54%」ではありません。
3. **時点のbias**: 2022年7月の断面です。その後成功した製品も、撤退した製品も反映されません。

**したがって「54%が失敗」とも「5%しか成功しない」とも読むべきではありません。**この分布から言えるのは、**「結果の分布が極端に歪んでおり、中央値は成功の目安として無意味」**という点だけです。中央値$169は「典型的な結果」ではなく「大量のゼロ〜低額と少数の高額が混在した分布の中央」です。

### 7.3 micro SaaSの収益分布(二次集計 — 出典chainに注意)

Freemius "State of Micro-SaaS 2025" は複数調査を集約した二次資料です。**原典の標本定義が確認できないものが混在するため、以下は参考値として扱ってください。**

| 数値 | 原典として示されているもの | 確信度 |
|---|---|---|
| 約70%が **MRR $1,000未満** | MicroConf State of Independent SaaS(約700 founder) | 中 |
| 18%が MRR $1,000〜$5,000 | 同上 | 中 |
| profitableなmicro SaaSの中央値 **MRR $4.2k**(ARR約$50.4k) | Rocking Web 1,000製品分析 | **低**(原典の手法未確認) |
| 上位1%が MRR $50k超 | 同上 | **低** |
| MicroConf 2025参加者230名のうち**28%がMRR $100k超**(無借金・VC無し) | MicroConf conference来場者 | 中(ただし**conference参加者という強い自己選択**) |
| 年間trialでcredit card事前登録を求める割合 70.6%、card必須trialのconversion 50% vs opt-in 18% vs freemium 3〜4% | 複数source混在 | **低**(原典不明) |

**MicroConf 2025の「28%がMRR $100k超」は、survivorship biasの教科書的な例です。**有料conferenceに渡航して参加できる bootstrapped founder は、定義上成功層です。この数字を「micro SaaSの28%は月$100k稼ぐ」と読むのは完全な誤りです。

### 7.4 survivorship biasへの実務的な対処

| 対処 | 具体的な方法 |
|---|---|
| **失敗を能動的に探す** | 競合のpricing pageをWayback CDXにかけると、**サービス終了の告知pageが最終snapshotとして残っている**ことがあります。「この市場で誰が撤退したか」は、成功事例より参入判断に効く情報です |
| **分布で見る、中央値で見ない** | 歪んだ分布では中央値も平均も無意味です。「自分が上位何%に入る必要があるか」で判断してください。3.2節の逆算(月50万円 ≒ ARR $57k)は、Indie Hackersの分布で**上位5%強**に相当します |
| **標本の入口を確認する** | benchmark を見たら必ず「この標本に入るには何が必要だったか」を問う。Stripe連携、tool契約、conference参加、survey回答 — すべてが filter です |
| **公開しない企業を想像する** | Open Startupsに載る企業は「見せられる数字がある」企業です。**同じ市場で公開していない企業のほうが多い**という前提で読んでください |

確信度: **高**(bias の存在と方向は明確。大きさの定量化は困難)

---

## 8. 個人規模での実行手順(この調査の結論を作業に落としたもの)

**原則: 推定を含む手法を後回しにし、観測できる事実から始めてください。**

| 順 | 作業 | 所要 | 出力 | 判断基準 |
|---|---|---|---|---|
| 1 | 競合5〜10社を列挙(検索・marketplace・Form D) | 2〜3h | 競合list | 0社なら2.1節の(a)(b)(c)判定へ |
| 2 | 各社のpricing pageをWayback CDXで時系列化 | 3〜4h | 価格の時系列表 | **値上げ実績が複数社にあるか**(無ければcommodity化を疑う) |
| 3 | 現行価格を同一単位に正規化し、価格帯とladder ratioを算出 | 1〜2h | 価格帯・ladder ratio | entry planの中央値が自分の想定と桁で合うか |
| 4 | marketplace系competitorのinstall数を取得(WordPress API / Chrome) | 1〜2h | 競合規模の桁 | 上位が独占的か、中位に隙間があるか |
| 5 | 競合reviewの★1〜★2を全件収集・分類 | 3〜5h | 不満の分類表 | 「特定業種で使えない」に偏るならniche downが有効 |
| 6 | 3.2節の逆算表を自分の数字で埋める | 30min | **必要月次純増契約数** | **この数が自分の獲得能力を超えていたら、単価設計をやり直す** |
| 7 | 上位10件のSERP実体分類(KD数値は補助) | 2〜3h | channel の可否 | 個人site が3件以上入っているか |
| 8 | 価格は実価格の sequential test で決める(VW/conjointは省略可) | 継続 | 実conversion data | 4週以上、新規訪問者のみ |

**step 6が全体のgateです。**ここで「月8契約の純増が必要」と出て、かつstep 7で有効なchannelが見つからなければ、その企画は**市場調査の段階で止めるべき**です。

---

## 9. 本調査で確認できなかったこと(正直な限界)

| 項目 | 状況 |
|---|---|
| Shopify App Storeにおけるchannel別install内訳 | **公式非公開。**「検索が主」という記述の一次裏付けは取れませんでした |
| Product Hunt launchの定量的成果 | **公式非公開。**検索で出る数値はすべて出典不明のblog由来のため不採用 |
| BLS Business Employment Dynamics Table 7の原data | bls.govがautomated fetchを403で拒否。生存率(1年79% / 5年49% / 10年34%)は検索経由の値であり、確信度 **中** |
| Flippa SaaS multiplesの標本定義 | page が403。件数・期間が確認できず、確信度 **中** |
| Acquire.com報告書の標本件数 | 報告書本文に**記載なし**。倍率3.9xは採用するが、標本サイズ不明の限界あり |
| MicroConf State of Independent SaaS の詳細 | email登録が必要なため、標本数を含む本文未取得 |
| Kyle Poyar の最新PLG benchmark詳細値 | Growth Unhinged が有料購読の壁。2022年OpenView調査(450社超)の枠組みまで |
| Similarweb公式のdata精度documentation | support.similarweb.com が403 |
| 日本市場のmicro SaaS単位経済benchmark | **存在を確認できませんでした。**One Capital "Japan SaaS Insights" は上場SaaS/VC投資対象が中心で、個人規模のbenchmarkは含みません |

---

## 10. 参考文献

### 学術文献(査読あり)

| 文献 | URL |
|---|---|
| Golder, P. N. & Tellis, G. J. (1993) "Pioneer Advantage: Marketing Logic or Marketing Legend?" *Journal of Marketing Research* 30(2) | https://journals.sagepub.com/doi/10.1177/002224379303000203 |
| Min, S., Kalwani, M. U. & Robinson, W. T. (2006) "Market Pioneer and Early Follower Survival Risks..." *Journal of Marketing* 70(1), 15-33 | https://journals.sagepub.com/doi/10.1509/jmkg.70.1.015.qxd |
| VanderWerf, P. A. & Mahon, J. F. (1997) "Meta-Analysis of the Impact of Research Methods on Findings of First-Mover Advantage" *Management Science* 43(11) | https://pubsonline.informs.org/doi/10.1287/mnsc.43.11.1510 |
| Kloss, D. & Kunter, M. (2016) "The Van Westendorp Price-Sensitivity Meter As A Direct Measure Of Willingness-To-Pay" *European Journal of Management* 16, 45-54 | https://www.semanticscholar.org/paper/223af7c3b5e33304313be8e1d570a3049164f872 |
| Burke, A. E., van Stel, A. J. & Thurik, R. "Blue Ocean versus Competitive Strategy: Theory and Evidence" (ERIM / SSRN) | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2024822 |
| "A Critique of Blue Ocean Strategies: Exploring the Limits of Creating Uncontested Markets" *The International Journal of Business & Management* | https://www.internationaljournalcorner.com/index.php/theijbm/article/view/173515 |
| Lieberman, M. & Montgomery, D. "Conundra and Progress: Research on Entry Order and Performance" *Long Range Planning* (2013) | https://marvinlieberman.com/wp-content/uploads/2016/09/Lieberman-Montgomery_LRP2013.pdf |

### 推定tool精度の検証

| 文献 | URL |
|---|---|
| SparkToro (2022) "Which 3rd-Party Traffic Estimate Best Matches Google Analytics?"(641 site / 7,692 site-month) | https://sparktoro.com/blog/which-3rd-party-traffic-estimate-best-matches-google-analytics/ |
| 同上(Medium版) | https://medium.com/@randfish/which-3rd-party-traffic-estimate-best-matches-google-analytics-sparktoro-bfc9d28d86c0 |
| Screaming Frog (2016) "How Accurate Are Website Traffic Estimators?"(25 site / 英国organic) | https://www.screamingfrog.co.uk/blog/how-accurate-are-website-traffic-estimators/ |
| Omniconvert "We analyzed 1,787 ecommerce websites: Similarweb vs Google Analytics"(本文未取得) | https://www.omniconvert.com/blog/we-analyzed-1787-ecommerce-websites-similarweb-google-analytics-thats-we-learned/ |

### 公式documentation / API

| 文献 | URL |
|---|---|
| Internet Archive Wayback CDX Server API(公式) | https://github.com/internetarchive/wayback/tree/master/wayback-cdx-server |
| Ahrefs "Keyword Difficulty"(公式glossary — 計算方法と限界) | https://ahrefs.com/seo/glossary/keyword-difficulty |
| Ahrefs blog "Keyword Difficulty: How to Estimate Your Chances to Rank" | https://ahrefs.com/blog/keyword-difficulty/ |
| Chrome for Developers "Analyze your store listing metrics"(公式) | https://developer.chrome.com/docs/webstore/metrics |
| Shopify Partners "Improving discoverability on the Shopify App Store"(2022-01-07) | https://www.shopify.com/partners/blog/improving-discoverability-on-the-shopify-app-store |
| shopify.dev "About the Shopify App Store" | https://shopify.dev/docs/apps/launch/app-store-review |
| Sawtooth Software "Sample Size Rule of Thumb for a Choice-Based Conjoint (CBC) Study"(公式) | https://sawtoothsoftware.com/resources/blog/posts/sample-size-rules-of-thumb |
| SEC EDGAR full-text search(Form D) | https://www.sec.gov/edgar/search |
| Similarweb "Similarweb's Data Accuracy"(403のため未取得) | https://support.similarweb.com/hc/en-us/articles/360002219177-Similarweb-s-Data-Accuracy |
| wpMetrics "Getting actual installs of WordPress plugin"(逆算手法) | https://wpmetrics.dev/blog/plugin-actual-active-installs |

### benchmark報告書(標本定義つき)

| 文献 | 標本 | URL |
|---|---|---|
| ChartMogul "The SaaS Retention Report: The AI churn wave"(2025) | 約3,500社(B2B 2,700 / B2C 600 / AI-native 200)、ARR $250k以上 | https://chartmogul.com/reports/saas-retention-the-ai-churn-wave/ |
| ChartMogul "The SaaS Retention Report: The New Normal"(2024) | 2,500社超、2021-2024 H1、ARPA分析はARR $300k以上 | https://chartmogul.com/reports/saas-retention-the-new-normal/ |
| ChartMogul "Retention Benchmarks and Insights From Studying Over 2,100 SaaS Businesses" | 2,100社超、2021 vs 2022 | https://chartmogul.com/blog/retention-benchmarks-and-insights/ |
| ChartMogul SaaS Retention Report 2023 (PDF) | — | https://chartmogul.com/reports/saas-retention-report/saas-retention-report-2023.pdf |
| Benchmarkit "2025 SaaS Performance Metrics"(2024年data) | 500社超のB2B(2024年版は約1,000社) | https://www.benchmarkit.ai/2025benchmarks |
| SaaS Capital "2025 Private SaaS Company Valuations"(第13回年次) | private B2B SaaS 1,500社超 | https://www.saas-capital.com/blog-posts/private-saas-company-valuations-multiples/ |
| SaaS Capital "2025 Private B2B SaaS Company Growth Rate Benchmarks" | 同上 | https://www.saas-capital.com/research/private-saas-company-growth-rate-benchmarks/ |
| Acquire.com "Biannual Acquisition Multiples Report (Jan 2026)" | 2025年成約案件、EV $10M未満中心、**件数非開示** | https://blog.acquire.com/acquire-com-biannual-acquisition-multiples-report-jan-2026/ |
| Acquire.com "Biannual Acquisition Multiples Report (Jan 2024)" | 2023年data | https://blog.acquire.com/acquire-biannual-acquisition-multiples-report-2024/ |
| Flippa "SaaS Valuation Multiples"(403のため検索結果経由) | 標本定義不明 | https://flippa.com/blog/saas-multiples/ |
| Lenny's Newsletter / Kyle Poyar / Pendo "What is a good free-to-paid conversion rate" | 1,000製品超の自己申告survey | https://www.lennysnewsletter.com/p/what-is-a-good-free-to-paid-conversion |
| OpenView "2022 Product Benchmarks"(Amplitude共同) | 450社超 | https://openviewpartners.com/2022-product-benchmarks/ |
| Kyle Poyar "Your guide to PLG benchmarks"(Growth Unhinged / 一部有料) | OpenView 2022調査ベース | https://www.growthunhinged.com/p/your-guide-to-plg-benchmarks |
| MicroConf "State of Independent SaaS"(email登録要) | bootstrapped founder、件数非公開 | https://microconf.com/state-of-indie-saas |
| Freemius "AI-Driven, Founder-Led: The 2025 State of Micro-SaaS"(**二次集計・原典の質にばらつきあり**) | 複数調査の集約 | https://freemius.com/blog/state-of-micro-saas-2025/ |

### 収益公開source / survivorship bias

| 文献 | URL |
|---|---|
| Baremetrics Open Startups(公開dashboard一覧) | https://baremetrics.com/open-startups |
| Baremetrics "The Open Startups Initiative" | https://baremetrics.com/blog/open-startups |
| Scraping Fish "How Much Money Do Indie Hackers Products Make?"(937 Stripe verified製品、2022-07-16) | https://scrapingfish.com/blog/indie-hackers-revenue |
| Indie Hackers "I analyzed 5,079 Stripe-verified startups"(user投稿) | https://www.indiehackers.com/post/i-analyzed-5-079-stripe-verified-startups-f0f6bd053f |
| Tyler Tringas "Digging in to the Open Startups List" | https://tylertringas.com/digging-in-to-the-open-startups-list/ |

### 企業生存率(SMB churnの構造的下限)

| 文献 | URL |
|---|---|
| 中小企業庁「2023年版 中小企業白書」第2部第2章第2節 起業・創業(5年後生存率80.7%、帝国データバンク委託調査、白書自身がbiasを注記) | https://www.chusho.meti.go.jp/pamflet/hakusyo/2023/chusho/b2_2_2.html |
| U.S. BLS "1-year survival rates for new business establishments"(The Economics Daily / 403のため未取得) | https://www.bls.gov/opub/ted/2024/1-year-survival-rates-for-new-business-establishments-by-year-and-location.htm |
| U.S. BLS Business Employment Dynamics Table 7(403のため未取得) | https://www.bls.gov/bdm/us_age_naics_55_table7.txt |

### その他(参考・確信度低)

| 文献 | 備考 | URL |
|---|---|---|
| Lightcast Data(求人data、220,000 site集約 / 4億3,500万件超) | vendor公式 | https://lightcast.io/products/data/overview |
| Revelio Public Labor Statistics | vendor公式 | https://www.reveliolabs.com/public-labor-statistics |
| One Capital "Japan SaaS Insights 2025" | 上場SaaS/VC対象中心。個人規模のbenchmarkは含まない | https://onecapital.jp/perspectives/japan-saas-insights-2025 |
| One Capital「SaaS上場企業27社のメトリクス開示状況と業界水準」 | 日本の上場SaaS 27社 | https://onecapital.jp/perspectives/saas-metrics |

---

**除外したsource**: 出典の無いまとめblog、affiliate目的の比較記事、「月収XXX万」式の煽り記事、AI生成と判断されるcontent farm。検索過程で多数出現しましたが、本reportには一切採用していません。特にchurn benchmark・CAC benchmark・Product Hunt統計の領域は、標本定義の無い記事が検索上位を占めており、**その多くが互いを循環引用しています**。数値の一致を根拠と誤認しないようご注意ください。

**全URL確認日: 2026-08-11**
