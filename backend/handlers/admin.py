import os
import time
from flask import Flask, jsonify, request, send_file
from middleware.admin_auth import require_admin_auth, get_admin_token
from middleware.logger import get_logger
from middleware.error_handler import NotFoundError, ValidationError, ApiError
from providers import get_provider, list_providers, AIProviderConfig
from providers.health_monitor import get_health_monitor


def register_admin_routes(app: Flask, backup_service, archive_service):
    @app.route("/admin-api/auth/verify", methods=["POST"])
    def admin_verify():
        token = get_admin_token()
        if not token:
            return jsonify({"error": "ADMIN_TOKEN is not configured"}), 503
        data = request.get_json() or {}
        provided = data.get("token", "")
        if provided == token:
            return jsonify({"success": True})
        return jsonify({"error": "認証に失敗しました"}), 401

    @app.route("/admin-api/api-keys", methods=["GET"])
    @require_admin_auth
    def admin_get_api_keys():
        from models.database import get_session
        from repositories import ApiKeyRepository

        session = get_session()
        try:
            repo = ApiKeyRepository(session)
            hints = repo.get_all_hints()
            return jsonify(hints)
        finally:
            session.close()

    @app.route("/admin-api/api-keys/<provider_id>", methods=["PUT"])
    @require_admin_auth
    def admin_save_api_key(provider_id: str):
        from models.database import get_session
        from repositories import ApiKeyRepository

        data = request.get_json()
        if not data or not data.get("apiKey"):
            return jsonify({"error": "apiKeyは必須です"}), 400
        api_key = data["apiKey"]
        session = get_session()
        try:
            repo = ApiKeyRepository(session)
            key_store = repo.save(provider_id, api_key)
            session.commit()
            return jsonify({"success": True, "hint": key_store.key_hint, "message": "APIキーが保存されました"})
        except Exception as e:
            get_logger().error(f"Failed to save API key for {provider_id}: {e}", exc_info=True)
            session.rollback()
            return jsonify({"error": "APIキーの保存に失敗しました"}), 500
        finally:
            session.close()

    @app.route("/admin-api/api-keys/<provider_id>", methods=["DELETE"])
    @require_admin_auth
    def admin_delete_api_key(provider_id: str):
        from models.database import get_session
        from repositories import ApiKeyRepository

        session = get_session()
        try:
            repo = ApiKeyRepository(session)
            deleted = repo.delete(provider_id)
            session.commit()
            if deleted:
                return jsonify({"success": True, "message": "APIキーが削除されました"})
            else:
                return jsonify({"error": "APIキーが見つかりません"}), 404
        except Exception as e:
            get_logger().error(f"Failed to delete API key for {provider_id}: {e}", exc_info=True)
            session.rollback()
            return jsonify({"error": "APIキーの削除に失敗しました"}), 500
        finally:
            session.close()

    @app.route("/admin-api/api-keys/<provider_id>/validate", methods=["POST"])
    @require_admin_auth
    def admin_validate_api_key(provider_id: str):
        from models.database import get_session
        from repositories import ApiKeyRepository

        session = get_session()
        try:
            repo = ApiKeyRepository(session)
            api_key = repo.get_decrypted_key(provider_id)
            if not api_key:
                return jsonify({"success": False, "error": "APIキーが保存されていません"}), 404
            config = AIProviderConfig(api_key=api_key)
            provider = get_provider(provider_id, config)
            if not provider:
                return jsonify({"success": False, "error": "未対応のプロバイダーです"}), 400
            start_time = time.time()
            result = provider.test_connection()
            latency = int((time.time() - start_time) * 1000)
            is_valid = result.get("success", False)
            repo.update_validation_status(provider_id, is_valid, latency)
            session.commit()
            return jsonify({"success": is_valid, "message": result.get("message", ""), "latency": latency})
        except Exception as e:
            get_logger().error(f"Failed to validate API key for {provider_id}: {e}", exc_info=True)
            session.rollback()
            return jsonify({"success": False, "error": "APIキーの検証に失敗しました"}), 500
        finally:
            session.close()

    @app.route("/admin-api/backups", methods=["GET"])
    @require_admin_auth
    def admin_list_backups():
        backups = backup_service.list_backups()
        return jsonify({"backups": backups, "info": backup_service.get_backup_info()})

    @app.route("/admin-api/backups", methods=["POST"])
    @require_admin_auth
    def admin_create_backup():
        data = request.get_json() or {}
        tag = data.get("tag")
        backup_path = backup_service.create_backup(tag=tag)
        if backup_path:
            return jsonify({"success": True, "path": backup_path})
        else:
            raise ApiError("Backup creation failed", code="BACKUP_ERROR", status_code=500)

    @app.route("/admin-api/backups/<backup_name>/restore", methods=["POST"])
    @require_admin_auth
    def admin_restore_backup(backup_name: str):
        import re

        if not re.match(r"^[\w\-\.]+\.db$", backup_name):
            raise ValidationError("不正なバックアップ名です", "backup_name")
        success = backup_service.restore_backup(backup_name)
        if success:
            return jsonify({"success": True, "message": f"Restored from {backup_name}"})
        else:
            raise NotFoundError("Backup", backup_name)

    @app.route("/admin-api/backups/<backup_name>", methods=["DELETE"])
    @require_admin_auth
    def admin_delete_backup(backup_name: str):
        import re

        if not re.match(r"^[\w\-\.]+\.db$", backup_name):
            raise ValidationError("不正なバックアップ名です", "backup_name")
        success = backup_service.delete_backup(backup_name)
        if success:
            return jsonify({"success": True})
        else:
            raise NotFoundError("Backup", backup_name)

    @app.route("/admin-api/archive/stats", methods=["GET"])
    @require_admin_auth
    def admin_archive_stats():
        project_id = request.args.get("projectId")
        stats = archive_service.get_data_statistics(project_id)
        return jsonify(stats)

    @app.route("/admin-api/archive/cleanup", methods=["POST"])
    @require_admin_auth
    def admin_cleanup():
        data = request.get_json() or {}
        project_id = data.get("projectId")
        deleted = archive_service.cleanup_old_traces(project_id)
        return jsonify({"success": True, "deleted": deleted})

    @app.route("/admin-api/archive/estimate", methods=["GET"])
    @require_admin_auth
    def admin_cleanup_estimate():
        project_id = request.args.get("projectId")
        estimate = archive_service.estimate_cleanup_size(project_id)
        return jsonify(estimate)

    @app.route("/admin-api/archive/retention", methods=["PUT"])
    @require_admin_auth
    def admin_set_retention():
        data = request.get_json() or {}
        days = data.get("retentionDays")
        if not days or not isinstance(days, int) or days < 1:
            raise ValidationError("retentionDays must be a positive integer", "retentionDays")
        archive_service.set_retention_days(days)
        return jsonify({"success": True, "retentionDays": days})

    @app.route("/admin-api/archive/export", methods=["POST"])
    @require_admin_auth
    def admin_export_traces():
        data = request.get_json() or {}
        project_id = data.get("projectId")
        agent_id = data.get("agentId")
        include_logs = data.get("includeLogs", True)
        if not project_id:
            raise ValidationError("projectId is required", "projectId")
        zip_path = archive_service.export_traces_to_zip(project_id, agent_id, include_logs)
        if zip_path:
            return jsonify(
                {
                    "success": True,
                    "zipPath": zip_path,
                    "zipName": os.path.basename(zip_path),
                    "zipSize": os.path.getsize(zip_path),
                }
            )
        else:
            raise ApiError("No traces found to export", code="NO_DATA", status_code=404)

    @app.route("/admin-api/archive/export-and-cleanup", methods=["POST"])
    @require_admin_auth
    def admin_export_and_cleanup():
        data = request.get_json() or {}
        project_id = data.get("projectId")
        agent_id = data.get("agentId")
        if not project_id:
            raise ValidationError("projectId is required", "projectId")
        result = archive_service.archive_and_cleanup(project_id, agent_id)
        if result.get("success"):
            return jsonify(result)
        else:
            raise ApiError(result.get("error", "Archive failed"), code="ARCHIVE_ERROR", status_code=400)

    @app.route("/admin-api/archive/auto-archive", methods=["POST"])
    @require_admin_auth
    def admin_auto_archive():
        data = request.get_json() or {}
        days_old = data.get("daysOld")
        result = archive_service.archive_old_traces(days_old)
        return jsonify(result)

    @app.route("/admin-api/archives", methods=["GET"])
    @require_admin_auth
    def admin_list_archives():
        archives = archive_service.list_archives()
        info = archive_service.get_archive_info()
        return jsonify({"archives": archives, "info": info})

    @app.route("/admin-api/archives/<archive_name>", methods=["DELETE"])
    @require_admin_auth
    def admin_delete_archive(archive_name: str):
        import re

        if not re.match(r"^[\w\-\.]+\.zip$", archive_name):
            raise ValidationError("不正なアーカイブ名です", "archive_name")
        success = archive_service.delete_archive(archive_name)
        if success:
            return jsonify({"success": True})
        else:
            raise NotFoundError("Archive", archive_name)

    @app.route("/admin-api/archives/<archive_name>/download", methods=["GET"])
    @require_admin_auth
    def admin_download_archive(archive_name: str):
        import re

        if not re.match(r"^[\w\-\.]+\.zip$", archive_name):
            raise ValidationError("不正なアーカイブ名です", "archive_name")
        archive_path = os.path.normpath(os.path.join(archive_service._archive_dir, archive_name))
        base_dir = os.path.normpath(archive_service._archive_dir)
        if not archive_path.startswith(base_dir + os.sep):
            raise ValidationError("不正なパスです", "archive_name")
        if not os.path.exists(archive_path):
            raise NotFoundError("Archive", archive_name)
        return send_file(archive_path, as_attachment=True, download_name=archive_name)

    @app.route("/admin-api/system/status", methods=["GET"])
    @require_admin_auth
    def admin_system_status():
        from middleware.rate_limiter import get_limiter

        db_path = app.config.get("DB_PATH", "")
        db_size = 0
        if db_path and os.path.exists(db_path):
            db_size = os.path.getsize(db_path)
        limiter = get_limiter()
        return jsonify(
            {
                "database": {"size": db_size, "path": db_path},
                "backup_info": backup_service.get_backup_info(),
                "archive_stats": archive_service.get_data_statistics(),
                "rate_limiter": limiter.get_stats() if limiter else {},
            }
        )

    @app.route("/admin-api/providers/health", methods=["GET"])
    @require_admin_auth
    def admin_providers_health():
        monitor = get_health_monitor()
        return jsonify(monitor.get_all_health_status())

    @app.route("/admin-api/providers", methods=["GET"])
    @require_admin_auth
    def admin_list_providers():
        providers = list_providers()
        return jsonify(providers)
