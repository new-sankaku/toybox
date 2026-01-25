from datetime import datetime
from typing import Any,Dict,List,AsyncGenerator,Optional
import asyncio

from .base import (
    AgentRunner,
    AgentContext,
    AgentOutput,
    AgentType,
    AgentStatus,
)
from config_loader import get_mock_content,get_checkpoint_title_config


class MockAgentRunner(AgentRunner):

    def __init__(self,data_store=None,**kwargs):
        self.data_store = data_store
        self._simulation_speed = kwargs.get("simulation_speed",1.0)

    async def run_agent(self,context:AgentContext)->AgentOutput:
        started_at = datetime.now().isoformat()
        tokens_used = 0
        output = {}

        try:
            async for event in self.run_agent_stream(context):
                if event["type"] == "output":
                    output = event["data"]
                elif event["type"] == "tokens":
                    tokens_used += event["data"].get("count",0)

            return AgentOutput(
                agent_id=context.agent_id,
                agent_type=context.agent_type,
                status=AgentStatus.COMPLETED,
                output=output,
                tokens_used=tokens_used,
                duration_seconds=(datetime.now() - datetime.fromisoformat(started_at)).total_seconds(),
                started_at=started_at,
                completed_at=datetime.now().isoformat(),
            )
        except Exception as e:
            return AgentOutput(
                agent_id=context.agent_id,
                agent_type=context.agent_type,
                status=AgentStatus.FAILED,
                error=str(e),
                tokens_used=tokens_used,
                started_at=started_at,
                completed_at=datetime.now().isoformat(),
            )

    async def run_agent_stream(
        self,
        context:AgentContext
    )->AsyncGenerator[Dict[str,Any],None]:
        agent_type = context.agent_type

        yield {
            "type":"log",
            "data":{
                "level":"info",
                "message":f"Mock Agent開始: {agent_type.value if hasattr(agent_type, 'value') else agent_type}",
                "timestamp":datetime.now().isoformat()
            }
        }

        yield {
            "type":"progress",
            "data":{"progress":10,"current_task":"初期化中"}
        }

        await asyncio.sleep(0.5 * self._simulation_speed)

        yield {
            "type":"progress",
            "data":{"progress":30,"current_task":"処理中"}
        }

        await asyncio.sleep(0.5 * self._simulation_speed)

        tokens = 500 + int(1500 * self._simulation_speed)
        yield {
            "type":"tokens",
            "data":{"count":tokens,"total":tokens}
        }

        yield {
            "type":"progress",
            "data":{"progress":70,"current_task":"出力生成中"}
        }

        await asyncio.sleep(0.3 * self._simulation_speed)

        output = self._generate_mock_output(context)

        yield {
            "type":"progress",
            "data":{"progress":90,"current_task":"完了処理中"}
        }

        checkpoint_data = self._generate_checkpoint(context,output)
        yield {
            "type":"checkpoint",
            "data":checkpoint_data
        }

        if context.on_checkpoint:
            context.on_checkpoint(checkpoint_data["type"],checkpoint_data)

        yield {
            "type":"progress",
            "data":{"progress":100,"current_task":"完了"}
        }

        yield {
            "type":"output",
            "data":output
        }

        yield {
            "type":"log",
            "data":{
                "level":"info",
                "message":"Mock Agent完了",
                "timestamp":datetime.now().isoformat()
            }
        }

    def _generate_mock_output(self,context:AgentContext)->Dict[str,Any]:
        agent_type = context.agent_type.value if hasattr(context.agent_type,'value') else str(context.agent_type)
        content = get_mock_content(agent_type)

        return {
            "type":"document",
            "format":"markdown",
            "content":content,
            "metadata":{
                "mock":True,
                "agent_type":agent_type,
                "generated_at":datetime.now().isoformat()
            }
        }

    def _generate_checkpoint(self,context:AgentContext,output:Dict[str,Any])->Dict[str,Any]:
        agent_type = context.agent_type.value if hasattr(context.agent_type,'value') else str(context.agent_type)
        cp_config = get_checkpoint_title_config(agent_type)
        cp_type = cp_config.get("type","review")
        title = cp_config.get("title","レビュー依頼")

        return {
            "type":cp_type,
            "title":title,
            "description":f"{agent_type}エージェントの出力を確認してください",
            "output":output,
            "timestamp":datetime.now().isoformat()
        }

    def get_supported_agents(self)->List[AgentType]:
        return list(AgentType)

    def validate_context(self,context:AgentContext)->bool:
        return True
