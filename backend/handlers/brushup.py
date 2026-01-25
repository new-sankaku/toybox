from flask import Flask,request,jsonify
from datastore import DataStore
import uuid


def register_brushup_routes(app:Flask,data_store:DataStore,sio):

    @app.route('/api/projects/<project_id>/brushup/suggest-images',methods=['POST'])
    def suggest_brushup_images(project_id:str):
        project = data_store.get_project(project_id)
        if not project:
            return jsonify({"error":"プロジェクトが見つかりません"}),404

        data = request.get_json() or {}
        presets = data.get("presets",[])
        custom_instruction = data.get("customInstruction","")
        count = min(data.get("count",3),5)

        images = []
        for i in range(count):
            images.append({
                "id":str(uuid.uuid4()),
                "url":f"/api/placeholder/brushup-suggest-{i+1}.png",
                "prompt":f"Generated suggestion {i+1} based on presets: {', '.join(presets)}"
            })

        return jsonify({"images":images})
