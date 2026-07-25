# TicTok 画面デザイン改善 提案書（案）

監視ページを中心とした画面デザイン変更案です。方針に沿って「情報密度を上げつつ、スクロールに頼らず一画面で把握できる」構成へ刷新します。
本書は**案の段階**です。実装着手前にuser承認をお願いします。

## 1. 対象と確認用モック

ブラウザで各ファイルを開くと **BEFORE（現状）/ AFTER（案）** を上部ボタンで切替できます。サンプルデータ入りの静的モックです（Server不要、単体で開けます）。

| ページ | モック | 状態 |
|--------|--------|------|
| 監視 | `TicTok/static/mockup/monitor.html` | STATSコンパクト化(見切れ修正)・Battle Score改名・過去配信比較・Battleタブ・Preview縦長・STATS/グラフ50:50 |
| 全体監視 | `TicTok/static/mockup/overview.html` | 集計バー＋高密度タイル・Preview縦長 |
| 履歴 | `TicTok/static/mockup/history.html` | Excel的一覧＋選択でGift増減グラフ |
| Battle詳細 | `TicTok/static/mockup/battle.html` | Battleごとの個別詳細（自陣/敵陣・形式・相手・時刻・実弾Gift・勝敗） |
| 設定 | （現状維持） | フォーム中心のため変更最小 |

## 1.5 用語と Battle（対戦）機能の拡張

`collector.py` の `battle_points` は **Battle（LinkMic対戦）中の配信者(host)スコアの合算**です（`armies` eventの `host_score` を battle_id ごとに合計）。「B.Score / PK」は分かりにくいため、UI表記を **「Battle Score」** に統一します（カタカナ「バトルスコア」と同義。本Projectのカタカナ→英語方針に合わせ英語表記を採用）。

### 現状で取得しているもの / いないもの

現状は **自陣スコアの合算のみ**で、しかも **Battleごとではなく合計値**です。ただしTikTokLive 6.6.5 の `WebcastLinkMicBattle` / `BattleUserArmies` には、ご要望のデータがほぼ全て含まれており、collectorが**受信しているが破棄している**だけです。

| 欲しい情報 | 現状 | ライブラリでの取得可否（追加実装で対応） |
|-----------|------|------------------------------|
| Battle Score（自陣） | ✅ 収集中（合算） | Battleごとに分離して保持に変更 |
| 敵陣 / 相手のスコア | ❌ 破棄中 | ✅ `armies` の他host_idの `host_score` |
| 個人戦 / チーム戦の区別 | ❌ なし | ✅ `BattleSetting.battle_type` / `team_users`・`team_armies` の有無 |
| 対戦相手（名前） | ❌ なし | ✅ `anchor_info`(BattleUserInfo) / `anchor_id_str`＋room情報 |
| いつのBattleか | ⚠️ markerに時刻のみ | ✅ `BattleSetting.start_time_ms`・`end_time_ms`・`duration` |
| 実弾で飛んだGift（誰がいくら） | ❌ なし | ✅ `BattleUserArmies.user_armies`（`BattleUserArmy`: nickname・`diamond_score`） |
| 勝敗 | ❌ なし | ✅ `battle_result`(BattleResult.result) / `team_battle_result` |
| Battleごとの個別表示 | ❌ 合算のみ | ✅ battle_idごとの個別レコードに変更（`battle.html` の表示） |
| **対戦形式（1v1 / 3コラ・4コラ / チーム NvM）** | ❌ 1対1に畳む | ✅ `participants[]`（各hostのscore/side/team_id/rank）で形式ごとに表示 |

### 対戦形式（topology）の扱い
Battleは1対1だけではありません。**個人マルチ（3コラ・4コラ）= N者の総当たり（順位制）** と **チーム戦 NvM** があります。従来は `own_score` / `opp_score` の2スカラーに畳んでいたため、3コラでも「自分 vs 一番強い相手」の1対1に見えていました。

- **判定は確定可能**: 個人/チームは `team_users`・`team_armies` の有無で確定（推測でない）。人数は `armies` のhost数 / `team_armies` の `team_id` グループで確定。
- **自チームは一意**: 監視中の配信者本人（`room_info.owner.id` = `_owner_id`）を含むチームが自チーム。配信者は接続roomから一意に分かるため曖昧さなし（残る確認点はID体系＝`anchor_id_str` がuser_id数値か、の整合のみ）。
- **モデル**: `own/opp` スカラーをやめ `participants[]`（`user_id`・`score`・`side`・`is_own`・`team_id`・`team_score`・`rank`）を一次データ化。`own_score`/`opp_score`/`result` は後方互換の派生値として維持。
- **表示**: 1v1=従来2バー、個人マルチ=**順位リスト**（自分強調・WINは1位）、チーム=**チーム合計2バー + メンバー内訳**（team_id単位、3チーム以上は「敵チーム①②」、人数可変）。
- **生protoは保存しない**: armies eventは高頻度発火し生protoはDisk/速度に不利。抽出済みの構造化（最終スナップショット）のみ `battles` テーブルへ保存する現方針を維持。

**結論**: ご要望（自陣/敵陣、個人戦/チーム戦、相手、時刻、実弾Gift、勝敗、個別表示、**3コラ/4コラ・チーム戦の形式別表示**）はすべて **新規データ収集なしで実装可能**です。必要なのは collector の保持構造をbattle_idごと・participants単位に変更し、破棄しているfieldを拾うことと、保存（storageにbattleテーブル追加）です。

## 1.6 ユーザーのアイコン（avatar）と「ID ≠ 表示名」

- **アイコンは取得可能**: `User.avatar_thumb / avatar_medium / avatar_large`（`ImageModel.m_urls` = CDN URL配列）。Gift送信者・Comment・入室者・**Battle貢献者**(`BattleUserArmy.avatar_thumb`)など、全ユーザーで取得できます。現状 `collector._user_payload`（collector.py:97）は **unique_id と nickname だけを抽出しavatarを破棄**しています。
- **ID と表示名は別物**:
  - `unique_id` … @ハンドル（一意・安定。**同定に使うべきキー**）
  - `nick_name` … 表示名（任意に変更可・他人と重複し得る）
  - `id`（数値）/ `sec_uid` … 内部の安定ID
  - → UIは **「表示名＋@id」を併記**し、集計・名寄せは unique_id（または数値id）で行う方針とします。モック各所（Gift/Comment/Ranking/Battle貢献者/配信者）に反映済み。
- **実装上の注意**: avatarのCDN URLは**有効期限切れ/ホットリンク制限**の可能性があるため、本実装では取得時刻での表示（必要なら自前proxy/cache）を検討します。Fallbackは設けず（方針）、URL不在時はイニシャル表示などの確定仕様にします。

## 2. 方針と対応

| user方針 | 現状の課題 | 案での対応 |
|----------|-----------|-----------|
| タイトルなど本質的に不要な部分はコンパクト | header（大見出し＋サブ＋nav）で縦に約4行消費 | 1行のスリムtopbarに統合（mark＋極小タイトル＋nav＋追加入力＋接続状態） |
| 情報密度を上げる | stat 1セルが大きく17項目で縦長 | statを「現在/累計/レート」でグループ化し小型セルで高密度配置 |
| スクロールに頼らない | 全パネルが縦積みで全体把握に多数スクロール | `height:100vh`の3カラムダッシュボード。スクロールは各カラム内部のみ |
| 直観的に分かる | 関連情報が縦に分散 | 左=映像/状態/操作、中=数値/推移、右=活動ログ、と役割で列を分離 |
| ユーザビリティが良い | nav・操作が上部固定で、スクロール時に見えない | topbar/tab/操作を常時表示。タブに概況（視聴者・💎・REC）を内包し切替前に把握 |
| 画面の更新が漏れなく行われる | パネルが多く更新箇所が散在、視認しづらい | 更新領域をカード単位で集約。差分（▲+52等）表示で変化を明示 |
| 要素追加でユーザビリティを損なわない | 縦積みは追加するほど更に伸びる | 右カラムをセグメント切替の1ペイン化。指標追加はタブ追加で吸収（縦に伸びない） |

## 3. レイアウト構成（AFTER）

```
┌────────────────────────────────────────────────────────────┐
│ ■TicTok | 監視 全体監視 履歴 設定 |        @___ [監視開始] ● │ topbar(1行)
├────────────────────────────────────────────────────────────┤
│ ●@kawaii_live 👁1.2k 💎18.6k REC | ●@music_room | ○@game_ch │ tab(概況内包)
├──────────────┬───────────────────────┬─────────────────────┤
│ LIVE Preview │ STATS 現在/累計/レート │ [Gift|Comment|Event │
│ CONNECTED    │ (高密度グリッド)       │  |Ranking]          │
│ steps ■■■■   ├───────────────────────┤ ┌─────────────────┐ │
│ [録画][停止] │ TIMELINE              │ │ 活動ログ         │ │
│ [再開][解除] │ (残り高さ全面)         │ │ (内部スクロール) │ │
└──────────────┴───────────────────────┴─────────────────────┘
│ ● Server接続中                          Glory to Mankind     │ footer
└────────────────────────────────────────────────────────────┘
```

- グリッド: `minmax(16rem,21rem) / minmax(0,1fr) / minmax(18rem,25rem)`。固定px幅を使わずFlexible（CLAUDE.md準拠）。
- 狭幅（〜60rem）では1カラムに自動stack（モバイル対応）。
- YoRHa（NieR）デザイン言語・配色tokenは現状を踏襲。装飾を削り情報面積を拡大。

## 4. 主要な変更点

1. **header → スリムtopbar**: 大見出しとサブタイトルを廃し1行に集約。「監視対象の追加」も常時topbarへ。
2. **statのグループ化＋小型化**: 17項目を 現在/累計/レート の3群に整理。差分インジケータ（▲▼）で更新を可視化。
3. **3カラム化**: 映像・数値・活動を横並びにし、各列内部のみスクロール。一覧性を確保。
4. **活動ログのセグメント統合**: Gift / Comment / Event / Ranking を1ペインの切替に。件数バッジ付き。縦方向の肥大化を防止。
5. **タブへの概況内包**: タブに視聴者・💎・REC状態を表示し、切替前に各配信の状況を把握。

## 4.5 STATS のコンパクト化と「過去配信比較」の追加

- **コンパクト化**: stat 1セルを「ラベル左・値右」の1行型に変更。`視聴者数/入室数/接続時間` 等の横幅占有を解消し、1行あたりの項目数を増やしました。現在/累計/レートを1グループに統合。
- **過去配信比較（新機能）**: 監視中の配信者について、過去Sessionとの比較表（今回 / 前回 / 平均(直近5) / 自己Best）を追加します。

### 過去配信比較のデータ実現性

- 過去配信データは **既に `storage.py` の `sessions` テーブルに unique_id 単位で保存**されています（`stats_json`・timeline・events）。履歴ページが利用中で、新規データ収集は不要です。
- 必要な追加は **per-streamer 集計エンドポイント1本**のみ（例: `GET /api/monitors/{unique_id}/history-stats` → 直近Nセッションの集計と自己Bestを返す）。`storage.list_sessions()` の結果を unique_id でフィルタ集計すれば実装可能です。
- フロントは監視ページの STATS 内に比較表として描画（既存の WebSocket 更新ループに影響なし）。

## 5. トレードオフ・確認したい点

- 活動ログを「同時表示」から「切替表示」に変更します。3種同時に見たいニーズがある場合は、右カラムを縦2分割する案も可能です（密度とのトレードオフ）。
- 「Result分析（UserごとのGift / Gift種類別）」は、本案ではRankingタブ＋既存の履歴ページへ集約する想定です。監視ページに常設したい場合は中央下部に折りたたみ領域として追加できます。
- 1画面に収める前提のため、極端に小さい画面では密度が高くなります（狭幅では自動でstack）。

## 6. 全体監視・履歴の案

### 全体監視（`overview.html`）
- 上部に **集計バー**（監視数 / LIVE中 / 録画中 / 合計視聴者 / 合計Gift / 合計💎）を追加し、全配信を一目で俯瞰。
- cardを **高密度タイル** へ。KPIを2列インラインに圧縮し、1画面あたりのタイル数を増やしてスクロールを削減。
- 並替（💎/視聴者/レート/状態）と一括映像・音声トグルを集計バー右に配置。

### 履歴（`history.html`）
- 縦積み3パネル → **Excel的な1枚の一覧表** に再構成（全Sessionを多列で俯瞰。配信者/期間/状態の絞込、列の表示切替、並替、CSV出力）。
- 「特定の日を開いて詳細展開」ではなく、まず**一覧で見比べる**ことを主体に。
- 行（配信者）を選ぶと下部に **Gift / Diamonds の増減グラフ**（Session別の推移）を表示。
- 個別Sessionの深掘り（Ranking・録画・実弾Gift内訳など）は「詳細」リンクから。

### 監視ページの調整（今回反映）
- 3カラムの比率を **LIVE Preview 40% / STATS+TIMELINE 35% / 活動ログ 25%** に変更。
- **LIVE Preview を枠いっぱいに最大化**（左カラムの残り高さを全て使用。縦長9:16はレターボックスで中央表示、操作・状態は下部にコンパクト集約）。
- STATS の**見切れを修正**（セル幅を確保しラベルは省略表示、はみ出しを抑制）。
- 中央カラムを **STATS 50% / TIMELINE 50%** に分割（STATS側は内部スクロール）。
- 活動ログに **Battle タブ** を追加。

### 全体監視ページの調整（今回反映）
- tile gridを **auto-fit + 1fr** にして**余白を残さず**画面を充填、**Liveをtile幅いっぱい（縦長9:16）で大きく表示**（tileは最大22remで中央寄せ）。
- 各tileヘッダーを **3分割（avatar固定 / 名前=可変・省略 / 状態固定）** に再構成し、**見切れ・不揃いを解消**。

## 7. 今後の展開（承認後）

1. 監視ページ実装（`index.html` / `style.css` / `app.js`）＋ per-streamer 履歴集計エンドポイント追加（過去配信比較）。
2. 全体監視・履歴を本案で実装。
3. 設定: 現状維持。

> 次のアクション: 3ページのモック（`TicTok/static/mockup/`）をご確認のうえ、方向性・トレードオフ・過去配信比較の追加可否についてご判断をお願いします。

## 8. 実装状況（本案の反映）

user承認のもと、本案をフル実装で本番へ反映しました（backend収集まで含む）。

### Backend
- `collector.py`: `_user_payload` に **avatar** 追加（`_image_url` で ImageModel/room_info両対応）。配信者 **owner**（表示名/avatar）をsnapshotへ。Battleを **battle_idごと** に保持（自陣/敵陣score・個人/チーム判定・相手・時刻/duration・実弾Gift貢献(side/diamonds)・勝敗）。`battles_snapshot()` と WS `battles` 配信。simulationもBattle詳細データを生成。`battle_points` は従来通り自陣合算（既存testは非破壊）。
- `storage.py`: `battles` テーブル + `save_battles`/`battles_for_session`、`events.user_avatar` migration、summary/gifterにavatar、`streamer_history_stats(unique_id, limit)` で過去配信比較（gifts/diamonds/comments/視聴Peak[buckets由来]/duration の前回/平均/自己Best）。
- `server.py`: `GET /api/monitors/{uid}/battles`・`/history-stats`、session詳細に `battles` 同梱、`GET /api/sessions/{id}/battles`、`GET /battle` route。

### Frontend
- 監視 `index.html`/`app.js`: スリムtopbar + 概況内包tab + 3カラム(LIVE Preview最大化 / STATS+TIMELINE / 活動ログ) + 高密度stat + 過去配信比較表 + segment活動ログ(Gift/Comment/Event/Battle/Ranking)。
- 全体監視 `overview.html`/`overview.js`: 集計バー + 高密度tile(縦長9:16最大化) + 並替・一括映像/音声。
- 履歴 `history.html`/`history.js`: KPIバー + 絞込/並替/CSV + Excel的多列一覧 + 行選択でSession別Gift/💎増減グラフ + 詳細modal(Memo/録画/Timeline/Result/Battle)。
- Battle詳細 `battle.html`/`battle.js`: battleごとのscore bar・個人/チーム・相手・実弾Gift貢献(自陣/敵陣)・勝敗。
- 共通 `common.js`: `userCell`（avatar+表示名+@id、URL欠落時はイニシャル）。`style.css` にAFTER系クラスを追加（固定px不使用）。

### データ実現性に伴う仕様確定
- 実弾Gift貢献は `BattleUserArmy.diamond_score`（💎）を表示。**Gift個数は当該eventに含まれない**ため列を設けない（捏造しない）。
- avatar CDN URLは失効/ホットリンク制限があり得るため、URL不在/失敗時は**イニシャル表示**に確定（Fallback値は埋めない）。
- 検証: `tests/test_collector.py` 全pass、simulationモードでの実機描画（監視/全体監視/履歴/Battle）と 画面→API→DB のbattle/avatar/比較フロー疎通を確認。
- 設定ページは現状維持（本案対象外）。

## 9. 配信者分析ページ（Streamer Profile / cross-session 集約）

履歴が個別Session単位のみで、配信者をまたいだ集約ビューが無かったため、`unique_id` 単位で全Sessionを束ねる分析ページを追加（nav tab「配信者」）。新規収集は行わず、既存DB(`sessions`/`events`/`battles`)の再集約で実現。

### Backend
- `storage.py`: `streamer_index()`（配信者一覧 + 通算coin/gift/comment/配信回数 + 最新owner identity）、`streamer_profile(unique_id, limit)`（通算/平均/自己Best、Session別系列、横断gifter[出現Session数=ロイヤリティ]、収益集中度[Top1/5/10比率・固定ファン(2回+)/一見]、Battle成績[勝敗・勝率・平均自陣/敵陣Score・対戦相手別W/L・Battle時間窓内のコイン比率]）。
- `server.py`: `GET /streamers` route、`GET /api/streamers`、`GET /api/streamers/{uid}/profile`（収集中Sessionは collector のlive statsで totals/average/best を再集約）。

### Frontend（master-detail 1ページ）
- `streamers.html`/`streamers.js`: 左=配信者リスト（検索/コイン順）、右=選択配信者の集約。通算KPIバー + Session別推移（既存 `createSessionTrendChart` 再利用）+ **時間帯ヒートマップ(後述)** + Gifter/収益分析（集中度chip + 横断gifter表）+ Battle分析（成績chip + 対戦相手別表）。
- 全ページ nav に「配信者」追加。`style.css` に `.sm-*` / `.hm-*`（固定px不使用、flex/clamp/%）追加。
- 共通部品（`userCell`/`renderTableRows`/`fmtCompact`/`connectWS`）再利用。WS `stats`/`battles` で選択中配信者をlive貼り替え。

### 時間帯ヒートマップ（bucket時系列ベース）
- 当初の「配信開始時刻へ全コインを帰属させる近似」を廃止し、`buckets` テーブル（`start`+各metric）を `(曜日, 時刻)` で集計する正確版へ強化。長時間配信は実際に発生した各時間帯へコイン/Comment/配信秒数が正しく分散される。
- `storage.streamer_profile` に `heatmap`(=`[{dow,hour,diamonds,comments,active_seconds}]`) を追加。`strftime('%w'/'%H', start, 'unixepoch', 'localtime')` でserver集計。本アプリはlocalhost運用（server=browser同一TZ）のため画面のbrowser-local表示と一致する。
- Frontend: 色の指標を **コイン / 配信時間 / Comment** で切替（`#sm-hm-metric`）。`active_seconds>0` のセル（配信実績あり）のみ着色し、選択指標が0でも薄く塗る。凡例(`.hm-legend`)に最大値を表示。
- 注: 収集中Sessionのbucketはfinalize時に永続化されるため、heatmapは終了済みSessionが対象（live反映はSession終了後）。

### 任意ID分析の判断
- TikTokLiveはevent駆動（room_idは配信中のみ取得可）で **過去遡及は不可**。「未登録IDの一時監視」は現状の監視開始と技術的に同一のため独立機能化は見送り（将来、監視追加時の「一時監視」option 1つで対応可能）。

## 10. 配信者分析ページ 追加分析（エンゲージメント・コホート・ハイライト）

§9の配信者プロファイルへ、3種の分析を追加。いずれも既存DBの再集約で実現。

### エンゲージメント正規化指標
- `totals`（viewers=各SessionのPeak同接総和、duration=総配信秒）から **コイン/Peak視聴・Comment/Peak視聴・コイン/時間・Comment/時間** をfrontend算出（`renderEngagement`）。規模の異なる配信者を公平比較。live overlayでtotalsを再集約するため収集中も反映。

### ファン継続率（月次コホート）
- `storage.streamer_cohort(unique_id)`: gift eventを `strftime('%Y-%m', ..., 'localtime')` で月次集計。各月の **Active / 新規(初回gift月) / 復帰・継続 / 前月継続率(=前月gifter∩当月 / 前月gifter)** を返す。
- `server.py`: `GET /api/streamers/{uid}/cohort`。Frontend: 新規/復帰を積み上げ棒(Gifter数) + 前月継続率を折れ線(%)で1枚に（`createCohortChart`）+ 月次表。

### ハイライト自動抽出（コイン急増点）
- `storage.streamer_highlights(unique_id, session_limit=50, top=15)`: 各Sessionのコインbucketで **z-score≥2 の外れ値** を急増点として検出し、Session毎の最大spikeを採用、全Sessionから上位を返す（時刻・平常比・z・Comment・録画カバー有無 `has_recording`）。
- `server.py`: `GET /api/streamers/{uid}/highlights`。Frontend: 日時/Session/瞬間コイン/平常比/Comment/録画 の表。
- 性能: bucket全走査のため、コホート/ハイライトは **手動選択時のみ** 取得し、収集中のWS live更新では profile のみ軽量再取得（`selectStreamer(uid, light)`）。
## 11. 成長トレンド & ハイライト録画 deep-link

### 成長トレンド指標
- 共有部品 `createSessionTrendChart(canvas, opts)` に `opts.movingAvg`（コイン移動平均線・左軸・既定off）を追加。既存呼び出し（履歴）は非破壊。`movingAverage()` は末尾基準SMA。配信者ページは `movingAvg:true`。
- `renderGrowth(sessions)`: 直近7日/30日のコイン合計と前週比/前月比をchip表示（増=ok色/減=warn色）。基準は現在時刻（直近に配信が無ければ減少として正直に表示）。frontend算出。

### ハイライト → 録画 deep-link
- `storage.streamer_highlights` が急増点をカバーする録画の `recording_id` と `offset`(=急増時刻−録画開始秒)を返す。
- `server.py`: `GET /api/recordings/{id}/play`（`FileResponse`、Rangeヘッダ対応で `<video>` がseek可能）。
- Frontend: ハイライト表の録画列を「▶ 再生」buttonにし、再生モーダル(`#sm-video-modal` / `<video>`)で `loadedmetadata` 後に `currentTime=offset` へseekして再生。
- 検証: 録画開始基準で offset 換算（spike base+120s → offset 120s）を実DBで確認。

## 12. AI活用（ローカルAI主体）

方針: **ローカル量子化モデル主体**（RTX 4070 Ti/12GB）。Provider/Model/EndpointはConfig化しhard-codeしない。Fallback禁止（未設定/未到達は「無効」と明示し偽結果を返さない）。

### 推奨モデル（12GB・量子化）
- コメント分析(LLM): Qwen2.5-7B-Instruct Q4_K_M(≈4.7GB) ／ 日本語特化 Llama-3-ELYZA-JP-8B Q4_K_M(≈5GB)。Ollama等のOpenAI互換serverで提供。
- 文字起こし(STT): faster-whisper large-v3-turbo(float16/int8 ≈1.5–2GB) ／ 日本語精度 kotoba-whisper-v2.x(CTranslate2 int8)。

### コメント感情・トピック分析（実装済み）
- `config.py`: `TICTOK_AI_ENABLED`(既定0) / `TICTOK_AI_BASE_URL`(既定 `http://127.0.0.1:11434/v1`=Ollama) / `TICTOK_AI_MODEL`(既定空・必須) / `TICTOK_AI_API_KEY` / `TICTOK_AI_TIMEOUT_SECONDS` / `TICTOK_AI_COMMENT_SAMPLE`(既定300)。
- `ai_analysis.py`: OpenAI互換 `/chat/completions` へ `httpx` で接続（追加重依存なし）。コメント群を1回のchatで分析しJSON(`sentiment`/`mood`/`topics`/`highlights`)を抽出。```json フェンスや前後proseも頑健に抽出。無効/未設定/未到達/不正JSONは `AIError`。
- `storage.session_comments()` / `server.py`: `GET /api/ai/status`、`GET /api/sessions/{id}/comment-analysis`（503でAIError詳細を返す）。
- Frontend(履歴詳細modal): 「AI コメント分析」section。statusでmodel表示/無効時はbutton無効化。結果はsentiment帯・mood・話題(share/例)・ハイライトで描画。
- 検証: 無効/JSON抽出/未到達 の各pathを単体確認（偽結果を返さないこと、StackTrace記録を含む）。

### 配信者AI講評（実装済み）
- `ai_analysis.analyze_streamer(data)`: 配信者の集約profileを基に強み/課題/改善提案をJSON生成（`summary`/`strengths`/`issues`/`advice`）。コメント分析と同じhttpx/OpenAI互換経路を再利用。
- `server.py`: `GET /api/streamers/{uid}/ai-review`。**生eventは送らず**、profileを圧縮した要約(通算/平均/自己ベスト/収益集中度/Battle成績/上位gifter/稼ぐ時間帯top)のみLLMへ渡す。
- Frontend(配信者ページ): 「AI 講評」section。status連動でbutton有効/無効、結果はsummary＋強み/課題/改善提案で描画。配信者切替時にreset。
- 検証: 無効path/JSON抽出を単体確認。

### 文字起こし（STT・実装済み）
- ライブラリ: **faster-whisper**（CTranslate2, GPU）。**optional依存**（lazy import）で、未導入でも基本アプリは動作（`transcription.py`）。requirements.txtにコメントで導入手順記載。
- `config.py`: `TICTOK_STT_ENABLED`(既定0) / `TICTOK_STT_MODEL`(既定 large-v3-turbo) / `TICTOK_STT_DEVICE`(auto) / `TICTOK_STT_COMPUTE_TYPE`(auto→cuda時float16/cpu時int8) / `TICTOK_STT_LANGUAGE`(ja) / `TICTOK_STT_BEAM_SIZE`。device/computeはautoでCUDA有無を検出。modelはConfig化・hard-codeなし。
- 単位/保存: **録画単位・DBキャッシュ**。`transcripts` table(recording_id PK, FK ON DELETE CASCADE)に text/segments/language/model/duration を保存。再生成不要。録画削除でcascade削除。
- `server.py`: `GET /api/stt/status`、`GET /api/recordings/{id}/transcript`(cache)、`POST /api/recordings/{id}/transcribe`(実行→保存)。処理は `asyncio.to_thread` でblockingを退避、segmentデコードの進捗を WS `transcribe_progress` で配信。
- Frontend(履歴詳細modalの録画行): STT有効時のみ「文字起こし」button。既存があれば表示、無ければ実行(WS進捗をbtnに%表示)→ `#transcript-modal` で時刻付きsegment一覧表示。
- Fallback禁止: 無効/未導入/model読込失敗/処理失敗は全て `STTError`→503で明示。
- 検証: 無効/未導入/status/DBキャッシュ/録画削除cascade を単体確認（GPU実機はuser側）。

### 文字起こし × 録画 時刻同期（実装済み）
- transcript modalに `<video>`(Range対応 `/api/recordings/{id}/play`)を埋め込み。**segment行クリック/Enterでその開始時刻へseek＋再生**。
- 再生中は `timeupdate` で対応segment(start≤現在時刻 の最後)を `.active` 強調＋追従scroll。STTの結果が録画の頭出しナビとして機能する。
- 検証: segment検索ロジック(各時刻→正しいindex)を単体確認。

## 13. 全体解析ページ（Cross-Streamer Analytics / 配信者横断集計）

§9-11 の配信者ページは全て `unique_id` 単位（縦の集約）。本節は **監視配信者を横断した集約（横の集約）** を扱う新tab「全体解析」。新規データ収集は行わず、既存DB(`buckets`/`events`/`battles`/`sessions`/`users`)の再集約のみで実現。母集団のサンプル数を各所に明示し、一時的な上振れ/下振れに結論を左右されない**統計的に頑健な**設計とする。

### 統計方針（ノイズ対策・全画面共通）
- **中央値 + IQR帯(P25–P75)** を基本指標に採用（平均/spikeに引っ張られない）。
- **レート正規化**（/稼働分・/同接）で配信規模差を吸収し公平比較。
- **within-session正規化 → 配信横断で中央値**：各配信を自分の平均で割ってから束ねるので、大型配信1本が全体を支配しない。
- **サンプル数 n の明示**。閾値未満のセル/点は淡色化し、少数で断定しない。
- **Spearman順位相関**を主指標に（外れ値・非線形に頑健）。
- **期間フィルタ**（直近7/30/90日/全期間）で母集団を明示制御。
- bucketは活動時に生成される＝オンライン時間の代理。稼働秒 ≈ bucket数 × `bucket_seconds`。

### A. 時間帯インデックス（Time-of-Day Index）※中核
- 「どの時間帯に入室が多いか」に直答。**各配信の平均レートを1.0**とし、時間帯ごとの相対倍率(1.2/1.4…)で表す（統計でいう季節性指数/day-part index）。生の合計でなく **within-session正規化レートの配信横断中央値** なので規模差・外れ値に強い。
- **指標切替**: 入室 / コメント / ギフト💎 / いいね / フォロー。
- **平日 / 休日 の切り分け**: 休日 = 土日 + **祝日**(`jpholiday`)。平日系列と休日系列を並置し「休日は昼が伸びる」等の差を可視化。祝日判定は `jpholiday`(業界標準・pure-python・Win/Linux両対応)を採用しhard-code回避。未導入時は `holidays_available=false` を返し **休日=土日のみ** と明示(Fallbackで偽装しない)。
- **縦レイアウト**: 24時刻を**縦(行)**に並べた**横棒**。基準線1.0、超過=右(暖色)/下回り=左(寒色)の diverging。横に24本並べる従来ヒートマップより狭幅でも読める。各行に n を併記。

### B. 入室 × 他指標の関連
- 「入室と他(コメント/ギフト/いいね/フォロー)の関連が分かる」ことを主目的。
- **Spearman相関行列**(色付きテーブル): 入室/コメント/ギフト/いいね/フォロー/同接の相互相関を bucket単位で算出。
- **リード-ラグ**: 入室に対する各指標の相互相関を遅れ±k bucketで算出し折れ線化。どの指標が入室に先行/追従するかを判定。

### C. Battle 影響分析
- 「バトル中の入室」に直答。Battle窓内 vs 平常(窓外)のレートを**同一session内ペア比較**し、入室/ギフト/コメント/フォローの**上昇率(中央値+IQR)**を横棒で表示。within-session比較なので配信規模差が自動でキャンセルされる。

### D. 入室の質（新規 / 常連）
- 入室数だけでなく「誰が来ているか」。入室者のうち **初見率**（`users.first_seen` が当該session開始以降＝我々が初めて観測）を時間帯別に。新規入室と常連入室のインデックスを比較。

### E. 規模 vs 効率マップ
- 散布図: 1点=配信者、x=平均同接(規模)、y=同接あたりコイン(効率)、バブル=配信回数。配信者ごとに中央値集約で頑健化。象限で位置づけ。

### F. 入室 → 定着（retention）
- 「入室しても抜けるか」。時刻別に入室数(棒)と平均同接(線)を素で並べ、入室が伸びても同接が上がらない時間帯＝「入っても抜けている」を目視する。純増(Δ)の散布図は同接線の傾きと重複するため廃止。全体の定着効率は stick rate(=Σ純増/Σ入室)を1数値のヘッダ指標として併記(配信間比較用)。実データでは stick rate ≈ 0.18(大半が入れ替わり)。

### G. ギフト / コメント集中度（Gini / Lorenz）
- 「上位N%のgifter/commenterが全体の何%か」。identity_key単位でgiftコイン/Comment数を集計し、**Gini係数・Lorenz曲線・上位N%シェア(1/5/10/25/50%)** を算出。実データでは gift Gini≈0.97(上位1%=約59%)、comment Gini≈0.92。

### H. 入室のコンテキスト別（Battle / 平時）
- Battle窓内 vs 平時の入室数・秒・**分あたりレート**。実データでは Battle中は平時の約2.1倍の速さで入室。
- **コラボ(非BattleのLinkMic)は現状未収集**。collectorは `LinkMicBattle*` のみ購読で、`LinkStateEvent`/`LinkMicMethodEvent`(接続/切断)を扱っていないため、コラボ窓のデータがDBに無い。3分類(Battle/コラボ/平時)にはcollectorへLinkMic接続窓の収集追加が必要(別途)。捏造しないため現状は2分類＋UIに明示。

### Backend / Frontend
- `storage.py`: `analytics_summary` / `analytics_time_index` / `analytics_relations` / `analytics_battle_uplift` / `analytics_join_quality` / `analytics_scale_efficiency` / `analytics_retention` / `analytics_concentration` / `analytics_join_context`（全て横断再集約）。統計ヘルパー `_median`/`_percentile`/`_spearman`/`_concentration`(Gini/Lorenz)/`_holiday_classifier`。
- `server.py`: `GET /analytics`(page) + `GET /api/analytics/*`。
- `analytics.html`/`analytics.js`: 上記A–Hをsection化。共通部品(`connectWS`/`fmt*`/`userCell`/Chart.js)再利用。全ページnavに「全体解析」追加。`style.css` に `.an-*`(固定px不使用・flex/clamp/%)追加。
- 依存: `requirements.txt` に `jpholiday` 追加。

## 14. コラボ(非BattleのLinkMic)収集方式の調査と提案（未実装・要承認）

§13.H の入室コンテキストを **3分類（Battle / コラボ / 平時）** にするには、コラボ＝非バトルのLinkMic接続窓をDBへ収集する必要がある。現状 collector は `LinkMicBattle*`（PK）のみ購読で、接続/切断そのものを扱っていない。以下は収集方式の調査結果と段階提案（実装は未着手）。

### 調査: 利用可能なevent と field（TikTokLive 6.6.5 proto実測）
- **`LinkLayerEvent`（`WebcastLinkLayerMessage`）＝有力**: `message_type` と content(oneof)を持つ。
  - `create_channel_content`(CreateChannelContent: owner) … コラボchannel開設
  - `finish_content`(FinishChannelContent: owner, finish_reason) … channel終了
  - `join_direct_content`(JoinDirectContent: joiner, **all_users**) … guest参加＋現在の全参加者
  - `leave_content`(LeaveContent: left_user, leave_reason) / `kick_out_content`(KickOutContent: left_user) … 退出/kick
  - `list_content`(**LinkListChangeContent: list_change_type, user_list**) … 参加者rosterの権威的スナップショット
- **`LinkStateEvent`（`WebcastLinkStateMessage`）＝補強**: `channel_id` / `scene` / `layout` / **`user_states`**(現在の接続者) / `state_type`。状態snapshotとしてrosterを裏取り。
- **`LinkMicMethodEvent`（`WebcastLinkMicMethod`）＝補助**: `m_type` / `channel_id` / `duration` / `start_time_ms` / `rival_anchor_id`。invite/PK寄り。

### 推奨する窓の定義（捏造なし・確定可能ロジック）
- **コラボ窓** = LinkMic channelが開いており guest≥1 の区間。判定は roster（`user_list`／`all_users`／`user_states`）のサイズ。開始 = CreateChannel または roster≥2、終了 = FinishChannel または roster<2。
- **Battle** はコラボ窓の部分区間（channel中にPKが発生）。既存の battle 窓を差し引いて「**コラボ（接続中・非Battle）**」を得る。
- 結果の3分類: **Battle** / **コラボ**（接続中だが非Battle）/ **平時**（非接続）。入室速度(件/分)で比較。

### 未確定点（実測が必要）
- `message_type` のenum実値、`user_list`/`all_users` 要素(LinkUser)の構造と **host識別**（owner=監視配信者）。
- これらeventが監視host roomで**安定発火するか**（roomが送るか次第。受信保証はない）。

### 段階提案
- **Phase 1（診断・低risk・storage/UI不変）＝実装済み**: collector の listener＋sampler登録表（`collector.py` の `_capture_sample` 表）に `LinkLayerEvent`/`LinkStateEvent`/`LinkMicMethodEvent`/`LinkLayoutEvent` を追加。`sample_capture`（既定ON）で実コラボ発生時に `samples/*.jsonl` へ生値を蓄積する。合成コラボeventでcapture経路を検証済み（`create_channel_content.owner.uid`＝host、`list_content.user_list.linked_list`＝roster が期待どおり直列化）。あとは**実コラボの生サンプル待ち**で「未確定点」を実値確定する。
- **Phase 2（実装）＝実装済み**: `collector` が `LinkLayerEvent` を購読し、content(create/finish/list/join)からコラボ窓を検出（host=`_owner_id`除外でguest数、message_typeは使わない）。新table `collab_windows(session_id, channel_id, start, end, guests_max, data_json)` へ session finalize時に保存。`analytics_join_context` を **Battle / コラボ / 平時 の3分類**へ拡張（session単位で battle区間・collab区間を構築し、collabからbattleを差し引いて純コラボ区間を得て、各join eventを区間所属で分類）。UIは3バー＋「コラボ未検出」注記。simulation がコラボ窓を `_on_link_layer` 経由で生成。
- **proto実測で確定済みの構造（実サンプルで確認済み）**: `WebcastLinkLayerMessage` = `channel_id` ＋ 通常フィールド(oneofではない)。`create_channel_content.owner`(Player: uid,room_id) / `finish_content.owner`+`finish_reason` / `list_content.user_list`(AllListUser: `linked_list`=接続中roster、各要素 LinkLayerListUser: `link_user`(Player: uid),`link_mic_id`) / `join_direct_content`(joiner, all_users)。host = owner.uid（=監視配信者 `_owner_id`）。**`message_type` は当てにならない**（TikTokが番号使い回し・ANCHOR_REMINDER等に誤decode）ため content有無で判定。
- **検証**: (1) `_on_link_layer` 単体（create→roster→finishで guests_max=1 の窓生成、host-in-rosterはguest0）、(2) collab窓をDB注入して `analytics_join_context` が3分類で保存量を保存（total_joins不変・battle不変・normal→collabへ正しく移動）、(3) endpoint疎通。simulation の擬似コラボ窓は force-kill だとfinalize未実行で保存されない（graceful停止が必要）点に注意。

### 状態
Phase 1（診断capture）＋ Phase 2（コラボ窓収集・3分類）を実装・検証済み。**実配信では次回のサーバ再起動＋実コラボ終了後に `collab_windows` が貯まり、全体解析の「入室のコンテキスト別」が3バー（Battle/コラボ/平時）になる**。残る不確実性は「実roomでのroster埋まり方」で、host-in-roster等はguest数に影響し得るが窓の時間帯集計は成立する（Phase 1 captureで継続確認）。

## 15. organic 入室推定（ノイズ除去した時間帯別の関心）※実証検証済み・未実装

§13.A（時間帯インデックス）は「生の入室」を時間帯別に見る。しかし生入室には **宝箱による外国勢の流入・フレアカード/ポータブル等の露出boost・share直後のバースト・付けたて期のシェア初速** といった、配信者本来の関心とは無関係なノイズが混じる。本節は「これらを除いた **organic（本来の関心）な時間帯カーブ**」を推定する設計と、その **実行可能性を実配信データで実証した結果** を記す。§13.D（新規/常連）・§13.F（定着）の信号を拡張・合成して用いる。

### 推定対象の定式化（フィルタでなく分解）
入室は時刻付きの点過程。最善の枠組みは「ノイズ窓を消す」のではなく、到着強度を **λ(t) = μ(t)（organic背景）＋ Σ 誘発項（share/boost/farmer波）** と**分解**し背景 μ(t) を取り出すこと。統計的には **自己励起点過程（Hawkes process）** の immigration（自然発生＝organic）と offspring（誘発）の分離に対応する。宝箱・フレア・ポータブルの発火時刻が不明でも、説明のつかないバーストは励起項に吸収され μ(t) が脱バースト後の素の関心として残る。

### 15.1 実証検証（実データで確認済み）
最も session 数の多い配信者（owner `81514481538` / 30 sessions / 入室者 8,158 / 2026-06-17〜07-04）で、主要信号の実在と分離効果を検証した。**可視化レポート（Artifact）**: `https://claude.ai/code/artifact/570b6b05-25da-4d4f-a8f1-c6f949669b40`（検証用スクリプトは scratchpad、本番実装ではないため未commit）。

| 検証項目 | 結果 | 判定 |
|---|---|---|
| identity紐付け | join の `identity_key` 100%（`user_id` 89%） | ✅ 基盤OK |
| 再訪コアの実在 | ≥2 sessions = 19%（1,552人、最大21回の裾） | ✅ 分離あり |
| engagement信号 | 入室後に何か発話/反応する人 8.4%（91.6%は無反応） | ✅ 疎だが実在 |
| **Negative control** | 初訪でengagementした人は将来 **39.5%** 再訪 / 無反応は **18.2%** → **2.17倍**（非循環の独立検証） | ✅ 署名が本物を予測 |
| **収束的妥当性** | gift時間帯との相関: 生入室 **0.830** → 再訪入室 **0.930** / comment 0.805 → 0.928 | ✅ 実勢へ接近 |
| share反応窓 | share後60秒の入室は baseline の **2.92倍**（ピークは約3.6倍） | ✅ 交絡が測定可能 |
| stick-rate（joins↔Δ同接） | 集計で **45.9%** だが bucket平均0.64入室と疎で per-bucket判定は不能 | ⚠️ 要粗粒度化 |

**要点**: (1) 初訪engagementが将来再訪を2.17倍予測＝farmer/drive-byと本物を**行動署名で分離できる**（国籍情報ゼロで達成）。(2) クリーン化が時間帯カーブの形を**14時の生スパイク（14.3%→9.7%）を縮め、夜22–01時＝本物の日本時計を持ち上げる**方向に動かし、gift/commentの実勢と一致（0.83→0.93）。(3) share交絡は明確に測定可能。**結論：実行可能。**

**検証で判明した設計変更**: stick-rate は既存 bucket 粒度では疎すぎ per-bucket で機能しない。**per-minute / 5-min への再集計**が必要（集計値は妥当なので方式変更のみ）。また share反応窓は**share前から入室が高い**＝shareは賑わい時に押される傾向があり、単純な「share後の引き算」は過剰帰属になる。回帰/Hawkesでの分離が要る。

### 15.2 設計（層別）
- **L0 特徴量**: 各 `join` に「再訪か（`first_seen`差 / 過去session出現）・後続engagement有無・実効dwell（同一identityの最終活動−入室、退室eventが無いため近似）・`fans_level`/`gifter_level`/badge・anonymous・share反応窓内か・battle/collab窓内か」を付与。
- **L1 質モデル**: 入室者を「本物の視聴者 / farmer・drive-by / share誘発」の**潜在クラス混合**で推定し、ハード除外でなく **genuineness weight w∈[0,1]** を付与（無言lurkerの誤判定を避ける）。
- **L2 バースト帰属**: Hawkes＋変化点検知で各バーストを share誘発/boost/farmer波に footprint 分類し、organic と誘発を分解。
- **L3 強度モデル**: 週×時間帯の**円周スプライン**（23時と0時は隣接なので circular basis）＋日次ランダム効果＋account-age（付けたて）＋battle/collab共変量の**階層Bayesian負の二項**を weight 付き入室に当て、organic λ(時間帯,曜日) を信用区間付きで得る（過分散のため Poisson でなく NB）。
- **L4 検証・監視**: 下記15.5の妥当性チェックと drift 監視。

### 15.3 ブラッシュアップ点（§13.A/D/F に対する上積み）
- **Hawkes（自己励起）分解**で未観測交絡（宝箱/フレア/ポータブル）をバースト側へ追い出す。
- **PU learning（Positive-Unlabeled）**: 正例（高 `fans_level`/`gifter_level`/badge/複数session再訪の固定客）は取れ、負例（farmer）はラベル無し＝典型的PU問題。固定客を正例アンカーに weight を較正。
- **潜在クラス混合**で farmer 層を国籍情報なしに行動署名（超短dwell・無engagement・再訪ゼロ・バースト到着）から教師なし推定。
- **joins↔Δ同接(`m_total`)↔累積(`total_user`) 突合**: per-user退室が無くても「100入室で同接+10なら90即抜け＝farmer波」を集計 stick-rate で検知・減点（要 per-minute 粗粒度化）。
- **ハード判定→ソフト weight** で情報を捨てない。
- **円周基底＋曜日交互作用＋日次ランダム効果**（ブースト日は切片で吸収しスケール差を消す）。
- **battle/collab を共変量**に投入（既存 `battles`/`collab_windows` を活用）し、PK・コラボ由来の入室急増を organic 時間帯と混ぜない。
- **分解の可視化**: 各時間帯を「organic / share誘発 / boost・unknown」の積み上げ＋信用区間で提示し、ノイズが**どれだけ**効いたかを可視化。
- **副次効果**: 本物（≒固定客≒日本）を weight で重視すると、多重タイムゾーン由来の時間帯歪みが自動で日本時計へ寄る。

### 15.4 観測できる交絡 / できない交絡
| 交絡要因 | 直接観測 | 扱い |
|---|---|---|
| share スパイク | ✅ `share` event（時刻+identity） | L2でdeconfound（回帰/Hawkes、単純引き算不可） |
| 付けたて（新規シェア初速） | ✅ `users.first_seen`/session順 | account-age 共変量 or 初期N日除外 |
| 宝箱による外国勢流入 | ❌ 宝箱eventは未取得 | 行動署名（L1潜在クラス）で間接分離 |
| フレアカード/ポータブル | ❌ 視聴者側eventを出さない | 検知不能→robust推定でoutlier吸収 |
| 外国勢判定そのもの | ❌ region/language無し | nickname推定は不正確・非採用 |

観測できる交絡＝回帰調整、観測できない交絡＝行動proxy（L1）＋robust推定（L2/L3）。「未観測交絡を差し引く魔法」は無く、**そもそも汚染されにくい指標に変える**（再訪+engagement weight）のが本質的解。

### 15.5 検証方法（ground truth 無しでの担保）
- **収束的妥当性**: organic入室curveは生入室より gift/comment/再訪の時間帯curveと強く相関するはず（実測済: 0.83→0.93）。
- **Negative control**: farmer判定は将来再訪を予測せず、本物判定は予測するはず（実測済: 2.17倍）。
- **安定性**: organic成分は週をまたいで安定・ノイズ成分は非再現。
- **付けたて期 vs 安定期**: 生curveは食い違うが、クリーン化後は一致するはず。

### 15.6 実装順序と逓減点
1. L0特徴量 ＋ joins↔Δ同接突合 ＋ 再訪/engagement/level 合成 weight（ヒューリスティック）→ 既存DBのみで動く。§13.A の隣に「organic入室」系列を追加。**実装済み**。
2. ~~PU learning 質モデル ＋ 潜在混合 → weight をデータ駆動化~~ → **実測により棄却（下記15.8）**。
3. 階層Bayesian（円周×曜日＋battle/collab＋account-age）→ 信用区間付き本命curve。
4. Hawkes分解 ＋ 分解UI → 最上位の厳密さ。
- 逓減は Hawkes と完全Bayesの厳密化（③④は大手以外で余地が小さい＝下記15.8参照）。**①の突合と④の分解UIは費用対効果が高く優先**。

### 15.7 上流のデータ収集改善（要調査・高価値）
現状 **per-viewer 退室を購読していない**ため dwell は集計突合で近似。TikTokLive が viewer leave / member_count delta 等を出せるなら per-user dwell が直接取れ L1/L2 の精度が段違いになる。併せて `total_user`（累積ユニーク）の**時系列delta保存**（現状は最新値のみ `_on_room_user`）で後付けの stick-rate 分析が効く。→ 最善を狙うなら 15.6 の①より前に潰す価値がある。

### 15.8 ②（データ駆動weight）の実測結果 — 棄却
§15.6②「PU learning/潜在クラスで weight をデータ駆動化」を実データで検証した結果、**現行の soft ヒューリスティック weight（①）に勝てず、棄却**する。

- **実験1（PU/予測 logistic, 対象=将来再訪, 特徴=[初訪engagement, level保有, 初訪share窓]）**: 5-fold **AUC=0.552**（偶然≈0.5）。係数の向きは妥当（engaged +1.23 / level +0.78 / **share窓 −0.25＝share流入は本物度が低い**）だが、個人単位の予測力はほぼ無い。学習weightの収束的妥当性 gift相関 **0.847** は、勘の重み(0.908)・再訪のみ(0.930)に劣後。
- **実験2（6配信者×gift相関の頑健性）**: 勝者は配信者で割れ、平均は **raw 0.947 / soft-heuristic 0.955 / returning-only 0.890**。
  - クリーン化が有意に効くのは**大手・高volume・ノイズ多**の配信者のみ（30 sessions で raw 0.830→再訪 0.930）。宝箱/boost で水増しされる主対象がここ。
  - 小規模配信者は raw が既に 0.95+（時間帯の幅が狭く自明に相関）で改善余地が小さく、「再訪のみ」に絞ると母数が痩せ**逆に悪化**（0.66まで低下）。
  - **soft weight（全員を残し重みを下げる）が平均最良かつ graceful**。薄いデータでも崩れない。
- **結論**: 追加モデル（PU/EM）は投資対効果が無い。①の soft weight を維持。唯一の磨き込みは **n（母数）併記＋薄い配信者ではクリーン化を控えめに提示**する UI 側の配慮（新モデル不要）。この判断は「安易な解決策を採用しない／効果を実証してから採用」に合致する（実証が"不要"を示した）。

### 状態
**実行可能性を実配信データで実証済み（未実装）**。主要信号（再訪19%・engagement署名2.17倍・share反応2.92倍・収束的妥当性0.83→0.93）は全て実在・測定可能。既存 `events`/`buckets`/`users`/`battles`/`collab_windows` で L3 まで到達可能で、新規データ収集は不要（退室event購読は最善化の任意上流）。着手は 15.6 の段階順、まず①（合成weight × per-min stick-rate × share窓control）を `analytics_*` に追加し §13.A の隣へ「organic入室」系列として出す。
