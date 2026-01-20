from abc import ABC,abstractmethod
from dataclasses import dataclass,field
from typing import Any,Dict,List,Optional,Callable,AsyncGenerator
from enum import Enum
from datetime import datetime


class AgentType(str,Enum):



    CONCEPT_LEADER = "concept_leader"
    DESIGN_LEADER = "design_leader"
    SCENARIO_LEADER = "scenario_leader"
    CHARACTER_LEADER = "character_leader"
    WORLD_LEADER = "world_leader"
    TASK_SPLIT_LEADER = "task_split_leader"


    RESEARCH_WORKER = "research_worker"
    IDEATION_WORKER = "ideation_worker"
    CONCEPT_VALIDATION_WORKER = "concept_validation_worker"


    ARCHITECTURE_WORKER = "architecture_worker"
    COMPONENT_WORKER = "component_worker"
    DATAFLOW_WORKER = "dataflow_worker"


    STORY_WORKER = "story_worker"
    DIALOG_WORKER = "dialog_worker"
    EVENT_WORKER = "event_worker"


    MAIN_CHARACTER_WORKER = "main_character_worker"
    NPC_WORKER = "npc_worker"
    RELATIONSHIP_WORKER = "relationship_worker"


    GEOGRAPHY_WORKER = "geography_worker"
    LORE_WORKER = "lore_worker"
    SYSTEM_WORKER = "system_worker"


    ANALYSIS_WORKER = "analysis_worker"
    DECOMPOSITION_WORKER = "decomposition_worker"
    SCHEDULE_WORKER = "schedule_worker"




    CODE_LEADER = "code_leader"
    ASSET_LEADER = "asset_leader"


    CODE_WORKER = "code_worker"
    ASSET_WORKER = "asset_worker"




    INTEGRATOR_LEADER = "integrator_leader"
    TESTER_LEADER = "tester_leader"
    REVIEWER_LEADER = "reviewer_leader"


    DEPENDENCY_WORKER = "dependency_worker"
    BUILD_WORKER = "build_worker"
    INTEGRATION_VALIDATION_WORKER = "integration_validation_worker"


    UNIT_TEST_WORKER = "unit_test_worker"
    INTEGRATION_TEST_WORKER = "integration_test_worker"
    E2E_TEST_WORKER = "e2e_test_worker"
    PERFORMANCE_TEST_WORKER = "performance_test_worker"


    CODE_REVIEW_WORKER = "code_review_worker"
    ASSET_REVIEW_WORKER = "asset_review_worker"
    GAMEPLAY_REVIEW_WORKER = "gameplay_review_worker"
    COMPLIANCE_WORKER = "compliance_worker"





    CONCEPT = "concept_leader"
    DESIGN = "design_leader"
    SCENARIO = "scenario_leader"
    CHARACTER = "character_leader"
    WORLD = "world_leader"
    TASK_SPLIT = "task_split_leader"
    INTEGRATOR = "integrator_leader"
    TESTER = "tester_leader"
    REVIEWER = "reviewer_leader"


class AgentStatus(str,Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class QualityCheckSettings:
    enabled:bool = True
    max_retries:int = 3
    is_high_cost:bool = False

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
    project_concept:Optional[str] = None
    previous_outputs:Dict[str,Any] = field(default_factory=dict)
    config:Dict[str,Any] = field(default_factory=dict)
    quality_check:Optional[QualityCheckSettings] = None
    on_progress:Optional[Callable[[int,str],None]] = None
    on_log:Optional[Callable[[str,str],None]] = None
    on_checkpoint:Optional[Callable[[str,Dict],None]] = None


@dataclass
class AgentOutput:
    agent_id:str
    agent_type:AgentType
    status:AgentStatus
    output:Dict[str,Any] = field(default_factory=dict)
    tokens_used:int = 0
    duration_seconds:float = 0
    error:Optional[str] = None
    started_at:Optional[str] = None
    completed_at:Optional[str] = None


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
    async def wait_for_resolution(self,checkpoint_id:str,timeout_seconds:Optional[float] = None)->Dict[str,Any]:
        pass

    @abstractmethod
    async def get_checkpoint_status(self,checkpoint_id:str)->Dict[str,Any]:
        pass
