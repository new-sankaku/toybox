"""WebSocket統合テスト"""

import pytest


class MockDataStore:
    def __init__(self):
        self.projects = {"proj-001": {"id": "proj-001", "name": "テスト", "status": "running", "currentPhase": 1}}
        self.agents = {"agent-001": {"id": "agent-001", "projectId": "proj-001", "status": "running"}}
        self.checkpoints = {
            "cp-001": {"id": "cp-001", "projectId": "proj-001", "agentId": "agent-001", "status": "pending"}
        }
        self.subscriptions = {}
        self.metrics = {"proj-001": {"totalAgents": 1, "completedAgents": 0}}

    def get_project(self, project_id: str):
        return self.projects.get(project_id)

    def get_agents_by_project(self, project_id: str):
        return [a for a in self.agents.values() if a.get("projectId") == project_id]

    def get_checkpoints_by_project(self, project_id: str):
        return [c for c in self.checkpoints.values() if c.get("projectId") == project_id]

    def get_project_metrics(self, project_id: str):
        return self.metrics.get(project_id, {})

    def add_subscription(self, project_id: str, sid: str):
        if project_id not in self.subscriptions:
            self.subscriptions[project_id] = set()
        self.subscriptions[project_id].add(sid)

    def remove_subscription(self, project_id: str, sid: str):
        if project_id in self.subscriptions:
            self.subscriptions[project_id].discard(sid)

    def remove_all_subscriptions(self, sid: str):
        for project_id in self.subscriptions:
            self.subscriptions[project_id].discard(sid)

    def resolve_checkpoint(self, checkpoint_id: str, resolution: str, feedback: str = None):
        if checkpoint_id not in self.checkpoints:
            return None
        self.checkpoints[checkpoint_id]["resolution"] = resolution
        self.checkpoints[checkpoint_id]["feedback"] = feedback
        self.checkpoints[checkpoint_id]["status"] = "resolved"
        return self.checkpoints[checkpoint_id]

    def get_agent(self, agent_id: str):
        return self.agents.get(agent_id)


class MockSocketIO:
    def __init__(self):
        self.handlers = {}
        self.emitted = []
        self.rooms = {}

    def event(self, func):
        self.handlers[func.__name__] = func
        return func

    def on(self, event_name):
        def decorator(func):
            self.handlers[event_name] = func
            return func

        return decorator

    def emit(self, event: str, data: dict, room: str = None):
        self.emitted.append({"event": event, "data": data, "room": room})

    def enter_room(self, sid: str, room: str):
        if room not in self.rooms:
            self.rooms[room] = set()
        self.rooms[room].add(sid)

    def leave_room(self, sid: str, room: str):
        if room in self.rooms:
            self.rooms[room].discard(sid)


class MockSocketManager:
    def __init__(self):
        self.subscriptions = {}

    def add_subscription(self, project_id: str, sid: str):
        if project_id not in self.subscriptions:
            self.subscriptions[project_id] = set()
        self.subscriptions[project_id].add(sid)

    def remove_subscription(self, project_id: str, sid: str):
        if project_id in self.subscriptions:
            self.subscriptions[project_id].discard(sid)

    def remove_all_subscriptions(self, sid: str):
        for project_id in self.subscriptions:
            self.subscriptions[project_id].discard(sid)

    def get_subscribers(self, project_id: str):
        return self.subscriptions.get(project_id, set()).copy()


def register_websocket_handlers(sio, data_store):
    @sio.event
    def connect(sid, environ):
        sio.emit("connection:state_sync", {"status": "connected", "sid": sid}, room=sid)

    @sio.event
    def disconnect(sid):
        data_store.remove_all_subscriptions(sid)

    @sio.on("subscribe:project")
    def subscribe_project(sid, data):
        project_id = data.get("projectId") if isinstance(data, dict) else data
        project = data_store.get_project(project_id)
        if not project:
            sio.emit(
                "error:state", {"message": f"Project not found: {project_id}", "code": "PROJECT_NOT_FOUND"}, room=sid
            )
            return
        data_store.add_subscription(project_id, sid)
        sio.enter_room(sid, f"project:{project_id}")
        agents = data_store.get_agents_by_project(project_id)
        checkpoints = data_store.get_checkpoints_by_project(project_id)
        metrics = data_store.get_project_metrics(project_id)
        sio.emit(
            "connection:state_sync",
            {"project": project, "agents": agents, "checkpoints": checkpoints, "metrics": metrics},
            room=sid,
        )

    @sio.on("unsubscribe:project")
    def unsubscribe_project(sid, data):
        project_id = data.get("projectId") if isinstance(data, dict) else data
        data_store.remove_subscription(project_id, sid)
        sio.leave_room(sid, f"project:{project_id}")

    @sio.on("checkpoint:resolve")
    def checkpoint_resolve(sid, data):
        checkpoint_id = data.get("checkpointId")
        resolution = data.get("resolution")
        feedback = data.get("feedback")
        if resolution not in ("approved", "rejected", "revision_requested"):
            sio.emit("error:state", {"message": "Invalid resolution", "code": "INVALID_RESOLUTION"}, room=sid)
            return
        checkpoint = data_store.resolve_checkpoint(checkpoint_id, resolution, feedback)
        if not checkpoint:
            sio.emit(
                "error:state",
                {"message": f"Checkpoint not found: {checkpoint_id}", "code": "CHECKPOINT_NOT_FOUND"},
                room=sid,
            )
            return
        project_id = checkpoint["projectId"]
        agent_id = checkpoint["agentId"]
        agent = data_store.get_agent(agent_id)
        agent_status = agent["status"] if agent else None
        sio.emit(
            "checkpoint:resolved",
            {
                "checkpointId": checkpoint_id,
                "projectId": project_id,
                "agentId": agent_id,
                "resolution": resolution,
                "feedback": feedback,
                "checkpoint": checkpoint,
                "agentStatus": agent_status,
            },
            room=f"project:{project_id}",
        )


def broadcast_navigator_message(sio, project_id: str, speaker: str, text: str, priority: str = "normal"):
    message_data = {"speaker": speaker, "text": text, "priority": priority, "source": "server"}
    if project_id == "global":
        sio.emit("navigator:message", message_data)
    else:
        sio.emit("navigator:message", message_data, room=f"project:{project_id}")


@pytest.fixture
def mock_sio():
    return MockSocketIO()


@pytest.fixture
def mock_data_store():
    return MockDataStore()


class TestSocketManagerSubscription:
    def test_add_subscription(self):
        manager = MockSocketManager()
        manager.add_subscription("proj-001", "sid-001")
        assert "sid-001" in manager.subscriptions["proj-001"]

    def test_remove_subscription(self):
        manager = MockSocketManager()
        manager.add_subscription("proj-001", "sid-001")
        manager.remove_subscription("proj-001", "sid-001")
        assert "sid-001" not in manager.subscriptions.get("proj-001", set())

    def test_remove_all_subscriptions(self):
        manager = MockSocketManager()
        manager.add_subscription("proj-001", "sid-001")
        manager.add_subscription("proj-002", "sid-001")
        manager.remove_all_subscriptions("sid-001")
        assert "sid-001" not in manager.subscriptions.get("proj-001", set())
        assert "sid-001" not in manager.subscriptions.get("proj-002", set())

    def test_get_subscribers(self):
        manager = MockSocketManager()
        manager.add_subscription("proj-001", "sid-001")
        manager.add_subscription("proj-001", "sid-002")
        subscribers = manager.get_subscribers("proj-001")
        assert len(subscribers) == 2
        assert "sid-001" in subscribers
        assert "sid-002" in subscribers

    def test_get_subscribers_empty(self):
        manager = MockSocketManager()
        subscribers = manager.get_subscribers("nonexistent")
        assert subscribers == set()


class TestWebSocketHandlers:
    def test_register_handlers(self, mock_sio, mock_data_store):
        register_websocket_handlers(mock_sio, mock_data_store)
        assert "connect" in mock_sio.handlers
        assert "disconnect" in mock_sio.handlers
        assert "subscribe:project" in mock_sio.handlers
        assert "unsubscribe:project" in mock_sio.handlers
        assert "checkpoint:resolve" in mock_sio.handlers

    def test_connect_emits_state_sync(self, mock_sio, mock_data_store):
        register_websocket_handlers(mock_sio, mock_data_store)
        mock_sio.handlers["connect"]("sid-001", {})
        assert len(mock_sio.emitted) == 1
        event = mock_sio.emitted[0]
        assert event["event"] == "connection:state_sync"
        assert event["data"]["status"] == "connected"
        assert event["room"] == "sid-001"

    def test_disconnect_removes_subscriptions(self, mock_sio, mock_data_store):
        register_websocket_handlers(mock_sio, mock_data_store)
        mock_data_store.add_subscription("proj-001", "sid-001")
        mock_sio.handlers["disconnect"]("sid-001")
        assert "sid-001" not in mock_data_store.subscriptions.get("proj-001", set())

    def test_subscribe_project_success(self, mock_sio, mock_data_store):
        register_websocket_handlers(mock_sio, mock_data_store)
        mock_sio.handlers["subscribe:project"]("sid-001", {"projectId": "proj-001"})
        assert "sid-001" in mock_data_store.subscriptions.get("proj-001", set())
        assert "project:proj-001" in mock_sio.rooms
        assert "sid-001" in mock_sio.rooms["project:proj-001"]
        state_sync = [e for e in mock_sio.emitted if e["event"] == "connection:state_sync"]
        assert len(state_sync) == 1
        data = state_sync[0]["data"]
        assert "project" in data
        assert "agents" in data
        assert "checkpoints" in data

    def test_subscribe_project_not_found(self, mock_sio, mock_data_store):
        register_websocket_handlers(mock_sio, mock_data_store)
        mock_sio.handlers["subscribe:project"]("sid-001", {"projectId": "nonexistent"})
        error_events = [e for e in mock_sio.emitted if e["event"] == "error:state"]
        assert len(error_events) == 1
        assert error_events[0]["data"]["code"] == "PROJECT_NOT_FOUND"

    def test_unsubscribe_project(self, mock_sio, mock_data_store):
        register_websocket_handlers(mock_sio, mock_data_store)
        mock_sio.handlers["subscribe:project"]("sid-001", {"projectId": "proj-001"})
        mock_sio.handlers["unsubscribe:project"]("sid-001", {"projectId": "proj-001"})
        assert "sid-001" not in mock_data_store.subscriptions.get("proj-001", set())


class TestCheckpointResolveHandler:
    def test_resolve_approved(self, mock_sio, mock_data_store):
        register_websocket_handlers(mock_sio, mock_data_store)
        mock_sio.handlers["checkpoint:resolve"]("sid-001", {"checkpointId": "cp-001", "resolution": "approved"})
        resolved_events = [e for e in mock_sio.emitted if e["event"] == "checkpoint:resolved"]
        assert len(resolved_events) == 1
        assert resolved_events[0]["data"]["resolution"] == "approved"

    def test_resolve_rejected(self, mock_sio, mock_data_store):
        register_websocket_handlers(mock_sio, mock_data_store)
        mock_sio.handlers["checkpoint:resolve"](
            "sid-001", {"checkpointId": "cp-001", "resolution": "rejected", "feedback": "却下理由"}
        )
        resolved_events = [e for e in mock_sio.emitted if e["event"] == "checkpoint:resolved"]
        assert len(resolved_events) == 1
        assert resolved_events[0]["data"]["feedback"] == "却下理由"

    def test_resolve_invalid_resolution(self, mock_sio, mock_data_store):
        register_websocket_handlers(mock_sio, mock_data_store)
        mock_sio.handlers["checkpoint:resolve"]("sid-001", {"checkpointId": "cp-001", "resolution": "invalid"})
        error_events = [e for e in mock_sio.emitted if e["event"] == "error:state"]
        assert len(error_events) == 1
        assert error_events[0]["data"]["code"] == "INVALID_RESOLUTION"

    def test_resolve_checkpoint_not_found(self, mock_sio, mock_data_store):
        register_websocket_handlers(mock_sio, mock_data_store)
        mock_sio.handlers["checkpoint:resolve"]("sid-001", {"checkpointId": "nonexistent", "resolution": "approved"})
        error_events = [e for e in mock_sio.emitted if e["event"] == "error:state"]
        assert len(error_events) == 1
        assert error_events[0]["data"]["code"] == "CHECKPOINT_NOT_FOUND"


class TestNavigatorMessage:
    def test_broadcast_to_project(self, mock_sio):
        broadcast_navigator_message(mock_sio, "proj-001", "システム", "テストメッセージ")
        assert len(mock_sio.emitted) == 1
        event = mock_sio.emitted[0]
        assert event["event"] == "navigator:message"
        assert event["data"]["speaker"] == "システム"
        assert event["data"]["text"] == "テストメッセージ"
        assert event["room"] == "project:proj-001"

    def test_broadcast_global(self, mock_sio):
        broadcast_navigator_message(mock_sio, "global", "オペレーター", "全体通知")
        assert len(mock_sio.emitted) == 1
        event = mock_sio.emitted[0]
        assert event["room"] is None

    def test_broadcast_with_priority(self, mock_sio):
        broadcast_navigator_message(mock_sio, "proj-001", "システム", "緊急メッセージ", priority="critical")
        assert mock_sio.emitted[0]["data"]["priority"] == "critical"
