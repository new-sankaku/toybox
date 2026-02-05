"""
Skill Prompt Builder Module

スキルランナー用のプロンプト構築を担当
"""

from typing import Any,Dict,List,TYPE_CHECKING

if TYPE_CHECKING:
    from ..base import AgentContext


class SkillPromptBuilder:
    def __init__(self,prev_output_max:int=2000):
        self._prev_output_max=prev_output_max

    def build_system_prompt(
        self,
        context:"AgentContext",
        skill_schemas:List[Dict],
        use_native_tools:bool=False,
    )->str:
        skills_desc="\n".join(
            [f"- {s['name']}: {s['description']}" for s in skill_schemas]
        )
        if use_native_tools:
            return f"""あなたはゲーム開発の専門家です。利用可能なツール（function calling）を使って作業を行えます。

## 利用可能なスキル
{skills_desc}

ツールの実行結果を受け取った後、次のアクションを決定するか、最終的な回答を出力してください。
最終的な回答を出力する場合はツール呼び出しを含めないでください。

## プロジェクト情報
{context.project_concept or"（未定義）"}
{self._get_comment_section(context)}"""
        return f"""あなたはゲーム開発の専門家です。以下のスキル（ツール）を使って作業を行えます。

## 利用可能なスキル
{skills_desc}

## スキルの呼び出し方法
スキルを使う場合は、以下の形式でJSONブロックを記述してください:

```tool_call
{{"name":"スキル名","input":{{"param1":"value1"}}}}
```

複数のスキルを呼び出す場合は、複数のtool_callブロックを記述できます。

スキルの実行結果を受け取った後、次のアクションを決定するか、最終的な回答を出力してください。
最終的な回答を出力する場合は、tool_callブロックを含めないでください。

## プロジェクト情報
{context.project_concept or"（未定義）"}
{self._get_comment_section(context)}"""

    def _get_comment_section(self,context:"AgentContext")->str:
        if not context.on_speech:
            return""
        try:
            from services.agent_speech_service import get_agent_speech_service

            agent_type=(
                context.agent_type.value
                if hasattr(context.agent_type,"value")
                else str(context.agent_type)
            )
            instruction=get_agent_speech_service().get_comment_instruction(agent_type)
            return f"\n## 一言コメント\n{instruction}"
        except Exception:
            return""

    def build_user_prompt(self,context:"AgentContext")->str:
        assigned_task_section=""
        if context.assigned_task:
            assigned_task_section=f"""## あなたへの指示（Leader からの割当タスク）
{context.assigned_task}

"""
        return f"""{assigned_task_section}## 前のエージェントの出力
{self._format_previous_outputs(context.previous_outputs)}

## あなたのタスク
{context.agent_type.value}エージェントとして、適切な成果物を作成してください。
必要に応じてスキルを使ってファイルを読み書きしたり、コマンドを実行してください。
"""

    def _format_previous_outputs(self,outputs:Dict[str,Any])->str:
        if not outputs:
            return"（なし）"
        parts=[]
        for agent,output in outputs.items():
            if isinstance(output,dict) and"content" in output:
                parts.append(
                    f"## {agent}の出力\n{output['content'][:self._prev_output_max]}"
                )
            else:
                parts.append(f"## {agent}の出力\n{str(output)[:self._prev_output_max]}")
        return"\n\n".join(parts)

    def build_progress_check_prompt(self,iteration:int,remaining:int)->str:
        return f"""[システム通知] 現在{iteration}イテレーション目です。残り{remaining}回のイテレーションが可能です。

以下を確認してください:
-作業は進捗していますか？同じ操作を繰り返していませんか？
-問題が解決に向かっていない場合、別のアプローチを検討してください。
-残りイテレーション内で完了できない場合、現時点の成果をまとめて最終出力としてください。
-最終出力を行う場合はtool_callブロックを含めないでください。"""

    def build_finalize_prompt(self,remaining:int)->str:
        return f"""[システム通知] 残りイテレーションは{remaining}回です。これが最後の作業機会です。

これ以上のスキル呼び出しは行わず、ここまでの作業成果を最終出力としてまとめてください。
tool_callブロックを含めず、成果物を出力してください。"""

    def build_summary_prompt(self,stop_reason:str)->str:
        return f"""[システム通知] {stop_reason}のため、作業を終了します。

これまでの作業内容と成果を最終出力としてまとめてください。
-完了した作業の成果をすべて含めてください。
-未完了の作業がある場合、何が残っているかを明記してください。
-tool_callブロックは含めないでください。"""
