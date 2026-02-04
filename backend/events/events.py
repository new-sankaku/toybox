from dataclasses import dataclass,field
from typing import Dict,Any,Optional


@dataclass
class SystemLogCreated:
    project_id:str
    log:Dict[str,Any]


@dataclass
class AgentStarted:
    project_id:str
    agent_id:str
    agent:Dict[str,Any]


@dataclass
class AgentProgress:
    project_id:str
    agent_id:str
    progress:int
    current_task:str
    tokens_used:int=0
    message:str=""


@dataclass
class AgentCompleted:
    project_id:str
    agent_id:str
    agent:Optional[Dict[str,Any]]=None


@dataclass
class AgentFailed:
    project_id:str
    agent_id:str
    reason:str=""


@dataclass
class AgentResumed:
    project_id:str
    agent_id:str
    agent:Dict[str,Any]=field(default_factory=dict)
    reason:str=""


@dataclass
class AgentRetried:
    project_id:str
    agent_id:str
    agent:Dict[str,Any]=field(default_factory=dict)
    previous_status:str=""


@dataclass
class CheckpointCreated:
    project_id:str
    checkpoint_id:str
    agent_id:str
    checkpoint:Dict[str,Any]=field(default_factory=dict)
    auto_approved:bool=False


@dataclass
class CheckpointResolved:
    project_id:str
    checkpoint_id:str
    checkpoint:Dict[str,Any]=field(default_factory=dict)
    resolution:str=""
    agent_id:str=""
    agent_status:str=""


@dataclass
class AssetCreated:
    project_id:str
    asset:Dict[str,Any]=field(default_factory=dict)
    auto_approved:bool=False


@dataclass
class AssetUpdated:
    project_id:str
    asset:Dict[str,Any]=field(default_factory=dict)
    auto_approved:bool=False


@dataclass
class PhaseChanged:
    project_id:str
    phase:int=0
    phase_name:str=""


@dataclass
class MetricsUpdated:
    project_id:str
    metrics:Dict[str,Any]=field(default_factory=dict)


@dataclass
class ProjectUpdated:
    project_id:str
    project:Dict[str,Any]=field(default_factory=dict)


@dataclass
class ProjectStatusChanged:
    project_id:str
    status:str=""
    previous_status:str=""
    retried_agents:int=0
    reason:str=""
    intervention_id:str=""


@dataclass
class ProjectInitialized:
    project_id:str


@dataclass
class ProjectPaused:
    project_id:str
    reason:str=""
    intervention_id:str=""


@dataclass
class AgentPaused:
    project_id:str
    agent_id:str
    agent:Dict[str,Any]=field(default_factory=dict)
    reason:str=""


@dataclass
class AgentActivated:
    project_id:str
    agent_id:str
    agent:Dict[str,Any]=field(default_factory=dict)
    previous_status:str=""
    intervention_id:str=""


@dataclass
class AgentCreated:
    project_id:str
    agent_id:str
    parent_agent_id:str=""
    agent:Dict[str,Any]=field(default_factory=dict)


@dataclass
class AgentWaitingResponse:
    project_id:str
    agent_id:str
    agent:Dict[str,Any]=field(default_factory=dict)
    intervention_id:str=""
    question:str=""


@dataclass
class AgentSnapshotRestored:
    project_id:str
    agent_id:str
    snapshot_id:str=""
    snapshot:Dict[str,Any]=field(default_factory=dict)


@dataclass
class InterventionCreated:
    project_id:str
    intervention_id:str
    intervention:Dict[str,Any]=field(default_factory=dict)


@dataclass
class InterventionAcknowledged:
    project_id:str
    intervention_id:str
    intervention:Dict[str,Any]=field(default_factory=dict)


@dataclass
class InterventionProcessed:
    project_id:str
    intervention_id:str
    intervention:Dict[str,Any]=field(default_factory=dict)


@dataclass
class InterventionDeleted:
    project_id:str
    intervention_id:str


@dataclass
class InterventionResponseAdded:
    project_id:str
    intervention_id:str
    intervention:Dict[str,Any]=field(default_factory=dict)
    sender:str=""
    agent_id:str=""


@dataclass
class AssetBulkUpdated:
    project_id:str
    assets:list=field(default_factory=list)
    status:str=""


@dataclass
class AssetRegenerationRequested:
    project_id:str
    asset_id:str
    feedback:str=""
