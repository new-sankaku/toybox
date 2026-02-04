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
