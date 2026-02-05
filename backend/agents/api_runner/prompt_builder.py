"""
Prompt Builder Module

システムプロンプト・ユーザープロンプトの構築を担当
"""

from typing import Dict,Optional,TYPE_CHECKING

from config_loaders.prompt_config import get_all_prompts
from config_loaders.workflow_config import get_workflow_context_policy
from config_loaders.principle_config import load_principles_for_agent
from middleware.logger import get_logger

if TYPE_CHECKING:
    from ..base import AgentContext
    from .context_filter import ContextFilter


class PromptBuilder:
    def __init__(
        self,
        context_filter:"ContextFilter",
        get_agent_service_func,
        get_project_context_policy_func,
    ):
        self._context_filter=context_filter
        self._get_agent_service=get_agent_service_func
        self._get_project_context_policy=get_project_context_policy_func
        self._prompts=self._load_prompts()

    def build_prompt(self,context:"AgentContext")->tuple:
        agent_type=context.agent_type.value
        base_prompt=self._prompts.get(agent_type,self._default_prompt())

        adv=context.config.get("advancedSettings",{}) if context.config else {}
        enabled_principles=adv.get("enabledPrinciples")
        principle_overrides=adv.get("principleOverrides")
        principles_text=load_principles_for_agent(
            agent_type,enabled_principles,principle_overrides
        )
        system_prompt=f"あなたはゲーム開発の専門家です。\n\n## プロジェクト情報\n{context.project_concept or '（未定義）'}"
        if principles_text:
            system_prompt+=f"\n\n## ゲームデザイン原則\n以下の原則に従って作業し、自己評価してください。\n{principles_text}"
        if context.on_speech:
            try:
                from services.agent_speech_service import get_agent_speech_service

                comment_instruction=get_agent_speech_service().get_comment_instruction(
                    agent_type
                )
                system_prompt+=f"\n\n## 一言コメント\n{comment_instruction}"
            except Exception as e:
                get_logger().warning(
                    f"Failed to load comment instruction for {agent_type}: {e}"
                )

        memory_section=self._build_memory_section(agent_type,context.project_id)
        if memory_section:
            system_prompt+=f"\n\n{memory_section}"

        context_policy=get_workflow_context_policy(agent_type)
        filtered_outputs=self._context_filter.filter_outputs_by_policy(
            context.previous_outputs,context_policy,context
        )
        if context.leader_analysis and not filtered_outputs:
            leader_content=context.leader_analysis.get("content","")
            if leader_content:
                settings=self._get_project_context_policy(context)
                leader_max=settings.get("leader_output_max_for_worker",5000)
                filtered_outputs={"leader":{"content":leader_content[:leader_max]}}
        previous_text=self._context_filter.format_previous_outputs(filtered_outputs)

        prompt_parts=[]
        prompt_parts.append(f"## 参照データ\n{previous_text}")
        retry_key=f"{agent_type}_previous_attempt"
        if retry_key in context.previous_outputs:
            attempt=context.previous_outputs[retry_key]
            issues=attempt.get("issues",[])
            failed_criteria=attempt.get("failed_criteria",[])
            suggestions=attempt.get("improvement_suggestions",[])
            if issues or failed_criteria:
                retry_parts=["## 前回の品質チェック結果（修正が必要）"]
                if failed_criteria:
                    criteria_text="\n".join(f"- {c}" for c in failed_criteria)
                    retry_parts.append(f"### 不合格の評価基準:\n{criteria_text}")
                if suggestions:
                    suggestions_text="\n".join(f"- {s}" for s in suggestions)
                    retry_parts.append(f"### 改善提案:\n{suggestions_text}")
                elif issues:
                    issues_text="\n".join(f"- {i}" for i in issues)
                    retry_parts.append(f"### 問題点:\n{issues_text}")
                prompt_parts.append("\n".join(retry_parts))
        task_prompt=base_prompt.format(
            project_concept="（system promptに記載）",
            previous_outputs="（上記の参照データを参照）",
        )
        if context.assigned_task:
            prompt_parts.append(
                f"## あなたへの指示（Leader からの割当タスク）\n{context.assigned_task}"
            )
        prompt_parts.append(task_prompt)
        prompt="\n\n".join(prompt_parts)
        return system_prompt,prompt

    def _build_memory_section(
        self,agent_type:str,project_id:Optional[str]=None
    )->str:
        agent_service=self._get_agent_service()
        if not agent_service:
            return""
        try:
            memories=agent_service.get_agent_memories(
                agent_type=agent_type,
                project_id=project_id,
                categories=[
                    "quality_insight",
                    "hallucination_pattern",
                    "improvement_pattern",
                ],
                limit=5,
            )
            if not memories:
                return""
            items=[]
            for m in memories:
                items.append(f"- {m['content']}")
            return (
                f"## 過去の品質チェックからの知見\n以下は過去の品質チェック結果から得られた知見です。同様の問題を繰り返さないよう注意してください。\n"
                +"\n".join(items)
            )
        except Exception as e:
            get_logger().error(f"Memory section build failed: {e}",exc_info=True)
            return""

    def _load_prompts(self)->Dict[str,str]:
        return get_all_prompts()

    def _default_prompt(self)->str:
        return"""あなたはゲーム開発の専門家です。

以下の情報に基づいて、適切なドキュメントを作成してください。

## プロジェクト情報
{project_concept}

## 前のエージェントの出力
{previous_outputs}

## 要件
詳細で実用的なドキュメントを作成してください。
"""
