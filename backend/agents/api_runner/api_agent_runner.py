"""
API Agent Runner Module

実際のLLM APIを呼び出してエージェントを実行するランナー
各サブモジュールを組み合わせてメインフローを提供
"""

import asyncio
import os
from datetime import datetime
from typing import Any,Callable,Dict,List,AsyncGenerator,Optional

from ..base import (
    AgentRunner,
    AgentContext,
    AgentOutput,
    AgentType,
    AgentStatus,
)
from ..retry_strategy import RetryConfig
from ..exceptions import ProviderUnavailableError,MaxRetriesExceededError
from .context_filter import ContextFilter
from .prompt_builder import PromptBuilder
from .output_processor import OutputProcessor
from .llm_caller import LLMCaller

from config_loaders.ai_provider_config import get_provider_default_model,get_provider_env_key
from providers.registry import get_provider,register_all_providers
from providers.base import AIProviderConfig
from middleware.logger import get_logger


class ApiAgentRunner(AgentRunner):
    _job_queue=None

    @classmethod
    def set_job_queue(cls,job_queue)->None:
        cls._job_queue=job_queue

    @classmethod
    def get_job_queue(cls):
        if cls._job_queue is None:
            from services.llm_job_queue import get_llm_job_queue

            cls._job_queue=get_llm_job_queue()
        return cls._job_queue

    def __init__(
        self,
        provider_id:Optional[str]=None,
        api_key:Optional[str]=None,
        model:Optional[str]=None,
        max_tokens:int=32768,
        retry_config:Optional[RetryConfig]=None,
        **kwargs,
    ):
        self._provider_id=provider_id or""
        self.api_key=api_key or (
            os.environ.get(self._env_key_for(provider_id)) if provider_id else None
        )
        self.model=(
            model or (get_provider_default_model(provider_id) if provider_id else"") or""
        )
        self.max_tokens=max_tokens
        self._provider=None
        self._graphs:Dict[AgentType,Any]={}
        self._retry_config=retry_config or RetryConfig(max_retries=3)
        self._health_monitor=None
        self._on_status_change:Optional[Callable[[str,AgentStatus],None]]=None
        self._trace_service=None
        self._agent_service=None
        register_all_providers()

        self._llm_caller=LLMCaller(
            provider_id=self._provider_id,
            model=self.model,
            max_tokens=max_tokens,
            get_job_queue_func=self.get_job_queue,
        )
        self._context_filter=ContextFilter(self._llm_caller.get_project_context_policy)
        self._prompt_builder=PromptBuilder(
            context_filter=self._context_filter,
            get_agent_service_func=self.get_agent_service,
            get_project_context_policy_func=self._llm_caller.get_project_context_policy,
        )
        self._output_processor=OutputProcessor()

    @staticmethod
    def _env_key_for(provider_id:str)->str:
        return get_provider_env_key(provider_id)

    def set_services(self,trace_service,agent_service)->None:
        self._trace_service=trace_service
        self._agent_service=agent_service

    def set_health_monitor(self,monitor)->None:
        self._health_monitor=monitor

    def set_status_callback(
        self,callback:Callable[[str,AgentStatus],None]
    )->None:
        self._on_status_change=callback

    def get_trace_service(self):
        return self._trace_service

    def get_agent_service(self):
        return self._agent_service

    def _check_provider_health(self)->bool:
        if not self._health_monitor:
            return True
        health=self._health_monitor.get_health_status(self._provider_id)
        if health and not health.available:
            return False
        return True

    def _emit_status(self,agent_id:str,status:AgentStatus)->None:
        if self._on_status_change:
            self._on_status_change(agent_id,status)

    def _get_provider(self):
        if self._provider is None:
            config=AIProviderConfig(api_key=self.api_key,timeout=120)
            self._provider=get_provider(self._provider_id,config)
            if self._provider is None:
                raise ValueError(f"Unknown provider: {self._provider_id}")
        return self._provider

    async def run_agent(self,context:AgentContext)->AgentOutput:
        started_at=datetime.now().isoformat()
        tokens_used=0
        output={}

        if not self._check_provider_health():
            self._emit_status(context.agent_id,AgentStatus.WAITING_PROVIDER)
            await self._wait_for_provider_recovery()

        self._emit_status(context.agent_id,AgentStatus.RUNNING)

        try:
            async for event in self.run_agent_stream(context):
                if event["type"]=="output":
                    output=event["data"]
                elif event["type"]=="tokens":
                    tokens_used+=event["data"].get("count",0)
                elif event["type"]=="progress":
                    d=event["data"]
                    if context.on_progress:
                        context.on_progress(d.get("progress",0),d.get("current_task",""))
                elif event["type"]=="log":
                    d=event["data"]
                    if context.on_log:
                        context.on_log(d.get("level","info"),d.get("message",""))

            return AgentOutput(
                agent_id=context.agent_id,
                agent_type=context.agent_type,
                status=AgentStatus.COMPLETED,
                output=output,
                tokens_used=tokens_used,
                duration_seconds=(
                    datetime.now()-datetime.fromisoformat(started_at)
                ).total_seconds(),
                started_at=started_at,
                completed_at=datetime.now().isoformat(),
            )

        except MaxRetriesExceededError as e:
            return AgentOutput(
                agent_id=context.agent_id,
                agent_type=context.agent_type,
                status=AgentStatus.FAILED,
                error=f"最大リトライ回数超過: {str(e)}",
                tokens_used=tokens_used,
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

    async def _wait_for_provider_recovery(self,max_wait:float=300)->None:
        import time

        start=time.time()
        while time.time()-start<max_wait:
            if self._check_provider_health():
                return
            await asyncio.sleep(5)
        raise ProviderUnavailableError(
            self._provider_id,"プロバイダー復旧待機タイムアウト"
        )

    async def run_agent_stream(
        self,context:AgentContext
    )->AsyncGenerator[Dict[str,Any],None]:
        agent_type=context.agent_type
        trace_id=None

        if self._trace_service:
            try:
                input_ctx={
                    "project_concept":context.project_concept,
                    "config":context.config,
                }
                trace=self._trace_service.create_trace(
                    project_id=context.project_id,
                    agent_id=context.agent_id,
                    agent_type=agent_type.value,
                    input_context=input_ctx,
                    model_used=self.resolve_model_for_agent(context),
                )
                trace_id=trace.get("id")
            except Exception as e:
                get_logger().error(
                    f"ApiAgentRunner: failed to create trace: {e}",exc_info=True
                )

        yield {
            "type":"log",
            "data":{
                "level":"info",
                "message":f"API Agent開始: {agent_type.value}",
                "timestamp":datetime.now().isoformat(),
            },
        }

        yield {
            "type":"progress",
            "data":{"progress":10,"current_task":"プロンプト準備中"},
        }

        system_prompt,user_prompt=self._prompt_builder.build_prompt(context)

        if self._trace_service and trace_id:
            try:
                trace_prompt=(
                    f"[SYSTEM]\n{system_prompt}\n\n[USER]\n{user_prompt}"
                    if system_prompt
                    else user_prompt
                )
                self._trace_service.update_trace_prompt(trace_id,trace_prompt)
            except Exception as e:
                get_logger().error(
                    f"ApiAgentRunner: failed to update trace prompt: {e}",exc_info=True
                )

        yield {
            "type":"progress",
            "data":{"progress":20,"current_task":"LLM呼び出し中"},
        }

        try:
            result=await self._llm_caller.call_llm(
                user_prompt,context,system_prompt=system_prompt
            )

            yield {
                "type":"tokens",
                "data":{
                    "count":result.get("tokens_used",0),
                    "total":result.get("tokens_used",0),
                },
            }

            yield {
                "type":"progress",
                "data":{"progress":80,"current_task":"出力処理中"},
            }

            output=self._output_processor.process_output(result,context)

            if self._trace_service and trace_id:
                try:
                    input_tokens=result.get("input_tokens",0)
                    output_tokens=result.get("output_tokens",0)
                    if input_tokens==0 and output_tokens==0:
                        total=result.get("tokens_used",0)
                        input_tokens=int(total*0.3)
                        output_tokens=total-input_tokens
                    llm_content=result.get("content","")
                    from services.summary_service import get_summary_service

                    summary=get_summary_service().generate_summary(
                        llm_content,
                        agent_type.value,
                        fallback_func=self._context_filter.extract_summary,
                        project_id=context.project_id,
                    )
                    self._trace_service.complete_trace(
                        trace_id=trace_id,
                        llm_response=llm_content,
                        output_data=output,
                        tokens_input=input_tokens,
                        tokens_output=output_tokens,
                        status="completed",
                        output_summary=summary,
                    )
                except Exception as e:
                    get_logger().error(
                        f"ApiAgentRunner: failed to complete trace: {e}",exc_info=True
                    )

            yield {
                "type":"progress",
                "data":{"progress":90,"current_task":"承認準備"},
            }

            checkpoint_data=self._output_processor.generate_checkpoint(context,output)
            yield {"type":"checkpoint","data":checkpoint_data}

            if context.on_checkpoint:
                context.on_checkpoint(checkpoint_data["type"],checkpoint_data)

            yield {
                "type":"progress",
                "data":{"progress":100,"current_task":"完了"},
            }

            yield {"type":"output","data":output}

        except Exception as e:
            if self._trace_service and trace_id:
                try:
                    self._trace_service.fail_trace(trace_id,str(e))
                except Exception as te:
                    get_logger().error(
                        f"ApiAgentRunner: failed to record trace failure: {te}",
                        exc_info=True,
                    )

            yield {
                "type":"log",
                "data":{
                    "level":"error",
                    "message":f"LLM呼び出しエラー: {str(e)}",
                    "timestamp":datetime.now().isoformat(),
                },
            }
            yield {"type":"error","data":{"message":str(e)}}
            raise

        yield {
            "type":"log",
            "data":{
                "level":"info",
                "message":"API Agent完了",
                "timestamp":datetime.now().isoformat(),
            },
        }

    def resolve_model_for_agent(self,context:AgentContext)->str:
        return self._llm_caller.resolve_model_for_agent(context)

    def resolve_provider_for_agent(self,context:AgentContext)->str:
        return self._llm_caller.resolve_provider_for_agent(context)

    def get_project_temperature(self,context:AgentContext,agent_type:str)->float:
        return self._llm_caller.get_project_temperature(context,agent_type)

    def get_project_dag_enabled(self,context:AgentContext)->bool:
        return self._llm_caller.get_project_dag_enabled(context)

    def get_project_token_budget(
        self,context:Optional[AgentContext]
    )->Optional[Dict[str,Any]]:
        return self._llm_caller.get_project_token_budget(context)

    _resolve_model_for_agent=resolve_model_for_agent
    _resolve_provider_for_agent=resolve_provider_for_agent
    _get_project_temperature=get_project_temperature
    _get_project_dag_enabled=get_project_dag_enabled
    _get_project_token_budget=get_project_token_budget

    def get_supported_agents(self)->List[AgentType]:
        return [
            AgentType.CONCEPT_LEADER,
            AgentType.DESIGN_LEADER,
            AgentType.SCENARIO_LEADER,
            AgentType.CHARACTER_LEADER,
            AgentType.WORLD_LEADER,
            AgentType.TASK_SPLIT_LEADER,
            AgentType.RESEARCH_WORKER,
            AgentType.IDEATION_WORKER,
            AgentType.CONCEPT_VALIDATION_WORKER,
            AgentType.ARCHITECTURE_WORKER,
            AgentType.COMPONENT_WORKER,
            AgentType.DATAFLOW_WORKER,
            AgentType.STORY_WORKER,
            AgentType.DIALOG_WORKER,
            AgentType.EVENT_WORKER,
            AgentType.MAIN_CHARACTER_WORKER,
            AgentType.NPC_WORKER,
            AgentType.RELATIONSHIP_WORKER,
            AgentType.GEOGRAPHY_WORKER,
            AgentType.LORE_WORKER,
            AgentType.SYSTEM_WORKER,
            AgentType.ANALYSIS_WORKER,
            AgentType.DECOMPOSITION_WORKER,
            AgentType.SCHEDULE_WORKER,
            AgentType.CODE_LEADER,
            AgentType.ASSET_LEADER,
            AgentType.CODE_WORKER,
            AgentType.ASSET_WORKER,
            AgentType.INTEGRATOR_LEADER,
            AgentType.TESTER_LEADER,
            AgentType.REVIEWER_LEADER,
            AgentType.DEPENDENCY_WORKER,
            AgentType.BUILD_WORKER,
            AgentType.INTEGRATION_VALIDATION_WORKER,
            AgentType.UNIT_TEST_WORKER,
            AgentType.INTEGRATION_TEST_WORKER,
            AgentType.E2E_TEST_WORKER,
            AgentType.PERFORMANCE_TEST_WORKER,
            AgentType.CODE_REVIEW_WORKER,
            AgentType.ASSET_REVIEW_WORKER,
            AgentType.GAMEPLAY_REVIEW_WORKER,
            AgentType.COMPLIANCE_WORKER,
        ]

    def validate_context(self,context:AgentContext)->bool:
        if not self.api_key:
            return False
        if context.agent_type not in self.get_supported_agents():
            return False
        return True
