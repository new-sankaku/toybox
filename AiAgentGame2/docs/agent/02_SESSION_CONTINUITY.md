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

```
projects/
└── {project_id}/
    ├── project.json              # プロジェクト基本情報
    └── sessions/
        └── {session_id}/
            ├── state_checkpoint.json # 機械可読な完全状態
            ├── approaches.json       # アプローチ記録（全種別統合）
            ├── remaining_tasks.json  # 残作業リスト
            └── artifacts/            # このセッションの成果物
```

## DBスキーマ

### sessionsテーブル

```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    parent_session_id TEXT,
    started_at TIMESTAMP NOT NULL,
    ended_at TIMESTAMP,
    interruption_reason TEXT,
    current_phase INTEGER,
    current_agent_role TEXT,
    current_agent_type TEXT,
    current_task_id TEXT,
    context_summary TEXT,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);
```

### human_approvalsテーブル

```sql
CREATE TABLE human_approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    checkpoint_type TEXT NOT NULL,
    leader_id TEXT NOT NULL,
    status TEXT NOT NULL,  -- pending, approved, rejected, revision_requested
    submitted_at TIMESTAMP NOT NULL,
    resolved_at TIMESTAMP,
    feedback TEXT,
    instruction_content TEXT,  -- LEADERの指示内容
    worker_instructions JSON,  -- WORKERへの指示（JSON配列）
    artifacts JSON,            -- 生成物のパス（JSON配列）
    revision_history JSON,     -- 修正履歴（JSON配列）
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);
```

### tasksテーブル

```sql
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    phase INTEGER NOT NULL,
    task_type TEXT NOT NULL,
    status TEXT NOT NULL,  -- pending, in_progress, completed, failed, blocked
    progress_percent INTEGER DEFAULT 0,
    assigned_to TEXT,
    depends_on JSON,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    result JSON,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);
```

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

## 状態ファイル

### state_checkpoint.json

```json
{
  "schema_version": "1.0",
  "project_id": "proj_20240115_a1b2c3",
  "session_id": "sess_20240115143000_x1y2z3",
  "timestamp": "2024-01-15T16:45:00Z",
  "interruption_reason": "connection_error",

  "current_state": {
    "phase": 2,
    "active_agent": {
      "role": "LEADER",
      "type": "code",
      "agent_id": "leader_code"
    },
    "active_task": {
      "task_id": "task_p2_code_003",
      "name": "PlayerController実装",
      "progress_percent": 70
    }
  },

  "completed_tasks": [
    {"task_id": "task_p1_concept_001", "status": "approved"},
    {"task_id": "task_p1_design_001", "status": "approved"}
  ],

  "pending_tasks": [
    {"task_id": "task_p2_code_003", "status": "in_progress", "progress": 70},
    {"task_id": "task_p2_asset_001", "status": "blocked", "blocked_by": "task_p2_code_003"}
  ],

  "remaining_tasks": [
    {"task_id": "task_p2_code_004", "status": "pending"},
    {"task_id": "task_p2_code_005", "status": "pending"}
  ],

  "context_summary": "ゲーム企画完了、開発フェーズでPlayerController実装中。ジャンプ機能にバグあり修正中。"
}
```

## アプローチ記録

### approaches.json

Agentが動作するためのデータなので、機械可読なJSON形式で保存。

```json
{
  "schema_version": "1.0",
  "session_id": "sess_20240115143000_x1y2z3",
  "last_updated": "2024-01-15T16:45:00Z",

  "verified": [
    {
      "id": "approach_001",
      "date": "2024-01-15",
      "category": "concept_generation",
      "description": "ユーザー入力「2Dアクションゲーム」から3案生成",
      "details": {
        "method": "各案に独自性スコアを付与",
        "parameters": {"案数": 3}
      },
      "evidence": {
        "type": "human_approval",
        "approval_id": 123,
        "comment": "2案目が良い"
      },
      "learnings": [
        "案は3つ程度が適切（多すぎると選択困難）",
        "独自性スコアは判断材料として有効"
      ],
      "reusable": true
    },
    {
      "id": "approach_002",
      "date": "2024-01-15",
      "category": "state_management",
      "description": "TypedDictベースの状態管理",
      "details": {
        "method": "LangGraphのAnnotatedで差分更新"
      },
      "evidence": {
        "type": "test_result",
        "test_file": "test_state.py",
        "passed": 5,
        "failed": 0
      },
      "learnings": [
        "Annotatedを使うと差分更新が楽"
      ],
      "reusable": true
    }
  ],

  "failed": [
    {
      "id": "approach_f001",
      "date": "2024-01-15",
      "category": "jump_implementation",
      "description": "単純なvelocity.y設定でジャンプ",
      "details": {
        "method": "直接velocity.yを設定"
      },
      "failure_reason": "地面判定なしで空中ジャンプ可能になった",
      "error": "無限ジャンプバグ",
      "learnings": [
        "地面判定（is_grounded）を先に実装すべき"
      ],
      "avoid": true
    },
    {
      "id": "approach_f002",
      "date": "2024-01-15",
      "category": "asset_generation",
      "description": "5つのアセットを同時に生成依頼",
      "details": {
        "parallel_count": 5
      },
      "failure_reason": "API rate limit超過",
      "error": "429 Too Many Requests",
      "learnings": [
        "並列度は3以下に制限すべき"
      ],
      "avoid": true
    }
  ],

  "untried": [
    {
      "id": "approach_u001",
      "category": "jump_implementation",
      "description": "Raycastによる地面判定",
      "details": {
        "method": "足元にRayを飛ばして地面検出"
      },
      "priority": "high",
      "next_to_try": true
    },
    {
      "id": "approach_u002",
      "category": "jump_implementation",
      "description": "Collider接触判定",
      "details": {
        "method": "OnCollisionEnterで地面タグ判定"
      },
      "priority": "medium",
      "next_to_try": false
    },
    {
      "id": "approach_u003",
      "category": "jump_implementation",
      "description": "CharacterControllerのisGrounded使用",
      "details": {
        "method": "Unity標準機能を使用"
      },
      "priority": "low",
      "next_to_try": false,
      "note": "カスタマイズ性が低い"
    }
  ]
}
```

## 再開フロー

### 1. 新セッション開始

```python
def resume_session(project_id: str, session_id: str) -> Session:
    """
    中断したセッションを再開する
    """
    # DBから状態を取得
    db_state = db.query_session(session_id)
    db_approvals = db.query_approvals(session_id)

    # JSONファイルから詳細を取得
    session_path = Path(f"projects/{project_id}/sessions/{session_id}")
    state = load_json(session_path / "state_checkpoint.json")
    approaches = load_json(session_path / "approaches.json")

    # 新しいセッションID生成
    new_session_id = generate_session_id()

    # コンテキスト構築
    context = build_resume_context(state, approaches)

    # 新セッションをDBに登録
    db.create_session(
        id=new_session_id,
        project_id=project_id,
        parent_session_id=session_id
    )

    return Session(
        session_id=new_session_id,
        parent_session=session_id,
        resume_context=context,
        remaining_tasks=state["remaining_tasks"]
    )
```

### 2. コンテキスト構築

```python
def build_resume_context(state: dict, approaches: dict) -> str:
    """
    再開用のコンテキストを構築する
    """
    # 失敗アプローチをフォーマット
    failed_approaches = format_approaches(approaches["failed"])

    # 成功アプローチをフォーマット
    verified_approaches = format_approaches(approaches["verified"])

    # 次に試すアプローチをフォーマット
    untried_approaches = [a for a in approaches["untried"] if a.get("next_to_try")]

    context = {
        "previous_state": state["context_summary"],
        "current_phase": state["current_state"]["phase"],
        "current_task": state["current_state"]["active_task"],
        "failed_approaches": failed_approaches,
        "verified_approaches": verified_approaches,
        "next_approaches": untried_approaches,
        "remaining_tasks": state["remaining_tasks"]
    }

    return context
```

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

### 再開ボタン
- プロジェクト一覧に「再開」ボタンを表示
- 中断セッションがある場合のみ有効

### セッション履歴
- 過去のセッション一覧を表示
- 各セッションの状態要約を閲覧可能

### 承認履歴
- DBから承認履歴を取得して表示
- 承認/却下/修正依頼のステータス確認

### API エンドポイント

| メソッド | パス | 説明 |
|---------|------|------|
| GET | /projects/{id}/sessions | セッション一覧 |
| GET | /projects/{id}/sessions/{sid} | セッション詳細 |
| POST | /projects/{id}/sessions/{sid}/resume | セッション再開 |
| GET | /projects/{id}/approvals | 承認履歴 |
