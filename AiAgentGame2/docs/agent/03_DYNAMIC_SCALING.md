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
| 負荷分散時 | 1つのWORKERに時間がかかりすぎている場合 |

### 生成上限

```python
WORKER_LIMITS = {
    "per_leader": 5,      # 1 LEADERあたりの最大WORKER数
    "per_phase": 10,      # 1 Phaseあたりの最大WORKER数
    "total": 20,          # システム全体の最大WORKER数
}
```

## WORKERの終了条件

| 条件 | アクション |
|------|-----------|
| タスク完了 | 即座に終了 |
| タスク失敗（リトライ上限） | 終了、LEADERにエスカレーション |
| タイムアウト | 終了、LEADERにエスカレーション |
| リソース不足 | 優先度の低いWORKERを終了 |

## スケーリング戦略

### 戦略1: タスクベース（デフォルト）

```
タスク数に応じてWORKERを生成
- 1タスク = 1 WORKER
- 最大数に達したらキュー待ち
```

```python
class TaskBasedScaler:
    def __init__(self, max_workers: int):
        self.max_workers = max_workers
        self.active_workers: List[Worker] = []
        self.task_queue: List[Task] = []

    def request_worker(self, task: Task) -> Optional[Worker]:
        if len(self.active_workers) < self.max_workers:
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
    def __init__(self):
        self.cpu_threshold_low = 50
        self.cpu_threshold_high = 80
        self.cpu_threshold_critical = 90

    def can_scale_up(self) -> bool:
        cpu_usage = self._get_cpu_usage()
        return cpu_usage < self.cpu_threshold_low

    def should_scale_down(self) -> bool:
        cpu_usage = self._get_cpu_usage()
        return cpu_usage > self.cpu_threshold_critical

    def get_recommended_workers(self) -> int:
        cpu_usage = self._get_cpu_usage()
        if cpu_usage < 30:
            return 5
        elif cpu_usage < 50:
            return 4
        elif cpu_usage < 70:
            return 3
        elif cpu_usage < 85:
            return 2
        else:
            return 1
```

### 戦略3: 時間ベース

```
タスクの推定時間に応じてWORKERを調整
- 短いタスク（< 1分）: 多くのWORKER
- 長いタスク（> 10分）: 少ないWORKER
```

```python
class TimeBasedScaler:
    def estimate_task_duration(self, task: Task) -> int:
        """タスクの推定時間（秒）を返す"""
        base_time = {
            "code_simple": 60,
            "code_complex": 300,
            "asset_image": 120,
            "asset_audio": 180,
            "test": 60,
            "review": 120,
        }
        return base_time.get(task.type, 120)

    def get_optimal_workers(self, tasks: List[Task]) -> int:
        total_time = sum(self.estimate_task_duration(t) for t in tasks)
        # 10分で完了を目標
        target_time = 600
        optimal = max(1, total_time // target_time)
        return min(optimal, WORKER_LIMITS["per_leader"])
```

## LEADERによるスケーリング判断

```python
class Leader:
    def __init__(self):
        self.scaler = TaskBasedScaler(max_workers=5)
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

        # 依存タスクは順次実行（依存解決後に実行）

    def on_worker_complete(self, worker: Worker, result: dict) -> None:
        """WORKER完了時の処理"""
        self.scaler.release_worker(worker)

        # 依存タスクの実行可能性をチェック
        self._check_dependent_tasks()
```

## 設定

### システム設定

```yaml
# config/scaling.yaml

scaling:
  strategy: "task_based"  # task_based, load_based, time_based

  limits:
    per_leader: 5
    per_phase: 10
    total: 20

  load_based:
    cpu_threshold_low: 50
    cpu_threshold_high: 80
    cpu_threshold_critical: 90
    memory_threshold: 80

  time_based:
    target_completion_time: 600  # 秒

  queue:
    max_size: 100
    timeout: 300  # 秒
```

### WebUIからの設定変更

| 設定項目 | UIコンポーネント |
|---------|----------------|
| 戦略選択 | ドロップダウン |
| WORKER上限 | スライダー |
| CPU閾値 | スライダー |

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

1. **リソースリーク防止**: WORKERが正常終了しない場合のクリーンアップ
2. **デッドロック防止**: 全WORKERが依存タスク待ちにならないよう注意
3. **優先度管理**: 重要タスクが後回しにならないようキュー管理
4. **状態保存**: スケーリング状態もセッション継続性の対象
