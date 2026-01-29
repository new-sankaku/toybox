import time
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from providers import get_provider, list_providers, AIProviderConfig
from providers.base import ChatMessage, MessageRole
from providers.health_monitor import get_health_monitor
from middleware.logger import get_logger
from schemas import (
    ProviderListItemSchema,
    ProviderDetailResponse,
    ModelSchema,
    TestProviderResponse,
    ChatResponse,
)

router = APIRouter()


class TestProviderRequest(BaseModel):
    providerType: str
    config: Dict[str, Any] = {}


class ChatRequest(BaseModel):
    provider: str
    model: str
    messages: List[Dict[str, str]]
    maxTokens: Optional[int] = None
    temperature: Optional[float] = None
    stream: bool = False


@router.get("/ai-providers", response_model=List[ProviderListItemSchema])
async def get_ai_providers():
    return list_providers()


@router.get("/ai-providers/{provider_id}", response_model=ProviderDetailResponse)
async def get_ai_provider(provider_id: str):
    provider = get_provider(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail=f"プロバイダーが見つかりません: {provider_id}")
    models = [
        {
            "id": m.id,
            "name": m.name,
            "max_tokens": m.max_tokens,
            "supports_vision": m.supports_vision,
            "supports_tools": m.supports_tools,
            "input_cost_per_1k": m.input_cost_per_1k,
            "output_cost_per_1k": m.output_cost_per_1k,
        }
        for m in provider.get_available_models()
    ]
    return {"id": provider.provider_id, "name": provider.display_name, "models": models}


@router.get("/ai-providers/{provider_id}/models", response_model=List[ModelSchema])
async def get_ai_provider_models(provider_id: str):
    provider = get_provider(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail=f"プロバイダーが見つかりません: {provider_id}")
    return [
        {
            "id": m.id,
            "name": m.name,
            "max_tokens": m.max_tokens,
            "supports_vision": m.supports_vision,
            "supports_tools": m.supports_tools,
            "input_cost_per_1k": m.input_cost_per_1k,
            "output_cost_per_1k": m.output_cost_per_1k,
        }
        for m in provider.get_available_models()
    ]


@router.post("/ai-providers/test", response_model=TestProviderResponse)
async def test_ai_provider(data: TestProviderRequest):
    if not data.providerType:
        raise HTTPException(status_code=400, detail="providerType is required")
    start_time = time.time()
    base_url = data.config.get("baseUrl")
    try:
        config = AIProviderConfig(
            api_key=data.config.get("apiKey"),
            base_url=base_url,
        )
        provider = get_provider(data.providerType, config)
        if not provider:
            return {"success": False, "message": f"未対応のプロバイダー: {data.providerType}"}
        result = provider.test_connection()
        latency = int((time.time() - start_time) * 1000)
        result["latency"] = latency
        if result.get("success") and data.providerType.startswith("local-"):
            _save_validated_local_provider(data.providerType, base_url or provider._get_base_url())
        return result
    except Exception as e:
        latency = int((time.time() - start_time) * 1000)
        error_type = type(e).__name__
        if "AuthenticationError" in error_type:
            message = "認証エラー: APIキーを確認してください"
        elif "RateLimitError" in error_type:
            message = "レート制限に達しました"
        elif "Connection" in error_type or "Timeout" in error_type:
            message = "接続エラー: ネットワークを確認してください"
        else:
            message = "接続テストに失敗しました"
        return {"success": False, "message": message, "latency": latency}


def _save_validated_local_provider(provider_id: str, base_url: str):
    from models.database import get_session
    from repositories import LocalProviderConfigRepository

    session = get_session()
    try:
        repo = LocalProviderConfigRepository(session)
        repo.save(provider_id, base_url, is_validated=True)
        session.commit()
    except Exception as e:
        get_logger().error(f"Failed to save validated local provider: {e}", exc_info=True)
        session.rollback()
    finally:
        session.close()


class ChatStreamRequest(BaseModel):
    provider: str
    model: str
    messages: List[Dict[str, str]]
    maxTokens: Optional[int] = None
    temperature: Optional[float] = None


@router.post("/ai/chat", response_model=ChatResponse)
async def ai_chat(data: ChatRequest):
    if not data.provider:
        raise HTTPException(status_code=400, detail="provider is required")
    if not data.model:
        raise HTTPException(status_code=400, detail="model is required")
    if not data.messages:
        raise HTTPException(status_code=400, detail="messages is required")
    api_key = _get_api_key_for_provider(data.provider)
    if not api_key:
        raise HTTPException(status_code=400, detail=f"APIキーが設定されていません: {data.provider}")
    config = AIProviderConfig(api_key=api_key)
    provider = get_provider(data.provider, config)
    if not provider:
        raise HTTPException(status_code=400, detail=f"未対応のプロバイダー: {data.provider}")
    chat_messages = []
    for msg in data.messages:
        role_str = msg.get("role", "user")
        role = (
            MessageRole.ASSISTANT
            if role_str == "assistant"
            else MessageRole.SYSTEM
            if role_str == "system"
            else MessageRole.USER
        )
        chat_messages.append(ChatMessage(role=role, content=msg.get("content", "")))
    try:
        if data.stream:

            async def generate():
                async for chunk in provider.chat_stream(
                    messages=chat_messages, model=data.model, max_tokens=data.maxTokens, temperature=data.temperature
                ):
                    yield f"data: {chunk}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(generate(), media_type="text/event-stream")
        else:
            result = await provider.chat(
                messages=chat_messages, model=data.model, max_tokens=data.maxTokens, temperature=data.temperature
            )
            return {
                "content": result.content,
                "model": result.model,
                "usage": {
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                },
                "finish_reason": result.finish_reason,
            }
    except Exception as e:
        get_logger().error(f"Chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ai/chat/stream")
async def ai_chat_stream(data: ChatStreamRequest):
    if not data.provider:
        raise HTTPException(status_code=400, detail="provider is required")
    if not data.model:
        raise HTTPException(status_code=400, detail="model is required")
    if not data.messages:
        raise HTTPException(status_code=400, detail="messages is required")
    api_key = _get_api_key_for_provider(data.provider)
    if not api_key:
        raise HTTPException(status_code=400, detail=f"APIキーが設定されていません: {data.provider}")
    config = AIProviderConfig(api_key=api_key)
    provider = get_provider(data.provider, config)
    if not provider:
        raise HTTPException(status_code=400, detail=f"未対応のプロバイダー: {data.provider}")
    chat_messages = []
    for msg in data.messages:
        role_str = msg.get("role", "user")
        role = (
            MessageRole.ASSISTANT
            if role_str == "assistant"
            else MessageRole.SYSTEM
            if role_str == "system"
            else MessageRole.USER
        )
        chat_messages.append(ChatMessage(role=role, content=msg.get("content", "")))
    try:
        import json

        async def generate():
            async for chunk in provider.chat_stream(
                messages=chat_messages, model=data.model, max_tokens=data.maxTokens, temperature=data.temperature
            ):
                yield f"data: {json.dumps(chunk)}\n\n"
            yield 'data: {"done": true}\n\n'

        return StreamingResponse(generate(), media_type="text/event-stream")
    except Exception as e:
        get_logger().error(f"Chat stream error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def _get_api_key_for_provider(provider_id: str) -> Optional[str]:
    from models.database import get_session
    from repositories import ApiKeyRepository

    session = get_session()
    try:
        repo = ApiKeyRepository(session)
        return repo.get_decrypted_key(provider_id)
    finally:
        session.close()


@router.get("/ai-providers/health/status", response_model=Dict[str, Any])
async def get_health_status():
    monitor = get_health_monitor()
    return monitor.get_all_health_status()
