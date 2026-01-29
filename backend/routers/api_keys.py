from typing import List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from models.database import get_session
from repositories import ApiKeyRepository
from security import generate_key_hint
from middleware.logger import get_logger
from providers import get_provider, AIProviderConfig
from schemas import ApiKeyHintSchema, ApiKeySaveResponse, ApiKeyValidationResponse

router = APIRouter()


class ApiKeySaveRequest(BaseModel):
    apiKey: str


@router.get("/api-keys", response_model=List[ApiKeyHintSchema])
async def list_api_keys():
    session = get_session()
    try:
        repo = ApiKeyRepository(session)
        return repo.get_all_hints()
    finally:
        session.close()


@router.put("/api-keys/{provider_id}", response_model=ApiKeySaveResponse)
async def save_api_key(provider_id: str, data: ApiKeySaveRequest):
    if not data.apiKey:
        raise HTTPException(status_code=400, detail="apiKey is required")
    session = get_session()
    try:
        repo = ApiKeyRepository(session)
        repo.save(provider_id, data.apiKey)
        session.commit()
        return {"success": True, "provider_id": provider_id, "hint": generate_key_hint(data.apiKey)}
    except Exception as e:
        session.rollback()
        get_logger().error(f"Failed to save API key: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="APIキーの保存に失敗しました")
    finally:
        session.close()


@router.delete("/api-keys/{provider_id}", status_code=204)
async def delete_api_key(provider_id: str):
    session = get_session()
    try:
        repo = ApiKeyRepository(session)
        repo.delete(provider_id)
        session.commit()
        return None
    except Exception as e:
        session.rollback()
        get_logger().error(f"Failed to delete API key: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="APIキーの削除に失敗しました")
    finally:
        session.close()


@router.post("/api-keys/{provider_id}/validate", response_model=ApiKeyValidationResponse)
async def validate_api_key(provider_id: str):
    session = get_session()
    try:
        repo = ApiKeyRepository(session)
        api_key = repo.get_decrypted_key(provider_id)
        if not api_key:
            raise HTTPException(status_code=404, detail="APIキーが見つかりません")
        config = AIProviderConfig(api_key=api_key)
        provider = get_provider(provider_id, config)
        if not provider:
            raise HTTPException(status_code=400, detail=f"未対応のプロバイダー: {provider_id}")
        result = provider.test_connection()
        if result.get("success"):
            repo.update_validation_status(provider_id, is_valid=True, latency_ms=result.get("latency"))
            session.commit()
        return result
    except HTTPException:
        raise
    except Exception as e:
        get_logger().error(f"Validation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="検証に失敗しました")
    finally:
        session.close()
