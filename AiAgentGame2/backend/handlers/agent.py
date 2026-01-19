"""
Agent REST API Handlers
"""

from flask import Flask, jsonify
from testdata import TestDataStore


def register_agent_routes(app: Flask, data_store: TestDataStore, sio):
    """Register agent-related REST API routes"""

    @app.route('/api/projects/<project_id>/agents', methods=['GET'])
    def list_project_agents(project_id: str):
        """Get all agents for a project"""
        project = data_store.get_project(project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404

        agents = data_store.get_agents_by_project(project_id)
        return jsonify(agents)

    @app.route('/api/agents/<agent_id>/logs', methods=['GET'])
    def get_agent_logs(agent_id: str):
        """Get logs for an agent"""
        agent = data_store.get_agent(agent_id)
        if not agent:
            return jsonify({"error": "Agent not found"}), 404

        logs = data_store.get_agent_logs(agent_id)
        return jsonify(logs)
