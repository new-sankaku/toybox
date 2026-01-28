from flask import Flask,jsonify,request
from datastore import DataStore


def register_metrics_routes(app:Flask,data_store:DataStore,sio=None):

    @app.route('/api/projects/<project_id>/ai-requests/stats',methods=['GET'])
    def get_ai_request_stats(project_id:str):
        """Get AI request statistics for a project"""
        project=data_store.get_project(project_id)
        if not project:
            return jsonify({"error":"Project not found"}),404


        agents=data_store.get_agents_by_project(project_id)

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
        project=data_store.get_project(project_id)
        if not project:
            return jsonify({"error":"Project not found"}),404

        metrics=data_store.get_project_metrics(project_id)

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
        project=data_store.get_project(project_id)
        if not project:
            return jsonify({"error":"Project not found"}),404

        logs=data_store.get_system_logs(project_id)
        return jsonify(logs)

    @app.route('/api/projects/<project_id>/assets',methods=['GET'])
    def get_project_assets(project_id:str):
        project=data_store.get_project(project_id)
        if not project:
            return jsonify({"error":"Project not found"}),404

        assets=data_store.get_assets_by_project(project_id)
        return jsonify(assets)

    @app.route('/api/projects/<project_id>/assets/<asset_id>',methods=['PATCH'])
    def update_project_asset(project_id:str,asset_id:str):
        project=data_store.get_project(project_id)
        if not project:
            return jsonify({"error":"Project not found"}),404

        data=request.get_json()
        asset=data_store.update_asset(project_id,asset_id,data)

        if not asset:
            return jsonify({"error":"Asset not found"}),404

        if sio:
            sio.emit('asset:updated',{
                "projectId":project_id,
                "asset":asset
            },room=f"project:{project_id}")

        return jsonify(asset)


def _get_phase_name(phase:int)->str:
    phase_names={
        1:"Phase 1: 企画・設計",
        2:"Phase 2: 実装",
        3:"Phase 3: 統合・テスト"
    }
    return phase_names.get(phase,f"Phase {phase}")
