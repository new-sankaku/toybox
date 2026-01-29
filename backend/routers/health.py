from fastapi import APIRouter,Request
from config import get_config

router=APIRouter()


@router.get("/health")
async def health(request:Request):
 config=request.app.state.config
 return {
  'status':'ok',
  'service':'toybox-backend',
  'agent_mode':config.agent.mode,
 }


@router.get("/api/system/stats")
async def system_stats(request:Request):
 backup_service=request.app.state.backup_service
 archive_service=request.app.state.archive_service
 return {
  'backup_info':backup_service.get_backup_info(),
  'archive_stats':archive_service.get_data_statistics(),
 }
