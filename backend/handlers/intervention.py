from flask import Flask,request,jsonify
from datastore import DataStore


def register_intervention_routes(app:Flask,data_store:DataStore,sio):

    @app.route('/api/projects/<project_id>/interventions',methods=['GET'])
    def list_interventions(project_id:str):
        project=data_store.get_project(project_id)
        if not project:
            return jsonify({"error":"Project not found"}),404

        interventions=data_store.get_interventions_by_project(project_id)
        return jsonify(interventions)

    @app.route('/api/projects/<project_id>/interventions',methods=['POST'])
    def create_intervention(project_id:str):
        project=data_store.get_project(project_id)
        if not project:
            return jsonify({"error":"Project not found"}),404

        data=request.get_json() or {}

        target_type=data.get("targetType","all")
        if target_type not in ("all","specific"):
            return jsonify({"error":"Invalid targetType. Must be: all or specific"}),400

        target_agent_id=data.get("targetAgentId")
        if target_type=="specific" and not target_agent_id:
            return jsonify({"error":"targetAgentId is required when targetType is 'specific'"}),400

        if target_agent_id:
            agent=data_store.get_agent(target_agent_id)
            if not agent or agent["projectId"]!=project_id:
                return jsonify({"error":"Agent not found in this project"}),404

        priority=data.get("priority","normal")
        if priority not in ("normal","urgent"):
            return jsonify({"error":"Invalid priority. Must be: normal or urgent"}),400

        message=data.get("message","").strip()
        if not message:
            return jsonify({"error":"Message is required"}),400

        attached_file_ids=data.get("attachedFileIds",[])

        intervention=data_store.create_intervention(
            project_id=project_id,
            target_type=target_type,
            target_agent_id=target_agent_id,
            priority=priority,
            message=message,
            attached_file_ids=attached_file_ids
        )


        sio.emit('intervention:created',{
            "interventionId":intervention["id"],
            "projectId":project_id,
            "intervention":intervention
        },room=f"project:{project_id}")


        if priority=="urgent":
            data_store.pause_project(project_id)
            sio.emit('project:paused',{
                "projectId":project_id,
                "reason":"urgent_intervention",
                "interventionId":intervention["id"]
            },room=f"project:{project_id}")

        return jsonify(intervention),201

    @app.route('/api/interventions/<intervention_id>',methods=['GET'])
    def get_intervention(intervention_id:str):
        intervention=data_store.get_intervention(intervention_id)
        if not intervention:
            return jsonify({"error":"Intervention not found"}),404
        return jsonify(intervention)

    @app.route('/api/interventions/<intervention_id>/acknowledge',methods=['POST'])
    def acknowledge_intervention(intervention_id:str):
        intervention=data_store.acknowledge_intervention(intervention_id)
        if not intervention:
            return jsonify({"error":"Intervention not found"}),404

        sio.emit('intervention:acknowledged',{
            "interventionId":intervention_id,
            "projectId":intervention["projectId"],
            "intervention":intervention
        },room=f"project:{intervention['projectId']}")

        return jsonify(intervention)

    @app.route('/api/interventions/<intervention_id>/process',methods=['POST'])
    def process_intervention(intervention_id:str):
        intervention=data_store.process_intervention(intervention_id)
        if not intervention:
            return jsonify({"error":"Intervention not found"}),404

        sio.emit('intervention:processed',{
            "interventionId":intervention_id,
            "projectId":intervention["projectId"],
            "intervention":intervention
        },room=f"project:{intervention['projectId']}")

        return jsonify(intervention)

    @app.route('/api/interventions/<intervention_id>',methods=['DELETE'])
    def delete_intervention(intervention_id:str):
        intervention=data_store.get_intervention(intervention_id)
        if not intervention:
            return jsonify({"error":"Intervention not found"}),404

        project_id=intervention["projectId"]
        success=data_store.delete_intervention(intervention_id)
        if not success:
            return jsonify({"error":"Failed to delete intervention"}),500

        sio.emit('intervention:deleted',{
            "interventionId":intervention_id,
            "projectId":project_id
        },room=f"project:{project_id}")

        return'',204
