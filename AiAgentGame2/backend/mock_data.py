"""
Mock Data Store and Generators
フロントエンドテスト用のモックデータ管理
"""

import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
import random


class MockDataStore:
    """In-memory data store for mock backend"""

    def __init__(self):
        self.projects: Dict[str, Dict] = {}
        self.agents: Dict[str, Dict] = {}
        self.checkpoints: Dict[str, Dict] = {}
        self.agent_logs: Dict[str, List[Dict]] = {}
        self.metrics: Dict[str, Dict] = {}
        self.subscriptions: Dict[str, set] = {}  # project_id -> set of sid

        # Initialize with sample data
        self._init_sample_data()

    def _init_sample_data(self):
        """Initialize with comprehensive sample project data"""

        # ============================================================
        # Project 1: Draft RPG - 新規作成待ち
        # ============================================================
        proj1_id = "proj-001"
        self.projects[proj1_id] = {
            "id": proj1_id,
            "name": "サンプルRPGゲーム",
            "description": "ターン制バトルシステムを持つシンプルなRPG。レトロスタイルのグラフィックと戦略的なバトルが特徴。",
            "concept": {
                "description": "勇者が魔王を倒す王道RPG。4人パーティでのターン制バトル、装備システム、スキルツリーを実装。",
                "platform": "web",
                "scope": "mvp",
                "genre": "RPG",
                "targetAudience": "カジュアルゲーマー、レトロゲーム好き"
            },
            "status": "draft",
            "currentPhase": 1,
            "state": {},
            "config": {
                "maxTokensPerAgent": 100000,
                "enableAutoApproval": False,
                "llmProvider": "mock"
            },
            "createdAt": datetime.now().isoformat(),
            "updatedAt": datetime.now().isoformat()
        }

        # ============================================================
        # Project 2: Running Puzzle Game - Phase 1実行中
        # ============================================================
        proj2_id = "proj-002"
        self.projects[proj2_id] = {
            "id": proj2_id,
            "name": "パズルアクションゲーム",
            "description": "物理演算を使ったパズルゲーム。ボールを転がして障害物を避けながらゴールを目指す。",
            "concept": {
                "description": "ボールを転がしてゴールを目指すパズル。重力や摩擦をリアルに再現した物理演算エンジン搭載。",
                "platform": "web",
                "scope": "mvp",
                "genre": "Puzzle",
                "targetAudience": "全年齢"
            },
            "status": "running",
            "currentPhase": 1,
            "state": {},
            "config": {
                "maxTokensPerAgent": 100000,
                "enableAutoApproval": False,
                "llmProvider": "mock"
            },
            "createdAt": (datetime.now() - timedelta(hours=2)).isoformat(),
            "updatedAt": datetime.now().isoformat()
        }

        # Add agents for project 2 (Phase 1)
        self._create_sample_agents_phase1(proj2_id)

        # Add checkpoints for project 2
        self._create_sample_checkpoints_phase1(proj2_id)

        # Initialize metrics for project 2
        self.metrics[proj2_id] = {
            "projectId": proj2_id,
            "totalTokensUsed": 15420,
            "estimatedTotalTokens": 50000,
            "elapsedTimeSeconds": 3600,
            "estimatedRemainingSeconds": 7200,
            "estimatedEndTime": (datetime.now() + timedelta(hours=2)).isoformat(),
            "completedTasks": 2,
            "totalTasks": 5,
            "progressPercent": 35,
            "currentPhase": 1,
            "phaseName": "Phase 1: 企画・設計"
        }

        # ============================================================
        # Project 3: Paused Shooting Game - Phase 2で一時停止
        # ============================================================
        proj3_id = "proj-003"
        self.projects[proj3_id] = {
            "id": proj3_id,
            "name": "スペースシューティング",
            "description": "レトロスタイルの縦スクロールシューティングゲーム。",
            "concept": {
                "description": "宇宙を舞台にした縦スクロールシューティング。パワーアップシステムとボス戦が特徴。",
                "platform": "web",
                "scope": "full",
                "genre": "Shooting",
                "targetAudience": "シューティング好き、アーケードゲーマー"
            },
            "status": "paused",
            "currentPhase": 2,
            "state": {},
            "config": {
                "maxTokensPerAgent": 150000,
                "enableAutoApproval": False,
                "llmProvider": "mock"
            },
            "createdAt": (datetime.now() - timedelta(days=1)).isoformat(),
            "updatedAt": (datetime.now() - timedelta(hours=3)).isoformat()
        }

        # Add completed Phase 1 agents and in-progress Phase 2 agents
        self._create_sample_agents_phase2(proj3_id)
        self._create_sample_checkpoints_phase2(proj3_id)

        self.metrics[proj3_id] = {
            "projectId": proj3_id,
            "totalTokensUsed": 78500,
            "estimatedTotalTokens": 150000,
            "elapsedTimeSeconds": 86400,
            "estimatedRemainingSeconds": 43200,
            "estimatedEndTime": (datetime.now() + timedelta(hours=12)).isoformat(),
            "completedTasks": 8,
            "totalTasks": 14,
            "progressPercent": 52,
            "currentPhase": 2,
            "phaseName": "Phase 2: 実装"
        }

        # ============================================================
        # Project 4: Completed Card Game - 完了済み
        # ============================================================
        proj4_id = "proj-004"
        self.projects[proj4_id] = {
            "id": proj4_id,
            "name": "トランプソリティア",
            "description": "クラシックなソリティアゲーム。ドラッグ&ドロップ操作対応。",
            "concept": {
                "description": "クロンダイク形式のソリティア。アンドゥ機能、ヒント機能、統計表示を実装。",
                "platform": "web",
                "scope": "mvp",
                "genre": "Card",
                "targetAudience": "カジュアルゲーマー、暇つぶし派"
            },
            "status": "completed",
            "currentPhase": 3,
            "state": {},
            "config": {
                "maxTokensPerAgent": 80000,
                "enableAutoApproval": True,
                "llmProvider": "mock"
            },
            "createdAt": (datetime.now() - timedelta(days=3)).isoformat(),
            "updatedAt": (datetime.now() - timedelta(days=1)).isoformat()
        }

        self._create_sample_agents_completed(proj4_id)
        self._create_sample_checkpoints_completed(proj4_id)

        self.metrics[proj4_id] = {
            "projectId": proj4_id,
            "totalTokensUsed": 65230,
            "estimatedTotalTokens": 80000,
            "elapsedTimeSeconds": 172800,
            "estimatedRemainingSeconds": 0,
            "estimatedEndTime": None,
            "completedTasks": 12,
            "totalTasks": 12,
            "progressPercent": 100,
            "currentPhase": 3,
            "phaseName": "Phase 3: 統合・テスト"
        }

        # ============================================================
        # Project 5: Failed Project - エラーで失敗
        # ============================================================
        proj5_id = "proj-005"
        self.projects[proj5_id] = {
            "id": proj5_id,
            "name": "3Dアクションゲーム（失敗）",
            "description": "複雑すぎる要件により失敗したプロジェクト例。",
            "concept": {
                "description": "オープンワールド3Dアクション。要件が複雑すぎてMVPスコープを超過。",
                "platform": "desktop",
                "scope": "full",
                "genre": "Action",
                "targetAudience": "コアゲーマー"
            },
            "status": "failed",
            "currentPhase": 1,
            "state": {"failReason": "要件の複雑さによりスコープ超過"},
            "config": {
                "maxTokensPerAgent": 200000,
                "enableAutoApproval": False,
                "llmProvider": "mock"
            },
            "createdAt": (datetime.now() - timedelta(days=5)).isoformat(),
            "updatedAt": (datetime.now() - timedelta(days=4)).isoformat()
        }

        self._create_sample_agents_failed(proj5_id)

        self.metrics[proj5_id] = {
            "projectId": proj5_id,
            "totalTokensUsed": 45000,
            "estimatedTotalTokens": 200000,
            "elapsedTimeSeconds": 28800,
            "estimatedRemainingSeconds": 0,
            "estimatedEndTime": None,
            "completedTasks": 1,
            "totalTasks": 5,
            "progressPercent": 15,
            "currentPhase": 1,
            "phaseName": "Phase 1: 企画・設計"
        }

    def _create_sample_agents_phase1(self, project_id: str):
        """Create sample agents for Phase 1 project"""
        base_time = datetime.now() - timedelta(hours=2)

        agents_data = [
            {
                "type": "concept",
                "status": "completed",
                "progress": 100,
                "currentTask": None,
                "tokensUsed": 4520,
                "startedAt": base_time.isoformat(),
                "completedAt": (base_time + timedelta(minutes=30)).isoformat(),
                "displayName": "コンセプト定義エージェント"
            },
            {
                "type": "design",
                "status": "running",
                "progress": 65,
                "currentTask": "UI/UX設計ドキュメント作成中",
                "tokensUsed": 6800,
                "startedAt": (base_time + timedelta(minutes=35)).isoformat(),
                "completedAt": None,
                "displayName": "ゲームデザインエージェント"
            },
            {
                "type": "scenario",
                "status": "pending",
                "progress": 0,
                "currentTask": None,
                "tokensUsed": 0,
                "startedAt": None,
                "completedAt": None,
                "displayName": "シナリオ作成エージェント"
            },
            {
                "type": "character",
                "status": "pending",
                "progress": 0,
                "currentTask": None,
                "tokensUsed": 0,
                "startedAt": None,
                "completedAt": None,
                "displayName": "キャラクターデザインエージェント"
            },
            {
                "type": "world",
                "status": "pending",
                "progress": 0,
                "currentTask": None,
                "tokensUsed": 0,
                "startedAt": None,
                "completedAt": None,
                "displayName": "ワールドビルディングエージェント"
            }
        ]

        for data in agents_data:
            agent_id = f"agent-{project_id}-{data['type']}"
            self.agents[agent_id] = {
                "id": agent_id,
                "projectId": project_id,
                "type": data["type"],
                "status": data["status"],
                "progress": data["progress"],
                "currentTask": data["currentTask"],
                "tokensUsed": data["tokensUsed"],
                "startedAt": data["startedAt"],
                "completedAt": data["completedAt"],
                "error": None,
                "parentAgentId": None,
                "metadata": {"displayName": data["displayName"]},
                "createdAt": base_time.isoformat()
            }

            if data["status"] in ("running", "completed"):
                self.agent_logs[agent_id] = self._generate_detailed_logs(agent_id, data["type"], data["status"])

    def _create_sample_agents_phase2(self, project_id: str):
        """Create sample agents for Phase 2 project (with completed Phase 1)"""
        base_time = datetime.now() - timedelta(days=1)

        # Phase 1 agents (all completed)
        phase1_agents = [
            {"type": "concept", "displayName": "コンセプト定義"},
            {"type": "design", "displayName": "ゲームデザイン"},
            {"type": "scenario", "displayName": "シナリオ作成"},
            {"type": "character", "displayName": "キャラクターデザイン"},
            {"type": "world", "displayName": "ワールドビルディング"}
        ]

        for i, data in enumerate(phase1_agents):
            agent_id = f"agent-{project_id}-p1-{data['type']}"
            start = base_time + timedelta(hours=i * 2)
            self.agents[agent_id] = {
                "id": agent_id,
                "projectId": project_id,
                "type": data["type"],
                "status": "completed",
                "progress": 100,
                "currentTask": None,
                "tokensUsed": random.randint(4000, 8000),
                "startedAt": start.isoformat(),
                "completedAt": (start + timedelta(hours=1, minutes=30)).isoformat(),
                "error": None,
                "parentAgentId": None,
                "metadata": {"displayName": data["displayName"], "phase": 1},
                "createdAt": base_time.isoformat()
            }
            self.agent_logs[agent_id] = self._generate_detailed_logs(agent_id, data["type"], "completed")

        # Phase 2 agents
        phase2_start = base_time + timedelta(hours=12)
        phase2_agents = [
            {"type": "task_split", "status": "completed", "progress": 100, "tokensUsed": 5200, "displayName": "タスク分割"},
            {"type": "code_leader", "status": "running", "progress": 45, "currentTask": "アーキテクチャ設計", "tokensUsed": 12000, "displayName": "コードリーダー"},
            {"type": "asset_leader", "status": "blocked", "progress": 30, "currentTask": "アセット仕様待ち", "tokensUsed": 3500, "displayName": "アセットリーダー"},
            {"type": "code_worker", "status": "pending", "progress": 0, "tokensUsed": 0, "displayName": "コードワーカー1"},
            {"type": "code_worker", "status": "pending", "progress": 0, "tokensUsed": 0, "displayName": "コードワーカー2"},
            {"type": "asset_worker", "status": "pending", "progress": 0, "tokensUsed": 0, "displayName": "アセットワーカー"}
        ]

        for i, data in enumerate(phase2_agents):
            suffix = f"-{i}" if data["type"] in ("code_worker", "asset_worker") else ""
            agent_id = f"agent-{project_id}-p2-{data['type']}{suffix}"
            start = phase2_start + timedelta(hours=i)

            self.agents[agent_id] = {
                "id": agent_id,
                "projectId": project_id,
                "type": data["type"],
                "status": data["status"],
                "progress": data["progress"],
                "currentTask": data.get("currentTask"),
                "tokensUsed": data["tokensUsed"],
                "startedAt": start.isoformat() if data["status"] != "pending" else None,
                "completedAt": (start + timedelta(hours=2)).isoformat() if data["status"] == "completed" else None,
                "error": None,
                "parentAgentId": None,
                "metadata": {"displayName": data["displayName"], "phase": 2},
                "createdAt": phase2_start.isoformat()
            }

            if data["status"] in ("running", "completed", "blocked"):
                self.agent_logs[agent_id] = self._generate_detailed_logs(agent_id, data["type"], data["status"])

    def _create_sample_agents_completed(self, project_id: str):
        """Create sample agents for completed project"""
        base_time = datetime.now() - timedelta(days=3)

        all_phases = [
            # Phase 1
            [("concept", "コンセプト"), ("design", "デザイン"), ("scenario", "シナリオ")],
            # Phase 2
            [("task_split", "タスク分割"), ("code_leader", "コードリーダー"), ("code_worker", "コードワーカー")],
            # Phase 3
            [("integrator", "統合"), ("tester", "テスト"), ("reviewer", "レビュー")]
        ]

        hour_offset = 0
        for phase_num, phase_agents in enumerate(all_phases, 1):
            for agent_type, display_name in phase_agents:
                agent_id = f"agent-{project_id}-p{phase_num}-{agent_type}"
                start = base_time + timedelta(hours=hour_offset)

                self.agents[agent_id] = {
                    "id": agent_id,
                    "projectId": project_id,
                    "type": agent_type,
                    "status": "completed",
                    "progress": 100,
                    "currentTask": None,
                    "tokensUsed": random.randint(5000, 10000),
                    "startedAt": start.isoformat(),
                    "completedAt": (start + timedelta(hours=3)).isoformat(),
                    "error": None,
                    "parentAgentId": None,
                    "metadata": {"displayName": display_name, "phase": phase_num},
                    "createdAt": base_time.isoformat()
                }
                self.agent_logs[agent_id] = self._generate_detailed_logs(agent_id, agent_type, "completed")
                hour_offset += 4

    def _create_sample_agents_failed(self, project_id: str):
        """Create sample agents for failed project"""
        base_time = datetime.now() - timedelta(days=5)

        agents_data = [
            {"type": "concept", "status": "completed", "progress": 100, "error": None},
            {"type": "design", "status": "failed", "progress": 35, "error": "要件の複雑さにより処理できません。スコープを縮小してください。"},
            {"type": "scenario", "status": "pending", "progress": 0, "error": None},
            {"type": "character", "status": "pending", "progress": 0, "error": None},
            {"type": "world", "status": "pending", "progress": 0, "error": None}
        ]

        for data in agents_data:
            agent_id = f"agent-{project_id}-{data['type']}"
            self.agents[agent_id] = {
                "id": agent_id,
                "projectId": project_id,
                "type": data["type"],
                "status": data["status"],
                "progress": data["progress"],
                "currentTask": None,
                "tokensUsed": random.randint(3000, 15000) if data["status"] != "pending" else 0,
                "startedAt": base_time.isoformat() if data["status"] != "pending" else None,
                "completedAt": (base_time + timedelta(hours=2)).isoformat() if data["status"] == "completed" else None,
                "error": data["error"],
                "parentAgentId": None,
                "metadata": {"phase": 1},
                "createdAt": base_time.isoformat()
            }

            if data["status"] in ("completed", "failed"):
                self.agent_logs[agent_id] = self._generate_detailed_logs(agent_id, data["type"], data["status"])

    def _create_sample_checkpoints_phase1(self, project_id: str):
        """Create sample checkpoints for Phase 1"""
        base_time = datetime.now() - timedelta(hours=1)

        # Approved checkpoint from concept agent
        cp1_id = f"cp-{project_id}-001"
        self.checkpoints[cp1_id] = {
            "id": cp1_id,
            "projectId": project_id,
            "agentId": f"agent-{project_id}-concept",
            "type": "concept_review",
            "title": "ゲームコンセプトの承認",
            "description": "ゲームの基本コンセプトと方向性を確認してください",
            "output": {
                "type": "document",
                "format": "markdown",
                "content": """# ゲームコンセプト: パズルアクションゲーム

## ゲーム概要
プレイヤーがボールを操作し、物理演算を活用して様々な障害物を乗り越えながらゴールを目指すパズルゲーム。

## コアコンセプト
- **シンプルな操作**: 方向キーのみの直感的操作
- **物理演算**: リアルな重力・摩擦・反発
- **段階的難易度**: チュートリアルから上級者向けまで

## ターゲットユーザー
- カジュアルゲーマー
- 短時間で遊びたい人
- パズルゲーム好き

## 差別化ポイント
1. 美しいミニマルデザイン
2. 中毒性のあるゲームループ
3. ソーシャル機能（スコア共有）

## MVP機能
- 30ステージ
- 基本物理演算
- スコアシステム
- ローカルハイスコア保存""",
                "artifacts": []
            },
            "status": "approved",
            "feedback": "コンセプトは明確で良い方向性です。MVPとして適切なスコープだと思います。",
            "resolvedAt": (base_time - timedelta(minutes=30)).isoformat(),
            "createdAt": (base_time - timedelta(hours=1)).isoformat(),
            "updatedAt": (base_time - timedelta(minutes=30)).isoformat()
        }

        # Pending checkpoint from design agent
        cp2_id = f"cp-{project_id}-002"
        self.checkpoints[cp2_id] = {
            "id": cp2_id,
            "projectId": project_id,
            "agentId": f"agent-{project_id}-design",
            "type": "game_design_review",
            "title": "ゲームデザインドキュメントのレビュー",
            "description": "基本的なゲームメカニクスと画面遷移の設計をレビューしてください",
            "output": {
                "type": "document",
                "format": "markdown",
                "content": """# ゲームデザインドキュメント

## 1. ゲームメカニクス

### 1.1 基本操作
| 入力 | アクション |
|------|----------|
| ← → | 左右移動 |
| ↑ | ジャンプ |
| スペース | ブースト |
| R | リスタート |

### 1.2 物理パラメータ
- 重力: 9.8 m/s²
- 摩擦係数: 0.3
- 反発係数: 0.7
- 最大速度: 15 m/s

### 1.3 スコアリング
```
最終スコア = 基本点 × タイムボーナス × コレクティブルボーナス
```

## 2. 画面遷移

```
[タイトル] → [ステージ選択] → [ゲームプレイ] → [リザルト]
     ↓              ↓                              ↓
  [設定]      [チュートリアル]              [次のステージ]
```

## 3. UI/UX設計

### 3.1 カラースキーム
- Primary: #3498db (ブルー)
- Secondary: #2ecc71 (グリーン)
- Accent: #e74c3c (レッド)
- Background: #1a1a2e (ダークネイビー)

### 3.2 フォント
- 見出し: Noto Sans JP Bold
- 本文: Noto Sans JP Regular
- 数字: Roboto Mono

## 4. 音声設計

### BGM
- タイトル: 落ち着いたアンビエント
- ゲームプレイ: テンポの良いエレクトロニカ
- リザルト: 達成感のあるファンファーレ

### SE
- ボール転がり音
- 壁接触音
- ゴール到達音
- スター獲得音""",
                "artifacts": []
            },
            "status": "pending",
            "feedback": None,
            "resolvedAt": None,
            "createdAt": base_time.isoformat(),
            "updatedAt": base_time.isoformat()
        }

    def _create_sample_checkpoints_phase2(self, project_id: str):
        """Create sample checkpoints for Phase 2"""
        base_time = datetime.now() - timedelta(hours=5)

        # Approved Phase 1 checkpoints
        for i, (cp_type, title) in enumerate([
            ("concept_review", "コンセプト承認"),
            ("design_review", "デザイン承認"),
            ("scenario_review", "シナリオ承認")
        ]):
            cp_id = f"cp-{project_id}-p1-{i+1:03d}"
            self.checkpoints[cp_id] = {
                "id": cp_id,
                "projectId": project_id,
                "agentId": f"agent-{project_id}-p1-concept",
                "type": cp_type,
                "title": title,
                "description": f"Phase 1 {title}",
                "output": {"type": "document", "format": "markdown", "content": f"# {title}\n\n承認済みドキュメント"},
                "status": "approved",
                "feedback": "LGTM",
                "resolvedAt": (base_time - timedelta(hours=10 + i)).isoformat(),
                "createdAt": (base_time - timedelta(hours=12 + i)).isoformat(),
                "updatedAt": (base_time - timedelta(hours=10 + i)).isoformat()
            }

        # Pending Phase 2 checkpoint
        cp_id = f"cp-{project_id}-p2-001"
        self.checkpoints[cp_id] = {
            "id": cp_id,
            "projectId": project_id,
            "agentId": f"agent-{project_id}-p2-code_leader",
            "type": "architecture_review",
            "title": "アーキテクチャ設計レビュー",
            "description": "コード実装のアーキテクチャを確認してください",
            "output": {
                "type": "document",
                "format": "markdown",
                "content": """# システムアーキテクチャ設計

## 技術スタック
- **フレームワーク**: Phaser 3
- **言語**: TypeScript
- **ビルドツール**: Vite
- **状態管理**: Zustand

## ディレクトリ構造
```
src/
├── scenes/          # Phaserシーン
│   ├── TitleScene.ts
│   ├── GameScene.ts
│   └── ResultScene.ts
├── objects/         # ゲームオブジェクト
│   ├── Ball.ts
│   └── Obstacle.ts
├── physics/         # 物理演算
│   └── PhysicsEngine.ts
├── ui/              # UIコンポーネント
├── stores/          # 状態管理
└── utils/           # ユーティリティ
```

## クラス設計
- `GameManager`: ゲーム全体の制御
- `LevelLoader`: ステージデータ読み込み
- `ScoreManager`: スコア計算・保存
- `SoundManager`: 音声制御"""
            },
            "status": "pending",
            "feedback": None,
            "resolvedAt": None,
            "createdAt": base_time.isoformat(),
            "updatedAt": base_time.isoformat()
        }

        # Revision requested checkpoint
        cp_id = f"cp-{project_id}-p2-002"
        self.checkpoints[cp_id] = {
            "id": cp_id,
            "projectId": project_id,
            "agentId": f"agent-{project_id}-p2-asset_leader",
            "type": "asset_plan_review",
            "title": "アセット制作計画レビュー",
            "description": "アセット制作の計画を確認してください",
            "output": {
                "type": "document",
                "format": "markdown",
                "content": "# アセット制作計画\n\n## 必要アセット一覧\n- キャラクタースプライト\n- 背景画像\n- UIアイコン\n- エフェクト"
            },
            "status": "revision_requested",
            "feedback": "アセットのサイズ仕様と形式を追記してください。また、アニメーションフレーム数も明記が必要です。",
            "resolvedAt": (base_time - timedelta(hours=1)).isoformat(),
            "createdAt": (base_time - timedelta(hours=3)).isoformat(),
            "updatedAt": (base_time - timedelta(hours=1)).isoformat()
        }

    def _create_sample_checkpoints_completed(self, project_id: str):
        """Create sample checkpoints for completed project"""
        base_time = datetime.now() - timedelta(days=2)

        checkpoints_data = [
            ("concept_review", "コンセプト承認", "approved", "良いコンセプトです"),
            ("design_review", "デザイン承認", "approved", "シンプルで分かりやすい設計"),
            ("code_review", "コードレビュー", "approved", "コード品質OK"),
            ("integration_review", "統合テスト結果", "approved", "全テストパス"),
            ("final_review", "最終承認", "approved", "リリース準備完了")
        ]

        for i, (cp_type, title, status, feedback) in enumerate(checkpoints_data):
            cp_id = f"cp-{project_id}-{i+1:03d}"
            created = base_time + timedelta(hours=i * 8)
            self.checkpoints[cp_id] = {
                "id": cp_id,
                "projectId": project_id,
                "agentId": f"agent-{project_id}-p1-concept",
                "type": cp_type,
                "title": title,
                "description": f"{title}のチェックポイント",
                "output": {"type": "document", "format": "markdown", "content": f"# {title}\n\n完了"},
                "status": status,
                "feedback": feedback,
                "resolvedAt": (created + timedelta(hours=2)).isoformat(),
                "createdAt": created.isoformat(),
                "updatedAt": (created + timedelta(hours=2)).isoformat()
            }

    def _generate_sample_logs(self, agent_id: str) -> List[Dict]:
        """Generate sample log entries (legacy, use _generate_detailed_logs)"""
        return self._generate_detailed_logs(agent_id, "generic", "running")

    def _generate_detailed_logs(self, agent_id: str, agent_type: str, status: str) -> List[Dict]:
        """Generate detailed log entries based on agent type and status"""
        logs = []
        base_time = datetime.now() - timedelta(minutes=random.randint(30, 120))

        # Agent-type specific log templates
        log_templates = {
            "concept": [
                ("info", "コンセプト定義エージェント起動", 0),
                ("info", "プロジェクト要件を分析中...", 5),
                ("debug", "ユーザー入力データ: ジャンル、プラットフォーム、スコープを取得", 10),
                ("info", "市場分析を実行中...", 15),
                ("debug", "類似ゲームのトレンドデータを収集", 20),
                ("info", "コアゲームループを設計中...", 30),
                ("info", "ターゲットユーザー分析完了", 40),
                ("debug", "USP (Unique Selling Point) を特定", 45),
                ("info", "コンセプトドキュメント生成中...", 55),
                ("info", "レビュー用チェックポイントを作成", 70),
                ("warn", "ドキュメントサイズが大きいため圧縮処理", 75),
                ("info", "最終確認中...", 85),
                ("info", "コンセプト定義完了", 100),
            ],
            "design": [
                ("info", "ゲームデザインエージェント起動", 0),
                ("info", "コンセプトドキュメントを読み込み中...", 5),
                ("debug", "ゲームジャンル: パズル, プラットフォーム: Web", 8),
                ("info", "ゲームメカニクス設計開始", 15),
                ("debug", "操作スキーム: キーボード/タッチ対応", 20),
                ("info", "物理パラメータを計算中...", 25),
                ("info", "画面遷移フローを設計中...", 35),
                ("debug", "シーン数: 5, 遷移パターン: 8", 40),
                ("info", "UI/UXガイドライン作成中...", 50),
                ("warn", "複雑なUI要素を検出 - 簡素化を推奨", 55),
                ("info", "カラースキーム決定", 60),
                ("info", "サウンドデザイン仕様作成中...", 65),
                ("debug", "BGM: 3曲, SE: 15種類", 68),
                ("info", "デザインドキュメント統合中...", 75),
                ("info", "チェックポイント作成準備", 85),
            ],
            "scenario": [
                ("info", "シナリオ作成エージェント起動", 0),
                ("info", "ゲームコンセプトを分析中...", 10),
                ("debug", "ストーリー要素: 必要, 複雑さ: 低", 15),
                ("info", "プロット構成を生成中...", 25),
                ("info", "キャラクター配置を計画中...", 40),
                ("debug", "主要キャラクター: 3, サブキャラクター: 5", 45),
                ("info", "イベントシーケンスを設計中...", 55),
                ("info", "台詞データベース作成中...", 70),
                ("warn", "テキスト量が多いため分割処理", 75),
                ("info", "シナリオドキュメント最終化", 90),
            ],
            "code_leader": [
                ("info", "コードリーダーエージェント起動", 0),
                ("info", "技術要件を分析中...", 5),
                ("debug", "フレームワーク選定: Phaser 3", 10),
                ("info", "アーキテクチャ設計開始", 15),
                ("debug", "パターン: Component-based, State: Zustand", 20),
                ("info", "ディレクトリ構造を設計中...", 30),
                ("info", "クラス設計ドキュメント作成中...", 45),
                ("warn", "依存関係の循環を検出 - 再設計中", 50),
                ("info", "インターフェース定義中...", 60),
                ("debug", "公開API: 12, 内部API: 28", 65),
                ("info", "タスク分割を準備中...", 75),
            ],
            "tester": [
                ("info", "テストエージェント起動", 0),
                ("info", "テスト計画を作成中...", 10),
                ("debug", "ユニットテスト: 45, 統合テスト: 12, E2E: 8", 15),
                ("info", "ユニットテスト実行中...", 25),
                ("debug", "テストカバレッジ: 78%", 35),
                ("info", "統合テスト実行中...", 45),
                ("warn", "統合テスト 2件 失敗 - 再試行中", 55),
                ("info", "E2Eテスト実行中...", 65),
                ("info", "パフォーマンステスト実行中...", 75),
                ("debug", "FPS: 60, メモリ使用量: 128MB", 80),
                ("info", "テストレポート生成中...", 90),
            ],
            "integrator": [
                ("info", "統合エージェント起動", 0),
                ("info", "コードモジュールを収集中...", 10),
                ("debug", "モジュール数: 15, 依存関係: 42", 15),
                ("info", "コード統合を実行中...", 25),
                ("warn", "型の不一致を検出 - 自動修正中", 35),
                ("info", "ビルドプロセス実行中...", 50),
                ("debug", "ビルド成功: バンドルサイズ 2.4MB", 60),
                ("info", "アセット統合中...", 70),
                ("info", "最終パッケージ作成中...", 85),
            ]
        }

        # Get appropriate logs or use generic
        template = log_templates.get(agent_type, [
            ("info", "エージェント起動", 0),
            ("info", "タスク分析中...", 15),
            ("debug", "データ処理中", 25),
            ("info", "メイン処理実行中...", 40),
            ("info", "中間結果を確認中...", 55),
            ("debug", "最適化処理", 65),
            ("info", "出力生成中...", 80),
            ("info", "処理完了", 100),
        ])

        # Determine how many logs to include based on status
        if status == "completed":
            logs_to_include = template
        elif status == "failed":
            logs_to_include = template[:len(template)//2] + [("error", "処理中にエラーが発生しました", template[len(template)//2][2])]
        elif status == "running":
            logs_to_include = template[:int(len(template) * 0.7)]
        elif status == "blocked":
            logs_to_include = template[:int(len(template) * 0.4)] + [("warn", "外部依存の完了待ち - ブロック中", template[int(len(template) * 0.4)][2])]
        else:
            logs_to_include = template[:3]

        for i, (level, message, progress) in enumerate(logs_to_include):
            logs.append({
                "id": f"log-{agent_id}-{i:03d}",
                "timestamp": (base_time + timedelta(minutes=i * random.randint(1, 4))).isoformat(),
                "level": level,
                "message": message,
                "progress": progress,
                "metadata": {"agent_type": agent_type}
            })

        return logs

    # Project CRUD
    def get_projects(self) -> List[Dict]:
        return list(self.projects.values())

    def get_project(self, project_id: str) -> Optional[Dict]:
        return self.projects.get(project_id)

    def create_project(self, data: Dict) -> Dict:
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
        return project

    def update_project(self, project_id: str, data: Dict) -> Optional[Dict]:
        if project_id not in self.projects:
            return None

        project = self.projects[project_id]
        project.update(data)
        project["updatedAt"] = datetime.now().isoformat()
        return project

    def delete_project(self, project_id: str) -> bool:
        if project_id in self.projects:
            del self.projects[project_id]
            # Clean up related data
            self.agents = {k: v for k, v in self.agents.items() if v["projectId"] != project_id}
            self.checkpoints = {k: v for k, v in self.checkpoints.items() if v["projectId"] != project_id}
            if project_id in self.metrics:
                del self.metrics[project_id]
            return True
        return False

    # Agent operations
    def get_agents_by_project(self, project_id: str) -> List[Dict]:
        return [a for a in self.agents.values() if a["projectId"] == project_id]

    def get_agent(self, agent_id: str) -> Optional[Dict]:
        return self.agents.get(agent_id)

    def get_agent_logs(self, agent_id: str) -> List[Dict]:
        return self.agent_logs.get(agent_id, [])

    def create_agent(self, project_id: str, agent_type: str) -> Dict:
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
        if agent_id not in self.agents:
            return None
        self.agents[agent_id].update(data)
        return self.agents[agent_id]

    def add_agent_log(self, agent_id: str, level: str, message: str, progress: Optional[int] = None):
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
        return log_entry

    # Checkpoint operations
    def get_checkpoints_by_project(self, project_id: str) -> List[Dict]:
        return [c for c in self.checkpoints.values() if c["projectId"] == project_id]

    def get_checkpoint(self, checkpoint_id: str) -> Optional[Dict]:
        return self.checkpoints.get(checkpoint_id)

    def create_checkpoint(self, project_id: str, agent_id: str, data: Dict) -> Dict:
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
        if checkpoint_id not in self.checkpoints:
            return None

        checkpoint = self.checkpoints[checkpoint_id]
        now = datetime.now().isoformat()

        checkpoint["status"] = resolution  # approved, rejected, revision_requested
        checkpoint["feedback"] = feedback
        checkpoint["resolvedAt"] = now
        checkpoint["updatedAt"] = now

        return checkpoint

    # Metrics operations
    def get_project_metrics(self, project_id: str) -> Optional[Dict]:
        return self.metrics.get(project_id)

    def update_project_metrics(self, project_id: str, data: Dict) -> Dict:
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
                "phaseName": "Phase 1: 企画・設計"
            }

        self.metrics[project_id].update(data)
        return self.metrics[project_id]

    # Subscription management
    def add_subscription(self, project_id: str, sid: str):
        if project_id not in self.subscriptions:
            self.subscriptions[project_id] = set()
        self.subscriptions[project_id].add(sid)

    def remove_subscription(self, project_id: str, sid: str):
        if project_id in self.subscriptions:
            self.subscriptions[project_id].discard(sid)

    def remove_all_subscriptions(self, sid: str):
        for project_id in self.subscriptions:
            self.subscriptions[project_id].discard(sid)

    def get_subscribers(self, project_id: str) -> set:
        return self.subscriptions.get(project_id, set())
