from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import FileResponse
from typing import Optional
from pydantic import BaseModel

router=APIRouter()


class RestoreRequest(BaseModel):
 filename:str


@router.get("/backups")
async def list_backups(request:Request):
 backup_service=request.app.state.backup_service
 return backup_service.list_backups()


@router.post("/backups")
async def create_backup(request:Request):
 backup_service=request.app.state.backup_service
 result=backup_service.create_backup()
 if result:
  return {"success":True,"backup":result}
 raise HTTPException(status_code=500,detail="バックアップ作成に失敗しました")


@router.post("/backups/restore")
async def restore_backup(data:RestoreRequest,request:Request):
 backup_service=request.app.state.backup_service
 success=backup_service.restore_backup(data.filename)
 if success:
  return {"success":True,"message":"復元が完了しました"}
 raise HTTPException(status_code=400,detail="復元に失敗しました")


@router.delete("/backups/{filename}",status_code=204)
async def delete_backup(filename:str,request:Request):
 backup_service=request.app.state.backup_service
 success=backup_service.delete_backup(filename)
 if not success:
  raise HTTPException(status_code=404,detail="バックアップが見つかりません")
 return None


@router.get("/backups/{filename}/download")
async def download_backup(filename:str,request:Request):
 backup_service=request.app.state.backup_service
 file_path=backup_service.get_backup_path(filename)
 if not file_path:
  raise HTTPException(status_code=404,detail="バックアップが見つかりません")
 return FileResponse(path=file_path,filename=filename,media_type="application/octet-stream")
