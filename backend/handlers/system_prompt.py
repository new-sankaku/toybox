from flask import Flask,jsonify,request
from services.project_service import ProjectService
from services.agent_service import AgentService
from services.trace_service import TraceService
from middleware.error_handler import NotFoundError
from config_loaders import get_config_dir
from config_loaders.prompt_config import load_prompt,_prompt_cache
from config_loaders.principle_config import (
 load_principles_for_agent,
 get_agent_principles,
)
from middleware.logger import get_logger

def register_system_prompt_routes(app:Flask,project_service:ProjectService,agent_service:AgentService,trace_service:TraceService):

 @app.route('/api/agents/<agent_id>/system-prompt',methods=['GET'])
 def get_agent_system_prompt(agent_id:str):
  agent=agent_service.get_agent(agent_id)
  if not agent:
   raise NotFoundError("Agent",agent_id)

  agent_type=agent.get("type","")
  project_id=agent.get("projectId")
  project=project_service.get_project(project_id) if project_id else None
  project_concept=project.get("concept","") if project else""

  system_components=[]
  user_components=[]
  order=0

  system_prompt_parts=[]
  system_prompt_parts.append(f"あなたはゲーム開発の専門家です。\n\n## プロジェクト情報\n{project_concept or'（未定義）'}")
  system_components.append({
   "label":"プロジェクト情報",
   "content":f"あなたはゲーム開発の専門家です。\n\n## プロジェクト情報\n{project_concept or'（未定義）'}",
   "source":"api_runner.py:_build_prompt",
   "order":order,
  })
  order+=1

  advanced_settings=project.get("advancedSettings",{}) if project else{}
  enabled_principles=advanced_settings.get("enabledPrinciples")
  principles_text=load_principles_for_agent(agent_type,enabled_principles)
  principle_names=get_agent_principles(agent_type)
  if principles_text:
   system_prompt_parts.append(f"\n\n## ゲームデザイン原則\n以下の原則に従って作業し、自己評価してください。\n{principles_text}")
   principles_dir=get_config_dir()/"principles"
   sources=", ".join([str(principles_dir/f"{p}.md") for p in principle_names])
   system_components.append({
    "label":"ゲームデザイン原則",
    "content":f"## ゲームデザイン原則\n以下の原則に従って作業し、自己評価してください。\n{principles_text}",
    "source":sources,
    "order":order,
   })
   order+=1

  try:
   from services.agent_speech_service import get_agent_speech_service
   comment_instruction=get_agent_speech_service().get_comment_instruction(agent_type)
   if comment_instruction:
    system_prompt_parts.append(f"\n\n## 一言コメント\n{comment_instruction}")
    system_components.append({
     "label":"一言コメント指示",
     "content":f"## 一言コメント\n{comment_instruction}",
     "source":"agent_speech_service",
     "order":order,
    })
    order+=1
  except Exception as e:
   get_logger().warning(f"Failed to load comment instruction for {agent_type}: {e}")

  system_prompt="\n".join(system_prompt_parts)

  user_order=0
  user_components.append({
   "label":"参照データ",
   "content":"## 参照データ\n（実行時に前のエージェント出力が挿入される）",
   "source":"api_runner.py:_build_prompt (previous_outputs)",
   "order":user_order,
  })
  user_order+=1

  user_components.append({
   "label":"品質チェック結果",
   "content":"## 前回の品質チェック結果\n（リトライ時のみ挿入される）",
   "source":"api_runner.py:_build_prompt (retry_feedback)",
   "order":user_order,
  })
  user_order+=1

  metadata=agent.get("metadata",{})
  assigned_task=metadata.get("assigned_task","")
  if assigned_task:
   user_components.append({
    "label":"Leaderからの割当タスク",
    "content":f"## あなたへの指示（Leader からの割当タスク）\n{assigned_task}",
    "source":"agent.metadata.assigned_task",
    "order":user_order,
   })
   user_order+=1

  base_prompt=load_prompt(agent_type)
  prompts_dir=get_config_dir()/"prompts"
  prompt_file=prompts_dir/f"{agent_type}.md"
  base_prompt_file=str(prompt_file) if prompt_file.exists() else None
  if base_prompt:
   user_components.append({
    "label":"ベースプロンプト",
    "content":base_prompt,
    "source":base_prompt_file or"prompts/_default.md",
    "order":user_order,
   })
   user_order+=1

  has_quality_feedback=False
  traces=trace_service.get_traces_by_agent(agent_id)
  if traces:
   for trace in traces:
    prompt_sent=trace.get("promptSent","") or""
    if"前回の品質チェック結果" in prompt_sent:
     has_quality_feedback=True
     break

  response={
   "agentId":agent_id,
   "agentType":agent_type,
   "systemPrompt":system_prompt,
   "systemComponents":[{
    "label":c["label"],
    "content":c["content"],
    "source":c.get("source"),
    "order":c["order"],
   } for c in system_components],
   "userPrompt":None,
   "userComponents":[{
    "label":c["label"],
    "content":c["content"],
    "source":c.get("source"),
    "order":c["order"],
   } for c in user_components],
   "principles":principle_names,
   "basePromptFile":base_prompt_file,
   "hasQualityFeedback":has_quality_feedback,
  }

  return jsonify(response)

 @app.route('/api/agents/<agent_id>/system-prompt/project',methods=['PUT'])
 def save_agent_prompt_to_project(agent_id:str):
  agent=agent_service.get_agent(agent_id)
  if not agent:
   raise NotFoundError("Agent",agent_id)

  data=request.get_json() or {}
  content=data.get("content","")
  if not content:
   return jsonify({"error":"content is required"}),400

  project_id=agent.get("projectId")
  if not project_id:
   return jsonify({"error":"Agent has no project"}),400

  project=project_service.get_project(project_id)
  if not project:
   return jsonify({"error":"Project not found"}),404

  agent_type=agent.get("type","")
  project_settings=project.get("settings",{}) or {}
  prompt_overrides=project_settings.get("promptOverrides",{}) or {}
  prompt_overrides[agent_type]=content
  project_settings["promptOverrides"]=prompt_overrides
  project_service.update_project(project_id,{"settings":project_settings})

  get_logger().info(f"Prompt saved to project {project_id} for agent type {agent_type}")
  return jsonify({"status":"saved","scope":"project","agentType":agent_type})

 @app.route('/api/agents/<agent_id>/system-prompt/global',methods=['PUT'])
 def save_agent_prompt_to_global(agent_id:str):
  agent=agent_service.get_agent(agent_id)
  if not agent:
   raise NotFoundError("Agent",agent_id)

  data=request.get_json() or {}
  content=data.get("content","")
  if not content:
   return jsonify({"error":"content is required"}),400

  agent_type=agent.get("type","")
  prompts_dir=get_config_dir()/"prompts"
  prompts_dir.mkdir(parents=True,exist_ok=True)
  prompt_file=prompts_dir/f"{agent_type}.md"

  with open(prompt_file,"w",encoding="utf-8") as f:
   f.write(content)

  if agent_type in _prompt_cache:
   _prompt_cache[agent_type]=content

  get_logger().info(f"Prompt saved globally for agent type {agent_type} to {prompt_file}")
  return jsonify({"status":"saved","scope":"global","agentType":agent_type,"file":str(prompt_file)})
