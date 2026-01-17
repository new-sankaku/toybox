"""
Mock Data Store and Generators
フロントエンドテスト用のモックデータ管理
リアルタイムシミュレーション対応
"""

import uuid
import threading
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
import random

from asset_scanner import scan_all_mock_data, get_mock_data_path
from agent_settings import get_default_quality_settings, QualityCheckConfig


class MockDataStore:
    """In-memory data store for mock backend with real-time simulation"""

    def __init__(self):
        self.projects: Dict[str, Dict] = {}
        self.agents: Dict[str, Dict] = {}
        self.checkpoints: Dict[str, Dict] = {}
        self.agent_logs: Dict[str, List[Dict]] = {}
        self.system_logs: Dict[str, List[Dict]] = {}  # Per project
        self.metrics: Dict[str, Dict] = {}
        self.assets: Dict[str, List[Dict]] = {}  # Per project assets
        self.subscriptions: Dict[str, set] = {}
        self.quality_settings: Dict[str, Dict[str, QualityCheckConfig]] = {}  # Per project

        # Simulation state
        self._simulation_running = False
        self._simulation_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        self._init_sample_data()

    def _init_sample_data(self):
        """Initialize with single comprehensive project"""

        proj_id = "proj-001"
        now = datetime.now()

        self.projects[proj_id] = {
            "id": proj_id,
            "name": "パズルアクションゲーム",
            "description": "物理演算を使ったパズルゲーム。ボールを転がして障害物を避けながらゴールを目指す。",
            "concept": {
                "description": "ボールを転がしてゴールを目指すパズル。重力や摩擦をリアルに再現。",
                "platform": "web",
                "scope": "mvp",
                "genre": "Puzzle",
                "targetAudience": "全年齢"
            },
            "status": "draft",  # Start as draft, user starts it
            "currentPhase": 1,
            "state": {},
            "config": {
                "maxTokensPerAgent": 100000,
                "enableAutoApproval": False,
                "llmProvider": "mock"
            },
            "createdAt": now.isoformat(),
            "updatedAt": now.isoformat()
        }

        # Create agents - all pending initially (Phase 1 Leaders)
        agents_data = [
            {"type": "concept_leader", "name": "コンセプト定義"},
            {"type": "design_leader", "name": "ゲームデザイン"},
            {"type": "scenario_leader", "name": "シナリオ作成"},
            {"type": "character_leader", "name": "キャラクターデザイン"},
            {"type": "world_leader", "name": "ワールドビルディング"},
            {"type": "task_split_leader", "name": "タスク分割"},
        ]

        for data in agents_data:
            agent_id = f"agent-{proj_id}-{data['type']}"
            self.agents[agent_id] = {
                "id": agent_id,
                "projectId": proj_id,
                "type": data["type"],
                "status": "pending",
                "progress": 0,
                "currentTask": None,
                "tokensUsed": 0,
                "startedAt": None,
                "completedAt": None,
                "error": None,
                "parentAgentId": None,
                "metadata": {"displayName": data["name"]},
                "createdAt": now.isoformat()
            }
            self.agent_logs[agent_id] = []

        # Initialize logs and metrics
        self.system_logs[proj_id] = []

        # Load real assets from mock_data folder
        mock_data_path = get_mock_data_path()
        real_assets = scan_all_mock_data(mock_data_path)
        self.assets[proj_id] = real_assets
        print(f"[MockDataStore] Loaded {len(real_assets)} real assets")

        self.metrics[proj_id] = {
            "projectId": proj_id,
            "totalTokensUsed": 0,
            "estimatedTotalTokens": 50000,
            "elapsedTimeSeconds": 0,
            "estimatedRemainingSeconds": 0,
            "estimatedEndTime": None,
            "completedTasks": 0,
            "totalTasks": 6,
            "progressPercent": 0,
            "currentPhase": 1,
            "phaseName": "Phase 1: 企画・設計",
            "activeGenerations": 0
        }

    # ===== Simulation Engine =====

    def start_simulation(self):
        """Start background simulation thread"""
        if self._simulation_running:
            return

        self._simulation_running = True
        self._simulation_thread = threading.Thread(target=self._simulation_loop, daemon=True)
        self._simulation_thread.start()
        print("[Simulation] Started")

    def stop_simulation(self):
        """Stop background simulation"""
        self._simulation_running = False
        if self._simulation_thread:
            self._simulation_thread.join(timeout=2)
        print("[Simulation] Stopped")

    def _simulation_loop(self):
        """Main simulation loop - runs every second"""
        while self._simulation_running:
            try:
                with self._lock:
                    self._tick_simulation()
            except Exception as e:
                print(f"[Simulation] Error: {e}")
            time.sleep(1)

    def _tick_simulation(self):
        """Process one simulation tick for all running projects"""
        for project_id, project in list(self.projects.items()):
            if project["status"] == "running":
                self._simulate_project(project_id)

    def _simulate_project(self, project_id: str):
        """Simulate one tick for a project"""
        project = self.projects.get(project_id)
        if not project:
            return

        agents = [a for a in self.agents.values() if a["projectId"] == project_id]
        running_agent = next((a for a in agents if a["status"] == "running"), None)

        if running_agent:
            self._simulate_agent(running_agent)
        else:
            # Start next pending agent
            pending_agents = [a for a in agents if a["status"] == "pending"]
            if pending_agents:
                self._start_agent(pending_agents[0])
            else:
                # All agents done - check if project complete
                completed = all(a["status"] == "completed" for a in agents)
                if completed:
                    project["status"] = "completed"
                    project["updatedAt"] = datetime.now().isoformat()
                    self._add_system_log(project_id, "info", "System", "プロジェクト完了！")

        # Update metrics
        self._update_project_metrics(project_id)

    def _start_agent(self, agent: Dict):
        """Start an agent"""
        now = datetime.now()
        agent["status"] = "running"
        agent["progress"] = 0
        agent["startedAt"] = now.isoformat()
        agent["currentTask"] = self._get_initial_task(agent["type"])

        # Add logs
        display_name = agent["metadata"].get("displayName", agent["type"])
        self._add_agent_log(agent["id"], "info", f"{display_name}エージェント起動", 0)
        self._add_system_log(agent["projectId"], "info", agent["type"], f"{display_name}開始")

    def _simulate_agent(self, agent: Dict):
        """Simulate one tick for a running agent"""
        # Progress increment (2-5% per second)
        increment = random.randint(2, 5)
        new_progress = min(100, agent["progress"] + increment)

        # Token increment
        token_increment = random.randint(30, 80)
        agent["tokensUsed"] += token_increment

        # Check for milestone logs
        old_progress = agent["progress"]
        agent["progress"] = new_progress

        # Update current task based on progress
        agent["currentTask"] = self._get_task_for_progress(agent["type"], new_progress)

        # Add progress logs at milestones
        self._check_milestone_logs(agent, old_progress, new_progress)

        # Check for checkpoint creation
        self._check_checkpoint_creation(agent, old_progress, new_progress)

        # Check for asset generation
        self._check_asset_generation(agent, old_progress, new_progress)

        # Check completion
        if new_progress >= 100:
            self._complete_agent(agent)

    def _complete_agent(self, agent: Dict):
        """Mark agent as completed"""
        now = datetime.now()
        agent["status"] = "completed"
        agent["progress"] = 100
        agent["completedAt"] = now.isoformat()
        agent["currentTask"] = None

        display_name = agent["metadata"].get("displayName", agent["type"])
        self._add_agent_log(agent["id"], "info", f"{display_name}完了", 100)
        self._add_system_log(agent["projectId"], "info", agent["type"], f"{display_name}完了")

    def _check_milestone_logs(self, agent: Dict, old_progress: int, new_progress: int):
        """Add logs at milestone progress points"""
        milestones = self._get_milestones(agent["type"])

        for milestone_progress, level, message in milestones:
            if old_progress < milestone_progress <= new_progress:
                self._add_agent_log(agent["id"], level, message, milestone_progress)
                if level in ("warn", "error"):
                    self._add_system_log(agent["projectId"], level, agent["type"], message)

    def _check_checkpoint_creation(self, agent: Dict, old_progress: int, new_progress: int):
        """Create checkpoints at certain progress points"""
        checkpoint_points = self._get_checkpoint_points(agent["type"])

        for cp_progress, cp_type, cp_title in checkpoint_points:
            if old_progress < cp_progress <= new_progress:
                # Check if checkpoint already exists
                existing = [c for c in self.checkpoints.values()
                           if c["agentId"] == agent["id"] and c["type"] == cp_type]
                if not existing:
                    self._create_agent_checkpoint(agent, cp_type, cp_title)

    def _create_agent_checkpoint(self, agent: Dict, cp_type: str, title: str):
        """Create a checkpoint for an agent"""
        checkpoint_id = f"cp-{uuid.uuid4().hex[:8]}"
        now = datetime.now().isoformat()

        content = self._generate_checkpoint_content(agent["type"], cp_type)

        checkpoint = {
            "id": checkpoint_id,
            "projectId": agent["projectId"],
            "agentId": agent["id"],
            "type": cp_type,
            "title": title,
            "description": f"{agent['metadata'].get('displayName', agent['type'])}の成果物を確認してください",
            "output": {
                "type": "document",
                "format": "markdown",
                "content": content
            },
            "status": "pending",
            "feedback": None,
            "resolvedAt": None,
            "createdAt": now,
            "updatedAt": now
        }
        self.checkpoints[checkpoint_id] = checkpoint

        self._add_system_log(agent["projectId"], "info", "System", f"チェックポイント作成: {title}")

    def _check_asset_generation(self, agent: Dict, old_progress: int, new_progress: int):
        """Generate assets at certain progress points"""
        asset_points = self._get_asset_points(agent["type"])

        for point_progress, asset_type, asset_name, asset_size in asset_points:
            if old_progress < point_progress <= new_progress:
                # Check if asset already exists
                project_id = agent["projectId"]
                existing = [a for a in self.assets.get(project_id, [])
                           if a["name"] == asset_name and a["agent"] == agent["metadata"].get("displayName", agent["type"])]
                if not existing:
                    self._create_asset(agent, asset_type, asset_name, asset_size)

    def _create_asset(self, agent: Dict, asset_type: str, name: str, size: str):
        """Create an asset"""
        project_id = agent["projectId"]
        if project_id not in self.assets:
            self.assets[project_id] = []

        # Determine URL based on asset type
        if asset_type == "image":
            url = f"/assets/{name}"
            thumbnail = f"/thumbnails/{name}"
        elif asset_type == "audio":
            url = f"/assets/{name}"
            thumbnail = None
        else:
            url = None
            thumbnail = None

        asset = {
            "id": f"asset-{uuid.uuid4().hex[:8]}",
            "name": name,
            "type": asset_type,
            "agent": agent["metadata"].get("displayName", agent["type"]),
            "size": size,
            "createdAt": datetime.now().isoformat(),
            "url": url,
            "thumbnail": thumbnail,
            "duration": self._random_duration() if asset_type == "audio" else None,
            "approvalStatus": "pending"
        }
        self.assets[project_id].append(asset)

        display_name = agent["metadata"].get("displayName", agent["type"])
        self._add_system_log(project_id, "info", display_name, f"アセット生成: {name}")

    def _random_duration(self) -> str:
        """Generate random audio duration"""
        seconds = random.randint(5, 180)
        mins = seconds // 60
        secs = seconds % 60
        return f"{mins}:{secs:02d}"

    def _get_asset_points(self, agent_type: str) -> List[tuple]:
        """Get asset generation points: (progress, type, name, size)"""
        assets = {
            "concept_leader": [
                (50, "document", "concept_draft.md", "12KB"),
                (90, "document", "concept_final.md", "28KB"),
            ],
            "design_leader": [
                (30, "document", "mechanics_spec.md", "18KB"),
                (45, "image", "ui_wireframe_01.png", "245KB"),
                (55, "image", "ui_wireframe_02.png", "312KB"),
                (70, "document", "sound_spec.md", "8KB"),
                (80, "audio", "bgm_title.wav", "1.2MB"),
                (85, "audio", "se_click.wav", "24KB"),
                (95, "document", "design_final.md", "42KB"),
            ],
            "scenario_leader": [
                (40, "document", "story_outline.md", "15KB"),
                (70, "document", "stage_design.md", "22KB"),
                (90, "document", "dialogue_script.md", "35KB"),
            ],
            "character_leader": [
                (35, "image", "ball_concept.png", "156KB"),
                (50, "image", "ball_sprite_sheet.png", "512KB"),
                (65, "image", "guide_character.png", "234KB"),
                (80, "image", "boss_enemy.png", "445KB"),
                (95, "document", "character_specs.md", "18KB"),
            ],
            "world_leader": [
                (25, "image", "bg_grassland.png", "1.8MB"),
                (45, "image", "bg_cave.png", "2.1MB"),
                (60, "image", "bg_sky.png", "1.6MB"),
                (75, "audio", "bgm_grassland.wav", "3.2MB"),
                (85, "audio", "bgm_cave.wav", "2.8MB"),
                (95, "audio", "bgm_sky.wav", "3.5MB"),
            ],
            "task_split_leader": [
                (50, "document", "task_breakdown.md", "25KB"),
                (90, "document", "iteration_plan.md", "35KB"),
            ],
        }
        return assets.get(agent_type, [])

    def _update_project_metrics(self, project_id: str):
        """Update project metrics"""
        agents = [a for a in self.agents.values() if a["projectId"] == project_id]

        total_tokens = sum(a["tokensUsed"] for a in agents)
        completed_count = len([a for a in agents if a["status"] == "completed"])
        total_count = len(agents)

        # Calculate overall progress
        total_progress = sum(a["progress"] for a in agents)
        overall_progress = int(total_progress / total_count) if total_count > 0 else 0

        # Time estimation
        running_agent = next((a for a in agents if a["status"] == "running"), None)
        if running_agent and running_agent["progress"] > 0:
            elapsed = (datetime.now() - datetime.fromisoformat(running_agent["startedAt"])).total_seconds()
            rate = running_agent["progress"] / elapsed if elapsed > 0 else 1
            remaining_progress = 100 - running_agent["progress"]
            remaining_agents = len([a for a in agents if a["status"] == "pending"])
            estimated_remaining = (remaining_progress / rate) + (remaining_agents * 100 / rate) if rate > 0 else 0
        else:
            estimated_remaining = 0

        # Count active generations (running agents doing LLM work)
        active_generations = len([a for a in agents if a["status"] == "running"])

        self.metrics[project_id] = {
            "projectId": project_id,
            "totalTokensUsed": total_tokens,
            "estimatedTotalTokens": 50000,
            "elapsedTimeSeconds": int((datetime.now() - datetime.fromisoformat(self.projects[project_id]["createdAt"])).total_seconds()),
            "estimatedRemainingSeconds": int(estimated_remaining),
            "estimatedEndTime": (datetime.now() + timedelta(seconds=estimated_remaining)).isoformat() if estimated_remaining > 0 else None,
            "completedTasks": completed_count,
            "totalTasks": total_count,
            "progressPercent": overall_progress,
            "currentPhase": 1,
            "phaseName": "Phase 1: 企画・設計",
            "activeGenerations": active_generations
        }

    # ===== Task and Log Templates =====

    def _get_initial_task(self, agent_type: str) -> str:
        tasks = {
            "concept_leader": "プロジェクト要件を分析中...",
            "design_leader": "コンセプトドキュメントを読み込み中...",
            "scenario_leader": "ストーリー構成を検討中...",
            "character_leader": "キャラクター設定を分析中...",
            "world_leader": "世界観設定を構築中...",
            "task_split_leader": "タスク分解を開始中...",
        }
        return tasks.get(agent_type, "処理中...")

    def _get_task_for_progress(self, agent_type: str, progress: int) -> str:
        tasks = {
            "concept_leader": [
                (0, "プロジェクト要件を分析中..."),
                (20, "コアコンセプトを定義中..."),
                (40, "ターゲットユーザーを分析中..."),
                (60, "コンセプトドキュメント作成中..."),
                (80, "最終確認中..."),
            ],
            "design_leader": [
                (0, "コンセプトドキュメントを読み込み中..."),
                (15, "ゲームメカニクスを設計中..."),
                (30, "操作スキームを定義中..."),
                (50, "UI/UXを設計中..."),
                (70, "サウンドデザイン仕様を作成中..."),
                (85, "最終レビュー中..."),
            ],
            "scenario_leader": [
                (0, "ストーリー構成を検討中..."),
                (25, "メインプロットを執筆中..."),
                (50, "ステージ構成を設計中..."),
                (75, "テキスト最終調整中..."),
            ],
            "character_leader": [
                (0, "キャラクター設定を分析中..."),
                (30, "メインキャラクターをデザイン中..."),
                (60, "サブキャラクターをデザイン中..."),
                (85, "最終調整中..."),
            ],
            "world_leader": [
                (0, "世界観設定を構築中..."),
                (25, "背景設定を作成中..."),
                (50, "ステージビジュアルを設計中..."),
                (75, "環境エフェクトを定義中..."),
            ],
            "task_split_leader": [
                (0, "企画成果物を分析中..."),
                (25, "タスクを分解中..."),
                (50, "依存関係を分析中..."),
                (75, "スケジュールを作成中..."),
            ],
        }

        agent_tasks = tasks.get(agent_type, [(0, "処理中...")])
        current_task = agent_tasks[0][1]
        for threshold, task in agent_tasks:
            if progress >= threshold:
                current_task = task
        return current_task

    def _get_milestones(self, agent_type: str) -> List[tuple]:
        """Get log milestones for agent type: (progress, level, message)"""
        milestones = {
            "concept_leader": [
                (10, "info", "プロジェクト要件の分析完了"),
                (30, "info", "コアコンセプト定義完了"),
                (50, "debug", "ターゲットユーザー分析中"),
                (70, "info", "コンセプトドキュメント生成開始"),
                (90, "info", "最終確認中"),
            ],
            "design_leader": [
                (10, "info", "コンセプトドキュメント読み込み完了"),
                (25, "info", "ゲームメカニクス設計開始"),
                (40, "debug", "操作スキーム定義中"),
                (55, "warn", "複雑なUI要素を検出 - 簡素化を検討"),
                (70, "info", "サウンドデザイン仕様作成中"),
                (85, "info", "最終レビュー開始"),
            ],
            "scenario_leader": [
                (15, "info", "ストーリー構成確定"),
                (40, "info", "メインプロット執筆中"),
                (60, "debug", "ステージ構成を調整中"),
                (85, "info", "テキスト最終調整"),
            ],
            "character_leader": [
                (20, "info", "キャラクター設定分析完了"),
                (50, "info", "メインキャラクターデザイン完了"),
                (75, "info", "サブキャラクターデザイン中"),
            ],
            "world_leader": [
                (15, "info", "世界観ベース構築完了"),
                (40, "info", "背景設定作成中"),
                (65, "info", "ステージビジュアル設計中"),
                (85, "debug", "環境エフェクト定義中"),
            ],
            "task_split_leader": [
                (15, "info", "企画成果物の分析完了"),
                (40, "info", "タスク分解完了"),
                (65, "info", "依存関係分析中"),
                (85, "info", "スケジュール作成中"),
            ],
        }
        return milestones.get(agent_type, [])

    def _get_checkpoint_points(self, agent_type: str) -> List[tuple]:
        """Get checkpoint creation points: (progress, type, title)"""
        checkpoints = {
            "concept_leader": [
                (90, "concept_review", "ゲームコンセプトの承認"),
            ],
            "design_leader": [
                (60, "design_review", "ゲームデザインドキュメントのレビュー"),
                (95, "ui_review", "UI設計の確認"),
            ],
            "scenario_leader": [
                (85, "scenario_review", "シナリオのレビュー"),
            ],
            "character_leader": [
                (90, "character_review", "キャラクターデザインの確認"),
            ],
            "world_leader": [
                (90, "world_review", "ワールド設計の確認"),
            ],
            "task_split_leader": [
                (90, "task_review", "タスク分割のレビュー"),
            ],
        }
        return checkpoints.get(agent_type, [])

    def _generate_checkpoint_content(self, agent_type: str, cp_type: str) -> str:
        """Generate checkpoint content"""
        contents = {
            "concept_review": """# ゲームコンセプト

## 概要
ボールを操作してゴールを目指すシンプルなパズルゲーム。

## 特徴
- 物理演算ベースのリアルな挙動
- 全30ステージ
- スコアシステム（タイム + コイン収集）

## ターゲット
全年齢向け、カジュアルゲーマー""",

            "design_review": """# ゲームデザイン

## 操作方法
- 矢印キー: ボールの移動
- スペースキー: ジャンプ
- R: リスタート

## 物理パラメータ
- 重力: 9.8 m/s²
- 摩擦係数: 0.3
- 反発係数: 0.7""",

            "ui_review": """# UI設計

## 画面構成
1. タイトル画面
2. ステージ選択
3. ゲームプレイ
4. リザルト画面

## HUD要素
- タイマー（右上）
- コイン数（左上）
- ポーズボタン（右上）""",

            "scenario_review": """# シナリオ

## ストーリー
小さなボールが大きな冒険に出る物語。
様々な障害物を乗り越えながら、最終目的地を目指す。

## ステージ構成
- ワールド1: 草原（チュートリアル）
- ワールド2: 洞窟
- ワールド3: 空中庭園""",

            "character_review": """# キャラクターデザイン

## メインキャラクター
- ボール: プレイヤー操作キャラ
- 表情変化あり（喜怒哀楽）

## サブキャラクター
- ガイドキャラ: チュートリアル担当
- ボスキャラ: 各ワールドボス""",

            "world_review": """# ワールドビルディング

## 世界観
ファンタジー × 物理パズル

## ステージテーマ
- 草原: 明るく開放的
- 洞窟: 暗めでミステリアス
- 空中: 浮遊感と開放感"""
        }
        return contents.get(cp_type, f"# {cp_type}\n\n内容を確認してください。")

    # ===== Log Management =====

    def _add_agent_log(self, agent_id: str, level: str, message: str, progress: Optional[int] = None):
        """Add log entry to agent"""
        if agent_id not in self.agent_logs:
            self.agent_logs[agent_id] = []

        log_entry = {
            "id": f"log-{uuid.uuid4().hex[:8]}",
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "message": message,
            "progress": progress,
            "metadata": {}
        }
        self.agent_logs[agent_id].append(log_entry)

    def _add_system_log(self, project_id: str, level: str, source: str, message: str):
        """Add system log entry"""
        if project_id not in self.system_logs:
            self.system_logs[project_id] = []

        log_entry = {
            "id": f"syslog-{uuid.uuid4().hex[:8]}",
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "source": source,
            "message": message,
            "details": None
        }
        self.system_logs[project_id].append(log_entry)

    # ===== Project CRUD =====

    def get_projects(self) -> List[Dict]:
        with self._lock:
            return list(self.projects.values())

    def get_project(self, project_id: str) -> Optional[Dict]:
        with self._lock:
            return self.projects.get(project_id)

    def create_project(self, data: Dict) -> Dict:
        with self._lock:
            project_id = f"proj-{uuid.uuid4().hex[:8]}"
            now = datetime.now().isoformat()
            project = {
                "id": project_id,
                "name": data.get("name", "新規プロジェクト"),
                "description": data.get("description", ""),
                "concept": data.get("concept", {}),
                "status": "draft",
                "currentPhase": 1,
                "state": {},
                "config": data.get("config", {}),
                "createdAt": now,
                "updatedAt": now
            }
            self.projects[project_id] = project
            self.system_logs[project_id] = []
            return project

    def update_project(self, project_id: str, data: Dict) -> Optional[Dict]:
        with self._lock:
            if project_id not in self.projects:
                return None
            project = self.projects[project_id]
            project.update(data)
            project["updatedAt"] = datetime.now().isoformat()
            return project

    def delete_project(self, project_id: str) -> bool:
        with self._lock:
            if project_id in self.projects:
                del self.projects[project_id]
                self.agents = {k: v for k, v in self.agents.items() if v["projectId"] != project_id}
                self.checkpoints = {k: v for k, v in self.checkpoints.items() if v["projectId"] != project_id}
                if project_id in self.metrics:
                    del self.metrics[project_id]
                if project_id in self.system_logs:
                    del self.system_logs[project_id]
                return True
            return False

    def start_project(self, project_id: str) -> Optional[Dict]:
        """Start a project - begins simulation"""
        with self._lock:
            project = self.projects.get(project_id)
            if not project:
                return None

            if project["status"] in ("draft", "paused"):
                project["status"] = "running"
                project["updatedAt"] = datetime.now().isoformat()
                self._add_system_log(project_id, "info", "System", "プロジェクト開始")
            return project

    def pause_project(self, project_id: str) -> Optional[Dict]:
        """Pause a project"""
        with self._lock:
            project = self.projects.get(project_id)
            if not project:
                return None

            if project["status"] == "running":
                project["status"] = "paused"
                project["updatedAt"] = datetime.now().isoformat()
                self._add_system_log(project_id, "info", "System", "プロジェクト一時停止")
            return project

    def resume_project(self, project_id: str) -> Optional[Dict]:
        """Resume a paused project"""
        with self._lock:
            project = self.projects.get(project_id)
            if not project:
                return None

            if project["status"] == "paused":
                project["status"] = "running"
                project["updatedAt"] = datetime.now().isoformat()
                self._add_system_log(project_id, "info", "System", "プロジェクト再開")
            return project

    def initialize_project(self, project_id: str) -> Optional[Dict]:
        """Initialize/reset a project - clears all agents, checkpoints, logs, assets, metrics"""
        with self._lock:
            project = self.projects.get(project_id)
            if not project:
                return None

            now = datetime.now()

            # Reset project status
            project["status"] = "draft"
            project["currentPhase"] = 1
            project["updatedAt"] = now.isoformat()

            # Clear agents and recreate
            self.agents = {k: v for k, v in self.agents.items() if v["projectId"] != project_id}
            self.agent_logs = {k: v for k, v in self.agent_logs.items() if not k.startswith(f"agent-{project_id}")}

            # Recreate initial agents (Phase 1 Leaders)
            agents_data = [
                {"type": "concept_leader", "name": "コンセプト定義"},
                {"type": "design_leader", "name": "ゲームデザイン"},
                {"type": "scenario_leader", "name": "シナリオ作成"},
                {"type": "character_leader", "name": "キャラクターデザイン"},
                {"type": "world_leader", "name": "ワールドビルディング"},
                {"type": "task_split_leader", "name": "タスク分割"},
            ]

            for data in agents_data:
                agent_id = f"agent-{project_id}-{data['type']}"
                self.agents[agent_id] = {
                    "id": agent_id,
                    "projectId": project_id,
                    "type": data["type"],
                    "status": "pending",
                    "progress": 0,
                    "currentTask": None,
                    "tokensUsed": 0,
                    "startedAt": None,
                    "completedAt": None,
                    "error": None,
                    "parentAgentId": None,
                    "metadata": {"displayName": data["name"]},
                    "createdAt": now.isoformat()
                }
                self.agent_logs[agent_id] = []

            # Clear checkpoints for this project
            self.checkpoints = {k: v for k, v in self.checkpoints.items() if v["projectId"] != project_id}

            # Clear system logs
            self.system_logs[project_id] = []

            # Reload assets from disk
            mock_data_path = get_mock_data_path()
            real_assets = scan_all_mock_data(mock_data_path)
            self.assets[project_id] = real_assets

            # Reset metrics
            self.metrics[project_id] = {
                "projectId": project_id,
                "totalTokensUsed": 0,
                "estimatedTotalTokens": 50000,
                "elapsedTimeSeconds": 0,
                "estimatedRemainingSeconds": 0,
                "estimatedEndTime": None,
                "completedTasks": 0,
                "totalTasks": 6,
                "progressPercent": 0,
                "currentPhase": 1,
                "phaseName": "Phase 1: 企画・設計",
                "activeGenerations": 0
            }

            self._add_system_log(project_id, "info", "System", "プロジェクト初期化完了")
            print(f"[MockDataStore] Project {project_id} initialized")
            return project

    # ===== Agent Operations =====

    def get_agents_by_project(self, project_id: str) -> List[Dict]:
        with self._lock:
            return [a for a in self.agents.values() if a["projectId"] == project_id]

    def get_agent(self, agent_id: str) -> Optional[Dict]:
        with self._lock:
            return self.agents.get(agent_id)

    def get_agent_logs(self, agent_id: str) -> List[Dict]:
        with self._lock:
            return self.agent_logs.get(agent_id, [])

    def create_agent(self, project_id: str, agent_type: str) -> Dict:
        with self._lock:
            agent_id = f"agent-{uuid.uuid4().hex[:8]}"
            now = datetime.now().isoformat()
            agent = {
                "id": agent_id,
                "projectId": project_id,
                "type": agent_type,
                "status": "pending",
                "progress": 0,
                "currentTask": None,
                "tokensUsed": 0,
                "startedAt": None,
                "completedAt": None,
                "error": None,
                "parentAgentId": None,
                "metadata": {},
                "createdAt": now
            }
            self.agents[agent_id] = agent
            self.agent_logs[agent_id] = []
            return agent

    def update_agent(self, agent_id: str, data: Dict) -> Optional[Dict]:
        with self._lock:
            if agent_id not in self.agents:
                return None
            self.agents[agent_id].update(data)
            return self.agents[agent_id]

    def add_agent_log(self, agent_id: str, level: str, message: str, progress: Optional[int] = None):
        with self._lock:
            self._add_agent_log(agent_id, level, message, progress)

    # ===== Checkpoint Operations =====

    def get_checkpoints_by_project(self, project_id: str) -> List[Dict]:
        with self._lock:
            return [c for c in self.checkpoints.values() if c["projectId"] == project_id]

    def get_checkpoint(self, checkpoint_id: str) -> Optional[Dict]:
        with self._lock:
            return self.checkpoints.get(checkpoint_id)

    def create_checkpoint(self, project_id: str, agent_id: str, data: Dict) -> Dict:
        with self._lock:
            checkpoint_id = f"cp-{uuid.uuid4().hex[:8]}"
            now = datetime.now().isoformat()
            checkpoint = {
                "id": checkpoint_id,
                "projectId": project_id,
                "agentId": agent_id,
                "type": data.get("type", "review"),
                "title": data.get("title", "レビュー依頼"),
                "description": data.get("description"),
                "output": data.get("output", {}),
                "status": "pending",
                "feedback": None,
                "resolvedAt": None,
                "createdAt": now,
                "updatedAt": now
            }
            self.checkpoints[checkpoint_id] = checkpoint
            return checkpoint

    def resolve_checkpoint(self, checkpoint_id: str, resolution: str, feedback: Optional[str] = None) -> Optional[Dict]:
        with self._lock:
            if checkpoint_id not in self.checkpoints:
                return None
            checkpoint = self.checkpoints[checkpoint_id]
            now = datetime.now().isoformat()
            checkpoint["status"] = resolution
            checkpoint["feedback"] = feedback
            checkpoint["resolvedAt"] = now
            checkpoint["updatedAt"] = now

            # Add system log
            project_id = checkpoint["projectId"]
            status_text = {"approved": "承認", "rejected": "却下", "revision_requested": "修正要求"}
            self._add_system_log(project_id, "info", "System",
                               f"チェックポイント{status_text.get(resolution, resolution)}: {checkpoint['title']}")

            # Check if all Phase 1 checkpoints are approved to advance to Phase 2
            if resolution == "approved":
                self._check_phase_advancement(project_id)

            return checkpoint

    def _check_phase_advancement(self, project_id: str):
        """Check if we should advance to the next phase"""
        project = self.projects.get(project_id)
        if not project:
            return

        current_phase = project.get("currentPhase", 1)
        project_checkpoints = [c for c in self.checkpoints.values() if c["projectId"] == project_id]

        # Phase 1 checkpoint types (from all Phase 1 Leaders)
        phase1_types = {"concept_review", "design_review", "scenario_review", "character_review", "world_review", "task_review"}

        if current_phase == 1:
            # Check if all phase 1 checkpoints are approved
            phase1_checkpoints = [c for c in project_checkpoints if c["type"] in phase1_types]
            if phase1_checkpoints and all(c["status"] == "approved" for c in phase1_checkpoints):
                # Advance to Phase 2
                project["currentPhase"] = 2
                project["updatedAt"] = datetime.now().isoformat()

                # Update metrics
                if project_id in self.metrics:
                    self.metrics[project_id]["currentPhase"] = 2
                    self.metrics[project_id]["phaseName"] = "Phase 2: 実装"

                self._add_system_log(project_id, "info", "System", "Phase 2: 実装 に移行しました")
                print(f"[MockDataStore] Project {project_id} advanced to Phase 2")

    # ===== System Logs =====

    def get_system_logs(self, project_id: str) -> List[Dict]:
        with self._lock:
            return self.system_logs.get(project_id, [])

    # ===== Asset Operations =====

    def get_assets_by_project(self, project_id: str) -> List[Dict]:
        with self._lock:
            return self.assets.get(project_id, [])

    def update_asset(self, project_id: str, asset_id: str, data: Dict) -> Optional[Dict]:
        with self._lock:
            assets = self.assets.get(project_id, [])
            for asset in assets:
                if asset["id"] == asset_id:
                    asset.update(data)
                    return asset
            return None

    # ===== Metrics Operations =====

    def get_project_metrics(self, project_id: str) -> Optional[Dict]:
        with self._lock:
            return self.metrics.get(project_id)

    def update_project_metrics(self, project_id: str, data: Dict) -> Dict:
        with self._lock:
            if project_id not in self.metrics:
                self.metrics[project_id] = {
                    "projectId": project_id,
                    "totalTokensUsed": 0,
                    "estimatedTotalTokens": 50000,
                    "elapsedTimeSeconds": 0,
                    "estimatedRemainingSeconds": 0,
                    "estimatedEndTime": None,
                    "completedTasks": 0,
                    "totalTasks": 0,
                    "progressPercent": 0,
                    "currentPhase": 1,
                    "phaseName": "Phase 1: 企画・設計",
                    "activeGenerations": 0
                }
            self.metrics[project_id].update(data)
            return self.metrics[project_id]

    # ===== Subscription Management =====

    def add_subscription(self, project_id: str, sid: str):
        with self._lock:
            if project_id not in self.subscriptions:
                self.subscriptions[project_id] = set()
            self.subscriptions[project_id].add(sid)

    def remove_subscription(self, project_id: str, sid: str):
        with self._lock:
            if project_id in self.subscriptions:
                self.subscriptions[project_id].discard(sid)

    def remove_all_subscriptions(self, sid: str):
        with self._lock:
            for project_id in self.subscriptions:
                self.subscriptions[project_id].discard(sid)

    def get_subscribers(self, project_id: str) -> set:
        with self._lock:
            return self.subscriptions.get(project_id, set()).copy()

    # ===== Quality Settings Operations =====

    def get_quality_settings(self, project_id: str) -> Dict[str, QualityCheckConfig]:
        """プロジェクトの品質チェック設定を取得"""
        with self._lock:
            if project_id not in self.quality_settings:
                # デフォルト設定で初期化
                self.quality_settings[project_id] = get_default_quality_settings()
            return self.quality_settings[project_id].copy()

    def set_quality_setting(
        self,
        project_id: str,
        agent_type: str,
        config: QualityCheckConfig
    ) -> None:
        """単一エージェントの品質チェック設定を更新"""
        with self._lock:
            if project_id not in self.quality_settings:
                self.quality_settings[project_id] = get_default_quality_settings()
            self.quality_settings[project_id][agent_type] = config

    def reset_quality_settings(self, project_id: str) -> None:
        """プロジェクトの品質チェック設定をデフォルトにリセット"""
        with self._lock:
            self.quality_settings[project_id] = get_default_quality_settings()

    def get_quality_setting_for_agent(
        self,
        project_id: str,
        agent_type: str
    ) -> QualityCheckConfig:
        """特定エージェントの品質チェック設定を取得"""
        settings = self.get_quality_settings(project_id)
        return settings.get(agent_type, QualityCheckConfig())
