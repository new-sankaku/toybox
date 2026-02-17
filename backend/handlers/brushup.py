from flask import Flask,request,jsonify
from services.project_service import ProjectService
from config_loaders import load_yaml_config


def register_brushup_routes(app:Flask,project_service:ProjectService,sio):

    @app.route('/api/brushup/options',methods=['GET'])
    def get_brushup_options():
        config=load_yaml_config('brushup_options.yaml')
        if not config:
            return jsonify({"error":"設定ファイルが見つかりません"}),500
        return jsonify(config)

    @app.route('/api/projects/<project_id>/brushup/suggest-images',methods=['POST'])
    def suggest_brushup_images(project_id:str):
        # TODO:Image生成Serviceと連携してBrushup提案画像を生成する
        return jsonify({"error":"未実装: Brushup画像提案機能"}),501
