"""
Settings API Handler

品質チェック設定のAPIエンドポイント
"""

from flask import Flask, request, jsonify
from testdata import TestDataStore
from agent_settings import (
    get_default_quality_settings,
    QualityCheckConfig,
    AGENT_PHASES,
    AGENT_DISPLAY_NAMES,
    HIGH_COST_AGENTS,
    AGENT_DEFINITIONS,
)


def register_settings_routes(app: Flask, data_store: TestDataStore):
    """設定関連のルートを登録"""

    @app.route('/api/projects/<project_id>/settings/quality-check', methods=['GET'])
    def get_quality_settings(project_id: str):
        """
        プロジェクトの品質チェック設定を全て取得

        Returns:
            {
                "settings": {
                    "concept_leader": { "enabled": true, "maxRetries": 3, "isHighCost": false },
                    ...
                },
                "phases": { ... },
                "displayNames": { ... }
            }
        """
        project = data_store.get_project(project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404

        # プロジェクト固有の設定を取得（なければデフォルト）
        settings = data_store.get_quality_settings(project_id)

        # 設定をdict形式に変換
        settings_dict = {}
        for agent_type, config in settings.items():
            settings_dict[agent_type] = config.to_dict()

        return jsonify({
            "settings": settings_dict,
            "phases": AGENT_PHASES,
            "displayNames": AGENT_DISPLAY_NAMES,
        })

    @app.route('/api/projects/<project_id>/settings/quality-check/<agent_type>', methods=['PATCH'])
    def update_quality_setting(project_id: str, agent_type: str):
        """
        単一エージェントの品質チェック設定を更新

        Request Body:
            { "enabled": true, "maxRetries": 3 }
        """
        project = data_store.get_project(project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404

        data = request.json or {}

        # 現在の設定を取得
        current_settings = data_store.get_quality_settings(project_id)
        if agent_type not in current_settings:
            return jsonify({"error": f"Unknown agent type: {agent_type}"}), 400

        # 設定を更新
        current_config = current_settings[agent_type]
        updated_config = QualityCheckConfig(
            enabled=data.get("enabled", current_config.enabled),
            max_retries=data.get("maxRetries", current_config.max_retries),
            is_high_cost=current_config.is_high_cost,  # is_high_costは変更不可
        )

        data_store.set_quality_setting(project_id, agent_type, updated_config)

        return jsonify({
            "agentType": agent_type,
            "config": updated_config.to_dict(),
        })

    @app.route('/api/projects/<project_id>/settings/quality-check/bulk', methods=['PATCH'])
    def bulk_update_quality_settings(project_id: str):
        """
        複数エージェントの品質チェック設定を一括更新

        Request Body:
            {
                "settings": {
                    "concept_leader": { "enabled": true },
                    "design_leader": { "enabled": false },
                    ...
                }
            }
        """
        project = data_store.get_project(project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404

        data = request.json or {}
        settings_updates = data.get("settings", {})

        if not settings_updates:
            return jsonify({"error": "No settings provided"}), 400

        current_settings = data_store.get_quality_settings(project_id)
        updated_results = {}

        for agent_type, update_data in settings_updates.items():
            if agent_type not in current_settings:
                continue  # 不明なエージェントタイプはスキップ

            current_config = current_settings[agent_type]
            updated_config = QualityCheckConfig(
                enabled=update_data.get("enabled", current_config.enabled),
                max_retries=update_data.get("maxRetries", current_config.max_retries),
                is_high_cost=current_config.is_high_cost,
            )

            data_store.set_quality_setting(project_id, agent_type, updated_config)
            updated_results[agent_type] = updated_config.to_dict()

        return jsonify({
            "updated": updated_results,
            "count": len(updated_results),
        })

    @app.route('/api/settings/quality-check/defaults', methods=['GET'])
    def get_default_settings():
        """
        デフォルトの品質チェック設定を取得

        Returns:
            {
                "settings": { ... },
                "phases": { ... },
                "displayNames": { ... },
                "highCostAgents": [ ... ]
            }
        """
        default_settings = get_default_quality_settings()

        settings_dict = {}
        for agent_type, config in default_settings.items():
            settings_dict[agent_type] = config.to_dict()

        return jsonify({
            "settings": settings_dict,
            "phases": AGENT_PHASES,
            "displayNames": AGENT_DISPLAY_NAMES,
            "highCostAgents": list(HIGH_COST_AGENTS),
        })

    @app.route('/api/projects/<project_id>/settings/quality-check/reset', methods=['POST'])
    def reset_quality_settings(project_id: str):
        """
        プロジェクトの品質チェック設定をデフォルトにリセット
        """
        project = data_store.get_project(project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404

        # デフォルト設定をセット
        default_settings = get_default_quality_settings()
        data_store.reset_quality_settings(project_id)

        settings_dict = {}
        for agent_type, config in default_settings.items():
            settings_dict[agent_type] = config.to_dict()

        return jsonify({
            "message": "Settings reset to default",
            "settings": settings_dict,
        })

    @app.route('/api/agent-definitions', methods=['GET'])
    def get_agent_definitions():
        """
        エージェント定義（表示名等）を取得

        Returns:
            {
                "concept": { "label": "コンセプト", "shortLabel": "コンセプト", "phase": 0 },
                ...
            }
        """
        return jsonify(AGENT_DEFINITIONS)
