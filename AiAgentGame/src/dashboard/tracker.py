"""
Event Tracker - Collects and broadcasts agent execution events.
"""

import asyncio
from datetime import datetime
from typing import Optional, Callable, Any
from dataclasses import dataclass, field, asdict
from enum import Enum


class AgentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class AgentEvent:
    agent: str
    status: AgentStatus
    message: str
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))
    details: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "agent": self.agent,
            "status": self.status.value,
            "message": self.message,
            "timestamp": self.timestamp,
            "details": self.details
        }


class EventTracker:
    """
    Singleton tracker for agent events.
    Collects events and notifies subscribers (WebSocket clients).
    """
    _instance: Optional["EventTracker"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self.events: list[AgentEvent] = []
        self.agent_states: dict[str, AgentStatus] = {}
        self.current_phase: str = "idle"
        self.user_request: str = ""
        self.game_spec: dict = {}
        self.tasks: list[dict] = []
        self._subscribers: list[Callable[[AgentEvent], Any]] = []
        self._async_subscribers: list[Callable[[AgentEvent], Any]] = []

    def reset(self):
        """Reset tracker state for new workflow."""
        self.events.clear()
        self.agent_states = {
            "planner": AgentStatus.PENDING,
            "coder": AgentStatus.PENDING,
            "asset_coordinator": AgentStatus.PENDING,
            "tester": AgentStatus.PENDING,
            "debugger": AgentStatus.PENDING,
            "reviewer": AgentStatus.PENDING,
        }
        self.current_phase = "idle"
        self.game_spec = {}
        self.architecture = {}
        self.task_phases = []
        self.asset_categories = {}
        self.tasks = []
        self.errors = []
        self.assets = []
        self.review_comments = []
        self.code_files = []
        self.llm_interactions = []
        self.total_tokens = {"input": 0, "output": 0}

    def subscribe(self, callback: Callable[[AgentEvent], Any]):
        """Subscribe to events (sync callback)."""
        self._subscribers.append(callback)

    def subscribe_async(self, callback: Callable[[AgentEvent], Any]):
        """Subscribe to events (async callback)."""
        self._async_subscribers.append(callback)

    def unsubscribe(self, callback: Callable):
        """Unsubscribe from events."""
        if callback in self._subscribers:
            self._subscribers.remove(callback)
        if callback in self._async_subscribers:
            self._async_subscribers.remove(callback)

    def emit(self, agent: str, status: AgentStatus, message: str, details: dict = None):
        """Emit an agent event."""
        event = AgentEvent(
            agent=agent,
            status=status,
            message=message,
            details=details
        )
        self.events.append(event)
        self.agent_states[agent] = status

        # Notify sync subscribers
        for callback in self._subscribers:
            try:
                callback(event)
            except Exception:
                pass

        # Notify async subscribers (handle both running and non-running event loops)
        for callback in self._async_subscribers:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(callback(event))
            except RuntimeError:
                # No running event loop - try to run in new loop
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # Schedule from different thread
                        asyncio.run_coroutine_threadsafe(callback(event), loop)
                    else:
                        asyncio.run(callback(event))
                except Exception:
                    pass

    def agent_start(self, agent: str, message: str = None):
        """Mark agent as running."""
        msg = message or f"{agent} started"
        self.emit(agent, AgentStatus.RUNNING, msg)

    def agent_progress(self, agent: str, message: str, details: dict = None):
        """Report agent progress."""
        self.emit(agent, AgentStatus.RUNNING, message, details)

    def agent_complete(self, agent: str, message: str = None, details: dict = None):
        """Mark agent as completed."""
        msg = message or f"{agent} completed"
        self.emit(agent, AgentStatus.COMPLETED, msg, details)

    def agent_error(self, agent: str, message: str, details: dict = None):
        """Mark agent as error."""
        self.emit(agent, AgentStatus.ERROR, message, details)

    def set_phase(self, phase: str):
        """Set current workflow phase."""
        self.current_phase = phase
        self.emit("workflow", AgentStatus.RUNNING, f"Phase: {phase}")

    def set_request(self, request: str):
        """Set user request."""
        self.user_request = request

    def set_game_spec(self, spec: dict):
        """Set game specification."""
        self.game_spec = spec

    def set_architecture(self, arch: dict):
        """Set game architecture and emit to dashboard."""
        self.architecture = arch
        self.emit("planner", AgentStatus.RUNNING, "アーキテクチャ設計完了", {
            "architecture": arch
        })

    def set_task_phases(self, phases: list):
        """Set task phases and emit to dashboard."""
        self.task_phases = phases
        self.emit("planner", AgentStatus.RUNNING, f"タスクフェーズ設定: {len(phases)}フェーズ", {
            "task_phases": phases
        })

    def set_asset_categories(self, categories: dict):
        """Set asset categories and emit to dashboard."""
        self.asset_categories = categories
        self.emit("planner", AgentStatus.RUNNING, "アセットカテゴリ設定完了", {
            "asset_categories": categories
        })

    def update_task_status(self, phase_id: str, task_name: str, status: str):
        """Update individual task status."""
        self.emit("workflow", AgentStatus.RUNNING, f"タスク更新: {task_name}", {
            "task_update": {"phaseId": phase_id, "taskName": task_name, "status": status}
        })

    def update_asset_status(self, tab_key: str, category_id: str, item_name: str, status: str):
        """Update individual asset status."""
        self.emit("workflow", AgentStatus.RUNNING, f"アセット更新: {item_name}", {
            "asset_update": {"tabKey": tab_key, "categoryId": category_id, "itemName": item_name, "status": status}
        })

    def set_tasks(self, tasks: list):
        """Set task list from planner."""
        self.tasks = [
            {"id": t.id if hasattr(t, 'id') else t.get('id', ''),
             "description": t.description if hasattr(t, 'description') else t.get('description', ''),
             "status": t.status if hasattr(t, 'status') else t.get('status', 'pending'),
             "assigned_agent": t.assigned_agent if hasattr(t, 'assigned_agent') else t.get('assigned_agent', '')}
            for t in tasks
        ]

    def set_errors(self, errors: list):
        """Set error list from tester."""
        self.errors = errors

    def set_assets(self, assets: list):
        """Set asset list."""
        self.assets = assets

    def set_review_comments(self, comments: list):
        """Set review comments."""
        self.review_comments = comments

    def set_code_files(self, files: list):
        """Set code files list."""
        self.code_files = files

    def add_llm_interaction(self, interaction: dict):
        """Add LLM interaction and emit event."""
        self.llm_interactions.append(interaction)
        self.total_tokens["input"] = interaction.get("total_input", 0)
        self.total_tokens["output"] = interaction.get("total_output", 0)

        # Emit event for real-time update
        self.emit("llm", AgentStatus.RUNNING,
            f"[{interaction.get('agent', '?')}] LLM応答: {len(interaction.get('response', ''))}文字", {
            "llm_interaction": interaction,
            "total_tokens": self.total_tokens.copy()
        })

    def get_state(self) -> dict:
        """Get current tracker state for API response."""
        return {
            "phase": self.current_phase,
            "user_request": self.user_request,
            "game_spec": self.game_spec,
            "architecture": self.architecture,
            "task_phases": self.task_phases,
            "asset_categories": self.asset_categories,
            "agents": {k: v.value for k, v in self.agent_states.items()},
            "events": [e.to_dict() for e in self.events[-100:]],
            "tasks": self.tasks,
            "errors": self.errors,
            "assets": self.assets,
            "review_comments": self.review_comments,
            "code_files": self.code_files,
            "llm_interactions": self.llm_interactions[-20:],  # Last 20 interactions
            "total_tokens": self.total_tokens,
        }


# Global tracker instance
tracker = EventTracker()
