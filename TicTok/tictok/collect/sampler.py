"""実配信の生eventサンプルを重複を抑えて保存する診断用サンプラー。

TikTokが実際にどのfieldをどう埋めて送ってくるかは配信・状況依存で事前に分からない
(例: ギフターLvの数値がbadgeのどのoverlay text fieldに入るか)。運用中の実eventを
「構造(shape)が新しいものだけ」1件ずつ保存しておくことで、後から実値を確認して実装を
確定できる。容量を圧迫しないよう、shape単位のdedupとkind別の件数上限で抑える。

保存先: samples/<kind>.jsonl (1 event = 1行 JSON)。dedup用のseen signatureは起動時に
既存jsonlから復元するので、Session/再起動をまたいでも同じshapeは二重取得しない。
"""

import json
import logging
from pathlib import Path
from typing import Any, Optional

from .proto_dict import safe_event_to_dict as _event_to_dict

logger = logging.getLogger("tictok.sampler")


def _shape_signature(value: Any, depth: int = 0) -> str:
    """dict/listを値ではなく「埋まっているfield path集合」に畳んだ署名。同じ構造の
    eventは同じ署名になり、値だけ違うeventはdedupされる。listは要素shapeのunionを取り、
    要素数には依存しない(件数違いで無限に増えないように)。深さは安全のため制限する。"""
    if depth > 12:
        return "…"
    if isinstance(value, dict):
        parts = []
        for key in sorted(value.keys()):
            child = value[key]
            if child is None or child == "" or child == [] or child == {}:
                continue
            parts.append(f"{key}:{_shape_signature(child, depth + 1)}")
        return "{" + ",".join(parts) + "}"
    if isinstance(value, (list, tuple)):
        inner = sorted({_shape_signature(v, depth + 1) for v in value})
        return "[" + "|".join(inner) + "]"
    return "·"


class EventSampler:
    """kind別に、未見shapeのeventを上限件数まで保存する。実API mode専用(simulationは
    生protoが無い)。呼び出しは単一event loop threadからのみを想定。"""

    def __init__(self, sample_dir: str, max_per_kind: int) -> None:
        self._dir = Path(sample_dir)
        self._max_per_kind = max(1, int(max_per_kind))
        # kind -> 既に保存済みのshape署名set / 保存件数。起動時に既存jsonlから復元する。
        self._seen: dict = {}
        self._counts: dict = {}
        self._load_existing()

    def _load_existing(self) -> None:
        if not self._dir.exists():
            return
        for path in self._dir.glob("*.jsonl"):
            kind = path.stem
            seen = self._seen.setdefault(kind, set())
            count = 0
            try:
                with path.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        count += 1
                        try:
                            sig = json.loads(line).get("sig")
                        except Exception:
                            sig = None
                        if sig:
                            seen.add(sig)
            except Exception:
                # 既存sampleのseen署名を復元できないと、その kind は同じshapeを
                # 上限まで取り直す(重複が増えるだけで収集は継続する)。
                logger.warning(
                    "kind %s の既存sampleを読み込めませんでした。既に観測済みのshapeを"
                    "再度captureする可能性があります", kind, exc_info=True,
                    extra={"event": "collector.sample_load_failed",
                           "ctx": {"kind": kind, "path": str(path)}},
                )
            self._counts[kind] = count

    def capture(self, kind: str, event: Any, meta: Optional[dict] = None) -> bool:
        """未見shapeなら1件保存してTrue。dedup/上限で保存しなければFalse。例外は握り
        つぶさずStackTraceを残すが、収集本流は止めない。"""
        try:
            if self._counts.get(kind, 0) >= self._max_per_kind:
                return False
            payload = _event_to_dict(event)
            sig = _shape_signature(payload)
            seen = self._seen.setdefault(kind, set())
            if sig in seen:
                return False
            record = {"kind": kind, "sig": sig, **(meta or {}), "payload": payload}
            self._dir.mkdir(parents=True, exist_ok=True)
            with (self._dir / f"{kind}.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            seen.add(sig)
            self._counts[kind] = self._counts.get(kind, 0) + 1
            logger.info(
                "%s の新しいsample shapeをcaptureしました（%d/%d）",
                kind, self._counts[kind], self._max_per_kind,
                extra={"event": "collector.sample_captured",
                       "ctx": {"kind": kind, "count": self._counts[kind],
                               "max_per_kind": self._max_per_kind}},
            )
            return True
        except Exception:
            # 診断用の任意機能。収集本流には影響しないが、sampleが貯まらない理由が
            # 分からなくなるので無音にはしない。
            logger.warning(
                "kind %s のevent sample captureに失敗しました。このshapeは記録されません",
                kind, exc_info=True,
                extra={"event": "collector.sample_capture_failed",
                       "ctx": {"kind": kind}},
            )
            return False
