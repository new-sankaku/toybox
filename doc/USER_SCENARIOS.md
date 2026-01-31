# ユーザーシナリオ一覧

## 画面構成

| # | 画面 | 概要 |
|---|------|------|
| 1 | ProjectView | プロジェクト作成・編集・実行制御 |
| 2 | AgentsView | エージェント進捗・ログ確認 |
| 3 | CheckpointsView | 出力レビュー・承認/却下/修正依頼 |
| 4 | LogsView | システムログ表示・フィルタリング |
| 5 | TraceView | LLM呼び出しトレース・トークン確認 |
| 6 | DataView | 生成アセット承認・ダウンロード |
| 7 | InterventionView | エージェントへの介入指示 |
| 8 | ConfigView | AI設定・自動承認・コスト・出力設定 |
| 9 | AIView | エージェント動作の2Dビジュアル |
| 10 | CostView | コスト追跡・予算管理 |

## 1. ProjectView - プロジェクト管理

### レイアウト

左パネル: プロジェクト一覧 [更新][+新規作成]
右パネル: 状態により変化 (未選択時→メッセージ / 新規作成→フォーム / 選択時→詳細+実行コントロール)

### シナリオ

| # | シナリオ | 操作 | API |
|---|----------|------|-----|
| 1 | 新規作成 | +ボタン→フォーム入力→作成 | POST /api/projects |
| 2 | 選択 | 行クリック→詳細表示 | - |
| 3 | 編集 | 鉛筆アイコン→フォーム編集→保存 | PATCH /api/projects/{id} |
| 4 | 削除 | ゴミ箱アイコン（即削除） | DELETE /api/projects/{id} |
| 5 | 開始 | 開始ボタン (draft時のみ) | POST /api/projects/{id}/start |
| 6 | 一時停止 | 一時停止ボタン (running時) | POST /api/projects/{id}/pause |
| 7 | 再開 | 再開ボタン (paused時) | POST /api/projects/{id}/resume |
| 8 | 停止 | 停止ボタン→draft状態に | PATCH /api/projects/{id} |
| 9 | 初期化 | 初期化ボタン→確認ダイアログ→全リセット | POST /api/projects/{id}/initialize |
| 10 | ブラッシュアップ | completed時→対象Agent選択→再実行 | POST /api/projects/{id}/brushup |
| 11 | 一覧更新 | 更新アイコン | GET /api/projects |

### 新規作成フォーム項目

- プロジェクト名（必須）、ゲームアイデア（必須）
- 参考ゲーム、プラットフォーム、スコープ、プロジェクト規模
- AIサービス設定（カテゴリ別）
- アセット自動生成、コンテンツ許可
- 初期ファイル（カテゴリ別アップロード）

### 実行コントロールボタン

| ステータス | 表示ボタン |
|-----------|----------|
| draft | 開始, 初期化※ |
| running | 一時停止, 停止 |
| paused | 再開, 停止 |
| completed | ブラッシュアップ, 初期化 |
| failed | 初期化 |

※currentPhase > 1 の場合のみ

## 2. CheckpointsView - 承認管理

### レイアウト

左パネル: チェックポイント一覧（カテゴリ色、タイトル、Agent名、ステータス）
右パネル: 詳細レビュー（出力プレビュー PREVIEW/RAW切替、アクションボタン）

### シナリオ

| # | シナリオ | 操作 | API |
|---|----------|------|-----|
| 1 | 一覧表示 | タブ開く | GET /api/projects/{id}/checkpoints |
| 2 | 詳細表示 | カードクリック | - |
| 3 | 承認 | 承認ボタン（緑） | POST /api/checkpoints/{id}/resolve (approved) |
| 4 | 変更要求 | 変更要求→フィードバック入力→送信 | POST /api/checkpoints/{id}/resolve (revision_requested) |
| 5 | 却下 | 却下ボタン（赤）→理由入力→送信 | POST /api/checkpoints/{id}/resolve (rejected) |
| 6 | 表示切替 | PREVIEW/RAWボタン | - |

## 3. DataView - アセット管理

### レイアウト

左パネル: フィルタ（タイプ、承認状態、表示モード）
右パネル: アセット一覧（グリッド/リスト）

### シナリオ

| # | シナリオ | 操作 | API |
|---|----------|------|-----|
| 1 | 一覧表示 | タブ開く | GET /api/projects/{id}/assets |
| 2 | タイプフィルタ | ラジオボタン選択 | - |
| 3 | 承認状態フィルタ | ラジオボタン選択（デフォルト: 未承認） | - |
| 4 | 表示切替 | グリッド/リストボタン | - |
| 5 | 承認 | ✓ボタン | PUT /api/.../assets/{id}/status?status=approved |
| 6 | 却下 | ✗ボタン | PUT /api/.../assets/{id}/status?status=rejected |
| 7 | 詳細表示 | カードクリック→モーダル | - |
| 8 | 音声再生 | ▶ボタン | - |
| 9 | ダウンロード | ダウンロードボタン | GET /api/assets/{id}/download |

## 4. LogsView - システムログ

### レイアウト

左パネル: ログ一覧 [時刻][レベル][ソース]メッセージ
右パネル: フィルタ（検索、レベル、エージェント）+ 統計

### シナリオ

| # | シナリオ | 操作 |
|---|----------|------|
| 1 | 一覧表示 | タブ開く (GET /api/projects/{id}/logs) |
| 2 | レベルフィルタ | ラジオボタン (全て/error/warn/info/debug) |
| 3 | Agentフィルタ | ドロップダウン（複数選択可） |
| 4 | テキスト検索 | 検索ボックス入力（リアルタイム） |
| 5 | 詳細表示 | ログ行クリック→FloatingPanel |

## 5. TraceView - トレース追跡

### レイアウト

ヘッダー: [自動更新][更新][全展開][全閉][削除]
左パネル: トレース一覧（展開可能）
右パネル: フィルタ（ステータス）+ 統計

### シナリオ

| # | シナリオ | 操作 |
|---|----------|------|
| 1 | 一覧表示 | タブ開く (GET /api/projects/{id}/traces) |
| 2 | ステータスフィルタ | ラジオボタン |
| 3 | 展開/折りたたみ | ▶/▼アイコン |
| 4 | 全展開/全閉 | ヘッダーボタン |
| 5 | 詳細表示 | 「詳細を表示」→FloatingPanel |
| 6 | 自動更新 | ボタンON→3秒間隔更新 |
| 7 | 手動更新 | 更新ボタン |
| 8 | 削除 | 削除ボタン→確認→全削除 (DELETE /api/.../traces) |

## API一覧

### Projects
| メソッド | エンドポイント | 説明 |
|----------|---------------|------|
| GET/POST | /api/projects | 一覧/作成 |
| PATCH/DELETE | /api/projects/{id} | 更新/削除 |
| POST | /api/projects/{id}/start | 開始 |
| POST | /api/projects/{id}/pause | 一時停止 |
| POST | /api/projects/{id}/resume | 再開 |
| POST | /api/projects/{id}/initialize | 初期化 |
| POST | /api/projects/{id}/brushup | ブラッシュアップ |

### Checkpoints
| メソッド | エンドポイント | 説明 |
|----------|---------------|------|
| GET | /api/projects/{id}/checkpoints | 一覧 |
| POST | /api/checkpoints/{id}/resolve | 解決 |

### Assets
| メソッド | エンドポイント | 説明 |
|----------|---------------|------|
| GET | /api/projects/{id}/assets | 一覧 |
| PUT | /api/projects/{id}/assets/{id}/status | 状態更新 |
| GET | /api/assets/{id}/download | ダウンロード |

### Logs / Traces
| メソッド | エンドポイント | 説明 |
|----------|---------------|------|
| GET | /api/projects/{id}/logs | ログ取得 |
| GET | /api/projects/{id}/traces | トレース一覧 |
| DELETE | /api/projects/{id}/traces | トレース全削除 |
