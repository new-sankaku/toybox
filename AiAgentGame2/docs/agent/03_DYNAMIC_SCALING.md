# Agentの動的増減

## 概要

タスク量や負荷に応じてWORKERの数を動的に増減させる。
LEADERが判断し、必要に応じてWORKERを生成・終了する。

## 増減の対象

| Agent種別 | 動的増減 | 理由 |
|----------|---------|------|
| ORCHESTRATOR | なし | 常に1体 |
| DIRECTOR | なし | Phase毎に1体固定 |
| LEADER | なし | 機能単位で1体固定 |
| WORKER | あり | タスク量に応じて増減 |

## WORKERの生成条件

### 生成トリガー

| 条件 | 説明 |
|------|------|
| タスク割当時 | LEADERがタスクを受け取ったら、WORKERを生成 |
| 並列実行可能時 | 依存関係のないタスクが複数ある場合 |

### 生成上限（DB管理）

WORKER数の上限はDBで管理し、WebUIから確認・変更できる。

```sql
CREATE TABLE scaling_config (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    value INTEGER NOT NULL,
    description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 初期値
INSERT INTO scaling_config (key, value, description) VALUES
    ('max_workers_per_leader', 5, '1 LEADERあたりの最大WORKER数'),
    ('max_workers_per_phase', 10, '1 Phaseあたりの最大WORKER数'),
    ('max_workers_total', 20, 'システム全体の最大WORKER数'),
    ('queue_max_size', 100, '待機キューの最大サイズ'),
    ('queue_timeout_seconds', 300, 'キュー待ちタイムアウト');
```

### WebUI設定画面

| 設定項目 | DB key | 説明 |
|---------|--------|------|
| LEADERあたりWORKER上限 | max_workers_per_leader | スライダー（1〜10） |
| Phaseあたり上限 | max_workers_per_phase | スライダー（1〜20） |
| 全体上限 | max_workers_total | スライダー（1〜50） |
| キューサイズ | queue_max_size | 数値入力 |
| キュータイムアウト | queue_timeout_seconds | 数値入力（秒） |

## WORKERの終了条件

| 条件 | 詳細 | アクション |
|------|------|-----------|
| タスク完了（承認不要） | テスト実行など、自動検証で完了判定できるタスク | 即座に終了 |
| タスク完了（承認待ち） | Human承認が必要なタスク | 成果物を提出して待機状態、LEADERが承認提出後に終了 |
| タスク失敗（リトライ上限） | 最大3回のリトライ後も失敗 | 終了、LEADERにエスカレーション |
| タイムアウト | 設定時間を超過 | 終了、LEADERにエスカレーション |
| リソース不足 | システムリソースが逼迫 | 優先度の低いWORKERを終了 |

### 承認フローとWORKER終了の関係

```
WORKER実行
    │
    v
成果物生成
    │
    ├── 承認不要タスク → 自動検証 → OK → WORKER終了
    │                            → NG → リトライ or エスカレーション
    │
    └── 承認必要タスク → LEADERに提出 → WORKER待機状態
                                         │
                                         v
                                    LEADERがHuman承認提出
                                         │
                                         v
                                    Human承認/修正指示
                                         │
                                         ├── 承認 → WORKER終了
                                         │
                                         └── 修正指示 → WORKERを再起動して修正
```

## スケーリング戦略

### 戦略1: タスクベース（デフォルト）

```
タスク数に応じてWORKERを生成
- 1タスク = 1 WORKER
- 最大数に達したらキュー待ち
```

```python
class TaskBasedScaler:
    def __init__(self, db: Database):
        self.db = db
        self.active_workers: List[Worker] = []
        self.task_queue: List[Task] = []

    def get_max_workers(self) -> int:
        """DBから上限値を取得"""
        return self.db.get_scaling_config("max_workers_per_leader")

    def request_worker(self, task: Task) -> Optional[Worker]:
        max_workers = self.get_max_workers()
        if len(self.active_workers) < max_workers:
            worker = self._create_worker(task)
            self.active_workers.append(worker)
            return worker
        else:
            self.task_queue.append(task)
            return None

    def release_worker(self, worker: Worker) -> None:
        self.active_workers.remove(worker)
        if self.task_queue:
            next_task = self.task_queue.pop(0)
            self.request_worker(next_task)
```

### 戦略2: 負荷ベース

```
CPU/メモリ使用率に応じてWORKERを増減
- 使用率 < 50%: WORKER追加可能
- 使用率 > 80%: WORKER追加停止
- 使用率 > 90%: WORKER削減
```

```python
class LoadBasedScaler:
    def __init__(self, db: Database):
        self.db = db

    def get_thresholds(self) -> dict:
        """DBから閾値を取得"""
        return {
            "low": self.db.get_scaling_config("cpu_threshold_low"),
            "high": self.db.get_scaling_config("cpu_threshold_high"),
            "critical": self.db.get_scaling_config("cpu_threshold_critical"),
        }

    def can_scale_up(self) -> bool:
        cpu_usage = self._get_cpu_usage()
        thresholds = self.get_thresholds()
        return cpu_usage < thresholds["low"]

    def should_scale_down(self) -> bool:
        cpu_usage = self._get_cpu_usage()
        thresholds = self.get_thresholds()
        return cpu_usage > thresholds["critical"]
```

## LEADERによるスケーリング判断

```python
class Leader:
    def __init__(self, db: Database):
        self.scaler = TaskBasedScaler(db)
        self.workers: List[Worker] = []

    def receive_tasks(self, tasks: List[Task]) -> None:
        """タスクを受け取り、WORKERに分配"""
        # 依存関係を解析
        independent_tasks = self._find_independent_tasks(tasks)
        dependent_tasks = [t for t in tasks if t not in independent_tasks]

        # 独立タスクは並列実行
        for task in independent_tasks:
            worker = self.scaler.request_worker(task)
            if worker:
                worker.execute(task)
            # 上限に達した場合はキュー待ち

        # 依存タスクはキューに追加（依存解決後に実行）

    def on_worker_complete(self, worker: Worker, result: dict) -> None:
        """WORKER完了時の処理"""
        self.scaler.release_worker(worker)

        # 依存タスクの実行可能性をチェック
        self._check_dependent_tasks()
```

## 監視メトリクス

| メトリクス | 説明 |
|-----------|------|
| active_workers | 現在稼働中のWORKER数 |
| queued_tasks | キュー待ちタスク数 |
| avg_task_duration | 平均タスク完了時間 |
| worker_utilization | WORKER稼働率 |
| scale_up_events | スケールアップ回数 |
| scale_down_events | スケールダウン回数 |

## 実装時の注意

### 1. リソースリーク防止

WORKERが正常終了しない場合のクリーンアップ処理が必要。

```python
class WorkerManager:
    async def cleanup_stale_workers(self):
        """異常終了したWORKERを検出してクリーンアップ"""
        for worker in self.active_workers:
            if worker.is_stale():  # 一定時間応答なし
                await worker.force_terminate()
                self.release_worker(worker)
```

### 2. デッドロック防止

全WORKERが依存タスク待ちになると処理が停止する。

**デッドロック発生例:**
```
WORKER A: タスクX実行中、タスクYの完了を待機
WORKER B: タスクY実行中、タスクXの完了を待機
→ 両方が互いを待ち続けて停止
```

**防止策:**

```python
class DeadlockPrevention:
    def __init__(self, max_workers: int):
        self.max_workers = max_workers

    def validate_task_assignment(self, tasks: List[Task]) -> bool:
        """デッドロックの可能性をチェック"""
        # 循環依存を検出
        if self._has_circular_dependency(tasks):
            return False

        # 独立タスクが最低1つあることを確認
        independent = [t for t in tasks if not t.depends_on]
        if not independent:
            return False

        return True

    def _has_circular_dependency(self, tasks: List[Task]) -> bool:
        """循環依存を検出（トポロジカルソートで確認）"""
        # グラフを構築
        graph = {t.id: set(t.depends_on) for t in tasks}

        # トポロジカルソートを試行
        visited = set()
        in_stack = set()

        def has_cycle(node):
            if node in in_stack:
                return True
            if node in visited:
                return False

            visited.add(node)
            in_stack.add(node)

            for dep in graph.get(node, []):
                if has_cycle(dep):
                    return True

            in_stack.remove(node)
            return False

        return any(has_cycle(t.id) for t in tasks)

    def reserve_independent_slot(self):
        """
        独立タスク用に常に1スロットを確保する。
        これにより、全WORKERが依存タスクで埋まることを防ぐ。
        """
        return self.max_workers - 1  # 依存タスクに使える最大数
```

### 3. 優先度管理

重要タスクが後回しにならないようキュー管理。

### 4. 状態保存

スケーリング状態もセッション継続性の対象とする（02_SESSION_CONTINUITY.md参照）。
