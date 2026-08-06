"""設定値と監視対象(配信者)の登録。

境界の理由: key-value 2表だけの小さな単位。他domainのどこからでも読まれるため、
特定domainに埋めずに独立させる。

lock契約: lock保持前提のmethodは無い。各methodが自分で self._lock を取る。
"""
import time


class SettingsMixin:
    """設定値と監視対象(配信者)の登録。

    lockもDB接続も持たない。すべて Storage が所有する self._conn /
    self._lock / self._read_lock を借りる(mixinとして Storage に混ぜられる前提)。
    契約の詳細はmodule docstringを参照。
    """

    def get_settings(self) -> dict:
        with self._lock:
            rows = self._conn.execute("SELECT key, value FROM settings").fetchall()
        return {row["key"]: row["value"] for row in rows}

    def set_settings(self, values: dict) -> None:
        with self._lock:
            self._conn.executemany(
                "INSERT INTO settings (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                [(key, str(value)) for key, value in values.items()],
            )
            self._conn.commit()

    def add_monitored_target(self, unique_id: str, record_video: bool = True) -> None:
        # ON CONFLICT DO NOTHING keeps an existing target's record_video preference
        # intact when the same monitor is (re)started; a removed-then-readded target
        # has no row, so the supplied value is applied fresh.
        with self._lock:
            self._conn.execute(
                "INSERT INTO monitored_targets (unique_id, added_at, record_video) VALUES (?, ?, ?)"
                " ON CONFLICT(unique_id) DO NOTHING",
                (unique_id, time.time(), 1 if record_video else 0),
            )
            self._conn.commit()

    def set_target_record_video(self, unique_id: str, record_video: bool) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE monitored_targets SET record_video = ? WHERE unique_id = ?",
                (1 if record_video else 0, unique_id),
            )
            self._conn.commit()

    def get_target_record_video(self, unique_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT record_video FROM monitored_targets WHERE unique_id = ?",
                (unique_id,),
            ).fetchone()
        return bool(row["record_video"]) if row is not None else True

    def remove_monitored_target(self, unique_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM monitored_targets WHERE unique_id = ?", (unique_id,)
            )
            self._conn.commit()

    def list_monitored_targets(self) -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT unique_id, record_video FROM monitored_targets ORDER BY added_at"
            ).fetchall()
        return [
            {"unique_id": row["unique_id"], "record_video": bool(row["record_video"])}
            for row in rows
        ]
