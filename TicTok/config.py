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
