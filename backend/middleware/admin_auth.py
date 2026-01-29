import os
from fastapi import HTTPException,Request,Depends
from fastapi.security import HTTPBearer,HTTPAuthorizationCredentials
from middleware.logger import get_logger

security=HTTPBearer(auto_error=False)


def get_admin_token()->str:
 return os.environ.get("ADMIN_TOKEN","")


async def require_admin_auth(
 request:Request,
 credentials:HTTPAuthorizationCredentials=Depends(security)
)->None:
 token=get_admin_token()
 if not token:
  get_logger().warning("ADMIN_TOKEN is not configured")
  raise HTTPException(status_code=503,detail="Admin authentication is not configured")
 if not credentials:
  raise HTTPException(status_code=401,detail="認証が必要です")
 if credentials.credentials!=token:
  raise HTTPException(status_code=401,detail="認証に失敗しました")
