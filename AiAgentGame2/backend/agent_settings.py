"""
Agent Settings Module

品質チェック設定の定義とデフォルト値を管理
"""

from typing import Dict, Set
from dataclasses import dataclass, field


# 高コストエージェント（画像/音声/動画系）
# これらはデフォルトで品質チェックOFF
HIGH_COST_AGENTS: Set[str] = {
    # Phase 2: Asset系
    "asset_leader",
    "asset_worker",
    # Phase 3: Asset Review
    "asset_review_worker",
}


# デフォルト品質チェック設定
# True = 品質チェックON, False = OFF
DEFAULT_QUALITY_CHECK_SETTINGS: Dict[str, bool] = {
    # ========================================
    # Phase 1: Planning - Leaders
    # ========================================
    "concept_leader": True,
    "design_leader": True,
    "scenario_leader": True,
    "character_leader": True,
    "world_leader": True,
    "task_split_leader": True,

    # Phase 1: Planning - Workers (CONCEPT)
    "research_worker": True,
    "ideation_worker": True,
    "concept_validation_worker": True,

    # Phase 1: Planning - Workers (DESIGN)
    "architecture_worker": True,
    "component_worker": True,
    "dataflow_worker": True,

    # Phase 1: Planning - Workers (SCENARIO)
    "story_worker": True,
    "dialog_worker": True,
    "event_worker": True,

    # Phase 1: Planning - Workers (CHARACTER)
    "main_character_worker": True,
    "npc_worker": True,
    "relationship_worker": True,

    # Phase 1: Planning - Workers (WORLD)
    "geography_worker": True,
    "lore_worker": True,
    "system_worker": True,

    # Phase 1: Planning - Workers (TASK_SPLIT)
    "analysis_worker": True,
    "decomposition_worker": True,
    "schedule_worker": True,

    # ========================================
    # Phase 2: Development - Leaders
    # ========================================
    "code_leader": True,
    "asset_leader": False,  # High Cost

    # Phase 2: Development - Workers
    "code_worker": True,
    "asset_worker": False,  # High Cost

    # ========================================
    # Phase 3: Quality - Leaders
    # ========================================
    "integrator_leader": True,
    "tester_leader": True,
    "reviewer_leader": True,

    # Phase 3: Quality - Workers (INTEGRATOR)
    "dependency_worker": True,
    "build_worker": True,
    "integration_validation_worker": True,

    # Phase 3: Quality - Workers (TESTER)
    "unit_test_worker": True,
    "integration_test_worker": True,
    "e2e_test_worker": True,
    "performance_test_worker": True,

    # Phase 3: Quality - Workers (REVIEWER)
    "code_review_worker": True,
    "asset_review_worker": False,  # High Cost
    "gameplay_review_worker": True,
    "compliance_worker": True,
}


@dataclass
class QualityCheckConfig:
    """品質チェック設定"""
    enabled: bool = True
    max_retries: int = 3
    is_high_cost: bool = False

    def to_dict(self) -> Dict:
        return {
            "enabled": self.enabled,
            "maxRetries": self.max_retries,
            "isHighCost": self.is_high_cost,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "QualityCheckConfig":
        return cls(
            enabled=data.get("enabled", True),
            max_retries=data.get("maxRetries", 3),
            is_high_cost=data.get("isHighCost", False),
        )


def get_default_quality_settings() -> Dict[str, QualityCheckConfig]:
    """全エージェントのデフォルト品質チェック設定を取得"""
    settings = {}
    for agent_type, enabled in DEFAULT_QUALITY_CHECK_SETTINGS.items():
        is_high_cost = agent_type in HIGH_COST_AGENTS
        settings[agent_type] = QualityCheckConfig(
            enabled=enabled,
            max_retries=3,
            is_high_cost=is_high_cost,
        )
    return settings


def is_high_cost_agent(agent_type: str) -> bool:
    """高コストエージェントかどうかを判定"""
    return agent_type in HIGH_COST_AGENTS


# Phase別エージェントグループ
AGENT_PHASES = {
    "phase1_leaders": [
        "concept_leader",
        "design_leader",
        "scenario_leader",
        "character_leader",
        "world_leader",
        "task_split_leader",
    ],
    "phase1_concept_workers": [
        "research_worker",
        "ideation_worker",
        "concept_validation_worker",
    ],
    "phase1_design_workers": [
        "architecture_worker",
        "component_worker",
        "dataflow_worker",
    ],
    "phase1_scenario_workers": [
        "story_worker",
        "dialog_worker",
        "event_worker",
    ],
    "phase1_character_workers": [
        "main_character_worker",
        "npc_worker",
        "relationship_worker",
    ],
    "phase1_world_workers": [
        "geography_worker",
        "lore_worker",
        "system_worker",
    ],
    "phase1_task_split_workers": [
        "analysis_worker",
        "decomposition_worker",
        "schedule_worker",
    ],
    "phase2_leaders": [
        "code_leader",
        "asset_leader",
    ],
    "phase2_workers": [
        "code_worker",
        "asset_worker",
    ],
    "phase3_leaders": [
        "integrator_leader",
        "tester_leader",
        "reviewer_leader",
    ],
    "phase3_integrator_workers": [
        "dependency_worker",
        "build_worker",
        "integration_validation_worker",
    ],
    "phase3_tester_workers": [
        "unit_test_worker",
        "integration_test_worker",
        "e2e_test_worker",
        "performance_test_worker",
    ],
    "phase3_reviewer_workers": [
        "code_review_worker",
        "asset_review_worker",
        "gameplay_review_worker",
        "compliance_worker",
    ],
}


# エージェント表示名（役割は別カラムで表示されるため、名前部分のみ）
AGENT_DISPLAY_NAMES: Dict[str, str] = {
    # Phase 1 Leaders
    "concept_leader": "コンセプト",
    "design_leader": "デザイン",
    "scenario_leader": "シナリオ",
    "character_leader": "キャラクター",
    "world_leader": "ワールド",
    "task_split_leader": "タスク分割",
    # Phase 1 Workers
    "research_worker": "リサーチ",
    "ideation_worker": "アイデア",
    "concept_validation_worker": "コンセプト検証",
    "architecture_worker": "アーキテクチャ",
    "component_worker": "コンポーネント",
    "dataflow_worker": "データフロー",
    "story_worker": "ストーリー",
    "dialog_worker": "ダイアログ",
    "event_worker": "イベント",
    "main_character_worker": "メインキャラ",
    "npc_worker": "NPC",
    "relationship_worker": "関係性",
    "geography_worker": "地理",
    "lore_worker": "設定",
    "system_worker": "システム",
    "analysis_worker": "分析",
    "decomposition_worker": "分解",
    "schedule_worker": "スケジュール",
    # Phase 2
    "code_leader": "コード",
    "asset_leader": "アセット",
    "code_worker": "コード",
    "asset_worker": "アセット",
    # Phase 3
    "integrator_leader": "統合",
    "tester_leader": "テスト",
    "reviewer_leader": "レビュー",
    "dependency_worker": "依存関係",
    "build_worker": "ビルド",
    "integration_validation_worker": "統合検証",
    "unit_test_worker": "ユニットテスト",
    "integration_test_worker": "統合テスト",
    "e2e_test_worker": "E2Eテスト",
    "performance_test_worker": "パフォーマンステスト",
    "code_review_worker": "コードレビュー",
    "asset_review_worker": "アセットレビュー",
    "gameplay_review_worker": "ゲームプレイレビュー",
    "compliance_worker": "コンプライアンス",
}
