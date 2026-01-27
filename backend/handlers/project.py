from flask import Flask,request,jsonify
from datastore import DataStore
from config_loader import get_status_labels
from middleware.logger import get_logger


def register_project_routes(app:Flask,data_store:DataStore,sio):

    @app.route('/api/projects',methods=['GET'])
    def list_projects():
        projects=data_store.get_projects()
        return jsonify(projects)

    @app.route('/api/projects',methods=['POST'])
    def create_project():
        data=request.get_json() or {}
        project=data_store.create_project(data)


        sio.emit('project:updated',project)

        return jsonify(project),201

    @app.route('/api/projects/<project_id>',methods=['PATCH'])
    def update_project(project_id:str):
        data=request.get_json() or {}
        project=data_store.update_project(project_id,data)

        if not project:
            return jsonify({"error":"プロジェクトが見つかりません"}),404


        sio.emit('project:updated',project)

        return jsonify(project)

    @app.route('/api/projects/<project_id>',methods=['DELETE'])
    def delete_project(project_id:str):
        success=data_store.delete_project(project_id)

        if not success:
            return jsonify({"error":"プロジェクトが見つかりません"}),404

        return'',204

    @app.route('/api/projects/<project_id>/start',methods=['POST'])
    def start_project(project_id:str):
        project=data_store.get_project(project_id)

        if not project:
            return jsonify({"error":"プロジェクトが見つかりません"}),404

        current_status=project["status"]
        if current_status not in ("draft","paused"):
            status_label=get_status_labels().get(current_status,current_status)
            return jsonify({
                "error":f"プロジェクトを開始できません。現在のステータス「{status_label}」では開始操作は実行できません。下書きまたは一時停止状態のプロジェクトのみ開始できます。"
            }),400

        from services.llm_job_queue import get_llm_job_queue
        job_queue=get_llm_job_queue()
        cleaned=job_queue.cleanup_project_jobs(project_id)
        if cleaned>0:
            get_logger().info(f"start_project: cleaned {cleaned} incomplete jobs for project {project_id}")

        project=data_store.update_project(project_id,{"status":"running"})
        sio.emit('project:status_changed',{
            "projectId":project_id,
            "status":"running",
            "previousStatus":project.get("status","draft")
        })

        return jsonify(project)

    @app.route('/api/projects/<project_id>/pause',methods=['POST'])
    def pause_project(project_id:str):
        project=data_store.get_project(project_id)

        if not project:
            return jsonify({"error":"プロジェクトが見つかりません"}),404

        current_status=project["status"]
        if current_status!="running":
            status_label=get_status_labels().get(current_status,current_status)
            return jsonify({
                "error":f"プロジェクトを一時停止できません。現在のステータス「{status_label}」では一時停止操作は実行できません。実行中のプロジェクトのみ一時停止できます。"
            }),400

        project=data_store.update_project(project_id,{"status":"paused"})
        sio.emit('project:status_changed',{
            "projectId":project_id,
            "status":"paused",
            "previousStatus":"running"
        })

        return jsonify(project)

    @app.route('/api/projects/<project_id>/resume',methods=['POST'])
    def resume_project(project_id:str):
        project=data_store.get_project(project_id)

        if not project:
            return jsonify({"error":"プロジェクトが見つかりません"}),404

        current_status=project["status"]
        if current_status!="paused":
            status_label=get_status_labels().get(current_status,current_status)
            return jsonify({
                "error":f"プロジェクトを再開できません。現在のステータス「{status_label}」では再開操作は実行できません。一時停止中のプロジェクトのみ再開できます。"
            }),400

        from services.llm_job_queue import get_llm_job_queue
        job_queue=get_llm_job_queue()
        cleaned=job_queue.cleanup_project_jobs(project_id)
        if cleaned>0:
            get_logger().info(f"resume_project: cleaned {cleaned} incomplete jobs for project {project_id}")

        project=data_store.update_project(project_id,{"status":"running"})
        sio.emit('project:status_changed',{
            "projectId":project_id,
            "status":"running",
            "previousStatus":"paused"
        })

        return jsonify(project)

    @app.route('/api/projects/<project_id>/initialize',methods=['POST'])
    def initialize_project(project_id:str):
        project=data_store.get_project(project_id)
        if not project:
            return jsonify({"error":"プロジェクトが見つかりません"}),404

        from services.llm_job_queue import get_llm_job_queue
        job_queue=get_llm_job_queue()
        cleaned=job_queue.cleanup_project_jobs(project_id)
        if cleaned>0:
            get_logger().info(f"initialize_project: cleaned {cleaned} incomplete jobs for project {project_id}")

        project=data_store.initialize_project(project_id)
        sio.emit('project:initialized',{
            "projectId":project_id,
        })

        return jsonify(project)

    @app.route('/api/projects/<project_id>/brushup',methods=['POST'])
    def brushup_project(project_id:str):
        project=data_store.get_project(project_id)
        if not project:
            return jsonify({"error":"プロジェクトが見つかりません"}),404

        if project["status"]!="completed":
            return jsonify({"error":"完了したプロジェクトのみブラッシュアップできます"}),400

        data=request.get_json() or {}
        options={
            "selectedAgents":data.get("selectedAgents",[]),
            "clearAssets":data.get("clearAssets",False),
            "presets":data.get("presets",[]),
            "customInstruction":data.get("customInstruction",""),
            "referenceImageIds":data.get("referenceImageIds",[])
        }

        project=data_store.brushup_project(project_id,options)
        sio.emit('project:status_changed',{
            "projectId":project_id,
            "status":"draft",
            "previousStatus":"completed"
        })

        return jsonify(project)

    @app.route('/api/projects/<project_id>/ai-services',methods=['GET'])
    def get_project_ai_services(project_id:str):
        project=data_store.get_project(project_id)
        if not project:
            return jsonify({"error":"プロジェクトが見つかりません"}),404

        ai_services=data_store.get_ai_services(project_id)
        return jsonify(ai_services)

    @app.route('/api/projects/<project_id>/ai-services',methods=['PUT'])
    def update_project_ai_services(project_id:str):
        project=data_store.get_project(project_id)
        if not project:
            return jsonify({"error":"プロジェクトが見つかりません"}),404

        data=request.get_json() or {}
        ai_services=data_store.update_ai_services(project_id,data)
        if ai_services is None:
            return jsonify({"error":"AI設定の更新に失敗しました"}),400

        sio.emit('project:updated',data_store.get_project(project_id))
        return jsonify(ai_services)

    @app.route('/api/projects/<project_id>/ai-services/<service_type>',methods=['PATCH'])
    def update_project_ai_service(project_id:str,service_type:str):
        project=data_store.get_project(project_id)
        if not project:
            return jsonify({"error":"プロジェクトが見つかりません"}),404

        data=request.get_json() or {}
        result=data_store.update_ai_service(project_id,service_type,data)
        if result is None:
            return jsonify({"error":f"サービスが見つかりません: {service_type}"}),404

        sio.emit('project:updated',data_store.get_project(project_id))
        return jsonify(result)
