import asyncio
import json
import re
from collections import Counter
from datetime import datetime
from typing import Any,Dict,List,AsyncGenerator,Optional,Callable
from dataclasses import dataclass,field

from .base import (
 AgentRunner,
 AgentContext,
 AgentOutput,
 AgentType,
 AgentStatus,
)
from .api_runner import ApiAgentRunner
from skills import create_skill_executor,SkillExecutor,SkillResult

DEFAULT_MAX_ITERATIONS=50
LOOP_DETECTION_WINDOW=6
LOOP_DETECTION_REPEAT_THRESHOLD=3
FINALIZING_BUDGET=1


@dataclass
class ToolCall:
 id:str
 name:str
 input:Dict[str,Any]


@dataclass
class IterationRecord:
 iteration:int
 skill_names:List[str]=field(default_factory=list)
 skill_results:List[bool]=field(default_factory=list)


class LoopDetector:
 def __init__(self,window:int=LOOP_DETECTION_WINDOW,repeat_threshold:int=LOOP_DETECTION_REPEAT_THRESHOLD):
  self._window=window
  self._repeat_threshold=repeat_threshold
  self._history:List[str]=[]

 def record(self,skill_names:List[str]):
  key=",".join(sorted(skill_names))
  self._history.append(key)

 def is_looping(self)->bool:
  if len(self._history)<self._window:
   return False
  recent=self._history[-self._window:]
  counts=Counter(recent)
  most_common_count=counts.most_common(1)[0][1]
  return most_common_count>=self._repeat_threshold

 def get_loop_info(self)->Optional[str]:
  if not self.is_looping():
   return None
  recent=self._history[-self._window:]
  counts=Counter(recent)
  pattern,count=counts.most_common(1)[0]
  return f"直近{self._window}回中{count}回同一パターン: [{pattern}]"


class SkillEnabledAgentRunner(AgentRunner):
 def __init__(
  self,
  base_runner:ApiAgentRunner,
  working_dir:str,
  max_tool_iterations:int=DEFAULT_MAX_ITERATIONS,
 ):
  self._base=base_runner
  self._working_dir=working_dir
  self._max_iterations=max_tool_iterations
  self._skill_executor:Optional[SkillExecutor]=None

 def _get_executor(self,context:AgentContext)->SkillExecutor:
  if self._skill_executor is None:
   agent_type=context.agent_type.value if hasattr(context.agent_type,'value') else str(context.agent_type)
   self._skill_executor=create_skill_executor(
    project_id=context.project_id,
    agent_id=context.agent_id,
    agent_type=agent_type,
    working_dir=self._working_dir,
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

 async def run_agent_stream(self,context:AgentContext)->AsyncGenerator[Dict[str,Any],None]:
  executor=self._get_executor(context)
  available_skills=executor.get_available_skills()
  data_store=self._base._data_store
  trace_id=None
  if data_store:
   try:
    trace=data_store.create_trace(
     project_id=context.project_id,
     agent_id=context.agent_id,
     agent_type=context.agent_type.value,
     input_context={"project_concept":context.project_concept,"config":context.config},
     model_used=self._base.model
    )
    trace_id=trace.get("id")
   except Exception as e:
    print(f"[SkillRunner] Failed to create trace: {e}")
  yield {
   "type":"log",
   "data":{
    "level":"info",
    "message":f"Skill-enabled Agent開始: {context.agent_type.value}, 利用可能スキル: {len(available_skills)}",
    "timestamp":datetime.now().isoformat()
   }
  }
  skill_schemas=executor.get_skill_schemas_for_llm()
  enhanced_context=self._enhance_context_with_skills(context,skill_schemas)
  initial_prompt=self._build_initial_prompt(enhanced_context,skill_schemas)
  if data_store and trace_id:
   try:
    data_store.update_trace_prompt(trace_id,initial_prompt)
   except Exception as e:
    print(f"[SkillRunner] Failed to update trace prompt: {e}")
  messages=[{"role":"user","content":initial_prompt}]
  iteration=0
  total_tokens=0
  final_output=None
  last_response_content=""
  loop_detector=LoopDetector()
  stop_reason=None
  try:
   while iteration<self._max_iterations:
    iteration+=1
    remaining=self._max_iterations-iteration
    progress=min(85,10+int((iteration/self._max_iterations)*75))
    yield {
     "type":"progress",
     "data":{"progress":progress,"current_task":f"LLM呼び出し中 (iteration {iteration}/{self._max_iterations})"}
    }
    if remaining<=FINALIZING_BUDGET and iteration>1:
     messages.append({"role":"user","content":self._build_finalize_prompt(remaining)})
    elif iteration>1 and iteration%10==0:
     messages.append({"role":"user","content":self._build_progress_check_prompt(iteration,remaining)})
    response=await self._call_llm_with_tools(messages,skill_schemas,context)
    tokens_used=response.get("tokens_used",0)
    total_tokens+=tokens_used
    yield {
     "type":"tokens",
     "data":{"count":tokens_used}
    }
    last_response_content=response.get("content","")
    tool_calls=self._extract_tool_calls(last_response_content)
    if not tool_calls:
     final_output=self._process_final_response(response,context)
     break
    yield {
     "type":"log",
     "data":{
      "level":"info",
      "message":f"ツール呼び出し: {[tc.name for tc in tool_calls]}",
      "timestamp":datetime.now().isoformat()
     }
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
       "timestamp":datetime.now().isoformat()
      }
     }
     break
    messages.append({"role":"assistant","content":last_response_content})
    tool_results=[]
    for tc in tool_calls:
     yield {
      "type":"skill_call",
      "data":{"skill":tc.name,"params":tc.input}
     }
     result=await executor.execute_skill(tc.name,**tc.input)
     yield {
      "type":"skill_result",
      "data":{"skill":tc.name,"success":result.success,"output":str(result.output)[:500]}
     }
     tool_results.append(self._format_tool_result(tc,result))
    messages.append({"role":"user","content":"\n\n".join(tool_results)})
   if final_output is None:
    if stop_reason is None:
     stop_reason=f"最大イテレーション数({self._max_iterations})に到達"
    final_output=await self._generate_summary_output(messages,skill_schemas,context,stop_reason)
    total_tokens+=final_output.get("metadata",{}).get("summary_tokens",0)
   if data_store and trace_id:
    try:
     input_tokens=int(total_tokens*0.3)
     output_tokens=total_tokens-input_tokens
     data_store.complete_trace(
      trace_id=trace_id,
      llm_response=last_response_content,
      output_data=final_output,
      tokens_input=input_tokens,
      tokens_output=output_tokens,
      status="completed"
     )
    except Exception as e:
     print(f"[SkillRunner] Failed to complete trace: {e}")
  except Exception as e:
   if data_store and trace_id:
    try:
     data_store.fail_trace(trace_id,str(e))
    except Exception as te:
     print(f"[SkillRunner] Failed to fail trace: {te}")
   raise
  yield {
   "type":"progress",
   "data":{"progress":90,"current_task":"完了処理中"}
  }
  yield {
   "type":"checkpoint",
   "data":{
    "type":"review",
    "title":f"{context.agent_type.value} 成果物レビュー",
    "output":final_output,
    "skill_history":executor.get_execution_history(),
   }
  }
  yield {
   "type":"progress",
   "data":{"progress":100,"current_task":"完了"}
  }
  yield {
   "type":"output",
   "data":final_output
  }

 def _build_progress_check_prompt(self,iteration:int,remaining:int)->str:
  return f"""[システム通知] 現在{iteration}イテレーション目です。残り{remaining}回のイテレーションが可能です。

以下を確認してください:
- 作業は進捗していますか？同じ操作を繰り返していませんか？
- 問題が解決に向かっていない場合、別のアプローチを検討してください。
- 残りイテレーション内で完了できない場合、現時点の成果をまとめて最終出力としてください。
- 最終出力を行う場合はtool_callブロックを含めないでください。"""

 def _build_finalize_prompt(self,remaining:int)->str:
  return f"""[システム通知] 残りイテレーションは{remaining}回です。これが最後の作業機会です。

これ以上のスキル呼び出しは行わず、ここまでの作業成果を最終出力としてまとめてください。
tool_callブロックを含めず、成果物を出力してください。"""

 async def _generate_summary_output(self,messages:List[Dict],skill_schemas:List[Dict],context:AgentContext,stop_reason:str)->Dict[str,Any]:
  summary_prompt=f"""[システム通知] {stop_reason}のため、作業を終了します。

これまでの作業内容と成果を最終出力としてまとめてください。
- 完了した作業の成果をすべて含めてください。
- 未完了の作業がある場合、何が残っているかを明記してください。
- tool_callブロックは含めないでください。"""
  messages_copy=list(messages)
  messages_copy.append({"role":"user","content":summary_prompt})
  try:
   response=await self._call_llm_with_tools(messages_copy,skill_schemas,context)
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
    "content":last_content or f"作業は{stop_reason}により中断されました。まとめ生成にも失敗しました: {e}",
    "metadata":{
     "agent_type":context.agent_type.value,
     "stop_reason":stop_reason,
     "summary_error":str(e),
    }
   }

 def _build_initial_prompt(self,context:AgentContext,skill_schemas:List[Dict])->str:
  skills_desc="\n".join([
   f"- {s['name']}: {s['description']}"
   for s in skill_schemas
  ])
  assigned_task_section=""
  if context.assigned_task:
   assigned_task_section=f"""## あなたへの指示（Leader からの割当タスク）
{context.assigned_task}

"""
  return f"""{assigned_task_section}あなたはゲーム開発の専門家です。以下のスキル（ツール）を使って作業を行えます。

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

## 前のエージェントの出力
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
    parts.append(f"## {agent}の出力\n{output['content'][:2000]}")
   else:
    parts.append(f"## {agent}の出力\n{str(output)[:2000]}")
  return"\n\n".join(parts)

 def _enhance_context_with_skills(self,context:AgentContext,skill_schemas:List[Dict])->AgentContext:
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
  )

 async def _call_llm_with_tools(
  self,
  messages:List[Dict],
  skill_schemas:List[Dict],
  context:AgentContext
 )->Dict[str,Any]:
  full_prompt="\n\n---\n\n".join([
   f"[{m['role']}]\n{m['content']}" for m in messages
  ])
  job_queue=self._base.get_job_queue()
  job=job_queue.submit_job(
   project_id=context.project_id,
   agent_id=context.agent_id,
   provider_id=self._base._provider_id,
   model=self._base.model,
   prompt=full_prompt,
   max_tokens=self._base.max_tokens,
  )
  result=await job_queue.wait_for_job_async(job["id"],timeout=300.0)
  if not result:
   raise TimeoutError(f"LLMジョブがタイムアウトしました: {job['id']}")
  if result["status"]=="failed":
   raise RuntimeError(f"LLMジョブ失敗: {result.get('errorMessage','Unknown error')}")
  return {
   "content":result["responseContent"],
   "tokens_used":result["tokensInput"]+result["tokensOutput"],
  }

 def _extract_tool_calls(self,content:str)->List[ToolCall]:
  pattern=r'```tool_call\s*\n?(.*?)\n?```'
  matches=re.findall(pattern,content,re.DOTALL)
  tool_calls=[]
  for i,match in enumerate(matches):
   try:
    data=json.loads(match.strip())
    tool_calls.append(ToolCall(
     id=f"tc_{i}",
     name=data.get("name",""),
     input=data.get("input",{}),
    ))
   except json.JSONDecodeError:
    continue
  return tool_calls

 def _format_tool_result(self,tc:ToolCall,result:SkillResult)->str:
  if result.success:
   output=result.output
   if isinstance(output,(dict,list)):
    output=json.dumps(output,ensure_ascii=False,indent=2)
   return f"""[ツール実行結果: {tc.name}]
成功:はい
出力:
{str(output)[:5000]}"""
  else:
   return f"""[ツール実行結果: {tc.name}]
成功:いいえ
エラー:{result.error}"""

 def _process_final_response(self,response:Dict[str,Any],context:AgentContext)->Dict[str,Any]:
  return {
   "type":"document",
   "format":"markdown",
   "content":response.get("content",""),
   "metadata":{
    "agent_type":context.agent_type.value,
    "tokens_used":response.get("tokens_used",0),
   }
  }

 def get_supported_agents(self)->List[AgentType]:
  return self._base.get_supported_agents()

 def validate_context(self,context:AgentContext)->bool:
  return self._base.validate_context(context)
