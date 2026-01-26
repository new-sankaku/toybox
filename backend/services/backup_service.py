import os
import shutil
from datetime import datetime
from typing import List,Optional
from pathlib import Path


class BackupService:
 def __init__(self,db_path:str,backup_dir:Optional[str]=None,max_backups:int=10):
  self._db_path=db_path
  self._backup_dir=backup_dir or os.path.join(os.path.dirname(db_path),"backups")
  self._max_backups=max_backups
  self._ensure_backup_dir()

 def _ensure_backup_dir(self)->None:
  Path(self._backup_dir).mkdir(parents=True,exist_ok=True)

 def create_backup(self,tag:Optional[str]=None)->Optional[str]:
  if not os.path.exists(self._db_path):
   print(f"[BackupService] Database not found: {self._db_path}")
   return None
  timestamp=datetime.now().strftime("%Y%m%d_%H%M%S")
  tag_suffix=f"_{tag}" if tag else""
  db_name=os.path.basename(self._db_path)
  backup_name=f"{os.path.splitext(db_name)[0]}_{timestamp}{tag_suffix}.db"
  backup_path=os.path.join(self._backup_dir,backup_name)
  try:
   shutil.copy2(self._db_path,backup_path)
   print(f"[BackupService] Backup created: {backup_path}")
   self._cleanup_old_backups()
   return backup_path
  except Exception as e:
   print(f"[BackupService] Backup failed: {e}")
   return None

 def create_startup_backup(self)->Optional[str]:
  return self.create_backup(tag="startup")

 def _cleanup_old_backups(self)->None:
  try:
   backups=self.list_backups()
   if len(backups)>self._max_backups:
    for old_backup in backups[self._max_backups:]:
     try:
      os.remove(old_backup["path"])
      print(f"[BackupService] Removed old backup: {old_backup['path']}")
     except Exception as e:
      print(f"[BackupService] Failed to remove backup: {e}")
  except Exception as e:
   print(f"[BackupService] Cleanup failed: {e}")

 def list_backups(self)->List[dict]:
  if not os.path.exists(self._backup_dir):
   return []
  backups=[]
  for filename in os.listdir(self._backup_dir):
   if filename.endswith(".db"):
    filepath=os.path.join(self._backup_dir,filename)
    stat=os.stat(filepath)
    backups.append({
     "name":filename,
     "path":filepath,
     "size":stat.st_size,
     "created_at":datetime.fromtimestamp(stat.st_mtime).isoformat(),
    })
  backups.sort(key=lambda x:x["created_at"],reverse=True)
  return backups

 def restore_backup(self,backup_name:str)->bool:
  backup_path=os.path.join(self._backup_dir,backup_name)
  if not os.path.exists(backup_path):
   print(f"[BackupService] Backup not found: {backup_path}")
   return False
  try:
   self.create_backup(tag="pre_restore")
   shutil.copy2(backup_path,self._db_path)
   print(f"[BackupService] Restored from: {backup_path}")
   return True
  except Exception as e:
   print(f"[BackupService] Restore failed: {e}")
   return False

 def delete_backup(self,backup_name:str)->bool:
  backup_path=os.path.join(self._backup_dir,backup_name)
  if not os.path.exists(backup_path):
   return False
  try:
   os.remove(backup_path)
   print(f"[BackupService] Deleted backup: {backup_path}")
   return True
  except Exception as e:
   print(f"[BackupService] Delete failed: {e}")
   return False

 def get_backup_info(self)->dict:
  backups=self.list_backups()
  total_size=sum(b["size"] for b in backups)
  return {
   "backup_dir":self._backup_dir,
   "db_path":self._db_path,
   "max_backups":self._max_backups,
   "backup_count":len(backups),
   "total_size_bytes":total_size,
   "latest_backup":backups[0] if backups else None,
  }
