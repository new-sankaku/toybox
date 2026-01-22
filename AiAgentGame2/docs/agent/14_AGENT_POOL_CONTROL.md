# Sub Agent起動数の制御

## 概要

WebUIからWORKERの同時起動数を制御できるようにする。
マシンスペックやコスト制約に応じて、適切な並列度を設定する。

## 制御対象

| Agent種別 | 制御 | 理由 |
|----------|------|------|
| ORCHESTRATOR | 不可 | 常に1体 |
| DIRECTOR | 不可 | Phase毎に1体固定 |
| LEADER | 不可 | 機能単位で固定 |
| WORKER | 可能 | 動的に増減 |

## 設定項目

### 並列度設定

```yaml
# config/agent_pool.yaml

agent_pool:
  worker:
    # 最大同時起動数
    max_total: 10          # システム全体
    max_per_leader: 5      # 1 LEADERあたり
    max_per_phase: 8       # 1 Phaseあたり

    # 最小起動数（常に維持）
    min_total: 1

    # スケーリング設定
    scaling:
      enabled: true
      scale_up_threshold: 80    # キュー使用率(%)
      scale_down_threshold: 20  # キュー使用率(%)
      cooldown_seconds: 60      # スケーリング間隔

  # リソース制約
  resource_limits:
    cpu_percent: 80
    memory_percent: 80
    api_calls_per_minute: 60
```

### WebUIからの設定

```typescript
interface AgentPoolConfig {
  worker: {
    maxTotal: number;
    maxPerLeader: number;
    maxPerPhase: number;
    minTotal: number;
    scaling: {
      enabled: boolean;
      scaleUpThreshold: number;
      scaleDownThreshold: number;
      cooldownSeconds: number;
    };
  };
  resourceLimits: {
    cpuPercent: number;
    memoryPercent: number;
    apiCallsPerMinute: number;
  };
}
```

## プリセット

### マシンスペック別プリセット

| プリセット | max_total | max_per_leader | 推奨環境 |
|-----------|-----------|----------------|---------|
| minimal | 2 | 2 | 低スペックPC |
| standard | 5 | 3 | 一般的なPC |
| performance | 10 | 5 | 高スペックPC |
| server | 20 | 8 | サーバー環境 |

### プリセット定義

```yaml
# config/presets/agent_pool.yaml

presets:
  minimal:
    description: "低スペックPC向け（メモリ8GB以下）"
    worker:
      max_total: 2
      max_per_leader: 2
      max_per_phase: 2
    resource_limits:
      cpu_percent: 60
      memory_percent: 60

  standard:
    description: "一般的なPC向け（メモリ16GB）"
    worker:
      max_total: 5
      max_per_leader: 3
      max_per_phase: 4
    resource_limits:
      cpu_percent: 70
      memory_percent: 70

  performance:
    description: "高スペックPC向け（メモリ32GB以上）"
    worker:
      max_total: 10
      max_per_leader: 5
      max_per_phase: 8
    resource_limits:
      cpu_percent: 80
      memory_percent: 80

  server:
    description: "サーバー環境向け"
    worker:
      max_total: 20
      max_per_leader: 8
      max_per_phase: 15
    resource_limits:
      cpu_percent: 90
      memory_percent: 85
```

## 実装

### AgentPoolController

```python
from dataclasses import dataclass
from typing import Dict, List, Optional
import asyncio
import psutil

@dataclass
class PoolConfig:
    max_total: int
    max_per_leader: int
    max_per_phase: int
    min_total: int
    cpu_limit: int
    memory_limit: int

class AgentPoolController:
    def __init__(self, config: PoolConfig):
        self.config = config
        self.active_workers: Dict[str, "Worker"] = {}
        self.queue: List["Task"] = []
        self._lock = asyncio.Lock()

    @property
    def current_count(self) -> int:
        return len(self.active_workers)

    def can_start_worker(self, leader_id: str, phase: int) -> bool:
        """新しいWORKERを起動できるか判定"""
        # 総数チェック
        if self.current_count >= self.config.max_total:
            return False

        # LEADER毎の上限チェック
        leader_count = sum(
            1 for w in self.active_workers.values()
            if w.leader_id == leader_id
        )
        if leader_count >= self.config.max_per_leader:
            return False

        # Phase毎の上限チェック
        phase_count = sum(
            1 for w in self.active_workers.values()
            if w.phase == phase
        )
        if phase_count >= self.config.max_per_phase:
            return False

        # リソースチェック
        if not self._check_resources():
            return False

        return True

    def _check_resources(self) -> bool:
        """リソース使用率をチェック"""
        cpu = psutil.cpu_percent()
        memory = psutil.virtual_memory().percent

        if cpu > self.config.cpu_limit:
            return False
        if memory > self.config.memory_limit:
            return False

        return True

    async def request_worker(self, task: "Task", leader_id: str, phase: int) -> Optional["Worker"]:
        """WORKERを要求"""
        async with self._lock:
            if self.can_start_worker(leader_id, phase):
                worker = Worker(task, leader_id, phase)
                self.active_workers[worker.worker_id] = worker
                return worker
            else:
                # キューに追加
                self.queue.append(task)
                return None

    async def release_worker(self, worker_id: str):
        """WORKERを解放"""
        async with self._lock:
            if worker_id in self.active_workers:
                worker = self.active_workers[worker_id]
                del self.active_workers[worker_id]

                # キューから次のタスクを処理
                if self.queue:
                    next_task = self.queue.pop(0)
                    await self.request_worker(
                        next_task,
                        next_task.leader_id,
                        next_task.phase
                    )

    def update_config(self, new_config: PoolConfig):
        """設定を動的に更新"""
        self.config = new_config

        # 上限を超えている場合は警告
        if self.current_count > new_config.max_total:
            # 既存のWORKERは完了まで継続
            # 新規は上限まで起動しない
            pass
```

### リソースモニター

```python
class ResourceMonitor:
    def __init__(self, pool_controller: AgentPoolController):
        self.pool = pool_controller
        self.history: List[dict] = []

    async def monitor_loop(self, interval_seconds: int = 10):
        """リソース監視ループ"""
        while True:
            stats = self._collect_stats()
            self.history.append(stats)

            # 履歴は直近100件のみ保持
            self.history = self.history[-100:]

            # 自動スケーリング判定
            if self.pool.config.scaling_enabled:
                await self._auto_scale(stats)

            await asyncio.sleep(interval_seconds)

    def _collect_stats(self) -> dict:
        """統計を収集"""
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "active_workers": self.pool.current_count,
            "queue_size": len(self.pool.queue),
            "cpu_percent": psutil.cpu_percent(),
            "memory_percent": psutil.virtual_memory().percent,
        }

    async def _auto_scale(self, stats: dict):
        """自動スケーリング"""
        queue_ratio = stats["queue_size"] / max(stats["active_workers"], 1)

        if queue_ratio > self.pool.config.scale_up_threshold / 100:
            # スケールアップ推奨
            suggested = min(
                self.pool.current_count + 2,
                self.pool.config.max_total
            )
            # 通知のみ（実際の変更はWebUIから）

        elif queue_ratio < self.pool.config.scale_down_threshold / 100:
            # スケールダウン可能
            suggested = max(
                self.pool.current_count - 1,
                self.pool.config.min_total
            )
```

## WebUI

### 設定画面

```typescript
// AgentPoolSettings.tsx

interface AgentPoolSettingsProps {
  projectId: string;
}

function AgentPoolSettings({ projectId }: AgentPoolSettingsProps) {
  const [config, setConfig] = useState<AgentPoolConfig | null>(null);
  const [preset, setPreset] = useState<string>("standard");

  // プリセット選択
  const applyPreset = (presetName: string) => {
    const presetConfig = PRESETS[presetName];
    setConfig(presetConfig);
    setPreset(presetName);
  };

  // カスタム設定
  const updateConfig = (key: string, value: number) => {
    setConfig(prev => ({
      ...prev,
      worker: { ...prev.worker, [key]: value }
    }));
    setPreset("custom");
  };

  return (
    <Panel title="Agent Pool 設定">
      {/* プリセット選択 */}
      <PresetSelector
        value={preset}
        onChange={applyPreset}
        options={["minimal", "standard", "performance", "server", "custom"]}
      />

      {/* 詳細設定 */}
      <Slider
        label="最大WORKER数（全体）"
        value={config.worker.maxTotal}
        min={1}
        max={30}
        onChange={v => updateConfig("maxTotal", v)}
      />

      <Slider
        label="最大WORKER数（LEADERあたり）"
        value={config.worker.maxPerLeader}
        min={1}
        max={10}
        onChange={v => updateConfig("maxPerLeader", v)}
      />

      {/* リソース制限 */}
      <Slider
        label="CPU使用率上限 (%)"
        value={config.resourceLimits.cpuPercent}
        min={30}
        max={100}
        onChange={v => updateConfig("cpuPercent", v)}
      />

      <Button onClick={saveConfig}>保存</Button>
    </Panel>
  );
}
```

### ダッシュボード

```typescript
// AgentPoolDashboard.tsx

function AgentPoolDashboard({ projectId }: { projectId: string }) {
  const stats = useAgentPoolStats(projectId);

  return (
    <Dashboard>
      {/* 現在の状態 */}
      <Stat label="アクティブWORKER" value={stats.activeWorkers} max={stats.maxWorkers} />
      <Stat label="待機タスク" value={stats.queueSize} />
      <Stat label="CPU使用率" value={`${stats.cpuPercent}%`} />
      <Stat label="メモリ使用率" value={`${stats.memoryPercent}%`} />

      {/* グラフ */}
      <Chart
        data={stats.history}
        series={["activeWorkers", "queueSize"]}
      />

      {/* WORKER一覧 */}
      <WorkerList workers={stats.workers} />
    </Dashboard>
  );
}
```

## APIエンドポイント

| メソッド | パス | 説明 |
|---------|------|------|
| GET | /agent-pool/config | 現在の設定を取得 |
| PUT | /agent-pool/config | 設定を更新 |
| GET | /agent-pool/stats | 統計情報を取得 |
| GET | /agent-pool/presets | プリセット一覧 |
| POST | /agent-pool/presets/{name}/apply | プリセットを適用 |

## 安全機能

### 緊急停止

```python
async def emergency_stop(self):
    """全WORKERを緊急停止"""
    async with self._lock:
        for worker_id, worker in list(self.active_workers.items()):
            await worker.cancel()
            del self.active_workers[worker_id]

        self.queue.clear()
```

### リソース超過時の自動制限

```python
def on_resource_exceeded(self, resource: str, current: float, limit: float):
    """リソース超過時の処理"""
    # 新規WORKERの起動を一時停止
    self._paused = True

    # 通知
    self._notify_resource_exceeded(resource, current, limit)

    # 回復を待つ
    asyncio.create_task(self._wait_for_recovery(resource, limit))
```
