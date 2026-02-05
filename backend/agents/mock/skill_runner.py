import asyncio
import json
import os
import re
from datetime import datetime
from typing import Any,Dict,List,AsyncGenerator
from dataclasses import dataclass

from .base import MockRunnerBase
from .asset_generator import MockAssetGenerator
from ..base import AgentContext
from skills import create_skill_executor,SkillExecutor,SkillResult
from config_loaders.mock_config import get_mock_skill_sequences
from config_loaders.skill_config import get_mock_handler_config


@dataclass
class MockToolCall:
    id:str
    name:str
    input:Dict[str,Any]


class MockSkillRunner(MockRunnerBase):

    def __init__(
        self,
        trace_service=None,
        agent_service=None,
        asset_generator:MockAssetGenerator|None=None,
        **kwargs
    ):
        super().__init__(trace_service=trace_service,**kwargs)
        self._agent_service=agent_service
        self._working_dir=kwargs.get("working_dir") or os.environ.get(
            "PROJECT_WORKING_DIR","/tmp/toybox/projects"
        )
        self._asset_generator=asset_generator or MockAssetGenerator(self._working_dir)

    def _process_stream_event(
        self,
        event:Dict[str,Any],
        tokens_used:int,
        output:Dict[str,Any],
    )->tuple[int,Dict[str,Any]]:
        event_type=event["type"]
        data=event["data"]
        if event_type=="output":
            return tokens_used,data
        if event_type=="tokens":
            return tokens_used+data.get("count",0),output
        return tokens_used,output

    async def run_agent_stream(self,context:AgentContext)->AsyncGenerator[Dict[str,Any],None]:
        agent_type=self._get_agent_type_str(context)
        executor=self._create_executor(context)
        sequences=get_mock_skill_sequences(agent_type)
        yield self._log_event("info",f"MockSkill Agent開始: {agent_type} (シーケンス数: {len(sequences)})")
        yield self._progress_event(5,"AI API接続中")
        await asyncio.sleep(0.05*self._simulation_speed)
        self._emit_start_speech(context,agent_type)
        skill_history:List[Dict[str,Any]]=[]
        total_tokens=0
        final_content=""
        total_steps=len(sequences)
        for step_idx,step in enumerate(sequences):
            step_progress=10+int((step_idx/max(total_steps,1))*75)
            content=step.get("content","")
            yield self._log_event("info",f"AI応答受信 (ステップ {step_idx + 1}/{total_steps})")
            step_tokens=200+len(content)*2
            total_tokens+=step_tokens
            yield {"type":"tokens","data":{"count":step_tokens}}
            tool_calls=self._extract_tool_calls(content)
            if tool_calls:
                async for event in self._execute_tool_calls(
                    tool_calls,step_progress,context,executor,skill_history
                ):
                    yield event
            else:
                final_content=content
                yield self._progress_event(step_progress,"AI応答処理中")
            await asyncio.sleep(0.05*self._simulation_speed)
        if not final_content and sequences:
            final_content=sequences[-1].get("content","")
        output=self._build_output(agent_type,final_content,skill_history)
        yield self._progress_event(90,"完了処理中")
        async for event in self._emit_checkpoint(context,agent_type,output,skill_history):
            yield event
        yield self._progress_event(100,"完了")
        yield {"type":"output","data":output}
        yield self._log_event(
            "info",f"MockSkill Agent完了 (スキル実行: {len(skill_history)}回, トークン: {total_tokens})"
        )

    async def _execute_tool_calls(
        self,
        tool_calls:List[MockToolCall],
        step_progress:int,
        context:AgentContext,
        executor:SkillExecutor,
        skill_history:List[Dict[str,Any]],
    )->AsyncGenerator[Dict[str,Any],None]:
        yield self._progress_event(
            step_progress,f"スキル実行中: {', '.join([tc.name for tc in tool_calls])}"
        )
        yield self._log_event("info",f"ツール呼び出し: {[tc.name for tc in tool_calls]}")
        for tc in tool_calls:
            yield {"type":"skill_call","data":{"skill":tc.name,"params":tc.input}}
            result=await self._execute_skill(tc,executor)
            yield {
                "type":"skill_result",
                "data":{"skill":tc.name,"success":result.success,"output":str(result.output)[:500]},
            }
            skill_history.append({
                "skill":tc.name,
                "params":tc.input,
                "success":result.success,
                "output":str(result.output)[:200],
                "error":result.error,
            })
            await asyncio.sleep(0.03*self._simulation_speed)

    async def _execute_skill(self,tc:MockToolCall,executor:SkillExecutor)->SkillResult:
        handler_config=get_mock_handler_config(tc.name)
        if not handler_config:
            return await executor.execute_skill(tc.name,**tc.input)
        handler_type=handler_config.get("handler_type","")
        if handler_type=="image":
            return await self._asset_generator.generate_image(
                tc.input,
                handler_config.get("output_dir","assets/images"),
                handler_config.get("output_format","png"),
            )
        if handler_type=="audio":
            return self._asset_generator.generate_audio(
                tc.input,
                handler_config.get("audio_type","audio"),
                handler_config.get("output_format","wav"),
                handler_config.get("output_dir","assets/audio"),
            )
        return SkillResult(success=False,error=f"Unknown handler type: {handler_type}")

    async def _emit_checkpoint(
        self,
        context:AgentContext,
        agent_type:str,
        output:Dict[str,Any],
        skill_history:List[Dict[str,Any]],
    )->AsyncGenerator[Dict[str,Any],None]:
        checkpoint_data=self._generate_checkpoint_data(
            context,
            output,
            extra_data={
                "description":f"{agent_type}エージェントの成果物を確認してください",
                "skill_history":skill_history,
            }
        )
        yield {"type":"checkpoint","data":checkpoint_data}
        if context.on_checkpoint:
            context.on_checkpoint(
                checkpoint_data["type"],
                {"output":output,"skill_history":skill_history}
            )

    def _create_executor(self,context:AgentContext)->SkillExecutor:
        agent_type=self._get_agent_type_str(context)
        return create_skill_executor(
            project_id=context.project_id,
            agent_id=context.agent_id,
            agent_type=agent_type,
            working_dir=self._working_dir,
            on_progress=context.on_progress,
        )

    def _extract_tool_calls(self,content:str)->List[MockToolCall]:
        pattern=r"```tool_call\s*\n?(.*?)\n?```"
        matches=re.findall(pattern,content,re.DOTALL)
        tool_calls=[]
        for i,match in enumerate(matches):
            try:
                data=json.loads(match.strip())
                tool_calls.append(
                    MockToolCall(
                        id=f"mock_tc_{i}",
                        name=data.get("name",""),
                        input=data.get("input",{}),
                    )
                )
            except json.JSONDecodeError:
                continue
        return tool_calls

    def _emit_start_speech(self,context:AgentContext,agent_type:str)->None:
        if not context.on_speech:
            return
        try:
            from services.agent_speech_service import get_agent_speech_service
            comment=get_agent_speech_service().get_pool_comment(agent_type,"started")
            if comment:
                context.on_speech(comment)
        except Exception:
            pass

    def _build_output(
        self,agent_type:str,content:str,skill_history:List[Dict[str,Any]]
    )->Dict[str,Any]:
        return {
            "type":"document",
            "format":"markdown",
            "content":content,
            "metadata":{
                "mock":True,
                "mock_skill_mode":True,
                "agent_type":agent_type,
                "skill_history":skill_history,
                "total_skill_calls":len(skill_history),
                "generated_at":datetime.now().isoformat(),
            },
        }
