from flask import Flask,request,jsonify
from services.project_service import ProjectService
from config_loaders import load_yaml_config
import uuid


def register_brushup_routes(app:Flask,project_service:ProjectService,sio):

    @app.route('/api/brushup/options',methods=['GET'])
    def get_brushup_options():
        config=load_yaml_config('brushup_options.yaml')
        if not config:
            return jsonify({"error":"設定ファイルが見つかりません"}),500
        return jsonify(config)

    @app.route('/api/projects/<project_id>/brushup/suggest-images',methods=['POST'])
    def suggest_brushup_images(project_id:str):
        project=project_service.get_project(project_id)
        if not project:
            return jsonify({"error":"プロジェクトが見つかりません"}),404

        data=request.get_json() or {}
        custom_instruction=data.get("customInstruction","")
        count=min(data.get("count",3),5)

        images=[]
        for i in range(count):
            images.append({
                "id":str(uuid.uuid4()),
                "url":f"/api/placeholder/brushup-suggest-{i+1}.png",
                "prompt":f"Generated suggestion {i+1}"
            })

        return jsonify({"images":images})
