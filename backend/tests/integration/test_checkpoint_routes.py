"""チェックポイントAPIルートの統合テスト"""

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from routers import checkpoint
from core.dependencies import set_data_store, set_socket_manager


class MockDataStore:
    def __init__(self):
        self.projects = {"proj-001": {"id": "proj-001", "name": "テスト", "status": "running"}}
        self.checkpoints = {}
        self.agents = {}
        self._next_id = 1

    def get_project(self, project_id: str):
        return self.projects.get(project_id)

    def get_checkpoints_by_project(self, project_id: str):
        return [c for c in self.checkpoints.values() if c.get("projectId") == project_id]

    def resolve_checkpoint(self, checkpoint_id: str, resolution: str, feedback: str = None):
        if checkpoint_id not in self.checkpoints:
            return None
        self.checkpoints[checkpoint_id]["resolution"] = resolution
        self.checkpoints[checkpoint_id]["feedback"] = feedback
        self.checkpoints[checkpoint_id]["status"] = "resolved"
        return self.checkpoints[checkpoint_id]

    def get_agent(self, agent_id: str):
        return self.agents.get(agent_id)

    def add_checkpoint(self, checkpoint_id: str, project_id: str, agent_id: str):
        self.checkpoints[checkpoint_id] = {
            "id": checkpoint_id,
            "projectId": project_id,
            "agentId": agent_id,
            "status": "pending",
            "type": "approval",
        }
        if agent_id and agent_id not in self.agents:
            self.agents[agent_id] = {"id": agent_id, "status": "waiting_approval"}


class MockSocketManager:
    def __init__(self):
        self.emitted = []

    async def emit_to_project(self, event: str, data: dict, project_id: str):
        self.emitted.append({"event": event, "data": data, "project_id": project_id})


@pytest.fixture
def mock_data_store():
    return MockDataStore()


@pytest.fixture
def mock_socket_manager():
    return MockSocketManager()


@pytest.fixture
def app(mock_data_store, mock_socket_manager):
    set_data_store(mock_data_store)
    set_socket_manager(mock_socket_manager)
    app = FastAPI()
    app.include_router(checkpoint.router, prefix="/api")
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


class TestListCheckpoints:
    def test_list_checkpoints_empty(self, client):
        response = client.get("/api/projects/proj-001/checkpoints")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_checkpoints_with_data(self, client, mock_data_store):
        mock_data_store.add_checkpoint("cp-001", "proj-001", "agent-001")
        mock_data_store.add_checkpoint("cp-002", "proj-001", "agent-002")
        response = client.get("/api/projects/proj-001/checkpoints")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    def test_list_checkpoints_project_not_found(self, client):
        response = client.get("/api/projects/nonexistent/checkpoints")
        assert response.status_code == 404


class TestResolveCheckpoint:
    def test_approve_checkpoint(self, client, mock_data_store):
        mock_data_store.add_checkpoint("cp-001", "proj-001", "agent-001")
        response = client.post("/api/checkpoints/cp-001/resolve", json={"resolution": "approved"})
        assert response.status_code == 200
        data = response.json()
        assert data["resolution"] == "approved"
        assert data["status"] == "resolved"

    def test_reject_checkpoint(self, client, mock_data_store):
        mock_data_store.add_checkpoint("cp-001", "proj-001", "agent-001")
        response = client.post(
            "/api/checkpoints/cp-001/resolve", json={"resolution": "rejected", "feedback": "品質が不十分です"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["resolution"] == "rejected"
        assert data["feedback"] == "品質が不十分です"

    def test_revision_requested(self, client, mock_data_store):
        mock_data_store.add_checkpoint("cp-001", "proj-001", "agent-001")
        response = client.post(
            "/api/checkpoints/cp-001/resolve", json={"resolution": "revision_requested", "feedback": "修正してください"}
        )
        assert response.status_code == 200
        assert response.json()["resolution"] == "revision_requested"

    def test_invalid_resolution(self, client, mock_data_store):
        mock_data_store.add_checkpoint("cp-001", "proj-001", "agent-001")
        response = client.post("/api/checkpoints/cp-001/resolve", json={"resolution": "invalid_status"})
        assert response.status_code == 400

    def test_checkpoint_not_found(self, client):
        response = client.post("/api/checkpoints/nonexistent/resolve", json={"resolution": "approved"})
        assert response.status_code == 404


class TestWebSocketEmission:
    def test_resolve_emits_event(self, client, mock_data_store, mock_socket_manager):
        mock_data_store.add_checkpoint("cp-001", "proj-001", "agent-001")
        client.post("/api/checkpoints/cp-001/resolve", json={"resolution": "approved"})
        assert len(mock_socket_manager.emitted) == 1
        event = mock_socket_manager.emitted[0]
        assert event["event"] == "checkpoint:resolved"
        assert event["project_id"] == "proj-001"
        assert event["data"]["checkpointId"] == "cp-001"
        assert event["data"]["resolution"] == "approved"
