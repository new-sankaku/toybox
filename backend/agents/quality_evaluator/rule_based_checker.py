"""
Rule-Based Checker Module

ルールベースの品質チェックを行う
"""

import re
import json
from typing import Dict,Any

from config_loaders.agent_config import get_output_requirements


class RuleBasedChecker:
    """ルールベースの品質チェッカー"""

    def check(self,content:Any,agent_type:str="")->Dict[str,Any]:
        """
        ルールベースの品質チェックを実行

        Args:
            content:チェック対象のコンテンツ
            agent_type:エージェント種別

        Returns:
            チェック結果を含む辞書
        """
        issues:list[str]=[]
        score=1.0
        content_str=str(content) if content else""

        reqs=get_output_requirements(agent_type) if agent_type else {"min_length":200}
        min_length=reqs.get("min_length",200)

        length_result=self._check_content_length(content_str,min_length)
        if length_result:
            issues.append(length_result)
            score-=0.3

        required_sections=reqs.get("required_sections",[])
        sections_result=self._check_required_sections(content_str,required_sections)
        if sections_result:
            issues.append(sections_result["message"])
            score-=0.1*sections_result["missing_count"]

        json_result=self._check_json_validity(content_str)
        if json_result:
            issues.append(json_result)
            score-=0.2

        score=max(score,0.0)
        passed=score>=0.7 and len(issues)==0

        return {
            "passed":passed,
            "issues":issues,
            "score":score,
            "failed_criteria":list(issues),
        }

    def _check_content_length(self,content_str:str,min_length:int)->str|None:
        """コンテンツ長のチェック"""
        if not content_str or len(content_str)<min_length:
            return f"出力内容が不十分です（{len(content_str)}文字、最低{min_length}文字必要）"
        return None

    def _check_required_sections(
        self,content_str:str,required_sections:list[str]
    )->Dict[str,Any]|None:
        """必須セクションのチェック"""
        if not required_sections or not content_str:
            return None
        missing=[s for s in required_sections if s not in content_str]
        if missing:
            return {
                "message":f"必須セクションが不足: {', '.join(missing)}",
                "missing_count":len(missing),
            }
        return None

    def _check_json_validity(self,content_str:str)->str|None:
        """JSON形式の妥当性チェック"""
        if"```json" not in content_str:
            return None
        json_match=re.search(r"```json\s*([\s\S]*?)\s*```",content_str)
        if json_match:
            try:
                json.loads(json_match.group(1))
            except json.JSONDecodeError:
                return"JSON形式が不正です"
        return None
