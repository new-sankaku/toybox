"""
Dashboard module for AI Agent Game Creator.
Provides real-time monitoring of agent execution via WebUI.
"""

from .tracker import tracker, EventTracker, AgentEvent, AgentStatus

__all__ = [
    "tracker",
    "EventTracker",
    "AgentEvent",
    "AgentStatus",
]
