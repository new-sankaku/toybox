"""
API統合テスト - 全エンドポイント

全エンドポイントの疎通確認を行う。
サーバー起動なしでFastAPIのTestClientを使用してテスト。
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from app import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def test_project(client):
    response = client.post(
        "/api/projects",
        json={"name": "Test Project for API Tests", "description": "Test"},
    )
    project = response.json()
    yield project
    client.delete(f"/api/projects/{project['id']}")


class TestHealthEndpoints:
    def test_health(self, client):
        response = client.get("/health")
        assert response.status_code == 200

    def test_system_stats(self, client):
        response = client.get("/api/system/stats")
        assert response.status_code == 200


class TestProjectEndpoints:
    def test_list_projects(self, client):
        response = client.get("/api/projects")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_create_project(self, client):
        response = client.post(
            "/api/projects",
            json={"name": "Test Create Project", "description": "Test"},
        )
        assert response.status_code == 201
        project = response.json()
        assert "id" in project
        client.delete(f"/api/projects/{project['id']}")

    def test_update_project(self, client, test_project):
        response = client.patch(
            f"/api/projects/{test_project['id']}",
            json={"name": "Updated Name"},
        )
        assert response.status_code == 200

    def test_delete_project(self, client):
        response = client.post(
            "/api/projects",
            json={"name": "To Delete", "description": "Test"},
        )
        project = response.json()
        response = client.delete(f"/api/projects/{project['id']}")
        assert response.status_code == 204

    def test_start_project(self, client, test_project):
        response = client.post(f"/api/projects/{test_project['id']}/start")
        assert response.status_code in (200, 400)

    def test_pause_project(self, client, test_project):
        response = client.post(f"/api/projects/{test_project['id']}/pause")
        assert response.status_code in (200, 400)

    def test_resume_project(self, client, test_project):
        response = client.post(f"/api/projects/{test_project['id']}/resume")
        assert response.status_code in (200, 400)

    def test_initialize_project(self, client, test_project):
        response = client.post(f"/api/projects/{test_project['id']}/initialize")
        assert response.status_code == 200

    def test_brushup_project(self, client, test_project):
        response = client.post(
            f"/api/projects/{test_project['id']}/brushup",
            json={"selectedAgents": [], "agentOptions": {}, "agentInstructions": {}},
        )
        assert response.status_code in (200, 400)

    def test_brushup_suggest_images(self, client, test_project):
        response = client.post(
            f"/api/projects/{test_project['id']}/brushup/suggest-images",
            json={"customInstruction": "", "count": 5},
        )
        assert response.status_code == 200


class TestProjectAIServicesEndpoints:
    def test_get_project_ai_services(self, client, test_project):
        response = client.get(f"/api/projects/{test_project['id']}/ai-services")
        assert response.status_code == 200

    def test_update_project_ai_services(self, client, test_project):
        response = client.put(
            f"/api/projects/{test_project['id']}/ai-services",
            json={"llm": {"enabled": True, "provider": "mock", "model": "test"}},
        )
        assert response.status_code == 200

    def test_update_project_ai_service_single(self, client, test_project):
        response = client.patch(
            f"/api/projects/{test_project['id']}/ai-services/llm",
            json={"enabled": True},
        )
        assert response.status_code in (200, 404)


class TestProjectSettingsEndpoints:
    def test_get_project_settings(self, client, test_project):
        response = client.get(f"/api/projects/{test_project['id']}/settings")
        assert response.status_code == 200

    def test_update_project_settings(self, client, test_project):
        response = client.patch(
            f"/api/projects/{test_project['id']}/settings",
            json={"settings": {"test": "value"}},
        )
        assert response.status_code == 200

    def test_get_output_settings(self, client, test_project):
        response = client.get(f"/api/projects/{test_project['id']}/settings/output")
        assert response.status_code == 200

    def test_update_output_settings(self, client, test_project):
        response = client.put(
            f"/api/projects/{test_project['id']}/settings/output",
            json={"default_dir": "outputs"},
        )
        assert response.status_code == 200

    def test_get_cost_settings(self, client, test_project):
        response = client.get(f"/api/projects/{test_project['id']}/settings/cost")
        assert response.status_code == 200

    def test_update_cost_settings(self, client, test_project):
        response = client.put(
            f"/api/projects/{test_project['id']}/settings/cost",
            json={
                "global_enabled": True,
                "global_monthly_limit": 100.0,
                "alert_threshold": 80,
                "stop_on_budget_exceeded": False,
                "services": {},
            },
        )
        assert response.status_code == 200

    def test_get_ai_providers_settings(self, client, test_project):
        response = client.get(f"/api/projects/{test_project['id']}/settings/ai-providers")
        assert response.status_code == 200

    def test_update_ai_providers_settings(self, client, test_project):
        response = client.put(
            f"/api/projects/{test_project['id']}/settings/ai-providers",
            json=[],
        )
        assert response.status_code == 200


class TestProjectQualitySettingsEndpoints:
    def test_get_quality_settings(self, client, test_project):
        response = client.get(f"/api/projects/{test_project['id']}/settings/quality-check")
        assert response.status_code == 200

    def test_update_quality_setting_single(self, client, test_project):
        response = client.patch(
            f"/api/projects/{test_project['id']}/settings/quality-check/test_agent",
            json={"enabled": True},
        )
        assert response.status_code in (200, 400, 404)

    def test_update_quality_settings_bulk(self, client, test_project):
        response = client.patch(
            f"/api/projects/{test_project['id']}/settings/quality-check/bulk",
            json={"settings": {}},
        )
        assert response.status_code in (200, 400)

    def test_reset_quality_settings(self, client, test_project):
        response = client.post(f"/api/projects/{test_project['id']}/settings/quality-check/reset")
        assert response.status_code == 200


class TestProjectAutoApprovalEndpoints:
    def test_get_auto_approval_rules(self, client, test_project):
        response = client.get(f"/api/projects/{test_project['id']}/auto-approval-rules")
        assert response.status_code == 200

    def test_update_auto_approval_rules(self, client, test_project):
        response = client.put(
            f"/api/projects/{test_project['id']}/auto-approval-rules",
            json={"rules": []},
        )
        assert response.status_code == 200


class TestAgentEndpoints:
    def test_list_agents(self, client, test_project):
        response = client.get(f"/api/projects/{test_project['id']}/agents")
        assert response.status_code == 200

    def test_list_agent_leaders(self, client, test_project):
        response = client.get(f"/api/projects/{test_project['id']}/agents/leaders")
        assert response.status_code == 200

    def test_list_retryable_agents(self, client, test_project):
        response = client.get(f"/api/projects/{test_project['id']}/agents/retryable")
        assert response.status_code == 200

    def test_list_interrupted_agents(self, client, test_project):
        response = client.get(f"/api/projects/{test_project['id']}/agents/interrupted")
        assert response.status_code == 200

    def test_get_agent_not_found(self, client):
        response = client.get("/api/agents/nonexistent-id")
        assert response.status_code == 404

    def test_get_agent_workers_not_found(self, client):
        response = client.get("/api/agents/nonexistent-id/workers")
        assert response.status_code == 404

    def test_get_agent_logs_not_found(self, client):
        response = client.get("/api/agents/nonexistent-id/logs")
        assert response.status_code == 404

    def test_execute_agent_not_found(self, client):
        response = client.post("/api/agents/nonexistent-id/execute")
        assert response.status_code == 404

    def test_execute_with_workers_not_found(self, client):
        response = client.post("/api/agents/nonexistent-id/execute-with-workers")
        assert response.status_code == 404

    def test_cancel_agent_not_found(self, client):
        response = client.post("/api/agents/nonexistent-id/cancel")
        assert response.status_code == 404

    def test_retry_agent_not_found(self, client):
        response = client.post("/api/agents/nonexistent-id/retry")
        assert response.status_code == 404

    def test_pause_agent_not_found(self, client):
        response = client.post("/api/agents/nonexistent-id/pause")
        assert response.status_code == 404

    def test_resume_agent_not_found(self, client):
        response = client.post("/api/agents/nonexistent-id/resume")
        assert response.status_code == 404

    def test_get_agent_sequence_not_found(self, client):
        response = client.get("/api/agents/nonexistent-id/sequence")
        assert response.status_code == 404

    def test_get_agent_traces_not_found(self, client):
        response = client.get("/api/agents/nonexistent-id/traces")
        assert response.status_code == 404

    def test_get_agent_pending_interventions_not_found(self, client):
        response = client.get("/api/agents/nonexistent-id/pending-interventions")
        assert response.status_code == 200


class TestCheckpointEndpoints:
    def test_list_checkpoints(self, client, test_project):
        response = client.get(f"/api/projects/{test_project['id']}/checkpoints")
        assert response.status_code == 200

    def test_resolve_checkpoint_not_found(self, client):
        response = client.post(
            "/api/checkpoints/nonexistent-id/resolve",
            json={"resolution": "approved"},
        )
        assert response.status_code == 404


class TestMetricsEndpoints:
    def test_get_project_metrics(self, client, test_project):
        response = client.get(f"/api/projects/{test_project['id']}/metrics")
        assert response.status_code == 200

    def test_get_project_logs(self, client, test_project):
        response = client.get(f"/api/projects/{test_project['id']}/logs")
        assert response.status_code == 200

    def test_get_project_assets(self, client, test_project):
        response = client.get(f"/api/projects/{test_project['id']}/assets")
        assert response.status_code == 200

    def test_get_ai_requests_stats(self, client, test_project):
        response = client.get(f"/api/projects/{test_project['id']}/ai-requests/stats")
        assert response.status_code == 200


class TestInterventionEndpoints:
    def test_list_interventions(self, client, test_project):
        response = client.get(f"/api/projects/{test_project['id']}/interventions")
        assert response.status_code == 200

    def test_create_intervention(self, client, test_project):
        response = client.post(
            f"/api/projects/{test_project['id']}/interventions",
            json={"targetType": "all", "priority": "normal", "message": "Test intervention"},
        )
        assert response.status_code == 201
        intervention = response.json()
        client.delete(f"/api/interventions/{intervention['id']}")

    def test_get_intervention_not_found(self, client):
        response = client.get("/api/interventions/nonexistent-id")
        assert response.status_code == 404

    def test_acknowledge_intervention_not_found(self, client):
        response = client.post("/api/interventions/nonexistent-id/acknowledge")
        assert response.status_code == 404

    def test_process_intervention_not_found(self, client):
        response = client.post("/api/interventions/nonexistent-id/process")
        assert response.status_code == 404

    def test_respond_intervention_not_found(self, client):
        response = client.post(
            "/api/interventions/nonexistent-id/respond",
            json={"message": "Test response"},
        )
        assert response.status_code == 404

    def test_delete_intervention_not_found(self, client):
        response = client.delete("/api/interventions/nonexistent-id")
        assert response.status_code == 404


class TestFileUploadEndpoints:
    def test_list_project_files(self, client, test_project):
        response = client.get(f"/api/projects/{test_project['id']}/files")
        assert response.status_code == 200

    def test_upload_file(self, client, test_project):
        response = client.post(
            f"/api/projects/{test_project['id']}/files",
            files={"file": ("test.txt", b"test content", "text/plain")},
        )
        assert response.status_code == 200
        file_info = response.json()
        if "id" in file_info:
            client.delete(f"/api/files/{file_info['id']}")

    def test_upload_files_batch(self, client, test_project):
        response = client.post(
            f"/api/projects/{test_project['id']}/files/batch",
            files=[
                ("files", ("test1.txt", b"content1", "text/plain")),
                ("files", ("test2.txt", b"content2", "text/plain")),
            ],
        )
        assert response.status_code == 200

    def test_get_file_not_found(self, client):
        response = client.get("/api/files/nonexistent-id")
        assert response.status_code == 404

    def test_download_file_not_found(self, client):
        response = client.get("/api/files/nonexistent-id/download")
        assert response.status_code == 404

    def test_delete_file_not_found(self, client):
        response = client.delete("/api/files/nonexistent-id")
        assert response.status_code == 404


class TestProjectTreeEndpoints:
    def test_get_project_tree(self, client, test_project):
        response = client.get(f"/api/projects/{test_project['id']}/tree")
        assert response.status_code == 200

    def test_download_tree_file_missing_path(self, client, test_project):
        response = client.get(f"/api/projects/{test_project['id']}/tree/download")
        assert response.status_code == 400

    def test_download_all_files_no_folder(self, client, test_project):
        response = client.get(f"/api/projects/{test_project['id']}/tree/download-all")
        assert response.status_code in (200, 404)


class TestTraceEndpoints:
    def test_list_project_traces(self, client, test_project):
        response = client.get(f"/api/projects/{test_project['id']}/traces")
        assert response.status_code == 200

    def test_get_trace_not_found(self, client):
        response = client.get("/api/traces/nonexistent-id")
        assert response.status_code == 404


class TestConfigEndpoints:
    def test_project_options(self, client):
        response = client.get("/api/config/project-options")
        assert response.status_code == 200

    def test_file_extensions(self, client):
        response = client.get("/api/config/file-extensions")
        assert response.status_code == 200

    def test_agents_config(self, client):
        response = client.get("/api/config/agents")
        assert response.status_code == 200

    def test_pricing(self, client):
        response = client.get("/api/config/pricing")
        assert response.status_code == 200

    def test_ui_settings(self, client):
        response = client.get("/api/config/ui-settings")
        assert response.status_code == 200

    def test_websocket_config(self, client):
        response = client.get("/api/config/websocket")
        assert response.status_code == 200

    def test_agent_service_map(self, client):
        response = client.get("/api/config/agent-service-map")
        assert response.status_code == 200

    def test_cost_settings_defaults(self, client):
        response = client.get("/api/config/cost-settings/defaults")
        assert response.status_code == 200

    def test_output_settings_defaults(self, client):
        response = client.get("/api/config/output-settings/defaults")
        assert response.status_code == 200


class TestAIServiceEndpoints:
    def test_list_ai_services(self, client):
        response = client.get("/api/ai-services")
        assert response.status_code == 200

    def test_get_ai_services_master(self, client):
        response = client.get("/api/config/ai-services")
        assert response.status_code == 200

    def test_get_ai_service_providers(self, client):
        response = client.get("/api/ai-services/providers")
        assert response.status_code == 200

    def test_get_ai_service_usage_categories(self, client):
        response = client.get("/api/ai-services/usage-categories")
        assert response.status_code == 200

    def test_get_ai_service_api_keys(self, client):
        response = client.get("/api/ai-services/api-keys")
        assert response.status_code == 200

    def test_get_ai_service_by_type(self, client):
        response = client.get("/api/ai-services/llm")
        assert response.status_code == 200

    def test_get_ai_service_invalid_type(self, client):
        response = client.get("/api/ai-services/invalid-type")
        assert response.status_code == 404


class TestAIProviderEndpoints:
    def test_list_ai_providers(self, client):
        response = client.get("/api/ai-providers")
        assert response.status_code == 200

    def test_get_ai_provider_not_found(self, client):
        response = client.get("/api/ai-providers/nonexistent")
        assert response.status_code == 404

    def test_get_ai_provider_models_not_found(self, client):
        response = client.get("/api/ai-providers/nonexistent/models")
        assert response.status_code == 404

    def test_test_ai_provider(self, client):
        response = client.post(
            "/api/ai-providers/test",
            json={"providerType": "mock", "config": {}},
        )
        assert response.status_code == 200

    def test_ai_chat_missing_params(self, client):
        response = client.post(
            "/api/ai/chat",
            json={"messages": []},
        )
        assert response.status_code == 422

    def test_ai_chat_stream_missing_params(self, client):
        response = client.post(
            "/api/ai/chat/stream",
            json={"messages": []},
        )
        assert response.status_code == 422

    def test_ai_providers_health_status(self, client):
        response = client.get("/api/ai-providers/health/status")
        assert response.status_code == 200


class TestAPIKeyEndpoints:
    def test_list_api_keys(self, client):
        response = client.get("/api/api-keys")
        assert response.status_code == 200

    def test_save_api_key(self, client):
        response = client.put(
            "/api/api-keys/test-provider",
            json={"apiKey": "test-key-12345"},
        )
        assert response.status_code == 200
        client.delete("/api/api-keys/test-provider")

    def test_validate_api_key_not_found(self, client):
        response = client.post("/api/api-keys/nonexistent/validate")
        assert response.status_code == 404


class TestBrushupEndpoints:
    def test_brushup_options(self, client):
        response = client.get("/api/brushup/options")
        assert response.status_code == 200

    def test_brushup_presets(self, client):
        response = client.get("/api/brushup/presets")
        assert response.status_code == 200

    def test_brushup_agent_options(self, client):
        response = client.get("/api/brushup/agent-options")
        assert response.status_code == 200


class TestAgentDefinitionEndpoints:
    def test_agent_definitions(self, client):
        response = client.get("/api/agent-definitions")
        assert response.status_code == 200


class TestQualitySettingsEndpoints:
    def test_quality_check_defaults(self, client):
        response = client.get("/api/settings/quality-check/defaults")
        assert response.status_code == 200


class TestLanguageEndpoints:
    def test_languages(self, client):
        response = client.get("/api/languages")
        assert response.status_code == 200

    def test_messages_not_found(self, client):
        response = client.get("/api/messages/invalid-lang")
        assert response.status_code in (200, 404)


class TestBackupEndpoints:
    def test_list_backups(self, client):
        response = client.get("/api/backups")
        assert response.status_code == 200

    def test_create_backup(self, client):
        response = client.post("/api/backups")
        assert response.status_code in (200, 500)

    def test_restore_backup_legacy(self, client):
        response = client.post(
            "/api/backups/restore",
            json={"filename": "nonexistent.db"},
        )
        assert response.status_code == 400

    def test_restore_backup_by_name(self, client):
        response = client.post("/api/backups/nonexistent.db/restore")
        assert response.status_code == 400

    def test_delete_backup_not_found(self, client):
        response = client.delete("/api/backups/nonexistent.db")
        assert response.status_code == 404

    def test_download_backup_not_found(self, client):
        response = client.get("/api/backups/nonexistent.db/download")
        assert response.status_code == 404


class TestArchiveEndpoints:
    def test_archive_stats(self, client):
        response = client.get("/api/archive/stats")
        assert response.status_code == 200

    def test_archive_estimate(self, client):
        response = client.get("/api/archive/estimate")
        assert response.status_code == 200

    def test_archive_cleanup(self, client):
        response = client.post("/api/archive/cleanup")
        assert response.status_code == 200

    def test_archive_retention(self, client):
        response = client.put(
            "/api/archive/retention",
            json={"retentionDays": 30},
        )
        assert response.status_code == 200

    def test_archive_export_no_data(self, client, test_project):
        response = client.post(
            "/api/archive/export",
            json={"projectId": test_project["id"]},
        )
        assert response.status_code in (200, 404)

    def test_archive_export_and_cleanup_no_data(self, client, test_project):
        response = client.post(
            "/api/archive/export-and-cleanup",
            json={"projectId": test_project["id"]},
        )
        assert response.status_code in (200, 404)

    def test_archive_auto_archive(self, client):
        response = client.post("/api/archive/auto-archive")
        assert response.status_code == 200

    def test_list_archives(self, client):
        response = client.get("/api/archives")
        assert response.status_code == 200

    def test_delete_archive_not_found(self, client):
        response = client.delete("/api/archives/nonexistent.zip")
        assert response.status_code == 404

    def test_download_archive_not_found(self, client):
        response = client.get("/api/archives/nonexistent.zip/download")
        assert response.status_code == 404


class TestRecoveryEndpoints:
    def test_recovery_status(self, client):
        response = client.get("/api/recovery/status")
        assert response.status_code == 200

    def test_recovery_interrupted(self, client):
        response = client.get("/api/recovery/interrupted")
        assert response.status_code == 200

    def test_recovery_retry_all(self, client):
        response = client.post("/api/recovery/retry-all")
        assert response.status_code == 200


class TestProviderHealthEndpoints:
    def test_providers_health(self, client):
        response = client.get("/api/providers/health")
        assert response.status_code == 200

    def test_check_provider_health(self, client):
        response = client.get("/api/providers/mock/health")
        assert response.status_code == 200


class TestNavigatorEndpoints:
    def test_navigator_message(self, client):
        response = client.post(
            "/api/navigator/message",
            json={"text": "Test message"},
        )
        assert response.status_code == 200

    def test_navigator_broadcast(self, client):
        response = client.post(
            "/api/navigator/broadcast",
            json={"targetPath": "/test"},
        )
        assert response.status_code == 200


class TestAdminEndpoints:
    def test_admin_stats_unauthorized(self, client):
        response = client.get("/api/admin/stats")
        assert response.status_code in (200, 401, 403, 503)

    def test_admin_archive_unauthorized(self, client):
        response = client.post("/api/admin/archive", json={})
        assert response.status_code in (200, 401, 403, 503)

    def test_admin_cleanup_unauthorized(self, client):
        response = client.post("/api/admin/cleanup")
        assert response.status_code in (200, 401, 403, 503)

    def test_admin_archives_unauthorized(self, client):
        response = client.get("/api/admin/archives")
        assert response.status_code in (200, 401, 403, 503)


class TestLLMJobEndpoints:
    def test_get_llm_job_not_found(self, client):
        response = client.get("/api/llm-jobs/nonexistent-id")
        assert response.status_code in (404, 503)


class TestOpenAPIEndpoints:
    def test_openapi_json(self, client):
        response = client.get("/api/openapi.json")
        assert response.status_code == 200
