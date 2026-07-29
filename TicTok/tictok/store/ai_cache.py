"""AI分析結果のcache。

境界の理由: LLM推論の結果を入れる単一tableで、target_type(session/recording)を跨いで
同じ形で使う。どのdomainにも属さないので独立させる。

lock契約: lock保持前提のmethodは無い。両methodとも自分で self._lock を取る。
"""
import json
import time
from typing import Optional


class AiCacheMixin:
    """AI分析結果のcache。

    lockもDB接続も持たない。すべて Storage が所有する self._conn /
    self._lock / self._read_lock を借りる(mixinとして Storage に混ぜられる前提)。
    契約の詳細はmodule docstringを参照。
    """

    # ----- AI分析結果のcache -----------------------------------------------------------
    # LLM推論はここへ保存し、model・prompt版・入力指紋が一致する限り再実行しない。
    # 「未計算をまとめて計算する」経路は意図的に持たない(operatorの明示要求のみで走らせる)。

    def get_ai_analysis(self, kind: str, target_type: str, target_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM ai_analysis WHERE kind = ? AND target_type = ? AND target_id = ?",
                (kind, target_type, str(target_id)),
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        try:
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
        except ValueError:
            # 壊れた行を「未分析」に化けさせない。読めなかったことを呼び出し元へ伝える。
            item.pop("payload_json", None)
            item["payload"] = None
            item["payload_unreadable"] = True
        return item

    def save_ai_analysis(self, kind: str, target_type: str, target_id: str, *,
                         session_id: Optional[int], model: str, prompt_version: int,
                         input_signature: str, payload: dict) -> dict:
        computed_at = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO ai_analysis"
                " (kind, target_type, target_id, session_id, model, prompt_version,"
                "  input_signature, payload_json, computed_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (kind, target_type, str(target_id), session_id, model, int(prompt_version),
                 input_signature, json.dumps(payload, ensure_ascii=False), computed_at),
            )
            self._conn.commit()
        return {
            "kind": kind,
            "target_type": target_type,
            "target_id": str(target_id),
            "session_id": session_id,
            "model": model,
            "prompt_version": int(prompt_version),
            "input_signature": input_signature,
            "payload": payload,
            "computed_at": computed_at,
        }
