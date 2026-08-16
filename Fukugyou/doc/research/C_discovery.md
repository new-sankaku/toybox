# C: 一次情報の取り方 — interview・観察・実験

調査担当: research team C
作成日: 2026-08-11
対象読者: 会社員 software engineer（副業で micro SaaS / tool / stock 型 business を立ち上げたい方）

---

## 0. この文書の読み方

### 0.1 確信度の凡例

| 表記 | 意味 |
|---|---|
| 確信度 高 | 査読論文・政府統計・著者本人の一次記述で、数値と出典年を確認済み |
| 確信度 中 | 一次出典は特定できたが、本文の全文確認までは至らず、要約・abstract・検索抽出に依存 |
| 確信度 低 | 業界の通説・vendor 開示 data・単一事例に基づく。方針決定の根拠にはしない |

### 0.2 出典の検証状況について（正直な申し送り）

本調査では PDF 形式の原著論文（Sheeran & Webb 2016、Camuffo et al. 2024、Kohavi の講演資料など）を直接 fetch した際、圧縮 stream のため本文抽出に失敗した case が複数ありました。また ScienceDirect・SSRN・academia.edu・中小企業庁 PDF は 403 で取得できませんでした。

そのため、**論文の書誌情報（著者・年・掲載誌）は確定していますが、一部の数値は検索経由の抽出に依存**しています。該当箇所は確信度「中」を付し、本文中に明示しました。重要な意思決定に使う数値は、原典の当該頁を確認してから使ってください。

### 0.3 本文書の主張の骨格

1. **「買いますか」と尋ねて得た答えは、購買行動をほとんど予測しません。**これは business 書の best practice ではなく、心理学と環境経済学で数十年にわたり定量化されてきた現象です（第2章）。
2. **一方で、「customer interview をこうやれ」という手法論の大半（Mom Test、continuous discovery、JTBD switch interview）は実証されていません。**内部論理は妥当ですが、比較対照試験は存在しません（第1章）。
3. **例外的に実証があるのは「仮説を立てて検証する態度そのもの」です。**Camuffo らの randomized control trial が唯一の強い証拠です（第1.7節）。
4. **個人規模の traffic では A/B test は原理的に回りません。**回らないという事実から逆算した代替設計を第4章に置きました。
5. **副業 engineer にとって最も費用対効果が高い一次情報は、「金銭 commitment を伴う小さな取引」と「自分が当事者である領域の観察」です。**第7章の protocol はこの2点に絞っています。

---

## 1. Customer discovery / interview 手法

### 1.0 手法群の全体地図

| 手法 | 提唱者 | 原典 | 中心的主張 | 実証の有無 |
|---|---|---|---|---|
| Customer Development | Steve Blank | *The Four Steps to the Epiphany*（2005） | 製品開発と並行して顧客開発を4段階で回す | 手法単体の比較試験なし |
| The Mom Test | Rob Fitzpatrick | *The Mom Test*（2013） | 未来の意向でなく過去の行動を聞く | 比較試験なし（原理は第2章の心理学と整合） |
| Continuous Discovery | Teresa Torres | *Continuous Discovery Habits*（2021） | product trio が週次で interview し opportunity solution tree に反映 | 比較試験なし。著者自身が「decision-making research」に言及するが具体的引用なし |
| JTBD switch interview | Bob Moesta / Chris Spiek | *Demand-Side Sales 101*（2020）ほか | 4つの force と timeline で「なぜ乗り換えたか」を再構成 | 比較試験なし |
| Problem Interview | Ash Maurya | *Running Lean*（2010, 2nd ed. 2012） | Lean Canvas の仮説を script 化した interview で反証する | 比較試験なし |
| 科学的 approach（仮説→検証の態度） | Camuffo, Cordova, Gambardella, Spina | Management Science 66(2), 2020 / SMJ 45(6), 2024 | 起業家に「科学者のように」仮説検証させると成果が改善 | **RCT あり（第1.7節）** |

**重要な区別**: 上表の「実証の有無」列が示すとおり、個々の interview 手法に「この聞き方をすると事業成功率が上がる」という比較対照試験は、調査した範囲で**存在しません**。存在するのは(a) 意向と行動が乖離するという心理学・経済学の証拠（第2章）と、(b) 仮説検証という態度全体の RCT（第1.7節）です。手法の細部は、この2つの証拠から逆算された合理的な設計、と位置づけるのが正確です。

---

### 1.1 Steve Blank / Customer Development

**目的**: 「顧客は誰か」「その顧客はどの問題を抱えているか」の仮説を、建物の外で反証すること。

**原典**: Steve Blank, *The Four Steps to the Epiphany*（2005、自費出版）。4段階は Customer Discovery → Customer Validation → Customer Creation → Company Building。著者本人の blog: https://steveblank.com/tag/customer-development/

**中心的主張**: 新規事業の最大の risk は「間違った製品を作ること」ではなく「誰も欲しがらない製品を作ること」である。ゆえに製品開発の前に顧客開発を置く。

**手順**:
1. 仮説を書き出す（顧客 segment、問題、solution、channel、収益）
2. 建物の外に出て、仮説を反証しにいく（"get out of the building"）
3. 仮説が外れたら pivot、当たったら次段階へ

**所要時間**: 段階1だけで数週間〜数ヶ月。副業では現実的に3ヶ月単位。

**何が言えるか**: 「自分が想定していた顧客像・問題設定が、現実と食い違っているかどうか」。

**何が言えないか**: 支払意思、市場規模、獲得 channel の経済性。Customer Discovery は「作るべきか」の判断材料であって「売れるか」の証明ではありません。

**落とし穴**:
- Blank の枠組みは venture capital を前提とした scale を想定しており、micro SaaS には過剰な部分があります（Customer Creation 以降）。副業では段階1〜2のみを取ればよいです。
- 「建物の外に出る」が「知人に聞く」に堕落しやすい。知人は最も biased な標本です。

**確信度**: 高（書誌）／ 手法の有効性については実証なし。

---

### 1.2 The Mom Test（Rob Fitzpatrick）

**目的**: 相手が善意で嘘をつく状況でも、意思決定に使える情報を取ること。

**原典**: Rob Fitzpatrick, *The Mom Test: How to talk to customers and learn if your business is a good idea when everyone is lying to you*（2013、自費出版）。著者 site: https://www.momtestbook.com/

著者本人は同 site で、本書を「practical, not academic」と明言し、理論枠組みを避けて実務課題（biased feedback の回避、返信される email の書き方、購入意思の見極め）に絞ったと述べています。**つまり著者自身が学術的裏付けを主張していません。**これは誠実な自己申告であり、本書を「実証された方法」として扱わないことが正しい読み方です。

**3つの規則**（著者の枠組み）:
1. 自分の idea ではなく、相手の生活について話す
2. 仮定の未来ではなく、具体的な過去の経験を聞く
3. 自分が話すより、相手に話させる

**なぜ効くとされるか**: 「過去の行動は data、未来の意向は fiction」。相手は未来の意向について無意識に嘘をつくが、実際にやったことについては嘘をつきにくい。

**この原理の実証的裏付け**: 手法自体の実証はありませんが、原理の前提（意向は行動を弱くしか予測しない）は第2章のとおり強く実証されています。**原理は実証されている、手法は実証されていない**、という整理が正確です。

**所要時間**: 1件 20〜40分。準備 15分、記録 15分。

**何が言えるか**:
- その問題が実際に発生しているか（発生頻度・直近の発生日時）
- 相手が既に何を試したか、いくら払ったか、どれだけ時間を使ったか
- 相手が「その問題を解くのに既に予算・時間を投じている」かどうか

**何が言えないか**:
- あなたの製品が買われるか。過去に他の物に払ったことは、あなたに払うことを意味しません。
- 価格。過去の支出額は上限の参考にはなりますが、あなたの価格の validation ではありません。
- 市場規模。

**落とし穴**:
- 「あなたの idea どう思いますか」を最後に聞いてしまい、その返答を根拠にする。これで全ての規律が無効化されます。
- 褒め言葉（compliment）を signal と誤認する。褒め言葉は情報量ゼロです。
- 相手が「困っている」と言うのに、その問題のために1円も時間も使っていない場合、それは困りごとではなく不満です。

**確信度**: 高（書誌・著者の主張）／ 有効性の実証なし（著者自身も主張していない）。

---

### 1.3 Teresa Torres / Continuous Discovery

**目的**: discovery を四半期の project ではなく週次の習慣にすること。

**原典**: Teresa Torres, *Continuous Discovery Habits*（2021, Product Talk LLC）。著者 site: https://www.producttalk.org/

**中心的主張**:
- product trio（product manager + designer + engineer）が**最低週1回** customer interview を行う
- 結果を opportunity solution tree（outcome → opportunity → solution → assumption test の4層）に反映する
- interview は story-based で行う（第1.8節に質問例）

**opportunity solution tree の9段階**（著者記事、2023-12-06 更新）: 前提確認 → outcome 定義 → interview から opportunity を map → 対象 opportunity を選択 → solution を brainstorm → 3案に絞る → 前提を洗い出す → 最も risk の高い前提を test → 結果を評価して作る物を決める。

**実証**: 著者は記事中で「decision-making research」に言及しますが、具体的な引用文献を示していません。査読研究による framework の有効性検証は確認できませんでした（確信度 高：「実証が見当たらない」という点について）。

**副業での適用可能性**:
- product trio は組織前提であり、1人副業では成立しません。**取り出せるのは「週次で1件の interview を絶やさない」という cadence と story-based の質問法だけ**です。
- opportunity solution tree は、solution を3案に絞って前提を書き出す部分だけが1人でも機能します。

**所要時間**: 週1件 interview（30分）+ 記録（15分）+ tree 更新（15分）= **週1時間**。副業でも維持可能な水準です。

**何が言えるか**: opportunity（顧客の未充足 needs）の一覧と、その相対的重要度についての継続的な仮説。

**何が言えないか**: どの solution が売れるか。tree の assumption test 層は結局第3章の実験に委ねられます。

**落とし穴**: 「週次で回す」ことが目的化し、聞く相手が同質になっていく（同じ community、同じ知人層）。標本の同質化は継続 interview の最大の敵です。

**確信度**: 高（書誌）／ 有効性の実証なし。

---

### 1.4 Jobs-to-be-Done switch interview（Bob Moesta）

**目的**: 「なぜ人は今の方法を捨てて新しい物に乗り換えたのか」を、購入者本人の記憶から時系列で再構成すること。

**原典**: Bob Moesta（Chris Spiek と共同）, *Demand-Side Sales 101*（2020）。手法解説の一次 source: https://jobstobedone.org/radio/unpacking-the-progress-making-forces-diagram/

**Progress-Making Forces（4つの力）**:

| 力 | 内容 | 方向 |
|---|---|---|
| F1: Push of the current situation | 今のやり方が機能していないという認識（機能面・社会面・感情面） | 推進 |
| F2: Pull of the new solution | 新しい選択肢の magnetism。「良くなった生活の具体像」が必要 | 推進 |
| F3: Anxiety of the new solution | 移行に伴う不安。ここで非消費（non-consumption）が発生する | 抑制 |
| F4: Habit of the present | 今のやり方に紐づいた感情的 energy | 抑制 |

**timeline 法**: 「最初にそれを考えた瞬間」から「購入」「使用」までの出来事を時系列で並べ、timeline を上下しながら質問する。著者は犯罪捜査の聴取技法を応用していると説明しています。

**Moesta の重要な観察**: 「顧客が話すことの約80%は説明的な detail で、価値があるのは残り20%——抵抗を乗り越えて progress を得るために実際に要した energy と労力の部分」。

**手順**:
1. **実際に買った人**を探す（買っていない人には switch interview は成立しません）
2. 購入日から遡って「最初にこれを考えたのはいつですか」を特定
3. その間の出来事を時系列で埋める。検索が止まっていた期間（gap）を必ず掘る
4. F1〜F4 に分類し、どの力が決め手だったかを判定

**所要時間**: 1件 45〜60分。timeline の再構成に時間がかかるため Mom Test より長くなります。

**何が言えるか**:
- 購買の trigger event（何が起きた時に人は探し始めるか）。これは marketing の timing 設計に直結します。
- 移行を止めている anxiety の正体。price 以外の障壁が見えます。

**何が言えないか**:
- 買っていない人がなぜ買わないか（標本が購入者に限定されるため survivorship bias が構造的に入ります）
- 記憶の正確性。timeline は本人の再構成であり、事後合理化が混入します。

**落とし穴**:
- **anxiety を直接聞かないこと。**Moesta 自身が、anxiety を直接質問するのではなく timeline を辿って自然に浮かび上がらせるべきだと述べています。直接聞くと「特に不安はなかった」という無内容な答えが返ります。
- 「買った人」しか対象にできないため、副業初期（まだ製品がない段階）では**競合製品の購入者**に対して行うのが唯一の適用法です。

**確信度**: 高（書誌・著者記述）／ 有効性の実証なし。

---

### 1.5 Ash Maurya / Problem Interview

**目的**: Lean Canvas に書いた顧客・問題仮説を反証すること。

**原典**: Ash Maurya, *Running Lean*（2nd ed., O'Reilly, 2012）第7章 The Problem Interview / 第8章 The Solution Interview。更新版 script: https://blog.leanstack.com/the-updated-problem-interview-script-and-a-new-canvas-1e43ff267a5d（2017-08-17）

**更新版で著者が変更した点**（初版からの自己批判として重要です）:
1. **問題の ranking を廃止** — 主観的で、顧客の自己理解が不十分なため
2. **「誰か」でなく「いつか」を問う** — 人口統計より行動 trigger の方が実用的
3. **trigger と desired outcome で顧客の旅を枠組み化**
4. **既存代替案（existing alternatives）と現在の解法の物語を聴取**
5. **inertia（新しい解に移る際の障害）と friction（使用時の障害）を評価**
6. **"problem" という語自体を interview で使わない** — 裏口から問題を抽出する

**Customer Forces Canvas の4要素**: trigger / desired outcome / existing alternatives / inertia・friction

**所要時間**: 1件 30分。

**何が言えるか**: 顧客が今どうやってその仕事を片付けているか（既存代替案）と、そこに残っている摩擦。

**何が言えないか**: 支払意思。Maurya 自身が problem interview と solution interview を分離しているのは、この2つを混ぜると両方汚染されるからです。

**落とし穴**: Maurya の初版 script（問題を3つ挙げて ranking させる）が今も広く引用されていますが、**著者本人が2017年に撤回しています**。古い要約 blog を参照すると撤回済みの手法を採用してしまいます。

**確信度**: 高（著者本人の記述を直接確認）。

---

### 1.6 手法間の相違点（実務的な使い分け）

| 場面 | 使う手法 |
|---|---|
| まだ何も作っていない。領域だけ決めた | Mom Test + Maurya の trigger / existing alternatives 質問 |
| 競合製品が存在し、その利用者に会える | JTBD switch interview（乗り換えの force を取る） |
| 既に少数の user がいる | Torres の週次 story-based interview |
| 何を作るか2〜3案で迷っている | opportunity solution tree の assumption test 層 → 第3章の実験へ |

---

### 1.7 唯一の強い実証: Camuffo らの randomized control trial

これが本章で**唯一、比較対照試験による裏付けがある**知見です。

**原著1**: Camuffo, A., Cordova, A., Gambardella, A., & Spina, C. (2020). "A Scientific Approach to Entrepreneurial Decision Making: Evidence from a Randomized Control Trial." *Management Science*, 66(2), 564–586.

- **設計**: Italy の startup 116社を treatment / control に無作為割付。両群とも market feedback の取り方について10 session の一般訓練を受講。treatment 群のみ、追加で「仮説を framework 化し、科学者のように厳密に検証する」訓練を受講。約1年間、16時点で data 収集。
- **結果**:
  - treatment 群の方が**成果が良い**
  - treatment 群の方が**別 idea への pivot 確率が高い**
  - 初期段階での**脱落率は control 群と差がない**
  - 機序: 「false positive（見込みのない案を追い続ける）の確率を下げ、false negative（見込みがあるのに捨てる）の確率も下げる」
- **確信度**: 高（書誌・INSEAD による著者側 abstract で確認）。ただし revenue の具体的な差の数値は当該 page に記載がなく、未確認です。

**原著2（大規模 replication）**: Camuffo, A., Gambardella, A., et al. (2024). "A scientific approach to entrepreneurial decision-making: Large-scale replication and extension." *Strategic Management Journal*, 45(6), 1209–1237.

- **設計**: 追加3 RCT（Milan 2017、Turin 2018、London 2019）を含め、計**759社・11,463 data point**を分析。
- **結果**（確信度 中: 検索経由の PDF 抽出に依存、原典頁未確認）:
  - treatment 群は control 群より **6,999.327 euro 多く稼いだ（p = .030）**
  - idea の中止（termination）に正の効果
  - 過激な pivot について**非線形**の効果と整合的。treatment 群は「pivot ゼロ」でも「何度も pivot」でもなく、**少数回の pivot** に集まる
- **著者の解釈**: 科学的 approach は有望な idea 探索の効率を上げ、「自分が立てた筋書き以外の scenario がありうる」という methodic doubt を高める。

**この RCT から副業 engineer が取るべき含意**:
1. 「仮説を明文化して検証する」という態度そのものに効果があります。手法の流派選択より、この態度の有無の方が効きます。
2. **効果の一部は「早く畳む」ことから来ています。**科学的 approach は「当たりを引く確率」だけでなく「外れを早く捨てる確率」を上げます。副業では時間が最大の制約なので、この効果の方が価値が高いです。
3. pivot は「一度もしない」も「繰り返す」も悪く、**少数回が良い**。

**留意点**: 対象は Italy / UK の accelerator 参加 startup であり、日本の1人副業 micro SaaS への外的妥当性は保証されません（確信度 高：この limitation について）。

---

### 1.8 そのまま使える interview 質問集

#### 1.8.1 開始（rapport と context）

```
本日はお時間ありがとうございます。何かを売りに来たのではなく、
〇〇（業務領域）の実務がどうなっているかを教えていただきたく伺いました。
私の説明は最小限にします。私が9割聞く形にさせてください。
録音してもよろしいでしょうか（記録用で、外には出しません）。
```

#### 1.8.2 過去の行動を取る質問（Mom Test / Torres の story-based）

英語圏の原型（Torres の例、producttalk.org）:
- "Tell me about the last time you [did X]."
- "Tell me about the last time you had to choose a new [tool/vendor]."

日本語での実用形:
```
・直近で〇〇をやったのはいつですか。その日のことを最初から順に教えてください。
・そのとき、最初に何をしましたか。次に何をしましたか。
・それは何時から何時までかかりましたか。
・その作業は月に何回発生しますか。直近3ヶ月で何回でしたか。
・その作業、他の人がやることもありますか。誰がやりますか。
・うまくいかなかったのは具体的にどの手順ですか。
・そのとき、どうやって回避しましたか。
・その回避策は今も使っていますか。使っていないなら、なぜやめましたか。
```

#### 1.8.3 既存代替案と投下 cost を取る質問（Maurya）

```
・今それをやるのに、どんな道具や仕組みを使っていますか。
・それはいつ、どういうきっかけで導入しましたか。
・導入前は何を使っていましたか。なぜ乗り換えましたか。
・その道具にいくら払っていますか（月額・年額・買い切り）。
・自作した仕組みはありますか。作るのに何時間かかりましたか。
・その仕組みのMaintenanceは誰がやっていますか。
・去年、この領域で何かにお金を使いましたか。何にいくらですか。
```

**判定基準**: 上記で「金額」「時間」「自作物」のいずれも出てこない場合、その問題は**顧客にとって解く価値がない**と判定してください。不満の表明と、資源を投じている problem は別物です。

#### 1.8.4 trigger を取る質問（Maurya / Moesta）

```
・その道具を探し始めたきっかけは何ですか。その日に何が起きましたか。
・それより前にも同じ不便はありましたよね。なぜその日だったのですか。
・探し始めてから決めるまで、どれくらいかかりましたか。
・途中で探すのをやめていた期間はありますか。なぜ止まりましたか。何で再開しましたか。
・最終的に決めたのは誰ですか。あなた1人で決められましたか。
```

最後の「決裁者は誰か」は B2B では必ず聞いてください。日本の中小企業 B2B では、担当者が乗り気でも決裁が通らない case が多く、担当者の熱意は購買を予測しません。

#### 1.8.5 anxiety / inertia を間接的に取る質問（Moesta）

anxiety は直接聞かず、以下で迂回します。

```
・導入を決めてから実際に使い始めるまで、何日かかりましたか。何をしていましたか。
・社内で反対や懸念はありましたか。誰が、何を言いましたか。
・検討したが選ばなかった選択肢はありますか。なぜ落としましたか。
・今の道具をやめるとしたら、一番面倒なのは何ですか。
・（過去に導入を見送った case について）そのとき、代わりに何をしましたか。
```

#### 1.8.6 絶対に聞いてはいけない質問

| 禁止質問 | 理由 |
|---|---|
| 「こういう tool があったら使いますか」 | 未来の意向。第2章のとおり行動を予測しません |
| 「いくらなら買いますか」 | hypothetical bias が直撃します。第2.5節 |
| 「この idea どう思いますか」 | 社交辞令しか返りません |
| 「〇〇で困っていませんか」 | 誘導。相手は「はい」と言うのが親切だと思います |
| 「月○円は高いですか、安いですか」 | 相対比較の frame を与えており、回答が anchor に汚染されます |

#### 1.8.7 interview の終わり方（次に繋げる）

```
・同じような業務をされている方で、話を聞かせていただけそうな方はいらっしゃいますか。
・もし試作品ができたら、10分だけ見ていただくことは可能でしょうか。
・（可能なら）この作業をやっている画面を、後日 15分だけ見せていただけませんか。
```

3番目が最も価値が高い質問です。**語りより観察の方が正確**です（自己申告の作業時間は体系的に歪みます）。

#### 1.8.8 interview 件数の目安

**根拠**: Guest, G., Bunce, A., & Johnson, L. (2006). "How Many Interviews Are Enough? An Experiment with Data Saturation and Variability." *Field Methods*, 18(1), 59–82.

- 西 Africa 2カ国での60件の in-depth interview を用い、theme の飽和を系統的に記録
- **最初の12件で飽和に達した**
- metatheme の基本要素は**6件の時点で既に出現**していた
- 確信度: 高（書誌・主要結果）。ただし**同質な母集団に対する**知見であり、顧客 segment が複数ある場合は segment ごとに必要です。

**副業での実用値**:
- 1つの顧客 segment・1つの業務領域につき **12件**を目標
- **6件**の時点で一度立ち止まり、それまでの発見を書き出す（ここで既に大勢は見えます）
- segment が2つあるなら 12 × 2 = 24件必要。segment を増やすと線形に costs が増えるため、**副業では segment を1つに絞る**判断が合理的です

---

## 2. 意向と行動の乖離

本章が本文書で最も証拠が強い部分です。**「買いますか」と聞いて得た答えを根拠に開発を始めてはいけない**理由の定量的な裏付けです。

### 2.1 intention は behavior を r ≈ .53 でしか予測しない

**原著**: Sheeran, P. (2002). "Intention—Behavior Relations: A Conceptual and Empirical Review." *European Review of Social Psychology*, 12(1), 1–36.

- 10件の meta-analysis（**422 研究・82,107名**）を統合
- **intention は behavior の分散の 28% しか説明しない（r = .53）**
- 確信度: 中（書誌は確定、数値は検索経由抽出）

**含意**: 意向が行動を「まったく」予測しないわけではありません。r = .53 は社会科学では強い部類です。問題は残り72%です。survey で得た購入意向を、実購入の代理変数として**そのまま**使うと、大きく外します。

### 2.2 意向を持った人の 47% が実行しない（inclined abstainers）

**原著**: Orbell, S., & Sheeran, P. (1998)。Sheeran, P., & Webb, T. L. (2016). "The Intention–Behavior Gap." *Social and Personality Psychology Compass*, 10(9), 503–518 に整理されています。

- 運動・condom 使用・癌 screening の研究群を横断
- **positive intention を持ちながら行動しなかった人の中央値は 47%**
- **negative intention なのに行動した人は 7%**
- つまり gap の主因は「やる気があるのにやらない人」であり、「やる気がないのにやる人」ではない
- 確信度: 中（書誌は確定、数値は検索経由抽出）

**含意（極めて実務的）**:
- 「使ってみたい」と言った10人のうち、**約5人は何もしません**。これが baseline です。
- 逆に「興味ない」と言った人が後で買う確率は 7% 程度で、**否定的な回答の方が予測力が高い**。
- **waiting list への登録者数を根拠に開発量を決めると、約半分の過大評価になります。**

### 2.3 意向を「動かして」も行動は半分しか動かない

**原著**: Webb, T. L., & Sheeran, P. (2006). "Does changing behavioral intentions engender behavior change? A meta-analysis of the experimental evidence." *Psychological Bulletin*, 132(2), 249–268.

- **47件の実験**を統合
- 中〜大の intention 変化（**d = 0.66**）が引き起こす behavior 変化は小〜中（**d = 0.36**）にとどまる
- 確信度: 中（書誌は確定、数値は検索経由抽出）

**含意**: landing page の copy を改善して「欲しい」度合いを上げても、実際の購買はその**約半分**しか動きません。意向 metric（アンケートの「興味あり」）を KPI にすると、改善効果を約2倍に見積もることになります。

### 2.4 purchase intention が sales を予測する条件

**原著**: Morwitz, V. G., Steckel, J. H., & Gupta, A. (2007). "When do purchase intentions predict sales?" *International Journal of Forecasting*, 23(3), 347–364.

- 購入意向と実購買の相関の強さは、**製品の種類**と **data 収集方法**によって変動する
- 確信度: 中（書誌は確定。moderator の具体的な効果量は原典 403 のため未確認）

**確認できた範囲での実務的整理**（確信度 低〜中、上記論文の一般的な引用のされ方に基づく。原典で検証してから使ってください）:
- **既存製品** > 新製品: 既存 category の方が予測が当たる
- **耐久財** > 非耐久財
- 予測 horizon が**短い**ほど当たる

**micro SaaS への含意**: 副業が狙うのはたいてい「新 category に見える tool」であり、これは purchase intention の予測力が**最も低い**条件です。ゆえに survey ではなく実取引で測る必要があります。

### 2.5 hypothetical bias: 仮想の支払額は実支払額の何倍か

**原著1**: List, J. A., & Gallet, C. A. (2001). "What Experimental Protocol Influence Disparities Between Actual and Hypothetical Stated Values?" *Environmental and Resource Economics*, 20(3), 241–254.

**原著2**: Murphy, J. J., Allen, P. G., Stevens, T. H., & Weatherhead, D. (2005). "A Meta-analysis of Hypothetical Bias in Stated Preference Valuation." *Environmental and Resource Economics*, 30(3), 313–325.

- **28件の stated preference 研究**から **83 observation**
- 同一の elicitation 機構で仮想値と実値の両方を測った研究に限定
- **仮想 WTP / 実 WTP の中央値 = 1.35**
- 分布は強い正の歪度（右裾が長い）を持つ
- 「人は経済的評価を2〜3倍に誇張する」という通説より、**適切な統制下では bias は小さい**
- **choice-based の elicitation 機構が bias 低減に重要**
- 確信度: 中（書誌は確定、数値は検索経由抽出。原典 PDF は本文抽出に失敗）

**注意すべき2点**:
1. 中央値 1.35 は「同一機構で比較した統制の効いた研究」の値です。統制のない実務 survey ではこれより大きいと考えるべきです（Murphy らは他 meta-analysis で 25%〜300% の範囲が報告されているとも記述）。
2. **分布が強く右に歪んでいる**ため、平均で語ると誤ります。「たいていは1.35倍だが、時々とんでもなく外れる」という性質です。単発の survey 結果に賭けてはいけない理由がここにあります。

### 2.6 social desirability bias

**原著**: Fisher, R. J. (1993). "Social Desirability Bias and the Validity of Indirect Questioning." *Journal of Consumer Research*, 20(2), 303–315.

- social desirability bias = 回答者が「気まずさを避け、好ましい印象を与えたい」という動機から生じる、自己申告 measure の系統誤差
- 3つの研究で、**間接（構造化投影法）質問**が bias を減らすことを検証
- 確信度: 高（書誌・要旨）

**副業 interview での現れ方**:
- 相手はあなたを傷つけたくないので「面白いですね」と言います
- 相手は「無駄な作業に月10時間使っている」と認めたくないので過少申告します
- 相手は「ITに疎い」と思われたくないので、実際より使いこなしているように話します

### 2.7 補正手法

#### (a) cheap talk script

**原著**: Cummings, R. G., & Taylor, L. O. (1999). "Unbiased Value Estimates for Environmental Goods: A Cheap Talk Design for the Contingent Valuation Method." *American Economic Review*, 89(3), 649–665.

- 8段落の script で「hypothetical bias とは何か」を回答者に説明し、それを避けるよう明示的に依頼する
- 学生を対象とした lab 実験で、複数の公共財について**hypothetical bias を消去**
- **ただし後続研究では結果が混在**しており、Cummings & Taylor の原 script の頑健性は確立していません
- 確信度: 中（原論文の結果は確定的だが、再現性については混在という点も含めて）

**副業での使える形**（interview の価格質問の直前に置く script）:
```
これから金額の話をお伺いしますが、一点だけ先にお伝えします。
こういう場面では、実際に自分のお金を出す時よりも高い金額を答えてしまう
傾向があることが知られています。悪気があるわけではなく、
仮の話だと財布の痛みが想像しにくいためです。
ですので恐縮ですが、「実際に今月の予算から出すとしたら」という前提で
お答えいただけますか。
```

#### (b) inferred valuation

**原著**: Lusk, J. L., & Norwood, F. B. "An Inferred Valuation Method." および Norwood, F. B., & Lusk, J. L. (2011). "Social Desirability Bias in Real, Hypothetical, and Inferred Valuation Experiments." *American Journal of Agricultural Economics*. 応用: Entem et al. (2022), *American Journal of Agricultural Economics*, 104(4), 1224–1242.

- 自分の価値ではなく、**他者の価値を推測させる**
- 社会的期待を意識させずに済むため social desirability bias が下がる
- 規範性が高い財（環境・倫理など）では特に有効
- 確信度: 中（書誌確定、効果量は未確認）

**副業での使える形**:
```
・あなたと同じ職種の方が、この tool に月いくらまで払うと思いますか。
・あなたの会社で、この種の tool の稟議が通る金額の上限はいくらぐらいですか。
・同僚の方は、この作業に週何時間ぐらい使っていると思いますか。
```

自分のことを聞くより正直な数字が出ます。ただし**推測値であって実測ではない**ので、価格決定の根拠ではなく仮説生成に使ってください。

#### (c) certainty follow-up

hypothetical bias 研究で広く使われる方法です。意向を答えさせた後に確信度を10段階で聞き、**確信度が閾値（多くの研究で8以上）未満の「はい」を「いいえ」に変換**します。

```
・（「使いたい」の後で）その気持ちは10段階でいくつですか。
  10が「今すぐ支払い情報を入力する」、1が「話としては面白い」です。
```

8未満は「いいえ」として集計してください。

#### (d) 最も確実な補正: 意向を聞かない

上記の補正手法はいずれも bias を**減らす**だけです。**bias をゼロにする唯一の方法は、意向ではなく行動を測ることです**（第3章）。副業では補正 script に労力を使うより、小さくても実際の取引を1件作る方が費用対効果が高いです。

### 2.8 本章のまとめ表

| 測定対象 | 実購買との関係 | 出典 |
|---|---|---|
| 一般的な intention | r = .53（分散の28%） | Sheeran 2002 |
| positive intention 保持者の実行率 | 約53%（47%が不実行） | Orbell & Sheeran 1998 |
| intention を実験的に上げた場合の行動変化 | 意向の変化 d=.66 → 行動 d=.36 | Webb & Sheeran 2006 |
| 仮想 WTP / 実 WTP | 中央値 1.35倍（右に強く歪む） | Murphy et al. 2005 |
| 新 category 製品の purchase intention | 予測力は最低水準 | Morwitz et al. 2007 |

---

## 3. 実験による検証

各手法を「目的 / 手順 / 所要時間 / 何が言える / 何が言えない / 落とし穴」の型で記述します。

### 3.0 実験の証拠強度の階層

弱い方から:

```
survey の「買いますか」        ← 第2章のとおり、ほぼ無価値
  ↓
email 登録（無料、1 click）    ← 意向の一種。約半分は動かない
  ↓
無料 trial への sign-up + 実利用  ← 行動だが支払意思ではない
  ↓
fake door click                ← 意向と行動の中間。文脈依存が強い
  ↓
LOI（署名付き購入意向書）       ← B2B では有効。法的拘束はない
  ↓
実際の決済（pre-sale / 有料 trial）  ← 最も強い
  ↓
継続課金（2ヶ月目の決済）        ← stock 型 business では唯一の真の証拠
```

**副業 micro SaaS では最下段の「2ヶ月目の決済」が到達目標です。**stock 型 business の経済性は継続率で決まるので、初回決済だけでは何も証明されていません。

---

### 3.1 Landing page test / smoke test

**目的**: 製品を作る前に、価値提案に対する行動反応（click・登録・決済）を測ること。

**手順**:
1. 価値提案を1文で書いた page を作る（機能一覧ではなく、解決する仕事を書く）
2. 明確な行動要求（call to action）を1つだけ置く
3. 有料 traffic（検索広告・SNS広告）か、既存 community からの誘導で流入を作る
4. 流入元ごとに conversion を分けて記録する

**所要時間**: page 作成 4〜8時間、traffic 獲得 2〜4週間、費用 数万円（広告費）。

**基準となる数値**: Unbounce Conversion Benchmark Report（41,000 landing page・4億6,400万訪問・5,700万 conversion action を集計、Q4 2024 data）によると:
- 全業種の中央値 conversion rate: **6.6%**
- **SaaS の中央値: 3.8%**（全業種比 42% 低い）
- SaaS の上位25%に入るには **11.6% 以上**
- 確信度: 中（vendor による集計だが、母数と手法を開示しており、業界横断の baseline としては使えます）

**何が言えるか**:
- 「この価値提案の文面は、この traffic 源からの訪問者の何%に click させるか」——ただそれだけです。
- 複数の価値提案を比較した場合の**相対**順位（sample size が足りていれば）

**何が言えないか**:
- **売れるかどうか**。無料登録の conversion と有料 conversion は別 metric です。第2.2節のとおり、登録者の約半分は何もしません。
- 価格の妥当性
- 継続率
- traffic 源を変えた時の一般化。検索広告で来た人と Reddit から来た人は別の母集団です。

**落とし穴**:
- **広告 copy と landing page copy を同時に変えると、何を測ったのか分からなくなります。**必ず片方を固定してください。
- 「知人に URL を送って反応を見る」は無価値です。標本が完全に汚染されています。
- SaaS の中央値 3.8% を「うちは 8% だから有望」と読むのは誤りです。母集団が違えば比較不能です。同じ page で価値提案だけ変えた**内部比較**にのみ意味があります。
- 訪問者数が少ない段階で「conversion 5%」と言っても、後述のとおり信頼区間が極めて広く、実質的に何も言えていません（第4.2節）。

**確信度**: 手法の存在と手順は 高。有効性（landing page conversion が実売上を予測するか）については、**査読研究を発見できませんでした（確信度 高：「実証が見当たらない」という点）**。これは landing page test を否定するものではありませんが、「業界の慣行であって実証された予測子ではない」と理解してください。

---

### 3.2 Fake door test（painted door test）

**目的**: 存在しない機能・製品への需要を、実際の click 行動で測ること。

**手順**:
1. 既存の page / app に、あたかも存在する機能のように entry point（button・link・menu）を置く
2. click した user に「準備中です」と開示し、通知登録の選択肢を出す
3. click 率を測る

**所要時間**: 実装 2〜4時間。観測期間は traffic 次第（第4章）。

**何が言えるか**:
- 既存 user 群における、その機能への**相対的な関心度**。複数の fake door を並べれば優先順位の材料になります。

**何が言えないか**:
- **支払意思**。click は無料です。
- **絶対的な需要量**。「10%が click した」は「10%が使う」でも「10%が払う」でもありません。
- **新規 user の需要**。既存 user は既にあなたの製品を選んだ人であり、母集団が偏っています。

**落とし穴**:
- **novelty effect**: 新しい button は、それが何であれ最初は click されます。観測期間を短くすると新規性を需要と誤認します。
- 同じ user に何度も fake door を見せると、click しなくなります（学習）。
- 導線上の位置で click 率は数倍変わります。位置を固定しない限り、機能間の比較は成立しません。

#### 3.2.1 倫理と法的境界（重要）

**まず事実確認**: 「fake door test で企業が炎上し謝罪した」という**具体的な documented 事例は、今回の調査では発見できませんでした**（確信度 高：「見つからなかった」という点について）。fake door への倫理的批判は、実務家の議論としては広く存在しますが、名前のついた大規模な backlash 事例に裏付けられてはいません。この点は正直に申し送ります。

**一方、user への無同意実験に対する documented な controversy は2件あります**:

1. **Facebook emotional contagion 実験（2014）**
   Kramer, A. D. I., Guillory, J. E., & Hancock, J. T. (2014). "Experimental evidence of massive-scale emotional contagion through social networks." *PNAS*, 111(24), 8788–8790.
   - 689,003名の news feed を無作為に positive / negative に操作
   - PNAS が同誌 2014年6月17日号で **Editorial Expression of Concern** を掲載（informed consent と opt-out の機会について疑義）
   - 著者側は「Facebook の Data Use Policy への同意が informed consent に相当する」と主張したが、研究倫理の基準との乖離が問題視された
   - 確信度: 高（PNAS 本体の Editorial Expression of Concern を確認）

2. **OkCupid の compatibility 操作実験（2014）**
   - 共同創業者 Christian Rudder が "We Experiment On Human Beings" と題した blog 記事で、実際には30%一致の pair に90%一致と表示する実験を行ったと公表
   - Rudder は「internet を使えば常に数百の実験の被験者だ。site とはそういうものだ」と述べ、informed consent の概念自体を退けた
   - 報道による強い批判を受けた
   - 確信度: 高（複数の一次報道で確認: Forbes 2014-07-28 ほか）

**両者から取れる境界線**:
- **開示の欠如**そのものより、「user が自分について持っている真実の情報を偽った」ことが批判の中心でした（OkCupid は互換性スコアを偽り、Facebook は感情状態を操作した）。
- fake door はこれに比べると軽度です。**未実装であることを click 直後に開示する限り**、user 自身に関する情報を偽ってはいません。

#### 3.2.2 日本の法規制（実務上、こちらの方が重要です）

**景品表示法 第5条第3号に基づく「おとり広告に関する表示」（平成5年公正取引委員会告示第17号）**

規制される4類型（消費者庁）:
1. 取引の申出に係る商品・サービスについて、**取引を行うための準備がなされていない場合**のその商品・サービスについての表示
2. 供給量が著しく限定されているのに、その限定内容が明瞭に記載されていない場合
3. 供給期間・供給の相手方・顧客1人当たりの供給量が限定されているのに、その限定内容が明瞭に記載されていない場合
4. 合理的理由がないのに取引の成立を妨げる行為が行われる場合、**その他実際には取引する意思がない場合**

違反と認められた場合、消費者庁長官が措置命令等を行います。

出典: https://www.caa.go.jp/policies/policy/representation/fair_labeling/representation_regulation/case_002
運用基準: https://www.caa.go.jp/policies/policy/representation/fair_labeling/guideline/pdf/100121premiums_31.pdf
確信度: 高（消費者庁の公式 page を直接確認）

**副業 micro SaaS への実務的含意**:

| 実装 | 法的 risk |
|---|---|
| 「近日公開」と明記した機能予告への通知登録 | 低い。取引の申出ではありません |
| 価格を表示し「購入」button を置くが、押すと「準備中」 | **類型1・4に該当する risk があります**。取引の申出をしているのに準備がなく、取引する意思もありません |
| 価格を表示し決済まで通す（pre-sale）。提供時期を明記し、遅延時は返金 | 適法な pre-sale。ただし特定商取引法の通信販売表示義務（返品条件・提供時期等）を満たす必要があります |

**推奨する運用**:
1. 価格と購入 button を出す fake door は**避けてください**。
2. どうしても価格反応を測りたいなら、**実際に決済を通す pre-sale にして、提供できなければ全額返金する**。これは適法であり、かつ第3.0節のとおり証拠として遥かに強いです。
3. 「準備中」の開示は click **直後**に、明確な文言で行ってください。

---

### 3.3 Pre-sale（事前販売）

**目的**: 実際の決済という、最も強い需要 signal を得ること。

**手順**:
1. 提供内容・提供予定時期・返金条件を明記する
2. 決済を実際に通す（Stripe 等）
3. 提供できなかった場合は全額返金する（この約束を先に明記する）
4. 決済率と、決済者からの追加要望を記録する

**所要時間**: 決済導線の実装 4〜8時間。

**何が言えるか**:
- **その価格でその価値提案に金を出す人が実在する**こと。第2章の bias が原理的に入りません。
- 顧客が「今すぐ欲しい」水準で困っているかどうか。

**何が言えないか**:
- **継続するか**。pre-sale は初回決済であり、stock 型 business の本命である継続率を何も証明しません。
- 規模。10件売れたことは1,000件売れることを意味しません。

**参考: crowdfunding という大規模 pre-sale の実態**

Mollick, E. (2015). "Delivery Rates on Kickstarter."（Kickstarter 委託調査、backer 47,188名の survey）
- 資金調達に成功した project のうち、**報酬を提供できなかった割合は約9%（range 5〜14%）**
- 小規模 project（および程度は劣るが極大規模 project）ほど不履行が多い
- 確信度: 中（書誌確定、数値は検索経由抽出。Kickstarter の fulfillment page は 403 で未確認）

別の分析（Kickstarter project の fulfillment rate 研究）では、**予定通りまたは6ヶ月未満の遅延で提供されたのは約30%**、**75%超が予定より遅れて提供**という報告もあります（確信度 低：複数の研究で定義が異なり、数値に大きな幅があります）。

**副業への含意**: pre-sale で金を受け取ったら、それは負債です。**平日夜と週末しか使えない条件で提供期限を約束するのは危険**です。提供時期は「見込みの2倍」で告知し、返金条件を先に明記してください。

**落とし穴**:
- 決済を受け取った瞬間に、pivot の自由を失います。pre-sale は「検証」であると同時に「拘束」です。
- 知人からの購入は data として無効です。区別して記録してください。
- 極端に少額（数百円）にすると、決済の signal 価値が落ちます。**実際に想定する価格で売ってください。**

---

### 3.4 Concierge MVP

**目的**: 自動化を作る前に、同じ価値を人手で提供し、価値提案が成立するか確かめること。

**原典**: Eric Ries, *The Lean Startup*（2011）で紹介された Food on the Table の事例。創業者 Manuel Rosso が顧客1人ひとりの献立を手作業で作り、顧客が買い物する grocery store の駐車場の Starbucks で週1回対面していた。顧客は手作業のサービスと知った上で支払っていた。

**手順**:
1. 顧客に「今は手作業で提供します」と**明示した上で**、対価を取る
2. 自分が顧客の作業を代行し、その過程を記録する
3. 手順のうち、時間を食っている部分・判断が必要な部分を特定する
4. その部分だけを自動化する

**所要時間**: 顧客1人あたり週2〜4時間。副業では**同時に3人が上限**です。

**何が言えるか**:
- 価値提案そのものが成立するか（顧客が対価を払う価値があるか）
- **自動化すべき箇所はどこか**。これが concierge の最大の価値です。想定と実際は必ずずれます。
- 顧客の実作業の詳細（interview では絶対に取れない粒度）

**何が言えないか**:
- **scale した時に同じ価値が出るか**。人手で提供している価値の一部は「人が対応してくれること」自体であり、自動化すると消えます。この混同が concierge の最大の失敗要因です。
- 単位経済性。人手の costs は自動化後の costs と無関係です。

**落とし穴**:
- 顧客に人手であることを隠すと Wizard of Oz になり、性質が変わります（第3.5節）。**concierge は開示が前提**です。
- 副業では、顧客が増えると自分の時間が線形に食われます。**concierge を続けたまま自動化する時間が取れなくなる**のが典型的な失敗です。開始時に「3人まで・8週間まで」と上限を決めてください。
- 顧客が「あなた」を買っている場合、製品化しても顧客は移行しません。

**確信度**: 高（事例の存在と手順）／ 有効性の実証なし（単一事例）。

---

### 3.5 Wizard of Oz

**目的**: 自動化されているように見せかけ、裏で人が処理することで、「完成した製品に対する user の反応」を実装前に測ること。

**原典**: Kelley, J. F. (1983). "An empirical methodology for writing user-friendly natural language computer applications." *Proc. ACM SIGCHI '83*, pp. 193–196. および Kelley, J. F. (1984). "An iterative design methodology for user-friendly natural language office information applications." *ACM Transactions on Office Information Systems*, 2(1), 26–41.

- Kelley が自然言語で操作する calendar application（CAL: Calendar Access Language）を、裏で実験者が処理する形で模擬したのが名称の由来
- 6回の反復で、実 user の誤解と期待に対処しながら usability を改善した
- 確信度: 高（書誌・手法の由来）

**concierge との決定的な違い**: **concierge は人手であることを開示し、Wizard of Oz は開示しません。**この差が倫理的・法的な性質を変えます。

**手順**:
1. 完成品の interface だけを作る
2. 裏側で人（自分）が入力を処理し、自動処理を装って返す
3. user の操作 log と、処理に要した実作業を記録する

**所要時間**: interface 実装 8〜16時間。運用は要求1件あたり数分〜数十分。

**何が言えるか**:
- 「もし自動化が完璧に動いたら、user はどう使うか」。**実装前に interaction design を検証できる**のが本質的価値です。
- 自動化の難所（人でも判断に迷う入力）の同定

**何が言えないか**:
- 技術的実現可能性。人ができることを機械ができるとは限りません（AI 領域では特にこの誤りが多発します）。
- 応答時間を含めた体験。人手では遅く、自動化すると速くなるため、体験が変わります。

**落とし穴**:
- **これは欺瞞です。**user は自動処理だと信じています。日本では、有料 service でこれを行うと、提供内容の表示と実態の乖離として景品表示法上の問題を生じうるほか、user の data を人が閲覧することの privacy 上の問題があります。
- **推奨する運用**: 副業では **Wizard of Oz を有料 service に使わないでください。**代わりに (a) 無償の user test 参加者に対して事前に「一部を人が処理する場合があります」と包括的に同意を取る、または (b) concierge（完全開示）に倒す。第3.4節の Food on the Table が示すとおり、開示しても顧客は払います。
- 個人 data を扱う場合、人が閲覧することを開示せずに扱うのは個人情報保護法上の risk があります（確信度 中：具体的な適法性は事案によります）。

---

### 3.6 5手法の比較表

| 手法 | 実装 costs | 証明できるもの | 証明できないもの | 倫理・法的 risk |
|---|---|---|---|---|
| Landing page / smoke test | 低 | 価値提案 copy への click 反応 | 支払意思・継続 | ほぼ無し |
| Fake door | 低 | 既存 user の相対的関心 | 支払意思・絶対需要 | **中**（価格表示すると景表法 risk） |
| Pre-sale | 中 | **支払意思（最強）** | 継続率・規模 | 低（提供義務は発生） |
| Concierge MVP | 高（時間） | 価値の成立・自動化箇所 | scale 時の価値・単位経済性 | 低（開示前提） |
| Wizard of Oz | 中 | interaction design | 技術的実現性 | **高**（欺瞞を含む） |

**副業 engineer への推奨順序**: concierge（3人まで） → pre-sale → landing page。fake door と Wizard of Oz は、既存 user がいる段階まで使わないでください。

---

## 4. 実験設計の作法

### 4.1 必要 sample size の具体的計算

2群比率の比較、両側 α = 0.05、検出力 80% の場合:

```
n（各群） ≈ (z_{α/2} + z_β)² × [p₁(1-p₁) + p₂(1-p₂)] / (p₂ - p₁)²
         = 7.849 × [p₁(1-p₁) + p₂(1-p₂)] / (p₂ - p₁)²
```

**baseline を SaaS landing page の中央値 3.8%（Unbounce 2024）として計算した実数**:

| 検出したい改善 | 改善後 rate | 各群の必要 click 数 | 合計必要 click 数 |
|---|---|---|---|
| 相対 +25%（3.8% → 4.75%） | 4.75% | **7,113** | **約14,200** |
| 相対 +50%（3.8% → 5.7%） | 5.7% | **1,963** | **約3,930** |
| 相対 +100%（3.8% → 7.6%） | 7.6% | **580** | **約1,160** |

（本表は上式による筆者の計算です。確信度 高：計算自体。baseline の 3.8% は Unbounce 集計に依存）

**簡便式**: 連続量の場合、α=0.05・power 80% では 2(z_{α/2}+z_β)² ≈ 16 となるため

```
n ≈ 16σ² / δ²
```

δ が squared で分母に入るため、**検出したい効果が半分になると必要 sample は4倍**になります。

### 4.2 A/B test 以前の問題: 単一 rate の推定精度

多くの副業者は A/B test 以前に、**「うちの conversion は何%か」すら精度よく言えていません。**

真の conversion が 4% のとき、95% 信頼区間の半幅:

| 訪問者数 | ±（95% CI 半幅） | 区間 |
|---|---|---|
| 200 | ±2.7% | 1.3% 〜 6.7% |
| 400 | ±1.9% | 2.1% 〜 5.9% |
| 1,000 | ±1.2% | 2.8% 〜 5.2% |
| 4,000 | ±0.6% | 3.4% 〜 4.6% |

400訪問での「conversion 4%」は、実質「2%かもしれないし6%かもしれない」という意味です。この精度で価格や事業性を判断してはいけません。

### 4.3 個人規模でも成立する統計: rule of three（否定の証明）

**個人規模 traffic でも確実に得られる結論があります。それは「上限」です。**

n 回の試行で conversion がゼロだったとき、真の rate の 95% 上限は近似的に **3/n** です（rule of three）。

| 訪問者数 | 0件だった場合の 95% 上限 |
|---|---|
| 100 | 3% 以下 |
| 200 | 1.5% 以下 |
| 300 | 1.0% 以下 |
| 1,000 | 0.3% 以下 |

**これは副業にとって極めて実用的です。**「300人来て1件も申し込みがなかった」は、「conversion は1%未満である」という統計的に堅い結論です。事業を畳む判断には十分な精度で、しかも300訪問なら現実的に到達できます。

**逆に、肯定の証明（「conversion は5%ある」）には桁違いの sample が要ります。**副業の実験設計は、**「肯定を証明する」ではなく「否定を早く確定させる」**方向に倒すべきです。これは第1.7節の Camuffo RCT の含意（効果の一部は早期撤退から来る）とも一致します。

同様に、**conversion 4% のとき、少なくとも1件の conversion を95%の確率で観測するには74訪問必要**です（ln(0.05)/ln(0.96) ≈ 73.4）。「50人来たけど誰も申し込まない」は、まだ何の情報でもありません。

### 4.4 p-hacking

**原著**: Simmons, J. P., Nelson, L. D., & Simonsohn, U. (2011). "False-Positive Psychology: Undisclosed Flexibility in Data Collection and Analysis Allows Presenting Anything as Significant." *Psychological Science*, 22(11), 1359–1366.

- data 収集・分析・報告の柔軟性が偽陽性率を劇的に押し上げる
- 「多くの場合、研究者は効果が存在しないことを正しく見出すより、存在しない効果を誤って見出す方が起こりやすい」
- 計算機 simulation と実験2件で、偽の仮説に対して有意な証拠を蓄積することがいかに容易かを示した
- 確信度: 高（書誌・主要主張）

**個人の実験で発生する p-hacking の典型形**:

| 行為 | 何が起きるか |
|---|---|
| 有意になるまで data を取り続ける（optional stopping） | 偽陽性率が 5% から 20%超に跳ね上がります。最も頻発する形です |
| 複数の metric を測り、良かったものを報告する | metric が k 個あれば偽陽性率は約 1-(0.95)^k |
| 事後的に segment を切る（「mobile では効いていた」） | 同上。segment を切るほど何か有意になります |
| 外れ値を後から除く | 除去 rule を先に決めていなければ p-hacking です |

**副業での対策（実行可能な最小限）**:
1. **実験開始前に、紙（または commit した file）に「必要 sample 数」「主要 metric 1つ」「判定基準」を書く。**これだけで optional stopping と metric の後付け選択は防げます。
2. 途中経過を見ない。見るなら「見ても止めない」と決めておく。
3. 副次的な発見は「次の実験の仮説」として扱い、結論にしない。

### 4.5 個人規模で A/B test は回るのか（結論: ほぼ回りません）

第4.1節の表のとおり、SaaS landing page の一般的な conversion で相対25%の改善を検出するには**14,000 click** が必要です。広告 click 単価を仮に100円とすれば140万円。副業の検証予算としては成立しません。

**参考: 大企業でも A/B test の成功率は低い**

Kohavi らの Microsoft / Bing での報告によれば、**実験 platform で test された idea のうち、意図した metric を改善したのは約3分の1**にとどまります。Bing では成功率は全社平均よりさらに低いとされます（1/3 が有意に positive、1/3 が有意差なし、1/3 が有意に negative）。

出典: Kohavi, R. et al., "Online Controlled Experiments and A/B Testing"（*Encyclopedia of Machine Learning and Data Mining*, 2015）、および KDD 2015 keynote "Online Controlled Experiments: Lessons from Running A/B/n Tests for 12 years"。書籍: Kohavi, R., Tang, D., & Xu, Y. (2020). *Trustworthy Online Controlled Experiments: A Practical Guide to A/B Testing*, Cambridge University Press.
確信度: 中（書誌は確定、1/3 の数値は検索経由抽出。PDF 本文は抽出失敗）

**この事実の副業への含意（重要）**: 世界最大級の traffic と専門 team を持つ組織でも、idea の 2/3 は外れます。**個人が A/B test なしで「良い改善」を直感で選べる確率は、それより高くはありません。**したがって取るべき戦略は「小さい改善を精密に測る」ではなく、以下です。

### 4.6 A/B test が回らない前提での代替設計

| 状況 | やること | 根拠 |
|---|---|---|
| traffic が月1,000未満 | A/B test をせず、**大きく違う案を逐次投入**し、rule of three で「明確に駄目な案」を落とす | 第4.3節 |
| 何を作るか決めたい | A/B test ではなく **concierge / pre-sale**。n=10 の実取引の方が n=1,000 の click より情報量が大きい | 第3.0節の証拠強度階層 |
| copy を改善したい | 定量比較を諦め、**5人の user test（画面を見せて操作させる）** に切り替える | 定性手法は小 n で機能します |
| 継続率を知りたい | 統計的検定を諦め、**個々の解約者に理由を聞く**（全数） | n が小さいなら全数調査が可能です |
| 効果量が大きい変更のみ test | 相対100%改善なら約1,160 click で検出可能（第4.1節） | 副業でも到達可能な唯一の帯域 |

**原則**: **sample が小さいときは定量を捨てて定性に倒し、定量を使うなら「否定」に使う。**中途半端な n で肯定的な結論を出すのが最悪の選択です。

---

## 5. Community 観察

### 5.1 目的と限界

**目的**: interview の相手を見つける前段階として、(a) どこに当事者がいるか、(b) 彼らがどんな語彙で困りごとを表現するか、(c) 既存代替案は何か、を低 costs で把握すること。

**この手法の本質的な限界を先に述べます**: community 観察は**仮説生成の手段であって、検証の手段ではありません**。第5.4節の bias により、観察された声の分布は母集団の分布と一致しません。

### 5.2 学術的な下敷き: netnography

**原著**: Kozinets, R. V. *Netnography: Doing Ethnographic Research Online*（SAGE, 2010）。および Kozinets, R. V. (2010). "Netnography: A Method Specifically Designed to Study Cultures and Communities Online."

- Kozinets が 1995年に提唱した、online 上での ethnography
- 中核手法は participant observation（参与観察）
- **community 成員の類型化**を推奨: newbies（社会的紐帯が弱く、関心も表層的）/ minglers（紐帯は強いが対象への関心は形式的）/ devotees（対象への関心は強いが紐帯は弱い）/ insiders（両方強い）
- 匿名性と informed consent の倫理を扱う
- 確信度: 高（書誌・手法の骨子）

**副業への実用的な翻訳**: **devotees と insiders の発言だけを読むと、市場を過大評価します。**彼らは対象への関心が異常に高い少数派です。**newbies の質問こそが、未解決の困りごとの最良の signal** です。「初歩的すぎて誰も答えない質問」が繰り返し投稿されている領域には、製品化の余地があります。

### 5.3 具体的な検索手順

#### 5.3.1 英語圏（Reddit / Stack Overflow / Hacker News / 専門 forum）

Reddit の検索 operator（確信度 中：Reddit 公式 help は 403 で未確認、複数の解説 source が一致）:

```
subreddit:<name>     指定 subreddit 内に限定
title:<word>         題名内を検索
selftext:<word>      本文内を検索
author:<name>        投稿者で限定
site:<domain>        link 投稿の URL domain で限定
AND / OR / NOT / "..." / ( )   boolean と句
```

**困りごとを掘る query 型（そのまま使えます）**:

```
"is there a tool that"
"is there a way to automate"
"how do I automate"
"anyone know a tool for"
"looking for a tool to"
"I built a script to"          ← 自作した = 既存製品では埋まらない需要
"we use a spreadsheet for"     ← spreadsheet 運用 = 製品化の古典的余地
"spreadsheet nightmare"
"our current process is"
"we do this manually"
"I do this manually every"
"still doing this by hand"
"there has to be a better way"
"switched from X to Y because"  ← switch interview の候補者発見に直結
"cancelled our subscription because"
"we outgrew"
"wish X had"
"X doesn't support"
"workaround for"
```

Google 経由で site 横断する場合:

```
site:reddit.com "is there a tool that" <領域語>
site:news.ycombinator.com "spreadsheet" <領域語>
site:stackoverflow.com "workaround" <領域語>
```

**時間軸を切る**: 検索結果を過去1年に絞ってください。3年前の困りごとは既に解決されている可能性が高く、また当時の代替案は今の代替案ではありません。

#### 5.3.2 日本語圏

```
"〜 自動化 したい"
"〜 手作業 つらい"
"〜 Excel 管理 限界"
"〜 スプレッドシート 運用"
"〜 転記 作業"
"〜 めんどくさい 毎月"
"〜 いい感じのツール ない"
"〜 良いツール 知りませんか"
"〜 自作した"
"〜 スクリプト 書いた"
"〜 乗り換えた 理由"
"〜 解約した"
"〜 課題 属人化"
```

検索先:
```
site:qiita.com  "自動化" <領域語>
site:zenn.dev   "作った" <領域語>
site:note.com   "困っている" <領域語>
X（旧 Twitter）  "<領域語> つらい" / "<領域語> 自動化"
```

**日本語特有の注意**: 日本語 community では困りごとが**直接的な不満の形では書かれにくく**、「〜してみました」「〜を作りました」という制作報告の形で現れます。**Qiita / Zenn の「作ってみた」記事は、その人が既存製品では満たされなかったことの証拠**です。同じ物を複数人が別々に自作している領域は、有望な signal です。

#### 5.3.3 記録方法

観察は必ず記録に落としてください。推奨 format:

```
日付 / URL / community名 / 発言者の類型(newbie|mingler|devotee|insider)
発言の原文（引用）
そこから読み取れる: trigger / 既存代替案 / 投下している時間・金
反証となる発言（同じ場所で「別に困ってない」と言っている人）
```

**「反証となる発言」欄を必ず設けてください。**これがないと確証 bias で観察が崩壊します。

### 5.4 観察の bias（定量的に）

**原著**: Nielsen, J. (2006-10-08). "Participation Inequality: The 90-9-1 Rule for Social Features." Nielsen Norman Group. https://www.nngroup.com/articles/participation-inequality/

- **90% は lurker（閲覧のみ）、9% は時々投稿、1% がほとんどの活動を担う**
- 根拠となった観測:
  - **Usenet**: 200万件超の message を調査。27% は投稿1件のみの user。最も活動的な 3% が全 message の 25% を占める
  - **Wikipedia**（2006年時点）: 3,200万訪問者中、活動的な貢献者は 68,000名（**0.2%**）。最も活動的な 1,000名（**0.003%**）が編集の約3分の2
  - **Amazon**: 数千冊売れた書籍でも review は12件程度（投稿率1%未満）
- Nielsen の結論: 「web 上の投稿を顧客 feedback として見ている企業は、代表性のない標本を見ている」
- 確信度: 高（NN/g の一次記事を直接確認）

**副業が受ける具体的な damage**:

| bias | 現れ方 | 対処 |
|---|---|---|
| participation inequality（1% rule） | 声の大きい少数の意見を市場と誤認 | 発言者数ではなく**別々の人が何人言ったか**を数える。同一人物の連投を1件に畳む |
| self-selection | community に参加している時点で、その領域への関心が異常に高い層 | community 外の人（同僚・取引先）に同じ質問をぶつける |
| survivorship | 既に解決した人は投稿しない。困り続けている人だけが可視 | 「解決した」報告を明示的に検索する（"solved it by", "結局〜で解決"） |
| 語彙 bias | 検索 query に使った語彙を使う人しか見つからない | 発見した投稿から**相手の語彙**を採取し、query を書き換えて再検索する（2〜3周回す） |
| 商業投稿の混入 | 実質広告の「困っていました→この tool で解決」記事 | 投稿者の履歴を確認する。単発 account は除外 |

**最重要**: community で観測した「困りごとの多さ」を市場規模の推定に使ってはいけません。1% rule により、観測数と実人数の比率が領域ごとに大きく違います。

### 5.5 所要時間と副業での配分

- 週2時間（平日夜 30分 × 2 + 週末 1時間）で十分に回ります
- 4週間続けると、その領域の語彙・主要 community・既存代替案の地図がほぼ完成します
- **それ以上続けても収穫は逓減します。**observation は interview の入口であり、目的ではありません

---

## 6. 日本語圏特有の事情

### 6.1 市場規模（一次統計）

| 指標 | 数値 | 出典・確信度 |
|---|---|---|
| 企業の cloud service 利用率（2024年） | **80.6%** | 総務省『令和7年版 情報通信白書』。確信度 高（総務省 page を直接確認） |
| 国内 public cloud service 市場（2024年） | **4兆1,423億円**（前年比 +26.1%） | IDC Japan、2025-02-20 発表。2029年に 8兆8,164億円（2024年比 約2.1倍）と予測。確信度 中 |
| 企業向け software 53品目の SaaS/PaaS 市場 | **2029年度 3兆3,975億円**（2024年度比 +73.0%） | 富士キメラ総研、2025-09-03 発表。確信度 中 |
| 中小企業の設備投資に占める software 投資比率 | **約7%**（大企業は約13%） | 『2025年版 中小企業白書』（中小企業庁、2025年4月）。確信度 中（白書 PDF は 403 で直接未確認） |
| digital 化に全く着手していない企業の割合 | 2023年 30.8% → 2024年 **12.5%** | 同上。確信度 中（同じく直接未確認） |
| 展示会（2019年） | 総開催数 **603件**、出展社 **77,041社・団体**、来場者 **7,490,484名**。うち BtoB 展示会が **93.7%（565件）** | 日本展示会協会。確信度 中 |

**読み取り**:
- cloud 利用率 80.6% は「使っている」の水準であり、内訳は file 保管・data 共有、社内情報共有、電子 mail、給与・財務会計・人事、schedule 共有が上位です。**汎用領域は既に埋まっています。**
- 中小企業の software 投資比率が大企業の約半分（7% 対 13%）である事実は、**「予算がない」ではなく「単価が低い」市場**を意味します。副業 micro SaaS の価格設定に直結します。月額数万円の稟議は日本の中小企業では簡単には通りません。
- digital 化未着手が 12.5% まで下がったということは、**「何も使っていない企業に初めての tool を売る」市場は既に小さい**ということです。狙いは「既に何か使っている企業の、埋まっていない隙間」になります。

### 6.2 一次情報の取り方: 日本の B2B 小規模 market

#### 6.2.1 展示会

**目的**: 短時間で同業の当事者に大量に会うこと。日本の B2B では最も効率の良い対面 channel です。

**副業での使い方（出展ではなく来場）**:
1. 対象領域の展示会を選ぶ（BtoB 展示会が全体の93.7%を占めるため、選択肢は豊富です）
2. **出展者ではなく来場者**に話しかける。出展者は営業モードであり、実務の困りごとは出てきません
3. 来場者は「その領域の課題を解決しに来ている当事者」であり、母集団として質が高いです
4. 名刺交換後、後日30分の interview を依頼する

**所要時間**: 1日（土日開催のものを選ぶ）。副業の時間制約と両立します。

**落とし穴**: 展示会は「今まさに探している人」に偏ります（第2章でいう intention が既に高い層）。ここで得た反応は市場平均より楽観的です。

**確信度**: 手法は 中（実務慣行）。統計は 中。

#### 6.2.2 note / Qiita / Zenn

| platform | 規模 | 出典・確信度 |
|---|---|---|
| Qiita | 会員 **150万人**（2025年3月突破、2025-04-22 発表）。月間 UU **800万**、月間 PV **5,000万**（2024年5月末時点集計） | Qiita 株式会社 press release。確信度 高（公式 page を直接確認） |
| note | 会員 **1,000万人**（2025年6月）。MAU **7,359万**（2025年2月時点、非会員含む active browser 数） | note 株式会社。確信度 中 |
| Zenn | 会員 10万人超、法人・組織 500超 | 確信度 低（一次 source 未確認） |

**副業 engineer にとっての使い方**:
1. **観察先として**: 第5.3.2節の query。特に「作ってみた」記事は未充足需要の証拠です。
2. **一次情報の作り手として**: 自分が対象領域で困った経験を Qiita / Zenn に書き、**comment と反応で当事者を釣り上げる**。これは日本語圏で最も costs の低い interview 相手の発見法です。「同じことで困っています」という comment がついたら、それが interview 候補です。
3. **note は B2B の意思決定者層に届きます。**Qiita / Zenn は engineer に届きますが、購買決裁者には届きません。売り先が非 engineer なら note です。

**落とし穴**: 自分の記事に反応した人は、あなたの文章に共感した人であり、標本が偏ります。第5.4節の self-selection がそのまま当てはまります。

#### 6.2.3 海外向けとの違い

| 項目 | 日本語圏 | 英語圏 |
|---|---|---|
| 困りごとの表出 | 制作報告・体験談の形。直接的な不満は少ない | 直接的な問題提起が多い（Reddit の質問文化） |
| cold outreach の反応 | 個人宛の突然の連絡は忌避されやすい。紹介の重みが大きい | cold email が商習慣として成立している |
| 決裁構造 | 担当者の熱意と決裁が乖離しやすい。稟議・複数決裁者 | 担当者裁量が比較的大きい |
| 価格帯 | 中小企業の software 投資比率が低く、単価が上がりにくい | 同等機能で数倍の価格が通る場合がある |
| 競合密度 | 日本語対応の micro SaaS は英語圏より薄い領域が残る | 大半の汎用領域は飽和 |
| 支払い方法 | 請求書・銀行振込を求められる（card 決済のみだと失注） | card 決済が標準 |

**この表の確信度は 低〜中**です。「日本は cold email が効かない」「稟議が重い」は実務家の間で広く共有された認識ですが、日本の B2B における cold outreach 反応率の統計的 data は、本調査では発見できませんでした。参考として英語圏の cold email 返信率は 2024年で **3〜5.1%** 程度という vendor 集計がありますが、これは vendor blog による集計であり確信度は 低です。

**日本語 market の規模と競合密度についての data**: 本調査では「日本語 micro SaaS の competitor 密度」を定量化した信頼できる source を発見できませんでした（確信度 高：「data が見当たらない」という点）。市場規模の統計（第6.1節）は存在しますが、niche 単位の競合密度を測った統計は存在しないと考えてください。**これは自分で調べるしかない領域**であり、第5章の community 観察と検索がその代替です。

### 6.3 日本での実験の法的制約（再掲・要点）

- **fake door で価格を表示するのは避けてください。**景品表示法第5条第3号「おとり広告に関する表示」（平成5年公取委告示第17号）の類型1・4に該当する risk があります（第3.2.2節）。
- pre-sale を行う場合、特定商取引法の通信販売表示（提供時期・返品条件・事業者情報）を満たしてください。
- Wizard of Oz で個人 data を人が閲覧する場合、個人情報保護法上の risk があります。

---

## 7. 副業 engineer 向け 最小 protocol

前提: 平日夜（1日 1時間 × 3日）+ 週末（4時間）= **週 7時間**。対面営業 network なし。

### 7.1 設計思想

第1〜6章から導かれる、この protocol の3原則:

1. **肯定を証明しようとせず、否定を早く確定させる。**（第4.3節の rule of three、第1.7節の Camuffo RCT）
2. **意向を測らず、行動と金銭を測る。**（第2章）
3. **自分が当事者である領域を選ぶ。**私的情報がなければ、community 観察も interview も、誰でもできる情報しか取れません。

### 7.2 12週間 protocol

#### Phase 0: 領域選定（週0、4時間）

| 作業 | 時間 |
|---|---|
| 自分が過去2年で「自作した script / spreadsheet」を全部書き出す | 1時間 |
| そのうち、同僚や取引先も同じ物を作っていた（または欲しがった）ものに印をつける | 30分 |
| 印がついた領域を3つに絞り、それぞれ第5.3節の query で30分ずつ観察 | 1.5時間 |
| 1つに決める。決めた理由と「これが外れる条件」を書く | 1時間 |

**判定**: 印がつく項目が1つもない場合、**その時点で領域選定をやり直してください。**私的情報のない領域に進むと、第0.3節の失敗を繰り返します。

#### Phase 1: 観察（週1〜2、週7時間 × 2 = 14時間）

| 作業 | 週あたり時間 |
|---|---|
| community 観察・記録（第5.3節の format） | 2時間 |
| 語彙を採取して query を書き換え、再検索（2周） | 1時間 |
| interview 候補者の list 化（最低20名。実名・所属・接点） | 2時間 |
| 接触（既存の知人経由の紹介依頼、Qiita/Zenn 記事の投稿） | 2時間 |

**週2終了時の判定基準**:
- 別々の人が5人以上、同じ困りごとを言っているか
- そのうち3人以上が「自作した／金を払っている／時間を使っている」を明言しているか
- **満たさなければ Phase 0 に戻ってください。**

#### Phase 2: interview（週3〜6、週7時間 × 4 = 28時間）

| 作業 | 週あたり時間 |
|---|---|
| interview 実施（週3件 × 30分） | 1.5時間 |
| 記録・整理（1件15分） | 1時間 |
| 次の候補者への接触・日程調整 | 2時間 |
| 6件終了時点の中間整理（週4末） | 1.5時間（週4のみ） |
| 既存代替案の実地調査（競合製品を実際に使う・課金する） | 1.5時間 |

**目標: 4週間で12件**（第1.8.8節、Guest et al. 2006 の飽和点）。

**質問構成**（第1.8節から選択、30分の配分）:
```
0〜3分   : 前置き・録音許可
3〜13分  : 直近の実作業を時系列で（1.8.2）
13〜20分 : 既存代替案と投下 cost（1.8.3）
20〜26分 : trigger（1.8.4）
26〜29分 : anxiety / inertia（1.8.5）
29〜30分 : 紹介依頼・画面を見せてもらう依頼（1.8.7）
```

**週4末（6件時点）の中間判定**:
- 6件のうち何件が「金または時間を実際に投じている」と答えたか
- **2件以下なら中止**。第1.8.8節のとおり metatheme は6件で出現するため、6件で何も出ないなら12件でも出ません。

**週6末（12件時点）の判定**:
| 条件 | 判定 |
|---|---|
| 12件中8件以上が同じ trigger を持つ | Phase 3 へ進む |
| 8件未満だが、特定 segment に集中している | segment を絞り直して Phase 2 を4件追加 |
| trigger がばらばら | **中止**。領域選定に戻る |

#### Phase 3: concierge（週7〜10、週7時間 × 4 = 28時間）

| 作業 | 週あたり時間 |
|---|---|
| 顧客3名に人手で service を提供（1名あたり週1.5時間） | 4.5時間 |
| 作業 log の記録と、自動化候補箇所の特定 | 1.5時間 |
| 顧客との週次 15分 check-in × 3 | 1時間 |

**必ず対価を取ってください。**金額は想定する製品価格と同水準（無料にすると第3.0節の証拠強度が landing page 以下に落ちます）。**人手であることを明示**してください（第3.4節）。

**上限を先に決める**: 顧客3名まで、8週間まで。これを超えると自動化する時間が消えます。

**週10末の判定**:
| 条件 | 判定 |
|---|---|
| 3名全員が2ヶ月目も支払った | 製品化へ進む |
| 1〜2名が継続 | segment を継続者側に絞り、concierge を4週延長 |
| 0名が継続 | **中止**。価値提案が成立していません |

#### Phase 4: pre-sale + 最小実装（週11〜12以降）

| 作業 | 週あたり時間 |
|---|---|
| landing page 作成（第3.1節） | 4時間（週11のみ） |
| concierge 顧客と、interview 12名への pre-sale 提示 | 2時間 |
| 自動化箇所の実装 | 残り時間すべて |

**pre-sale の判定**: 第4.3節の rule of three を適用してください。**接触した30名から0件なら、その価格・価値提案の conversion は10%未満**です。これは「駄目」を意味しませんが、「30名接触で1件も出ない事業は、副業の時間では立ち上がらない」という運用判断の根拠になります。

### 7.3 週次 routine（Phase 2 以降の定常形）

Torres の continuous discovery（第1.3節）から取れる部分を、1人用に縮約したものです。

| 曜日 | 時間 | 作業 |
|---|---|---|
| 平日夜A | 1時間 | interview 1件（30分）+ 記録（15分）+ 次の日程調整（15分） |
| 平日夜B | 1時間 | community 観察・記録 |
| 平日夜C | 1時間 | 実装 or concierge 作業 |
| 週末 | 4時間 | concierge 提供（2時間）+ 整理と判断（1時間）+ 実装（1時間） |

**「整理と判断」の1時間を絶対に削らないでください。**第1.7節の RCT が示す効果は、data を取ることではなく**取った data で判断を更新すること**から来ています。

### 7.4 記録 template

判断の質を担保するため、以下を1 file に維持してください（p-hacking 対策も兼ねます、第4.4節）。

```markdown
## 仮説（更新履歴つき）
- 顧客: 
- 問題: 
- 既存代替案: 
- 支払意思の仮説: 円/月
- この仮説が外れる条件（先に書く）: 

## 判定基準（Phase 開始前に確定・以後変更禁止）
- Phase 2 中間（6件）: 「金or時間を投じている」が __件以上
- Phase 2 終了（12件）: 同一 trigger が __件以上
- Phase 3 終了: 継続支払 __名以上

## 証拠 log
| 日付 | 種別(観察/interview/取引) | 相手 | 事実（解釈でなく） | 仮説への影響 |
|---|---|---|---|---|

## 反証 log（仮説に不利な事実だけを書く）
| 日付 | 事実 | 仮説のどこを否定するか |
|---|---|---|
```

**反証 log を独立させてください。**証拠 log に混ぜると、確証 bias で書かれなくなります。

### 7.5 この protocol で「言えないこと」

正直に列挙します。

- **市場規模は分かりません。**12件の interview と3名の concierge からは、市場規模を推定できません。推定したければ第6.1節の統計と、自分の segment の企業数を突き合わせる別の作業が必要です。
- **競合が来た時に勝てるかは分かりません。**
- **12件で飽和しない市場もあります。**Guest et al. 2006 は同質な母集団での知見です。顧客の業務が企業ごとに大きく異なる領域（受託・製造の現場系など）では、12件では足りません。この場合、segment をさらに絞ってください。
- **rule of three による「否定」は、その価格・その文面・その traffic 源についての否定**です。価値提案そのものの否定ではありません。ただし副業の時間制約下では、3回試して駄目なら畳むのが合理的です。

---

## 8. 落とし穴の総覧

| # | 落とし穴 | 根拠 | 対処 |
|---|---|---|---|
| 1 | 「使いますか」への肯定を根拠にする | 第2.2節（意向者の47%は不実行） | 過去の行動と支出だけを記録 |
| 2 | waiting list 登録者数で開発量を決める | 同上 | 登録者数を半分に割り引く。可能なら pre-sale に置換 |
| 3 | 価格を survey で決める | 第2.5節（仮想 WTP は中央値1.35倍、右に強く歪む） | 実決済で測る。無理なら inferred valuation |
| 4 | 有意になるまで data を取り続ける | 第4.4節（optional stopping） | 開始前に n を確定し file に commit |
| 5 | 少ない n で「conversion 5%」と結論する | 第4.2節（400訪問で ±1.9%） | 肯定は主張せず、rule of three で否定のみ主張 |
| 6 | community の声を市場規模と誤認 | 第5.4節（90-9-1、Wikipedia 貢献者は 0.2%） | 発言数でなく別人数を数える。community 外に当てる |
| 7 | 熱心な devotee の意見を代表と誤認 | 第5.2節（Kozinets の類型） | newbie の未回答質問を重視 |
| 8 | 知人に聞いて validation とする | 第2.6節（social desirability） | 知人 data は別集計。判断に使わない |
| 9 | 価格つき fake door を出す | 第3.2.2節（景表法 おとり広告） | 価格を出すなら実決済（pre-sale）にする |
| 10 | Wizard of Oz を有料 service で使う | 第3.5節 | concierge（開示）に倒す |
| 11 | concierge を上限なく続ける | 第3.4節 | 開始時に人数と週数の上限を決める |
| 12 | 初回決済で PMF と判断する | 第3.0節（stock 型の本命は継続） | 2ヶ月目の決済を判定点にする |
| 13 | Sean Ellis の 40% 基準を根拠にする | 第9章 | 方向性の目安に留める。判断の根拠にしない |
| 14 | Maurya の初版 problem interview script（問題の ranking）を使う | 第1.5節（著者が2017年に撤回） | 更新版（trigger / existing alternatives / inertia・friction）を使う |
| 15 | interview 相手が同質化する | 第1.3節 | 紹介の連鎖を2段までで打ち切り、別 channel を開く |
| 16 | 手法論の流派選びに時間を使う | 第1.0節（どの流派も未実証） | 第1.7節のとおり、態度（仮説→検証）の方が効く |

---

## 9. 補足: 広く使われているが実証が弱い指標

### Sean Ellis の product-market fit survey（40% 基準）

- 「この製品が使えなくなったらどう感じますか」に対し「非常に残念（very disappointed）」が **40% 以上なら product-market fit** とする指標。Sean Ellis が約100社を benchmark した経験に基づき、2009年に blog で公開。
- **評価**: Jim Lewis 博士・Jeff Sauro 博士（MeasuringU, 2022-03-15）は、「40% という閾値は権威的で精密に聞こえるが、**提唱者の直感に基づくもの**であり、実務利用を支持する説得力のある証拠はほとんどない」「business 判断で過度に重視すべきでない」と評価しています。MeasuringU 自身が SUPR-Q 調査で PMF score の収集を開始したものの、**結果はまだ発表されていません**。
- **統計的な問題**: n=50 で 40% を得た場合、95% 信頼区間は概ね ±13%（27%〜53%）です。副業規模の n では、40% の上下を区別できません。
- **加えて**、この質問は**未来の感情の予測を求めており**、第2章の intention-behavior gap がそのまま当てはまります。
- 出典: https://measuringu.com/product-market-fit-item/（Lewis & Sauro, 2022）
- 確信度: 高（MeasuringU の評価を直接確認）

**推奨**: 使ってもよいですが、**判断の根拠にはしないでください。**同じ労力を「先月払った人が今月も払ったか」の確認に使う方が、遥かに情報量があります。

---

## 10. 参考文献

### 意向と行動の乖離（心理学・marketing science）

- Sheeran, P. (2002). Intention—Behavior Relations: A Conceptual and Empirical Review. *European Review of Social Psychology*, 12(1), 1–36. https://www.scirp.org/reference/referencespapers?referenceid=1687803
- Webb, T. L., & Sheeran, P. (2006). Does changing behavioral intentions engender behavior change? A meta-analysis of the experimental evidence. *Psychological Bulletin*, 132(2), 249–268. https://www.semanticscholar.org/paper/fb59bc130ba009194610c16a2beb172bd218e70c
- Sheeran, P., & Webb, T. L. (2016). The Intention–Behavior Gap. *Social and Personality Psychology Compass*, 10(9), 503–518. https://compass.onlinelibrary.wiley.com/doi/abs/10.1111/spc3.12265 ／ open access: https://eprints.whiterose.ac.uk/107519/
- Morwitz, V. G., Steckel, J. H., & Gupta, A. (2007). When do purchase intentions predict sales? *International Journal of Forecasting*, 23(3), 347–364. https://www.sciencedirect.com/science/article/abs/pii/S0169207007000799
- Fisher, R. J. (1993). Social Desirability Bias and the Validity of Indirect Questioning. *Journal of Consumer Research*, 20(2), 303–315. https://academic.oup.com/jcr/article-abstract/20/2/303/1793106

### hypothetical bias とその補正（環境経済学・実験経済学）

- List, J. A., & Gallet, C. A. (2001). What Experimental Protocol Influence Disparities Between Actual and Hypothetical Stated Values? *Environmental and Resource Economics*, 20(3), 241–254.
- Murphy, J. J., Allen, P. G., Stevens, T. H., & Weatherhead, D. (2005). A Meta-analysis of Hypothetical Bias in Stated Preference Valuation. *Environmental and Resource Economics*, 30(3), 313–325. https://link.springer.com/article/10.1007/s10640-004-3332-z ／ 著者 page: http://faculty.cbpp.uaa.alaska.edu/jmurphy/meta/meta.html
- Cummings, R. G., & Taylor, L. O. (1999). Unbiased Value Estimates for Environmental Goods: A Cheap Talk Design for the Contingent Valuation Method. *American Economic Review*, 89(3), 649–665.
- Norwood, F. B., & Lusk, J. L. (2011). Social Desirability Bias in Real, Hypothetical, and Inferred Valuation Experiments. *American Journal of Agricultural Economics*. https://onlinelibrary.wiley.com/doi/10.1093/ajae/aaq142
- Entem, A., et al. (2022). Using inferred valuation to quantify survey and social desirability bias in stated preference research. *American Journal of Agricultural Economics*, 104(4), 1224–1242. https://onlinelibrary.wiley.com/doi/abs/10.1111/ajae.12268

### customer discovery / interview 手法（原典）

- Blank, S. (2005). *The Four Steps to the Epiphany*. 著者 blog: https://steveblank.com/tag/customer-development/
- Fitzpatrick, R. (2013). *The Mom Test*. https://www.momtestbook.com/
- Torres, T. (2021). *Continuous Discovery Habits*. Product Talk LLC. https://www.producttalk.org/
  - Opportunity Solution Trees: https://www.producttalk.org/opportunity-solution-trees/（2023-12-06）
  - Best Customer Interview Questions: https://www.producttalk.org/best-customer-interview-questions/
  - Product Trio: https://www.producttalk.org/2021/08/product-trio/
- Moesta, B. (2020). *Demand-Side Sales 101*. Progress-Making Forces 解説: https://jobstobedone.org/radio/unpacking-the-progress-making-forces-diagram/
- Maurya, A. (2012). *Running Lean*, 2nd ed. O'Reilly.
  - Ch.7 The Problem Interview: https://www.oreilly.com/library/view/running-lean-2nd/9781449321529/ch07.html
  - Ch.8 The Solution Interview: https://www.oreilly.com/library/view/running-lean-2nd/9781449321529/ch08.html
  - 更新版 script と Customer Forces Canvas（2017-08-17）: https://medium.com/lean-stack/the-updated-problem-interview-script-and-a-new-canvas-1e43ff267a5d
- Ries, E. (2011). *The Lean Startup*.

### 起業手法の実証（RCT）

- Camuffo, A., Cordova, A., Gambardella, A., & Spina, C. (2020). A Scientific Approach to Entrepreneurial Decision Making: Evidence from a Randomized Control Trial. *Management Science*, 66(2), 564–586. https://www.insead.edu/faculty-research/publications/journal-articles/a-scientific-approach-entrepreneurial-decision ／ SSRN: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3295625
- Camuffo, A., Gambardella, A., et al. (2024). A scientific approach to entrepreneurial decision-making: Large-scale replication and extension. *Strategic Management Journal*, 45(6), 1209–1237. https://sms.onlinelibrary.wiley.com/doi/full/10.1002/smj.3580 ／ open access: https://openaccess.city.ac.uk/id/eprint/32437/

### 定性調査の方法論

- Guest, G., Bunce, A., & Johnson, L. (2006). How Many Interviews Are Enough? An Experiment with Data Saturation and Variability. *Field Methods*, 18(1), 59–82. https://journals.sagepub.com/doi/10.1177/1525822X05279903
- Kozinets, R. V. (2010). *Netnography: Doing Ethnographic Research Online*. SAGE. https://dl.acm.org/doi/10.5555/1823232
- Kozinets, R. V. (2010). Netnography: A Method Specifically Designed to Study Cultures and Communities Online. *The Qualitative Report*. https://nsuworks.nova.edu/tqr/vol15/iss5/13/

### 実験設計・A/B testing

- Kohavi, R., Tang, D., & Xu, Y. (2020). *Trustworthy Online Controlled Experiments: A Practical Guide to A/B Testing*. Cambridge University Press.
- Kohavi, R., et al. (2015). Online Controlled Experiments and A/B Testing. *Encyclopedia of Machine Learning and Data Mining*. https://www.exp-platform.com/Documents/2015%20Online%20Controlled%20Experiments_EncyclopediaOfMLDM.pdf
- Kohavi, R. (2015). Online Controlled Experiments: Lessons from Running A/B/n Tests for 12 years. KDD 2015 keynote. https://exp-platform.com/Documents/2015-08OnlineControlledExperimentsKDDKeynoteNR.pdf
- Simmons, J. P., Nelson, L. D., & Simonsohn, U. (2011). False-Positive Psychology: Undisclosed Flexibility in Data Collection and Analysis Allows Presenting Anything as Significant. *Psychological Science*, 22(11), 1359–1366. https://journals.sagepub.com/doi/10.1177/0956797611417632

### 実験の倫理

- Kramer, A. D. I., Guillory, J. E., & Hancock, J. T. (2014). Experimental evidence of massive-scale emotional contagion through social networks. *PNAS*, 111(24), 8788–8790. https://www.pnas.org/doi/10.1073/pnas.1320040111
- Editorial Expression of Concern（PNAS, 2014-06-17）: https://www.pnas.org/doi/10.1073/pnas.1412469111
- Hill, K. (2014-07-28). OkCupid Lied To Users About Their Compatibility As An Experiment. *Forbes*. https://www.forbes.com/sites/kashmirhill/2014/07/28/okcupid-experiment-compatibility-deception/
- 消費者庁「おとり広告に関する表示」（平成5年公正取引委員会告示第17号、景品表示法第5条第3号）: https://www.caa.go.jp/policies/policy/representation/fair_labeling/representation_regulation/case_002
- 同 運用基準（平成5年4月28日 事務局長通達第6号）: https://www.caa.go.jp/policies/policy/representation/fair_labeling/guideline/pdf/100121premiums_31.pdf

### Wizard of Oz 法の原典

- Kelley, J. F. (1983). An empirical methodology for writing user-friendly natural language computer applications. *Proc. ACM SIGCHI '83*, 193–196.
- Kelley, J. F. (1984). An iterative design methodology for user-friendly natural language office information applications. *ACM Transactions on Office Information Systems*, 2(1), 26–41.

### community 観察の bias

- Nielsen, J. (2006-10-08). Participation Inequality: The 90-9-1 Rule for Social Features. Nielsen Norman Group. https://www.nngroup.com/articles/participation-inequality/

### pre-sale / crowdfunding

- Mollick, E. (2015). Delivery Rates on Kickstarter. SSRN. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2699251
- Kickstarter Fulfillment Report. https://www.kickstarter.com/fulfillment

### 指標の妥当性

- Lewis, J. R., & Sauro, J. (2022-03-15). What Is the Product-Market Fit (PMF) Item? MeasuringU. https://measuringu.com/product-market-fit-item/

### 日本の統計

- 総務省『令和7年版 情報通信白書』クラウドサービス: https://www.soumu.go.jp/johotsusintokei/whitepaper/ja/r07/html/nd111210.html
- 中小企業庁『2025年版 中小企業白書・小規模企業白書の概要』（2025年4月）: https://www.meti.go.jp/press/2025/04/20250425001/20250425001-1r.pdf ／ https://www.chusho.meti.go.jp/pamflet/hakusyo/2025/PDF/2025gaiyou.pdf
- IDC Japan「国内パブリッククラウドサービス市場予測」（2025-02-20）: https://my.idc.com/getdoc.jsp?containerId=prJPJ53205625
- 富士キメラ総研「企業向けソフトウェア53品目の国内市場調査」（2025-09-03）: https://www.fuji-keizai.co.jp/press/detail.html?cid=25089
- 日本展示会協会「展示会産業とは」: https://www.nittenkyo.ne.jp/about-exhibition/
- Qiita 株式会社「会員数150万人突破」（2025-04-22）: https://corp.qiita.com/releases/2025/04/one-million-five-hundred-thousand/
- note 株式会社「会員数1000万人突破」（2025年6月）: https://note.jp/n/n0c08f6e33ab8

### benchmark（vendor 集計・確信度 低〜中）

- Unbounce Conversion Benchmark Report（41,000 landing page、4億6,400万訪問、Q4 2024）: https://unbounce.com/conversion-benchmark-report/saas-conversion-rate/ ／ https://unbounce.com/average-conversion-rates-landing-pages/

---

## 付録: 未解決の調査項目（次に埋めるべき穴）

本調査で埋められなかった点を、後続の調査のために明示します。

1. **landing page conversion が実売上を予測するかの査読研究**: 発見できませんでした。存在しない可能性が高いです。
2. **fake door の documented な backlash 事例**: 名前のついた大規模事例は発見できませんでした。批判は原理的な議論に留まります。
3. **日本の B2B における cold outreach 反応率の統計**: 発見できませんでした。英語圏の vendor 集計しかありません。
4. **日本語 niche market の競合密度 data**: 存在しないと考えてください。自分で調べるしかない領域です。
5. **Morwitz et al. (2007) の moderator の具体的効果量**: 原典が 403 のため未確認です。購入意向を使う判断をする前に、原典の当該箇所を確認してください。
6. **Sheeran & Webb (2016) / Camuffo et al. (2024) の原典本文**: PDF の本文抽出に失敗しました。本文書の数値は検索経由の抽出です。重要な判断に使う前に原典で照合してください。
