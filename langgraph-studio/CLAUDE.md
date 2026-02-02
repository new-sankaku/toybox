## スタイル修正の正しい手順
- まず `tailwind.config.cjs` の色定義を確認
- 次に `src/styles/index.css` のCSS変数を確認
- 問題があれば設定ファイルを修正
- コンポーネントではTailwindクラスを使用

## エージェント定義ルール
- **エージェント名はサーバー側で一元管理** - エージェントの表示名（label, shortLabel）はバックエンド（`backend/agent_settings.py`の`AGENT_DEFINITIONS`）で定義し、APIで提供する。フロントエンドでハードコーディングしない。

## UI/UXルール
- **暗い背景上のテキストには明示的な色指定** - `bg-nier-bg-header` や `bg-nier-bg-panel` などの暗い背景を持つ要素内のテキストには、必ず `text-nier-text-main` や `text-nier-text-light` 等の明示的な文字色クラスを指定すること。デフォルトの文字色に頼らないこと。
- **カラー絵文字の使用禁止** - 📋、🔍、⚡、✓、✗ などのカラー絵文字は使用禁止。アイコンが必要な場合は Lucide React のフラットカラーアイコンを使用すること。
- **リスト/表形式の列位置揃え** - 複数行のリストや表形式の表示では、上下の行で列位置を揃えること。CSS Gridの固定幅カラム（例: `grid-cols-[4px_160px_1fr_100px_auto]`）を使用して、各列の開始位置を統一する。

## 表示設定ルール
- **行間（line-height）のデフォルト値** - 行間のデフォルト値は `1.4` とする。CONFIG画面では `0.2` から `2.5` の範囲で調整可能。
- **余白（padding/margin）は現状維持** - カードやセクションの余白は現在の設定を維持すること。CONFIG画面での余白調整は `0px` から `15px` の範囲。
- **表示設定の適用** - 行間と余白の設定は `ConfigView.tsx` で管理し、CSS変数（`--leading-base`, `--padding-card` 等）を通じて全体に適用される。
- **フィルタ順序** - フィルタボタンは「全て」を先頭に配置すること。

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

