from fastapi import APIRouter,HTTPException
from typing import Dict,Any,Optional
from pydantic import BaseModel
from models.database import get_session
from repositories import ApiKeyRepository
from security import encrypt_api_key,generate_key_hint
from ai_config import get_providers,get_usage_categories
from middleware.logger import get_logger

router=APIRouter()


class ApiKeySet(BaseModel):
 apiKey:str


@router.get("/ai-services/providers")
async def get_ai_providers():
 return get_providers()


@router.get("/ai-services/usage-categories")
async def get_categories():
 return get_usage_categories()


@router.get("/ai-services/api-keys")
async def get_api_keys():
 session=get_session()
 try:
  repo=ApiKeyRepository(session)
  return repo.get_all_hints()
 finally:
  session.close()


@router.post("/ai-services/api-keys/{provider_id}")
async def set_api_key(provider_id:str,data:ApiKeySet):
 if not data.apiKey:
  raise HTTPException(status_code=400,detail="apiKey is required")
 session=get_session()
 try:
  repo=ApiKeyRepository(session)
  repo.save(provider_id,data.apiKey)
  session.commit()
  return {
   "providerId":provider_id,
   "hint":generate_key_hint(data.apiKey),
   "validated":False
  }
 except Exception as e:
  session.rollback()
  get_logger().error(f"Failed to save API key: {e}",exc_info=True)
  raise HTTPException(status_code=500,detail="Failed to save API key")
 finally:
  session.close()


@router.delete("/ai-services/api-keys/{provider_id}",status_code=204)
async def delete_api_key(provider_id:str):
 session=get_session()
 try:
  repo=ApiKeyRepository(session)
  repo.delete(provider_id)
  session.commit()
  return None
 except Exception as e:
  session.rollback()
  get_logger().error(f"Failed to delete API key: {e}",exc_info=True)
  raise HTTPException(status_code=500,detail="Failed to delete API key")
 finally:
  session.close()
