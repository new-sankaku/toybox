"""プロジェクトAPIルートの統合テスト"""

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from unittest.mock import MagicMock, AsyncMock
from routers import project
from core.dependencies import set_data_store, set_socket_manager


class MockDataStore:
    def __init__(self):
        self.projects = {}
        self._next_id = 1

    def get_projects(self):
        return list(self.projects.values())

    def get_project(self, project_id: str):
        return self.projects.get(project_id)

    def create_project(self, data: dict):
        pid = f"proj-{self._next_id:03d}"
        self._next_id += 1
        proj = {
            "id": pid,
            "name": data.get("name"),
            "description": data.get("description"),
            "status": "draft",
            "currentPhase": 1,
            **data,
        }
        self.projects[pid] = proj
        return proj

    def update_project(self, project_id: str, data: dict):
        if project_id not in self.projects:
            return None
        self.projects[project_id].update(data)
        return self.projects[project_id]

    def delete_project(self, project_id: str):
        if project_id not in self.projects:
            return False
        del self.projects[project_id]
        return True

    def initialize_project(self, project_id: str):
        if project_id not in self.projects:
            return None
        self.projects[project_id]["status"] = "draft"
        self.projects[project_id]["currentPhase"] = 1
        return self.projects[project_id]

    def brushup_project(self, project_id: str, options: dict):
        if project_id not in self.projects:
            return None
        self.projects[project_id]["status"] = "draft"
        return self.projects[project_id]

    def get_ai_services(self, project_id: str):
        return {"chat": {"provider": "anthropic", "model": "claude-3-5-sonnet-20241022"}}

    def update_ai_services(self, project_id: str, data: dict):
        return data

    def update_ai_service(self, project_id: str, service_type: str, data: dict):
        if service_type not in ["chat", "image", "audio"]:
            return None
        return {"provider": data.get("provider"), "model": data.get("model")}


class MockSocketManager:
    def __init__(self):
        self.emitted = []

    async def emit(self, event: str, data: dict, **kwargs):
        self.emitted.append({"event": event, "data": data})

    async def emit_to_project(self, event: str, data: dict, project_id: str):
        self.emitted.append({"event": event, "data": data, "project_id": project_id})


class MockJobQueue:
    def cleanup_project_jobs(self, project_id: str):
        return 0


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
    app.include_router(project.router, prefix="/api")
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


class TestProjectCRUD:
    def test_list_projects_empty(self, client):
        response = client.get("/api/projects")
        assert response.status_code == 200
        assert response.json() == []

    def test_create_project(self, client):
        response = client.post("/api/projects", json={"name": "テストプロジェクト", "description": "テスト説明"})
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "テストプロジェクト"
        assert data["status"] == "draft"
        assert "id" in data

    def test_list_projects_with_data(self, client):
        client.post("/api/projects", json={"name": "プロジェクト1"})
        client.post("/api/projects", json={"name": "プロジェクト2"})
        response = client.get("/api/projects")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    def test_update_project(self, client):
        create_resp = client.post("/api/projects", json={"name": "元の名前"})
        project_id = create_resp.json()["id"]
        response = client.patch(f"/api/projects/{project_id}", json={"name": "新しい名前"})
        assert response.status_code == 200
        assert response.json()["name"] == "新しい名前"

    def test_update_project_not_found(self, client):
        response = client.patch("/api/projects/nonexistent", json={"name": "テスト"})
        assert response.status_code == 404

    def test_delete_project(self, client):
        create_resp = client.post("/api/projects", json={"name": "削除対象"})
        project_id = create_resp.json()["id"]
        response = client.delete(f"/api/projects/{project_id}")
        assert response.status_code == 204
        list_resp = client.get("/api/projects")
        assert len(list_resp.json()) == 0

    def test_delete_project_not_found(self, client):
        response = client.delete("/api/projects/nonexistent")
        assert response.status_code == 404


class TestProjectLifecycle:
    def test_start_project_from_draft(self, client, monkeypatch):
        monkeypatch.setattr("services.llm_job_queue.get_llm_job_queue", lambda: MockJobQueue())
        create_resp = client.post("/api/projects", json={"name": "ライフサイクルテスト"})
        project_id = create_resp.json()["id"]
        response = client.post(f"/api/projects/{project_id}/start")
        assert response.status_code == 200
        assert response.json()["status"] == "running"

    def test_start_project_not_found(self, client, monkeypatch):
        monkeypatch.setattr("services.llm_job_queue.get_llm_job_queue", lambda: MockJobQueue())
        response = client.post("/api/projects/nonexistent/start")
        assert response.status_code == 404

    def test_start_project_invalid_status(self, client, mock_data_store, monkeypatch):
        monkeypatch.setattr("services.llm_job_queue.get_llm_job_queue", lambda: MockJobQueue())
        create_resp = client.post("/api/projects", json={"name": "テスト"})
        project_id = create_resp.json()["id"]
        mock_data_store.projects[project_id]["status"] = "running"
        response = client.post(f"/api/projects/{project_id}/start")
        assert response.status_code == 400

    def test_pause_project(self, client, mock_data_store):
        create_resp = client.post("/api/projects", json={"name": "一時停止テスト"})
        project_id = create_resp.json()["id"]
        mock_data_store.projects[project_id]["status"] = "running"
        response = client.post(f"/api/projects/{project_id}/pause")
        assert response.status_code == 200
        assert response.json()["status"] == "paused"

    def test_pause_project_not_running(self, client):
        create_resp = client.post("/api/projects", json={"name": "テスト"})
        project_id = create_resp.json()["id"]
        response = client.post(f"/api/projects/{project_id}/pause")
        assert response.status_code == 400

    def test_resume_project(self, client, mock_data_store, monkeypatch):
        monkeypatch.setattr("services.llm_job_queue.get_llm_job_queue", lambda: MockJobQueue())
        create_resp = client.post("/api/projects", json={"name": "再開テスト"})
        project_id = create_resp.json()["id"]
        mock_data_store.projects[project_id]["status"] = "paused"
        response = client.post(f"/api/projects/{project_id}/resume")
        assert response.status_code == 200
        assert response.json()["status"] == "running"

    def test_resume_project_not_paused(self, client):
        create_resp = client.post("/api/projects", json={"name": "テスト"})
        project_id = create_resp.json()["id"]
        response = client.post(f"/api/projects/{project_id}/resume")
        assert response.status_code == 400

    def test_initialize_project(self, client, monkeypatch):
        monkeypatch.setattr("services.llm_job_queue.get_llm_job_queue", lambda: MockJobQueue())
        create_resp = client.post("/api/projects", json={"name": "初期化テスト"})
        project_id = create_resp.json()["id"]
        response = client.post(f"/api/projects/{project_id}/initialize")
        assert response.status_code == 200

    def test_initialize_project_not_found(self, client, monkeypatch):
        monkeypatch.setattr("services.llm_job_queue.get_llm_job_queue", lambda: MockJobQueue())
        response = client.post("/api/projects/nonexistent/initialize")
        assert response.status_code == 404


class TestProjectAIServices:
    def test_get_ai_services(self, client):
        create_resp = client.post("/api/projects", json={"name": "AIテスト"})
        project_id = create_resp.json()["id"]
        response = client.get(f"/api/projects/{project_id}/ai-services")
        assert response.status_code == 200
        assert "chat" in response.json()

    def test_get_ai_services_not_found(self, client):
        response = client.get("/api/projects/nonexistent/ai-services")
        assert response.status_code == 404

    def test_update_ai_services(self, client):
        create_resp = client.post("/api/projects", json={"name": "AIテスト"})
        project_id = create_resp.json()["id"]
        response = client.put(
            f"/api/projects/{project_id}/ai-services", json={"chat": {"provider": "openai", "model": "gpt-4"}}
        )
        assert response.status_code == 200

    def test_update_ai_service(self, client):
        create_resp = client.post("/api/projects", json={"name": "AIテスト"})
        project_id = create_resp.json()["id"]
        response = client.patch(
            f"/api/projects/{project_id}/ai-services/chat", json={"provider": "openai", "model": "gpt-4"}
        )
        assert response.status_code == 200

    def test_update_ai_service_not_found_project(self, client):
        response = client.patch("/api/projects/nonexistent/ai-services/chat", json={"provider": "openai"})
        assert response.status_code == 404


class TestBrushup:
    def test_brushup_completed_project(self, client, mock_data_store):
        create_resp = client.post("/api/projects", json={"name": "ブラッシュアップテスト"})
        project_id = create_resp.json()["id"]
        mock_data_store.projects[project_id]["status"] = "completed"
        response = client.post(
            f"/api/projects/{project_id}/brushup",
            json={
                "selectedAgents": [],
                "agentOptions": {},
                "agentInstructions": {},
                "clearAssets": False,
                "presets": [],
                "customInstruction": "",
                "referenceImageIds": [],
            },
        )
        assert response.status_code == 200

    def test_brushup_not_completed(self, client):
        create_resp = client.post("/api/projects", json={"name": "ブラッシュアップテスト"})
        project_id = create_resp.json()["id"]
        response = client.post(
            f"/api/projects/{project_id}/brushup",
            json={
                "selectedAgents": [],
                "agentOptions": {},
                "agentInstructions": {},
                "clearAssets": False,
                "presets": [],
                "customInstruction": "",
                "referenceImageIds": [],
            },
        )
        assert response.status_code == 400

    def test_brushup_not_found(self, client):
        response = client.post(
            "/api/projects/nonexistent/brushup",
            json={
                "selectedAgents": [],
                "agentOptions": {},
                "agentInstructions": {},
                "clearAssets": False,
                "presets": [],
                "customInstruction": "",
                "referenceImageIds": [],
            },
        )
        assert response.status_code == 404
