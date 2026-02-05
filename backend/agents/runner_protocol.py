"""
Agent Runner Protocol Module

オーケストレーターが依存するランナーインターフェースを定義
Protocol を使用して構造的サブタイピングを実現
"""

from typing import Protocol,Dict,Any,Optional
from .base import AgentContext,AgentOutput


class AgentRunnerProtocol(Protocol):
    """オーケストレーターが依存するランナーインターフェース"""

    max_tokens:int

    @classmethod
    def get_job_queue(cls):...

    async def run_agent(self,context:AgentContext)->AgentOutput:...

    def get_trace_service(self):...

    def get_agent_service(self):...

    def resolve_model_for_agent(self,context:AgentContext)->str:...

    def resolve_provider_for_agent(self,context:AgentContext)->str:...

    def get_project_temperature(self,context:AgentContext,agent_type:str)->float:...

    def get_project_token_budget(self,context:Optional[AgentContext])->Optional[Dict[str,Any]]:...

    def get_project_dag_enabled(self,context:AgentContext)->bool:...
