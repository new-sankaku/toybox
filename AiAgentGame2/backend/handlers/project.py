"""
Project REST API Handlers
"""

from flask import Flask, request, jsonify
from testdata import TestDataStore
from simulation.agent_simulation import AgentSimulator

# ステータスの日本語表示
STATUS_LABELS = {
    "draft": "下書き",
    "running": "実行中",
    "paused": "一時停止",
    "completed": "完了",
    "failed": "エラー"
}


def register_project_routes(app: Flask, data_store: TestDataStore, sio):
    """Register project-related REST API routes"""

    simulator = AgentSimulator(data_store, sio)

    @app.route('/api/projects', methods=['GET'])
    def list_projects():
        """Get all projects"""
        projects = data_store.get_projects()
        return jsonify(projects)

    @app.route('/api/projects/<project_id>', methods=['GET'])
    def get_project(project_id: str):
        """Get a single project by ID"""
        project = data_store.get_project(project_id)
        if not project:
            return jsonify({"error": "プロジェクトが見つかりません"}), 404
        return jsonify(project)

    @app.route('/api/projects', methods=['POST'])
    def create_project():
        """Create a new project"""
        data = request.get_json() or {}
        project = data_store.create_project(data)

        # Emit project creation event
        sio.emit('project:updated', project)

        return jsonify(project), 201

    @app.route('/api/projects/<project_id>', methods=['PATCH'])
    def update_project(project_id: str):
        """Update an existing project"""
        data = request.get_json() or {}
        project = data_store.update_project(project_id, data)

        if not project:
            return jsonify({"error": "プロジェクトが見つかりません"}), 404

        # Emit update event
        sio.emit('project:updated', project)

        return jsonify(project)

    @app.route('/api/projects/<project_id>', methods=['DELETE'])
    def delete_project(project_id: str):
        """Delete a project"""
        success = data_store.delete_project(project_id)

        if not success:
            return jsonify({"error": "プロジェクトが見つかりません"}), 404

        return '', 204

    @app.route('/api/projects/<project_id>/start', methods=['POST'])
    def start_project(project_id: str):
        """Start a project execution"""
        project = data_store.get_project(project_id)

        if not project:
            return jsonify({"error": "プロジェクトが見つかりません"}), 404

        current_status = project["status"]
        if current_status not in ("draft", "paused"):
            status_label = STATUS_LABELS.get(current_status, current_status)
            return jsonify({
                "error": f"プロジェクトを開始できません。現在のステータス「{status_label}」では開始操作は実行できません。下書きまたは一時停止状態のプロジェクトのみ開始できます。"
            }), 400

        # Update project status
        project = data_store.update_project(project_id, {"status": "running"})

        # Emit status change
        sio.emit('project:status_changed', {
            "projectId": project_id,
            "status": "running",
            "previousStatus": project.get("status", "draft")
        })

        # Start agent simulation
        simulator.start_simulation(project_id)

        return jsonify(project)

    @app.route('/api/projects/<project_id>/pause', methods=['POST'])
    def pause_project(project_id: str):
        """Pause a running project"""
        project = data_store.get_project(project_id)

        if not project:
            return jsonify({"error": "プロジェクトが見つかりません"}), 404

        current_status = project["status"]
        if current_status != "running":
            status_label = STATUS_LABELS.get(current_status, current_status)
            return jsonify({
                "error": f"プロジェクトを一時停止できません。現在のステータス「{status_label}」では一時停止操作は実行できません。実行中のプロジェクトのみ一時停止できます。"
            }), 400

        # Update project status
        project = data_store.update_project(project_id, {"status": "paused"})

        # Stop simulation
        simulator.stop_simulation(project_id)

        # Emit status change
        sio.emit('project:status_changed', {
            "projectId": project_id,
            "status": "paused",
            "previousStatus": "running"
        })

        return jsonify(project)

    @app.route('/api/projects/<project_id>/resume', methods=['POST'])
    def resume_project(project_id: str):
        """Resume a paused project"""
        project = data_store.get_project(project_id)

        if not project:
            return jsonify({"error": "プロジェクトが見つかりません"}), 404

        current_status = project["status"]
        if current_status != "paused":
            status_label = STATUS_LABELS.get(current_status, current_status)
            return jsonify({
                "error": f"プロジェクトを再開できません。現在のステータス「{status_label}」では再開操作は実行できません。一時停止中のプロジェクトのみ再開できます。"
            }), 400

        # Update project status
        project = data_store.update_project(project_id, {"status": "running"})

        # Resume simulation
        simulator.start_simulation(project_id)

        # Emit status change
        sio.emit('project:status_changed', {
            "projectId": project_id,
            "status": "running",
            "previousStatus": "paused"
        })

        return jsonify(project)

    @app.route('/api/projects/<project_id>/initialize', methods=['POST'])
    def initialize_project(project_id: str):
        """Initialize/reset a project - clears all data"""
        project = data_store.get_project(project_id)

        if not project:
            return jsonify({"error": "プロジェクトが見つかりません"}), 404

        # Stop any running simulation first
        simulator.stop_simulation(project_id)

        # Initialize project
        project = data_store.initialize_project(project_id)

        # Emit reset event
        sio.emit('project:initialized', {
            "projectId": project_id,
        })

        return jsonify(project)
