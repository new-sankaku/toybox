import asyncio
import json
import os
import re
import struct
import zlib
from datetime import datetime
from typing import Any,Dict,List,AsyncGenerator,Optional
from dataclasses import dataclass

from .base import (
 AgentRunner,
 AgentContext,
 AgentOutput,
 AgentType,
 AgentStatus,
)
from skills import create_skill_executor,SkillExecutor,SkillResult
from config_loader import get_mock_skill_sequences,get_checkpoint_title_config


ASSET_SKILLS={"image_generate","bgm_generate","sfx_generate","voice_generate"}


@dataclass
class MockToolCall:
 id:str
 name:str
 input:Dict[str,Any]


class MockSkillRunner(AgentRunner):

 def __init__(self,data_store=None,**kwargs):
  self.data_store=data_store
  self._simulation_speed=kwargs.get("simulation_speed",1.0)
  self._working_dir=kwargs.get("working_dir",None) or os.environ.get("PROJECT_WORKING_DIR","/tmp/toybox/projects")

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
  agent_type=context.agent_type.value if hasattr(context.agent_type,'value') else str(context.agent_type)
  executor=self._create_executor(context)
  sequences=get_mock_skill_sequences(agent_type)
  yield {
   "type":"log",
   "data":{
    "level":"info",
    "message":f"MockSkill Agent開始: {agent_type} (シーケンス数: {len(sequences)})",
    "timestamp":datetime.now().isoformat()
   }
  }
  yield {
   "type":"progress",
   "data":{"progress":5,"current_task":"AI API接続中"}
  }
  await asyncio.sleep(0.3*self._simulation_speed)
  total_steps=len(sequences)
  total_tokens=0
  final_content=""
  skill_history=[]
  for step_idx,step in enumerate(sequences):
   step_progress=10+int((step_idx/max(total_steps,1))*75)
   content=step.get("content","")
   yield {
    "type":"log",
    "data":{
     "level":"info",
     "message":f"AI応答受信 (ステップ {step_idx+1}/{total_steps})",
     "timestamp":datetime.now().isoformat()
    }
   }
   step_tokens=200+len(content)*2
   total_tokens+=step_tokens
   yield {
    "type":"tokens",
    "data":{"count":step_tokens}
   }
   tool_calls=self._extract_tool_calls(content)
   if tool_calls:
    yield {
     "type":"progress",
     "data":{"progress":step_progress,"current_task":f"スキル実行中: {', '.join([tc.name for tc in tool_calls])}"}
    }
    yield {
     "type":"log",
     "data":{
      "level":"info",
      "message":f"ツール呼び出し: {[tc.name for tc in tool_calls]}",
      "timestamp":datetime.now().isoformat()
     }
    }
    for tc in tool_calls:
     yield {
      "type":"skill_call",
      "data":{"skill":tc.name,"params":tc.input}
     }
     if tc.name in ASSET_SKILLS:
      result=await self._execute_mock_asset_skill(tc,context,executor)
     else:
      result=await executor.execute_skill(tc.name,**tc.input)
     yield {
      "type":"skill_result",
      "data":{"skill":tc.name,"success":result.success,"output":str(result.output)[:500]}
     }
     skill_history.append({
      "skill":tc.name,
      "params":tc.input,
      "success":result.success,
      "output":str(result.output)[:200],
      "error":result.error,
     })
     await asyncio.sleep(0.2*self._simulation_speed)
   else:
    final_content=content
    yield {
     "type":"progress",
     "data":{"progress":step_progress,"current_task":"AI応答処理中"}
    }
   await asyncio.sleep(0.3*self._simulation_speed)
  if not final_content and sequences:
   final_content=sequences[-1].get("content","")
  output={
   "type":"document",
   "format":"markdown",
   "content":final_content,
   "metadata":{
    "mock":True,
    "mock_skill_mode":True,
    "agent_type":agent_type,
    "skill_history":skill_history,
    "total_skill_calls":len(skill_history),
    "generated_at":datetime.now().isoformat(),
   }
  }
  yield {
   "type":"progress",
   "data":{"progress":90,"current_task":"完了処理中"}
  }
  cp_config=get_checkpoint_title_config(agent_type)
  yield {
   "type":"checkpoint",
   "data":{
    "type":cp_config.get("type","review"),
    "title":cp_config.get("title","レビュー依頼"),
    "description":f"{agent_type}エージェントの成果物を確認してください",
    "output":output,
    "skill_history":skill_history,
    "timestamp":datetime.now().isoformat()
   }
  }
  if context.on_checkpoint:
   context.on_checkpoint(cp_config.get("type","review"),{"output":output,"skill_history":skill_history})
  yield {
   "type":"progress",
   "data":{"progress":100,"current_task":"完了"}
  }
  yield {
   "type":"output",
   "data":output
  }
  yield {
   "type":"log",
   "data":{
    "level":"info",
    "message":f"MockSkill Agent完了 (スキル実行: {len(skill_history)}回, トークン: {total_tokens})",
    "timestamp":datetime.now().isoformat()
   }
  }

 def _create_executor(self,context:AgentContext)->SkillExecutor:
  agent_type=context.agent_type.value if hasattr(context.agent_type,'value') else str(context.agent_type)
  return create_skill_executor(
   project_id=context.project_id,
   agent_id=context.agent_id,
   agent_type=agent_type,
   working_dir=self._working_dir,
  )

 def _extract_tool_calls(self,content:str)->List[MockToolCall]:
  pattern=r'```tool_call\s*\n?(.*?)\n?```'
  matches=re.findall(pattern,content,re.DOTALL)
  tool_calls=[]
  for i,match in enumerate(matches):
   try:
    data=json.loads(match.strip())
    tool_calls.append(MockToolCall(
     id=f"mock_tc_{i}",
     name=data.get("name",""),
     input=data.get("input",{}),
    ))
   except json.JSONDecodeError:
    continue
  return tool_calls

 async def _execute_mock_asset_skill(self,tc:MockToolCall,context:AgentContext,executor:SkillExecutor)->SkillResult:
  output_dir=executor.config.working_dir
  if tc.name=="image_generate":
   return await self._generate_placeholder_image(tc.input,output_dir)
  elif tc.name=="bgm_generate":
   return self._generate_placeholder_audio(tc.input,output_dir,"bgm","wav")
  elif tc.name=="sfx_generate":
   return self._generate_placeholder_audio(tc.input,output_dir,"sfx","wav")
  elif tc.name=="voice_generate":
   return self._generate_placeholder_audio(tc.input,output_dir,"voice","wav")
  return SkillResult(success=False,error=f"Unknown asset skill: {tc.name}")

 async def _generate_placeholder_image(self,params:Dict[str,Any],output_dir:str)->SkillResult:
  prompt=params.get("prompt","placeholder")
  width=params.get("width",512)
  height=params.get("height",512)
  output_path=params.get("output_path")
  style=params.get("style","")
  if not output_path:
   safe_name=re.sub(r'[^\w\-]','_',prompt[:30])
   output_path=f"assets/images/{safe_name}.png"
  if not os.path.isabs(output_path):
   full_path=os.path.join(output_dir,output_path)
  else:
   full_path=output_path
  os.makedirs(os.path.dirname(full_path),exist_ok=True)
  png_data=self._create_minimal_png(width,height,prompt,style)
  await asyncio.to_thread(self._write_binary,full_path,png_data)
  return SkillResult(
   success=True,
   output=f"画像生成完了（モック）: {output_path} ({width}x{height})",
   metadata={
    "path":full_path,
    "prompt":prompt,
    "width":width,
    "height":height,
    "style":style,
    "mock":True,
   }
  )

 def _generate_placeholder_audio(self,params:Dict[str,Any],output_dir:str,audio_type:str,ext:str)->SkillResult:
  prompt=params.get("prompt","") or params.get("text","")
  duration=params.get("duration",3.0)
  output_path=params.get("output_path")
  if not output_path:
   safe_name=re.sub(r'[^\w\-]','_',prompt[:30])
   output_path=f"assets/audio/{audio_type}_{safe_name}.{ext}"
  if not os.path.isabs(output_path):
   full_path=os.path.join(output_dir,output_path)
  else:
   full_path=output_path
  os.makedirs(os.path.dirname(full_path),exist_ok=True)
  wav_data=self._create_silent_wav(duration)
  self._write_binary(full_path,wav_data)
  return SkillResult(
   success=True,
   output=f"{audio_type}生成完了（モック）: {output_path} ({duration}秒)",
   metadata={
    "path":full_path,
    "prompt":prompt,
    "duration":duration,
    "audio_type":audio_type,
    "mock":True,
   }
  )

 def _create_minimal_png(self,width:int,height:int,prompt:str,style:str)->bytes:
  color_map={
   "pixel_art":(100,180,100),
   "anime":(180,130,200),
   "realistic":(130,160,200),
   "cartoon":(200,180,100),
  }
  r,g,b=color_map.get(style,(180,170,150))
  raw_data=b""
  for y in range(height):
   raw_data+=b'\x00'
   for x in range(width):
    raw_data+=bytes([r,g,b])
  def png_chunk(chunk_type:bytes,data:bytes)->bytes:
   chunk=chunk_type+data
   crc=zlib.crc32(chunk)&0xffffffff
   return struct.pack(">I",len(data))+chunk+struct.pack(">I",crc)
  sig=b'\x89PNG\r\n\x1a\n'
  ihdr=struct.pack(">IIBBBBB",width,height,8,2,0,0,0)
  compressed=zlib.compress(raw_data)
  return sig+png_chunk(b'IHDR',ihdr)+png_chunk(b'IDAT',compressed)+png_chunk(b'IEND',b'')

 def _create_silent_wav(self,duration:float)->bytes:
  sample_rate=22050
  num_samples=int(sample_rate*duration)
  data_size=num_samples*2
  header=struct.pack(
   '<4sI4s4sIHHIIHH4sI',
   b'RIFF',36+data_size,b'WAVE',
   b'fmt ',16,1,1,sample_rate,sample_rate*2,2,16,
   b'data',data_size
  )
  return header+b'\x00'*data_size

 def _write_binary(self,path:str,data:bytes)->None:
  with open(path,"wb") as f:
   f.write(data)

 def get_supported_agents(self)->List[AgentType]:
  return list(AgentType)

 def validate_context(self,context:AgentContext)->bool:
  return True
