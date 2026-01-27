import asyncio
from datetime import datetime
from typing import Any,Dict,List,AsyncGenerator,Optional,Callable
import os
from dataclasses import dataclass,field

from .base import (
    AgentRunner,
    AgentContext,
    AgentOutput,
    AgentType,
    AgentStatus,
)
from .retry_strategy import RetryConfig,retry_with_backoff,is_retryable_error
from .exceptions import ProviderUnavailableError,MaxRetriesExceededError
from config_loader import (
    get_all_prompts,
    get_api_runner_checkpoint_config,
    get_provider_default_model,
    get_agent_max_tokens,
    get_workflow_context_policy,
)
from providers.registry import get_provider,register_all_providers
from providers.base import AIProviderConfig


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
        provider_id:str="anthropic",
        api_key:Optional[str]=None,
        model:Optional[str]=None,
        max_tokens:int=16384,
        retry_config:Optional[RetryConfig]=None,
        data_store=None,
        **kwargs
    ):
        self._provider_id=provider_id
        env_key_map={
            "anthropic":"ANTHROPIC_API_KEY",
            "openai":"OPENAI_API_KEY",
            "google":"GOOGLE_API_KEY",
            "xai":"XAI_API_KEY",
            "zhipu":"ZHIPU_API_KEY",
            "deepseek":"DEEPSEEK_API_KEY",
        }
        self.api_key=api_key or os.environ.get(env_key_map.get(provider_id,"ANTHROPIC_API_KEY"))
        self.model=model or get_provider_default_model(provider_id) or"claude-sonnet-4-20250514"
        self.max_tokens=max_tokens
        self._provider=None
        self._graphs:Dict[AgentType,Any]={}
        self._prompts=self._load_prompts()
        self._retry_config=retry_config or RetryConfig(max_retries=3)
        self._health_monitor=None
        self._on_status_change:Optional[Callable[[str,AgentStatus],None]]=None
        self._data_store=data_store
        register_all_providers()

    def set_data_store(self,data_store)->None:
        self._data_store=data_store

    def set_health_monitor(self,monitor)->None:
        self._health_monitor=monitor

    def set_status_callback(self,callback:Callable[[str,AgentStatus],None])->None:
        self._on_status_change=callback

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
        raise ProviderUnavailableError(self._provider_id,"プロバイダー復旧待機タイムアウト")

    async def run_agent_stream(
        self,
        context:AgentContext
    )->AsyncGenerator[Dict[str,Any],None]:
        agent_type=context.agent_type
        trace_id=None

        if self._data_store:
            try:
                input_ctx={
                    "project_concept":context.project_concept,
                    "config":context.config,
                }
                trace=self._data_store.create_trace(
                    project_id=context.project_id,
                    agent_id=context.agent_id,
                    agent_type=agent_type.value,
                    input_context=input_ctx,
                    model_used=self.model
                )
                trace_id=trace.get("id")
            except Exception as e:
                print(f"[ApiAgentRunner] Failed to create trace: {e}")

        yield {
            "type":"log",
            "data":{
                "level":"info",
                "message":f"API Agent開始: {agent_type.value}",
                "timestamp":datetime.now().isoformat()
            }
        }

        yield {
            "type":"progress",
            "data":{"progress":10,"current_task":"プロンプト準備中"}
        }

        system_prompt,user_prompt=self._build_prompt(context)

        if self._data_store and trace_id:
            try:
                trace_prompt=f"[SYSTEM]\n{system_prompt}\n\n[USER]\n{user_prompt}" if system_prompt else user_prompt
                self._data_store.update_trace_prompt(trace_id,trace_prompt)
            except Exception as e:
                print(f"[ApiAgentRunner] Failed to update trace prompt: {e}")

        yield {
            "type":"progress",
            "data":{"progress":20,"current_task":"LLM呼び出し中"}
        }

        try:
            result=await self._call_llm(user_prompt,context,system_prompt=system_prompt)

            yield {
                "type":"tokens",
                "data":{
                    "count":result.get("tokens_used",0),
                    "total":result.get("tokens_used",0)
                }
            }

            yield {
                "type":"progress",
                "data":{"progress":80,"current_task":"出力処理中"}
            }

            output=self._process_output(result,context)

            if self._data_store and trace_id:
                try:
                    input_tokens=result.get("input_tokens",0)
                    output_tokens=result.get("output_tokens",0)
                    if input_tokens==0 and output_tokens==0:
                        total=result.get("tokens_used",0)
                        input_tokens=int(total*0.3)
                        output_tokens=total-input_tokens
                    llm_content=result.get("content","")
                    summary=self._extract_summary(llm_content)
                    self._data_store.complete_trace(
                        trace_id=trace_id,
                        llm_response=llm_content,
                        output_data=output,
                        tokens_input=input_tokens,
                        tokens_output=output_tokens,
                        status="completed",
                        output_summary=summary,
                    )
                except Exception as e:
                    print(f"[ApiAgentRunner] Failed to complete trace: {e}")

            yield {
                "type":"progress",
                "data":{"progress":90,"current_task":"承認準備"}
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

        except Exception as e:
            if self._data_store and trace_id:
                try:
                    self._data_store.fail_trace(trace_id,str(e))
                except Exception as te:
                    print(f"[ApiAgentRunner] Failed to fail trace: {te}")

            yield {
                "type":"log",
                "data":{
                    "level":"error",
                    "message":f"LLM呼び出しエラー: {str(e)}",
                    "timestamp":datetime.now().isoformat()
                }
            }
            yield {
                "type":"error",
                "data":{"message":str(e)}
            }
            raise

        yield {
            "type":"log",
            "data":{
                "level":"info",
                "message":"API Agent完了",
                "timestamp":datetime.now().isoformat()
            }
        }

    async def _call_llm(self,prompt:str,context:AgentContext,system_prompt:Optional[str]=None)->Dict[str,Any]:
        agent_max_tokens=self._get_agent_max_tokens(context.agent_type.value)
        job_queue=self.get_job_queue()
        job=job_queue.submit_job(
            project_id=context.project_id,
            agent_id=context.agent_id,
            provider_id=self._provider_id,
            model=self.model,
            prompt=prompt,
            max_tokens=agent_max_tokens,
            system_prompt=system_prompt,
        )
        if context.on_log:
            context.on_log("info",f"LLMジョブ投入: {job['id']}")
        result=await job_queue.wait_for_job_async(job["id"],timeout=300.0)
        if not result:
            raise TimeoutError(f"LLMジョブがタイムアウトしました: {job['id']}")
        if result["status"]=="failed":
            raise RuntimeError(f"LLMジョブ失敗: {result.get('errorMessage','Unknown error')}")
        return {
            "content":result["responseContent"],
            "tokens_used":result["tokensInput"]+result["tokensOutput"],
            "input_tokens":result["tokensInput"],
            "output_tokens":result["tokensOutput"],
            "model":self.model,
        }

    def _get_agent_max_tokens(self,agent_type:str)->int:
        configured=get_agent_max_tokens(agent_type)
        if configured:
            return configured
        return self.max_tokens

    def _build_prompt(self,context:AgentContext)->tuple:
        agent_type=context.agent_type.value
        base_prompt=self._prompts.get(agent_type,self._default_prompt())

        system_prompt=f"あなたはゲーム開発の専門家です。\n\n## プロジェクト情報\n{context.project_concept or'（未定義）'}"

        context_policy=get_workflow_context_policy(agent_type)
        filtered_outputs=self._filter_outputs_by_policy(context.previous_outputs,context_policy)
        previous_text=self._format_previous_outputs(filtered_outputs)

        prompt=base_prompt.format(
            project_concept="（system promptに記載）",
            previous_outputs=previous_text,
        )

        if context.assigned_task:
            prompt=f"""## あなたへの指示（Leader からの割当タスク）
{context.assigned_task}

{prompt}"""

        retry_key=f"{agent_type}_previous_attempt"
        if retry_key in context.previous_outputs:
            attempt=context.previous_outputs[retry_key]
            issues=attempt.get("issues",[])
            if issues:
                issues_text="\n".join(f"- {i}" for i in issues)
                prompt+=f"""

## 前回の品質チェック結果（修正が必要）
以下の問題点が指摘されました。これらを改善した出力を生成してください。
{issues_text}"""

        return system_prompt,prompt

    def _filter_outputs_by_policy(self,outputs:Dict[str,Any],policy:Dict[str,str])->Dict[str,Any]:
        if not policy:
            return outputs
        filtered={}
        for agent_key,output in outputs.items():
            if agent_key.endswith("_previous_attempt"):
                continue
            level=policy.get(agent_key,"full")
            if level=="none":
                continue
            elif level=="summary":
                if isinstance(output,dict) and output.get("summary"):
                    filtered[agent_key]={"content":output["summary"]}
                elif isinstance(output,dict) and output.get("content"):
                    content=str(output["content"])
                    if len(content)>1500:
                        filtered[agent_key]={"content":content[:1500]+"\n\n（以降省略）"}
                    else:
                        filtered[agent_key]=output
                else:
                    filtered[agent_key]=output
            else:
                filtered[agent_key]=output
        return filtered

    def _format_previous_outputs(self,outputs:Dict[str,Any])->str:
        if not outputs:
            return"（なし）"

        parts=[]
        for agent,output in outputs.items():
            if isinstance(output,dict) and"content" in output:
                parts.append(f"## {agent}の出力\n{output['content']}")
            else:
                parts.append(f"## {agent}の出力\n{output}")

        return"\n\n".join(parts)

    def _extract_summary(self,content:str,max_length:int=1500)->str:
        if not content:
            return""
        import re
        json_match=re.search(r'```json\s*([\s\S]*?)\s*```',content)
        if json_match:
            import json
            try:
                data=json.loads(json_match.group(1))
                keys_to_keep=["summary","title","name","description","type","tasks","worker_tasks"]
                filtered={k:v for k,v in data.items() if k in keys_to_keep}
                if filtered:
                    return json.dumps(filtered,ensure_ascii=False)[:max_length]
            except (json.JSONDecodeError,AttributeError):
                pass
        headers=re.findall(r'^#{1,3}\s+(.+)$',content,re.MULTILINE)
        if headers:
            header_summary="# 構成\n"+"\n".join(f"- {h}" for h in headers[:20])
            first_section=content[:500]
            summary=f"{first_section}\n\n{header_summary}"
            return summary[:max_length]
        return content[:max_length]

    def _process_output(self,result:Dict[str,Any],context:AgentContext)->Dict[str,Any]:
        return {
            "type":"document",
            "format":"markdown",
            "content":result.get("content",""),
            "metadata":{
                "model":result.get("model"),
                "tokens_used":result.get("tokens_used"),
                "agent_type":context.agent_type.value,
            }
        }

    def _generate_checkpoint(self,context:AgentContext,output:Dict[str,Any])->Dict[str,Any]:
        agent_type=context.agent_type.value if hasattr(context.agent_type,'value') else str(context.agent_type)
        cp_config=get_api_runner_checkpoint_config(agent_type)
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

    def _load_prompts(self)->Dict[str,str]:
        return get_all_prompts()

    def _default_prompt(self)->str:
        """デフォルトプロンプト"""
        return"""あなたはゲーム開発の専門家です。

以下の情報に基づいて、適切なドキュメントを作成してください。

## プロジェクト情報
{project_concept}

## 前のエージェントの出力
{previous_outputs}

## 要件
詳細で実用的なドキュメントを作成してください。
"""


@dataclass
class QualityCheckResult:
    passed:bool
    issues:List[str]=field(default_factory=list)
    score:float=1.0
    retry_needed:bool=False
    human_review_needed:bool=False


@dataclass
class WorkerTaskResult:
    worker_type:str
    status:str="pending"
    output:Dict[str,Any]=field(default_factory=dict)
    quality_check:Optional[QualityCheckResult]=None
    retries:int=0
    error:Optional[str]=None
    tokens_used:int=0
    input_tokens:int=0
    output_tokens:int=0


class LeaderWorkerOrchestrator:
    """Leaderの分析結果に基づいてWorkerを実行し、品質チェックに応じてリトライやHuman Review要求を行う"""

    def __init__(
        self,
        agent_runner:ApiAgentRunner,
        quality_settings:Dict[str,Any],
        on_progress:Optional[Callable[[str,int,str],None]]=None,
        on_checkpoint:Optional[Callable[[str,Dict],None]]=None,
        on_worker_created:Optional[Callable[[str,str],str]]=None,
        on_worker_status:Optional[Callable[[str,str,Dict],None]]=None,
    ):
        self.agent_runner=agent_runner
        self.quality_settings=quality_settings
        self.on_progress=on_progress
        self.on_checkpoint=on_checkpoint
        self.on_worker_created=on_worker_created
        self.on_worker_status=on_worker_status

    async def run_leader_with_workers(self,leader_context:AgentContext)->Dict[str,Any]:
        results={
            "leader_output":{},
            "worker_results":[],
            "final_output":{},
            "checkpoint":None,
            "human_review_required":[],
        }


        self._emit_progress(leader_context.agent_type.value,10,"Leader分析開始")

        leader_output=await self.agent_runner.run_agent(leader_context)
        results["leader_output"]=leader_output.output

        if leader_output.status==AgentStatus.FAILED:
            return results


        worker_tasks=self._extract_worker_tasks(leader_output.output)

        self._emit_progress(leader_context.agent_type.value,30,f"Worker実行開始 ({len(worker_tasks)}タスク)")


        total_workers=len(worker_tasks)
        for i,worker_task in enumerate(worker_tasks):
            worker_type=worker_task.get("worker","")
            task_description=worker_task.get("task","")

            progress=30+int((i/total_workers)*50)
            self._emit_progress(leader_context.agent_type.value,progress,f"{worker_type} 実行中: {task_description}")


            qc_config=self.quality_settings.get(worker_type,{})
            qc_enabled=qc_config.get("enabled",True)
            max_retries=qc_config.get("maxRetries",3)


            worker_result=await self._execute_worker(
                leader_context=leader_context,
                worker_type=worker_type,
                task=task_description,
                leader_output=leader_output.output,
                quality_check_enabled=qc_enabled,
                max_retries=max_retries,
            )

            results["worker_results"].append(worker_result.__dict__)


            if worker_result.status=="needs_human_review":
                results["human_review_required"].append({
                    "worker_type":worker_type,
                    "task":task_description,
                    "issues":worker_result.quality_check.issues if worker_result.quality_check else [],
                })


        self._emit_progress(leader_context.agent_type.value,85,"Leader統合中")

        final_output=await self._integrate_outputs(
            leader_context=leader_context,
            leader_output=leader_output.output,
            worker_results=results["worker_results"],
        )
        results["final_output"]=final_output


        self._emit_progress(leader_context.agent_type.value,95,"承認生成")

        checkpoint_data={
            "type":f"{leader_context.agent_type.value}_review",
            "title":f"{leader_context.agent_type.value} 成果物レビュー",
            "output":final_output,
            "worker_summary":{
                "total":total_workers,
                "completed":sum(1 for r in results["worker_results"] if r["status"]=="completed"),
                "failed":sum(1 for r in results["worker_results"] if r["status"]=="failed"),
                "needs_review":len(results["human_review_required"]),
            },
            "human_review_required":results["human_review_required"],
        }
        results["checkpoint"]=checkpoint_data

        if self.on_checkpoint:
            self.on_checkpoint(checkpoint_data["type"],checkpoint_data)

        self._emit_progress(leader_context.agent_type.value,100,"完了")

        return results

    async def _execute_worker(
        self,
        leader_context:AgentContext,
        worker_type:str,
        task:str,
        leader_output:Dict[str,Any],
        quality_check_enabled:bool,
        max_retries:int,
    )->WorkerTaskResult:
        """
        Workerを実行（品質チェック有無で分岐）
        """
        result=WorkerTaskResult(worker_type=worker_type)

        try:

            try:
                agent_type=AgentType(worker_type)
            except ValueError:
                result.status="failed"
                result.error=f"Unknown worker type: {worker_type}"
                return result

            worker_id=f"{leader_context.agent_id}-{worker_type}"
            if self.on_worker_created:
                worker_id=self.on_worker_created(worker_type,task) or worker_id

            worker_on_progress=None
            if self.on_worker_status:
                def _make_progress_cb(wid):
                    def cb(p,t):
                        self.on_worker_status(wid,"running",{"progress":p,"currentTask":t})
                    return cb
                worker_on_progress=_make_progress_cb(worker_id)

            worker_context=AgentContext(
                project_id=leader_context.project_id,
                agent_id=worker_id,
                agent_type=agent_type,
                project_concept=leader_context.project_concept,
                previous_outputs=leader_context.previous_outputs,
                config=leader_context.config,
                assigned_task=task,
                leader_analysis=leader_output,
                on_progress=worker_on_progress,
                on_log=leader_context.on_log,
            )

            if self.on_worker_status:
                self.on_worker_status(worker_id,"running",{"currentTask":task})

            if quality_check_enabled:
                result=await self._run_with_quality_check(
                    worker_context=worker_context,
                    worker_type=worker_type,
                    max_retries=max_retries,
                )
            else:
                output=await self.agent_runner.run_agent(worker_context)
                result.status="completed" if output.status==AgentStatus.COMPLETED else"failed"
                result.output=output.output
                result.tokens_used=output.tokens_used
                if output.error:
                    result.error=output.error

            if self.on_worker_status:
                if result.status=="completed":
                    self.on_worker_status(worker_id,"completed",{
                        "tokensUsed":result.tokens_used,
                        "inputTokens":result.input_tokens,
                        "outputTokens":result.output_tokens,
                    })
                elif result.status=="failed":
                    self.on_worker_status(worker_id,"failed",{"error":result.error})
                elif result.status=="needs_human_review":
                    self.on_worker_status(worker_id,"waiting_approval",{"currentTask":"レビュー待ち"})

        except Exception as e:
            result.status="failed"
            result.error=str(e)
            if self.on_worker_status and'worker_id' in locals():
                self.on_worker_status(worker_id,"failed",{"error":str(e)})

        return result

    async def _run_with_quality_check(
        self,
        worker_context:AgentContext,
        worker_type:str,
        max_retries:int=3,
    )->WorkerTaskResult:
        """失敗時は最大max_retries回リトライ、それでも失敗ならHuman Review要求"""
        result=WorkerTaskResult(worker_type=worker_type)

        for retry in range(max_retries):
            result.retries=retry
            output=await self.agent_runner.run_agent(worker_context)

            if output.status==AgentStatus.FAILED:
                result.error=output.error
                continue

            result.output=output.output
            qc_result=self._perform_quality_check(output.output,worker_type)
            result.quality_check=qc_result

            if qc_result.passed:
                result.status="completed"
                return result

            if retry<max_retries-1:
                result.status="needs_retry"
                worker_context.previous_outputs[f"{worker_type}_previous_attempt"]={
                    "issues":qc_result.issues,
                }
            else:
                result.status="needs_human_review"
                result.quality_check.human_review_needed=True
                return result

        return result

    def _perform_quality_check(self,output:Dict[str,Any],worker_type:str)->QualityCheckResult:
        """簡易的なルールベースチェック（本番ではLLMで品質評価）"""
        issues=[]
        score=1.0
        content=output.get("content","")

        if not content or len(str(content))<50:
            issues.append("出力内容が不十分です")
            score-=0.3

        if"```json" in str(content):
            import json
            import re
            json_match=re.search(r'```json\s*([\s\S]*?)\s*```',str(content))
            if json_match:
                try:
                    json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    issues.append("JSON形式が不正です")
                    score-=0.2

        passed=score>=0.7 and len(issues)==0

        return QualityCheckResult(
            passed=passed,
            issues=issues,
            score=score,
            retry_needed=not passed,
        )

    def _extract_worker_tasks(self,leader_output:Dict[str,Any])->List[Dict[str,Any]]:
        content=leader_output.get("content","")
        import json
        import re

        json_match=re.search(r'```json\s*([\s\S]*?)\s*```',str(content))
        if json_match:
            try:
                data=json.loads(json_match.group(1))
                return data.get("worker_tasks",[])
            except json.JSONDecodeError:
                pass

        if isinstance(leader_output,dict) and"worker_tasks" in leader_output:
            return leader_output.get("worker_tasks",[])

        return []

    async def _integrate_outputs(
        self,
        leader_context:AgentContext,
        leader_output:Dict[str,Any],
        worker_results:List[Dict[str,Any]],
    )->Dict[str,Any]:
        """Worker結果をマージ（本番ではLeaderに再度LLM呼び出しで統合）"""
        integrated={
            "type":"document",
            "format":"markdown",
            "leader_summary":leader_output,
            "worker_outputs":{},
            "metadata":{
                "agent_type":leader_context.agent_type.value,
                "worker_count":len(worker_results),
                "completed_count":sum(1 for r in worker_results if r.get("status")=="completed"),
            }
        }

        for result in worker_results:
            worker_type=result.get("worker_type","unknown")
            integrated["worker_outputs"][worker_type]={
                "status":result.get("status"),
                "output":result.get("output",{}),
            }

        return integrated

    def _emit_progress(self,agent_type:str,progress:int,message:str):
        if self.on_progress:
            self.on_progress(agent_type,progress,message)
