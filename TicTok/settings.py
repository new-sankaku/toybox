import logging
import os

from storage import Storage

logger = logging.getLogger("tictok.settings")

SETTING_DEFS = {
    "bucket_seconds": {
        "env": "TICTOK_BUCKET_SECONDS",
        "default": 10,
        "type": int,
        "min": 1,
        "max": 600,
        "label": "Timeline集計のbucket幅（秒）",
        "note": "次のSession開始から適用されます。",
    },
    "live_check_interval": {
        "env": "TICTOK_LIVE_CHECK_INTERVAL",
        "default": 60,
        "type": int,
        "min": 10,
        "max": 3600,
        "label": "配信開始の確認間隔（秒）",
        "note": "常駐監視で未配信のとき、この間隔でLIVE開始を確認します。",
    },
    "reconnect_max_attempts": {
        "env": "TICTOK_RECONNECT_MAX_ATTEMPTS",
        "default": 10,
        "type": int,
        "min": 0,
        "max": 100,
        "label": "自動再接続の最大試行回数",
        "note": "一時的な接続障害が続いた場合に諦めるまでの回数です。",
    },
    "reconnect_base_delay": {
        "env": "TICTOK_RECONNECT_BASE_DELAY",
        "default": 2.0,
        "type": float,
        "min": 0.5,
        "max": 300.0,
        "label": "再接続の初回待機秒数",
        "note": "exponential backoffの起点です（2→4→8…秒）。",
    },
    "reconnect_max_delay": {
        "env": "TICTOK_RECONNECT_MAX_DELAY",
        "default": 60.0,
        "type": float,
        "min": 1.0,
        "max": 3600.0,
        "label": "再接続待機秒数の上限",
        "note": "backoffがこの秒数を超えないように制限します。",
    },
    "event_history": {
        "env": "TICTOK_EVENT_HISTORY",
        "default": 200,
        "type": int,
        "min": 10,
        "max": 5000,
        "label": "画面再接続時に再送するEvent履歴件数",
        "note": "次のSession開始から適用されます。",
    },
    "auto_record": {
        "env": "TICTOK_AUTO_RECORD",
        "default": 0,
        "type": int,
        "min": 0,
        "max": 1,
        "label": "配信開始時に自動録画する（0=しない / 1=する）",
        "note": "1にすると、配信開始を検出するたびにffmpegで自動録画します（ffmpegが必要）。",
    },
    "session_list_limit": {
        "env": "TICTOK_SESSION_LIST_LIMIT",
        "default": 100,
        "type": int,
        "min": 10,
        "max": 1000,
        "label": "履歴一覧の表示件数",
        "note": "履歴pageに表示するSessionの最大数です。",
    },
}


class Settings:
    def __init__(self, storage: Storage) -> None:
        self._storage = storage
        self._values: dict = {}
        self._load()

    def _env_default(self, key: str):
        definition = SETTING_DEFS[key]
        raw = os.environ.get(definition["env"])
        if raw is None:
            return definition["default"]
        return definition["type"](raw)

    def _load(self) -> None:
        stored = self._storage.get_settings()
        for key, definition in SETTING_DEFS.items():
            if key in stored:
                self._values[key] = definition["type"](stored[key])
            else:
                self._values[key] = self._env_default(key)

    def get(self, key: str):
        return self._values[key]

    def all_values(self) -> dict:
        return dict(self._values)

    def describe(self) -> list:
        return [
            {
                "key": key,
                "value": self._values[key],
                "label": definition["label"],
                "note": definition["note"],
                "min": definition["min"],
                "max": definition["max"],
                "step": 1 if definition["type"] is int else 0.5,
            }
            for key, definition in SETTING_DEFS.items()
        ]

    def update(self, values: dict) -> dict:
        validated = {}
        for key, value in values.items():
            if key not in SETTING_DEFS:
                raise ValueError(f"不明な設定key: {key}")
            definition = SETTING_DEFS[key]
            try:
                typed = definition["type"](value)
            except (TypeError, ValueError):
                raise ValueError(f"{definition['label']} の値が不正です: {value}")
            if not (definition["min"] <= typed <= definition["max"]):
                raise ValueError(
                    f"{definition['label']} は {definition['min']}〜{definition['max']} の範囲で指定してください。"
                )
            validated[key] = typed
        if validated:
            self._storage.set_settings(validated)
            self._values.update(validated)
            logger.info("settings updated: %s", validated)
        return self.all_values()
