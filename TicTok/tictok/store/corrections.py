"""文字起こしの訂正(transcript_corrections)の出し入れ。

境界の理由: ``transcripts`` は文字起こしの**生の出力**を持つ表で、ここは**人と機械が後から
当てた直し**を持つ表である。同じ録画を指すが寿命が違う — 生の層は再文字起こしで丸ごと
入れ替わり、訂正の層はそれを跨いで生き残る(跨がせない選択も出来る)。重ね方と照合の規則は
:mod:`tictok.record.corrections` にあり、この module は行の出し入れだけを持つ。

lock契約: ``_locked`` で終わる method は呼び出し元が self._lock を保持している前提。
``get_transcript`` が lock の中から訂正を引くため、この形が要る(self._lock は再入不可)。
"""
import time
from typing import Optional

from tictok.store._common import logger

ACTIVE = "active"
ORPHAN = "orphan"
DISCARDED = "discarded"


class CorrectionsMixin:
    """文字起こし訂正のCRUDと、再文字起こし時の引き継ぎ/破棄。

    lockもDB接続も持たない。すべて Storage が所有する self._conn / self._lock を借りる。
    """

    def _corrections_locked(self, recording_id: int, states: tuple) -> list:
        rows = self._conn.execute(
            "SELECT id, recording_id, start, src, dst, origin, confidence, note, state,"
            " created_at, updated_at FROM transcript_corrections"
            " WHERE recording_id = ? AND state IN (%s) ORDER BY start, id"
            % ",".join("?" * len(states)),
            (int(recording_id), *states),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_corrections(self, recording_id: int,
                         states: tuple = (ACTIVE, ORPHAN)) -> list:
        """1録画分の訂正。既定では破棄済みを除く(破棄は消さずに残すため)。"""
        with self._lock:
            return self._corrections_locked(recording_id, tuple(states))

    def correction_counts(self) -> dict:
        """recording_id -> {state: 件数}。一覧が「訂正あり/保留あり」を出すための集計。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT recording_id, state, COUNT(*) AS n FROM transcript_corrections"
                " GROUP BY recording_id, state"
            ).fetchall()
        out: dict = {}
        for row in rows:
            out.setdefault(row["recording_id"], {})[row["state"]] = row["n"]
        return out

    def upsert_corrections(self, recording_id: int, rows: list) -> dict:
        """訂正をまとめて入れる。同じ (start, src) の行は上書きする。

        まとめて1つのlock区間で行うのは、途中で失敗したときに「半分だけ入った訂正」が
        字幕へ出るのを避けるため。``src == dst`` の行は訂正ではないので受け付けない
        (取り込み元の生成ミスをここで止める)。
        """
        prepared = []
        for row in rows:
            src, dst = row["src"], row["dst"]
            if src == dst:
                raise ValueError(f"原文と訂正が同じです: {src!r}")
            if not dst:
                raise ValueError(f"訂正が空です: {src!r}")
            prepared.append((int(recording_id), float(row["start"]), src, dst,
                             row.get("origin") or "human", row.get("confidence"),
                             row.get("note"), ACTIVE, time.time(), time.time()))
        with self._lock:
            before = self._conn.execute(
                "SELECT COUNT(*) FROM transcript_corrections WHERE recording_id = ?",
                (int(recording_id),)).fetchone()[0]
            self._conn.executemany(
                "INSERT INTO transcript_corrections"
                " (recording_id, start, src, dst, origin, confidence, note, state,"
                "  created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(recording_id, start, src) DO UPDATE SET"
                " dst = excluded.dst, origin = excluded.origin,"
                " confidence = excluded.confidence, note = excluded.note,"
                " state = excluded.state, updated_at = excluded.updated_at",
                prepared,
            )
            after = self._conn.execute(
                "SELECT COUNT(*) FROM transcript_corrections WHERE recording_id = ?",
                (int(recording_id),)).fetchone()[0]
            self._conn.commit()
        result = {"received": len(prepared), "added": after - before,
                  "updated": len(prepared) - (after - before)}
        logger.info(
            "文字起こしの訂正を取り込みました: recording_id=%d 追加=%d 更新=%d",
            recording_id, result["added"], result["updated"],
            extra={"event": "transcript.corrections_upserted",
                   "ctx": {"recording_id": recording_id, **result}},
        )
        return result

    def set_correction_state(self, correction_ids: list, state: str) -> int:
        if state not in (ACTIVE, ORPHAN, DISCARDED):
            raise ValueError(f"未知のstateです: {state}")
        if not correction_ids:
            return 0
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE transcript_corrections SET state = ?, updated_at = ?"
                " WHERE id IN (%s)" % ",".join("?" * len(correction_ids)),
                [state, time.time(), *[int(c) for c in correction_ids]],
            )
            self._conn.commit()
        return cursor.rowcount

    def delete_correction(self, correction_id: int) -> bool:
        """1件を本当に消す。取り消しの既定は破棄(state)であって削除ではない —
        入れ間違えた行を片付けるための口である。"""
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM transcript_corrections WHERE id = ?", (int(correction_id),))
            self._conn.commit()
        return cursor.rowcount > 0

    def _carry_corrections_locked(self, recording_id: int, segments: list,
                                  policy: str) -> Optional[dict]:
        """再文字起こし後に訂正をどうするか。lock保持前提。

        ``policy`` は ``keep``(貼り直す) / ``discard``(捨てる)。捨てる場合も行は
        ``discarded`` で残す — 後から戻せるようにするためで、削除はしない。
        """
        from tictok.record.corrections import rematch

        rows = self._corrections_locked(recording_id, (ACTIVE, ORPHAN))
        if not rows:
            return None
        now = time.time()
        if policy == "discard":
            self._conn.execute(
                "UPDATE transcript_corrections SET state = ?, updated_at = ?"
                " WHERE recording_id = ? AND state IN (?, ?)",
                (DISCARDED, now, int(recording_id), ACTIVE, ORPHAN))
            return {"policy": policy, "discarded": len(rows), "matched": 0, "orphaned": 0}

        result = rematch(segments, rows)
        for correction_id, start in result["matched"]:
            self._conn.execute(
                "UPDATE transcript_corrections SET start = ?, state = ?, updated_at = ?"
                " WHERE id = ?", (float(start), ACTIVE, now, int(correction_id)))
        if result["orphaned"]:
            self._conn.execute(
                "UPDATE transcript_corrections SET state = ?, updated_at = ?"
                " WHERE id IN (%s)" % ",".join("?" * len(result["orphaned"])),
                [ORPHAN, now, *[int(c) for c in result["orphaned"]]])
        return {"policy": policy, "discarded": 0,
                "matched": len(result["matched"]), "orphaned": len(result["orphaned"])}
