# ログシステムの改良

## 概要

ログをAgent単位、グループ単位、Task単位で閲覧できるようにする。
従来のファイル形式のログに加え、構造化されたログを提供する。

## ログの階層

| パス | 説明 |
|------|------|
| logs/directors/ | DIRECTOR レベル（phase1_director.log等） |
| logs/leaders/ | LEADER レベル（concept_leader.log等） |
| logs/workers/ | WORKER レベル（worker_task_001.log等） |
| logs/tasks/ | タスク単位（横断的） |
| logs/groups/ | グループ単位（集約） |
| logs/combined/ | 全体ログ |

## ログエントリ形式

### 構造化ログ（JSONL）

| フィールド | 説明 |
|-----------|------|
| timestamp | タイムスタンプ |
| level | ログレベル（DEBUG/INFO/WARN/ERROR/FATAL） |
| session_id | セッションID |
| project_id | プロジェクトID |
| agent | エージェント情報（role, type, id） |
| task | タスク情報（id, name, phase） |
| group | グループ |
| message | ログメッセージ |
| details | 詳細情報 |
| metrics | メトリクス（tokens_used, duration_ms, cost_usd） |

### 人間可読ログ（テキスト）

フォーマット例:
`2024-01-15 14:30:00 [INFO] [WORKER:code:worker_task_p2_code_003] [task_p2_code_003] ジャンプ機能の実装を完了`

## ログレベル

| レベル | 用途 | 例 |
|--------|------|-----|
| DEBUG | 詳細なデバッグ情報 | 変数値、内部状態 |
| INFO | 通常の動作情報 | タスク開始/完了 |
| WARN | 警告（動作は継続） | リトライ発生、性能低下 |
| ERROR | エラー（タスク失敗） | 実行エラー、検証失敗 |
| FATAL | 致命的エラー（停止） | システムエラー |

## ログ検索・閲覧

### WebUI ログビューア機能

| 機能 | 説明 |
|------|------|
| フィルタ | Agent種別、グループ、タスクID、時間範囲、レベル |
| 検索 | テキスト検索 |
| リアルタイム | WebSocket経由でリアルタイム更新 |
| エクスポート | JSON/CSV形式でダウンロード |

### APIエンドポイント

| メソッド | パス | 説明 |
|---------|------|------|
| GET | /logs | ログ検索 |
| GET | /logs/stream | リアルタイムストリーム（WebSocket） |
| GET | /logs/export | エクスポート |
| GET | /logs/stats | 統計情報 |

## ログローテーション

### 設定項目

| 設定 | 説明 |
|------|------|
| max_size_mb | 最大ファイルサイズ |
| max_files | 保持するファイル数 |
| compress | 圧縮するかどうか |
| retention_days | 保持日数 |
