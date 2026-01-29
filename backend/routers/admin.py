from fastapi import APIRouter,Request,HTTPException
from typing import Optional,List
from pydantic import BaseModel
from middleware.logger import get_logger

router=APIRouter()


class ArchiveRequest(BaseModel):
 projectIds:Optional[List[str]]=None


@router.get("/admin/stats")
async def get_admin_stats(request:Request):
 backup_service=request.app.state.backup_service
 archive_service=request.app.state.archive_service
 return {
  "backups":backup_service.get_backup_info(),
  "archives":archive_service.get_data_statistics(),
 }


@router.post("/admin/archive")
async def archive_old_data(data:ArchiveRequest,request:Request):
 archive_service=request.app.state.archive_service
 try:
  result=archive_service.archive_old_data(project_ids=data.projectIds)
  return {"success":True,"archived":result}
 except Exception as e:
  get_logger().error(f"Archive failed: {e}",exc_info=True)
  raise HTTPException(status_code=500,detail="アーカイブに失敗しました")


@router.post("/admin/cleanup")
async def cleanup_old_data(request:Request):
 archive_service=request.app.state.archive_service
 try:
  result=archive_service.cleanup_archived_data()
  return {"success":True,"cleaned":result}
 except Exception as e:
  get_logger().error(f"Cleanup failed: {e}",exc_info=True)
  raise HTTPException(status_code=500,detail="クリーンアップに失敗しました")


@router.get("/admin/archives")
async def list_archives(request:Request):
 archive_service=request.app.state.archive_service
 return archive_service.list_archives()
