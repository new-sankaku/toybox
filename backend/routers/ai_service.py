from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from models.database import get_session
from repositories import ApiKeyRepository
from security import encrypt_api_key, generate_key_hint
from ai_config import (
    get_providers,
    get_usage_categories,
    get_service_types,
    get_service_labels,
    get_defaults,
    get_providers_for_service,
    get_provider_type_mapping,
    get_reverse_provider_type_mapping,
)
from middleware.logger import get_logger
from schemas import AiServiceInfoSchema, AiServicesMasterResponse, ApiKeyHintSchema, ApiKeySetResponse

router = APIRouter()


class ApiKeySet(BaseModel):
    apiKey: str


@router.get("/ai-services", response_model=Dict[str, AiServiceInfoSchema])
async def list_ai_services():
    defaults = get_defaults()
    service_labels = get_service_labels()
    result = {}
    for stype in get_service_types():
        d = defaults.get(stype, {})
        result[stype] = {
            "label": service_labels.get(stype, stype),
            "description": "",
            "provider": d.get("provider", ""),
            "model": d.get("model", ""),
        }
    return result


@router.get("/config/ai-services", response_model=AiServicesMasterResponse)
async def get_ai_services_master():
    providers_raw = get_providers()
    providers = {}
    for pid, pdata in providers_raw.items():
        providers[pid] = {
            "label": pdata.get("label", pid),
            "service_types": pdata.get("service_types", []),
            "models": [
                {
                    "id": m.get("id", ""),
                    "label": m.get("label", m.get("id", "")),
                    "recommended": m.get("recommended", False),
                }
                for m in pdata.get("models", [])
            ],
            "default_model": pdata.get("default_model", ""),
        }
    services = {}
    service_labels = get_service_labels()
    defaults = get_defaults()
    for stype in get_service_types():
        d = defaults.get(stype, {})
        services[stype] = {
            "label": service_labels.get(stype, stype),
            "providers": get_providers_for_service(stype),
            "default": {"provider": d.get("provider", ""), "model": d.get("model", "")},
        }
    return {
        "service_types": get_service_types(),
        "usage_categories": get_usage_categories(),
        "services": services,
        "providers": providers,
        "provider_type_mapping": get_provider_type_mapping(),
        "reverse_provider_type_mapping": get_reverse_provider_type_mapping(),
    }


@router.get("/ai-services/providers", response_model=Dict[str, Any])
async def get_ai_providers():
    return get_providers()


@router.get("/ai-services/usage-categories", response_model=List[Dict[str, Any]])
async def get_categories():
    return get_usage_categories()


@router.get("/ai-services/api-keys", response_model=List[ApiKeyHintSchema])
async def get_api_keys():
    session = get_session()
    try:
        repo = ApiKeyRepository(session)
        return repo.get_all_hints()
    finally:
        session.close()


@router.post("/ai-services/api-keys/{provider_id}", response_model=ApiKeySetResponse)
async def set_api_key(provider_id: str, data: ApiKeySet):
    if not data.apiKey:
        raise HTTPException(status_code=400, detail="apiKey is required")
    session = get_session()
    try:
        repo = ApiKeyRepository(session)
        repo.save(provider_id, data.apiKey)
        session.commit()
        return {"provider_id": provider_id, "hint": generate_key_hint(data.apiKey), "validated": False}
    except Exception as e:
        session.rollback()
        get_logger().error(f"Failed to save API key: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to save API key")
    finally:
        session.close()


@router.delete("/ai-services/api-keys/{provider_id}", status_code=204)
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
        raise HTTPException(status_code=500, detail="Failed to delete API key")
    finally:
        session.close()


@router.get("/ai-services/{service_type}", response_model=AiServiceInfoSchema)
async def get_ai_service(service_type: str):
    if service_type in ("providers", "usage-categories", "api-keys"):
        raise HTTPException(status_code=400, detail="無効なサービスタイプです")
    defaults = get_defaults()
    service_labels = get_service_labels()
    if service_type not in get_service_types():
        raise HTTPException(status_code=404, detail=f"サービスタイプが見つかりません: {service_type}")
    d = defaults.get(service_type, {})
    return {
        "label": service_labels.get(service_type, service_type),
        "description": "",
        "provider": d.get("provider", ""),
        "model": d.get("model", ""),
    }
