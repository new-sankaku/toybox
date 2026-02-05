"""
LLM Evaluator Module

LLMを使用した品質評価を行う
"""

import re
import json
from typing import Dict,Any,Optional,Tuple

from middleware.logger import get_logger


def extract_rubrics(principles_text:str)->str:
    """
    原則テキストから評価ルーブリックを抽出

    Args:
        principles_text:原則テキスト

    Returns:
        ルーブリック部分のテキスト
    """
    if not principles_text:
        return""
    lines=principles_text.split("\n")
    result:list[str]=[]
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


class LLMEvaluator:
    """LLMを使用した品質評価器"""

    def __init__(self,max_tokens:int=2048):
        self._max_tokens=max_tokens

    async def evaluate(
        self,
        output_text:str,
        rubrics:str,
        project_id:Optional[str]=None,
        usage_category:str="llm_low",
    )->Dict[str,Any]:
        """
        LLMを使用して品質評価を実行

        Args:
            output_text:評価対象テキスト
            rubrics:評価ルーブリック
            project_id:プロジェクトID
            usage_category:使用カテゴリ

        Returns:
            評価結果を含む辞書
        """
        from providers.registry import get_provider
        from providers.base import AIProviderConfig
        from services.llm_resolver import resolve_llm_for_project,resolve_with_env_key

        resolved=resolve_llm_for_project(project_id,usage_category)
        provider_id=resolved["provider"]
        model=resolved["model"]

        if not provider_id or not model:
            raise ValueError(
                f"LLM config not resolved: usage_category={usage_category} project_id={project_id}"
            )

        api_key=resolve_with_env_key(provider_id)
        config=AIProviderConfig(api_key=api_key,timeout=60)
        provider=get_provider(provider_id,config)
        if provider is None:
            raise ValueError(f"Quality check provider not available: {provider_id}")

        system_prompt,user_prompt=self._build_evaluation_prompt(output_text,rubrics)

        result=await provider.generate(
            prompt=user_prompt,
            model=model,
            max_tokens=self._max_tokens,
            system_prompt=system_prompt,
        )

        response_text=result.get("content","") if isinstance(result,dict) else str(result)
        return self._parse_response(response_text)

    def _build_evaluation_prompt(self,output_text:str,rubrics:str)->Tuple[str,str]:
        """
        評価用プロンプトを構築

        Args:
            output_text:評価対象テキスト
            rubrics:評価ルーブリック

        Returns:
            (システムプロンプト,ユーザープロンプト)のタプル
        """
        system="""あなたはゲーム開発の品質評価の専門家です。
与えられた出力をルーブリックに基づいて評価し、JSON形式で結果を返してください。"""

        user=f"""## 評価対象の出力
{output_text[:8000]}

## 評価ルーブリック
{rubrics}

## 指示
上記ルーブリックの各観点について1-5のスコアで評価してください。
加えて、Hallucination（幻覚）チェックを行ってください:
-出力に含まれる固有名詞・数値・仕様値が、入力コンテキストに存在するか確認する
-入力に存在しない情報が推測で追加されている場合、hallucination_warningsに記載する

以下のJSON形式で回答してください。他のテキストは不要です。

```json
{{
  "scores":{{"観点名":スコア数値}},
  "average_score":平均スコア数値,
  "failed_criteria":["スコア2以下の観点名"],
  "improvement_suggestions":["改善提案"],
  "strengths":["良かった点"],
  "hallucination_warnings":["入力に根拠のない情報があれば記載"]
}}
```"""
        return system,user

    def _parse_response(self,response:str)->Dict[str,Any]:
        """
        LLMレスポンスをパース

        Args:
            response:LLMからのレスポンステキスト

        Returns:
            パースされた評価結果
        """
        json_match=re.search(r"```json\s*([\s\S]*?)\s*```",response)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass
        get_logger().warning("LLMEvaluator: LLM応答のJSON解析失敗")
        return {
            "average_score":3.0,
            "failed_criteria":[],
            "improvement_suggestions":[],
            "strengths":[],
        }
