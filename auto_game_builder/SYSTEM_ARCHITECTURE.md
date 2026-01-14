# ゲーム自動生成システム アーキテクチャ設計

## 1. 設計思想

### 課題
- 生成AIは処理に時間がかかる（画像: 10-60秒、動画: 数分）
- GPUリソースは有限（VRAM競合問題）
- タスク間に依存関係がある
- 人間の監視・承認が必要な箇所がある

### 解決策
```
┌─────────────────────────────────────────────────────────────┐
│  非同期キューシステム + ワーカープール + 依存関係グラフ      │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. システム全体構成

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         オーケストレーター                               │
│                    (タスク管理・依存関係解決)                            │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
            ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
            │ タスクキュー │ │ タスクキュー │ │ タスクキュー │
            │   (GPU)     │ │   (CPU)     │ │  (外部API)  │
            └─────────────┘ └─────────────┘ └─────────────┘
                    │               │               │
        ┌───────────┼───────┐       │               │
        ▼           ▼       ▼       ▼               ▼
   ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
   │ComfyUI  │ │ComfyUI  │ │ Ollama  │ │VOICEVOX │ │ Suno    │
   │Worker 1 │ │Worker 2 │ │ Worker  │ │ Worker  │ │ Worker  │
   │(GPU:0)  │ │(GPU:1)  │ │(GPU/CPU)│ │ (CPU)   │ │ (Web)   │
   └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘
        │           │           │           │           │
        └───────────┴───────────┴───────────┴───────────┘
                                │
                    ┌───────────┴───────────┐
                    ▼                       ▼
            ┌─────────────┐         ┌─────────────┐
            │  アセット   │         │  メタデータ │
            │  ストレージ │         │    DB       │
            └─────────────┘         └─────────────┘
```

---

## 3. コンポーネント詳細

### 3.1 オーケストレーター (Orchestrator)

**役割**: 全体の司令塔。タスクの依存関係を解決し、適切なキューに投入

```python
# orchestrator/main.py 概念設計

class Orchestrator:
    def __init__(self):
        self.task_graph = TaskGraph()      # 依存関係グラフ
        self.queue_manager = QueueManager() # キュー管理
        self.state_store = StateStore()     # 状態管理

    def submit_project(self, project_config):
        """プロジェクト全体を受け取り、タスクに分解"""
        tasks = self.decompose_project(project_config)
        self.task_graph.build(tasks)
        self.schedule_ready_tasks()

    def schedule_ready_tasks(self):
        """依存関係が解決されたタスクをキューに投入"""
        ready_tasks = self.task_graph.get_ready_tasks()
        for task in ready_tasks:
            queue = self.select_queue(task)
            queue.enqueue(task)

    def on_task_complete(self, task_id, result):
        """タスク完了時のコールバック"""
        self.task_graph.mark_complete(task_id)
        self.state_store.save_result(task_id, result)
        self.schedule_ready_tasks()  # 次のタスクを投入
```

### 3.2 タスクキュー (Task Queues)

**3種類のキューで負荷分散**

| キュー名 | リソース | 処理内容 | 同時実行数 |
|---------|---------|---------|-----------|
| `gpu_queue` | GPU (VRAM) | ComfyUI画像/動画生成 | GPU数に依存 |
| `cpu_queue` | CPU/RAM | VOICEVOX, テキスト処理 | CPU コア数 |
| `api_queue` | ネットワーク | Suno, 外部API | レート制限に依存 |

```python
# queue/manager.py 概念設計

class QueueManager:
    def __init__(self):
        self.queues = {
            'gpu': PriorityQueue(maxsize=100),
            'cpu': PriorityQueue(maxsize=500),
            'api': RateLimitedQueue(rate=10/60)  # 10 req/min
        }

    def select_queue(self, task):
        """タスク種類に応じてキューを選択"""
        if task.type in ['image_gen', 'video_gen', 'animatediff']:
            return self.queues['gpu']
        elif task.type in ['voice_gen', 'text_gen', 'data_process']:
            return self.queues['cpu']
        elif task.type in ['bgm_gen', 'external_api']:
            return self.queues['api']
```

### 3.3 ワーカー (Workers)

**各ワーカーの特性**

| ワーカー | 処理時間 | VRAM使用 | 並列可否 | 備考 |
|---------|---------|---------|---------|------|
| ComfyUI (SDXL) | 10-30秒/枚 | 8-12GB | GPU毎に1 | LoRA切替にオーバーヘッド |
| ComfyUI (Flux) | 20-60秒/枚 | 12-16GB | GPU毎に1 | 高品質だが遅い |
| ComfyUI (AnimateDiff) | 1-5分/クリップ | 10-14GB | GPU毎に1 | 動画長に比例 |
| Ollama (8B) | 1-30秒/req | 6-8GB | 複数可 | コンテキスト長に依存 |
| VOICEVOX | 0.5-3秒/発話 | 2GB | 複数可 | 高速 |
| Suno (Web) | 30-120秒/曲 | - | レート制限 | 無料枠制限あり |

```python
# workers/comfyui_worker.py 概念設計

class ComfyUIWorker:
    def __init__(self, gpu_id, comfyui_url):
        self.gpu_id = gpu_id
        self.api = ComfyUIAPI(comfyui_url)
        self.current_workflow = None

    async def process(self, task):
        """タスクを処理"""
        workflow = self.load_workflow(task.workflow_type)
        workflow = self.inject_parameters(workflow, task.params)

        # 非同期で実行、進捗をポーリング
        prompt_id = await self.api.queue_prompt(workflow)
        result = await self.wait_for_completion(prompt_id)

        return self.save_output(result, task.output_path)

    async def wait_for_completion(self, prompt_id):
        """完了までポーリング"""
        while True:
            status = await self.api.get_status(prompt_id)
            if status['done']:
                return status['outputs']
            await asyncio.sleep(1)
```

---

## 4. 依存関係グラフ (DAG)

### 4.1 タスク依存関係の例

```
[ゲーム1本分の依存関係グラフ]

Level 0 (依存なし - 並列実行可能)
├── キャラ設定生成 (LLM)
├── 世界観設定生成 (LLM)
├── BGM生成 (Suno) ─────────────────────────────────────┐
└── SE生成 (AudioLDM) ──────────────────────────────────┤
                                                        │
Level 1 (Level 0に依存)                                 │
├── シナリオ生成 (LLM) ← キャラ設定, 世界観設定          │
├── キャラ立ち絵生成 (ComfyUI) ← キャラ設定             │
└── 背景画像生成 (ComfyUI) ← 世界観設定                 │
                                                        │
Level 2 (Level 1に依存)                                 │
├── ダイアログ生成 (LLM) ← シナリオ                     │
├── 表情差分生成 (ComfyUI) ← キャラ立ち絵               │
├── 衣装差分生成 (ComfyUI) ← キャラ立ち絵               │
└── 時間帯差分生成 (ComfyUI) ← 背景画像                 │
                                                        │
Level 3 (Level 2に依存)                                 │
├── ボイス生成 (VOICEVOX) ← ダイアログ                  │
└── イベントCG生成 (ComfyUI) ← キャラ立ち絵, 背景       │
                                                        │
Level 4 (Level 3に依存)                                 │
├── ゲームデータ統合 ← 全アセット                       │
└── ビルド・テスト ← ゲームデータ統合 ──────────────────┘
```

### 4.2 依存関係の定義形式

```yaml
# project_definition.yaml

tasks:
  # Level 0
  - id: char_setting
    type: llm_gen
    template: character_setting
    depends_on: []

  - id: world_setting
    type: llm_gen
    template: world_setting
    depends_on: []

  - id: bgm_title
    type: bgm_gen
    prompt: "Epic orchestral game title theme"
    depends_on: []

  # Level 1
  - id: scenario
    type: llm_gen
    template: main_scenario
    depends_on: [char_setting, world_setting]

  - id: char_image_hero
    type: image_gen
    workflow: character_fullbody
    depends_on: [char_setting]
    params:
      character: hero

  # Level 2
  - id: char_expression_hero
    type: image_gen
    workflow: expression_variation
    depends_on: [char_image_hero]
    params:
      expressions: [happy, sad, angry, surprised]

  # Level 3
  - id: voice_hero
    type: voice_gen
    depends_on: [scenario]
    params:
      character: hero
      speaker_id: 1
```

---

## 5. リソース競合の解決

### 5.1 GPUリソース管理

```
問題: ComfyUIとOllamaが同じGPUを使うとVRAM不足

解決策: 排他制御 + 優先度スケジューリング
```

```python
# resource/gpu_manager.py

class GPUResourceManager:
    def __init__(self, gpu_count):
        self.locks = [asyncio.Lock() for _ in range(gpu_count)]
        self.vram_usage = [0] * gpu_count

    async def acquire(self, gpu_id, vram_required):
        """GPUリソースを確保"""
        async with self.locks[gpu_id]:
            if self.vram_usage[gpu_id] + vram_required > MAX_VRAM:
                raise ResourceBusy("VRAM不足")
            self.vram_usage[gpu_id] += vram_required
            return GPUContext(self, gpu_id, vram_required)

    def release(self, gpu_id, vram_amount):
        """GPUリソースを解放"""
        self.vram_usage[gpu_id] -= vram_amount
```

### 5.2 推奨構成パターン

**パターンA: シングルGPU (RTX 4070 12GB)**
```
┌─────────────────────────────────────────┐
│ GPU 0 (12GB VRAM)                       │
├─────────────────────────────────────────┤
│ 時分割で排他利用:                        │
│  - ComfyUI SDXL (10GB) ← 画像生成時     │
│  - Ollama 8B (8GB) ← テキスト生成時      │
│                                         │
│ 同時実行不可 → キューで順次処理          │
└─────────────────────────────────────────┘
│
│ CPU並列 (常時稼働)
├── VOICEVOX Worker x4
├── データ処理 Worker x8
└── API Worker x2 (Suno等)
```

**パターンB: デュアルGPU (RTX 4090 x2)**
```
┌──────────────────┐  ┌──────────────────┐
│ GPU 0 (24GB)     │  │ GPU 1 (24GB)     │
├──────────────────┤  ├──────────────────┤
│ ComfyUI専用      │  │ ComfyUI専用      │
│ - SDXL Worker    │  │ - Flux Worker    │
│ - AnimateDiff    │  │ - 3D生成         │
└──────────────────┘  └──────────────────┘

┌──────────────────┐
│ CPU (Ollama)     │  ← GPUオフロードも可
├──────────────────┤
│ - Llama3 8B      │
│ - Qwen2.5-Coder  │
└──────────────────┘
```

**パターンC: 分散構成 (複数マシン)**
```
┌─────────────────────────────────────────────────────────┐
│                    メインサーバー                        │
│  - オーケストレーター                                    │
│  - タスクキュー (Redis)                                 │
│  - メタデータDB (PostgreSQL)                            │
│  - アセットストレージ (MinIO/S3)                         │
└─────────────────────────────────────────────────────────┘
              │
    ┌─────────┴─────────┬─────────────────┐
    ▼                   ▼                 ▼
┌─────────┐       ┌─────────┐       ┌─────────┐
│ Worker  │       │ Worker  │       │ Worker  │
│ Node 1  │       │ Node 2  │       │ Node 3  │
│ RTX4090 │       │ RTX4090 │       │ CPU専用  │
│ ComfyUI │       │ ComfyUI │       │ VOICEVOX│
└─────────┘       └─────────┘       │ Ollama  │
                                    └─────────┘
```

---

## 6. 並列処理戦略

### 6.1 最大並列化マトリクス

```
タスク種類ごとの並列可能性:

                    画像生成  動画生成  LLM    音声    BGM
画像生成 (GPU)        ✕        ✕       △      ◎      ◎
動画生成 (GPU)        ✕        ✕       △      ◎      ◎
LLM (GPU/CPU)         △        △       ◎      ◎      ◎
音声生成 (CPU)        ◎        ◎       ◎      ◎      ◎
BGM生成 (API)         ◎        ◎       ◎      ◎      ◎

◎: 完全並列可能
△: リソース状況による
✕: 排他 (同一GPU使用時)
```

### 6.2 スケジューリングアルゴリズム

```python
# scheduler/priority_scheduler.py

class PriorityScheduler:
    """
    優先度:
    1. クリティカルパス上のタスク (他の多くのタスクがブロックされる)
    2. 処理時間が長いタスク (早めに開始)
    3. GPUタスク (ボトルネック)
    """

    def calculate_priority(self, task, task_graph):
        score = 0

        # 依存されている数が多いほど優先
        dependents = task_graph.get_dependents(task.id)
        score += len(dependents) * 100

        # 処理時間が長いほど優先
        estimated_time = self.estimate_time(task)
        score += estimated_time * 10

        # GPUタスクは優先
        if task.resource_type == 'gpu':
            score += 50

        return score

    def get_next_task(self, queue, available_resources):
        """利用可能リソースで実行できる最優先タスクを取得"""
        candidates = []
        for task in queue:
            if self.can_run(task, available_resources):
                candidates.append((self.calculate_priority(task), task))

        if candidates:
            candidates.sort(reverse=True)
            return candidates[0][1]
        return None
```

---

## 7. 進捗監視とリカバリ

### 7.1 ダッシュボード

```
┌─────────────────────────────────────────────────────────────────┐
│ ゲーム自動生成システム - ダッシュボード                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ 全体進捗: ████████████░░░░░░░░ 58% (234/402 タスク完了)          │
│                                                                 │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ キュー状況                                                  │ │
│ │  GPU Queue:  ██████░░░░ 12 待機中 / 2 実行中               │ │
│ │  CPU Queue:  ███░░░░░░░  8 待機中 / 4 実行中               │ │
│ │  API Queue:  █░░░░░░░░░  3 待機中 / 1 実行中               │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                 │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ ワーカー状況                                                │ │
│ │  ComfyUI-0:  🟢 実行中 [char_hero_happy] 45%    ETA: 15s   │ │
│ │  ComfyUI-1:  🟢 実行中 [bg_forest_night] 78%    ETA: 8s    │ │
│ │  Ollama:     🟢 実行中 [dialog_ch3] 23%         ETA: 12s   │ │
│ │  VOICEVOX:   🟢 実行中 [voice_hero_023]         ETA: 2s    │ │
│ │  Suno:       🟡 待機中 (レート制限)             次回: 45s   │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                 │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ カテゴリ別進捗                                              │ │
│ │  キャラクター:  ████████████████░░░░ 80% (32/40)            │ │
│ │  背景:         ████████████░░░░░░░░ 60% (18/30)            │ │
│ │  UI:           ██████░░░░░░░░░░░░░░ 30% (12/40)            │ │
│ │  BGM:          ████████████████████ 100% (10/10)           │ │
│ │  SE:           ████████████████░░░░ 80% (40/50)            │ │
│ │  ボイス:       ████░░░░░░░░░░░░░░░░ 20% (50/250)           │ │
│ │  シナリオ:     ████████████████████ 100% (完了)            │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                 │
│ 推定残り時間: 2時間34分                                         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 7.2 エラーリカバリ

```python
# recovery/error_handler.py

class ErrorRecoveryHandler:
    MAX_RETRIES = 3

    async def handle_error(self, task, error):
        """エラー発生時の処理"""

        if task.retry_count < self.MAX_RETRIES:
            # リトライ可能なエラー
            if isinstance(error, (TimeoutError, ConnectionError, OOMError)):
                task.retry_count += 1
                delay = 2 ** task.retry_count  # exponential backoff
                await asyncio.sleep(delay)
                return RetryAction(task)

        # リトライ不可 or 上限到達
        if isinstance(error, OOMError):
            # VRAM不足: パラメータ調整して再試行
            task.params['batch_size'] = 1
            task.params['resolution'] = self.reduce_resolution(task)
            return RetryAction(task)

        # 回復不能: 人間に通知
        return EscalateAction(task, error)

    def reduce_resolution(self, task):
        """解像度を下げる"""
        current = task.params.get('resolution', 1024)
        return max(512, current - 256)
```

---

## 8. 実装技術スタック

### 8.1 推奨構成

```yaml
# docker-compose.yml 概念

services:
  orchestrator:
    build: ./orchestrator
    depends_on:
      - redis
      - postgres
    environment:
      - REDIS_URL=redis://redis:6379
      - DATABASE_URL=postgresql://postgres/gamebuilder

  redis:
    image: redis:7-alpine
    # タスクキュー

  postgres:
    image: postgres:16-alpine
    # メタデータ、タスク状態

  minio:
    image: minio/minio
    # アセットストレージ

  comfyui-worker:
    build: ./workers/comfyui
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

  voicevox-worker:
    build: ./workers/voicevox
    # CPU専用

  ollama-worker:
    build: ./workers/ollama
    # CPU or GPU

  dashboard:
    build: ./dashboard
    ports:
      - "8080:8080"
```

### 8.2 主要ライブラリ

| 用途 | ライブラリ | 理由 |
|-----|-----------|------|
| 非同期処理 | asyncio + aiohttp | Python標準、軽量 |
| タスクキュー | Redis + rq または Celery | シンプルで実績あり |
| DAG管理 | networkx | 依存関係グラフ処理 |
| API | FastAPI | 高速、型安全 |
| DB | SQLAlchemy + PostgreSQL | 堅牢 |
| ストレージ | MinIO (S3互換) | ローカルで動作 |
| 監視 | Prometheus + Grafana | 標準的 |

---

## 9. フェーズ別実装計画

### Phase 1: 最小構成 (MVP)

```
目標: 単一マシンで動作する基本パイプライン

実装:
├── シンプルなタスクキュー (Python asyncio.Queue)
├── ComfyUI Worker x1
├── VOICEVOX Worker x1
├── Ollama Worker x1
├── ローカルファイルストレージ
└── CLIダッシュボード

制約:
- GPU タスクは直列実行
- 手動リトライ
```

### Phase 2: 並列化

```
目標: 複数ワーカーの並列実行

追加実装:
├── Redis タスクキュー
├── 複数 ComfyUI Worker
├── 優先度スケジューラ
├── 自動リトライ
└── Web ダッシュボード
```

### Phase 3: スケーラブル

```
目標: 分散環境対応

追加実装:
├── PostgreSQL メタデータDB
├── MinIO アセットストレージ
├── 複数マシン対応
├── 高度な監視・アラート
└── 人間承認ワークフロー
```

---

## 10. ボトルネック対策まとめ

| ボトルネック | 対策 |
|-------------|------|
| GPU処理の遅さ | 複数GPU/マシン、優先度スケジューリング |
| VRAM競合 | 排他制御、タスク種類でGPU分離 |
| API レート制限 | キューでバッファ、夜間バッチ処理 |
| 依存関係の連鎖 | DAGで最大並列化、クリティカルパス優先 |
| エラーによる停止 | 自動リトライ、graceful degradation |
| 品質のばらつき | 自動品質チェック、人間レビューポイント |

---

*作成日: 2026-01-14*
*設計バージョン: 1.0*
