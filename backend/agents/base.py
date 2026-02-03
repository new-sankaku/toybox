from abc import ABC,abstractmethod
from dataclasses import dataclass,field
from typing import Any,Dict,List,Optional,Callable,AsyncGenerator
from enum import Enum
from datetime import datetime


class AgentType(str,Enum):
    CONCEPT="concept"
    TASK_SPLIT_1="task_split_1"
    CONCEPT_DETAIL="concept_detail"
    SCENARIO="scenario"
    WORLD="world"
    GAME_DESIGN="game_design"
    TECH_SPEC="tech_spec"
    TASK_SPLIT_2="task_split_2"
    DATA_DESIGN="data_design"
    ASSET_CHARACTER="asset_character"
    ASSET_BACKGROUND="asset_background"
    ASSET_UI="asset_ui"
    ASSET_EFFECT="asset_effect"
    ASSET_BGM="asset_bgm"
    ASSET_VOICE="asset_voice"
    ASSET_SFX="asset_sfx"
    TASK_SPLIT_3="task_split_3"
    CODE="code"
    EVENT="event"
    UI_INTEGRATION="ui_integration"
    ASSET_INTEGRATION="asset_integration"
    TASK_SPLIT_4="task_split_4"
    UNIT_TEST="unit_test"
    INTEGRATION_TEST="integration_test"

    CONCEPT_LEADER="concept_leader"
    DESIGN_LEADER="design_leader"
    SCENARIO_LEADER="scenario_leader"
    CHARACTER_LEADER="character_leader"
    WORLD_LEADER="world_leader"
    TASK_SPLIT_LEADER="task_split_leader"
    CODE_LEADER="code_leader"
    ASSET_LEADER="asset_leader"
    INTEGRATOR_LEADER="integrator_leader"
    TESTER_LEADER="tester_leader"
    REVIEWER_LEADER="reviewer_leader"

    RESEARCH_WORKER="research_worker"
    IDEATION_WORKER="ideation_worker"
    CONCEPT_VALIDATION_WORKER="concept_validation_worker"
    ARCHITECTURE_WORKER="architecture_worker"
    COMPONENT_WORKER="component_worker"
    DATAFLOW_WORKER="dataflow_worker"
    STORY_WORKER="story_worker"
    DIALOG_WORKER="dialog_worker"
    EVENT_WORKER="event_worker"
    MAIN_CHARACTER_WORKER="main_character_worker"
    NPC_WORKER="npc_worker"
    RELATIONSHIP_WORKER="relationship_worker"
    GEOGRAPHY_WORKER="geography_worker"
    LORE_WORKER="lore_worker"
    SYSTEM_WORKER="system_worker"
    ANALYSIS_WORKER="analysis_worker"
    DECOMPOSITION_WORKER="decomposition_worker"
    SCHEDULE_WORKER="schedule_worker"
    CODE_WORKER="code_worker"
    ASSET_WORKER="asset_worker"
    DEPENDENCY_WORKER="dependency_worker"
    BUILD_WORKER="build_worker"
    INTEGRATION_VALIDATION_WORKER="integration_validation_worker"
    UNIT_TEST_WORKER="unit_test_worker"
    INTEGRATION_TEST_WORKER="integration_test_worker"
    E2E_TEST_WORKER="e2e_test_worker"
    PERFORMANCE_TEST_WORKER="performance_test_worker"
    CODE_REVIEW_WORKER="code_review_worker"
    ASSET_REVIEW_WORKER="asset_review_worker"
    GAMEPLAY_REVIEW_WORKER="gameplay_review_worker"
    COMPLIANCE_WORKER="compliance_worker"


class AgentStatus(str,Enum):
    PENDING="pending"
    RUNNING="running"
    WAITING_APPROVAL="waiting_approval"
    WAITING_RESPONSE="waiting_response"
    WAITING_PROVIDER="waiting_provider"
    PAUSED="paused"
    COMPLETED="completed"
    FAILED="failed"


@dataclass
class QualityCheckSettings:
    enabled:bool=True
    max_retries:int=3
    is_high_cost:bool=False

    def to_dict(self)->Dict[str,Any]:
        return {
            "enabled":self.enabled,
            "maxRetries":self.max_retries,
            "isHighCost":self.is_high_cost,
        }

    @classmethod
    def from_dict(cls,data:Dict[str,Any])->"QualityCheckSettings":
        return cls(
            enabled=data.get("enabled",True),
            max_retries=data.get("maxRetries",3),
            is_high_cost=data.get("isHighCost",False),
        )


@dataclass
class AgentContext:
    project_id:str
    agent_id:str
    agent_type:AgentType
    project_concept:Optional[str]=None
    previous_outputs:Dict[str,Any]=field(default_factory=dict)
    config:Dict[str,Any]=field(default_factory=dict)
    quality_check:Optional[QualityCheckSettings]=None
    assigned_task:Optional[str]=None
    leader_analysis:Optional[Dict[str,Any]]=None
    on_progress:Optional[Callable[[int,str],None]]=None
    on_log:Optional[Callable[[str,str],None]]=None
    on_checkpoint:Optional[Callable[[str,Dict],None]]=None
    on_speech:Optional[Callable[[str],None]]=None


@dataclass
class AgentOutput:
    agent_id:str
    agent_type:AgentType
    status:AgentStatus
    output:Dict[str,Any]=field(default_factory=dict)
    tokens_used:int=0
    duration_seconds:float=0
    error:Optional[str]=None
    started_at:Optional[str]=None
    completed_at:Optional[str]=None
    generation_counts:Optional[Dict[str,Any]]=None


class AgentRunner(ABC):
    """全ての実装（Mock, LangGraph）はこのインターフェースを実装する"""

    @abstractmethod
    async def run_agent(self,context:AgentContext)->AgentOutput:
        pass

    @abstractmethod
    async def run_agent_stream(self,context:AgentContext)->AsyncGenerator[Dict[str,Any],None]:
        pass

    @abstractmethod
    def get_supported_agents(self)->List[AgentType]:
        pass

    @abstractmethod
    def validate_context(self,context:AgentContext)->bool:
        pass


class CheckpointHandler(ABC):
    """Human-in-the-loop のチェックポイント処理を担当"""

    @abstractmethod
    async def create_checkpoint(
        self,project_id:str,agent_id:str,checkpoint_type:str,title:str,output:Dict[str,Any]
    )->str:
        pass

    @abstractmethod
    async def wait_for_resolution(self,checkpoint_id:str,timeout_seconds:Optional[float]=None)->Dict[str,Any]:
        pass

    @abstractmethod
    async def get_checkpoint_status(self,checkpoint_id:str)->Dict[str,Any]:
        pass
