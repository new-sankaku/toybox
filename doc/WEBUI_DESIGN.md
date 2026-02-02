# WebUI Design Specification

NieR:Automata風UIデザインシステム。参照実装: `sample_webui/index.html`

## 1. Design Philosophy

**Core Principles:**
- Minimalism: 不要な装飾を排除
- Geometry: 直線・グリッド構成
- Warm Monochrome: ベージュ/セピア基調
- Machine: 機械的・アンドロイド的美学
- Category Colors: 状態を色で即座に識別

**Visual Identity:**
- 明るいベージュ背景 `#E8E4D4`
- ダークヘッダー/フッター `#57534A`
- カテゴリマーカー: 4px縦線で状態色分け
- ダイヤモンドマーカー `◇` でセクション区切り
- 広い字間 letter-spacing 0.1em以上
- 角ばったデザイン border-radius: 0

## 2. Color System

**→ CLAUDE.md の「CSS/デザインルール」セクションを参照**

サーフェスクラス、アクセントカラーの定義はCLAUDE.mdに集約。

### Design Tokens

```css
:root {
  /* Background */
  --bg-main: #E8E4D4;
  --bg-panel: #DAD5C3;
  --bg-selected: #CCC7B5;
  --bg-header: #57534A;
  --bg-footer: #57534A;

  /* Text */
  --text-main: #454138;
  --text-light: #7A756A;
  --text-header: #E8E4D4;

  /* Accent (状態表示) */
  --accent-red: #B85C5C;      /* エラー/Critical */
  --accent-orange: #C4956C;   /* 実行中/Warning */
  --accent-yellow: #C9C078;   /* 待機中/Pending */
  --accent-green: #7AAA7A;    /* 完了/Success */
  --accent-blue: #6B8FAA;     /* 情報/Info */

  /* Border */
  --border-light: rgba(69,65,56,0.2);
  --border-dark: rgba(69,65,56,0.4);

  /* Typography */
  --font-primary: 'Noto Sans JP', sans-serif;
  --letter-spacing-normal: 0.1em;
  --letter-spacing-wide: 0.15em;

  /* Spacing */
  --space-xs: 4px;
  --space-sm: 8px;
  --space-md: 16px;
  --space-lg: 24px;
  --space-xl: 32px;

  /* Transitions */
  --transition-fast: 150ms ease;
  --transition-normal: 300ms ease;

  /* Z-Index */
  --z-dropdown: 100;
  --z-modal: 200;
  --z-toast: 300;
}
```

## 3. Typography

| Level | Size | 用途 |
|-------|------|------|
| Display | 28px | ページタイトル |
| H1 | 20px | セクション見出し |
| H2 | 16px | カード見出し |
| Body | 14px | 本文 |
| Small | 13px | サブ情報 |
| Caption | 12px | ラベル、タイムスタンプ |

Font weight: 300(本文), 400(見出し), 500(強調)

## 4. Layout Structure

```
┌─────────────────────────────────────────────────────┐
│ HEADER TABS (--bg-header)                           │
│ [MAP] [QUEST] [SYSTEM] [AGENTS] [LOGS] [DATA]       │
├─────────────────────────────────────────────────────┤
│ MAIN CONTENT (--bg-main)                            │
│ ┌──────────────┐  ┌─────────────────────────────┐   │
│ │ LEFT PANEL   │  │ RIGHT PANEL                 │   │
│ │ (List View)  │  │ (Detail View)               │   │
│ │ width: 320px │  │ flex: 1                     │   │
│ └──────────────┘  └─────────────────────────────┘   │
├─────────────────────────────────────────────────────┤
│ FOOTER (--bg-footer) メッセージ / 操作ガイド        │
└─────────────────────────────────────────────────────┘
```

## 5. Components

### 5.1 Panel / Card

- 背景: `--bg-panel`
- ヘッダー: `--bg-header` + `--text-header`
- ボーダー: `1px solid var(--border-light)`
- border-radius: 0

### 5.2 List Item with Category Marker

```
┌─┬────────────────────────────────────┬────┐
│▌│ Item Name                          │ 67%│
└─┴────────────────────────────────────┴────┘
 ↑ Category Marker (4px×16px)
```

Marker色: running=orange, pending=yellow, complete=green, error=red

### 5.3 Progress Bar

- height: 8px
- 背景: `--border-light`
- Fill: `--text-main`

### 5.4 Checkpoint Alert Card

- ヘッダー背景: `--accent-red`
- 待機時間を赤文字で表示
- ボタン: APPROVE / REQUEST CHANGES / REJECT

## 6. Metrics Display

### Agent Metrics Panel

表示項目:
- 実行時間 / 推定残り時間 / 推定終了時刻
- トークン使用量 (Agent/累計/推定総量)
- 進捗 (完了タスク/総タスク, プログレスバー)
- アクティブサブAgent数

### Task Queue Display

グループ表示: 実行中(n) / 待機中(n) / 完了(n)
各タスクは List Item with Category Marker 形式

## 7. Output Viewers

| Type | 機能 |
|------|------|
| Document | Markdown preview/raw切替、メタ情報表示 |
| Code | シンタックスハイライト、行番号、Copy/Diff |
| Asset | 画像プレビュー、音声プレイヤー、ダウンロード |
| Test Results | Pass Rate、結果テーブル、失敗詳細 |

## 8. Error Handling UI

### Error Categories

| カテゴリ | 例 |
|----------|-----|
| CONNECTION | WebSocket切断、サーバー接続失敗、タイムアウト |
| LLM | API呼び出し失敗、レート制限、トークン上限 |
| AGENT | タスク失敗、依存関係エラー、タイムアウト |
| STATE | 状態同期失敗、チェックポイント保存失敗 |
| USER | 入力バリデーション、権限エラー |

### Error Display Components

- **Inline Error**: フィールド下に赤ボーダー+メッセージ
- **Toast**: 右上に5秒表示、Category Marker付き
- **Error Panel**: 詳細表示+対処方法+アクションボタン

### Connection Status Indicator

ヘッダー右上に常時表示:
- `●` Connected (green)
- `◐` Reconnecting... (orange, 点滅)
- `○` Disconnected (red)

切断時はオーバーレイで再接続状況を表示

## 9. Resilience & Recovery

### Connection Recovery Flow

1. WebSocket切断検知
2. 自動再接続試行 (Exponential Backoff: 1s→2s→4s...)
3. 5回失敗 → 手動再接続ボタン表示
4. 成功 → 状態同期 → 正常動作

### State Persistence Indicator

フッター左側に常時表示:
- 最終保存時刻
- 自動保存ON/OFF
- 保存状態 (◉保存済み/◐保存中/⚠失敗)

## 10. Page Layouts

### Dashboard (Main View)

4パネル構成:
- プロジェクト情報
- フェーズ進捗
- メトリクス
- 承認待ち一覧
- アクティブAgent一覧

### Agent Detail View

- Agent基本情報 (ステータス、進捗)
- トークン/時間メトリクス
- 現在のタスク詳細
- サブAgent一覧
- Agentログ (フィルタ付き)

### Human Checkpoint Review

- Agent情報、待機時間
- 出力プレビュー (RAW/PREVIEW切替)
- フィードバック入力
- 承認ボタン群

## 11. Animations

| アニメーション | トリガー | Duration |
|---------------|----------|----------|
| Fade In | ページ読み込み | 300ms |
| Panel Slide | パネル開閉 | 300ms |
| Progress Fill | 進捗更新 | 300ms |
| Status Pulse | 実行中状態 | slow pulse |
| Error Flash | エラー発生 | 100ms |

## Appendix: Assets

**Fonts:** Noto Sans JP (weight: 300, 400, 500)

**Icons (Unicode):**
- Diamond: `◇`
- Status: `●` `◐` `○` `✓` `✕` `⚠`
- Tab: `⊞` `✦` `⚙` `⚔` `◈` `☰`
