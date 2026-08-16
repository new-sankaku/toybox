# F: Stock型 business model の類型と、model別の調査観点

調査担当: F（stock型 business model 類型）
最終確認日: **2026-08-11**（本文中の料率・条件はすべてこの日に公式 page を fetch して確認したものです。以後変わり得ます）
対象読者: 会社員 software engineer が副業として stock 型 business を立ち上げる前提

---

## 0. この文書の主張（要旨）

1. **「stock型」は単一の model ではなく、少なくとも 8 類型に分解できます。** 収益の立ち上がり速度・継続工数・platform 依存 risk が類型ごとに桁違いに異なるため、「市場調査のやり方」も類型ごとに別物になります。同じ「需要があるか」を調べても、subscription micro SaaS では *支払い意思のある法人がいるか* が論点であり、marketplace add-on では *その platform が明日も課金を許すか* が論点です。
2. **多くの類型で、最大の risk は「需要が無いこと」ではなく「流通経路の条件が一方的に変わること」です。** 本文 §3 に実例を並べましたが、告知から実施まで **5日**（Twitter API 2023）から **約6か月**（YouTube YPP 2027）まで幅があり、平均を語る意味はありません。「最悪 30 日で条件が変わる」を前提に置く方が安全です。
3. **「stock（放置しても収益が出る）」という語は、実態としては 3 類型にしか当てはまりません。** §6 で継続工数の実態を扱いますが、marketplace add-on・content 資産・open source は構造的に継続工数が重く、subscription micro SaaS は support 工数が顧客数に比例します。
4. **確信度の低い数値は本文で明示的に「低」と記しました。** 特に「micro SaaS の median MRR」「SEO 記事の減衰率」「support に要する時間」は、一次 source に当たると原典が存在しないか、方法論が開示されていない数値が流通していました（§7 に詳述）。これらを前提に事業判断をしない方が安全です。

---

## 1. 類型の整理

本文で扱う類型は以下の 9 つです（8 に加え、実務上分けるべき「自社直販 desktop / CLI tool」を買い切り software に統合し、代わりに **B2B API/data 販売** を独立させました）。

| # | 類型 | 定義 | 代表例 |
|---|------|------|--------|
| A | Subscription micro SaaS（自社 host・直接課金） | 自社 domain で web app を提供し、Stripe 等で直接月額課金 | 単機能 SaaS、niche 業務 tool |
| B | Marketplace / platform add-on | 他社 platform の拡張として配布し、platform または自社が課金 | Shopify app, Chrome extension, VS Code extension, Figma plugin, Notion/Obsidian plugin, Atlassian app, WordPress plugin |
| C | 買い切り software / desktop app | 永続 license を一度売る。自社直販または OS の app store | Mac/Win utility, CLI tool の pro 版 |
| D | Digital product（template / boilerplate / asset / dataset / font / LUT） | file を売る。納品後の運用が原理的にゼロに近い | UI kit, SaaS boilerplate, icon set |
| E | Info product / course / 有料 newsletter | 知識そのものを売る。継続課金型と買い切り型がある | Udemy/自社 course, Substack |
| F | API / developer tool（usage 課金） | 従量課金の API を提供 | 変換 API, data API |
| G | Content 資産（SEO site / YouTube / app 内広告） | 広告・affiliate で間接収益化 | 技術 blog, 解説 channel, 無料 app |
| H | Open source + 商用 license / sponsorship | OSS を公開し、商用利用に別 license を課すか sponsor を募る | dual license, GitHub Sponsors |
| I | B2B API/data 販売（企業向け直販） | 個別契約で data や API を法人に売る | 業界 data set |

※ I は個人副業では契約・与信の面で難度が高く、以下の比較表では A/F に準じるものとして扱います。

---

## 2. 類型比較表

### 2-1. 経済構造の比較

| 類型 | 収益の立ち上がり速度 | 継続運用工数 | 単価帯（観測される中心） | 主な流通 channel |
|------|----------------------|--------------|--------------------------|------------------|
| A: Subscription micro SaaS | 遅い（数か月〜年単位） | 中〜大（顧客数に比例して support が増える） | 月 $10〜$100 が中心。B2B なら $50〜$500 | SEO, 直接営業, community, 紹介 |
| B: Marketplace add-on | 速い（platform の検索流入が既にある） | 大（platform API の破壊的変更に追随） | 月 $5〜$50、または買い切り $10〜$100 | platform 内検索・ranking がほぼ全て |
| C: 買い切り software | 中（発売時に山、その後 long tail） | 中（OS version 追随が主） | $20〜$100 買い切り | 自社 site, Product Hunt, OS store |
| D: Digital product | 速い（作った瞬間から売れる） | **小**（最も stock に近い） | $10〜$100、boilerplate は $200〜$500 | Gumroad, Envato, 自社 site, X/SNS |
| E: Info product / newsletter | 中（audience の有無に全依存） | 中〜大（newsletter は発行が止まると解約） | course $50〜$300、newsletter 月 $5〜$20 | 既存 audience, SEO, SNS |
| F: API / developer tool | 遅い（開発者の採用 cycle が長い） | 中（SLA と互換性維持） | 従量。$0.001〜$0.05/call 規模 | 技術 doc, GitHub, developer community |
| G: Content 資産 | **最も遅い**（半年〜数年） | 大（更新を止めると減衰する） | 広告 RPM に依存。単体では低単価 | 検索 engine, 推薦 algorithm |
| H: OSS + 商用 license | 遅い（信頼の蓄積が前提） | **最大**（issue/PR/security 対応） | sponsor 月 $5〜、商用 license は個別 | GitHub, 技術記事, 口コミ |

### 2-2. Risk と障壁の比較

| 類型 | Platform 依存 risk | 参入障壁 | 決済 rail の自由度 |
|------|--------------------|----------|--------------------|
| A | **低**（自社 domain・自社課金。決済事業者の risk のみ） | 中（獲得 channel を自力で作る必要） | 自由 |
| B | **最高**（審査・料率・API・ranking 全てが他社の裁量） | 低（技術的には低いが、審査 queue が実質的な障壁） | platform による（§4 参照） |
| C | 低〜中（自社直販なら低、OS store 経由なら高） | 中 | 直販なら自由 |
| D | 中（marketplace 経由なら料率変更 risk。自社直販なら低） | **最低**（誰でも出せる＝競合も多い） | 自由 |
| E | 中（platform 手数料 + 推薦 algorithm 依存） | 低（ただし audience が無いと売れない） | 概ね自由 |
| F | 低（自社 API なら低）／上流 API を再販するなら**最高** | 高（信頼性・稼働率の要求） | 自由 |
| G | **最高**（検索 algorithm・推薦 algorithm・収益化要件が一方的に変わる） | 低 | 広告 network 依存 |
| H | 中（license 変更で community 離反の risk。§3-7） | 高（技術的評価の獲得） | 自由 |

### 2-3. 類型ごとに「調査で確認すべき固有の項目」

ここが本調査の中核です。共通の需要調査（担当 C/D）に**加えて**、類型ごとに以下を確認します。

| 類型 | 固有の確認項目 |
|------|----------------|
| **A: Subscription micro SaaS** | ① 課金主体が個人か法人か（法人なら請求書・稟議・年払いの要求が発生します）② 解約理由が「使わなくなった」か「代替した」か ③ 顧客獲得 channel が SEO 依存でないか（§3-9 の algorithm risk）④ 単価 × 想定顧客数が、support 工数を賄うか ⑤ 競合が free tier を出した場合に残る差分は何か |
| **B: Marketplace add-on** | ① **platform の課金 rail が存在するか**（Chrome/VS Code/Obsidian は存在しません＝自前実装が必須）② 料率の改定履歴と告知期間 ③ 審査の実測待ち時間（公式 SLA と実態は乖離します。§4）④ platform 本体が同機能を取り込む可能性（"sherlocking"）⑤ platform API の破壊的変更頻度（changelog の deprecation 件数を数える）⑥ 上位 ranking app の review 件数分布（新規参入の可否がここで決まります） |
| **C: 買い切り software** | ① 更新収益が無い前提で、OS の major update 追随 cost を賄えるか ② 「version 2 を売る」以外の再課金設計があるか ③ 返金率と海賊版の影響 ④ code signing / notarization の年間 cost |
| **D: Digital product** | ① 納品後の質問対応が発生する種類か（boilerplate は発生します。font/LUT は発生しません）② 更新義務の有無（framework 依存の boilerplate は事実上の subscription になります）③ marketplace の独占契約条項 ④ 生成 AI による代替可能性（この類型が最も直撃を受けます） |
| **E: Info product / newsletter** | ① audience 獲得 cost が先行する構造を許容できるか ② 情報の陳腐化速度（技術 course は 1〜2 年で作り直しになります）③ 継続課金型なら「発行を止めた瞬間に解約が始まる」＝ stock ではない点 ④ 会社の副業規程との整合（実名・所属の露出が前提になりやすい） |
| **F: API / developer tool** | ① 上流に他社 API を使う場合、その料率変更 risk（§3-1, §3-2 が直撃した層です）② SLA を個人で維持できるか（深夜障害対応）③ 従量課金の下限（無料枠だけで足りる利用者が大半、という分布になりがち）④ 価格が上流原価に連動して破綻しないか |
| **G: Content 資産** | ① 検索流入が主なら、algorithm 変更と AI 要約による click 減少の影響 ② 収益化要件の引き上げ risk（§3-8）③ 更新を止めた場合の減衰実測（§7 に注意点）④ 広告主単価が季節・景気に連動する点 |
| **H: OSS + 商用 license** | ① 商用 license に切り替えた際の fork risk（§3-7 の Terraform/OpenTofu が実例）② sponsorship の実効性（§6 に Tidelift 調査）③ security 報告対応の義務感が無償で発生する点 ④ 会社の職務発明・OSS 貢献規程との整合 |

---

## 3. Platform 依存 risk：実際に起きた事例

### 3-1. Twitter/X API の有料化（2023）

- 2023-02-08、Twitter は API の basic tier を **月 $100** とすると発表しました。無料 access の終了期限は当初 2023-02-09 とされ、その後 **2023-02-13** に延期されました（発表から実施まで実質 **約5日**）。無料枠は「単一の認証済み user token で月 1,500 post の write only」に縮小されました。（出典: TechCrunch 2023-02-08）
- 影響を受けた層として、bot 開発者、学術研究者、災害情報 app の開発者が報じられています。**影響を受けた開発者数の公式集計は見つかりませんでした**（確信度: 影響の存在=高／人数=不明）。
- 2026-02-06、X は固定 tier 制から **pay-per-use（credit 制）** へ移行したと発表しました。現行料金は post read $0.005/件、post 作成 $0.015/件（URL を含む post は $0.200/件）、user read $0.010/件などです。旧 free tier の利用者は $10 分の voucher を付けて pay-per-use へ移行されました。（出典: docs.x.com、確認日 2026-08-11）
- **導出される観点**: 上流 API に依存する product は、原価が 3 年で「無料 → 月 $100 → 従量」と 2 回構造変更されています。**原価が外生変数である product は stock ではありません。**

### 3-2. Reddit API の有料化（2023）

- 2023-06 に商用 API 課金が announce され、**2023-07-01** から適用されました。無料枠は OAuth 認証で概ね **100 queries/分**、超過分は **$0.24 / 1,000 calls** です。
- Apollo 開発者 Christian Selig は、Reddit から **50M requests あたり $12,000** の提示を受け、直前月の実績 70 億 requests を当てはめると **月 $1.7M / 年 $20M** に相当すると公表しました。比較として Imgur には 50M calls で月 $166 を支払っていたと述べています。
- **2023-06-08 に Apollo の停止を告知し、2023-06-30 に停止**しました。Apollo, Reddit is Fun, Sync など複数の third-party client が数週間内に停止し、数千の subreddit が抗議で非公開化しました。（出典: TechCrunch, MacRumors, Wikipedia "Reddit API controversy"）
- **導出される観点**: 価格改定は「率」ではなく「桁」で来ることがあります。**現在の原価に対する感応度ではなく、100 倍になった場合に事業が成立するかを見るべきです。**

### 3-3. Chrome Manifest V3 への強制移行（2022–2026）

公式の deprecation timeline（developer.chrome.com、確認日 2026-08-11）:

| 時期 | 内容 |
|------|------|
| 2022-01 | Chrome Web Store が Public/Unlisted の新規 MV2 拡張の受付を停止 |
| 2022-06 | 非公開 MV2 拡張の新規受付も停止 |
| 2024-06-03 | 管理画面に警告 banner を表示開始 |
| 2024-10-09 | stable channel で MV2 拡張の無効化を段階開始 |
| 2025-03-31 | 全 channel で既定無効化（一時的な再有効化は可能） |
| 2025-07-24 | Chrome 138 で再有効化も不可に |
| 2026-08-31 | 残存 MV2 拡張を Chrome Web Store から削除 |

- webRequest API が declarativeNetRequest API に置き換わったことで、content blocker の実装が制約されました。uBlock Origin は 2024-10 に stable で無効化が始まり、報道では **約 4,000 万 user** が影響を受けたとされています（確信度: 中。Google 公式の user 数公表ではありません）。
- **導出される観点**: 移行期間が長い（4年以上）ことは「安全」を意味しません。**期間の長さではなく、移行後に自分の product の中核機能が実装可能か**を見る必要があります。uBlock Origin の場合、期間が長くても機能そのものが実装不能になりました。

### 3-4. Chrome Web Store 決済 rail の廃止（2020–2021）

- **2020-09-21** に Chrome Web Store payments API の deprecation が announce されました。以降の日程は、**2020-12-01** に free trial（Try Now button）停止、**2021-02-01** に既存 item・in-app purchase の課金停止です。新規の有料拡張の作成は announce と同時に不可になりました。（出典: chromium-extensions groups、公式 deprecation notice の転載）
- 以後、Chrome 拡張の課金は開発者が自前で実装する必要があります（Stripe / Paddle / ExtensionPay 等）。
- **導出される観点**: **platform は課金 rail を「増やす」だけでなく「畳む」ことがあります。** 現在 rail が存在するかだけでなく、その rail に platform 自身が投資を続けているかを見るべきです。

### 3-5. Shopify App Store の revenue share 改定（2021 / 2025）

- 2021-06-29、Shopify は revenue share を 20% から、**年間 $1M までは 0%**、超過分 15% へ引き下げました。
- **2025-04-24**、Shopify はこの $1M 免除の **年次 reset を廃止**し、**生涯（lifetime）$1M** へ変更すると announce しました。適用は **2025-06-16**（Partner Program Agreement 更新）で、**告知から 53 日**です。2025-01-01 以降の収益のみが lifetime 累計に算入されます。（出典: shopify.dev changelog、確認日 2026-08-11）
- **導出される観点**: 料率の数字（0%/15%）が同じでも、**適用単位（年次 vs 生涯）が変わるだけで長期の実効料率は 0% から 15% へ変わります。** 料率だけでなく「計算単位」を changelog で追う必要があります。

### 3-6. Atlassian Marketplace の revenue share 改定（2025–2026、進行中）

- **2025-05-05** に、Connect app の revenue share を 15% → 20%（2026-01-01）→ 25%（2026-07-01）へ引き上げる計画が announce されました。同時に Forge app は生涯 $1M まで 0% とする incentive が示されました。
- **2025-11-03** に日程が変更され、引き上げは **2026-04-01**（Connect 20% / Forge 16%）と **2026-10-01**（Connect 25% / Forge 17%）に後ろ倒しされました。
- Atlassian は「standard rate 変更の **6 か月以上前に告知する**」と明記しています。これは本調査で確認できた platform の中で**唯一、告知期間を約束している例**です。
- 「Runs on Atlassian」badge 取得 app は 2025-10-05 から、通常の Forge app は 2026-01-01 から、生涯 Forge 収益 $1M まで 100% 受け取りとなりました。
- **導出される観点**: **告知期間の約束が明文であるか**は、platform を選ぶ際の一次評価項目になり得ます。加えて Atlassian の例は、料率引き上げと incentive がほぼ同時に出るため、**「どの技術 stack を選ぶか」が料率を決める**構造（Connect 25% vs Forge 0〜17%）になっている点が重要です。

### 3-7. Unity Runtime Fee の導入と撤回（2023–2024）

- **2023-09-12**、Unity は install 数と収益の閾値を超えた game に対し install 課金を行う Runtime Fee を発表しました。適用開始は 2024-01-01 とされ、**告知から約 110 日**でした。
- 反発を受け、**2024-09-12**、Unity は CEO Matt Bromberg 名義で **Runtime Fee の全面撤回**を発表しました（game 顧客に対し即時）。代わりに subscription 価格の引き上げが行われました。（出典: unity.com/blog、Unity Discussions、Game World Observer）
- **導出される観点**: 撤回された事例ですが、**発表から撤回まで 1 年間、事業計画が不確定だった**点が本質です。platform risk の cost は「実際に課金されたか」ではなく「意思決定が止まった期間」で測るべきです。

### 3-8. YouTube Partner Program の要件引き上げ（2026、進行中）

- **2026-08-10**、YouTube は YPP の新規参加要件を引き上げると発表しました。適用は **2027-02-01**（**告知から約 175 日**）。新規申請者は「直近 365 日で 8,000 qualified watch hours」または「直近 90 日で 2,000 万 qualified Shorts views」が必要になります。既存の YPP 参加者には影響しないとされています。
- Shorts については 2027-02-01 以降、直近 90 日で 1,000 万 views を満たさないと Shorts の広告・subscription 収益配分を受けられなくなります（long-form の YPP 資格は維持）。
- 収益配分は long-form 55% / Shorts 45% です。（出典: blog.youtube 2026-08-10、support.google.com/youtube/answer/72851、確認日 2026-08-11）
- **導出される観点**: content 資産の類型では、**「作った資産」が収益化資格を失う**形の risk があります。既存参加者は保護されたため、**参入時期そのものが資産価値を決めます**。

### 3-9. Envato Market の author fee 一律化（2026、直近）

- Envato は **2026-07-01** から、ThemeForest / CodeCanyon / AudioJungle / VideoHive / GraphicRiver の全 author を **非独占・一律 50% revenue share** に移行しました。従来は独占 author が累計売上に応じて **最大 87.5%** を受け取れる階層構造でした。独占義務は撤廃され、自社 site 等での併売が可能になりました。（出典: Envato Author Hub 告知 / The Repository 2026、**Author Hub の原典 page は本調査時点で fetch できず（403）、確信度は中**）
- **導出される観点**: **実効収益が一夜で 87.5% → 50%（約 43% 減）になり得る**という、率変更としては本調査中で最大の事例です。marketplace 単一依存の product は、この幅を吸収できません。

### 3-10. 告知期間の一覧

| 事例 | 発表日 | 実施日 | 告知期間 |
|------|--------|--------|----------|
| Twitter API 有料化 | 2023-02-08（価格発表） | 2023-02-13 | **約5日** |
| Reddit API 有料化 | 2023-05〜06 | 2023-07-01 | 約30〜60日 |
| Chrome Web Store 決済廃止（新規停止） | 2020-09-21 | 即時 | **0日** |
| Chrome Web Store 決済廃止（課金停止） | 2020-09-21 | 2021-02-01 | 約133日 |
| Unity Runtime Fee | 2023-09-12 | 2024-01-01（後に撤回） | 約110日 |
| Shopify rev share 単位変更 | 2025-04-24 | 2025-06-16 | **53日** |
| Atlassian rev share 引き上げ | 2025-05-05 | 2026-04-01（延期後） | 約330日 |
| Envato 50% 一律化 | 2026 前半（原典未確認） | 2026-07-01 | 不明 |
| YouTube YPP 要件引き上げ | 2026-08-10 | 2027-02-01 | 約175日 |
| Google Play policy 変更（常態） | 各 announcement | +30日以上 | **最低30日**（公式に明記） |

### 3-11. 「platform risk をどう測るか」の調査項目

上記から導かれる、着手前に確認すべき項目です。

1. **告知期間の明文規約があるか。** Atlassian（6 か月）、Google Play（30 日以上）は明文があります。Chrome Web Store 決済廃止のように **0 日**の例もあります。
2. **過去 3 年の料率・policy 変更回数を changelog で数える。** 回数そのものが将来の変更確率の推定値になります。
3. **課金 rail を platform が持っているか、持っているなら畳む予兆があるか。** rail を持たない platform（Chrome, VS Code, Obsidian）は自前課金が必須ですが、**畳まれる risk が無い**という逆説的な利点があります。
4. **中核機能が platform API の「制約されうる部分」に依存していないか。** MV3 の webRequest のように、期間ではなく機能の可否で判定します。
5. **platform 本体が同機能を取り込む動機があるか。** 単機能で人気の add-on ほど取り込まれます。
6. **収益化資格の要件があるか、引き上げられた履歴があるか。**（YouTube 型 risk）
7. **独占条項の有無と、解除時の移行 cost。**（Envato 型 risk）
8. **収益が単一 platform に何 % 依存するか。** 依存度 100% の状態を「事業」と呼ぶかは判断が要ります。
9. **「50% 減」「原価 100 倍」の 2 つの stress test を通るか。**（Envato / Reddit の実績値）

---

## 4. 各 platform の現在の経済条件（確認日 2026-08-11）

すべて公式 page を fetch して確認しました。確認できなかった項目は「未確認」と明記します。

| Platform | 手数料 / revenue share | 登録料 | 課金 rail | 審査 | 公表規模 |
|----------|------------------------|--------|-----------|------|----------|
| **Shopify App Store** | 生涯 $1M まで **0%**、超過分 **15%**。加えて **2.9% の決済処理手数料**。年 $20M 超または企業総収益 $100M 超の開発者は一律 15% | Partner 登録 **$19（一度きり）** | あり（Shopify が課金・merchant への請求に合算） | 公式 SLA **なし**。2026-02-26 に Shopify 公式が「現在 review 期間が通常より長い」と告知（具体的日数の提示なし） | 公式集計は未確認。third-party 集計で 12,000〜17,600 app（確信度: 低） |
| **Chrome Web Store** | **手数料なし（課金 rail 自体が存在しない）** | **$5（一度きり）** | **なし**（2021-02-01 に廃止）。Stripe/Paddle 等を自前実装 | 「多くは数日、最大で数週間」。3 週間超なら support へ。広範な host 権限・code 難読化で遅延 | 公開 item 数の公式集計は未確認。third-party 集計で 11〜17 万件（確信度: 低） |
| **VS Code Marketplace** | **手数料なし（有料 extension 非対応）** | **無料** | **なし**。sponsor link と `pricing: Free/Trial` label のみ | 公式 SLA 未確認 | 未確認 |
| **Figma Community** | **一律 15%**（決済処理・返金対応・税処理込み） | 無料 | あり（Figma が MoR 的に処理） | 未確認 | **重要: 「現時点で有料 file を売る新規 creator の承認を行っていない」と公式明記**。payout 対応 89 か国（日本を含む）。最低価格 $2、整数のみ。売上から **30 US 営業日後**に出金可、出金は **週 1 回まで**。有料 resource は個人 account からのみ公開可 |
| **Atlassian Marketplace** | Connect: **20%**（2026-04-01〜）→ **25%**（2026-10-01〜）。Forge: **16%**（2026-04-01〜）→ **17%**（2026-10-01〜）。Forge/Runs on Atlassian は**生涯 $1M まで 0%**（partner 単位で合算） | 未確認 | あり | 未確認 | 公式に「standard rate 変更は 6 か月以上前に告知」と明記。partner 数 1,800+ / 顧客 26 万超（Atlassian 公式 blog・third-party 分析、確信度: 中） |
| **WordPress.org** | **手数料なし（有料配布不可）** | 無料 | **なし** | 人手 review（期間は未確認） | 全 code が **GPL 互換 license 必須**。「支払いや upgrade でのみ解放される機能」の同梱は**禁止**。trial 後の機能停止も禁止。**外部 SaaS 連携は可**（実体のある機能かつ readme に明記が条件）。upsell 自体は可（過度な dashboard 占有は不可）。→ **freemium の pro 版は別 plugin として外部配布する構造が必須** |
| **Apple App Store** | 標準 **30%**。Small Business Program で **15%**（前年の proceeds が **$1M 未満**）。年内に $1M を超えると残りの期間は 30%、翌々年に再資格化の可能性。EU の alternative terms では 2 年目以降の subscription が 10% | Apple Developer Program **年 $99**（教育機関は waiver あり） | あり（IAP 必須の場面が多い） | 「90% が 24 時間以内に review」との数値が広く流通していますが、**公式 page からは確認できませんでした（未確認）** | 未確認 |
| **Google Play** | 他市場: 年 **最初の $1M は 15%**、超過 30%。subscription は一律 15%。**US/EEA/UK は 2026-06-30 から**: subscription 10%+5% billing fee、その他は新規 install 10%+5%、既存 install 20%+5%。韓国・India の alternative billing は 4% 減額 | **$25（一度きり）** | あり | policy 変更は **最低 30 日**の compliance 猶予を公式に明記 | 未確認 |
| **Obsidian Community** | **手数料なし（store ではない）** | 無料 | **なし**。license key / API key / login gate を自前実装 | plugin 種別 label（Free / Optional payments / Paid）の正確な申告が必須 | 公式 blog 2026-05-12 で有料 plugin を明示的に許容 |

**注記**: Chrome Web Store は同時公開 **20 extension** の上限があります（theme は上限なし）。上限緩和は申請制です。package の最大 size は 2GB、審査通過後 30 日以内に公開しないと draft に戻ります。

---

## 5. 課金 rail の調査観点

### 5-1. 主要 rail の比較（確認日 2026-08-11）

| Rail | 手数料 | Merchant of Record | 日本からの利用 | 税処理 |
|------|--------|--------------------|----------------|--------|
| **Stripe（日本 account）** | 国内 card **3.6%**、海外 card 3.6% + **通貨変換 2% **。初期費用・月額なし。銀行振込 1.5%、konbini 3.6%（最低 ¥120）、PayPay 3.98%（digital content は 9.48%） | **いいえ**（売り手が売り手のまま） | 可 | **自己責任**。各国 VAT/消費税の判定・登録・申告は自分で行う |
| **Paddle** | **5% + $0.50 / checkout**。月額・移行費なし。$10 未満の product は要相談 | **はい** | 可（sanctioned 国以外は世界中に payout。日本は unsupported list に無し）。審査で business registration certificate 等を求められる | Paddle が全支援国の税を計算・徴収・納付。売り手の sales tax 責任はゼロ |
| **Lemon Squeezy** | **5% + $0.50** | **はい** | 可（ただし Stripe による 2024-07 買収後、onboarding が長期化との報告。確信度: 中） | 同上 |
| **Stripe Managed Payments** | **5% + $0.50**（Lemon Squeezy と同率） | **はい** | 2026-04 時点で public preview。日本からの利用可否は**未確認** | Stripe が MoR として処理 |
| **Gumroad** | 直販 **10% + $0.50**。Discover 経由の新規顧客は **30%** | **はい**（2025-01-01 から） | 可 | Gumroad が全世界の sales tax を徴収・納付 |
| **Substack** | **10%** + Stripe の card 手数料 2.9%+$0.30 + recurring billing 手数料 0.7%（**公式 page が fetch 不可のため確信度: 中**） | いいえ（Stripe 直結） | 可 | 自己責任 |
| **Envato Market** | **50%**（2026-07-01 以降、一律） | はい | 可 | Envato 側で処理 |
| **Figma Community** | **15%** | はい | 可（payout 89 か国に日本を含む）。**ただし新規売り手の承認停止中** | Figma 側で処理 |

### 5-2. Rail 選択の判断軸

1. **MoR かどうかが、事務負担の大半を決めます。** Stripe 直結（非 MoR）は手数料が 3.6% と安い一方、EU VAT / UK VAT / 米国 sales tax の登録・申告義務が自分に来ます。個人副業では **MoR（Paddle / Lemon Squeezy / Gumroad）の 5〜10% は税務事務の外注費**と考えるのが妥当です。
2. **MoR は「単一障害点」でもあります。** account 停止・保留の判断権が rail 側にあり、Envato の例のように料率変更 risk もあります。売上が育った段階で Stripe 直結へ移行できる設計（顧客 data の可搬性、subscription の移行可否）を最初から確認しておくべきです。
3. **rail の日本対応は「payout できるか」と「売り手として登録できるか」が別問題です。** Figma のように payout 対応国に日本が入っていても、新規売り手の承認自体が止まっている例があります。
4. **課金 rail が platform 側に無い類型（Chrome / VS Code / Obsidian / WordPress.org）では、rail の選定が product 設計そのものです。** license key 検証 server の運用が発生し、これは「stock」の前提を崩します。

### 5-3. 日本居住者が海外向けに課金する際の「確認すべき論点 list」

**以下は税務助言ではありません。税理士に確認すべき論点の一覧です。**

1. **消費税の内外判定**: 国税庁は「電気通信利用役務の提供」（電子書籍・音楽・広告配信等、internet 経由の役務提供）について、**役務の提供を受けた者の住所等が国内にあるか**で内外判定を行うとしています。国外の顧客への提供は国外取引として消費税の対象外となる整理ですが、顧客所在地の記録・証跡が前提になります。（出典: 国税庁 タックスアンサー No.6118）
2. **事業者向け / 消費者向けの区分と reverse charge**: 「事業者向け電気通信利用役務の提供」については、国内事業者側が「特定課税仕入れ」として申告納税する reverse charge 方式が適用されます。経過措置により課税売上割合 95% 以上の事業者等は当分の間これを行わないとされています。**自分が国外 SaaS を利用する側**の論点でもあります。
3. **登録国外事業者制度の廃止**: 令和 5 年（2023）10-01 に登録国外事業者制度は廃止され、適格請求書等保存方式（invoice 制度）へ移行しました。
4. **適格請求書発行事業者の登録要否**: 適格請求書を発行できるのは課税事業者のみです。免税事業者のままだと、国内の法人顧客が仕入税額控除を取れず、取引条件で不利になる可能性があります。**顧客が国内法人中心か、海外個人中心かで、登録の要否判断が変わります。**
5. **各国 VAT/GST の登録義務**: MoR を使わない場合、EU・UK・豪州等で digital service の登録義務が閾値なしで発生する国があります。MoR 採用の主要な理由がここです。
6. **源泉徴収**: 海外 platform（YouTube 等）からの支払いにおける源泉徴収と租税条約の届出。米国 platform では W-8BEN の提出が典型的な論点です。
7. **給与所得者の申告要否**: 給与所得者の副業所得に関する確定申告の要否と、住民税の徴収方法（会社への通知経路）。
8. **勤務先の副業規程との整合**: 職務発明規程、競業避止、OSS 貢献規程。技術的な論点ではありませんが、H 類型（OSS）と E 類型（実名 audience 前提）で特に問題になります。

---

## 6. 「stock」と言われるが継続工数が重い model

### 6-1. 継続工数が構造的に重い順

**1 位: H（Open source + 商用 license / sponsorship）**

Tidelift の 2024 年 maintainer 調査（一次 source: Tidelift 公式 report / Business Wire press release 2024-09-17）によれば:
- maintainer の **60% が無償**で作業しています。
- **約 60%** が維持している project を辞めた、または辞めることを検討したことがあります。
- 辞める理由の上位は competing life demands 54%、興味の喪失 51%、**burnout 44%** です。
- **48%** が「感謝されない仕事」と感じ、**43%** が個人的 stress の増加を挙げています。
- 最多の不満（50%）は「十分な金銭的報酬が無い、または全く無い」ことです。

（確信度: 高。ただし調査対象は Tidelift の network 寄りの母集団であり、母集団 bias があります）

さらに、商用 license へ切り替える判断自体が risk です。HashiCorp は 2023-08 に Terraform を MPL から BSL 1.1 へ変更し、2023-08-25 に OpenTF（後の OpenTofu）が fork を発表、2023-09-20 に Linux Foundation が受け入れました。Redis は 2024-03 に BSD から RSALv2/SSPLv1 の dual source-available へ変更し、AWS と Google が独自 fork を維持する結果となり、**2025-05-01 に AGPLv3 を追加して事実上撤回**しました（Redis 公式 blog）。**license 変更は「収益化」ではなく「community 離反と fork の risk」として評価すべきです。**

**2 位: B（Marketplace add-on）**

- platform API の破壊的変更に追随する義務が継続的に発生します。Chrome MV3 の例では、**2022 年から 2026 年まで 4 年以上**にわたり移行作業と対応が続きました。
- 審査 queue が事業 speed を規定します。Shopify は 2026-02-26 に公式に「review が通常より長い」と告知し、community では reviewer 割り当てまで 1〜4 か月待ちという報告が出ています（**開発者の自己申告であり、公式の実測値ではありません。確信度: 低**）。
- 料率・条件の変更が §3 の通り高頻度です。

**3 位: G（Content 資産 / SEO site）**

- 検索流入は algorithm 変更と AI 要約の影響を受け続けます。
- **重要な注意**: 「2 年以上経過した page の 66% が organic 流入を失う」という Ahrefs 由来とされる数値が広く流通していますが、**本調査で Ahrefs の該当記事を直接 fetch した結果、この集計値は記載されていませんでした**（記事は個別 site の decay 検出手順を説明する内容でした）。同様に「68% の site が年間で decay により流入を失う」「AI 検索では 13 週で decay する」といった数値も一次 source を特定できませんでした。**これらの減衰率は本文書では採用しません（確信度: 低〜根拠不明）。** 減衰の存在自体は G 類型の運用者にとって既知の現象ですが、**定量値は自分の site で実測するしかない**というのが本調査の結論です。

**4 位: A（Subscription micro SaaS）**

- support 工数が顧客数に比例します。ただし **1 顧客あたりの support 時間の信頼できる調査 data は、本調査では見つかりませんでした。** 検索で得られた「10〜200 顧客なら 1 日 30 分」等の数値は、いずれも自社 tool を売る blog 記事が出典であり、方法論の開示がありません（**確信度: 低**）。採用しません。
- 加えて、決済・認証・依存 library の security update、host 側の runtime EOL 追随が継続します。

**5 位: E（継続課金型 newsletter）**

- 発行が止まると解約が始まる構造上、**stock ではなく flow です。** 買い切り course は stock 寄りですが、技術 course は内容の陳腐化により作り直しが発生します。

### 6-2. 「stock に近い」と言える類型

- **D（Digital product）**: 納品後の運用が原理的に不要です。font / LUT / icon / dataset は特にそうです。ただし boilerplate は framework の更新追随義務が発生し、実質的に subscription になります。
- **C（買い切り software）**: OS の major update 追随のみ。ただし更新収益が無いため、追随 cost を賄えるかが論点です。
- **A（自社 host micro SaaS）のうち、B2B で単価が高く顧客数が少ないもの**: 顧客数が少なければ support 総量は抑えられます。**「安く多く」より「高く少なく」の方が stock に近づきます。**

### 6-3. 収益水準の参考値（確信度に注意）

micro SaaS の収益分布として「median $500/月 MRR」「70% が $1,000 MRR 未満」「黒字の median は $4.2K MRR」といった数値が流通しています。追跡した結果、これらは **Freemius の 2025 年 report が third-party の "1,000 micro SaaS 分析" を引用したもの**で、原典の標本抽出方法が開示されていませんでした。MicroConf の State of Independent SaaS は「約 700 名の founder」を対象とする一次調査ですが、**report 本体が registration gate の背後にあり、本調査では数値を一次確認できませんでした**。

**したがって本文書では収益水準の具体値を採用しません（確信度: 低）。** 事業判断の前提には置かないことを推奨します。

---

## 7. 調査時の source 衛生に関する所見

本調査で確認された、この領域固有の情報汚染 pattern を記録します。

1. **料率・条件の記事は、決済 service 提供企業の content marketing が検索上位を占めます。** 「Chrome 拡張の収益化」「Figma plugin の売り方」で上位に来るのは決済 vendor の blog であり、料率の記載に誤りや古い値が混じります。**必ず platform 公式 page を直接 fetch すべきです。**
2. **統計値は原典に辿れないものが多いです。** §6 の SEO 減衰率、support 時間、micro SaaS median MRR はいずれも原典を特定できませんでした。孫引きが循環参照になっている典型例です。
3. **公式 page が消えることがあります。** Envato の Author Hub 告知は本調査時点で 403 を返し、Chrome Web Store の決済廃止 notice も現行 doc からは 404 で、groups.google.com の転載でしか確認できませんでした。**platform 条件は、確認できた時点で日付つきで手元に保存すべきです。**

---

## 8. 実務上の推奨（この調査から導かれる範囲）

1. **類型を先に選び、その後に idea を探す方が効率的です。** 需要調査の観点が類型ごとに違うため、類型が決まらないと調査項目が決まりません。
2. **会社員 software engineer が副業として始める場合、継続工数の観点からは D（digital product）→ C（買い切り）→ A（B2B 高単価 micro SaaS）の順に負荷が低くなります。** B（marketplace add-on）は流入の獲得が容易な反面、本調査で確認された platform 変更事例の大半が集中しており、副業の時間 budget と相性が悪い可能性があります。
3. **B を選ぶ場合、課金 rail が platform 側に無い platform（Chrome / VS Code / Obsidian）は、rail 廃止 risk が構造的にゼロという利点があります。** 一方で license 検証 server の運用が発生します。この trade-off は明示的に選ぶべきです。
4. **決済は MoR（Paddle / Lemon Squeezy / Gumroad）から始め、税務事務を外注する**のが、日本居住者が海外向けに売る際の初期構成として合理的です。手数料差（3.6% vs 5%）より、VAT 登録義務の回避価値の方が大きい規模帯です。
5. **単一 platform 依存度が 100% の構成は、Envato（87.5%→50%）と Reddit（原価 100 倍）の 2 つの stress test に耐えません。** 初期はやむを得ないとしても、耐えられない構成であることは自覚した上で選ぶべきです。

---

## 参考文献

### Platform 公式（確認日 2026-08-11）

- Shopify: Revenue share for Shopify App Store developers — https://shopify.dev/docs/apps/launch/distribution/revenue-share
- Shopify: Update to Shopify's app developer revenue share（changelog, 2025-04-24） — https://shopify.dev/changelog/update-to-shopifys-app-developer-revenue-share
- Shopify: About the app review process — https://shopify.dev/docs/apps/launch/app-store-review/review-process
- Shopify Developer Community: Longer App Store Review Times: What You Need to Know（2026-02-26） — https://community.shopify.dev/t/longer-app-store-review-times-what-you-need-to-know/31728
- Chrome for Developers: Register your developer account — https://developer.chrome.com/docs/webstore/register
- Chrome for Developers: Publish in the Chrome Web Store — https://developer.chrome.com/docs/webstore/publish
- Chrome for Developers: Review process — https://developer.chrome.com/docs/webstore/review-process
- Chrome for Developers: Manifest V2 deprecation timeline — https://developer.chrome.com/docs/extensions/develop/migrate/mv2-deprecation-timeline
- chromium-extensions: Chrome Web Store Payments Deprecation Notice（2020-09-21 転載） — https://groups.google.com/a/chromium.org/g/chromium-extensions/c/XLeZ6iKiuVI
- VS Code: Publishing Extensions — https://code.visualstudio.com/api/working-with-extensions/publishing-extension
- microsoft/vscode Issue #111800: Find a way to allow us to monetize the extensions（closed） — https://github.com/microsoft/vscode/issues/111800
- Figma Learn: About selling Community resources — https://help.figma.com/hc/en-us/articles/12067637274519-About-selling-Community-resources
- Atlassian: Updates to Marketplace Revenue Share: 2026（2025-05-05） — https://www.atlassian.com/blog/development/updates-to-marketplace-revenue-share-2026
- Atlassian: Extended Timelines for Marketplace Revenue Share Changes（2025-11-03） — https://www.atlassian.com/blog/developer/extended-timelines-for-marketplace-revenue-share-changes
- Atlassian: Runs on Atlassian Apps Can Now Take Home 100% of Marketplace Revenue（2025-10-05） — https://www.atlassian.com/blog/developer/runs-on-atlassian-apps-can-now-take-home-100-of-marketplace-revenue
- WordPress: Detailed Plugin Guidelines — https://developer.wordpress.org/plugins/wordpress-org/detailed-plugin-guidelines/
- Apple: App Store Small Business Program — https://developer.apple.com/app-store/small-business-program/
- Apple: Enrollment / Membership fees — https://developer.apple.com/support/enrollment/
- Google Play Console Help: Service fees — https://support.google.com/googleplay/android-developer/answer/112622
- Google Play Console Help: Policy announcement: July 15, 2026 — https://support.google.com/googleplay/android-developer/answer/17134731
- Obsidian: The future of Obsidian plugins（2026-05-12） — https://obsidian.md/blog/future-of-plugins/
- Unity: Unity is Canceling the Runtime Fee（2024-09-12） — https://unity.com/blog/unity-is-canceling-the-runtime-fee
- Unity Discussions: A message to our community: Unity is canceling the Runtime Fee — https://discussions.unity.com/t/a-message-to-our-community-unity-is-canceling-the-runtime-fee/1517714
- X: X API pay-per-usage pricing and credits — https://docs.x.com/x-api/getting-started/pricing
- X Developers: Announcing the Launch of X API Pay-Per-Use Pricing（2026-02-06） — https://devcommunity.x.com/t/announcing-the-launch-of-x-api-pay-per-use-pricing/256476
- YouTube Blog: New opportunities to earn and changes to the YouTube Partner Program（2026-08-10） — https://blog.youtube/news-and-events/youtube-partner-program-updates-2027-new-opportunities-earn/
- YouTube Help: YouTube Partner Program overview & eligibility — https://support.google.com/youtube/answer/72851
- Redis: Redis is now available under the AGPLv3 open source license（2025-05-01） — https://redis.io/blog/agplv3/
- Redis: Redis Adopts Dual Source-Available Licensing（2024-03） — https://redis.io/blog/redis-adopts-dual-source-available-licensing/
- OpenTofu: OpenTofu Announces Fork of Terraform（2023-08-25） — https://opentofu.org/blog/opentofu-announces-fork-of-terraform/
- Envato Author Support: Historical and Special Payment Rates — https://help.author.envato.com/hc/en-us/articles/360000618863（本調査時点で 403）
- Envato Author Hub: Changes to Envato Market revenue share and exclusivity — https://author.envato.com/hub/changes-to-envato-market-revenue-share-and-exclusivity-what-you-need-to-know/（本調査時点で 403）

### 決済 rail 公式（確認日 2026-08-11）

- Stripe 日本: 料金体系 — https://stripe.com/jp/pricing
- Paddle: Pricing — https://www.paddle.com/pricing
- Paddle Help: Which countries are supported by Paddle? — https://www.paddle.com/help/start/intro-to-paddle/which-countries-are-supported-by-paddle
- Lemon Squeezy: 2026 Update: Lemon Squeezy + Stripe Managed Payments — https://www.lemonsqueezy.com/blog/2026-update（本調査時点で 403、検索結果経由で確認）
- Gumroad: Pricing — https://gumroad.com/pricing
- Substack Support: How much does Substack cost? — https://support.substack.com/hc/en-us/articles/360037607131（本調査時点で 403）

### 税務（日本・公式）

- 国税庁 タックスアンサー No.6118: 国境を越えた役務の提供に係る消費税の課税関係 — https://www.nta.go.jp/taxes/shiraberu/taxanswer/shohi/6118.htm
- 国税庁: 国境を越えた役務の提供に係る消費税の課税関係について — https://www.nta.go.jp/publication/pamph/shohi/cross/01.htm
- 国税庁（令和6年7月）: 電気通信利用役務の提供に係る消費税 — https://www.nta.go.jp/publication/pamph/pdf/0024003-087_02.pdf

### 一次調査・報道

- Tidelift: 2024 State of the Open Source Maintainer Report（PDF） — https://assets-eu-01.kc-usercontent.com/ef593040-b591-0198-9506-ed88b30bc023/d325a56f-05be-4379-bfd1-ee4776fcad41/2024-tidelift-state-of-the-open-source-maintainer-report-.pdf
- Business Wire: Tidelift Study Reveals Paid Open Source Maintainers Do Significantly More Critical Security and Maintenance Work（2024-09-17） — https://www.businesswire.com/news/home/20240917030299/en/
- TechCrunch: Twitter says the basic tier of its API will cost $100 per month（2023-02-08） — https://techcrunch.com/2023/02/08/twitter-says-the-basic-tier-of-its-api-will-cost-100-per-month/
- TechCrunch: Popular Reddit app Apollo may go out of business over Reddit's new, unaffordable API pricing（2023-05-31） — https://techcrunch.com/2023/05/31/popular-reddit-app-apollo-may-go-out-of-business-over-reddits-new-unaffordable-api-pricing/
- MacRumors: Popular Reddit App Apollo Would Need to Pay $20 Million Per Year Under New API Pricing（2023-05-31） — https://www.macrumors.com/2023/05/31/reddit-api-changes-pricing-apollo/
- Wikipedia: Reddit API controversy — https://en.wikipedia.org/wiki/Reddit_API_controversy
- TechCrunch: Shopify drops its App Store commissions to 0% on developers' first million in revenue（2021-06-29） — https://techcrunch.com/2021/06/29/shopify-drops-its-app-store-commissions-to-0-on-developers-first-million-in-revenue/
- BleepingComputer: Google Chrome disables uBlock Origin for some in Manifest v3 rollout — https://www.bleepingcomputer.com/news/google/google-chrome-disables-ublock-origin-for-some-in-manifest-v3-rollout/
- The Register: uBlock Origin dead for many as Google purges Manifest v2 extensions（2025-02-24） — https://www.theregister.com/2025/02/24/google_v2_eol_v3_rollout/
- The Repository: Envato Ends Exclusive Author Model, Moves All Marketplace Sellers to Flat 50% Revenue Share — https://www.therepository.email/envato-ends-exclusive-author-model-moves-all-marketplace-sellers-to-flat-50-revenue-share

### 採用しなかった source（記録）

- Ahrefs: What Is Content Decay?（https://ahrefs.com/blog/content-decay/）— 流通している「2 年超の page の 66% が流入を失う」という集計値が本文に存在しないため、当該数値は採用しませんでした。
- Freemius: State of Micro-SaaS 2025（https://freemius.com/blog/state-of-micro-saas-2025/）— 一次調査部分と third-party 引用が混在し、median MRR 等の原典の方法論が不明のため、数値は採用しませんでした。
- MicroConf: State of Independent SaaS（https://microconf.com/state-of-indie-saas）— report 本体が registration gate の背後にあり、一次確認できませんでした。
- 各決済 vendor の「◯◯の収益化方法」記事群 — 料率の孫引きであり、公式 page で代替しました。
