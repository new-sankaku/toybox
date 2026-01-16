"""
Project REST API Handlers
"""

from flask import Flask, request, jsonify
from mock_data import MockDataStore
from simulation.agent_simulation import AgentSimulator


def register_project_routes(app: Flask, data_store: MockDataStore, sio):
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
            return jsonify({"error": "Project not found"}), 404
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
            return jsonify({"error": "Project not found"}), 404

        # Emit update event
        sio.emit('project:updated', project)

        return jsonify(project)

    @app.route('/api/projects/<project_id>', methods=['DELETE'])
    def delete_project(project_id: str):
        """Delete a project"""
        success = data_store.delete_project(project_id)

        if not success:
            return jsonify({"error": "Project not found"}), 404

        return '', 204

    @app.route('/api/projects/<project_id>/start', methods=['POST'])
    def start_project(project_id: str):
        """Start a project execution"""
        project = data_store.get_project(project_id)

        if not project:
            return jsonify({"error": "Project not found"}), 404

        if project["status"] not in ("draft", "paused"):
            return jsonify({"error": f"Cannot start project in {project['status']} status"}), 400

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
            return jsonify({"error": "Project not found"}), 404

        if project["status"] != "running":
            return jsonify({"error": "Can only pause running projects"}), 400

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
            return jsonify({"error": "Project not found"}), 404

        if project["status"] != "paused":
            return jsonify({"error": "Can only resume paused projects"}), 400

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
