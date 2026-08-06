# 全体解析グラフ監査レポート（2026-07-11）

Agentチーム（Review 12体 + 敵対的Verify、計58 agent）による全グラフ監査の結果。
各指摘はコード実読の上で別agentが反証を試み、生き残ったもののみ「確認済み」として記載。

- 確認済み指摘: 38件（反証により棄却: 7件）
- 目的達成と判定: ④相関matrix・③share・⑨グローブ・⑥Lorenz/Gini・横断基盤
- 目的達成が不十分と判定: ①heatmap・①'organic・②状況別・③'battle・⑤定着・⑦新規率・⑧配信者マップ

## 優先度: 高（数値・表示が誤り、または既知の結論と矛盾する表示が出る）

### ⑤ 入室数と同接（定着）— KPIとして成立していない
1. **retained_per_join の分子分母が別母集団** (algorithm/high)
   `net_change`は匿名込み総同接（`buckets.viewers`=m_total）の純増、`total_joins`は会員JoinEventのみ。匿名増減が会員入室に帰属し、値が1超・負になり得る。frontend「1入室あたりN人が定着（残りは入れ替わり）」は0〜1前提で破綻。`analytics.py:554-558,1160`
2. **j>0のbucketだけ純増を合算する選択バイアス** (algorithm/high)
   入室0のbucket（delta≤0が支配的）の減少が脱落し、定着率が系統的に過大。真にΣ純変化なら末尾-先頭のtelescopingになるはず。`analytics.py:556-558`
3. **joins≠純増・join間引きの既知落とし穴が無注記のままKPI化** (purpose/medium)
   再入室重複・TikTok側間引きを含む概算値を断定表示。`collector.py:3095-3096` / `analytics.js:479`
4. 時刻別の棒(入室SUM)と線(同接MEAN)の並置は観測時間量の交絡を含み、「棒高・線不変=抜けている」の読み方が成立しない。`analytics.py:1143,1152`

### ⑦ 入室者の内訳（新規/常連）
1. **「人数」表示の実体はjoinイベント数（DISTINCTなし）** (bug/high)
   離脱→再入室で多重計上。常連ほど再入室が多く新規率が下方に歪む。`COUNT(DISTINCT identity_key)`+`MIN(first_seen)`判定にすべき。`analytics.py:511-515`
2. **left-censoring/truncation biasの注記なし** (purpose/high)
   「新規」=監視が初観測したidentity_key。監視開始直後・配信者の初回session直後は新規率が構造的に~100%に張り付く。warm-up除外か注記が必要。`analytics.py:511` / `storage.py:453-462`
3. first_seenが全配信者横断のため、配信者Aの常連がBに初訪問しても「常連」扱い（新規過小）。`storage.py:66`
4. users未登録(identity_key空)のjoinが無条件に常連側へ流れ新規率を希釈。(bug/low)

### ③' バトル開始後の入室数の変化
1. **anySigがpre区間(-60..0s)のbinを含む** (bug/medium)
   開始前の交絡由来上振れ1binで「比較帯を超える明確な入室増あり」と表示。既知の「battle効果は交絡でほぼ0」と正面から矛盾する誤表示が出うる。post限定(index>pre)にすべき。`analytics.js:333-337` / `analytics.py:934-937`（peak計算はpost限定なのにsigだけ全域という不整合）
2. **pre_rise(逆因果)警告をrenderBattleが未表示** (purpose/medium)
   backendは算出済み(`analytics.py:966`)。help「読み方は③と同じ」の約束を満たさない。renderShareと同じ分岐を追加。`analytics.js:324-340`
3. onsetがmarker受信時刻ベースで不応期300s≒バトル長のため、長尺battleではFINISH markerが第2のonsetになる。onsetはbattles.start_timeを使うかbattle_id単位でdedupすべき。(bug/medium)
4. 参考倍率の「バトル外」が他バトル区間を含み希釈（_subtract_intervalsで除外可能）。(low)

### ② 状況別の入室速度
1. **「Battle中は平時のX倍」太字が交絡注記なしで、③'の自己記述と矛盾** (purpose/high)
   ③'helpが「単純な倍率は時間帯の影響を効果と取り違える」と格下げしている計算そのもの。最低限「時間帯の影響を含む参考値。因果は③'参照」の注記が必須。`analytics.js:206`
2. battle/collab秒(wall-clock)と総秒(bucket数×bucket_seconds)の測定基準混在でnormal_secondsが歪む（収集断のある配信でnormal率が信頼不能）。(bug/medium) `analytics.py:569,626-628,1180`
3. per_min/倍率にn・CIの担保なし（normal区間が短い配信で倍率が暴れる）。(medium)
4. `!("collab" in data)`の警告分岐は到達不能dead code（reduceが常にcollabキーを返す）。(low)

### ⑧ 配信者マップ（規模×効率）
1. **x軸「平均同接」の実体はPeak同接の配信ごと中央値**（field名もavg_viewersと誤称）。(purpose/medium) `analytics.py:523,1115,1124`
2. **効率=総コイン/ΣPeakは配信長に交絡**。「1視聴あたり収益」ならviewer-minutes（Σ平均同接×秒）を分母に。(algorithm/medium) `analytics.py:1126`
3. Peak分母で小規模配信者のyが爆発、線形軸・外れ値処理なし → log軸/min-peak足切り/winsorize。(medium)
4. バブル径・tooltipのsessions数がPeak=0のsessionを含み統計母数と不一致。(low)

## 優先度: 中（統計的厳密性・透明性）

### ③ シェア後の入室数の変化（設計は妥当、CIが楽観的）
1. **窓重複(refractory 20s ≪ 窓幅250s)のpseudo-replicationで95%CIが過小、有意判定が楽観側** (algorithm/high)。session内クラスタも無視。cluster-robust化かblock-bootstrapが本来必要。`analytics.py:47,262-274,934-937`
2. placebo帯がbattle期を除外していない（保守側バイアス+「無関係な時点」の文言不一致）。battle近傍もforbiddenに。`analytics.py:393-395`
3. peak%の分母(全体平均rate)と線の基準(窓内local baseline)が別物で「平常比」が2種類の平常を指す。`analytics.py:918,963`
4. n=5でもz=1.96固定（t分布ならn=5で約3割広い）。(low)
5. 近接onset(3〜24bin先)の山がpost窓に漏れuplift上振れ（マスク補正なし）。(low)

### ⑨ グローブ発動率（中核仕様は正しい）
1. **undecided(判定不能)件数がbackendで算出済みなのにUI完全未表示**。docstringの「別掲する」意図が未達。(purpose/medium) `analytics.py:1063` / `analytics.js:395-397`
2. **battle_id横断dedupが両参加者監視時に相手側の自陣グローブ標本を丸ごと破棄**（ownが互いに素なので二重計上は元々起きない。dedupはowner区別なし）。(bug/medium, confidence high) `analytics.py:1021-1025`
3. n=1で100%の帯も大nの帯と同一の暖色フルバー（Wilson/Jeffreys CI・n閾値淡色化なし）。(medium)
4. 単価>45000・帯境界の隙間(非整数fallback単価)のgiftが無計上で黙って消える。範囲外を別カウントすべき。(low)
5. 色分け(暖色=抽選率20-30%圏)の凡例がUIにない。

### ④ 相関matrix（実装は数学的に正しい）
1. **偏相関の制御がpeak同接のみで配信長(exposure)未制御**。相関対象がSUM累積のため長時間配信で全指標が一斉に膨らむ交絡が残る。nを制御変数に追加するかrate化。(algorithm/medium) `analytics.py:324-331,876`
2. n=3〜でも|v|≥0.5で濃色an-strong断定表示（CI/有意性/最低n閾値なし。③はCIを出すのに不揃い）。(medium)

### ① 時間帯heatmap（構造は概ね妥当）
1. help「右端全部=全曜日の合計」は誤り。実装は全観測の中央値。文言修正。(purpose/medium) `analytics.html:59` / `analytics.py:855`
2. 中央値がnb(枠内bucket数)非重み付けで、配信端の低coverage slot(開始burst等)が満coverage slotと同格に混入。最小nb閾値かnb重み付き中央値。(algorithm/medium) `analytics.py:834-847`

### ①' organic入室
1. **重み係数(0.15/0.45/0.30/0.10)はhard-codeの勘値**（提案書§15.8自身が「勘の重み」と明記。MVPヒューリスティックとして文書化済みだが、CLAUDE.mdのhard-code禁止方針とは緊張関係）。(algorithm/high→緩和あり) `analytics.py:31-34`（`w=min(1.0,w)`はdead clamp）
2. **§15.8が結論づけた緩和UI（n_sessions併記+薄いデータで控えめ提示）が未実装**。n_sessionsは算出済みなのにrenderOrganicが未参照。(purpose/medium) `analytics.py:1245` / `analytics.js:602-618`
3. 暖色線は構造的に常に灰線以下（weight≤1.0）で「下がる時間帯」の二値的な読ませ方が誤読を招く。share_window系列・organic_ratioは算出されるが未描画のdead data。

### ⑥ Lorenz/Gini（実装は正しい）
1. population Gini式は最大(n-1)/nで頭打ち。貢献者n=10で独占でも0.9止まりなのにhelp「1に近いほど偏り大」。sample補正(n/(n-1))か注記。(medium) `analytics.py:233`
2. 母集団は「貢献者(>0)のみ」で無言視聴者を含まない旨の注記なし。(medium)
3. Lorenz x軸`reverse:true`で慣例（右端=人口100%）と逆向き。(low)

### 横断
1. 期間フィルタがstarted_at基準のため「窓外開始・継続中」の配信が丸ごと除外され、窓内開始は窓外活動も全量計上（境界非対称、注記なし）。(low)
2. 部分取得失敗時にsafeRenderがnullスキップし、前回描画がstaleのまま残る（期間切替後に前期間のグラフを誤認しうる）。(improve/medium)
3. n併記の一貫性: ①'⑤⑦は配信本数を未表示（ページ冒頭の約束と不整合）。
4. `_session_long_enough`はended_at=Noneで無条件True → 開始直後の収集中sessionが①/①'に混入。

## 反証により棄却された指摘（安心材料）
- timezone('localtime')依存 → localhostアプリ前提の文書化済み設計（storage.py:1368）で実害なし
- organic「無反応初訪85%割引が目的を反転」→ データ上識別不能な本質的限界であり、0.15 floorは文書化済みの設計判断。silent層の時間帯信号は支配項として残る
- organic「1配信者検証の過剰一般化」→ 本グラフは全session集約で、volume加重により補正が有効な大手が支配的。集約文脈では主張は妥当
- ②「battle_id空で件数水増し」→ collectorがdictでdedup済み+n_battlesはUI未使用
- ⑤「先頭bucketの入室が分母から脱落」→ delta測定不能時に分子分母両方から落とす一貫した設計。delta=0扱いは逆に捏造
- 横断「_session_long_enoughのグラフ間不整合」→ ①/①'の正規化固有のフィルタであり、raw集計の⑤/⑦に適用する方がデータを捨てる
- ④「レート正規化の文言不一致」→ 冒頭文はページ全体の手法列挙であり④固有helpは実手法を透明に開示済み

## 推奨対応順
1. ③' anySigのpost限定化 + pre_rise警告追加（誤結論の直接表示。修正は小さい）
2. ⑤ retained_per_joinの再設計（分母unique化 or 指標の置換）と断定文言の撤回
3. ⑦ DISTINCT化 + left-censoring注記/warm-up除外
4. ② 倍率への交絡注記（③'への参照）
5. ⑧ 軸ラベル修正 + 効率のviewer-minutes化 + log軸
6. ⑨ undecided表示 + owner区別dedup
7. ③/④ CIの改善（クラスタ考慮・小標本表示制御）
8. ①/①'/⑥ 文言修正・n併記・注記類

## 対応状況（2026-07-11 第1弾修正）

### 修正済み
- **③'**: anySigを「開始後(lag>0)かつ増加」のbinのみに限定。pre_rise警告をrenderBattleに追加。ピーク%に「全期間の平均入室レート比」を明記（analytics.js）
- **⑤**: 「1入室あたり定着」を撤回し、drift補正付き「1入室あたり同接押し上げ」推定に置換（入室なしbucketの平均変化を差し引き、選択バイアスを除去）。時刻別の棒を件/分に正規化して観測時間量の交絡を除去。joins概算・匿名混入の注記を追加（payload v2）
- **⑦**: DISTINCT identity化（人数=時間帯ごとのユニーク人数、newcomersも同基準）。識別できない入室はexcludedとして別掲し率の母数から除外。left-censoring・グローバルfirst_seenの注記をhelp/noteに追加（payload v2）
- **②**: 倍率へ時間帯交絡の注記（③'参照）を追加。到達不能なcollab警告dead codeを除去。総稼働秒をwall-clock基準に統一しnormal秒の単位混在を解消（payload v2）
- **⑧**: 規模=配信ごとの平均同接(AVG)の中央値へ変更（Peak誤称を解消）。効率=コイン/viewer-hours（配信長交絡を除去）。x軸を対数化。Peak=0 sessionを件数から除外（payload v2）
- **⑨**: dedupを(owner, battle_id)化（両参加者監視時の標本破棄を解消）。undecided・コイン帯範囲外件数をnoteに表示。Wilson 95%CIを全体noteとtooltipに追加
- **③/③'共通**: placebo(比較帯)からshare/battle双方の近傍を除外（交絡時点の汚染を解消、payload v2）。CI係数を小標本でt分布補正（z=1.96固定を解消）
- **①**: help「全部=合計」→「中央値」に修正。tooltipのnの意味を明記。slot coverage 25%未満の端切れ観測を除外（低coverage歪みの軽減）
- **①'**: n_sessions(配信本数)をnoteに表示。「暖色は常に灰以下・見るのはギャップ」に文言修正。「一致確認済み」の過剰一般化を限定表現に修正
- **⑥**: 貢献者内の偏りである旨・Gini上限(n-1)/nをhelp/noteに明記。Lorenz x軸のreverseを外し慣例の向きに修正

### 修正済み（2026-07-11 第2弾）
- **③/③' CI**: 窓のpseudo-replication対策として、sessionをクラスタとしたcluster-robust分散(CR1)+t(G-1)へ変更。session内の窓重複・自己相関をすべて吸収（単一sessionしか無い場合は素のSEにフォールバック）。合成データで強相関クラスタのCIが素のSEの約3.4倍に広がることを検証済み
- **③' onset**: marker受信時刻→`battles`表の`start_time`（battle_setting実開始時刻）に変更。FINISH markerが同一バトル内の第2 onsetになる問題を解消（実DBでonset 351→250）（peri_battle v3）
- **③' 参考倍率**: 「バトル外」から全バトル窓union分の時間・eventを差し引き、真の平時を基準化（battle_ratio v2）
- **④ 偏相関**: 制御変数を同接のみ→同接+配信長(bucket数)の2変数重回帰残差に変更。実データで入室×コイン 素0.56→偏相関0.02となり、配信長交絡が支配的だったことを確認。t近似の5%有意判定を追加し、有意でないセルは色なし参考値として表示
- **横断**: 取得失敗パネルにstale警告を表示。期間フィルタ境界（開始時刻基準）の注記を追加。⑤⑦に配信本数(n_sessions)を併記

### 未対応（提案書の将来項目・低優先）
- ①' 重み係数のデータ駆動化（PU learning等、提案書§15の将来項目。データ駆動weightは§15.8で一度棄却済みのため要再検討）
- ③ 近接onsetのpost窓漏れマスク（cluster-robust化で分散側は対処済み。点推定の上振れは残るが軽微）
- ① `_session_long_enough`が収集開始直後のsessionを含む点（実害軽微）
