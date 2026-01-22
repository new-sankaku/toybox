# 作業領域の重複回避

## 概要

複数のWORKERが同じファイルを編集することによるコンフリクトを防ぐ。
Git Worktreeを活用して各WORKERに独立した作業領域を割り当て、安全に並列作業を行う。

## 問題点

### コンフリクトが発生するケース

```
WORKER A: PlayerController.cs を編集中
WORKER B: PlayerController.cs を編集中
    ↓
マージ時にコンフリクト発生
    ↓
解決に追加のToken・時間が必要
```

### コスト

| 項目 | コンフリクトなし | コンフリクトあり |
|------|----------------|----------------|
| Token消費 | 1,000 | 3,000+ |
| 時間 | 1分 | 5分+ |
| Human介入 | 不要 | 必要な場合あり |

## 解決策

### 1. Git Worktreeによる分離

```bash
# メインリポジトリ
projects/{project_id}/repo/
    ├── .git/
    ├── src/
    └── ...

# WORKER用Worktree
projects/{project_id}/worktrees/
    ├── worker_task_001/    # WORKER Aの作業領域
    │   ├── src/
    │   └── ...
    ├── worker_task_002/    # WORKER Bの作業領域
    │   ├── src/
    │   └── ...
    └── worker_task_003/    # WORKER Cの作業領域
```

### 2. ファイルロック機構

同じファイルを複数WORKERが編集しないよう制御。

## Git Worktree管理

### Worktreeの作成

```python
import subprocess
from pathlib import Path

class WorktreeManager:
    def __init__(self, repo_path: Path, worktrees_path: Path):
        self.repo_path = repo_path
        self.worktrees_path = worktrees_path
        self.active_worktrees: Dict[str, Path] = {}

    def create_worktree(self, task_id: str) -> Path:
        """タスク用のWorktreeを作成"""
        worktree_path = self.worktrees_path / f"worker_{task_id}"
        branch_name = f"task/{task_id}"

        # ブランチ作成
        subprocess.run(
            ["git", "branch", branch_name, "main"],
            cwd=self.repo_path,
            check=True
        )

        # Worktree作成
        subprocess.run(
            ["git", "worktree", "add", str(worktree_path), branch_name],
            cwd=self.repo_path,
            check=True
        )

        self.active_worktrees[task_id] = worktree_path
        return worktree_path

    def remove_worktree(self, task_id: str):
        """Worktreeを削除"""
        worktree_path = self.active_worktrees.get(task_id)
        if not worktree_path:
            return

        branch_name = f"task/{task_id}"

        # Worktree削除
        subprocess.run(
            ["git", "worktree", "remove", str(worktree_path)],
            cwd=self.repo_path,
            check=True
        )

        # ブランチ削除（マージ後）
        subprocess.run(
            ["git", "branch", "-d", branch_name],
            cwd=self.repo_path,
            check=False  # マージされていない場合は失敗してもOK
        )

        del self.active_worktrees[task_id]

    def merge_worktree(self, task_id: str) -> bool:
        """Worktreeの変更をmainにマージ"""
        branch_name = f"task/{task_id}"

        # mainに切り替え
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=self.repo_path,
            check=True
        )

        # マージ
        result = subprocess.run(
            ["git", "merge", branch_name, "--no-ff", "-m", f"Merge {task_id}"],
            cwd=self.repo_path,
            capture_output=True
        )

        if result.returncode != 0:
            # コンフリクト発生
            return False

        return True
```

### WORKERへのWorktree割り当て

```python
class Worker:
    def __init__(self, task: Task, worktree_manager: WorktreeManager):
        self.task = task
        self.worktree_manager = worktree_manager
        self.worktree_path: Optional[Path] = None

    async def setup(self):
        """作業領域を準備"""
        self.worktree_path = self.worktree_manager.create_worktree(self.task.task_id)

    async def execute(self) -> Result:
        """タスクを実行"""
        # Worktree内で作業
        # self.worktree_path を使用してファイル操作

        # 変更をコミット
        subprocess.run(
            ["git", "add", "."],
            cwd=self.worktree_path
        )
        subprocess.run(
            ["git", "commit", "-m", f"Complete {self.task.task_id}: {self.task.objective}"],
            cwd=self.worktree_path
        )

        return Result(success=True)

    async def cleanup(self):
        """作業領域をクリーンアップ"""
        self.worktree_manager.remove_worktree(self.task.task_id)
```

## ファイルロック機構

### ロックの種類

| ロック種類 | 説明 | 用途 |
|-----------|------|------|
| 排他ロック | 1つのWORKERのみ | ファイル編集 |
| 共有ロック | 複数WORKER可 | ファイル読み取り |
| ディレクトリロック | ディレクトリ全体 | 大規模な変更 |

### ロックマネージャー

```python
from threading import RLock
from typing import Dict, Set, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta

@dataclass
class FileLock:
    filepath: str
    worker_id: str
    lock_type: str  # "exclusive" or "shared"
    acquired_at: datetime
    timeout: timedelta

class FileLockManager:
    def __init__(self, default_timeout_seconds: int = 300):
        self._lock = RLock()
        self._exclusive_locks: Dict[str, FileLock] = {}
        self._shared_locks: Dict[str, Set[str]] = {}  # filepath -> worker_ids
        self.default_timeout = timedelta(seconds=default_timeout_seconds)

    def acquire_exclusive(self, filepath: str, worker_id: str) -> bool:
        """排他ロックを取得"""
        with self._lock:
            self._cleanup_expired()

            # 既存のロックをチェック
            if filepath in self._exclusive_locks:
                return False
            if filepath in self._shared_locks and self._shared_locks[filepath]:
                return False

            # ロックを取得
            self._exclusive_locks[filepath] = FileLock(
                filepath=filepath,
                worker_id=worker_id,
                lock_type="exclusive",
                acquired_at=datetime.utcnow(),
                timeout=self.default_timeout
            )
            return True

    def acquire_shared(self, filepath: str, worker_id: str) -> bool:
        """共有ロックを取得"""
        with self._lock:
            self._cleanup_expired()

            # 排他ロックをチェック
            if filepath in self._exclusive_locks:
                return False

            # 共有ロックを取得
            if filepath not in self._shared_locks:
                self._shared_locks[filepath] = set()
            self._shared_locks[filepath].add(worker_id)
            return True

    def release(self, filepath: str, worker_id: str):
        """ロックを解放"""
        with self._lock:
            if filepath in self._exclusive_locks:
                if self._exclusive_locks[filepath].worker_id == worker_id:
                    del self._exclusive_locks[filepath]

            if filepath in self._shared_locks:
                self._shared_locks[filepath].discard(worker_id)

    def _cleanup_expired(self):
        """期限切れロックを削除"""
        now = datetime.utcnow()

        expired = [
            fp for fp, lock in self._exclusive_locks.items()
            if now > lock.acquired_at + lock.timeout
        ]
        for fp in expired:
            del self._exclusive_locks[fp]
```

## 事前コンフリクトチェック

### タスク割り当て時のチェック

```python
class ConflictChecker:
    def __init__(self, file_lock_manager: FileLockManager):
        self.lock_manager = file_lock_manager

    def check_conflicts(self, task: Task, active_tasks: List[Task]) -> List[str]:
        """コンフリクトの可能性があるファイルを検出"""
        conflicts = []

        for active_task in active_tasks:
            # ファイルの重複をチェック
            overlap = set(task.modifies_files) & set(active_task.modifies_files)
            if overlap:
                conflicts.extend(overlap)

        return list(set(conflicts))

    def can_execute(self, task: Task) -> bool:
        """タスクが実行可能か判定"""
        for filepath in task.modifies_files:
            if not self.lock_manager.acquire_exclusive(filepath, task.task_id):
                # ロック取得失敗 → 実行不可
                # 取得済みのロックを解放
                for acquired in task.modifies_files:
                    if acquired == filepath:
                        break
                    self.lock_manager.release(acquired, task.task_id)
                return False
        return True
```

### LEADER によるタスク分配

```python
class Leader:
    def __init__(self, conflict_checker: ConflictChecker):
        self.conflict_checker = conflict_checker

    def assign_tasks(self, tasks: List[Task]) -> List[Task]:
        """コンフリクトを避けてタスクを割り当て"""
        assigned = []
        pending = []

        for task in tasks:
            # コンフリクトチェック
            conflicts = self.conflict_checker.check_conflicts(task, assigned)

            if conflicts:
                # コンフリクトあり → 待機キューへ
                pending.append(task)
            else:
                # コンフリクトなし → 割り当て
                if self.conflict_checker.can_execute(task):
                    assigned.append(task)
                else:
                    pending.append(task)

        return assigned  # pending は後で再試行
```

## マージ戦略

### Integrator LEADERによる統合

```python
class IntegratorLeader:
    def __init__(self, worktree_manager: WorktreeManager):
        self.worktree_manager = worktree_manager

    async def integrate(self, completed_tasks: List[Task]) -> IntegrationResult:
        """完了タスクを統合"""

        # 依存関係順にソート
        sorted_tasks = self._sort_by_dependencies(completed_tasks)

        results = []
        for task in sorted_tasks:
            # マージ実行
            success = self.worktree_manager.merge_worktree(task.task_id)

            if not success:
                # コンフリクト発生
                conflict_result = await self._resolve_conflict(task)
                results.append(conflict_result)
            else:
                results.append(IntegrationResult(task_id=task.task_id, success=True))

        return results

    async def _resolve_conflict(self, task: Task) -> IntegrationResult:
        """コンフリクトを解決"""
        # 1. コンフリクトの詳細を取得
        conflict_info = self._get_conflict_info()

        # 2. 自動解決を試みる
        if self._can_auto_resolve(conflict_info):
            return await self._auto_resolve(conflict_info)

        # 3. 自動解決できない場合はHumanにエスカレーション
        return IntegrationResult(
            task_id=task.task_id,
            success=False,
            conflict=conflict_info,
            requires_human=True
        )
```

## 設定

```yaml
# config/workspace.yaml

workspace:
  worktree:
    enabled: true
    base_path: "worktrees"
    cleanup_on_complete: true

  file_lock:
    enabled: true
    default_timeout_seconds: 300
    max_wait_seconds: 60

  conflict_prevention:
    check_before_assign: true
    auto_resolve_enabled: true
    escalate_on_failure: true
```

## 監視

| メトリクス | 説明 |
|-----------|------|
| active_worktrees | アクティブなWorktree数 |
| lock_contentions | ロック競合回数 |
| merge_conflicts | マージコンフリクト回数 |
| auto_resolve_rate | 自動解決成功率 |
