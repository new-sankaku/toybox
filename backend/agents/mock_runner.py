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
from config_loader import get_mock_content,get_checkpoint_title_config,get_provider_default_model
from middleware.logger import get_logger


class MockAgentRunner(AgentRunner):

    def __init__(self,data_store=None,**kwargs):
        self._data_store=data_store
        self._simulation_speed=kwargs.get("simulation_speed",1.0)

    async def run_agent(self,context:AgentContext)->AgentOutput:
        started_at=datetime.now().isoformat()
        tokens_used=0
        output={}

        try:
            async for event in self.run_agent_stream(context):
                if event["type"]=="output":
                    output=event["data"]
                elif event["type"]=="tokens":
                    tokens_used+=event["data"].get("count",0)

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
        agent_type=context.agent_type
        agent_type_str=agent_type.value if hasattr(agent_type,'value') else str(agent_type)
        trace_id=None
        start_time=datetime.now()

        if self._data_store:
            try:
                model=get_provider_default_model("anthropic")
                trace=self._data_store.create_trace(
                    project_id=context.project_id,
                    agent_id=context.agent_id,
                    agent_type=agent_type_str,
                    input_context={"mock":True},
                    model_used=f"{model} (simulation)"
                )
                trace_id=trace.get("id")
            except Exception as e:
                get_logger().error(f"MockAgentRunner: failed to create trace: {e}",exc_info=True)

        yield {
            "type":"log",
            "data":{
                "level":"info",
                "message":f"Mock Agent開始: {agent_type_str}",
                "timestamp":datetime.now().isoformat()
            }
        }

        yield {
            "type":"progress",
            "data":{"progress":10,"current_task":"初期化中"}
        }

        await asyncio.sleep(0.25*self._simulation_speed)

        yield {
            "type":"progress",
            "data":{"progress":30,"current_task":"処理中"}
        }

        await asyncio.sleep(0.25*self._simulation_speed)

        tokens=500+int(1500*self._simulation_speed)
        input_tokens=int(tokens*0.3)
        output_tokens=tokens-input_tokens
        yield {
            "type":"tokens",
            "data":{"count":tokens,"total":tokens}
        }

        yield {
            "type":"progress",
            "data":{"progress":70,"current_task":"出力生成中"}
        }

        await asyncio.sleep(0.15*self._simulation_speed)

        output=self._generate_mock_output(context)
        content=output.get("content","")
        summary=content[:100] if content else f"{agent_type_str}のモック出力"

        if self._data_store and trace_id:
            try:
                duration_ms=int((datetime.now()-start_time).total_seconds()*1000)
                self._data_store.complete_trace(
                    trace_id=trace_id,
                    llm_response=content[:500] if content else "",
                    output_data=output,
                    tokens_input=input_tokens,
                    tokens_output=output_tokens,
                    status="completed",
                    output_summary=summary
                )
            except Exception as e:
                get_logger().error(f"MockAgentRunner: failed to complete trace: {e}",exc_info=True)

        yield {
            "type":"progress",
            "data":{"progress":90,"current_task":"完了処理中"}
        }

        checkpoint_data=self._generate_checkpoint(context,output)
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
        agent_type=context.agent_type.value if hasattr(context.agent_type,'value') else str(context.agent_type)
        content=get_mock_content(agent_type)

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
        agent_type=context.agent_type.value if hasattr(context.agent_type,'value') else str(context.agent_type)
        cp_config=get_checkpoint_title_config(agent_type)
        cp_type=cp_config.get("type","review")
        title=cp_config.get("title","レビュー依頼")

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
