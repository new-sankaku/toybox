"""Claude Code プロバイダー - CLIを通じてClaude Codeを呼び出す"""
import subprocess
import json
import os
from typing import List,Optional,Dict,Any,Iterator
from enum import Enum
from .base import (
 AIProvider,AIProviderConfig,ChatMessage,ChatResponse,
 StreamChunk,ModelInfo,MessageRole
)


class ClaudeCodeMode(str,Enum):
 RESPONSE="response"
 ACTION="action"


class ClaudeCodeProvider(AIProvider):
 """Claude Code CLIプロバイダー"""

 @property
 def provider_id(self)->str:
  return"claude-code"

 @property
 def display_name(self)->str:
  return"Claude Code (CLI)"

 def get_available_models(self)->List[ModelInfo]:
  models=self.load_models_from_config(self.provider_id)
  if models:
   return models
  return [
   ModelInfo(
    id="opus",
    name="Claude Opus (via CLI)",
    max_tokens=8192,
    supports_vision=False,
    supports_tools=True,
   ),
   ModelInfo(
    id="sonnet",
    name="Claude Sonnet (via CLI)",
    max_tokens=8192,
    supports_vision=False,
    supports_tools=True,
   ),
  ]

 def _build_command(
  self,
  prompt:str,
  model:str="opus",
  system_prompt:Optional[str]=None,
  working_dir:Optional[str]=None,
  mode:ClaudeCodeMode=ClaudeCodeMode.RESPONSE,
  allowed_tools:Optional[List[str]]=None,
 )->List[str]:
  cmd=["claude","-p","--output-format","json","--dangerously-skip-permissions"]
  if model:
   cmd.extend(["--model",model])
  if system_prompt:
   cmd.extend(["--system-prompt",system_prompt])
  if allowed_tools:
   cmd.extend(["--allowedTools"]+allowed_tools)
  cmd.append(prompt)
  return cmd

 def _parse_json_output(self,output:str)->Dict[str,Any]:
  try:
   return json.loads(output)
  except json.JSONDecodeError:
   return {"content":output,"raw":True}

 def _get_git_changes(self,working_dir:str)->List[Dict[str,str]]:
  try:
   result=subprocess.run(
    ["git","diff","--name-status","HEAD"],
    cwd=working_dir,
    capture_output=True,
    text=True,
    timeout=10
   )
   changes=[]
   for line in result.stdout.strip().split("\n"):
    if line:
     parts=line.split("\t",1)
     if len(parts)==2:
      status,path=parts
      action_map={"M":"modified","A":"added","D":"deleted","R":"renamed"}
      changes.append({
       "path":path,
       "action":action_map.get(status[0],"unknown")
      })
   return changes
  except Exception:
   return []

 def chat(
  self,
  messages:List[ChatMessage],
  model:str,
  max_tokens:int=1024,
  temperature:float=0.7,
  **kwargs
 )->ChatResponse:
  mode=ClaudeCodeMode(kwargs.get("mode",ClaudeCodeMode.RESPONSE))
  working_dir=kwargs.get("working_dir",os.getcwd())
  system_prompt=kwargs.get("system_prompt")
  allowed_tools=kwargs.get("allowed_tools")

  prompt_parts=[]
  for msg in messages:
   if msg.role==MessageRole.SYSTEM:
    system_prompt=msg.content
   elif msg.role==MessageRole.USER:
    prompt_parts.append(msg.content)
   elif msg.role==MessageRole.ASSISTANT:
    prompt_parts.append(f"[Previous response]: {msg.content}")

  prompt="\n\n".join(prompt_parts)

  cmd=self._build_command(
   prompt=prompt,
   model=model,
   system_prompt=system_prompt,
   working_dir=working_dir,
   mode=mode,
   allowed_tools=allowed_tools,
  )

  try:
   result=subprocess.run(
    cmd,
    cwd=working_dir,
    capture_output=True,
    text=True,
    timeout=kwargs.get("timeout",600)
   )

   if result.returncode!=0 and result.stderr:
    raise RuntimeError(f"Claude Code error: {result.stderr}")

   output=result.stdout
   parsed=self._parse_json_output(output)

   content=""
   if isinstance(parsed,dict):
    if"result"in parsed:
     content=parsed["result"]
    elif"content"in parsed:
     content=parsed["content"]
    elif"text"in parsed:
     content=parsed["text"]
    else:
     content=json.dumps(parsed,ensure_ascii=False)
   else:
    content=str(parsed)

   if mode==ClaudeCodeMode.ACTION:
    changed_files=self._get_git_changes(working_dir)
    action_result={
     "status":"completed",
     "content":content,
     "changed_files":changed_files,
     "exit_code":result.returncode
    }
    content=json.dumps(action_result,ensure_ascii=False)

   return ChatResponse(
    content=content,
    model=model,
    input_tokens=0,
    output_tokens=0,
    total_tokens=0,
    finish_reason="stop",
    raw_response=parsed
   )

  except subprocess.TimeoutExpired:
   raise RuntimeError("Claude Code execution timed out")
  except FileNotFoundError:
   raise RuntimeError("Claude Code CLI not found. Please install it first.")

 def chat_stream(
  self,
  messages:List[ChatMessage],
  model:str,
  max_tokens:int=1024,
  temperature:float=0.7,
  **kwargs
 )->Iterator[StreamChunk]:
  response=self.chat(messages,model,max_tokens,temperature,**kwargs)
  yield StreamChunk(
   content=response.content,
   is_final=True,
   input_tokens=response.input_tokens,
   output_tokens=response.output_tokens
  )

 def test_connection(self)->Dict[str,Any]:
  try:
   result=subprocess.run(
    ["claude","--version"],
    capture_output=True,
    text=True,
    timeout=10
   )
   if result.returncode==0:
    version=result.stdout.strip()
    return {
     "success":True,
     "message":f"Claude Code CLI: {version}"
    }
   return {
    "success":False,
    "message":f"Claude Code CLI error: {result.stderr}"
   }
  except FileNotFoundError:
   return {
    "success":False,
    "message":"Claude Code CLI not found"
   }
  except Exception as e:
   return {
    "success":False,
    "message":f"Error: {str(e)}"
   }

 def validate_config(self)->bool:
  result=self.test_connection()
  return result.get("success",False)

 def execute_action(
  self,
  task:str,
  working_dir:str,
  model:str="opus",
  system_prompt:Optional[str]=None,
  allowed_tools:Optional[List[str]]=None,
  timeout:int=600
 )->Dict[str,Any]:
  messages=[ChatMessage(role=MessageRole.USER,content=task)]
  if system_prompt:
   messages.insert(0,ChatMessage(role=MessageRole.SYSTEM,content=system_prompt))

  response=self.chat(
   messages=messages,
   model=model,
   mode=ClaudeCodeMode.ACTION,
   working_dir=working_dir,
   allowed_tools=allowed_tools,
   timeout=timeout
  )

  try:
   return json.loads(response.content)
  except json.JSONDecodeError:
   return {
    "status":"completed",
    "content":response.content,
    "changed_files":[],
    "exit_code":0
   }

 def get_response(
  self,
  prompt:str,
  working_dir:Optional[str]=None,
  model:str="opus",
  system_prompt:Optional[str]=None,
  timeout:int=300
 )->str:
  messages=[ChatMessage(role=MessageRole.USER,content=prompt)]
  if system_prompt:
   messages.insert(0,ChatMessage(role=MessageRole.SYSTEM,content=system_prompt))

  response=self.chat(
   messages=messages,
   model=model,
   mode=ClaudeCodeMode.RESPONSE,
   working_dir=working_dir or os.getcwd(),
   timeout=timeout
  )

  return response.content
