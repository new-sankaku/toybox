import re
import json
from typing import Dict,Any,List,Optional
from dataclasses import dataclass

from config_loader import (
 load_principles_for_agent,
 get_principle_settings,
 get_agents_config,
 get_output_requirements,
)
from middleware.logger import get_logger


def _extract_rubrics(principles_text:str)->str:
 if not principles_text:
  return""
 lines=principles_text.split("\n")
 result=[]
 in_rubric=False
 current_title=""
 for line in lines:
  if line.startswith("# 原則:"):
   current_title=line
   continue
  if line.strip()=="## 評価ルーブリック":
   in_rubric=True
   if current_title:
    result.append(current_title)
    current_title=""
   result.append(line)
   continue
  if in_rubric:
   if line.startswith("## ") and line.strip()!="## 評価ルーブリック":
    in_rubric=False
   else:
    result.append(line)
    continue
 return"\n".join(result)


def _build_evaluation_prompt(output_text:str,rubrics:str)->tuple:
 system="""あなたはゲーム開発の品質評価の専門家です。
与えられた出力をルーブリックに基づいて評価し、JSON形式で結果を返してください。"""

 user=f"""## 評価対象の出力
{output_text[:8000]}

## 評価ルーブリック
{rubrics}

## 指示
上記ルーブリックの各観点について1-5のスコアで評価してください。
以下のJSON形式で回答してください。他のテキストは不要です。

```json
{{
  "scores":{{"観点名":スコア数値}},
  "average_score":平均スコア数値,
  "failed_criteria":["スコア2以下の観点名"],
  "improvement_suggestions":["改善提案"],
  "strengths":["良かった点"]
}}
```"""
 return system,user


class PrincipleBasedQualityEvaluator:
 def __init__(self):
  self._settings=get_principle_settings()

 async def evaluate(self,output:Dict[str,Any],agent_type:str,project_id:Optional[str]=None)->Dict[str,Any]:
  from .api_runner import QualityCheckResult
  content=output.get("content","")

  rule_result=self._rule_based_check(content,agent_type)
  if not rule_result["passed"]:
   return QualityCheckResult(
    passed=False,
    issues=rule_result["issues"],
    score=rule_result["score"],
    retry_needed=True,
    failed_criteria=rule_result.get("failed_criteria",[]),
    improvement_suggestions=rule_result.get("issues",[]),
   )

  principles_text=load_principles_for_agent(agent_type)
  if not principles_text:
   return QualityCheckResult(passed=True,score=1.0)

  rubrics=_extract_rubrics(principles_text)
  if not rubrics.strip():
   return QualityCheckResult(passed=True,score=1.0)

  try:
   usage_cat=self._settings.get("quality_check_usage_category","llm_low")
   llm_result=await self._llm_evaluate(str(content),rubrics,project_id,usage_cat)
   threshold=self._settings.get("quality_threshold",0.6)
   normalized=llm_result.get("average_score",3.0)/5.0

   escalation=self._settings.get("escalation",{})
   if escalation.get("enabled",False):
    tier2_min=escalation.get("tier2_score_min",0.5)
    tier2_max=escalation.get("tier2_score_max",0.7)
    if tier2_min<=normalized<=tier2_max:
     tier2_cat=escalation.get("tier2_usage_category","llm_mid")
     get_logger().info(f"QualityEvaluator: スコア{normalized:.2f}で境界帯、Tier2({tier2_cat})で再評価")
     llm_result=await self._llm_evaluate(str(content),rubrics,project_id,tier2_cat)
     normalized=llm_result.get("average_score",3.0)/5.0

   passed=normalized>=threshold
   return QualityCheckResult(
    passed=passed,
    issues=llm_result.get("improvement_suggestions",[]) if not passed else [],
    score=normalized,
    retry_needed=not passed,
    failed_criteria=llm_result.get("failed_criteria",[]),
    improvement_suggestions=llm_result.get("improvement_suggestions",[]),
    strengths=llm_result.get("strengths",[]),
   )
  except Exception as e:
   get_logger().error(f"QualityEvaluator: LLM評価失敗、ルールベースにフォールバック: {e}",exc_info=True)
   return QualityCheckResult(passed=True,score=0.8)

 def _rule_based_check(self,content,agent_type:str="")->Dict[str,Any]:
  issues=[]
  score=1.0
  content_str=str(content) if content else""

  reqs=get_output_requirements(agent_type) if agent_type else {"min_length":200}
  min_length=reqs.get("min_length",200)

  if not content or len(content_str)<min_length:
   issues.append(f"出力内容が不十分です（{len(content_str)}文字、最低{min_length}文字必要）")
   score-=0.3

  required_sections=reqs.get("required_sections",[])
  if required_sections and content_str:
   missing=[s for s in required_sections if s not in content_str]
   if missing:
    issues.append(f"必須セクションが不足: {', '.join(missing)}")
    score-=0.1*len(missing)

  if"```json" in content_str:
   json_match=re.search(r'```json\s*([\s\S]*?)\s*```',content_str)
   if json_match:
    try:
     json.loads(json_match.group(1))
    except json.JSONDecodeError:
     issues.append("JSON形式が不正です")
     score-=0.2

  score=max(score,0.0)
  passed=score>=0.7 and len(issues)==0
  return {"passed":passed,"issues":issues,"score":score,"failed_criteria":[i for i in issues]}

 async def _llm_evaluate(self,output_text:str,rubrics:str,project_id:Optional[str]=None,usage_category:str="llm_low")->Dict[str,Any]:
  from providers.registry import get_provider
  from providers.base import AIProviderConfig
  from services.llm_resolver import resolve_llm_for_project,resolve_with_env_key

  resolved=resolve_llm_for_project(project_id,usage_category)
  provider_id=resolved["provider"]
  model=resolved["model"]

  if not provider_id or not model:
   raise ValueError(f"LLM config not resolved: usage_category={usage_category} project_id={project_id}")

  max_tokens=self._settings.get("quality_check_max_tokens",2048)
  api_key=resolve_with_env_key(provider_id)
  config=AIProviderConfig(api_key=api_key,timeout=60)
  provider=get_provider(provider_id,config)
  if provider is None:
   raise ValueError(f"Quality check provider not available: {provider_id}")

  system_prompt,user_prompt=_build_evaluation_prompt(output_text,rubrics)

  result=await provider.generate(
   prompt=user_prompt,
   model=model,
   max_tokens=max_tokens,
   system_prompt=system_prompt,
  )

  response_text=result.get("content","") if isinstance(result,dict) else str(result)
  return self._parse_evaluation_response(response_text)

 def _parse_evaluation_response(self,response:str)->Dict[str,Any]:
  json_match=re.search(r'```json\s*([\s\S]*?)\s*```',response)
  if json_match:
   try:
    return json.loads(json_match.group(1))
   except json.JSONDecodeError:
    pass
  try:
   return json.loads(response)
  except json.JSONDecodeError:
   pass
  get_logger().warning("QualityEvaluator: LLM応答のJSON解析失敗")
  return {"average_score":3.0,"failed_criteria":[],"improvement_suggestions":[],"strengths":[]}


_evaluator_instance:Optional[PrincipleBasedQualityEvaluator]=None


def get_quality_evaluator()->PrincipleBasedQualityEvaluator:
 global _evaluator_instance
 if _evaluator_instance is None:
  _evaluator_instance=PrincipleBasedQualityEvaluator()
 return _evaluator_instance
