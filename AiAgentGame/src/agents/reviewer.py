"""
Reviewer Agent - Code review and quality assessment.
"""

from typing import Dict, Any
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from ..core.state import GameState
from ..core.llm import get_llm_for_agent
from ..utils.logger import get_logger
from ..dashboard.tracker import tracker, AgentStatus

logger = get_logger()


class ReviewerAgent:
    """
    Reviewer Agent performs code review.

    Responsibilities:
    - Check code quality
    - Identify potential issues
    - Suggest improvements
    - Approve or request changes
    """

    def __init__(self):
        """Initialize the Reviewer Agent."""
        self.llm = get_llm_for_agent("planner")
        self.parser = JsonOutputParser()

    def run(self, state: GameState) -> Dict[str, Any]:
        """
        Execute review phase.

        Args:
            state: Current game state

        Returns:
            Dictionary with review_comments and approval_status
        """
        code_files = state.get("code_files", {})
        game_spec = state.get("game_spec", {})

        if not code_files:
            logger.warning("レビュー対象のコードなし")
            tracker.agent_complete("reviewer", "レビュー対象のコードなし")
            return {"review_comments": [], "approval_status": True}

        tracker.agent_start("reviewer", f"レビュー開始: {len(code_files)}ファイル")

        logger.info(f"レビュー中: {len(code_files)}ファイル")

        main_file = None
        main_content = None

        for filename, content in code_files.items():
            if filename.endswith('.py'):
                main_file = filename
                main_content = content
                break

        if not main_file:
            return {"review_comments": [], "approval_status": True}

        review_comments = self._review_code(main_file, main_content, game_spec)

        critical_count = len([c for c in review_comments if c.get("severity") == "error"])

        if critical_count > 0:
            logger.warning(f"レビュー不合格: 重大な問題{critical_count}件")
            approval_status = False
            tracker.agent_complete("reviewer", f"レビュー不合格: 重大な問題{critical_count}件", {
                "files_reviewed": len(code_files),
                "comments": len(review_comments),
                "critical_count": critical_count,
                "approved": False
            })
        else:
            logger.info(f"レビュー合格: 提案{len(review_comments)}件")
            approval_status = True
            tracker.agent_complete("reviewer", f"レビュー合格: 提案{len(review_comments)}件", {
                "files_reviewed": len(code_files),
                "comments": len(review_comments),
                "critical_count": 0,
                "approved": True
            })

        return {
            "review_comments": review_comments,
            "approval_status": approval_status
        }

    def _review_code(self, filename: str, code: str, game_spec: Dict[str, Any]) -> list:
        """Review code and return comments."""

        prompt = ChatPromptTemplate.from_template("""You are a code reviewer.
Review the following game code for quality and correctness.

Game Specification:
Title: {title}
Mechanics: {mechanics}

Code ({filename}):
```python
{code}
```

Provide a review with the following format:
{{
  "comments": [
    {{
      "severity": "error" or "warning" or "info",
      "line": line_number (if applicable, else null),
      "message": "description of the issue",
      "suggestion": "how to fix it"
    }}
  ]
}}

Focus on:
1. Critical errors that would prevent the game from running
2. Missing game mechanics from the specification
3. Code quality issues

Return ONLY the JSON, no additional text.""")

        chain = prompt | self.llm | self.parser

        try:
            result = chain.invoke({
                "title": game_spec.get("title", "Unknown"),
                "mechanics": ", ".join(game_spec.get("mechanics", [])),
                "filename": filename,
                "code": code[:2000]
            })

            comments = result.get("comments", [])

            for comment in comments:
                severity = comment.get("severity", "info")
                message = comment.get("message", "")
                level = severity.upper()
                logger.debug(f"[{level}] {message}")

            return comments

        except Exception as e:
            import traceback
            logger.error(f"レビュー失敗: {e}")
            logger.error(f"詳細: {traceback.format_exc()}")
            raise RuntimeError(f"レビューフェーズでエラーが発生しました: {e}") from e
