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
    "asset_character",
    "asset_background",
    "asset_ui",
    "asset_effect",
    "asset_bgm",
    "asset_voice",
    "asset_sfx",
}




DEFAULT_QUALITY_CHECK_SETTINGS:Dict[str,bool] = {
    "concept":True,
    "task_split_1":True,
    "concept_detail":True,
    "scenario":True,
    "world":True,
    "game_design":True,
    "tech_spec":True,
    "task_split_2":True,
    "asset_character":True,
    "asset_background":True,
    "asset_ui":True,
    "asset_effect":True,
    "asset_bgm":True,
    "asset_voice":True,
    "asset_sfx":True,
    "task_split_3":True,
    "code":True,
    "event":True,
    "ui_integration":True,
    "asset_integration":True,
    "task_split_4":True,
    "unit_test":True,
    "integration_test":True,
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
    "phase0_concept":[
        "concept",
    ],
    "phase1_task_split":[
        "task_split_1",
    ],
    "phase2_design":[
        "concept_detail",
        "scenario",
        "world",
        "game_design",
        "tech_spec",
    ],
    "phase3_task_split":[
        "task_split_2",
    ],
    "phase4_assets":[
        "asset_character",
        "asset_background",
        "asset_ui",
        "asset_effect",
        "asset_bgm",
        "asset_voice",
        "asset_sfx",
    ],
    "phase5_task_split":[
        "task_split_3",
    ],
    "phase6_implementation":[
        "code",
        "event",
        "ui_integration",
        "asset_integration",
    ],
    "phase7_task_split":[
        "task_split_4",
    ],
    "phase8_testing":[
        "unit_test",
        "integration_test",
    ],
}


AGENT_DISPLAY_NAMES:Dict[str,str] = {
    "concept":"コンセプト",
    "task_split_1":"タスク分割1",
    "concept_detail":"コンセプト詳細",
    "scenario":"シナリオ",
    "world":"世界観",
    "game_design":"ゲームデザイン",
    "tech_spec":"技術仕様",
    "task_split_2":"タスク分割2",
    "asset_character":"キャラクター",
    "asset_background":"背景",
    "asset_ui":"UI",
    "asset_effect":"エフェクト",
    "asset_bgm":"BGM",
    "asset_voice":"ボイス",
    "asset_sfx":"効果音",
    "task_split_3":"タスク分割3",
    "code":"コード",
    "event":"イベント",
    "ui_integration":"UI統合",
    "asset_integration":"アセット統合",
    "task_split_4":"タスク分割4",
    "unit_test":"単体テスト",
    "integration_test":"統合テスト",
}
