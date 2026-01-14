"""
LangGraph workflow definition for AI Agent Game Creator.
"""

from typing import Literal
from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage

from .state import GameState, Phase
from .feedback import FeedbackManager


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
        """
        Planner Agent node - Creates game specification and task list.
        """
        print("\n" + "="*80)
        print("🎯 PLANNER AGENT")
        print("="*80)

        # Import here to avoid circular imports
        from ..agents.planner import PlannerAgent

        planner = PlannerAgent()
        result = planner.run(state)

        # Update state
        state["current_phase"] = Phase.PLANNING
        state["game_spec"] = result.get("game_spec")
        state["tasks"] = result.get("tasks", [])
        state["messages"].append({
            "role": "assistant",
            "content": f"Game spec created: {result.get('game_spec', {}).get('title', 'Unknown')}"
        })

        # Save status
        self.feedback_manager.save_status(state)

        return state

    def _coder_node(self, state: GameState) -> GameState:
        """
        Coder Agent node - Implements game code.
        """
        print("\n" + "="*80)
        print("💻 CODER AGENT")
        print("="*80)

        from ..agents.coder import CoderAgent

        coder = CoderAgent()
        result = coder.run(state)

        # Update state
        state["current_phase"] = Phase.CODING
        state["code_files"].update(result.get("code_files", {}))
        state["messages"].append({
            "role": "assistant",
            "content": f"Generated {len(result.get('code_files', {}))} code files"
        })

        return state

    def _asset_coordinator_node(self, state: GameState) -> GameState:
        """
        Asset Coordinator node - Distributes asset generation tasks.
        """
        print("\n" + "="*80)
        print("🎨 ASSET COORDINATOR")
        print("="*80)

        from ..agents.asset_coordinator import AssetCoordinatorAgent

        coordinator = AssetCoordinatorAgent()
        result = coordinator.run(state)

        # Update state
        state["current_phase"] = Phase.ASSET_GENERATION
        state["artifacts"].update(result.get("artifacts", {}))
        state["messages"].append({
            "role": "assistant",
            "content": f"Generated {len(result.get('artifacts', {}))} assets"
        })

        return state

    def _tester_node(self, state: GameState) -> GameState:
        """
        Tester Agent node - Tests the game.
        """
        print("\n" + "="*80)
        print("🧪 TESTER AGENT")
        print("="*80)

        from ..agents.tester import TesterAgent

        tester = TesterAgent()
        result = tester.run(state)

        # Update state
        state["current_phase"] = Phase.TESTING
        state["test_results"] = result.get("test_results")
        state["errors"].extend(result.get("errors", []))
        state["messages"].append({
            "role": "assistant",
            "content": f"Testing completed with {len(result.get('errors', []))} errors"
        })

        return state

    def _debugger_node(self, state: GameState) -> GameState:
        """
        Debugger Agent node - Fixes bugs.
        """
        print("\n" + "="*80)
        print("🐛 DEBUGGER AGENT")
        print("="*80)

        from ..agents.debugger import DebuggerAgent

        debugger = DebuggerAgent()
        result = debugger.run(state)

        # Update state
        state["current_phase"] = Phase.DEBUGGING
        state["code_files"].update(result.get("fixed_code", {}))
        state["messages"].append({
            "role": "assistant",
            "content": f"Fixed {len(result.get('fixed_code', {}))} files"
        })

        return state

    def _reviewer_node(self, state: GameState) -> GameState:
        """
        Reviewer Agent node - Reviews code quality.
        """
        print("\n" + "="*80)
        print("👀 REVIEWER AGENT")
        print("="*80)

        from ..agents.reviewer import ReviewerAgent

        reviewer = ReviewerAgent()
        result = reviewer.run(state)

        # Update state
        state["review_comments"].extend(result.get("review_comments", []))
        state["messages"].append({
            "role": "assistant",
            "content": f"Review completed with {len(result.get('review_comments', []))} comments"
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
        # Check if assets are needed
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
            # Check if we've retried too many times
            iteration = state.get("iteration", 0)
            if iteration >= 10:
                print("⚠️  Maximum retry limit reached. Manual intervention required.")
                return "completed"
            return "debugging"

        # No errors, proceed to review
        return "review"

    def _route_after_debugging(self, state: GameState) -> Literal["coding", "testing"]:
        """Route after debugging phase."""
        # Increment iteration counter
        state["iteration"] = state.get("iteration", 0) + 1

        # Re-test after fixes
        return "testing"

    def _route_after_review(self, state: GameState) -> Literal["coding", "completed"]:
        """Route after review phase."""
        # Check for critical review comments
        review_comments = state.get("review_comments", [])
        critical_comments = [c for c in review_comments if c.get("severity") == "error"]

        if len(critical_comments) > 0:
            return "coding"

        # All good!
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
        print("\n" + "="*80)
        print("🚀 AI AGENT GAME CREATOR - Starting workflow")
        print("="*80)
        print(f"User Request: {state.get('user_request')}")
        print(f"Development Phase: {state.get('development_phase')}")
        print("="*80 + "\n")

        # Execute the graph
        final_state = self.graph.invoke(state)

        print("\n" + "="*80)
        print("✅ WORKFLOW COMPLETED")
        print("="*80)
        print(f"Final Phase: {final_state.get('current_phase')}")
        print(f"Generated Files: {len(final_state.get('code_files', {}))}")
        print(f"Generated Assets: {len(final_state.get('artifacts', {}))}")
        print("="*80 + "\n")

        return final_state
