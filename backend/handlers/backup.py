from flask import Flask, jsonify, request, send_file
from services.backup_service import BackupService
from services.archive_service import ArchiveService
from middleware.error_handler import NotFoundError, ValidationError, ApiError


def register_backup_routes(app: Flask, backup_service: BackupService, archive_service: ArchiveService):
    @app.route("/api/backups", methods=["GET"])
    def list_backups():
        backups = backup_service.list_backups()
        return jsonify({"backups": backups, "info": backup_service.get_backup_info()})

    @app.route("/api/backups", methods=["POST"])
    def create_backup():
        data = request.get_json() or {}
        tag = data.get("tag")
        backup_path = backup_service.create_backup(tag=tag)
        if backup_path:
            return jsonify({"success": True, "path": backup_path})
        else:
            raise ApiError("Backup creation failed", code="BACKUP_ERROR", status_code=500)

    @app.route("/api/backups/<backup_name>/restore", methods=["POST"])
    def restore_backup(backup_name: str):
        import re

        if not re.match(r"^[\w\-\.]+\.db$", backup_name):
            raise ValidationError("不正なバックアップ名です", "backup_name")
        success = backup_service.restore_backup(backup_name)
        if success:
            return jsonify({"success": True, "message": f"Restored from {backup_name}"})
        else:
            raise NotFoundError("Backup", backup_name)

    @app.route("/api/backups/<backup_name>", methods=["DELETE"])
    def delete_backup(backup_name: str):
        import re

        if not re.match(r"^[\w\-\.]+\.db$", backup_name):
            raise ValidationError("不正なバックアップ名です", "backup_name")
        success = backup_service.delete_backup(backup_name)
        if success:
            return jsonify({"success": True})
        else:
            raise NotFoundError("Backup", backup_name)

    @app.route("/api/archive/stats", methods=["GET"])
    def get_archive_stats():
        project_id = request.args.get("projectId")
        stats = archive_service.get_data_statistics(project_id)
        return jsonify(stats)

    @app.route("/api/archive/cleanup", methods=["POST"])
    def cleanup_old_data():
        data = request.get_json() or {}
        project_id = data.get("projectId")
        deleted = archive_service.cleanup_old_traces(project_id)
        return jsonify({"success": True, "deleted": deleted})

    @app.route("/api/archive/estimate", methods=["GET"])
    def estimate_cleanup():
        project_id = request.args.get("projectId")
        estimate = archive_service.estimate_cleanup_size(project_id)
        return jsonify(estimate)

    @app.route("/api/archive/retention", methods=["PUT"])
    def set_retention():
        data = request.get_json() or {}
        days = data.get("retentionDays")
        if not days or not isinstance(days, int) or days < 1:
            raise ValidationError("retentionDays must be a positive integer", "retentionDays")
        archive_service.set_retention_days(days)
        return jsonify({"success": True, "retentionDays": days})

    @app.route("/api/archive/export", methods=["POST"])
    def export_traces():
        data = request.get_json() or {}
        project_id = data.get("projectId")
        agent_id = data.get("agentId")
        include_logs = data.get("includeLogs", True)
        if not project_id:
            raise ValidationError("projectId is required", "projectId")
        zip_path = archive_service.export_traces_to_zip(project_id, agent_id, include_logs)
        if zip_path:
            import os

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

    @app.route("/api/archive/export-and-cleanup", methods=["POST"])
    def export_and_cleanup():
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

    @app.route("/api/archive/auto-archive", methods=["POST"])
    def auto_archive_old():
        data = request.get_json() or {}
        days_old = data.get("daysOld")
        result = archive_service.archive_old_traces(days_old)
        return jsonify(result)

    @app.route("/api/archives", methods=["GET"])
    def list_archives():
        archives = archive_service.list_archives()
        info = archive_service.get_archive_info()
        return jsonify({"archives": archives, "info": info})

    @app.route("/api/archives/<archive_name>", methods=["DELETE"])
    def delete_archive(archive_name: str):
        import re

        if not re.match(r"^[\w\-\.]+\.zip$", archive_name):
            raise ValidationError("不正なアーカイブ名です", "archive_name")
        success = archive_service.delete_archive(archive_name)
        if success:
            return jsonify({"success": True})
        else:
            raise NotFoundError("Archive", archive_name)

    @app.route("/api/archives/<archive_name>/download", methods=["GET"])
    def download_archive(archive_name: str):
        import os
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
