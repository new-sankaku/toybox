# プロジェクトルール

## 用語定義

- **Agent**: AIエージェント（concept_leader, design_workerなど）。独立した実行単位。1つのAgentは特定の役割を持つ。
- **Task**: Agentが実行する個別の作業単位。1つのAgentが複数のTaskを実行することがある。AgentとTaskは別物であり、混同しないこと。

## 禁止事項

- **nulファイルの作成禁止** - Windowsで出力を破棄する場合、`> nul` を使用しない（`nul`という名前のファイルが作成されてしまう）。代わりに `> /dev/null 2>&1` を使用するか、出力リダイレクトを使わない。
- **応急処置の禁止** - インラインスタイル（`style={{ }}`）でのべた書きは禁止。必ずTailwindクラスまたはCSSファイルを使用すること。
- **動作確認なしの大量変更禁止** - 複数ファイルを一度に変更する前に、1ファイルずつ動作確認すること。
- **既存コンポーネントの破壊禁止** - Card, CardHeader等の既存UIコンポーネントを使わずに書き換えることは禁止。
- **推測での修正禁止** - 「たぶんこれだろう」で修正を始めない。必ず問題の要素を特定してから修正すること。
- **同じ調査の繰り返し禁止** - 同じ問題が再度発生した場合、前回と同じ視点で調査しない。別の観点（親要素、子要素、関連コンポーネント、CSS継承、Tailwind設定など）から調べ直すこと。
- **不要なコメント禁止** - コードを見れば分かる内容のコメントは書かない。コメントは以下の場合のみ許可:
  - 複雑なロジックの意図説明（なぜそうしたか）
  - 外部仕様やAPIの制約事項
  - TODO/FIXME（一時的なもの）
  - 型定義やインターフェースのJSDoc
- **誤認させるデフォルト値禁止** - API取得失敗時などに、実際とは異なる値をデフォルト値として画面に表示しない。取得失敗時は「-」や空欄、または「取得失敗」等の明示的な表示にすること。ユーザーを誤認させる情報を表示してはならない。

## スタイル修正の正しい手順

- まず `tailwind.config.cjs` の色定義を確認
- 次に `src/styles/index.css` のCSS変数を確認
- 問題があれば設定ファイルを修正
- コンポーネントではTailwindクラスを使用

## CSS問題のデバッグ手順

- **問題の要素を特定** - どのコンポーネントの、どの部分か明確にする
- **コンポーネントを読む** - 該当するTSXファイルを開き、使用しているclassNameを確認
- **CSS定義を確認** - `index.css`で該当クラスの定義を読む
- **継承関係を追跡** - 親要素の色設定も確認する
- **それから修正** - 原因を特定してから初めてコードを変更する

## データ表示ルール

- **ログはDESC順で統一** - 全てのログ表示（エージェントログ、システムログ等）は新しいものが上に来るようにDESC（降順）で並べること。

## エージェント定義ルール

- **エージェント名はサーバー側で一元管理** - エージェントの表示名（label, shortLabel）はバックエンド（`backend/agent_settings.py`の`AGENT_DEFINITIONS`）で定義し、APIで提供する。フロントエンドでハードコーディングしない。
- **表示名の取得方法** - フロントエンドでは`useAgentDefinitionStore`を使用して表示名を取得する。
  ```typescript
  const { getLabel, getShortLabel } = useAgentDefinitionStore()
  const fullName = getLabel('concept')       // → 'コンセプト'
  const shortName = getShortLabel('concept') // → 'コンセプト'
  ```
- **新しいエージェントの追加手順**:
  - `backend/agent_settings.py`の`AGENT_DEFINITIONS`に追加
  - フロントエンドは自動的に新しい定義を取得する（コード変更不要）
- **使用するラベルの選択**:
  - 通常の画面: `getLabel()` でフル表示名を使用
  - スペースが限られる場所（アイコン下、小さいカード等）: `getShortLabel()` で短縮名を使用

## UI/UXルール

- **暗い背景上のテキストには明示的な色指定** - `bg-nier-bg-header` や `bg-nier-bg-panel` などの暗い背景を持つ要素内のテキストには、必ず `text-nier-text-main` や `text-nier-text-light` 等の明示的な文字色クラスを指定すること。デフォルトの文字色に頼らないこと。
- **モーダル/ダイアログでのアクション後は閉じる** - 承認・却下などのアクションボタンをクリックした後は、ダイアログを自動的に閉じること。
- **カラー絵文字の使用禁止** - 📋、🔍、⚡、✓、✗ などのカラー絵文字は使用禁止。アイコンが必要な場合は Lucide React のフラットカラーアイコンを使用すること。
- **リスト/表形式の列位置揃え** - 複数行のリストや表形式の表示では、上下の行で列位置を揃えること。CSS Gridの固定幅カラム（例: `grid-cols-[4px_160px_1fr_100px_auto]`）を使用して、各列の開始位置を統一する。

## 表示設定ルール

- **行間（line-height）のデフォルト値** - 行間のデフォルト値は `1.4` とする。CONFIG画面では `0.2` から `2.5` の範囲で調整可能。
- **余白（padding/margin）は現状維持** - カードやセクションの余白は現在の設定を維持すること。CONFIG画面での余白調整は `0px` から `15px` の範囲。
- **表示設定の適用** - 行間と余白の設定は `ConfigView.tsx` で管理し、CSS変数（`--leading-base`, `--padding-card` 等）を通じて全体に適用される。

## 共通CSSクラス

- **スクロールリスト** - リストやグリッドのスクロール表示には `index.css` で定義された共通クラスを使用すること。個別にmax-heightやoverflowを指定しない。
  - `nier-scroll-list`: 標準のスクロールリスト（`max-height: calc(100vh - 280px)`）
  - `nier-scroll-list-short`: 短いスクロールリスト（`max-height: 300px`）
- **ページヘッダー** - 全ビューのページタイトルは `index.css` の共通クラスで統一構造を使用すること。
  ```html
  <div className="nier-page-header-row">
    <div className="nier-page-header-left">
      <h1 className="nier-page-title">TITLE</h1>
      <span className="nier-page-subtitle">- サブタイトル</span>
    </div>
    <div className="nier-page-header-right">
      <!-- 右側の部品がある場合 -->
    </div>
  </div>
  ```
  - `nier-page-header-row`: 外側コンテナ（`flex items-baseline justify-between mb-3`）
  - `nier-page-header-left`: 左側（`flex items-baseline gap-2`）
  - `nier-page-header-right`: 右側（`flex items-center gap-2`）ボタン等
  - `nier-page-title`: タイトル（`text-nier-h1 font-medium tracking-nier-wide`）= 20px
  - `nier-page-subtitle`: サブタイトル（`text-nier-small text-nier-text-light`）= 13px
- **グリッド/スペース** - 要素間の余白は統一すること。
  - グリッドギャップ: `gap-3`
  - リスト間隔: `space-y-3`
- **フィルタ順序** - フィルタボタンは「全て」を先頭に配置すること。
- **ボタンサイズ** - Buttonコンポーネントのサイズは以下の通り。ヘッダー等の狭いスペースでは `size="sm"` を使用すること。
  - `default`: h-8 (32px)、px-4、text-nier-small
  - `sm`: h-7 (28px)、px-3、text-nier-small
  - `lg`: h-10 (40px)、px-6、text-nier-body
- **ボタン色の視認性** - 全てのボタンは「明るい背景 + 暗い文字」で統一する。暗い背景に明るい文字のパターンは視認性問題が繰り返し発生するため禁止。
  - `default`: 明るい背景、薄いボーダー(border-light)、暗い文字
  - `primary`: 明るい背景、濃いボーダー(border-dark)、暗い文字、font-medium で区別
  - `secondary`: 明るい背景、薄いボーダー(border-light)、薄い文字(text-light) → hover時にtext-main
  - `danger/success`: 明るい背景、色付きボーダー、色付き文字 → hover時に反転
- **アイコン色の統一** - アイコンは役割に応じて色を使い分ける。
  - **装飾的アイコン**: `text-nier-text-light` で統一（Cpu, Clock, FolderOpen等、意味を伝えないアイコン）
  - **機能的アイコン**: 状態や意味に応じた色を使用（ステータスアイコン、警告アイコン等）
  - 一覧画面で複数のアイコンがカラフルに並ぶとゴチャゴチャするため、装飾目的のアイコンは全て `text-nier-text-light` に統一すること
- **背景色の視認性** - 暗い背景（`bg-nier-bg-header`, `bg-nier-bg-main`）は極力使用しない。
  - グリッドのサムネイル、モーダル内のコード表示等は `bg-nier-bg-selected` または `bg-nier-bg-panel + border` を使用
  - どうしても暗い背景が必要な場合は、必ず `text-white` 等の明示的な文字色を指定すること

### カラールール

**色に頼らないデザイン** - ステータスや状態を色だけで区別しない。文字ラベルで明確に表現すること。

**使用可能な色:**
- **基本**: `text-nier-text-main`（メインテキスト）、`text-nier-text-light`（サブテキスト）
- **アクセント（限定使用）**:
  - `text-nier-accent-orange` / `bg-nier-accent-orange` - 淡い赤橙。警告、重要な操作、ハイライト
  - `text-white` - ごく一部（ボタンホバー時の反転等）
  - `text-nier-accent-green` / `bg-nier-accent-green` - ごく一部（成功メッセージ等）

**禁止:**
- ステータス表示での色分け（running=緑、paused=オレンジ等）→ 全て `text-nier-text-light` で統一
- 青色（`accent-blue`）の使用
- 色だけで意味を伝えるデザイン

- **文言の統一** - 画面に表示する文言（ラベル、ボタン、メッセージ等）は他の画面と統一的な表現にすること。新しい文言を追加する前に、既存の画面で使われている表現を確認して合わせる。
  - **ステータス表示**: `下書き`/`実行中`/`一時停止`/`完了`/`エラー` で統一（全画面共通）
  - **ボタンラベル**: `作成`/`編集`/`削除`/`保存`/`キャンセル`/`開始`/`停止`/`再開`/`初期化`
  - **新規作成**: 「新規〇〇作成」の形式（例: 新規プロジェクト作成）
  - **確認ダイアログ**: 「〇〇しますか？」の形式
  - **エラーメッセージ**: 「〇〇に失敗: {詳細}」の形式
  - **空状態**: 「〇〇がありません」の形式
  - **件数表示**: 「N件」の形式（例: 3件）
  - **Agent名**: コード内のAgent ID（`concept_leader`, `design_worker`等）と画面表示名は統一すること。新しいAgentを追加する場合は、既存の命名規則（`{role}_{type}`形式）に従う
- **画面デザインの統一** - 新しい画面や機能を追加する際は、既存の画面と統一されたデザインにすること。部品の有無によってレイアウトが崩れないよう注意する。
  - **既存画面の確認**: 新しい画面を作る前に、類似の既存画面（一覧画面、詳細画面、フォーム画面等）を確認してレイアウト構造を合わせる
  - **ヘッダー構造の固定**: ページヘッダーは `nier-page-header-row` を使用し、右側にボタンがない場合も `nier-page-header-right` の空divを配置してレイアウトを維持する
  - **カード構造の統一**: Card + CardHeader + CardContent の構造を守る。CardHeaderには必ず DiamondMarker を使用する
  - **グリッドレイアウトの統一**: 2カラム構成は `grid-cols-3` で左1:右2、3カラム構成は `grid-cols-3` で均等分割など、既存パターンに従う
  - **空状態の表示**: データがない場合も同じレイアウト構造を維持し、中央に「〇〇がありません」メッセージとアクションボタンを表示する
  - **条件付き表示の注意**: ボタンやアイコンを条件で表示/非表示にする場合、非表示時もスペースを確保するか、親要素のレイアウトに影響しないことを確認する
- **動的な画面構成** - 拡張性を持たせるため、画面構成は動的にすること。ハードコーディングを避け、データ駆動で画面を構築する。
  - **リスト/テーブル**: カラム定義を配列で管理し、マップで描画する
  - **フォーム**: フィールド定義を配列/オブジェクトで管理し、動的に生成する
  - **ナビゲーション**: メニュー項目を設定ファイルや定数で管理する
  - **フィルタ/タブ**: 選択肢をハードコーディングせず、データから生成する
  - **新しい項目の追加**: コードの複数箇所を修正せずに、定義を1箇所追加するだけで画面に反映されるようにする

## Three.js ルール

このプロジェクトではThree.js 0.182.0（npm版）を使用している。`public/sample/`にあるHTMLファイルはThree.js r128（CDN版）を使用している。

### バージョン間の色の違い

Three.js r152以降で以下の変更があり、r128と同じコードでも色がくすんで見える：

- **カラーマネジメントがデフォルトで有効** - sRGB↔リニア変換が自動で行われる
- **ライティング計算が物理的に正確（physically correct）になった** - 同じライト強度でも暗く見える

### r128と同じ色を再現するための設定

- **main.tsxでカラーマネジメントを無効化**（Colorインスタンス作成前に設定必須）:
  ```typescript
  import * as THREE from 'three'
  THREE.ColorManagement.enabled = false
  ```
- **レンダラーの出力カラースペースを設定**:
  ```typescript
  renderer.outputColorSpace = THREE.LinearSRGBColorSpace
  ```
- **ライト強度を上げる**（r128の約3倍）:
  ```typescript
  // r128: AmbientLight(0xffffff, 0.6), DirectionalLight(0xffffff, 0.8)
  // r182: AmbientLight(0xffffff, 2.0), DirectionalLight(0xffffff, 2.0)
  ```

### 注意事項

- Sampleファイル（`public/sample/*.html`）のコードをReactに移植する際は、上記の設定を必ず適用すること
- 色が黒い/くすんでいる場合、まずライト強度を確認すること
- gradientMapは不要（r128でも使っていない）
