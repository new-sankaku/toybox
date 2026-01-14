"""
Reviewer Agent - Code review and quality assessment.
"""

from typing import Dict, Any
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from ..core.state import GameState
from ..core.llm import get_llm_for_agent


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
        self.llm = get_llm_for_agent("planner")  # Reuse planner LLM
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
            print("⚠️  No code to review")
            return {"review_comments": [], "approval_status": True}

        print(f"👀 Reviewing {len(code_files)} files")

        # Review main Python file
        main_file = None
        main_content = None

        for filename, content in code_files.items():
            if filename.endswith('.py'):
                main_file = filename
                main_content = content
                break

        if not main_file:
            return {"review_comments": [], "approval_status": True}

        # Perform review
        review_comments = self._review_code(main_file, main_content, game_spec)

        # Count critical issues
        critical_count = len([c for c in review_comments if c.get("severity") == "error"])

        if critical_count > 0:
            print(f"\n❌ Review failed: {critical_count} critical issues")
            approval_status = False
        else:
            print(f"\n✅ Review passed with {len(review_comments)} suggestions")
            approval_status = True

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
                "code": code[:2000]  # Limit code length for review
            })

            comments = result.get("comments", [])

            for comment in comments:
                severity = comment.get("severity", "info")
                message = comment.get("message", "")
                print(f"   {self._get_emoji(severity)} {message}")

            return comments

        except Exception as e:
            print(f"⚠️  Review error: {e}")
            # Return empty comments on error
            return []

    def _get_emoji(self, severity: str) -> str:
        """Get emoji for severity level."""
        return {
            "error": "❌",
            "warning": "⚠️",
            "info": "ℹ️"
        }.get(severity, "•")
