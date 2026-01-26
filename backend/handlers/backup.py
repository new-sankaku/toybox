from flask import Flask,jsonify,request
from services.backup_service import BackupService
from services.archive_service import ArchiveService
from middleware.error_handler import NotFoundError,ValidationError,ApiError


def register_backup_routes(app:Flask,backup_service:BackupService,archive_service:ArchiveService):

 @app.route('/api/backups',methods=['GET'])
 def list_backups():
  backups=backup_service.list_backups()
  return jsonify({"backups":backups,"info":backup_service.get_backup_info()})

 @app.route('/api/backups',methods=['POST'])
 def create_backup():
  data=request.get_json() or{}
  tag=data.get("tag")
  backup_path=backup_service.create_backup(tag=tag)
  if backup_path:
   return jsonify({"success":True,"path":backup_path})
  else:
   raise ApiError("Backup creation failed",code="BACKUP_ERROR",status_code=500)

 @app.route('/api/backups/<backup_name>/restore',methods=['POST'])
 def restore_backup(backup_name:str):
  success=backup_service.restore_backup(backup_name)
  if success:
   return jsonify({"success":True,"message":f"Restored from {backup_name}"})
  else:
   raise NotFoundError("Backup",backup_name)

 @app.route('/api/backups/<backup_name>',methods=['DELETE'])
 def delete_backup(backup_name:str):
  success=backup_service.delete_backup(backup_name)
  if success:
   return jsonify({"success":True})
  else:
   raise NotFoundError("Backup",backup_name)

 @app.route('/api/archive/stats',methods=['GET'])
 def get_archive_stats():
  project_id=request.args.get("projectId")
  stats=archive_service.get_data_statistics(project_id)
  return jsonify(stats)

 @app.route('/api/archive/cleanup',methods=['POST'])
 def cleanup_old_data():
  data=request.get_json() or{}
  project_id=data.get("projectId")
  deleted=archive_service.cleanup_old_traces(project_id)
  return jsonify({"success":True,"deleted":deleted})

 @app.route('/api/archive/estimate',methods=['GET'])
 def estimate_cleanup():
  project_id=request.args.get("projectId")
  estimate=archive_service.estimate_cleanup_size(project_id)
  return jsonify(estimate)

 @app.route('/api/archive/retention',methods=['PUT'])
 def set_retention():
  data=request.get_json() or{}
  days=data.get("retentionDays")
  if not days or not isinstance(days,int) or days<1:
   raise ValidationError("retentionDays must be a positive integer","retentionDays")
  archive_service.set_retention_days(days)
  return jsonify({"success":True,"retentionDays":days})
