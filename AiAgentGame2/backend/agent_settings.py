from typing import Dict,Set,TypedDict
from dataclasses import dataclass,field


class AgentDefinition(TypedDict):
    label:str
    shortLabel:str
    phase:int
    speechBubble:str


AGENT_DEFINITIONS:Dict[str,AgentDefinition] = {

    'concept':{
        'label':'コンセプト',
        'shortLabel':'コンセプト',
        'phase':0,
        'speechBubble':'全体を統括するのだ',
    },

    'task_split_1':{
        'label':'タスク分割1',
        'shortLabel':'分割1',
        'phase':1,
        'speechBubble':'設計タスクを分配します',
    },

    'concept_detail':{
        'label':'コンセプト詳細',
        'shortLabel':'詳細',
        'phase':2,
        'speechBubble':'企画を練り上げます',
    },
    'scenario':{
        'label':'シナリオ',
        'shortLabel':'シナリオ',
        'phase':2,
        'speechBubble':'物語を紡ぎます',
    },
    'world':{
        'label':'世界観',
        'shortLabel':'世界観',
        'phase':2,
        'speechBubble':'世界を創造します',
    },
    'game_design':{
        'label':'ゲームデザイン',
        'shortLabel':'デザイン',
        'phase':2,
        'speechBubble':'システムを設計します',
    },
    'tech_spec':{
        'label':'技術仕様',
        'shortLabel':'テック',
        'phase':2,
        'speechBubble':'技術を検証します',
    },

    'task_split_2':{
        'label':'タスク分割2',
        'shortLabel':'分割2',
        'phase':3,
        'speechBubble':'アセットタスクを分配',
    },

    'asset_character':{
        'label':'キャラクター',
        'shortLabel':'キャラ',
        'phase':4,
        'speechBubble':'キャラを描くにゃ',
    },
    'asset_background':{
        'label':'背景',
        'shortLabel':'背景',
        'phase':4,
        'speechBubble':'背景を観察中...',
    },
    'asset_ui':{
        'label':'UI',
        'shortLabel':'UI',
        'phase':4,
        'speechBubble':'UIをデザイン中',
    },
    'asset_effect':{
        'label':'エフェクト',
        'shortLabel':'エフェクト',
        'phase':4,
        'speechBubble':'キラキラを作るよ',
    },
    'asset_bgm':{
        'label':'BGM',
        'shortLabel':'BGM',
        'phase':4,
        'speechBubble':'旋律を奏でます',
    },
    'asset_voice':{
        'label':'ボイス',
        'shortLabel':'ボイス',
        'phase':4,
        'speechBubble':'声を届けます',
    },
    'asset_sfx':{
        'label':'効果音',
        'shortLabel':'効果音',
        'phase':4,
        'speechBubble':'音を探索中...',
    },

    'task_split_3':{
        'label':'タスク分割3',
        'shortLabel':'分割3',
        'phase':5,
        'speechBubble':'実装タスクを分配',
    },

    'code':{
        'label':'コード',
        'shortLabel':'コード',
        'phase':6,
        'speechBubble':'コード...実装中...',
    },
    'event':{
        'label':'イベント',
        'shortLabel':'イベント',
        'phase':6,
        'speechBubble':'イベントを仕込む',
    },
    'ui_integration':{
        'label':'UI統合',
        'shortLabel':'UI統合',
        'phase':6,
        'speechBubble':'UI部品を組み立て中',
    },
    'asset_integration':{
        'label':'アセット統合',
        'shortLabel':'統合',
        'phase':6,
        'speechBubble':'アセットを統合中',
    },

    'task_split_4':{
        'label':'タスク分割4',
        'shortLabel':'分割4',
        'phase':7,
        'speechBubble':'テストタスクを分配',
    },

    'unit_test':{
        'label':'単体テスト',
        'shortLabel':'テスト1',
        'phase':8,
        'speechBubble':'バグを焼き尽くす！',
    },
    'integration_test':{
        'label':'統合テスト',
        'shortLabel':'テスト2',
        'phase':8,
        'speechBubble':'慎重にテスト中...',
    },
}




HIGH_COST_AGENTS:Set[str] = {

    "asset_leader",
    "asset_worker",

    "asset_review_worker",
}




DEFAULT_QUALITY_CHECK_SETTINGS:Dict[str,bool] = {



    "concept_leader":True,
    "design_leader":True,
    "scenario_leader":True,
    "character_leader":True,
    "world_leader":True,
    "task_split_leader":True,


    "research_worker":True,
    "ideation_worker":True,
    "concept_validation_worker":True,


    "architecture_worker":True,
    "component_worker":True,
    "dataflow_worker":True,


    "story_worker":True,
    "dialog_worker":True,
    "event_worker":True,


    "main_character_worker":True,
    "npc_worker":True,
    "relationship_worker":True,


    "geography_worker":True,
    "lore_worker":True,
    "system_worker":True,


    "analysis_worker":True,
    "decomposition_worker":True,
    "schedule_worker":True,




    "code_leader":True,
    "asset_leader":False,


    "code_worker":True,
    "asset_worker":False,




    "integrator_leader":True,
    "tester_leader":True,
    "reviewer_leader":True,


    "dependency_worker":True,
    "build_worker":True,
    "integration_validation_worker":True,


    "unit_test_worker":True,
    "integration_test_worker":True,
    "e2e_test_worker":True,
    "performance_test_worker":True,


    "code_review_worker":True,
    "asset_review_worker":False,
    "gameplay_review_worker":True,
    "compliance_worker":True,
}


@dataclass
class QualityCheckConfig:
    enabled:bool = True
    max_retries:int = 3
    is_high_cost:bool = False

    def to_dict(self)->Dict:
        return {
            "enabled":self.enabled,
            "maxRetries":self.max_retries,
            "isHighCost":self.is_high_cost,
        }

    @classmethod
    def from_dict(cls,data:Dict)->"QualityCheckConfig":
        return cls(
            enabled=data.get("enabled",True),
            max_retries=data.get("maxRetries",3),
            is_high_cost=data.get("isHighCost",False),
        )


def get_default_quality_settings()->Dict[str,QualityCheckConfig]:
    settings = {}
    for agent_type,enabled in DEFAULT_QUALITY_CHECK_SETTINGS.items():
        is_high_cost = agent_type in HIGH_COST_AGENTS
        settings[agent_type] = QualityCheckConfig(
            enabled=enabled,
            max_retries=3,
            is_high_cost=is_high_cost,
        )
    return settings


def is_high_cost_agent(agent_type:str)->bool:
    return agent_type in HIGH_COST_AGENTS


AGENT_PHASES = {
    "phase1_leaders":[
        "concept_leader",
        "design_leader",
        "scenario_leader",
        "character_leader",
        "world_leader",
        "task_split_leader",
    ],
    "phase1_concept_workers":[
        "research_worker",
        "ideation_worker",
        "concept_validation_worker",
    ],
    "phase1_design_workers":[
        "architecture_worker",
        "component_worker",
        "dataflow_worker",
    ],
    "phase1_scenario_workers":[
        "story_worker",
        "dialog_worker",
        "event_worker",
    ],
    "phase1_character_workers":[
        "main_character_worker",
        "npc_worker",
        "relationship_worker",
    ],
    "phase1_world_workers":[
        "geography_worker",
        "lore_worker",
        "system_worker",
    ],
    "phase1_task_split_workers":[
        "analysis_worker",
        "decomposition_worker",
        "schedule_worker",
    ],
    "phase2_leaders":[
        "code_leader",
        "asset_leader",
    ],
    "phase2_workers":[
        "code_worker",
        "asset_worker",
    ],
    "phase3_leaders":[
        "integrator_leader",
        "tester_leader",
        "reviewer_leader",
    ],
    "phase3_integrator_workers":[
        "dependency_worker",
        "build_worker",
        "integration_validation_worker",
    ],
    "phase3_tester_workers":[
        "unit_test_worker",
        "integration_test_worker",
        "e2e_test_worker",
        "performance_test_worker",
    ],
    "phase3_reviewer_workers":[
        "code_review_worker",
        "asset_review_worker",
        "gameplay_review_worker",
        "compliance_worker",
    ],
}


AGENT_DISPLAY_NAMES:Dict[str,str] = {

    "concept_leader":"コンセプト",
    "design_leader":"デザイン",
    "scenario_leader":"シナリオ",
    "character_leader":"キャラクター",
    "world_leader":"ワールド",
    "task_split_leader":"タスク分割",

    "research_worker":"リサーチ",
    "ideation_worker":"アイデア",
    "concept_validation_worker":"コンセプト検証",
    "architecture_worker":"アーキテクチャ",
    "component_worker":"コンポーネント",
    "dataflow_worker":"データフロー",
    "story_worker":"ストーリー",
    "dialog_worker":"ダイアログ",
    "event_worker":"イベント",
    "main_character_worker":"メインキャラ",
    "npc_worker":"NPC",
    "relationship_worker":"関係性",
    "geography_worker":"地理",
    "lore_worker":"設定",
    "system_worker":"システム",
    "analysis_worker":"分析",
    "decomposition_worker":"分解",
    "schedule_worker":"スケジュール",

    "code_leader":"コード",
    "asset_leader":"アセット",
    "code_worker":"コード",
    "asset_worker":"アセット",

    "integrator_leader":"統合",
    "tester_leader":"テスト",
    "reviewer_leader":"レビュー",
    "dependency_worker":"依存関係",
    "build_worker":"ビルド",
    "integration_validation_worker":"統合検証",
    "unit_test_worker":"ユニットテスト",
    "integration_test_worker":"統合テスト",
    "e2e_test_worker":"E2Eテスト",
    "performance_test_worker":"パフォーマンステスト",
    "code_review_worker":"コードレビュー",
    "asset_review_worker":"アセットレビュー",
    "gameplay_review_worker":"ゲームプレイレビュー",
    "compliance_worker":"コンプライアンス",
}
