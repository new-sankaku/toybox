# LangGraph Studio API仕様

## 概要

| プロトコル | 用途 |
|-----------|------|
| WebSocket (Socket.IO) | リアルタイム通信・状態更新 |
| REST API | CRUD操作・初期データ取得 |

## 1. WebSocket API (Socket.IO)

### Server → Client イベント

| カテゴリ | イベント | 主要フィールド |
|---------|---------|---------------|
| Agent | agent:started | agentId, agentType, projectId |
| Agent | agent:progress | agentId, progress(0-100), currentTask, completedTasks, totalTasks |
| Agent | agent:completed | agentId, duration(ms), tokensUsed, outputSummary |
| Agent | agent:failed | agentId, errorType, errorMessage, canRetry, retryCount, maxRetries |
| Agent | agent:log | agentId, level, message, metadata |
| Checkpoint | checkpoint:created | checkpointId, projectId, agentId, type, title, outputPreview |
| Checkpoint | checkpoint:resolved | checkpointId, resolution, feedback |
| Project | project:status_changed | projectId, oldStatus, newStatus |
| Project | project:phase_changed | projectId, phase(1-3), phaseName |
| Metrics | metrics:update | projectId, totalTokens, estimatedTotalTokens, elapsedSeconds, estimatedRemainingSeconds, completedTasks, totalTasks |
| Metrics | metrics:tokens | agentId, tokensUsed, tokensTotal |
| Error | error:agent | agentId, errorType, errorMessage, suggestions[], actions[] |
| Error | error:llm | errorType(rate_limit/token_limit/api_error/invalid_response), retryAfter |
| Error | error:state | errorType(sync_failed/checkpoint_failed/restore_failed) |
| Connection | connection:state_sync | projectId, serverState, hasDiff |

### Client → Server イベント

| イベント | ペイロード | 説明 |
|---------|-----------|------|
| subscribe:project | projectId | プロジェクト購読 |
| unsubscribe:project | projectId | 購読解除 |
| subscribe:agent | agentId | Agent購読 (予定) |
| request:state_sync | { projectId } | 状態同期リクエスト (予定) |
| checkpoint:resolve | checkpointId, resolution, feedback | チェックポイント解決 |

## 2. REST API

### Projects API

| メソッド | エンドポイント | 説明 |
|---------|---------------|------|
| GET | /api/projects | 一覧取得 |
| GET | /api/projects/:id | 詳細取得 |
| POST | /api/projects | 作成 |
| PATCH | /api/projects/:id | 更新 |
| DELETE | /api/projects/:id | 削除 |
| POST | /api/projects/:id/start | 開始 |
| POST | /api/projects/:id/pause | 一時停止 |
| POST | /api/projects/:id/resume | 再開 |
| POST | /api/projects/:id/cancel | キャンセル (予定) |

### Agents API

| メソッド | エンドポイント | 説明 |
|---------|---------------|------|
| GET | /api/projects/:projectId/agents | 一覧 |
| GET | /api/agents/:id | 詳細 |
| GET | /api/agents/:id/logs | ログ |
| GET | /api/agents/:id/outputs | 出力 |
| GET | /api/agents/:id/metrics | メトリクス |
| GET | /api/agents/:id/tasks | タスクキュー (予定) |

### Checkpoints API

| メソッド | エンドポイント | 説明 |
|---------|---------------|------|
| GET | /api/projects/:projectId/checkpoints | 一覧 |
| GET | /api/checkpoints/:id | 詳細 |
| POST | /api/checkpoints/:id/resolve | 解決 (approved/rejected/revision_requested) |

### Metrics / Outputs / State / Logs API

| メソッド | エンドポイント | 説明 |
|---------|---------------|------|
| GET | /api/projects/:projectId/metrics | プロジェクトメトリクス |
| GET | /api/outputs/:id | 出力取得 (予定) |
| GET | /api/outputs/:id/preview | プレビュー (予定) |
| GET | /api/outputs/:id/download | ダウンロード (予定) |
| GET | /api/projects/:id/state | 状態取得 (予定) |
| GET | /api/projects/:id/state/diff | 状態差分 (予定) |
| POST | /api/projects/:id/state/sync | 状態同期 (予定) |
| GET | /api/projects/:id/logs | ログ取得 (予定) |

## 3. 接続情報

| 項目 | 値 |
|-----|-----|
| WebSocket URL | ws://localhost:{port} |
| REST API Base URL | http://localhost:{port}/api |
| 再接続最大試行 | 5回 |
| 再接続初期遅延 | 1000ms |
| 再接続最大遅延 | 5000ms |
| 接続タイムアウト | 10000ms |

トランスポート優先順位: WebSocket → Polling (フォールバック)

## 4. 実装ルール

| レイヤー | 役割 |
|---------|------|
| フロントエンド | Viewer のみ（表示専用） |
| バックエンド | ファイル読み書き、Agent実行、状態管理 |

- リアルタイム更新: WebSocket
- CRUD操作: WebSocket (REST APIは将来のWeb版対応用)
- フロントエンドはファイル操作を行わない
