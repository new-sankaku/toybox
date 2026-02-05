from datetime import datetime
from typing import Any,Dict,List,AsyncGenerator
from abc import abstractmethod

from ..base import (
    AgentRunner,
    AgentContext,
    AgentOutput,
    AgentType,
    AgentStatus,
)
from config_loaders.mock_config import get_checkpoint_title_config
from middleware.logger import get_logger


class MockRunnerBase(AgentRunner):

    def __init__(self,trace_service=None,**kwargs):
        self._trace_service=trace_service
        self._simulation_speed=kwargs.get("simulation_speed",1.0)

    async def run_agent(self,context:AgentContext)->AgentOutput:
        started_at=datetime.now().isoformat()
        tokens_used=0
        output={}

        try:
            async for event in self.run_agent_stream(context):
                tokens_used,output=self._process_stream_event(event,tokens_used,output)

            return AgentOutput(
                agent_id=context.agent_id,
                agent_type=context.agent_type,
                status=AgentStatus.COMPLETED,
                output=output,
                tokens_used=tokens_used,
                duration_seconds=(datetime.now()-datetime.fromisoformat(started_at)).total_seconds(),
                started_at=started_at,
                completed_at=datetime.now().isoformat(),
            )
        except Exception as e:
            get_logger().error(f"MockRunner error: {e}",exc_info=True)
            return AgentOutput(
                agent_id=context.agent_id,
                agent_type=context.agent_type,
                status=AgentStatus.FAILED,
                error=str(e),
                tokens_used=tokens_used,
                started_at=started_at,
                completed_at=datetime.now().isoformat(),
            )

    def _process_stream_event(
        self,
        event:Dict[str,Any],
        tokens_used:int,
        output:Dict[str,Any],
    )->tuple[int,Dict[str,Any]]:
        event_type=event["type"]
        data=event["data"]
        if event_type=="output":
            return tokens_used,data
        if event_type=="tokens":
            return tokens_used+data.get("count",0),output
        return tokens_used,output

    @abstractmethod
    async def run_agent_stream(self,context:AgentContext)->AsyncGenerator[Dict[str,Any],None]:
        pass

    def _log_event(self,level:str,message:str)->Dict[str,Any]:
        return {
            "type":"log",
            "data":{"level":level,"message":message,"timestamp":datetime.now().isoformat()},
        }

    def _progress_event(self,progress:int,task:str)->Dict[str,Any]:
        return {"type":"progress","data":{"progress":progress,"current_task":task}}

    def _get_agent_type_str(self,context:AgentContext)->str:
        if hasattr(context.agent_type,"value"):
            return context.agent_type.value
        return str(context.agent_type)

    def _generate_checkpoint_data(
        self,
        context:AgentContext,
        output:Dict[str,Any],
        extra_data:Dict[str,Any]=None,
    )->Dict[str,Any]:
        agent_type=self._get_agent_type_str(context)
        cp_config=get_checkpoint_title_config(agent_type)
        cp_type=cp_config.get("type","review")
        title=cp_config.get("title","レビュー依頼")

        checkpoint_data={
            "type":cp_type,
            "title":title,
            "description":f"{agent_type}エージェントの出力を確認してください",
            "output":output,
            "timestamp":datetime.now().isoformat(),
        }
        if extra_data:
            checkpoint_data.update(extra_data)
        return checkpoint_data

    def _emit_checkpoint_callback(
        self,
        context:AgentContext,
        checkpoint_data:Dict[str,Any],
    )->None:
        if context.on_checkpoint:
            context.on_checkpoint(checkpoint_data["type"],checkpoint_data)

    def get_supported_agents(self)->List[AgentType]:
        return list(AgentType)

    def validate_context(self,context:AgentContext)->bool:
        return True
