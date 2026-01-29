from flask import Flask, request, jsonify
from datastore import DataStore


def register_intervention_routes(app: Flask, data_store: DataStore, sio):
    def _get_execution_service():
        if hasattr(app, "agent_execution_service"):
            return app.agent_execution_service
        return None

    @app.route("/api/projects/<project_id>/interventions", methods=["GET"])
    def list_interventions(project_id: str):
        project = data_store.get_project(project_id)
        if not project:
            return jsonify({"error": "プロジェクトが見つかりません"}), 404

        interventions = data_store.get_interventions_by_project(project_id)
        return jsonify(interventions)

    @app.route("/api/projects/<project_id>/interventions", methods=["POST"])
    def create_intervention(project_id: str):
        project = data_store.get_project(project_id)
        if not project:
            return jsonify({"error": "プロジェクトが見つかりません"}), 404

        data = request.get_json() or {}

        target_type = data.get("targetType", "all")
        if target_type not in ("all", "specific"):
            return jsonify({"error": "対象タイプが不正です。all または specific を指定してください"}), 400

        target_agent_id = data.get("targetAgentId")
        if target_type == "specific" and not target_agent_id:
            return jsonify({"error": "specific の場合は targetAgentId が必須です"}), 400

        if target_agent_id:
            agent = data_store.get_agent(target_agent_id)
            if not agent or agent["projectId"] != project_id:
                return jsonify({"error": "このプロジェクトにエージェントが見つかりません"}), 404

        priority = data.get("priority", "normal")
        if priority not in ("normal", "urgent"):
            return jsonify({"error": "優先度が不正です。normal または urgent を指定してください"}), 400

        message = data.get("message", "").strip()
        if not message:
            return jsonify({"error": "メッセージは必須です"}), 400

        attached_file_ids = data.get("attachedFileIds", [])

        intervention = data_store.create_intervention(
            project_id=project_id,
            target_type=target_type,
            target_agent_id=target_agent_id,
            priority=priority,
            message=message,
            attached_file_ids=attached_file_ids,
        )

        sio.emit(
            "intervention:created",
            {"interventionId": intervention["id"], "projectId": project_id, "intervention": intervention},
            room=f"project:{project_id}",
        )

        if priority == "urgent":
            data_store.pause_project(project_id)
            sio.emit(
                "project:paused",
                {"projectId": project_id, "reason": "urgent_intervention", "interventionId": intervention["id"]},
                room=f"project:{project_id}",
            )

        if target_type == "specific" and target_agent_id:
            activation_result = data_store.activate_agent_for_intervention(target_agent_id, intervention["id"])
            if activation_result.get("activated"):
                activated_agent = activation_result["agent"]
                sio.emit(
                    "agent:activated",
                    {
                        "agentId": target_agent_id,
                        "projectId": project_id,
                        "agent": activated_agent,
                        "previousStatus": activation_result.get("previousStatus"),
                        "interventionId": intervention["id"],
                    },
                    room=f"project:{project_id}",
                )
                for paused_agent in activation_result.get("pausedAgents", []):
                    sio.emit(
                        "agent:paused",
                        {
                            "agentId": paused_agent["id"],
                            "projectId": project_id,
                            "agent": paused_agent,
                            "reason": "subsequent_phase_pause",
                        },
                        room=f"project:{project_id}",
                    )
                if activation_result.get("previousStatus") != "waiting_response":
                    execution_service = _get_execution_service()
                    if execution_service:
                        execution_service.re_execute_agent(project_id, target_agent_id)
            intervention["activationResult"] = activation_result

        return jsonify(intervention), 201

    @app.route("/api/interventions/<intervention_id>", methods=["GET"])
    def get_intervention(intervention_id: str):
        intervention = data_store.get_intervention(intervention_id)
        if not intervention:
            return jsonify({"error": "介入が見つかりません"}), 404
        return jsonify(intervention)

    @app.route("/api/interventions/<intervention_id>/acknowledge", methods=["POST"])
    def acknowledge_intervention(intervention_id: str):
        intervention = data_store.acknowledge_intervention(intervention_id)
        if not intervention:
            return jsonify({"error": "介入が見つかりません"}), 404

        sio.emit(
            "intervention:acknowledged",
            {"interventionId": intervention_id, "projectId": intervention["projectId"], "intervention": intervention},
            room=f"project:{intervention['projectId']}",
        )

        return jsonify(intervention)

    @app.route("/api/interventions/<intervention_id>/process", methods=["POST"])
    def process_intervention(intervention_id: str):
        intervention = data_store.process_intervention(intervention_id)
        if not intervention:
            return jsonify({"error": "介入が見つかりません"}), 404

        sio.emit(
            "intervention:processed",
            {"interventionId": intervention_id, "projectId": intervention["projectId"], "intervention": intervention},
            room=f"project:{intervention['projectId']}",
        )

        return jsonify(intervention)

    @app.route("/api/interventions/<intervention_id>", methods=["DELETE"])
    def delete_intervention(intervention_id: str):
        intervention = data_store.get_intervention(intervention_id)
        if not intervention:
            return jsonify({"error": "介入が見つかりません"}), 404

        project_id = intervention["projectId"]
        success = data_store.delete_intervention(intervention_id)
        if not success:
            return jsonify({"error": "介入の削除に失敗しました"}), 500

        sio.emit(
            "intervention:deleted",
            {"interventionId": intervention_id, "projectId": project_id},
            room=f"project:{project_id}",
        )

        return "", 204

    @app.route("/api/interventions/<intervention_id>/respond", methods=["POST"])
    def respond_to_intervention(intervention_id: str):
        intervention = data_store.get_intervention(intervention_id)
        if not intervention:
            return jsonify({"error": "介入が見つかりません"}), 404

        data = request.get_json() or {}
        message = data.get("message", "").strip()
        if not message:
            return jsonify({"error": "メッセージは必須です"}), 400

        result = data_store.respond_to_intervention(intervention_id, message)
        if not result:
            return jsonify({"error": "返答の追加に失敗しました"}), 500

        project_id = intervention["projectId"]
        sio.emit(
            "intervention:response_added",
            {"interventionId": intervention_id, "projectId": project_id, "intervention": result, "sender": "operator"},
            room=f"project:{project_id}",
        )

        if intervention.get("targetAgentId"):
            agent = data_store.get_agent(intervention["targetAgentId"])
            if agent and agent.get("status") == "running":
                sio.emit(
                    "agent:resumed",
                    {"agentId": agent["id"], "projectId": project_id, "agent": agent, "reason": "operator_response"},
                    room=f"project:{project_id}",
                )

        return jsonify(result)

    @app.route("/api/interventions/<intervention_id>/agent-question", methods=["POST"])
    def agent_question(intervention_id: str):
        intervention = data_store.get_intervention(intervention_id)
        if not intervention:
            return jsonify({"error": "介入が見つかりません"}), 404

        data = request.get_json() or {}
        message = data.get("message", "").strip()
        agent_id = data.get("agentId")

        if not message:
            return jsonify({"error": "メッセージは必須です"}), 400
        if not agent_id:
            return jsonify({"error": "agentIdは必須です"}), 400

        result = data_store.add_intervention_response(intervention_id, "agent", message, agent_id)
        if not result:
            return jsonify({"error": "質問の追加に失敗しました"}), 500

        project_id = intervention["projectId"]
        agent = data_store.get_agent(agent_id)

        sio.emit(
            "intervention:response_added",
            {
                "interventionId": intervention_id,
                "projectId": project_id,
                "intervention": result,
                "sender": "agent",
                "agentId": agent_id,
            },
            room=f"project:{project_id}",
        )

        if agent:
            sio.emit(
                "agent:waiting_response",
                {
                    "agentId": agent_id,
                    "projectId": project_id,
                    "agent": agent,
                    "interventionId": intervention_id,
                    "question": message,
                },
                room=f"project:{project_id}",
            )

        return jsonify(result)
