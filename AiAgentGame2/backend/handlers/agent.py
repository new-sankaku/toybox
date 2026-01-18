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

    @app.route('/api/agents/<agent_id>', methods=['GET'])
    def get_agent(agent_id: str):
        """Get a single agent by ID"""
        agent = data_store.get_agent(agent_id)
        if not agent:
            return jsonify({"error": "Agent not found"}), 404
        return jsonify(agent)

    @app.route('/api/agents/<agent_id>/logs', methods=['GET'])
    def get_agent_logs(agent_id: str):
        """Get logs for an agent"""
        agent = data_store.get_agent(agent_id)
        if not agent:
            return jsonify({"error": "Agent not found"}), 404

        logs = data_store.get_agent_logs(agent_id)
        return jsonify(logs)

    @app.route('/api/agents/<agent_id>/outputs', methods=['GET'])
    def get_agent_outputs(agent_id: str):
        """Get outputs for an agent"""
        agent = data_store.get_agent(agent_id)
        if not agent:
            return jsonify({"error": "Agent not found"}), 404

        # Mock outputs based on agent type
        outputs = _generate_mock_outputs(agent)
        return jsonify(outputs)

    @app.route('/api/agents/<agent_id>/metrics', methods=['GET'])
    def get_agent_metrics(agent_id: str):
        """Get metrics for an agent"""
        agent = data_store.get_agent(agent_id)
        if not agent:
            return jsonify({"error": "Agent not found"}), 404

        metrics = {
            "agentId": agent_id,
            "tokensUsed": agent.get("tokensUsed", 0),
            "tokensLimit": 100000,
            "executionTimeSeconds": _calculate_execution_time(agent),
            "progress": agent.get("progress", 0),
            "status": agent.get("status", "pending")
        }
        return jsonify(metrics)


def _generate_mock_outputs(agent: dict) -> list:
    """Generate mock outputs based on agent type"""
    agent_type = agent.get("type", "")
    agent_id = agent.get("id", "")

    if agent["status"] == "pending":
        return []

    outputs = []

    if agent_type == "concept":
        outputs.append({
            "id": f"output-{agent_id}-001",
            "type": "document",
            "format": "markdown",
            "title": "ゲームコンセプト",
            "content": "# ゲームコンセプト\n\nシンプルで楽しいゲーム体験を提供します。",
            "createdAt": agent.get("completedAt") or agent.get("startedAt")
        })

    elif agent_type == "design":
        outputs.append({
            "id": f"output-{agent_id}-001",
            "type": "document",
            "format": "markdown",
            "title": "ゲームデザインドキュメント",
            "content": "# ゲームデザイン\n\n## メカニクス\n- 基本操作\n- スコアシステム",
            "createdAt": agent.get("completedAt") or agent.get("startedAt")
        })

    elif agent_type == "scenario":
        outputs.append({
            "id": f"output-{agent_id}-001",
            "type": "document",
            "format": "markdown",
            "title": "シナリオ",
            "content": "# ストーリー\n\n物語の始まり...",
            "createdAt": agent.get("completedAt") or agent.get("startedAt")
        })

    return outputs


def _calculate_execution_time(agent: dict) -> int:
    """Calculate execution time in seconds"""
    from datetime import datetime

    if not agent.get("startedAt"):
        return 0

    start = datetime.fromisoformat(agent["startedAt"].replace("Z", "+00:00"))

    if agent.get("completedAt"):
        end = datetime.fromisoformat(agent["completedAt"].replace("Z", "+00:00"))
    else:
        end = datetime.now(start.tzinfo) if start.tzinfo else datetime.now()

    return int((end - start).total_seconds())
