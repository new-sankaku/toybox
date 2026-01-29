from fastapi import APIRouter
from config_loader import get_messages_config

router = APIRouter()


@router.get("/languages")
async def get_languages():
    return [
        {"code": "ja", "name": "日本語", "nativeName": "日本語"},
        {"code": "en", "name": "English", "nativeName": "English"},
    ]


@router.get("/messages/{lang}")
async def get_messages(lang: str):
    config = get_messages_config()
    messages = config.get("ui_messages", {}).get(lang, {})
    return messages
