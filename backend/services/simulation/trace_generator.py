"""
Trace Generator Module

シミュレーション用トレース生成を担当
"""

import random

from repositories.trace import AgentTraceRepository


class TraceGenerator:
    def check_trace_generation(
        self,
        session,
        agent,
        old_progress:int,
        new_progress:int,
    )->None:
        trace_points=[20,50,80]
        for point in trace_points:
            if old_progress<point<=new_progress:
                self._create_simulation_trace(session,agent,point)

    def _create_simulation_trace(self,session,agent,progress:int)->None:
        trace_repo=AgentTraceRepository(session)
        display_name=(
            agent.metadata_.get("displayName",agent.type)
            if agent.metadata_
            else agent.type
        )
        input_tokens=random.randint(500,2000)
        output_tokens=random.randint(200,1000)
        sample_prompt=f"""あなたは{display_name}エージェントです。
以下のタスクを実行してください。

## タスク
プロジェクトの{agent.type}フェーズの処理を行います。

## 入力
進捗:{progress}%
"""
        sample_response=f"""## 処理結果

{display_name}の処理が完了しました。

### 実行内容
-データ分析を実施
-結果を生成
-品質チェックを実行

### 出力
処理は正常に完了しました。次のステップに進む準備ができています。
"""
        trace_repo.create_trace(
            project_id=agent.project_id,
            agent_id=agent.id,
            agent_type=agent.type,
            input_context={"progress":progress,"phase":agent.phase},
            model_used="simulation",
        )
        traces=trace_repo.get_by_agent(agent.id)
        if traces:
            latest_trace_id=traces[0]["id"]
            trace_repo.update_prompt(latest_trace_id,sample_prompt)
            trace_repo.complete_trace(
                trace_id=latest_trace_id,
                llm_response=sample_response,
                output_data={"type":"document","progress":progress},
                tokens_input=input_tokens,
                tokens_output=output_tokens,
                status="completed",
            )
