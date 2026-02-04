from flask import Flask,request,jsonify
from models.database import get_session
from repositories.global_cost_settings import GlobalCostSettingsRepository
from services.budget_manager import get_budget_manager
from middleware.logger import get_logger
from middleware.error_handler import ApiError

def register_global_cost_settings_routes(app:Flask,sio=None):

 @app.route('/api/config/global-cost-settings',methods=['GET'])
 def get_global_cost_settings():
  try:
   with get_session() as session:
    repo=GlobalCostSettingsRepository(session)
    settings=repo.get_or_create_default()
    return jsonify(repo.to_dict(settings))
  except Exception as e:
   get_logger().error(f"Failed to get global cost settings: {e}",exc_info=True)
   raise ApiError("グローバルコスト設定の取得に失敗しました",code="GLOBAL_COST_SETTINGS_ERROR",status_code=500)

 @app.route('/api/config/global-cost-settings',methods=['PUT'])
 def update_global_cost_settings():
  try:
   data=request.json or {}
   with get_session() as session:
    repo=GlobalCostSettingsRepository(session)
    settings=repo.update(data)
    session.commit()
    return jsonify(repo.to_dict(settings))
  except Exception as e:
   get_logger().error(f"Failed to update global cost settings: {e}",exc_info=True)
   raise ApiError("グローバルコスト設定の更新に失敗しました",code="GLOBAL_COST_SETTINGS_UPDATE_ERROR",status_code=500)

 @app.route('/api/cost/budget-status',methods=['GET'])
 def get_budget_status():
  try:
   manager=get_budget_manager(sio)
   status=manager.get_budget_status()
   return jsonify(status)
  except Exception as e:
   get_logger().error(f"Failed to get budget status: {e}",exc_info=True)
   raise ApiError("予算ステータスの取得に失敗しました",code="BUDGET_STATUS_ERROR",status_code=500)
