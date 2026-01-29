from typing import List
from fastapi import APIRouter, HTTPException
from providers.health_monitor import get_health_monitor
from schemas import ProviderHealthSchema

router = APIRouter()


@router.get("/providers/health", response_model=List[ProviderHealthSchema])
async def get_all_provider_health():
    monitor = get_health_monitor()
    statuses = monitor.get_all_health_status()
    result = []
    for provider_id, status in statuses.items():
        result.append(
            {
                "provider_id": provider_id,
                "healthy": status.get("available", False),
                "latency_ms": status.get("latency_ms"),
                "last_checked": status.get("checked_at"),
                "error": status.get("error"),
            }
        )
    return result


@router.get("/providers/{provider_id}/health", response_model=ProviderHealthSchema)
async def check_provider_health(provider_id: str):
    monitor = get_health_monitor()
    result = monitor.check_provider_now(provider_id)
    return {
        "provider_id": provider_id,
        "healthy": result.available,
        "latency_ms": result.latency_ms,
        "last_checked": result.checked_at.isoformat() if result.checked_at else None,
        "error": result.error,
    }
