"""
LangGraph workflow definition for AI Agent Game Creator.
"""

from typing import Literal
from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage

from .state import GameState, Phase
from .feedback import FeedbackManager
from ..utils.logger import get_logger
from ..dashboard.tracker import tracker

logger = get_logger()


class GameCreatorGraph:
    """Main workflow graph for game creation."""

    def __init__(self):
        """Initialize the game creator graph."""
        self.feedback_manager = FeedbackManager()
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph workflow."""
        workflow = StateGraph(GameState)

        # Add nodes
        workflow.add_node("planner", self._planner_node)
        workflow.add_node("coder", self._coder_node)
        workflow.add_node("asset_coordinator", self._asset_coordinator_node)
        workflow.add_node("tester", self._tester_node)
        workflow.add_node("debugger", self._debugger_node)
        workflow.add_node("reviewer", self._reviewer_node)

        # Set entry point
        workflow.set_entry_point("planner")

        # Add conditional edges
        workflow.add_conditional_edges(
            "planner",
            self._route_after_planning,
            {
                "coding": "coder",
                "cancelled": END
            }
        )

        workflow.add_conditional_edges(
            "coder",
            self._route_after_coding,
            {
                "assets": "asset_coordinator",
                "testing": "tester"
            }
        )

        workflow.add_conditional_edges(
            "asset_coordinator",
            self._route_after_assets,
            {
                "testing": "tester"
            }
        )

        workflow.add_conditional_edges(
            "tester",
            self._route_after_testing,
            {
                "debugging": "debugger",
                "review": "reviewer",
                "completed": END
            }
        )

        workflow.add_conditional_edges(
            "debugger",
            self._route_after_debugging,
            {
                "coding": "coder",
                "testing": "tester"
            }
        )

        workflow.add_conditional_edges(
            "reviewer",
            self._route_after_review,
            {
                "coding": "coder",
                "completed": END
            }
        )

        return workflow.compile()

    def _planner_node(self, state: GameState) -> GameState:
        """Planner Agent node - Creates game specification and task list."""
        user_request = state.get("user_request", "不明")
        logger.info("[Planner] 開始")
        tracker.agent_start("planner", f"企画開始: 「{user_request[:30]}...」を分析中")
        tracker.set_phase("planning")

        from ..agents.planner import PlannerAgent

        planner = PlannerAgent()
        tracker.agent_progress("planner", "LLM呼び出し中: ゲームコンセプト・仕様・タスク分解を生成")

        try:
            result = planner.run(state)
        except Exception as e:
            tracker.agent_error("planner", f"計画失敗: {e}")
            tracker.set_phase("error")
            raise

        state["current_phase"] = Phase.PLANNING
        state["game_spec"] = result.get("game_spec")
        state["tasks"] = result.get("tasks", [])
        state["messages"].append({
            "role": "assistant",
            "content": f"Game spec created: {result.get('game_spec', {}).get('title', 'Unknown')}"
        })

        self.feedback_manager.save_status(state)

        game_spec = result.get("game_spec", {})
        tasks = result.get("tasks", [])
        tracker.set_game_spec(game_spec)
        tracker.set_tasks(tasks)

        # Format tasks for frontend
        task_list = [
            {"id": t.id if hasattr(t, 'id') else t.get('id', ''),
             "description": t.description if hasattr(t, 'description') else t.get('description', ''),
             "status": t.status if hasattr(t, 'status') else t.get('status', 'pending'),
             "assigned_agent": t.assigned_agent if hasattr(t, 'assigned_agent') else t.get('assigned_agent', '')}
            for t in tasks
        ]

        # Send complete game spec to frontend
        tracker.agent_complete("planner",
            f"企画完了: 「{game_spec.get('title', '?')}」({game_spec.get('genre', '?')}) - タスク{len(tasks)}件生成", {
            "title": game_spec.get("title"),
            "genre": game_spec.get("genre"),
            "description": game_spec.get("description"),
            "target_platform": game_spec.get("target_platform"),
            "visual_style": game_spec.get("visual_style"),
            "audio_style": game_spec.get("audio_style"),
            "game_spec": game_spec,
            "task_list": task_list,
            "task_count": len(tasks)
        })

        return state

    def _coder_node(self, state: GameState) -> GameState:
        """Coder Agent node - Implements game code."""
        game_spec = state.get("game_spec", {})
        game_title = game_spec.get("title", "不明")
        platform = game_spec.get("target_platform", "pygame")
        logger.info("[Coder] 開始")
        tracker.agent_start("coder", f"コーディング開始: 「{game_title}」を{platform}で実装")
        tracker.set_phase("coding")

        from ..agents.coder import CoderAgent

        coder = CoderAgent()
        tracker.agent_progress("coder", f"LLM呼び出し中: {platform}コード生成 (メインループ・クラス・関数)")
        result = coder.run(state)

        state["current_phase"] = Phase.CODING
        state["code_files"].update(result.get("code_files", {}))
        state["messages"].append({
            "role": "assistant",
            "content": f"Generated {len(result.get('code_files', {}))} code files"
        })

        code_files = result.get("code_files", {})
        file_list = list(code_files.keys())
        file_count = len(file_list)
        total_lines = sum(len(content.split('\n')) for content in code_files.values())
        tracker.set_code_files(file_list)
        tracker.agent_complete("coder",
            f"コード生成完了: {file_count}ファイル ({total_lines}行) - {', '.join(file_list)}", {
            "files": file_count,
            "total_lines": total_lines,
            "file_list": file_list
        })

        return state

    def _asset_coordinator_node(self, state: GameState) -> GameState:
        """Asset Coordinator node - Distributes asset generation tasks."""
        game_spec = state.get("game_spec", {})
        visual_style = game_spec.get("visual_style", "なし")
        audio_style = game_spec.get("audio_style", "なし")
        logger.info("[AssetCoordinator] 開始")
        tracker.agent_start("asset_coordinator",
            f"アセット生成開始: ビジュアル={visual_style}, オーディオ={audio_style}")
        tracker.set_phase("asset_generation")

        from ..agents.asset_coordinator import AssetCoordinatorAgent

        coordinator = AssetCoordinatorAgent()
        tracker.agent_progress("asset_coordinator",
            "アセット生成中: 画像(スプライト/背景/UI)・音声(BGM/SE)を作成")
        result = coordinator.run(state)

        state["current_phase"] = Phase.ASSET_GENERATION
        state["artifacts"].update(result.get("artifacts", {}))
        state["messages"].append({
            "role": "assistant",
            "content": f"Generated {len(result.get('artifacts', {}))} assets"
        })

        artifacts = result.get("artifacts", {})
        asset_count = len(artifacts)
        asset_list = [{"name": k, "type": v.get("type", "unknown") if isinstance(v, dict) else "file"}
                      for k, v in artifacts.items()]

        # Count by type
        image_count = len([a for a in asset_list if a["type"] in ["image", "sprite", "background", "ui"]])
        audio_count = len([a for a in asset_list if a["type"] in ["audio", "bgm", "se", "sound"]])

        tracker.set_assets(asset_list)
        tracker.agent_complete("asset_coordinator",
            f"アセット生成完了: 計{asset_count}件 (画像{image_count}/音声{audio_count}) - {', '.join([a['name'] for a in asset_list[:5]])}", {
            "assets": asset_count,
            "image_count": image_count,
            "audio_count": audio_count,
            "asset_list": asset_list
        })

        return state

    def _tester_node(self, state: GameState) -> GameState:
        """Tester Agent node - Tests the game."""
        code_files = state.get("code_files", {})
        file_list = list(code_files.keys())
        file_count = len(file_list)
        iteration = state.get("iteration", 0)
        logger.info("[Tester] 開始")
        tracker.agent_start("tester",
            f"テスト開始: {file_count}ファイルを検証 (試行{iteration + 1}回目)")
        tracker.set_phase("testing")

        from ..agents.tester import TesterAgent

        tester = TesterAgent()

        # Send test items being checked
        test_items = [
            {"name": "構文チェック", "target": "全ファイル", "status": "running"},
            {"name": "インポート検証", "target": "import文", "status": "pending"},
            {"name": "型チェック", "target": "変数・関数", "status": "pending"},
            {"name": "依存関係", "target": "モジュール", "status": "pending"}
        ]
        tracker.agent_progress("tester",
            f"テスト実行中: {', '.join(file_list)} の構文・インポート・型を検証", {
            "test_items": test_items,
            "files_being_tested": file_list
        })
        result = tester.run(state)

        state["current_phase"] = Phase.TESTING
        state["test_results"] = result.get("test_results")
        state["errors"].extend(result.get("errors", []))
        state["messages"].append({
            "role": "assistant",
            "content": f"Testing completed with {len(result.get('errors', []))} errors"
        })

        errors = result.get("errors", [])
        error_count = len(errors)
        tracker.set_errors(errors)

        if error_count > 0:
            # Format error details
            error_summary = []
            for e in errors[:5]:
                if isinstance(e, dict):
                    error_summary.append(f"{e.get('file', '?')}:{e.get('line', '?')} - {e.get('message', str(e))[:50]}")
                else:
                    error_summary.append(str(e)[:60])

            tracker.agent_complete("tester",
                f"テスト失敗: {error_count}件のエラー検出 - {'; '.join(error_summary[:3])}", {
                "errors": error_count,
                "error_list": errors,
                "test_passed": False,
                "files_tested": file_count
            })
        else:
            tracker.agent_complete("tester",
                f"テスト成功: {file_count}ファイル全て正常 (構文OK/インポートOK)", {
                "errors": 0,
                "error_list": [],
                "test_passed": True,
                "files_tested": file_count
            })

        return state

    def _debugger_node(self, state: GameState) -> GameState:
        """Debugger Agent node - Fixes bugs."""
        errors = state.get("errors", [])
        error_count = len(errors)
        iteration = state.get("iteration", 0) + 1
        logger.info("[Debugger] 開始")

        # Get first few error messages for display
        error_preview = []
        for e in errors[:3]:
            if isinstance(e, dict):
                error_preview.append(f"{e.get('file', '?')}:{e.get('line', '?')}")
            else:
                error_preview.append(str(e)[:30])

        tracker.agent_start("debugger",
            f"デバッグ開始: {error_count}件のエラーを修正 (試行{iteration}/10)")
        tracker.set_phase("debugging")

        from ..agents.debugger import DebuggerAgent

        debugger = DebuggerAgent()
        tracker.agent_progress("debugger",
            f"LLM呼び出し中: エラー分析・コード修正 - {'; '.join(error_preview)}", {
            "errors_to_fix": error_count,
            "error_preview": error_preview
        })
        result = debugger.run(state)

        state["current_phase"] = Phase.DEBUGGING
        state["code_files"].update(result.get("fixed_code", {}))
        state["messages"].append({
            "role": "assistant",
            "content": f"Fixed {len(result.get('fixed_code', {}))} files"
        })

        fixed_code = result.get("fixed_code", {})
        fixed_files = list(fixed_code.keys())
        fixed_count = len(fixed_files)

        # Clear errors for next test
        state["errors"] = []

        tracker.agent_complete("debugger",
            f"デバッグ完了: {fixed_count}ファイル修正 ({', '.join(fixed_files)}) - 再テストへ", {
            "fixed_files": fixed_count,
            "fixed_file_list": fixed_files,
            "iteration": iteration,
            "errors_fixed": error_count
        })

        return state

    def _reviewer_node(self, state: GameState) -> GameState:
        """Reviewer Agent node - Reviews code quality."""
        code_files = state.get("code_files", {})
        file_list = list(code_files.keys())
        file_count = len(file_list)
        review_iteration = state.get("review_iteration", 0) + 1
        logger.info("[Reviewer] 開始")
        tracker.agent_start("reviewer",
            f"レビュー開始: {file_count}ファイルのコード品質を検査 (回{review_iteration}/3)")
        tracker.set_phase("review")

        from ..agents.reviewer import ReviewerAgent

        reviewer = ReviewerAgent()
        tracker.agent_progress("reviewer",
            f"LLM呼び出し中: 可読性・保守性・ベストプラクティス・セキュリティをチェック", {
            "review_targets": file_list,
            "review_criteria": ["可読性", "保守性", "ベストプラクティス", "セキュリティ"]
        })
        result = reviewer.run(state)

        state["review_comments"].extend(result.get("review_comments", []))
        state["messages"].append({
            "role": "assistant",
            "content": f"Review completed with {len(result.get('review_comments', []))} comments"
        })

        # Increment review iteration counter in the node (not routing function)
        state["review_iteration"] = review_iteration

        review_comments = result.get("review_comments", [])
        comment_count = len(review_comments)
        critical_count = len([c for c in review_comments if c.get("severity") == "error"])
        warning_count = len([c for c in review_comments if c.get("severity") == "warning"])

        tracker.set_review_comments(review_comments)
        tracker.agent_complete("reviewer",
            f"レビュー完了: {comment_count}件 (重大{critical_count}/警告{warning_count}) - {'要修正' if critical_count > 0 else 'OK'}", {
            "comments": comment_count,
            "critical_count": critical_count,
            "warning_count": warning_count,
            "review_iteration": review_iteration,
            "comment_list": review_comments,
            "needs_revision": critical_count > 0
        })

        return state

    # Routing functions

    def _route_after_planning(self, state: GameState) -> Literal["coding", "cancelled"]:
        """Route after planning phase."""
        if state.get("game_spec") is None:
            return "cancelled"
        return "coding"

    def _route_after_coding(self, state: GameState) -> Literal["assets", "testing"]:
        """Route after coding phase."""
        game_spec = state.get("game_spec", {})
        if game_spec.get("visual_style") or game_spec.get("audio_style"):
            return "assets"
        return "testing"

    def _route_after_assets(self, state: GameState) -> Literal["testing"]:
        """Route after asset generation."""
        return "testing"

    def _route_after_testing(self, state: GameState) -> Literal["debugging", "review", "completed"]:
        """Route after testing phase."""
        errors = state.get("errors", [])

        if len(errors) > 0:
            iteration = state.get("iteration", 0)
            if iteration >= 10:
                logger.warning("最大リトライ回数に到達")
                return "completed"
            return "debugging"

        return "review"

    def _route_after_debugging(self, state: GameState) -> Literal["coding", "testing"]:
        """Route after debugging phase."""
        state["iteration"] = state.get("iteration", 0) + 1
        return "testing"

    def _route_after_review(self, state: GameState) -> Literal["coding", "completed"]:
        """Route after review phase."""
        review_comments = state.get("review_comments", [])
        critical_comments = [c for c in review_comments if c.get("severity") == "error"]

        # Counter is incremented in _reviewer_node
        review_iteration = state.get("review_iteration", 0)

        if len(critical_comments) > 0 and review_iteration < 3:
            logger.info(f"レビュー反復 {review_iteration}/3 - コーダーへ戻る")
            return "coding"

        if len(critical_comments) > 0:
            logger.warning("最大レビュー回数に到達")

        state["current_phase"] = Phase.COMPLETED
        return "completed"

    def run(self, state: GameState) -> GameState:
        """
        Run the workflow.

        Args:
            state: Initial game state

        Returns:
            Final game state
        """
        logger.info("ワークフロー開始")
        logger.info(f"リクエスト: {state.get('user_request')}")
        logger.info(f"フェーズ: {state.get('development_phase')}")

        final_state = self.graph.invoke(state)

        logger.info("ワークフロー完了")
        logger.info(f"ファイル: {len(final_state.get('code_files', {}))}件")
        logger.info(f"アセット: {len(final_state.get('artifacts', {}))}件")

        return final_state
