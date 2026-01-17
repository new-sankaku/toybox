"""
Agent Simulation Logic
エージェントの実行をシミュレートして進捗、ログ、チェックポイントを生成
"""

import random
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, Optional
import uuid


class AgentSimulator:
    """Simulates agent execution for mock backend"""

    def __init__(self, data_store, sio):
        self.data_store = data_store
        self.sio = sio
        self.active_simulations: Dict[str, threading.Event] = {}
        self.simulation_threads: Dict[str, threading.Thread] = {}

    def start_simulation(self, project_id: str):
        """Start simulation for a project"""
        if project_id in self.active_simulations:
            return

        stop_event = threading.Event()
        self.active_simulations[project_id] = stop_event

        thread = threading.Thread(
            target=self._run_simulation,
            args=(project_id, stop_event),
            daemon=True
        )
        self.simulation_threads[project_id] = thread
        thread.start()

        print(f"[Simulation] Started for project: {project_id}")

    def stop_simulation(self, project_id: str):
        """Stop simulation for a project"""
        if project_id in self.active_simulations:
            self.active_simulations[project_id].set()
            del self.active_simulations[project_id]
            print(f"[Simulation] Stopped for project: {project_id}")

    def _run_simulation(self, project_id: str, stop_event: threading.Event):
        """Main simulation loop"""
        project = self.data_store.get_project(project_id)
        if not project:
            return

        # Create agents if they don't exist
        agents = self.data_store.get_agents_by_project(project_id)
        if not agents:
            self._create_phase_agents(project_id, project.get("currentPhase", 1))
            agents = self.data_store.get_agents_by_project(project_id)

        # Initialize metrics
        self._init_metrics(project_id, agents)

        # Simulation loop
        while not stop_event.is_set():
            agents = self.data_store.get_agents_by_project(project_id)

            # Find running or pending agent
            running_agent = next((a for a in agents if a["status"] == "running"), None)

            if not running_agent:
                # Start next pending agent
                pending_agent = next((a for a in agents if a["status"] == "pending"), None)
                if pending_agent:
                    self._start_agent(pending_agent)
                    running_agent = pending_agent
                else:
                    # All agents completed - check for phase completion
                    if all(a["status"] == "completed" for a in agents):
                        self._complete_phase(project_id)
                        break

            if running_agent:
                self._simulate_agent_progress(running_agent, stop_event)

            # Update metrics
            self._update_metrics(project_id)

            # Small delay between iterations
            if stop_event.wait(0.5):
                break

        print(f"[Simulation] Ended for project: {project_id}")

    def _create_phase_agents(self, project_id: str, phase: int):
        """Create agents for a phase"""
        phase_agents = {
            1: [
                ("concept", "コンセプト"),
                ("design", "デザイン"),
                ("scenario", "シナリオ"),
                ("character", "キャラクター"),
                ("world", "ワールド"),
            ],
            2: [
                ("task_split", "タスク分割"),
                ("code_leader", "コード"),
                ("asset_leader", "アセット"),
                ("code_worker", "コード"),
                ("code_worker", "コード"),
                ("asset_worker", "アセット"),
            ],
            3: [
                ("integrator", "統合"),
                ("tester", "テスト"),
                ("reviewer", "レビュー"),
            ]
        }

        for agent_type, name in phase_agents.get(phase, []):
            agent = self.data_store.create_agent(project_id, agent_type)
            agent["metadata"]["displayName"] = name

            # Emit agent creation
            self.sio.emit('agent:started', {
                "agentId": agent["id"],
                "projectId": project_id,
                "type": agent_type,
                "status": "pending"
            }, room=f"project:{project_id}")

    def _start_agent(self, agent: dict):
        """Start an agent"""
        now = datetime.now().isoformat()

        self.data_store.update_agent(agent["id"], {
            "status": "running",
            "startedAt": now,
            "currentTask": self._get_initial_task(agent["type"])
        })

        # Add log entry
        self.data_store.add_agent_log(
            agent["id"],
            "info",
            f"エージェント開始: {agent['type']}",
            0
        )

        # Emit event
        self.sio.emit('agent:started', {
            "agentId": agent["id"],
            "projectId": agent["projectId"],
            "type": agent["type"],
            "status": "running"
        }, room=f"project:{agent['projectId']}")

    def _simulate_agent_progress(self, agent: dict, stop_event: threading.Event):
        """Simulate progress for a running agent"""
        agent_id = agent["id"]
        project_id = agent["projectId"]
        current_progress = agent.get("progress", 0)

        # Progress simulation
        tasks = self._get_agent_tasks(agent["type"])
        checkpoint_at = random.choice([30, 50, 70])  # Create checkpoint at random progress
        checkpoint_created = agent.get("metadata", {}).get("checkpoint_created", False)

        while current_progress < 100 and not stop_event.is_set():
            # Increment progress
            increment = random.randint(3, 8)
            current_progress = min(100, current_progress + increment)

            # Determine current task
            task_index = min(len(tasks) - 1, int(current_progress / (100 / len(tasks))))
            current_task = tasks[task_index]

            # Update agent
            self.data_store.update_agent(agent_id, {
                "progress": current_progress,
                "currentTask": current_task,
                "tokensUsed": agent.get("tokensUsed", 0) + random.randint(100, 500)
            })

            # Add log
            log_level = random.choice(["info", "info", "info", "debug"])
            log_messages = [
                f"処理中: {current_task}",
                f"進捗: {current_progress}%",
                "データを分析しています...",
                "生成中...",
                "検証中...",
            ]
            log_entry = self.data_store.add_agent_log(
                agent_id,
                log_level,
                random.choice(log_messages),
                current_progress
            )

            # Emit progress
            self.sio.emit('agent:progress', {
                "agentId": agent_id,
                "projectId": project_id,
                "progress": current_progress,
                "currentTask": current_task
            }, room=f"project:{project_id}")

            # Emit log
            self.sio.emit('agent:log', {
                "agentId": agent_id,
                "projectId": project_id,
                "log": log_entry
            }, room=f"project:{project_id}")

            # Create checkpoint at certain progress
            if current_progress >= checkpoint_at and not checkpoint_created:
                self._create_checkpoint(agent)
                self.data_store.update_agent(agent_id, {
                    "metadata": {**agent.get("metadata", {}), "checkpoint_created": True}
                })
                checkpoint_created = True

                # Wait for checkpoint resolution (with timeout)
                wait_count = 0
                while wait_count < 60 and not stop_event.is_set():  # Max 30 seconds wait
                    checkpoint = self._get_pending_checkpoint(project_id, agent_id)
                    if not checkpoint:
                        break
                    time.sleep(0.5)
                    wait_count += 1

            # Delay between progress updates
            if stop_event.wait(random.uniform(0.8, 1.5)):
                return

        # Complete agent if reached 100%
        if current_progress >= 100:
            self._complete_agent(agent)

    def _complete_agent(self, agent: dict):
        """Mark agent as completed"""
        now = datetime.now().isoformat()

        self.data_store.update_agent(agent["id"], {
            "status": "completed",
            "progress": 100,
            "completedAt": now,
            "currentTask": None
        })

        self.data_store.add_agent_log(
            agent["id"],
            "info",
            "エージェント完了",
            100
        )

        self.sio.emit('agent:completed', {
            "agentId": agent["id"],
            "projectId": agent["projectId"],
            "type": agent["type"]
        }, room=f"project:{agent['projectId']}")

    def _create_checkpoint(self, agent: dict):
        """Create a checkpoint for human review"""
        checkpoint_types = {
            "concept": ("concept_review", "ゲームコンセプトのレビュー"),
            "design": ("game_design_review", "ゲームデザインドキュメントのレビュー"),
            "scenario": ("scenario_review", "シナリオのレビュー"),
            "character": ("character_review", "キャラクターデザインのレビュー"),
            "world": ("world_review", "ワールド設定のレビュー"),
            "task_split": ("task_review", "タスク分割のレビュー"),
            "code_leader": ("code_plan_review", "コード実装計画のレビュー"),
            "asset_leader": ("asset_plan_review", "アセット制作計画のレビュー"),
            "integrator": ("integration_review", "統合結果のレビュー"),
            "tester": ("test_review", "テスト結果のレビュー"),
            "reviewer": ("final_review", "最終レビュー"),
        }

        cp_type, title = checkpoint_types.get(agent["type"], ("review", "レビュー依頼"))

        checkpoint = self.data_store.create_checkpoint(
            agent["projectId"],
            agent["id"],
            {
                "type": cp_type,
                "title": title,
                "description": f"{agent['type']}エージェントの出力を確認してください",
                "output": self._generate_checkpoint_output(agent)
            }
        )

        self.sio.emit('checkpoint:created', {
            "checkpointId": checkpoint["id"],
            "projectId": agent["projectId"],
            "agentId": agent["id"],
            "type": cp_type,
            "title": title,
            "checkpoint": checkpoint
        }, room=f"project:{agent['projectId']}")

        self.data_store.add_agent_log(
            agent["id"],
            "info",
            f"チェックポイント作成: {title}",
            agent.get("progress", 50)
        )

    def _generate_checkpoint_output(self, agent: dict) -> dict:
        """Generate mock output for checkpoint"""
        outputs = {
            "concept": {
                "type": "document",
                "format": "markdown",
                "content": """# ゲームコンセプト

## ゲーム概要
プレイヤーが楽しめるシンプルで直感的なゲーム体験を提供します。

## ターゲット層
- カジュアルゲーマー
- 全年齢対象

## 主要機能
1. 直感的な操作システム
2. 段階的な難易度設計
3. リプレイ性の高いゲームプレイ

## 差別化ポイント
- ユニークなビジュアルスタイル
- 革新的なゲームメカニクス
"""
            },
            "design": {
                "type": "document",
                "format": "markdown",
                "content": """# ゲームデザインドキュメント

## 1. ゲームメカニクス

### 基本操作
- 移動: 矢印キー / WASD
- アクション: スペースキー
- メニュー: ESCキー

### スコアシステム
- クリアタイム
- 収集アイテム
- コンボボーナス

## 2. 画面遷移

```
タイトル → ステージ選択 → ゲームプレイ → リザルト
    ↓            ↓
  設定        チュートリアル
```

## 3. UI/UX設計
- ミニマルデザイン
- 直感的なナビゲーション
- アクセシビリティ配慮
"""
            },
            "scenario": {
                "type": "document",
                "format": "markdown",
                "content": """# ゲームシナリオ

## プロローグ
平和な世界に突然現れた謎の脅威。
主人公は世界を救う旅に出る...

## 第1章: 始まりの地
主人公が冒険を始める場所。
基本的な操作を学びながら進行。

## 第2章: 試練の洞窟
最初の本格的な挑戦。
新しいスキルを習得。

## エピローグ
世界に平和が戻り、主人公は英雄として称えられる。
"""
            }
        }

        default_output = {
            "type": "document",
            "format": "markdown",
            "content": f"# {agent['type']}の出力\n\nエージェントの処理結果がここに表示されます。\n\n## 詳細\n処理が完了しました。"
        }

        return outputs.get(agent["type"], default_output)

    def _get_pending_checkpoint(self, project_id: str, agent_id: str) -> Optional[dict]:
        """Get pending checkpoint for agent"""
        checkpoints = self.data_store.get_checkpoints_by_project(project_id)
        return next(
            (c for c in checkpoints if c["agentId"] == agent_id and c["status"] == "pending"),
            None
        )

    def _complete_phase(self, project_id: str):
        """Complete current phase and potentially move to next"""
        project = self.data_store.get_project(project_id)
        if not project:
            return

        current_phase = project.get("currentPhase", 1)

        if current_phase < 3:
            # Move to next phase
            next_phase = current_phase + 1
            self.data_store.update_project(project_id, {
                "currentPhase": next_phase
            })

            self.sio.emit('phase:changed', {
                "projectId": project_id,
                "previousPhase": current_phase,
                "currentPhase": next_phase,
                "phaseName": self._get_phase_name(next_phase)
            }, room=f"project:{project_id}")

            # Create agents for new phase
            self._create_phase_agents(project_id, next_phase)

        else:
            # Project completed
            self.data_store.update_project(project_id, {"status": "completed"})

            self.sio.emit('project:status_changed', {
                "projectId": project_id,
                "status": "completed",
                "previousStatus": "running"
            }, room=f"project:{project_id}")

    def _init_metrics(self, project_id: str, agents: list):
        """Initialize project metrics"""
        self.data_store.update_project_metrics(project_id, {
            "totalTokensUsed": sum(a.get("tokensUsed", 0) for a in agents),
            "estimatedTotalTokens": 100000,
            "elapsedTimeSeconds": 0,
            "estimatedRemainingSeconds": 3600,
            "completedTasks": len([a for a in agents if a["status"] == "completed"]),
            "totalTasks": len(agents),
            "progressPercent": 0
        })

    def _update_metrics(self, project_id: str):
        """Update project metrics"""
        agents = self.data_store.get_agents_by_project(project_id)
        project = self.data_store.get_project(project_id)

        if not agents or not project:
            return

        completed = len([a for a in agents if a["status"] == "completed"])
        total = len(agents)
        total_tokens = sum(a.get("tokensUsed", 0) for a in agents)
        avg_progress = sum(a.get("progress", 0) for a in agents) / total if total > 0 else 0

        metrics = self.data_store.update_project_metrics(project_id, {
            "totalTokensUsed": total_tokens,
            "completedTasks": completed,
            "totalTasks": total,
            "progressPercent": int(avg_progress),
            "currentPhase": project.get("currentPhase", 1),
            "phaseName": self._get_phase_name(project.get("currentPhase", 1))
        })

        self.sio.emit('metrics:update', {
            "projectId": project_id,
            "metrics": metrics
        }, room=f"project:{project_id}")

    def _get_initial_task(self, agent_type: str) -> str:
        """Get initial task description for agent type"""
        tasks = {
            "concept": "コンセプト分析開始",
            "design": "デザインドキュメント作成開始",
            "scenario": "シナリオプロット作成",
            "character": "キャラクター設計開始",
            "world": "ワールド構築開始",
            "task_split": "タスク分割分析",
            "code_leader": "コード設計開始",
            "asset_leader": "アセット計画立案",
            "code_worker": "コード実装開始",
            "asset_worker": "アセット制作開始",
            "integrator": "統合処理開始",
            "tester": "テスト実行開始",
            "reviewer": "レビュー開始",
        }
        return tasks.get(agent_type, "処理開始")

    def _get_agent_tasks(self, agent_type: str) -> list:
        """Get task list for agent type"""
        tasks = {
            "concept": [
                "要件分析",
                "市場調査",
                "コンセプト定義",
                "ドキュメント作成",
                "レビュー準備"
            ],
            "design": [
                "メカニクス設計",
                "UI/UX設計",
                "画面遷移設計",
                "バランス調整案",
                "ドキュメント統合"
            ],
            "scenario": [
                "プロット作成",
                "キャラクター配置",
                "イベント設計",
                "台詞作成",
                "校正"
            ],
            "character": [
                "キャラクター分析",
                "ビジュアル設計",
                "パラメータ設定",
                "関係性定義",
                "ドキュメント化"
            ],
            "world": [
                "世界観設計",
                "マップ構造",
                "環境設定",
                "ロア作成",
                "統合"
            ],
        }
        return tasks.get(agent_type, ["初期化", "処理中", "検証", "完了準備", "完了"])

    def _get_phase_name(self, phase: int) -> str:
        """Get human-readable phase name"""
        phase_names = {
            1: "Phase 1: 企画・設計",
            2: "Phase 2: 実装",
            3: "Phase 3: 統合・テスト"
        }
        return phase_names.get(phase, f"Phase {phase}")
