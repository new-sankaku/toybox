from flask import Flask,request,jsonify
from events.events import InterventionCreated,InterventionAcknowledged,InterventionProcessed,InterventionDeleted,InterventionResponseAdded,ProjectPaused,AgentActivated,AgentPaused,AgentResumed,AgentWaitingResponse


def register_intervention_routes(app:Flask,project_service,agent_service,intervention_service,event_bus):

    def _get_execution_service():
        if hasattr(app,"agent_execution_service"):
            return app.agent_execution_service
        return None

    @app.route('/api/projects/<project_id>/interventions',methods=['GET'])
    def list_interventions(project_id:str):
        project=project_service.get_project(project_id)
        if not project:
            return jsonify({"error":"プロジェクトが見つかりません"}),404

        interventions=intervention_service.get_interventions_by_project(project_id)
        return jsonify(interventions)

    @app.route('/api/projects/<project_id>/interventions',methods=['POST'])
    def create_intervention(project_id:str):
        project=project_service.get_project(project_id)
        if not project:
            return jsonify({"error":"プロジェクトが見つかりません"}),404

        data=request.get_json() or {}

        target_type=data.get("targetType","all")
        if target_type not in ("all","specific"):
            return jsonify({"error":"対象タイプが不正です。all または specific を指定してください"}),400

        target_agent_id=data.get("targetAgentId")
        if target_type=="specific" and not target_agent_id:
            return jsonify({"error":"specific の場合は targetAgentId が必須です"}),400

        if target_agent_id:
            agent=agent_service.get_agent(target_agent_id)
            if not agent or agent["projectId"]!=project_id:
                return jsonify({"error":"このプロジェクトにエージェントが見つかりません"}),404

        priority=data.get("priority","normal")
        if priority not in ("normal","urgent"):
            return jsonify({"error":"優先度が不正です。normal または urgent を指定してください"}),400

        message=data.get("message","").strip()
        if not message:
            return jsonify({"error":"メッセージは必須です"}),400

        attached_file_ids=data.get("attachedFileIds",[])

        intervention=intervention_service.create_intervention(
            project_id=project_id,
            target_type=target_type,
            target_agent_id=target_agent_id,
            priority=priority,
            message=message,
            attached_file_ids=attached_file_ids
        )


        event_bus.publish(InterventionCreated(project_id=project_id,intervention_id=intervention["id"],intervention=intervention))

        if priority=="urgent":
            project_service.pause_project(project_id)
            event_bus.publish(ProjectPaused(project_id=project_id,reason="urgent_intervention",intervention_id=intervention["id"]))

        if target_type=="specific" and target_agent_id:
            activation_result=agent_service.activate_agent_for_intervention(target_agent_id,intervention["id"])
            if activation_result.get("activated"):
                activated_agent=activation_result["agent"]
                event_bus.publish(AgentActivated(project_id=project_id,agent_id=target_agent_id,agent=activated_agent,previous_status=activation_result.get("previousStatus",""),intervention_id=intervention["id"]))
                for paused_agent in activation_result.get("pausedAgents",[]):
                    event_bus.publish(AgentPaused(project_id=project_id,agent_id=paused_agent["id"],agent=paused_agent,reason="subsequent_phase_pause"))
                if activation_result.get("previousStatus")!="waiting_response":
                    execution_service=_get_execution_service()
                    if execution_service:
                        execution_service.re_execute_agent(project_id,target_agent_id)
            intervention["activationResult"]=activation_result

        return jsonify(intervention),201

    @app.route('/api/interventions/<intervention_id>',methods=['GET'])
    def get_intervention(intervention_id:str):
        intervention=intervention_service.get_intervention(intervention_id)
        if not intervention:
            return jsonify({"error":"介入が見つかりません"}),404
        return jsonify(intervention)

    @app.route('/api/interventions/<intervention_id>/acknowledge',methods=['POST'])
    def acknowledge_intervention(intervention_id:str):
        intervention=intervention_service.acknowledge_intervention(intervention_id)
        if not intervention:
            return jsonify({"error":"介入が見つかりません"}),404

        event_bus.publish(InterventionAcknowledged(project_id=intervention["projectId"],intervention_id=intervention_id,intervention=intervention))

        return jsonify(intervention)

    @app.route('/api/interventions/<intervention_id>/process',methods=['POST'])
    def process_intervention(intervention_id:str):
        intervention=intervention_service.process_intervention(intervention_id)
        if not intervention:
            return jsonify({"error":"介入が見つかりません"}),404

        event_bus.publish(InterventionProcessed(project_id=intervention["projectId"],intervention_id=intervention_id,intervention=intervention))

        return jsonify(intervention)

    @app.route('/api/interventions/<intervention_id>',methods=['DELETE'])
    def delete_intervention(intervention_id:str):
        intervention=intervention_service.get_intervention(intervention_id)
        if not intervention:
            return jsonify({"error":"介入が見つかりません"}),404

        project_id=intervention["projectId"]
        success=intervention_service.delete_intervention(intervention_id)
        if not success:
            return jsonify({"error":"介入の削除に失敗しました"}),500

        event_bus.publish(InterventionDeleted(project_id=project_id,intervention_id=intervention_id))

        return'',204

    @app.route('/api/interventions/<intervention_id>/respond',methods=['POST'])
    def respond_to_intervention(intervention_id:str):
        intervention=intervention_service.get_intervention(intervention_id)
        if not intervention:
            return jsonify({"error":"介入が見つかりません"}),404

        data=request.get_json() or {}
        message=data.get("message","").strip()
        if not message:
            return jsonify({"error":"メッセージは必須です"}),400

        result=intervention_service.respond_to_intervention(intervention_id,message)
        if not result:
            return jsonify({"error":"返答の追加に失敗しました"}),500

        project_id=intervention["projectId"]
        event_bus.publish(InterventionResponseAdded(project_id=project_id,intervention_id=intervention_id,intervention=result,sender="operator"))

        if intervention.get("targetAgentId"):
            agent=agent_service.get_agent(intervention["targetAgentId"])
            if agent and agent.get("status")=="running":
                event_bus.publish(AgentResumed(project_id=project_id,agent_id=agent["id"],agent=agent,reason="operator_response"))

        return jsonify(result)

    @app.route('/api/interventions/<intervention_id>/agent-question',methods=['POST'])
    def agent_question(intervention_id:str):
        intervention=intervention_service.get_intervention(intervention_id)
        if not intervention:
            return jsonify({"error":"介入が見つかりません"}),404

        data=request.get_json() or {}
        message=data.get("message","").strip()
        agent_id=data.get("agentId")

        if not message:
            return jsonify({"error":"メッセージは必須です"}),400
        if not agent_id:
            return jsonify({"error":"agentIdは必須です"}),400

        result=intervention_service.add_intervention_response(intervention_id,"agent",message,agent_id)
        if not result:
            return jsonify({"error":"質問の追加に失敗しました"}),500

        project_id=intervention["projectId"]
        agent=agent_service.get_agent(agent_id)

        event_bus.publish(InterventionResponseAdded(project_id=project_id,intervention_id=intervention_id,intervention=result,sender="agent",agent_id=agent_id))

        if agent:
            event_bus.publish(AgentWaitingResponse(project_id=project_id,agent_id=agent_id,agent=agent,intervention_id=intervention_id,question=message))

        return jsonify(result)
