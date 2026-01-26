from flask import Flask,request,jsonify
from datastore import DataStore


def register_checkpoint_routes(app:Flask,data_store:DataStore,sio):

    @app.route('/api/projects/<project_id>/checkpoints',methods=['GET'])
    def list_project_checkpoints(project_id:str):
        project=data_store.get_project(project_id)
        if not project:
            return jsonify({"error":"プロジェクトが見つかりません"}),404

        checkpoints=data_store.get_checkpoints_by_project(project_id)
        return jsonify(checkpoints)

    @app.route('/api/checkpoints/<checkpoint_id>/resolve',methods=['POST'])
    def resolve_checkpoint(checkpoint_id:str):
        data=request.get_json() or {}
        resolution=data.get("resolution")
        feedback=data.get("feedback")

        if resolution not in ("approved","rejected","revision_requested"):
            return jsonify({"error":"解決タイプが不正です。approved, rejected, revision_requested のいずれかを指定してください"}),400

        checkpoint=data_store.resolve_checkpoint(checkpoint_id,resolution,feedback)

        if not checkpoint:
            return jsonify({"error":"チェックポイントが見つかりません"}),404

        agent_id=checkpoint["agentId"]
        agent=data_store.get_agent(agent_id)
        agent_status=agent["status"] if agent else None
        sio.emit('checkpoint:resolved',{
            "checkpointId":checkpoint_id,
            "projectId":checkpoint["projectId"],
            "agentId":agent_id,
            "resolution":resolution,
            "feedback":feedback,
            "agentStatus":agent_status
        })

        return jsonify(checkpoint)
