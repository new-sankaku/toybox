# セッション継続性（処理中断対策）

## 概要

停電やエラーでAgentが中断した場合、最初からやり直さずに途中から再開できる仕組み。
作業をIDで管理し、状態をDBとJSONファイルに保存することで、新しいセッションでファイルパスを提供するだけで継続可能にする。

## データ保存先

| データ種別 | 保存先 | 理由 |
|-----------|-------|------|
| Human承認 | SQLite DB | 永続性、検索性、トランザクション |
| セッション状態 | SQLite DB + JSON | DBがメイン、JSONはバックアップ |
| アプローチ記録 | JSON | Agentが読み書きするため機械可読形式 |
| 成果物 | ファイルシステム | バイナリ含むため |

## フォルダ構造

| パス | 用途 |
|------|------|
| projects/{project_id}/project.json | プロジェクト基本情報 |
| projects/{project_id}/sessions/{session_id}/state_checkpoint.json | 機械可読な完全状態 |
| projects/{project_id}/sessions/{session_id}/approaches.json | アプローチ記録（全種別統合） |
| projects/{project_id}/sessions/{session_id}/remaining_tasks.json | 残作業リスト |
| projects/{project_id}/sessions/{session_id}/artifacts/ | このセッションの成果物 |

## DBスキーマ

### sessionsテーブル

| カラム | 型 | 説明 |
|--------|-----|------|
| id | TEXT | セッションID（主キー） |
| project_id | TEXT | プロジェクトID |
| parent_session_id | TEXT | 親セッションID（再開時） |
| started_at | TIMESTAMP | 開始日時 |
| ended_at | TIMESTAMP | 終了日時 |
| interruption_reason | TEXT | 中断理由 |
| current_phase | INTEGER | 現在のPhase |
| current_agent_role | TEXT | 現在のAgent役割 |
| current_agent_type | TEXT | 現在のAgent種別 |
| current_task_id | TEXT | 現在のタスクID |
| context_summary | TEXT | コンテキスト要約 |

### human_approvalsテーブル

| カラム | 型 | 説明 |
|--------|-----|------|
| id | INTEGER | 自動採番（主キー） |
| session_id | TEXT | セッションID |
| project_id | TEXT | プロジェクトID |
| checkpoint_type | TEXT | チェックポイント種別 |
| leader_id | TEXT | 提出したLEADERのID |
| status | TEXT | pending/approved/rejected/revision_requested |
| submitted_at | TIMESTAMP | 提出日時 |
| resolved_at | TIMESTAMP | 解決日時 |
| feedback | TEXT | フィードバック |
| instruction_content | TEXT | LEADERの指示内容 |
| worker_instructions | JSON | WORKERへの指示（JSON配列） |
| artifacts | JSON | 生成物のパス（JSON配列） |
| revision_history | JSON | 修正履歴（JSON配列） |

### tasksテーブル

| カラム | 型 | 説明 |
|--------|-----|------|
| id | TEXT | タスクID（主キー） |
| session_id | TEXT | セッションID |
| project_id | TEXT | プロジェクトID |
| phase | INTEGER | Phase番号 |
| task_type | TEXT | タスク種別 |
| status | TEXT | pending/in_progress/completed/failed/blocked |
| progress_percent | INTEGER | 進捗率 |
| assigned_to | TEXT | 担当Agent ID |
| depends_on | JSON | 依存タスク（JSON配列） |
| started_at | TIMESTAMP | 開始日時 |
| completed_at | TIMESTAMP | 完了日時 |
| result | JSON | 結果（JSON） |

## ID体系

### Project ID
- 形式: `proj_{timestamp}_{random}`
- 例: `proj_20240115_a1b2c3`
- 用途: プロジェクト全体を識別

### Session ID
- 形式: `sess_{timestamp}_{random}`
- 例: `sess_20240115143000_x1y2z3`
- 用途: 1回の実行セッションを識別
- 生成タイミング: Agent開始時

### Task ID
- 形式: `task_{phase}_{type}_{seq}`
- 例: `task_p1_concept_001`
- 用途: 個別タスクを識別

## 状態ファイル（state_checkpoint.json）

| フィールド | 説明 |
|-----------|------|
| schema_version | スキーマバージョン |
| project_id | プロジェクトID |
| session_id | セッションID |
| timestamp | タイムスタンプ |
| interruption_reason | 中断理由 |
| current_state | 現在の状態（phase, active_agent, active_task） |
| completed_tasks | 完了タスク一覧 |
| pending_tasks | 実行中/ブロック中タスク |
| remaining_tasks | 未着手タスク |
| context_summary | コンテキスト要約 |

## アプローチ記録（approaches.json）

| カテゴリ | 説明 |
|---------|------|
| verified | 成功したアプローチ（Human承認済み、テスト通過など） |
| failed | 失敗したアプローチ（避けるべきもの） |
| untried | 未試行のアプローチ（次に試す候補） |

各アプローチには以下を記録:
- id: アプローチID
- date: 記録日
- category: カテゴリ
- description: 説明
- details: 詳細（method, parameters等）
- evidence: 証拠（approval_id, test_result等）
- learnings: 学び
- reusable/avoid: 再利用可否

## 再開フロー

1. **DBから状態を取得**: session_id を使って sessions, human_approvals, tasks を取得
2. **JSONから詳細を取得**: state_checkpoint.json, approaches.json を読み込み
3. **新セッションID生成**: 新しいセッションを開始
4. **コンテキスト構築**: 失敗アプローチ、成功アプローチ、次に試すアプローチを整理
5. **新セッションをDBに登録**: parent_session_id を設定
6. **残タスクから再開**: remaining_tasks を処理

## 自動保存タイミング

| イベント | 保存先 | 保存内容 |
|---------|-------|---------|
| タスク完了時 | DB + JSON | タスク状態、state_checkpoint.json |
| Human承認時 | DB | human_approvalsテーブル |
| アプローチ記録時 | JSON | approaches.json |
| エラー発生時 | DB + JSON | 全データ + エラー情報 |
| 5分ごと | JSON | state_checkpoint.json（定期バックアップ） |
| セッション終了時 | DB + JSON | 全データ |

## WebUIとの連携

### 機能

| 機能 | 説明 |
|------|------|
| 再開ボタン | 中断セッションがある場合のみ有効 |
| セッション履歴 | 過去のセッション一覧と状態要約 |
| 承認履歴 | DBから承認履歴を取得して表示 |

### API エンドポイント

| メソッド | パス | 説明 |
|---------|------|------|
| GET | /projects/{id}/sessions | セッション一覧 |
| GET | /projects/{id}/sessions/{sid} | セッション詳細 |
| POST | /projects/{id}/sessions/{sid}/resume | セッション再開 |
| GET | /projects/{id}/approvals | 承認履歴 |
