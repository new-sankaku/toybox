"""
Skill Enabled Agent Runner Module

スキル（ツール）実行機能を持つエージェントランナー
各サブモジュールを組み合わせてメインフローを提供
"""

import json
from datetime import datetime
from typing import Any,Dict,List,AsyncGenerator,Optional

from ..base import (
    AgentRunner,
    AgentContext,
    AgentOutput,
    AgentType,
    AgentStatus,
)
from ..api_runner import ApiAgentRunner
from skills import create_skill_executor,SkillExecutor
from middleware.logger import get_logger

from .types import (
    LoopDetector,
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_MESSAGE_WINDOW_SIZE,
    DEFAULT_MESSAGE_COMPACTION_TRIGGER,
    FINALIZING_BUDGET,
)
from .tool_call_parser import ToolCallParser
from .message_compactor import MessageCompactor
from .skill_prompt_builder import SkillPromptBuilder


class SkillEnabledAgentRunner(AgentRunner):
    def __init__(
        self,
        base_runner:ApiAgentRunner,
        working_dir:str,
        max_tool_iterations:int=DEFAULT_MAX_ITERATIONS,
        message_window_size:int=DEFAULT_MESSAGE_WINDOW_SIZE,
        message_compaction_trigger:int=DEFAULT_MESSAGE_COMPACTION_TRIGGER,
        task_limits:Optional[Dict[str,Any]]=None,
    ):
        self._base=base_runner
        self._working_dir=working_dir
        self._max_iterations=max_tool_iterations
        self._message_compaction_trigger=message_compaction_trigger
        tl=task_limits or {}
        self._tool_result_max=tl.get("tool_result_max_length",5000)
        self._prev_output_max=tl.get("previous_output_max_length",2000)
        self._skill_log_max=tl.get("skill_log_output_max",500)
        self._compact_assistant_max=tl.get("compaction_assistant_max",300)
        self._compact_system_max=tl.get("compaction_system_max",200)
        self._compact_user_max=tl.get("compaction_user_max",200)
        self._skill_executor:Optional[SkillExecutor]=None

        self._tool_call_parser=ToolCallParser(tool_result_max=self._tool_result_max)
        self._message_compactor=MessageCompactor(
            message_window_size=message_window_size,
            compact_assistant_max=self._compact_assistant_max,
            compact_system_max=self._compact_system_max,
            compact_user_max=self._compact_user_max,
        )
        self._prompt_builder=SkillPromptBuilder(prev_output_max=self._prev_output_max)

    def _get_executor(self,context:AgentContext)->SkillExecutor:
        if self._skill_executor is None:
            agent_type=(
                context.agent_type.value
                if hasattr(context.agent_type,"value")
                else str(context.agent_type)
            )
            self._skill_executor=create_skill_executor(
                project_id=context.project_id,
                agent_id=context.agent_id,
                agent_type=agent_type,
                working_dir=self._working_dir,
                on_progress=context.on_progress,
            )
        return self._skill_executor

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
                elif event["type"]=="progress":
                    d=event["data"]
                    if context.on_progress:
                        context.on_progress(d.get("progress",0),d.get("current_task",""))
                elif event["type"]=="log":
                    d=event["data"]
                    if context.on_log:
                        context.on_log(d.get("level","info"),d.get("message",""))
                elif event["type"]=="skill_call":
                    d=event["data"]
                    if context.on_log:
                        context.on_log("info",f"スキル実行開始: {d['skill']}")
                elif event["type"]=="skill_result":
                    d=event["data"]
                    if context.on_log:
                        if d.get("success"):
                            context.on_log("info",f"スキル成功: {d['skill']}")
                        else:
                            err=d.get("error") or d.get("output","")
                            context.on_log("error",f"スキル失敗: {d['skill']} - {err}")
                elif event["type"]=="checkpoint":
                    if context.on_checkpoint:
                        d=event["data"]
                        context.on_checkpoint(d.get("type","review"),d)
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
        self,context:AgentContext
    )->AsyncGenerator[Dict[str,Any],None]:
        executor=self._get_executor(context)
        available_skills=executor.get_available_skills()
        trace_service=self._base.get_trace_service()
        trace_id=None
        if trace_service:
            try:
                trace=trace_service.create_trace(
                    project_id=context.project_id,
                    agent_id=context.agent_id,
                    agent_type=context.agent_type.value,
                    input_context={
                        "project_concept":context.project_concept,
                        "config":context.config,
                    },
                    model_used=self._base.model,
                )
                trace_id=trace.get("id")
            except Exception as e:
                get_logger().error(
                    f"SkillRunner: failed to create trace: {e}",exc_info=True
                )
        yield {
            "type":"log",
            "data":{
                "level":"info",
                "message":f"Skill-enabled Agent開始: {context.agent_type.value}, 利用可能スキル: {len(available_skills)}",
                "timestamp":datetime.now().isoformat(),
            },
        }
        skill_schemas=executor.get_skill_schemas_for_llm()
        use_native_tools=self._check_native_tools_support()
        if use_native_tools:
            get_logger().info(
                f"SkillRunner: native tool calling enabled for model={self._base.model}"
            )
        enhanced_context=self._enhance_context_with_skills(context,skill_schemas)
        system_prompt=self._prompt_builder.build_system_prompt(
            enhanced_context,skill_schemas,use_native_tools=use_native_tools
        )
        user_prompt=self._prompt_builder.build_user_prompt(enhanced_context)
        if trace_service and trace_id:
            try:
                trace_service.update_trace_prompt(
                    trace_id,f"[SYSTEM]\n{system_prompt}\n\n[USER]\n{user_prompt}"
                )
            except Exception as e:
                get_logger().error(
                    f"SkillRunner: failed to update trace prompt: {e}",exc_info=True
                )
        messages=[{"role":"user","content":user_prompt}]
        iteration=0
        total_tokens=0
        final_output=None
        last_response_content=""
        loop_detector=LoopDetector()
        stop_reason=None
        adv_settings=(
            context.config.get("advancedSettings",{}) if context.config else {}
        )
        tool_exec=adv_settings.get("toolExecution",{})
        max_iter=tool_exec.get("max_iterations",self._max_iterations)
        try:
            while iteration<max_iter:
                iteration+=1
                remaining=max_iter-iteration
                progress=min(85,10+int((iteration/max_iter)*75))
                yield {
                    "type":"progress",
                    "data":{
                        "progress":progress,
                        "current_task":f"LLM呼び出し中 (iteration {iteration}/{max_iter})",
                    },
                }
                if remaining<=FINALIZING_BUDGET and iteration>1:
                    messages.append(
                        {
                            "role":"user",
                            "content":self._prompt_builder.build_finalize_prompt(remaining),
                        }
                    )
                elif iteration>1 and iteration%10==0:
                    messages.append(
                        {
                            "role":"user",
                            "content":self._prompt_builder.build_progress_check_prompt(
                                iteration,remaining
                            ),
                        }
                    )
                if len(messages)>self._message_compaction_trigger:
                    messages=self._message_compactor.compact_messages(messages)
                response=await self._call_llm_with_tools(
                    messages,
                    skill_schemas,
                    context,
                    system_prompt=system_prompt,
                    use_native_tools=use_native_tools,
                )
                tokens_used=response.get("tokens_used",0)
                total_tokens+=tokens_used
                yield {"type":"tokens","data":{"count":tokens_used}}
                last_response_content=response.get("content","")
                native_tc=response.get("native_tool_calls")
                tool_calls=self._tool_call_parser.extract_tool_calls(
                    last_response_content,native_tool_calls=native_tc
                )
                if not tool_calls:
                    final_output=self._process_final_response(response,context)
                    break
                yield {
                    "type":"log",
                    "data":{
                        "level":"info",
                        "message":f"ツール呼び出し: {[tc.name for tc in tool_calls]}",
                        "timestamp":datetime.now().isoformat(),
                    },
                }
                loop_detector.record([tc.name for tc in tool_calls])
                if loop_detector.is_looping():
                    loop_info=loop_detector.get_loop_info()
                    stop_reason=f"ループ検出: {loop_info}"
                    yield {
                        "type":"log",
                        "data":{
                            "level":"warning",
                            "message":f"無限ループを検出しました。成果をまとめます。({loop_info})",
                            "timestamp":datetime.now().isoformat(),
                        },
                    }
                    break
                if native_tc:
                    tc_msg_data=[
                        {
                            "id":tc.id,
                            "name":tc.name,
                            "arguments":json.dumps(tc.input,ensure_ascii=False),
                        }
                        for tc in tool_calls
                    ]
                    messages.append(
                        {
                            "role":"assistant",
                            "content":last_response_content or"",
                            "tool_calls":tc_msg_data,
                        }
                    )
                else:
                    messages.append({"role":"assistant","content":last_response_content})
                tool_results=[]
                for tc in tool_calls:
                    yield {
                        "type":"skill_call",
                        "data":{"skill":tc.name,"params":tc.input},
                    }
                    result=await executor.execute_skill(tc.name,**tc.input)
                    yield {
                        "type":"skill_result",
                        "data":{
                            "skill":tc.name,
                            "success":result.success,
                            "output":str(result.output)[:self._skill_log_max],
                            "error":result.error,
                        },
                    }
                    if native_tc:
                        tool_results.append(
                            self._tool_call_parser.format_tool_result_native(tc,result)
                        )
                    else:
                        tool_results.append(
                            self._tool_call_parser.format_tool_result(tc,result)
                        )
                if native_tc:
                    for tr in tool_results:
                        messages.append(tr)
                else:
                    messages.append({"role":"user","content":"\n\n".join(tool_results)})
            if final_output is None:
                if stop_reason is None:
                    stop_reason=f"最大イテレーション数({max_iter})に到達"
                final_output=await self._generate_summary_output(
                    messages,
                    skill_schemas,
                    context,
                    stop_reason,
                    system_prompt=system_prompt,
                    use_native_tools=use_native_tools,
                )
                total_tokens+=final_output.get("metadata",{}).get("summary_tokens",0)
            if trace_service and trace_id:
                try:
                    input_tokens=int(total_tokens*0.3)
                    output_tokens=total_tokens-input_tokens
                    trace_service.complete_trace(
                        trace_id=trace_id,
                        llm_response=last_response_content,
                        output_data=final_output,
                        tokens_input=input_tokens,
                        tokens_output=output_tokens,
                        status="completed",
                    )
                except Exception as e:
                    get_logger().error(
                        f"SkillRunner: failed to complete trace: {e}",exc_info=True
                    )
        except Exception as e:
            if trace_service and trace_id:
                try:
                    trace_service.fail_trace(trace_id,str(e))
                except Exception as te:
                    get_logger().error(
                        f"SkillRunner: failed to record trace failure: {te}",
                        exc_info=True,
                    )
            raise
        yield {"type":"progress","data":{"progress":90,"current_task":"完了処理中"}}
        yield {
            "type":"checkpoint",
            "data":{
                "type":"review",
                "title":f"{context.agent_type.value} 成果物レビュー",
                "output":final_output,
                "skill_history":executor.get_execution_history(),
            },
        }
        yield {"type":"progress","data":{"progress":100,"current_task":"完了"}}
        yield {"type":"output","data":final_output}

    async def _generate_summary_output(
        self,
        messages:List[Dict],
        skill_schemas:List[Dict],
        context:AgentContext,
        stop_reason:str,
        system_prompt:Optional[str]=None,
        use_native_tools:bool=False,
    )->Dict[str,Any]:
        summary_prompt=self._prompt_builder.build_summary_prompt(stop_reason)
        messages_copy=list(messages)
        messages_copy.append({"role":"user","content":summary_prompt})
        try:
            response=await self._call_llm_with_tools(
                messages_copy,skill_schemas,context,system_prompt=system_prompt
            )
            output=self._process_final_response(response,context)
            output["metadata"]["stop_reason"]=stop_reason
            output["metadata"]["summary_tokens"]=response.get("tokens_used",0)
            return output
        except Exception as e:
            last_content=""
            for msg in reversed(messages):
                if msg.get("role")=="assistant" and msg.get("content"):
                    last_content=msg["content"]
                    break
            return {
                "type":"document",
                "format":"markdown",
                "content":last_content
                or f"作業は{stop_reason}により中断されました。まとめ生成にも失敗しました: {e}",
                "metadata":{
                    "agent_type":context.agent_type.value,
                    "stop_reason":stop_reason,
                    "summary_error":str(e),
                },
            }

    def _check_native_tools_support(self)->bool:
        try:
            from providers.registry import get_provider
            from providers.base import AIProviderConfig

            provider=get_provider(self._base._provider_id,AIProviderConfig())
            if not provider:
                return False
            models=provider.get_available_models()
            for m in models:
                if m.id==self._base.model:
                    return m.supports_tools
        except Exception:
            pass
        return False

    def _enhance_context_with_skills(
        self,context:AgentContext,skill_schemas:List[Dict]
    )->AgentContext:
        enhanced_config=dict(context.config)
        enhanced_config["available_skills"]=[s["name"] for s in skill_schemas]
        return AgentContext(
            project_id=context.project_id,
            agent_id=context.agent_id,
            agent_type=context.agent_type,
            project_concept=context.project_concept,
            previous_outputs=context.previous_outputs,
            config=enhanced_config,
            quality_check=context.quality_check,
            assigned_task=context.assigned_task,
            leader_analysis=context.leader_analysis,
            on_progress=context.on_progress,
            on_log=context.on_log,
            on_checkpoint=context.on_checkpoint,
            on_speech=context.on_speech,
        )

    async def _call_llm_with_tools(
        self,
        messages:List[Dict],
        skill_schemas:List[Dict],
        context:AgentContext,
        system_prompt:Optional[str]=None,
        use_native_tools:bool=False,
    )->Dict[str,Any]:
        from config_loaders.agent_config import get_agent_temperature

        temperature=get_agent_temperature(context.agent_type.value)
        messages_json_str=json.dumps(messages,ensure_ascii=False)
        prompt_fallback=messages[-1].get("content","") if messages else""
        tools_json_str=None
        if use_native_tools and skill_schemas:
            openai_tools=self._tool_call_parser.convert_to_openai_tools(skill_schemas)
            tools_json_str=json.dumps(openai_tools,ensure_ascii=False)
        job_queue=self._base.get_job_queue()
        job=job_queue.submit_job(
            project_id=context.project_id,
            agent_id=context.agent_id,
            provider_id=self._base._provider_id,
            model=self._base.model,
            prompt=prompt_fallback,
            max_tokens=self._base.max_tokens,
            system_prompt=system_prompt,
            temperature=str(temperature),
            messages_json=messages_json_str,
            on_speech=context.on_speech,
            tools_json=tools_json_str,
        )
        result=await job_queue.wait_for_job_async(job["id"],timeout=300.0)
        if not result:
            raise TimeoutError(f"LLMジョブがタイムアウトしました: {job['id']}")
        if result["status"]=="failed":
            raise RuntimeError(
                f"LLMジョブ失敗: {result.get('errorMessage', 'Unknown error')}"
            )
        response_content=result["responseContent"]
        native_tool_calls=None
        try:
            parsed=json.loads(response_content)
            if isinstance(parsed,dict) and"tool_calls" in parsed:
                native_tool_calls=parsed["tool_calls"]
                response_content=parsed.get("content","")
        except (json.JSONDecodeError,TypeError):
            pass
        return {
            "content":response_content,
            "tokens_used":result["tokensInput"]+result["tokensOutput"],
            "native_tool_calls":native_tool_calls,
        }

    def _process_final_response(
        self,response:Dict[str,Any],context:AgentContext
    )->Dict[str,Any]:
        return {
            "type":"document",
            "format":"markdown",
            "content":response.get("content",""),
            "metadata":{
                "agent_type":context.agent_type.value,
                "tokens_used":response.get("tokens_used",0),
            },
        }

    def get_supported_agents(self)->List[AgentType]:
        return self._base.get_supported_agents()

    def validate_context(self,context:AgentContext)->bool:
        return self._base.validate_context(context)
