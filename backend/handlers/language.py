"""Language API - 言語設定の提供"""
import os
import yaml
from flask import Flask,jsonify

def load_languages_config():
    config_path=os.path.join(os.path.dirname(__file__),'..','config','languages.yaml')
    with open(config_path,'r',encoding='utf-8') as f:
        return yaml.safe_load(f)

def register_language_routes(app:Flask):
    """Register language related routes"""

    @app.route('/api/languages',methods=['GET'])
    def get_languages():
        """Get language options"""
        config=load_languages_config()
        return jsonify({
            "defaultPrimary":config.get('default_primary','ja'),
            "defaultLanguages":config.get('default_languages',['ja']),
            "languages":[
                {
                    "value":lang['code'],
                    "label":lang['label'],
                    "nativeName":lang['native_name']
                }
                for lang in config.get('languages',[])
            ]
        })
