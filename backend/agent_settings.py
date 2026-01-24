
"""Agent settings - wraps config_loader for agent configuration"""
from typing import Dict,Set,TypedDict
from dataclasses import dataclass
from config_loader import (
 get_agent_definitions_from_yaml as _get_agent_definitions,
 get_high_cost_agents_from_yaml as _get_high_cost_agents,
 get_quality_check_defaults_from_yaml as _get_quality_check_defaults,
 get_agent_phases_from_yaml as _get_agent_phases,
 get_agent_display_names_from_yaml as _get_agent_display_names,
)


class AgentDefinition(TypedDict):
 label:str
 shortLabel:str
 phase:int
 speechBubble:str


def get_agent_definitions()->Dict[str,AgentDefinition]:
 return _get_agent_definitions()


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
 defaults = _get_quality_check_defaults()
 high_cost = _get_high_cost_agents()
 settings = {}
 for agent_type,enabled in defaults.items():
  settings[agent_type] = QualityCheckConfig(
   enabled=enabled,
   max_retries=3,
   is_high_cost=agent_type in high_cost,
  )
 return settings


def is_high_cost_agent(agent_type:str)->bool:
 return agent_type in _get_high_cost_agents()


def get_agent_phases()->Dict[str,list]:
 return _get_agent_phases()


def get_agent_display_names()->Dict[str,str]:
 return _get_agent_display_names()


AGENT_DEFINITIONS = _get_agent_definitions()
HIGH_COST_AGENTS:Set[str] = _get_high_cost_agents()
AGENT_PHASES = _get_agent_phases()
AGENT_DISPLAY_NAMES = _get_agent_display_names()
