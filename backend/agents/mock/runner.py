from datetime import datetime
from typing import Any,Dict,AsyncGenerator
import asyncio

from .base import MockRunnerBase
from ..base import AgentContext
from config_loaders.mock_config import get_mock_content
from config_loaders.ai_provider_config import get_provider_default_model
from middleware.logger import get_logger


class MockAgentRunner(MockRunnerBase):

    async def run_agent_stream(
        self,
        context:AgentContext
    )->AsyncGenerator[Dict[str,Any],None]:
        agent_type_str=self._get_agent_type_str(context)
        trace_id=None
        start_time=datetime.now()

        trace_id=self._create_trace(context,agent_type_str)

        yield self._log_event("info",f"Mock Agent開始: {agent_type_str}")
        yield self._progress_event(10,"初期化中")
        await asyncio.sleep(0.25*self._simulation_speed)

        yield self._progress_event(30,"処理中")
        await asyncio.sleep(0.25*self._simulation_speed)

        tokens=500+int(1500*self._simulation_speed)
        input_tokens=int(tokens*0.3)
        output_tokens=tokens-input_tokens
        yield {"type":"tokens","data":{"count":tokens,"total":tokens}}

        yield self._progress_event(70,"出力生成中")
        await asyncio.sleep(0.15*self._simulation_speed)

        output=self._generate_mock_output(context)
        content=output.get("content","")

        self._complete_trace(trace_id,content,output,input_tokens,output_tokens,start_time)

        yield self._progress_event(90,"完了処理中")

        checkpoint_data=self._generate_checkpoint_data(context,output)
        yield {"type":"checkpoint","data":checkpoint_data}
        self._emit_checkpoint_callback(context,checkpoint_data)

        yield self._progress_event(100,"完了")
        yield {"type":"output","data":output}
        yield self._log_event("info","Mock Agent完了")

    def _create_trace(self,context:AgentContext,agent_type_str:str)->str|None:
        if not self._trace_service:
            return None
        try:
            model=get_provider_default_model("anthropic")
            trace=self._trace_service.create_trace(
                project_id=context.project_id,
                agent_id=context.agent_id,
                agent_type=agent_type_str,
                input_context={"mock":True},
                model_used=f"{model} (simulation)"
            )
            return trace.get("id")
        except Exception as e:
            get_logger().error(f"MockAgentRunner: failed to create trace: {e}",exc_info=True)
            return None

    def _complete_trace(
        self,
        trace_id:str|None,
        content:str,
        output:Dict[str,Any],
        input_tokens:int,
        output_tokens:int,
        start_time:datetime,
    )->None:
        if not self._trace_service or not trace_id:
            return
        try:
            summary=content[:100] if content else"モック出力"
            self._trace_service.complete_trace(
                trace_id=trace_id,
                llm_response=content[:500] if content else"",
                output_data=output,
                tokens_input=input_tokens,
                tokens_output=output_tokens,
                status="completed",
                output_summary=summary
            )
        except Exception as e:
            get_logger().error(f"MockAgentRunner: failed to complete trace: {e}",exc_info=True)

    def _generate_mock_output(self,context:AgentContext)->Dict[str,Any]:
        agent_type=self._get_agent_type_str(context)
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
