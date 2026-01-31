# Backend API Reference

## Projects

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET/POST | `/api/projects` | 一覧取得/作成 |
| PATCH/DELETE | `/api/projects/<id>` | 更新/削除 |
| POST | `/api/projects/<id>/start\|pause\|resume\|initialize\|brushup` | 状態制御 |
| GET/PUT/PATCH | `/api/projects/<id>/ai-services` | AI設定 |

## Agents

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/projects/<id>/agents` | 一覧取得 |
| GET | `/api/agents/<id>/logs` | ログ取得 |

## Checkpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/projects/<id>/checkpoints` | 一覧取得 |
| POST | `/api/checkpoints/<id>/resolve` | 解決 |

## Interventions

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET/POST | `/api/projects/<id>/interventions` | 一覧/作成 |
| GET | `/api/interventions/<id>` | 詳細 |
| POST | `/api/interventions/<id>/acknowledge\|process` | 確認/処理 |

## Metrics & Assets

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/projects/<id>/metrics` | メトリクス |
| GET | `/api/projects/<id>/ai-requests/stats` | AIリクエスト統計 |
| GET | `/api/projects/<id>/logs` | システムログ |
| GET/PATCH | `/api/projects/<id>/assets` | アセット一覧/更新 |

## Files

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET/POST | `/api/projects/<id>/files` | 一覧/アップロード |
| POST | `/api/projects/<id>/files/batch` | バッチアップロード |
| GET/DELETE | `/api/files/<id>` | 詳細/削除 |
| GET | `/api/files/<id>/download` | ダウンロード |

## Project Tree

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/projects/<id>/tree` | ツリー構造 |
| GET | `/api/projects/<id>/tree/download\|download-all` | ダウンロード |
| POST | `/api/projects/<id>/tree/replace` | ファイル置換 |

## Settings

| カテゴリ | エンドポイント |
|---------|---------------|
| Quality | GET/PATCH `/api/projects/<id>/settings/quality-check` |
| Auto Approval | GET/PUT `/api/projects/<id>/auto-approval-rules` |
| Output/Cost | GET/PUT `/api/projects/<id>/settings/output\|cost` |
| AI Providers | GET/PUT `/api/projects/<id>/settings/ai-providers` |
| Defaults | GET `/api/config/output-settings\|cost-settings/defaults` |
| Agent Definitions | GET `/api/agent-definitions` |

## Static Config

| Endpoint | Description |
|----------|-------------|
| `/api/config/models` | モデル設定 |
| `/api/config/project-options` | プロジェクトオプション |
| `/api/config/file-extensions` | ファイル拡張子設定 |
| `/api/config/agents` | エージェント設定 |

## AI Providers & Services

| Endpoint | Description |
|----------|-------------|
| `/api/ai-providers` | プロバイダー一覧/詳細/モデル/テスト |
| `/api/ai/chat\|chat/stream` | チャット実行 |
| `/api/ai-services` | AIサービス一覧/詳細/設定 |
| `/api/config/pricing` | 料金設定 |

## WebSocket Events

| Event | Direction | Description |
|-------|-----------|-------------|
| connect/disconnect | C→S | 接続/切断 |
| subscribe/unsubscribe | C→S | プロジェクト購読 |
| project:updated/status_changed/initialized | S→C | プロジェクト通知 |
| agent:started/progress/completed | S→C | エージェント通知 |
| checkpoint:created | S→C | チェックポイント通知 |
| metrics:update | S→C | メトリクス通知 |
| asset:created | S→C | アセット通知 |
