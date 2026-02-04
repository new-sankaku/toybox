from flask import Flask,jsonify,request
from events.events import AssetUpdated,AssetBulkUpdated,AssetRegenerationRequested


def register_metrics_routes(app:Flask,project_service,agent_service,workflow_service,event_bus=None):

    @app.route('/api/projects/<project_id>/ai-requests/stats',methods=['GET'])
    def get_ai_request_stats(project_id:str):
        """Get AI request statistics for a project"""
        project=project_service.get_project(project_id)
        if not project:
            return jsonify({"error":"Project not found"}),404


        agents=agent_service.get_agents_by_project(project_id)

        total=len(agents)
        processing=len([a for a in agents if a["status"]=="running"])
        pending=len([a for a in agents if a["status"]=="pending"])
        completed=len([a for a in agents if a["status"]=="completed"])
        failed=len([a for a in agents if a["status"]=="failed"])

        return jsonify({
            "total":total,
            "processing":processing,
            "pending":pending,
            "completed":completed,
            "failed":failed
        })

    @app.route('/api/projects/<project_id>/metrics',methods=['GET'])
    def get_project_metrics(project_id:str):
        project=project_service.get_project(project_id)
        if not project:
            return jsonify({"error":"Project not found"}),404

        metrics=project_service.get_project_metrics(project_id)

        if not metrics:
            metrics={
                "projectId":project_id,
                "totalTokensUsed":0,
                "estimatedTotalTokens":50000,
                "elapsedTimeSeconds":0,
                "estimatedRemainingSeconds":0,
                "estimatedEndTime":None,
                "completedTasks":0,
                "totalTasks":0,
                "progressPercent":0,
                "currentPhase":project.get("currentPhase",1),
                "phaseName":_get_phase_name(project.get("currentPhase",1)),
                "generationCounts":{
                    "images":{"count":0,"unit":"枚","calls":0},
                    "music":{"count":0,"unit":"曲","calls":0},
                    "sfx":{"count":0,"unit":"個","calls":0},
                    "voice":{"count":0,"unit":"件","calls":0},
                    "code":{"count":0,"unit":"行","calls":0},
                    "documents":{"count":0,"unit":"件","calls":0},
                    "scenarios":{"count":0,"unit":"本","calls":0}
                }
            }

        return jsonify(metrics)

    @app.route('/api/projects/<project_id>/logs',methods=['GET'])
    def get_project_logs(project_id:str):
        project=project_service.get_project(project_id)
        if not project:
            return jsonify({"error":"Project not found"}),404

        logs=project_service.get_system_logs(project_id)
        return jsonify(logs)

    @app.route('/api/projects/<project_id>/assets',methods=['GET'])
    def get_project_assets(project_id:str):
        project=project_service.get_project(project_id)
        if not project:
            return jsonify({"error":"Project not found"}),404

        assets=workflow_service.get_assets_by_project(project_id)
        return jsonify(assets)

    @app.route('/api/projects/<project_id>/assets/<asset_id>',methods=['PATCH'])
    def update_project_asset(project_id:str,asset_id:str):
        project=project_service.get_project(project_id)
        if not project:
            return jsonify({"error":"Project not found"}),404

        data=request.get_json()
        asset=workflow_service.update_asset(project_id,asset_id,data)

        if not asset:
            return jsonify({"error":"Asset not found"}),404

        if event_bus:
            event_bus.publish(AssetUpdated(project_id=project_id,asset=asset))

        return jsonify(asset)

    @app.route('/api/projects/<project_id>/assets/bulk',methods=['PATCH'])
    def bulk_update_assets(project_id:str):
        project=project_service.get_project(project_id)
        if not project:
            return jsonify({"error":"Project not found"}),404

        data=request.get_json() or {}
        asset_ids=data.get("assetIds",[])
        new_status=data.get("approvalStatus")

        if not asset_ids:
            return jsonify({"error":"assetIds is required"}),400
        if new_status not in ("approved","rejected"):
            return jsonify({"error":"approvalStatus must be 'approved' or 'rejected'"}),400

        updated_assets=[]
        for asset_id in asset_ids:
            asset=workflow_service.update_asset(project_id,asset_id,{"approvalStatus":new_status})
            if asset:
                updated_assets.append(asset)

        if event_bus:
            event_bus.publish(AssetBulkUpdated(project_id=project_id,assets=updated_assets,status=new_status))

        return jsonify({"updated":len(updated_assets),"assets":updated_assets})

    @app.route('/api/projects/<project_id>/assets/<asset_id>/regenerate',methods=['POST'])
    def request_asset_regeneration(project_id:str,asset_id:str):
        project=project_service.get_project(project_id)
        if not project:
            return jsonify({"error":"Project not found"}),404

        data=request.get_json() or {}
        feedback=data.get("feedback","")

        if not feedback:
            return jsonify({"error":"feedback is required"}),400

        asset=workflow_service.update_asset(project_id,asset_id,{"approvalStatus":"rejected"})
        if not asset:
            return jsonify({"error":"Asset not found"}),404

        workflow_service.request_asset_regeneration(project_id,asset_id,feedback)

        if event_bus:
            event_bus.publish(AssetRegenerationRequested(project_id=project_id,asset_id=asset_id,feedback=feedback))

        return jsonify({"success":True,"message":"再生成リクエストを送信しました"})


def _get_phase_name(phase:int)->str:
    phase_names={
        1:"Phase 1: 企画・設計",
        2:"Phase 2: 実装",
        3:"Phase 3: 統合・テスト"
    }
    return phase_names.get(phase,f"Phase {phase}")
