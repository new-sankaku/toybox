# Backend API Reference

## Projects

| Method | Endpoint | Handler | Description |
|--------|----------|---------|-------------|
| GET | `/api/projects` | project.py | プロジェクト一覧取得 |
| POST | `/api/projects` | project.py | プロジェクト作成 |
| PATCH | `/api/projects/<project_id>` | project.py | プロジェクト更新 |
| DELETE | `/api/projects/<project_id>` | project.py | プロジェクト削除 |
| POST | `/api/projects/<project_id>/start` | project.py | プロジェクト開始 |
| POST | `/api/projects/<project_id>/pause` | project.py | プロジェクト一時停止 |
| POST | `/api/projects/<project_id>/resume` | project.py | プロジェクト再開 |
| POST | `/api/projects/<project_id>/initialize` | project.py | プロジェクト初期化 |
| POST | `/api/projects/<project_id>/brushup` | project.py | ブラッシュアップ開始 |
| GET | `/api/projects/<project_id>/ai-services` | project.py | AI設定取得 |
| PUT | `/api/projects/<project_id>/ai-services` | project.py | AI設定一括更新 |
| PATCH | `/api/projects/<project_id>/ai-services/<service_type>` | project.py | AI設定個別更新 |

## Agents

| Method | Endpoint | Handler | Description |
|--------|----------|---------|-------------|
| GET | `/api/projects/<project_id>/agents` | agent.py | エージェント一覧取得 |
| GET | `/api/agents/<agent_id>/logs` | agent.py | エージェントログ取得 |

## Checkpoints

| Method | Endpoint | Handler | Description |
|--------|----------|---------|-------------|
| GET | `/api/projects/<project_id>/checkpoints` | checkpoint.py | チェックポイント一覧取得 |
| POST | `/api/checkpoints/<checkpoint_id>/resolve` | checkpoint.py | チェックポイント解決 |

## Interventions

| Method | Endpoint | Handler | Description |
|--------|----------|---------|-------------|
| GET | `/api/projects/<project_id>/interventions` | intervention.py | 介入一覧取得 |
| POST | `/api/projects/<project_id>/interventions` | intervention.py | 介入作成 |
| GET | `/api/interventions/<intervention_id>` | intervention.py | 介入詳細取得 |
| POST | `/api/interventions/<intervention_id>/acknowledge` | intervention.py | 介入確認 |
| POST | `/api/interventions/<intervention_id>/process` | intervention.py | 介入処理 |

## Metrics & Assets

| Method | Endpoint | Handler | Description |
|--------|----------|---------|-------------|
| GET | `/api/projects/<project_id>/metrics` | metrics.py | メトリクス取得 |
| GET | `/api/projects/<project_id>/ai-requests/stats` | metrics.py | AIリクエスト統計 |
| GET | `/api/projects/<project_id>/logs` | metrics.py | システムログ取得 |
| GET | `/api/projects/<project_id>/assets` | metrics.py | アセット一覧取得 |
| PATCH | `/api/projects/<project_id>/assets/<asset_id>` | metrics.py | アセット更新 |

## Files

| Method | Endpoint | Handler | Description |
|--------|----------|---------|-------------|
| GET | `/api/projects/<project_id>/files` | file_upload.py | ファイル一覧取得 |
| POST | `/api/projects/<project_id>/files` | file_upload.py | ファイルアップロード |
| POST | `/api/projects/<project_id>/files/batch` | file_upload.py | バッチアップロード |
| GET | `/api/files/<file_id>` | file_upload.py | ファイル詳細取得 |
| DELETE | `/api/files/<file_id>` | file_upload.py | ファイル削除 |
| GET | `/api/files/<file_id>/download` | file_upload.py | ファイルダウンロード |
| GET | `/uploads/<project_id>/<filename>` | file_upload.py | ファイル配信 |

## Project Tree

| Method | Endpoint | Handler | Description |
|--------|----------|---------|-------------|
| GET | `/api/projects/<project_id>/tree` | project_tree.py | ツリー構造取得 |
| GET | `/api/projects/<project_id>/tree/download` | project_tree.py | ファイルダウンロード |
| POST | `/api/projects/<project_id>/tree/replace` | project_tree.py | ファイル置換 |
| GET | `/api/projects/<project_id>/tree/download-all` | project_tree.py | 全ファイルダウンロード |

## Settings

### Quality Settings

| Method | Endpoint | Handler | Description |
|--------|----------|---------|-------------|
| GET | `/api/projects/<project_id>/settings/quality-check` | quality_settings.py | 品質設定取得 |
| PATCH | `/api/projects/<project_id>/settings/quality-check/<agent_type>` | quality_settings.py | 品質設定更新 |
| PATCH | `/api/projects/<project_id>/settings/quality-check/bulk` | quality_settings.py | 品質設定一括更新 |
| POST | `/api/projects/<project_id>/settings/quality-check/reset` | quality_settings.py | 品質設定リセット |
| GET | `/api/settings/quality-check/defaults` | quality_settings.py | デフォルト品質設定 |
| GET | `/api/agent-definitions` | quality_settings.py | エージェント定義取得 |

### Auto Approval

| Method | Endpoint | Handler | Description |
|--------|----------|---------|-------------|
| GET | `/api/projects/<project_id>/auto-approval-rules` | auto_approval.py | 自動承認ルール取得 |
| PUT | `/api/projects/<project_id>/auto-approval-rules` | auto_approval.py | 自動承認ルール更新 |

### Project Settings

| Method | Endpoint | Handler | Description |
|--------|----------|---------|-------------|
| GET | `/api/config/output-settings/defaults` | project_settings.py | 出力設定デフォルト |
| GET | `/api/config/cost-settings/defaults` | project_settings.py | コスト設定デフォルト |
| GET | `/api/projects/<project_id>/settings/output` | project_settings.py | 出力設定取得 |
| PUT | `/api/projects/<project_id>/settings/output` | project_settings.py | 出力設定更新 |
| GET | `/api/projects/<project_id>/settings/cost` | project_settings.py | コスト設定取得 |
| PUT | `/api/projects/<project_id>/settings/cost` | project_settings.py | コスト設定更新 |
| GET | `/api/projects/<project_id>/settings/ai-providers` | project_settings.py | AIプロバイダー設定取得 |
| PUT | `/api/projects/<project_id>/settings/ai-providers` | project_settings.py | AIプロバイダー設定更新 |

## Static Config

| Method | Endpoint | Handler | Description |
|--------|----------|---------|-------------|
| GET | `/api/config/models` | static_config.py | モデル設定取得 |
| GET | `/api/config/models/pricing/<model_id>` | static_config.py | モデル料金取得 |
| GET | `/api/config/project-options` | static_config.py | プロジェクトオプション取得 |
| GET | `/api/config/file-extensions` | static_config.py | ファイル拡張子設定取得 |
| GET | `/api/config/agents` | static_config.py | エージェント設定取得 |

## AI Providers

| Method | Endpoint | Handler | Description |
|--------|----------|---------|-------------|
| GET | `/api/ai-providers` | ai_provider.py | プロバイダー一覧取得 |
| GET | `/api/ai-providers/<provider_id>` | ai_provider.py | プロバイダー詳細取得 |
| GET | `/api/ai-providers/<provider_id>/models` | ai_provider.py | モデル一覧取得 |
| POST | `/api/ai-providers/test` | ai_provider.py | 接続テスト |
| POST | `/api/ai/chat` | ai_provider.py | チャット実行 |
| POST | `/api/ai/chat/stream` | ai_provider.py | ストリーミングチャット |

## AI Services

| Method | Endpoint | Handler | Description |
|--------|----------|---------|-------------|
| GET | `/api/ai-services` | ai_service.py | AIサービス一覧取得 |
| GET | `/api/ai-services/<service_type>` | ai_service.py | AIサービス詳細取得 |
| GET | `/api/config/ai-services` | ai_service.py | AIサービス設定取得 |
| GET | `/api/config/ai-providers` | ai_service.py | AIプロバイダー設定取得 |
| GET | `/api/config/pricing` | ai_service.py | 料金設定取得 |

## Languages

| Method | Endpoint | Handler | Description |
|--------|----------|---------|-------------|
| GET | `/api/languages` | language.py | 言語設定取得 |

## Navigator

| Method | Endpoint | Handler | Description |
|--------|----------|---------|-------------|
| POST | `/api/navigator/message` | navigator.py | メッセージ送信 |
| POST | `/api/navigator/broadcast` | navigator.py | ブロードキャスト |

## WebSocket Events

| Event | Direction | Description |
|-------|-----------|-------------|
| `connect` | Client→Server | 接続確立 |
| `disconnect` | Client→Server | 切断 |
| `subscribe` | Client→Server | プロジェクト購読開始 |
| `unsubscribe` | Client→Server | プロジェクト購読終了 |
| `project:updated` | Server→Client | プロジェクト更新通知 |
| `project:status_changed` | Server→Client | ステータス変更通知 |
| `project:initialized` | Server→Client | 初期化完了通知 |
| `agent:started` | Server→Client | エージェント開始通知 |
| `agent:progress` | Server→Client | エージェント進捗通知 |
| `agent:completed` | Server→Client | エージェント完了通知 |
| `checkpoint:created` | Server→Client | チェックポイント作成通知 |
| `metrics:update` | Server→Client | メトリクス更新通知 |
| `asset:created` | Server→Client | アセット作成通知 |
