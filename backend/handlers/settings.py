from flask import Flask,request,jsonify
from testdata import TestDataStore
from agent_settings import (
    get_default_quality_settings,
    QualityCheckConfig,
    AGENT_PHASES,
    AGENT_DISPLAY_NAMES,
    HIGH_COST_AGENTS,
    AGENT_DEFINITIONS,
)
from config_loader import (
    get_models_config,
    get_project_options_config,
    get_file_extensions_config,
    get_agent_definitions_config,
    get_token_pricing,
)


def register_settings_routes(app:Flask,data_store:TestDataStore):

    @app.route('/api/projects/<project_id>/settings/quality-check',methods=['GET'])
    def get_quality_settings(project_id:str):
        project = data_store.get_project(project_id)
        if not project:
            return jsonify({"error":"Project not found"}),404

        settings = data_store.get_quality_settings(project_id)
        settings_dict = {}
        for agent_type,config in settings.items():
            settings_dict[agent_type] = config.to_dict()

        return jsonify({
            "settings":settings_dict,
            "phases":AGENT_PHASES,
            "displayNames":AGENT_DISPLAY_NAMES,
        })

    @app.route('/api/projects/<project_id>/settings/quality-check/<agent_type>',methods=['PATCH'])
    def update_quality_setting(project_id:str,agent_type:str):
        project = data_store.get_project(project_id)
        if not project:
            return jsonify({"error":"Project not found"}),404

        data = request.json or {}
        current_settings = data_store.get_quality_settings(project_id)
        if agent_type not in current_settings:
            return jsonify({"error":f"Unknown agent type: {agent_type}"}),400

        current_config = current_settings[agent_type]
        updated_config = QualityCheckConfig(
            enabled=data.get("enabled",current_config.enabled),
            max_retries=data.get("maxRetries",current_config.max_retries),
            is_high_cost=current_config.is_high_cost,
        )

        data_store.set_quality_setting(project_id,agent_type,updated_config)

        return jsonify({
            "agentType":agent_type,
            "config":updated_config.to_dict(),
        })

    @app.route('/api/projects/<project_id>/settings/quality-check/bulk',methods=['PATCH'])
    def bulk_update_quality_settings(project_id:str):
        project = data_store.get_project(project_id)
        if not project:
            return jsonify({"error":"Project not found"}),404

        data = request.json or {}
        settings_updates = data.get("settings",{})

        if not settings_updates:
            return jsonify({"error":"No settings provided"}),400

        current_settings = data_store.get_quality_settings(project_id)
        updated_results = {}

        for agent_type,update_data in settings_updates.items():
            if agent_type not in current_settings:
                continue

            current_config = current_settings[agent_type]
            updated_config = QualityCheckConfig(
                enabled=update_data.get("enabled",current_config.enabled),
                max_retries=update_data.get("maxRetries",current_config.max_retries),
                is_high_cost=current_config.is_high_cost,
            )

            data_store.set_quality_setting(project_id,agent_type,updated_config)
            updated_results[agent_type] = updated_config.to_dict()

        return jsonify({
            "updated":updated_results,
            "count":len(updated_results),
        })

    @app.route('/api/settings/quality-check/defaults',methods=['GET'])
    def get_default_settings():
        default_settings = get_default_quality_settings()

        settings_dict = {}
        for agent_type,config in default_settings.items():
            settings_dict[agent_type] = config.to_dict()

        return jsonify({
            "settings":settings_dict,
            "phases":AGENT_PHASES,
            "displayNames":AGENT_DISPLAY_NAMES,
            "highCostAgents":list(HIGH_COST_AGENTS),
        })

    @app.route('/api/projects/<project_id>/settings/quality-check/reset',methods=['POST'])
    def reset_quality_settings(project_id:str):
        project = data_store.get_project(project_id)
        if not project:
            return jsonify({"error":"Project not found"}),404

        default_settings = get_default_quality_settings()
        data_store.reset_quality_settings(project_id)

        settings_dict = {}
        for agent_type,config in default_settings.items():
            settings_dict[agent_type] = config.to_dict()

        return jsonify({
            "message":"Settings reset to default",
            "settings":settings_dict,
        })

    @app.route('/api/agent-definitions',methods=['GET'])
    def get_agent_definitions():
        return jsonify(AGENT_DEFINITIONS)



    @app.route('/api/config/models',methods=['GET'])
    def get_models_config_api():
        """モデル設定を取得（プロバイダー、モデル一覧、トークン料金）"""
        return jsonify(get_models_config())

    @app.route('/api/config/models/pricing/<model_id>',methods=['GET'])
    def get_model_pricing_api(model_id:str):
        """特定モデルのトークン料金を取得"""
        pricing = get_token_pricing(model_id)
        return jsonify({
            "modelId":model_id,
            "pricing":pricing,
        })

    @app.route('/api/config/project-options',methods=['GET'])
    def get_project_options_api():
        """プロジェクトオプション設定を取得（プラットフォーム、スコープ、LLMプロバイダー）"""
        return jsonify(get_project_options_config())

    @app.route('/api/config/file-extensions',methods=['GET'])
    def get_file_extensions_api():
        """ファイル拡張子分類設定を取得"""
        return jsonify(get_file_extensions_config())

    @app.route('/api/config/agents',methods=['GET'])
    def get_agents_config_api():
        """エージェント定義設定を取得"""
        return jsonify(get_agent_definitions_config())

    @app.route('/api/projects/<project_id>/auto-approval-rules',methods=['GET'])
    def get_auto_approval_rules(project_id:str):
        """プロジェクトの自動承認ルールを取得"""
        project = data_store.get_project(project_id)
        if not project:
            return jsonify({"error":"Project not found"}),404
        rules = data_store.get_auto_approval_rules(project_id)
        return jsonify({"rules":rules})

    @app.route('/api/projects/<project_id>/auto-approval-rules',methods=['PUT'])
    def update_auto_approval_rules(project_id:str):
        """プロジェクトの自動承認ルールを更新"""
        project = data_store.get_project(project_id)
        if not project:
            return jsonify({"error":"Project not found"}),404
        data = request.json or {}
        rules = data.get("rules",[])
        updated_rules = data_store.set_auto_approval_rules(project_id,rules)
        return jsonify({"rules":updated_rules})
