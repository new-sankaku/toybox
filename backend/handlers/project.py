from flask import Flask,request,jsonify
from config_loaders.checkpoint_config import get_status_labels
from events.events import ProjectUpdated,ProjectStatusChanged,ProjectInitialized
from middleware.logger import get_logger


def register_project_routes(app:Flask,project_service,agent_service,event_bus):

    @app.route('/api/projects',methods=['GET'])
    def list_projects():
        projects=project_service.get_projects()
        return jsonify(projects)

    @app.route('/api/projects',methods=['POST'])
    def create_project():
        data=request.get_json() or {}
        project=project_service.create_project(data)


        event_bus.publish(ProjectUpdated(project_id=project["id"],project=project))

        return jsonify(project),201

    @app.route('/api/projects/<project_id>',methods=['PATCH'])
    def update_project(project_id:str):
        data=request.get_json() or {}
        project=project_service.update_project(project_id,data)

        if not project:
            return jsonify({"error":"プロジェクトが見つかりません"}),404


        event_bus.publish(ProjectUpdated(project_id=project_id,project=project))

        return jsonify(project)

    @app.route('/api/projects/<project_id>',methods=['DELETE'])
    def delete_project(project_id:str):
        success=project_service.delete_project(project_id)

        if not success:
            return jsonify({"error":"プロジェクトが見つかりません"}),404

        return'',204

    @app.route('/api/projects/<project_id>/start',methods=['POST'])
    def start_project(project_id:str):
        project=project_service.get_project(project_id)

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

        project=project_service.update_project(project_id,{"status":"running"})
        event_bus.publish(ProjectStatusChanged(project_id=project_id,status="running",previous_status=project.get("status","draft")))

        return jsonify(project)

    @app.route('/api/projects/<project_id>/pause',methods=['POST'])
    def pause_project(project_id:str):
        project=project_service.get_project(project_id)

        if not project:
            return jsonify({"error":"プロジェクトが見つかりません"}),404

        current_status=project["status"]
        if current_status!="running":
            status_label=get_status_labels().get(current_status,current_status)
            return jsonify({
                "error":f"プロジェクトを一時停止できません。現在のステータス「{status_label}」では一時停止操作は実行できません。実行中のプロジェクトのみ一時停止できます。"
            }),400

        project=project_service.update_project(project_id,{"status":"paused"})
        event_bus.publish(ProjectStatusChanged(project_id=project_id,status="paused",previous_status="running"))

        return jsonify(project)

    @app.route('/api/projects/<project_id>/resume',methods=['POST'])
    def resume_project(project_id:str):
        project=project_service.get_project(project_id)

        if not project:
            return jsonify({"error":"プロジェクトが見つかりません"}),404

        current_status=project["status"]
        resumable_statuses={"paused","interrupted"}
        if current_status not in resumable_statuses:
            status_label=get_status_labels().get(current_status,current_status)
            return jsonify({
                "error":f"プロジェクトを再開できません。現在のステータス「{status_label}」では再開操作は実行できません。一時停止中または中断されたプロジェクトのみ再開できます。"
            }),400

        from services.llm_job_queue import get_llm_job_queue
        job_queue=get_llm_job_queue()
        cleaned=job_queue.cleanup_project_jobs(project_id)
        if cleaned>0:
            get_logger().info(f"resume_project: cleaned {cleaned} incomplete jobs for project {project_id}")

        retried_count=0
        if current_status=="interrupted":
            interrupted_agents=agent_service.get_interrupted_agents(project_id)
            for agent in interrupted_agents:
                result=agent_service.retry_agent(agent["id"])
                if result:
                    retried_count+=1
            if retried_count>0:
                get_logger().info(f"resume_project: auto-retried {retried_count} interrupted agents for project {project_id}")

        project=project_service.update_project(project_id,{"status":"running"})
        event_bus.publish(ProjectStatusChanged(project_id=project_id,status="running",previous_status=current_status,retried_agents=retried_count))

        return jsonify(project)

    @app.route('/api/projects/<project_id>/initialize',methods=['POST'])
    def initialize_project(project_id:str):
        project=project_service.get_project(project_id)
        if not project:
            return jsonify({"error":"プロジェクトが見つかりません"}),404

        from services.llm_job_queue import get_llm_job_queue
        job_queue=get_llm_job_queue()
        cleaned=job_queue.cleanup_project_jobs(project_id)
        if cleaned>0:
            get_logger().info(f"initialize_project: cleaned {cleaned} incomplete jobs for project {project_id}")

        project=project_service.initialize_project(project_id)
        event_bus.publish(ProjectInitialized(project_id=project_id))

        return jsonify(project)

    @app.route('/api/projects/<project_id>/brushup',methods=['POST'])
    def brushup_project(project_id:str):
        project=project_service.get_project(project_id)
        if not project:
            return jsonify({"error":"プロジェクトが見つかりません"}),404

        if project["status"]!="completed":
            return jsonify({"error":"完了したプロジェクトのみブラッシュアップできます"}),400

        data=request.get_json() or {}
        options={
            "selectedAgents":data.get("selectedAgents",[]),
            "agentOptions":data.get("agentOptions",{}),
            "agentInstructions":data.get("agentInstructions",{}),
            "clearAssets":data.get("clearAssets",False),
            "presets":data.get("presets",[]),
            "customInstruction":data.get("customInstruction",""),
            "referenceImageIds":data.get("referenceImageIds",[])
        }

        project=project_service.brushup_project(project_id,options)
        event_bus.publish(ProjectStatusChanged(project_id=project_id,status="draft",previous_status="completed"))

        return jsonify(project)

    @app.route('/api/projects/<project_id>/ai-services',methods=['GET'])
    def get_project_ai_services(project_id:str):
        project=project_service.get_project(project_id)
        if not project:
            return jsonify({"error":"プロジェクトが見つかりません"}),404

        ai_services=project_service.get_ai_services(project_id)
        return jsonify(ai_services)

    @app.route('/api/projects/<project_id>/ai-services',methods=['PUT'])
    def update_project_ai_services(project_id:str):
        project=project_service.get_project(project_id)
        if not project:
            return jsonify({"error":"プロジェクトが見つかりません"}),404

        data=request.get_json() or {}
        ai_services=project_service.update_ai_services(project_id,data)
        if ai_services is None:
            return jsonify({"error":"AI設定の更新に失敗しました"}),400

        event_bus.publish(ProjectUpdated(project_id=project_id,project=project_service.get_project(project_id)))
        return jsonify(ai_services)

    @app.route('/api/projects/<project_id>/ai-services/<service_type>',methods=['PATCH'])
    def update_project_ai_service(project_id:str,service_type:str):
        project=project_service.get_project(project_id)
        if not project:
            return jsonify({"error":"プロジェクトが見つかりません"}),404

        data=request.get_json() or {}
        result=project_service.update_ai_service(project_id,service_type,data)
        if result is None:
            return jsonify({"error":f"サービスが見つかりません: {service_type}"}),404

        event_bus.publish(ProjectUpdated(project_id=project_id,project=project_service.get_project(project_id)))
        return jsonify(result)
