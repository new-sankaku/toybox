from typing import List, Dict, Any
from fastapi import APIRouter
from config_loader import get_messages_config
from schemas import LanguageSchema

router = APIRouter()


@router.get("/languages", response_model=List[LanguageSchema])
async def get_languages():
    return [
        {"code": "ja", "name": "日本語", "native_name": "日本語"},
        {"code": "en", "name": "English", "native_name": "English"},
    ]


@router.get("/messages/{lang}", response_model=Dict[str, Any])
async def get_messages(lang: str):
    config = get_messages_config()
    messages = config.get("ui_messages", {}).get(lang, {})
    return messages
