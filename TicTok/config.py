import os


def get_host() -> str:
    return os.environ.get("TICTOK_HOST", "127.0.0.1")


def get_port() -> int:
    return int(os.environ.get("TICTOK_PORT", "8520"))


def get_log_level() -> str:
    return os.environ.get("TICTOK_LOG_LEVEL", "INFO")


def get_event_history_size() -> int:
    return int(os.environ.get("TICTOK_EVENT_HISTORY", "200"))
