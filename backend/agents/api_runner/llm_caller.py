"""
LLM Caller Module

LLM呼び出し・モデル/プロバイダー解決を担当
"""

from typing import Any,Dict,Optional,TYPE_CHECKING

from config_loaders.agent_config import get_agent_max_tokens,get_agent_temperature,get_agent_usage_category
from config_loaders.workflow_config import get_context_policy_settings

if TYPE_CHECKING:
    from ..base import AgentContext


class LLMCaller:
    def __init__(
        self,
        provider_id:str,
        model:str,
        max_tokens:int,
        get_job_queue_func,
    ):
        self._provider_id=provider_id
        self.model=model
        self.max_tokens=max_tokens
        self._get_job_queue=get_job_queue_func

    async def call_llm(
        self,
        prompt:str,
        context:"AgentContext",
        system_prompt:Optional[str]=None,
    )->Dict[str,Any]:
        agent_max_tokens=self._get_agent_max_tokens(context.agent_type.value)
        temperature=self.get_project_temperature(context,context.agent_type.value)
        resolved_model=self.resolve_model_for_agent(context)
        resolved_provider=self.resolve_provider_for_agent(context)
        job_queue=self._get_job_queue()
        job=job_queue.submit_job(
            project_id=context.project_id,
            agent_id=context.agent_id,
            provider_id=resolved_provider,
            model=resolved_model,
            prompt=prompt,
            max_tokens=agent_max_tokens,
            system_prompt=system_prompt,
            temperature=str(temperature),
            on_speech=context.on_speech,
            token_budget=self.get_project_token_budget(context),
        )
        if context.on_log:
            context.on_log("info",f"LLMジョブ投入: {job['id']} model={resolved_model}")
        result=await job_queue.wait_for_job_async(job["id"],timeout=300.0)
        if not result:
            raise TimeoutError(f"LLMジョブがタイムアウトしました: {job['id']}")
        if result["status"]=="failed":
            raise RuntimeError(
                f"LLMジョブ失敗: {result.get('errorMessage', 'Unknown error')}"
            )
        return {
            "content":result["responseContent"],
            "tokens_used":result["tokensInput"]+result["tokensOutput"],
            "input_tokens":result["tokensInput"],
            "output_tokens":result["tokensOutput"],
            "model":resolved_model,
        }

    def resolve_model_for_agent(self,context:"AgentContext")->str:
        from services.llm_resolver import resolve_llm_for_project

        agent_type_str=(
            context.agent_type.value
            if hasattr(context.agent_type,"value")
            else str(context.agent_type)
        )
        usage_cat=get_agent_usage_category(agent_type_str)
        resolved=resolve_llm_for_project(context.project_id,usage_cat)
        if resolved["model"]:
            return resolved["model"]
        return self.model

    def resolve_provider_for_agent(self,context:"AgentContext")->str:
        from services.llm_resolver import resolve_llm_for_project

        agent_type_str=(
            context.agent_type.value
            if hasattr(context.agent_type,"value")
            else str(context.agent_type)
        )
        usage_cat=get_agent_usage_category(agent_type_str)
        resolved=resolve_llm_for_project(context.project_id,usage_cat)
        if resolved["provider"]:
            return resolved["provider"]
        return self._provider_id

    def get_project_temperature(
        self,context:"AgentContext",agent_type:str
    )->float:
        adv=context.config.get("advancedSettings",{}) if context.config else {}
        temp_defaults=adv.get("temperatureDefaults",{})
        role=self._get_agent_role(agent_type)
        if role in temp_defaults:
            return temp_defaults[role]
        return get_agent_temperature(agent_type)

    def _get_agent_role(self,agent_type:str)->str:
        if"leader" in agent_type.lower():
            return"leader"
        if"worker" in agent_type.lower():
            return"worker"
        if"splitter" in agent_type.lower():
            return"splitter"
        if"quality" in agent_type.lower():
            return"quality_checker"
        if"integrator" in agent_type.lower():
            return"integrator"
        return"default"

    def get_project_dag_enabled(self,context:"AgentContext")->bool:
        if context and context.config:
            adv=context.config.get("advancedSettings",{})
            dag=adv.get("dagExecution",{})
            if"enabled" in dag:
                return dag["enabled"]
        from config_loaders.workflow_config import is_dag_execution_enabled

        return is_dag_execution_enabled()

    def get_project_token_budget(
        self,context:Optional["AgentContext"]
    )->Optional[Dict[str,Any]]:
        if context and context.config:
            adv=context.config.get("advancedSettings",{})
            budget=adv.get("tokenBudget")
            if budget:
                return budget
        return None

    def get_project_context_policy(
        self,context:Optional["AgentContext"]
    )->Dict[str,Any]:
        if context and context.config:
            adv=context.config.get("advancedSettings",{})
            proj_policy=adv.get("contextPolicy",{})
            if proj_policy:
                base=get_context_policy_settings()
                base.update(proj_policy)
                return base
        return get_context_policy_settings()

    def _get_agent_max_tokens(self,agent_type:str)->int:
        configured=get_agent_max_tokens(agent_type)
        if configured:
            return configured
        return self.max_tokens
