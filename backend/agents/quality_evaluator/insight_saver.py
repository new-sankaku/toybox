"""
Insight Saver Module

品質評価インサイトの保存を担当
"""

from typing import Any,Dict,List,Optional

from middleware.logger import get_logger


class InsightSaver:
    """品質評価インサイトをメモリに保存するクラス"""

    def save(
        self,
        agent_type:str,
        project_id:Optional[str],
        passed:bool,
        llm_result:Dict[str,Any],
        agent_service:Any=None,
    )->None:
        """
        品質インサイトをメモリに保存

        Args:
            agent_type:エージェント種別
            project_id:プロジェクトID
            passed:品質チェックが合格したかどうか
            llm_result:LLM評価結果
            agent_service:エージェントサービス
        """
        if agent_service is None:
            return

        try:
            self._save_failed_criteria(agent_type,project_id,llm_result,agent_service)
            self._save_hallucination_pattern(agent_type,project_id,llm_result,agent_service)
            self._save_improvement_pattern(
                agent_type,project_id,passed,llm_result,agent_service
            )
        except Exception as e:
            get_logger().error(f"QualityEvaluator: メモリ保存失敗: {e}",exc_info=True)

    def _save_failed_criteria(
        self,
        agent_type:str,
        project_id:Optional[str],
        llm_result:Dict[str,Any],
        agent_service:Any,
    )->None:
        """不合格基準をメモリに保存"""
        failed:List[str]=llm_result.get("failed_criteria",[])
        if not failed:
            return
        insight=f"[{agent_type}] 頻出の不合格基準: {', '.join(failed[:5])}"
        agent_service.create_agent_memory(
            category="quality_insight",
            agent_type=agent_type,
            content=insight,
            project_id=project_id,
            source_project_id=project_id,
        )

    def _save_hallucination_pattern(
        self,
        agent_type:str,
        project_id:Optional[str],
        llm_result:Dict[str,Any],
        agent_service:Any,
    )->None:
        """Hallucinationパターンをメモリに保存"""
        hallucinations:List[str]=llm_result.get("hallucination_warnings",[])
        if not hallucinations:
            return
        insight=f"[{agent_type}] Hallucination傾向: {'; '.join(hallucinations[:3])}"
        agent_service.create_agent_memory(
            category="hallucination_pattern",
            agent_type=agent_type,
            content=insight,
            project_id=project_id,
            source_project_id=project_id,
        )

    def _save_improvement_pattern(
        self,
        agent_type:str,
        project_id:Optional[str],
        passed:bool,
        llm_result:Dict[str,Any],
        agent_service:Any,
    )->None:
        """改善パターンをメモリに保存"""
        suggestions:List[str]=llm_result.get("improvement_suggestions",[])
        if not suggestions or passed:
            return
        insight=f"[{agent_type}] 改善ポイント: {'; '.join(suggestions[:3])}"
        agent_service.create_agent_memory(
            category="improvement_pattern",
            agent_type=agent_type,
            content=insight,
            project_id=project_id,
            source_project_id=project_id,
        )
