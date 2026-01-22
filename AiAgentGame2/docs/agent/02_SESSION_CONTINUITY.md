# セッション継続性（処理中断対策）

## 概要

停電やエラーでAgentが中断した場合、最初からやり直さずに途中から再開できる仕組み。
作業をIDで管理し、状態要約ファイルを作成することで、新しいセッションでファイルパスを提供するだけで継続可能にする。

## フォルダ構造

```
projects/
└── {project_id}/
    ├── project.json              # プロジェクト基本情報
    └── sessions/
        └── {session_id}/
            ├── SESSION_STATE.md      # 人間可読な状態要約
            ├── state_checkpoint.json # 機械可読な完全状態
            ├── approaches/
            │   ├── verified.md       # 機能したアプローチ（証拠付き）
            │   ├── failed.md         # 失敗したアプローチ（理由付き）
            │   └── untried.md        # 未試行のアプローチ
            ├── remaining_tasks.json  # 残作業リスト
            └── artifacts/            # このセッションの成果物
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

## 状態要約ファイル

### SESSION_STATE.md（人間可読）

```markdown
# セッション状態要約

## 基本情報
- Project ID: proj_20240115_a1b2c3
- Session ID: sess_20240115143000_x1y2z3
- 開始時刻: 2024-01-15 14:30:00
- 中断時刻: 2024-01-15 16:45:00
- 中断理由: 接続エラー

## 現在位置
- Phase: 2 (開発)
- 実行中Agent: Code LEADER
- 実行中タスク: PlayerController実装

## 完了済み
- [x] Phase1 企画完了
- [x] Concept承認済み
- [x] Design承認済み
- [x] タスク分解完了（全15タスク）

## 進行中
- [ ] task_p2_code_003: PlayerController実装 (70%)
- [ ] task_p2_asset_001: プレイヤー画像生成 (待機中)

## 未着手
- task_p2_code_004 ~ task_p2_code_010
- task_p2_asset_002 ~ task_p2_asset_005

## 再開時の注意
- PlayerControllerのジャンプ機能でバグあり、approaches/failed.md参照
- アセット生成はコード実装後に開始予定
```

### state_checkpoint.json（機械可読）

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

  "human_approvals": [
    {"checkpoint": "concept", "status": "approved", "timestamp": "2024-01-15T15:00:00Z"},
    {"checkpoint": "design", "status": "approved", "timestamp": "2024-01-15T15:30:00Z"}
  ],

  "context_summary": "ゲーム企画完了、開発フェーズでPlayerController実装中。ジャンプ機能にバグあり修正中。"
}
```

## アプローチ記録

### approaches/verified.md（機能したアプローチ）

```markdown
# 機能したアプローチ

## [2024-01-15] Concept生成

### アプローチ
- ユーザー入力「2Dアクションゲーム」から3案生成
- 各案に独自性スコアを付与

### 証拠
- 3案すべてHuman承認取得
- 承認コメント: 「2案目が良い」

### 再利用可能な知見
- 案は3つ程度が適切（多すぎると選択困難）
- 独自性スコアは判断材料として有効

---

## [2024-01-15] State管理実装

### アプローチ
- TypedDictベースの状態管理
- LangGraphのAnnotatedで差分更新

### 証拠
- テスト通過: test_state.py (5/5 passed)

### 再利用可能な知見
- Annotatedを使うと差分更新が楽
```

### approaches/failed.md（失敗したアプローチ）

```markdown
# 失敗したアプローチ

## [2024-01-15] PlayerController ジャンプ実装 (1回目)

### 試したこと
- 単純なvelocity.y設定でジャンプ

### 失敗理由
- 地面判定なしで空中ジャンプ可能になった
- エラー: 無限ジャンプバグ

### 学び
- 地面判定（is_grounded）を先に実装すべき

---

## [2024-01-15] アセット並列生成

### 試したこと
- 5つのアセットを同時に生成依頼

### 失敗理由
- API rate limit超過
- エラー: 429 Too Many Requests

### 学び
- 並列度は3以下に制限すべき
```

### approaches/untried.md（未試行のアプローチ）

```markdown
# 未試行のアプローチ

## PlayerController ジャンプ実装

### 案1: Raycastによる地面判定
- 足元にRayを飛ばして地面検出
- 優先度: 高（次に試す）

### 案2: Collider接触判定
- OnCollisionEnterで地面タグ判定
- 優先度: 中

### 案3: CharacterControllerのisGrounded使用
- Unity標準機能を使用
- 優先度: 低（カスタマイズ性が低い）
```

## 再開フロー

### 1. 新セッション開始

```python
def resume_session(session_path: str) -> Session:
    """
    中断したセッションを再開する
    """
    # 状態ファイル読み込み
    state = load_json(f"{session_path}/state_checkpoint.json")
    approaches = {
        "verified": load_md(f"{session_path}/approaches/verified.md"),
        "failed": load_md(f"{session_path}/approaches/failed.md"),
        "untried": load_md(f"{session_path}/approaches/untried.md"),
    }

    # 新しいセッションID生成
    new_session_id = generate_session_id()

    # コンテキスト構築
    context = build_resume_context(state, approaches)

    return Session(
        session_id=new_session_id,
        parent_session=state["session_id"],
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
    context = f"""
# 再開セッション

## 前回の状態
{state["context_summary"]}

## 現在位置
- Phase: {state["current_state"]["phase"]}
- 実行中タスク: {state["current_state"]["active_task"]["name"]}

## 失敗したアプローチ（避けるべき）
{approaches["failed"]}

## 機能したアプローチ（参考にすべき）
{approaches["verified"]}

## 次に試すべきアプローチ
{approaches["untried"]}

## 残タスク
{format_remaining_tasks(state["remaining_tasks"])}
"""
    return context
```

## 自動保存タイミング

| イベント | 保存内容 |
|---------|---------|
| タスク完了時 | state_checkpoint.json更新 |
| Human承認時 | 全ファイル更新 |
| エラー発生時 | 全ファイル更新 + エラー情報追加 |
| 5分ごと | state_checkpoint.json更新（定期） |
| セッション終了時 | 全ファイル更新 |

## 実装時のクラス構造

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List
from pathlib import Path
import json

@dataclass
class SessionState:
    project_id: str
    session_id: str
    phase: int
    active_agent: Optional[dict]
    active_task: Optional[dict]
    completed_tasks: List[dict]
    pending_tasks: List[dict]
    remaining_tasks: List[dict]

class SessionManager:
    def __init__(self, project_path: Path):
        self.project_path = project_path
        self.current_session: Optional[SessionState] = None

    def start_new_session(self) -> str:
        """新しいセッションを開始"""
        session_id = f"sess_{datetime.now().strftime('%Y%m%d%H%M%S')}_{generate_random(6)}"
        session_path = self.project_path / "sessions" / session_id
        session_path.mkdir(parents=True)
        (session_path / "approaches").mkdir()
        return session_id

    def save_checkpoint(self) -> None:
        """現在の状態を保存"""
        if not self.current_session:
            return

        session_path = self.project_path / "sessions" / self.current_session.session_id

        # JSON保存
        with open(session_path / "state_checkpoint.json", "w") as f:
            json.dump(self.current_session.__dict__, f, indent=2, default=str)

        # Markdown生成
        self._generate_session_state_md(session_path)

    def resume_from(self, session_id: str) -> SessionState:
        """既存セッションから再開"""
        session_path = self.project_path / "sessions" / session_id
        with open(session_path / "state_checkpoint.json") as f:
            data = json.load(f)
        return SessionState(**data)

    def record_approach(self, approach_type: str, content: str) -> None:
        """アプローチを記録"""
        # verified, failed, untried のいずれか
        pass
```

## WebUIとの連携

### 再開ボタン
- プロジェクト一覧に「再開」ボタンを表示
- 中断セッションがある場合のみ有効

### セッション履歴
- 過去のセッション一覧を表示
- 各セッションの状態要約を閲覧可能

### API エンドポイント

| メソッド | パス | 説明 |
|---------|------|------|
| GET | /projects/{id}/sessions | セッション一覧 |
| GET | /projects/{id}/sessions/{sid} | セッション詳細 |
| POST | /projects/{id}/sessions/{sid}/resume | セッション再開 |
