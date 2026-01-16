"""
Metrics REST API Handlers
"""

from flask import Flask, jsonify
from mock_data import MockDataStore


def register_metrics_routes(app: Flask, data_store: MockDataStore):
    """Register metrics-related REST API routes"""

    @app.route('/api/projects/<project_id>/metrics', methods=['GET'])
    def get_project_metrics(project_id: str):
        """Get metrics for a project"""
        project = data_store.get_project(project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404

        metrics = data_store.get_project_metrics(project_id)

        if not metrics:
            # Return default metrics if none exist
            metrics = {
                "projectId": project_id,
                "totalTokensUsed": 0,
                "estimatedTotalTokens": 50000,
                "elapsedTimeSeconds": 0,
                "estimatedRemainingSeconds": 0,
                "estimatedEndTime": None,
                "completedTasks": 0,
                "totalTasks": 0,
                "progressPercent": 0,
                "currentPhase": project.get("currentPhase", 1),
                "phaseName": _get_phase_name(project.get("currentPhase", 1))
            }

        return jsonify(metrics)


def _get_phase_name(phase: int) -> str:
    """Get human-readable phase name"""
    phase_names = {
        1: "Phase 1: 企画・設計",
        2: "Phase 2: 実装",
        3: "Phase 3: 統合・テスト"
    }
    return phase_names.get(phase, f"Phase {phase}")
