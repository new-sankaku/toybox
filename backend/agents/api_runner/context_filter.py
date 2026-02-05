"""
Context Filter Module

コンテキストポリシーに基づく出力フィルタリングを担当
"""

from typing import Any,Dict,Optional,TYPE_CHECKING

from config_loaders.workflow_config import get_context_policy_settings
from middleware.logger import get_logger

if TYPE_CHECKING:
    from ..base import AgentContext


class ContextFilter:
    def __init__(self,get_project_context_policy_func):
        self._get_project_context_policy=get_project_context_policy_func

    def filter_outputs_by_policy(
        self,
        outputs:Dict[str,Any],
        policy:Dict[str,Any],
        context:Optional["AgentContext"]=None,
    )->Dict[str,Any]:
        if not policy:
            return outputs
        settings=self._get_project_context_policy(context)
        summary_max=settings.get("summary_max_length",10000)
        auto_downgrade=settings.get("auto_downgrade_threshold",15000)
        filtered={}
        for agent_key,output in outputs.items():
            if agent_key.endswith("_previous_attempt"):
                continue
            agent_policy=policy.get(agent_key,{"level":"full"})
            if isinstance(agent_policy,str):
                agent_policy={"level":agent_policy}
            level=agent_policy.get("level","full")
            focus=agent_policy.get("focus")
            if level=="none":
                continue
            content_str=""
            if isinstance(output,dict) and output.get("content"):
                content_str=str(output["content"])
            if level=="full" and content_str and len(content_str)>auto_downgrade:
                get_logger().info(
                    f"context auto-downgrade: {agent_key} ({len(content_str)}文字) full→summary"
                )
                level="summary"
            if focus and content_str:
                from services.summary_service import get_summary_service

                focused=get_summary_service().generate_focused_extraction(
                    content_str,agent_key,focus
                )
                filtered[agent_key]={"content":focused,"focus":focus}
            elif level=="summary":
                if isinstance(output,dict) and output.get("summary"):
                    filtered[agent_key]={"content":output["summary"]}
                elif content_str:
                    if len(content_str)>summary_max:
                        filtered[agent_key]={
                            "content":content_str[:summary_max]+"\n\n（以降省略）"
                        }
                    else:
                        filtered[agent_key]=output
                else:
                    filtered[agent_key]=output
            else:
                filtered[agent_key]=output
        return filtered

    def format_previous_outputs(self,outputs:Dict[str,Any])->str:
        if not outputs:
            return"（なし）"
        import json

        structured={}
        for agent,output in outputs.items():
            if isinstance(output,dict) and"content" in output:
                structured[agent]={"content":output["content"]}
                if output.get("focus"):
                    structured[agent]["extraction_focus"]=output["focus"]
            else:
                structured[agent]={"content":str(output)}
        return f"```json\n{json.dumps(structured, ensure_ascii=False, indent=1)}\n```"

    def extract_summary(self,content:str,max_length:int=0)->str:
        if max_length<=0:
            settings=get_context_policy_settings()
            max_length=settings.get("summary_max_length",10000)
        if not content:
            return""
        import re
        import json

        json_match=re.search(r"```json\s*([\s\S]*?)\s*```",content)
        if json_match:
            try:
                data=json.loads(json_match.group(1))
                full_json=json.dumps(data,ensure_ascii=False)
                if len(full_json)<=max_length:
                    return full_json
                exclude_keys={
                    "reasoning",
                    "thinking",
                    "explanation",
                    "details",
                    "verbose",
                    "raw",
                }
                filtered={k:v for k,v in data.items() if k not in exclude_keys}
                return json.dumps(filtered,ensure_ascii=False)[:max_length]
            except (json.JSONDecodeError,AttributeError):
                pass
        headers=re.findall(r"^#{1,3}\s+(.+)$",content,re.MULTILINE)
        if headers:
            header_summary="# 構成\n"+"\n".join(f"- {h}" for h in headers[:20])
            first_section=content[:500]
            summary=f"{first_section}\n\n{header_summary}"
            return summary[:max_length]
        return content[:max_length]
