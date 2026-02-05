"""
Tool Call Parser Module

ツール呼び出しの抽出・結果フォーマットを担当
"""

import json
import re
from typing import Any,Dict,List,Optional

from skills import SkillResult
from .types import ToolCall


class ToolCallParser:
    def __init__(self,tool_result_max:int=5000):
        self._tool_result_max=tool_result_max

    def extract_tool_calls(
        self,content:str,native_tool_calls:Optional[List[Dict]]=None
    )->List[ToolCall]:
        if native_tool_calls:
            tool_calls=[]
            for tc in native_tool_calls:
                args=tc.get("arguments","{}")
                if isinstance(args,str):
                    try:
                        parsed_args=json.loads(args)
                    except json.JSONDecodeError:
                        parsed_args={}
                else:
                    parsed_args=args
                tool_calls.append(
                    ToolCall(
                        id=tc.get("id",f"tc_{len(tool_calls)}"),
                        name=tc.get("name",""),
                        input=parsed_args,
                    )
                )
            return tool_calls
        pattern=r"```tool_call\s*\n?(.*?)\n?```"
        matches=re.findall(pattern,content,re.DOTALL)
        tool_calls=[]
        for i,match in enumerate(matches):
            try:
                data=json.loads(match.strip())
                tool_calls.append(
                    ToolCall(
                        id=f"tc_{i}",
                        name=data.get("name",""),
                        input=data.get("input",{}),
                    )
                )
            except json.JSONDecodeError:
                continue
        return tool_calls

    def format_tool_result(self,tc:ToolCall,result:SkillResult)->str:
        if result.success:
            output=result.output
            if isinstance(output,(dict,list)):
                output=json.dumps(output,ensure_ascii=False,indent=2)
            return f"""[ツール実行結果: {tc.name}]
成功:はい
出力:
{str(output)[:self._tool_result_max]}"""
        else:
            return f"""[ツール実行結果: {tc.name}]
成功:いいえ
エラー:{result.error}"""

    def format_tool_result_native(
        self,tc:ToolCall,result:SkillResult
    )->Dict[str,Any]:
        if result.success:
            output=result.output
            if isinstance(output,(dict,list)):
                content=json.dumps(output,ensure_ascii=False,indent=2)
            else:
                content=str(output)[:self._tool_result_max]
        else:
            content=f"Error: {result.error}"
        return {"role":"tool","tool_call_id":tc.id,"content":content}

    def convert_to_openai_tools(self,skill_schemas:List[Dict])->List[Dict[str,Any]]:
        tools=[]
        for s in skill_schemas:
            tools.append(
                {
                    "type":"function",
                    "function":{
                        "name":s["name"],
                        "description":s["description"],
                        "parameters":s.get(
                            "input_schema",{"type":"object","properties":{}}
                        ),
                    },
                }
            )
        return tools
