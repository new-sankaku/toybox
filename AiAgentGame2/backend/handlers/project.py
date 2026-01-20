from flask import Flask,request,jsonify
from testdata import TestDataStore

STATUS_LABELS = {
    "draft":"下書き",
    "running":"実行中",
    "paused":"一時停止",
    "completed":"完了",
    "failed":"エラー"
}


def register_project_routes(app:Flask,data_store:TestDataStore,sio):

    @app.route('/api/projects',methods=['GET'])
    def list_projects():
        projects = data_store.get_projects()
        return jsonify(projects)

    @app.route('/api/projects',methods=['POST'])
    def create_project():
        data = request.get_json() or {}
        project = data_store.create_project(data)


        sio.emit('project:updated',project)

        return jsonify(project),201

    @app.route('/api/projects/<project_id>',methods=['PATCH'])
    def update_project(project_id:str):
        data = request.get_json() or {}
        project = data_store.update_project(project_id,data)

        if not project:
            return jsonify({"error":"プロジェクトが見つかりません"}),404


        sio.emit('project:updated',project)

        return jsonify(project)

    @app.route('/api/projects/<project_id>',methods=['DELETE'])
    def delete_project(project_id:str):
        success = data_store.delete_project(project_id)

        if not success:
            return jsonify({"error":"プロジェクトが見つかりません"}),404

        return '',204

    @app.route('/api/projects/<project_id>/start',methods=['POST'])
    def start_project(project_id:str):
        project = data_store.get_project(project_id)

        if not project:
            return jsonify({"error":"プロジェクトが見つかりません"}),404

        current_status = project["status"]
        if current_status not in ("draft","paused"):
            status_label = STATUS_LABELS.get(current_status,current_status)
            return jsonify({
                "error":f"プロジェクトを開始できません。現在のステータス「{status_label}」では開始操作は実行できません。下書きまたは一時停止状態のプロジェクトのみ開始できます。"
            }),400

        project = data_store.update_project(project_id,{"status":"running"})
        sio.emit('project:status_changed',{
            "projectId":project_id,
            "status":"running",
            "previousStatus":project.get("status","draft")
        })

        return jsonify(project)

    @app.route('/api/projects/<project_id>/pause',methods=['POST'])
    def pause_project(project_id:str):
        project = data_store.get_project(project_id)

        if not project:
            return jsonify({"error":"プロジェクトが見つかりません"}),404

        current_status = project["status"]
        if current_status != "running":
            status_label = STATUS_LABELS.get(current_status,current_status)
            return jsonify({
                "error":f"プロジェクトを一時停止できません。現在のステータス「{status_label}」では一時停止操作は実行できません。実行中のプロジェクトのみ一時停止できます。"
            }),400

        project = data_store.update_project(project_id,{"status":"paused"})
        sio.emit('project:status_changed',{
            "projectId":project_id,
            "status":"paused",
            "previousStatus":"running"
        })

        return jsonify(project)

    @app.route('/api/projects/<project_id>/resume',methods=['POST'])
    def resume_project(project_id:str):
        project = data_store.get_project(project_id)

        if not project:
            return jsonify({"error":"プロジェクトが見つかりません"}),404

        current_status = project["status"]
        if current_status != "paused":
            status_label = STATUS_LABELS.get(current_status,current_status)
            return jsonify({
                "error":f"プロジェクトを再開できません。現在のステータス「{status_label}」では再開操作は実行できません。一時停止中のプロジェクトのみ再開できます。"
            }),400

        project = data_store.update_project(project_id,{"status":"running"})
        sio.emit('project:status_changed',{
            "projectId":project_id,
            "status":"running",
            "previousStatus":"paused"
        })

        return jsonify(project)

    @app.route('/api/projects/<project_id>/initialize',methods=['POST'])
    def initialize_project(project_id:str):
        project = data_store.get_project(project_id)
        if not project:
            return jsonify({"error":"プロジェクトが見つかりません"}),404

        project = data_store.initialize_project(project_id)
        sio.emit('project:initialized',{
            "projectId":project_id,
        })

        return jsonify(project)
