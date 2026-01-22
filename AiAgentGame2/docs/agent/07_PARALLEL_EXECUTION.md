# Agentの並列化処理

## 概要

依存関係のないタスクを複数のWORKERで同時に実行し、全体の処理時間を短縮する。
ただし、リソース制約とコンフリクト回避を考慮する。

## 並列化の条件

### 並列実行可能な条件

| 条件 | 説明 |
|------|------|
| 依存関係がない | タスクAの完了がタスクBの開始に必要でない |
| 同一ファイルを編集しない | ファイルロックで競合しない |
| 共有リソースを使わない | API rate limit等の制約がない |

### 並列実行不可の条件

| 条件 | 例 |
|------|-----|
| 順序依存 | 「基底クラス作成」→「派生クラス作成」 |
| ファイル競合 | 同じファイルを2つのWORKERが編集 |
| リソース競合 | 同じAPIを同時に大量呼び出し |

## 依存関係グラフ

### 依存関係の表現

```python
from dataclasses import dataclass
from typing import List, Set

@dataclass
class Task:
    task_id: str
    depends_on: List[str]  # 依存するタスクIDのリスト
    modifies_files: List[str]  # 変更するファイル

class DependencyGraph:
    def __init__(self):
        self.tasks: Dict[str, Task] = {}
        self.completed: Set[str] = set()

    def add_task(self, task: Task):
        self.tasks[task.task_id] = task

    def get_executable_tasks(self) -> List[Task]:
        """現在実行可能なタスクを取得"""
        executable = []
        for task in self.tasks.values():
            if task.task_id in self.completed:
                continue
            # 依存タスクがすべて完了しているか
            if all(dep in self.completed for dep in task.depends_on):
                executable.append(task)
        return executable

    def mark_completed(self, task_id: str):
        self.completed.add(task_id)
```

### 可視化例

```
task_001 (基底クラス)
    │
    ├── task_002 (Player) ──┐
    │                       │
    ├── task_003 (Enemy)    ├── task_006 (ゲームループ)
    │                       │
    └── task_004 (Item) ────┘
         │
         └── task_005 (インベントリ)
```

この例では:
- task_002, task_003, task_004 は並列実行可能
- task_005 は task_004 の完了後に実行
- task_006 は task_002, task_003, task_004 の完了後に実行

## 並列実行の制御

### 並列度の設定

```yaml
# config/parallel.yaml

parallel:
  max_workers:
    total: 10          # システム全体
    per_leader: 5      # 1 LEADERあたり
    per_phase: 8       # 1 Phaseあたり

  resource_limits:
    cpu_percent: 80
    memory_percent: 80
    api_calls_per_minute: 60

  file_lock:
    enabled: true
    timeout_seconds: 300
```

### 実行スケジューラ

```python
import asyncio
from typing import List, Dict

class ParallelScheduler:
    def __init__(self, max_workers: int):
        self.max_workers = max_workers
        self.active_workers: Dict[str, Worker] = {}
        self.file_locks: Dict[str, str] = {}  # filepath -> task_id
        self.semaphore = asyncio.Semaphore(max_workers)

    async def execute_tasks(self, tasks: List[Task]) -> Dict[str, Result]:
        """タスクを並列実行"""
        graph = DependencyGraph()
        for task in tasks:
            graph.add_task(task)

        results = {}

        while len(results) < len(tasks):
            # 実行可能なタスクを取得
            executable = graph.get_executable_tasks()

            # ファイルロックを考慮してフィルタ
            executable = self._filter_by_file_locks(executable)

            if not executable:
                # 実行可能なタスクがない場合は待機
                await asyncio.sleep(0.1)
                continue

            # 並列実行
            coros = [self._execute_task(task) for task in executable]
            task_results = await asyncio.gather(*coros)

            for task, result in zip(executable, task_results):
                results[task.task_id] = result
                graph.mark_completed(task.task_id)
                self._release_file_locks(task)

        return results

    def _filter_by_file_locks(self, tasks: List[Task]) -> List[Task]:
        """ファイルロックで競合しないタスクのみ返す"""
        filtered = []
        for task in tasks:
            conflict = False
            for filepath in task.modifies_files:
                if filepath in self.file_locks:
                    conflict = True
                    break
            if not conflict:
                filtered.append(task)
                # ロックを取得
                for filepath in task.modifies_files:
                    self.file_locks[filepath] = task.task_id
        return filtered

    def _release_file_locks(self, task: Task):
        """ファイルロックを解放"""
        for filepath in task.modifies_files:
            if self.file_locks.get(filepath) == task.task_id:
                del self.file_locks[filepath]

    async def _execute_task(self, task: Task) -> Result:
        """単一タスクを実行"""
        async with self.semaphore:
            worker = Worker(task.task_id)
            self.active_workers[task.task_id] = worker
            try:
                result = await worker.execute_async(task)
                return result
            finally:
                del self.active_workers[task.task_id]
```

## ファイルロック機構

### ロックの種類

| 種類 | 説明 | 用途 |
|------|------|------|
| 排他ロック | 1つのWORKERのみ | 書き込み |
| 共有ロック | 複数のWORKERが可能 | 読み取り |

### 実装

```python
from enum import Enum
from threading import RLock
from typing import Optional

class LockType(Enum):
    EXCLUSIVE = "exclusive"
    SHARED = "shared"

class FileLockManager:
    def __init__(self):
        self._lock = RLock()
        self._exclusive_locks: Dict[str, str] = {}  # filepath -> worker_id
        self._shared_locks: Dict[str, Set[str]] = {}  # filepath -> {worker_ids}

    def acquire(self, filepath: str, worker_id: str, lock_type: LockType) -> bool:
        """ロックを取得"""
        with self._lock:
            if lock_type == LockType.EXCLUSIVE:
                # 排他ロック：他のロックがなければ取得
                if filepath in self._exclusive_locks:
                    return False
                if filepath in self._shared_locks and self._shared_locks[filepath]:
                    return False
                self._exclusive_locks[filepath] = worker_id
                return True
            else:
                # 共有ロック：排他ロックがなければ取得
                if filepath in self._exclusive_locks:
                    return False
                if filepath not in self._shared_locks:
                    self._shared_locks[filepath] = set()
                self._shared_locks[filepath].add(worker_id)
                return True

    def release(self, filepath: str, worker_id: str):
        """ロックを解放"""
        with self._lock:
            if self._exclusive_locks.get(filepath) == worker_id:
                del self._exclusive_locks[filepath]
            if filepath in self._shared_locks:
                self._shared_locks[filepath].discard(worker_id)
```

## API Rate Limit対策

### レートリミッター

```python
import time
from collections import deque

class RateLimiter:
    def __init__(self, max_calls: int, period_seconds: int):
        self.max_calls = max_calls
        self.period = period_seconds
        self.calls: deque = deque()

    async def acquire(self):
        """呼び出し権を取得（必要なら待機）"""
        now = time.time()

        # 古い呼び出し記録を削除
        while self.calls and self.calls[0] < now - self.period:
            self.calls.popleft()

        # 上限に達していたら待機
        if len(self.calls) >= self.max_calls:
            wait_time = self.calls[0] + self.period - now
            await asyncio.sleep(wait_time)
            return await self.acquire()

        self.calls.append(now)

# 使用例
api_limiter = RateLimiter(max_calls=60, period_seconds=60)

async def call_llm_api(prompt: str):
    await api_limiter.acquire()
    # API呼び出し
```

## 監視

### メトリクス

| メトリクス | 説明 |
|-----------|------|
| active_workers | 現在稼働中のWORKER数 |
| parallel_efficiency | 並列実行効率（実際/理論最大） |
| lock_contention | ロック競合回数 |
| queue_depth | 待機中タスク数 |
| avg_wait_time | 平均待機時間 |

### WebUI表示

```
┌─────────────────────────────────────┐
│ 並列実行状況                        │
├─────────────────────────────────────┤
│ アクティブWORKER: 4/5               │
│ 待機タスク: 3                       │
│ 並列効率: 85%                       │
│                                     │
│ [■■■■□] task_002 (75%)             │
│ [■■□□□] task_003 (40%)             │
│ [■■■□□] task_004 (60%)             │
│ [■□□□□] task_005 (20%)             │
└─────────────────────────────────────┘
```

## Phase別の並列化

### Phase1（企画）

```
Concept → Design → Scenario ┐
                            ├→ TaskSplit
         Character → World ─┘
```
- Character と World は Scenario と並列可能
- TaskSplit は他すべての完了後

### Phase2（開発）

```
Code LEADER ─┬─ WORKER群（並列）
             │
Asset LEADER ─┬─ WORKER群（並列）
```
- Code と Asset は別LEADERなので完全並列
- 各LEADER配下のWORKERも依存関係なければ並列

### Phase3（品質）

```
Integrator → Tester → Reviewer
```
- 基本的に順次実行
- Testerの一部テストは並列可能
