import os
from pathlib import Path


def get_host() -> str:
    return os.environ.get("TICTOK_HOST", "127.0.0.1")


def get_port() -> int:
    return int(os.environ.get("TICTOK_PORT", "8520"))


def get_log_level() -> str:
    return os.environ.get("TICTOK_LOG_LEVEL", "INFO")


def get_db_path() -> str:
    return os.environ.get(
        "TICTOK_DB_PATH", str(Path(__file__).resolve().parent / "tictok.db")
    )


def get_timeline_limit() -> int:
    return int(os.environ.get("TICTOK_TIMELINE_LIMIT", "2160"))


def get_simulation() -> bool:
    return os.environ.get("TICTOK_SIMULATION", "0").lower() in ("1", "true", "yes")


def get_record_dir() -> str:
    return os.environ.get(
        "TICTOK_RECORD_DIR", str(Path(__file__).resolve().parent / "recordings")
    )


def get_sign_api_key() -> str:
    return os.environ.get("TICTOK_SIGN_API_KEY", "").strip()


def get_sign_api_url() -> str:
    return os.environ.get("TICTOK_SIGN_API_URL", "").strip()


def get_web_proxy() -> str:
    return os.environ.get("TICTOK_WEB_PROXY", "").strip()
