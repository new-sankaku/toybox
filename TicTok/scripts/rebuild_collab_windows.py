"""samples/raw の生LinkLayerEventから、コラボ窓を現行ruleで作り直す。

判定rule(core.collab)の版を上げると、分析は現行版の窓だけを集計するので過去の窓が
すべて落ちる。生captureが残っているsessionは、そこから同じruleで作り直せば版を上げても
data を失わない。collectorの窓管理(_on_link_layer / _close_open_collab_windows)と同じ
手順をここで再現する — 手順が割れると「作り直した窓」と「これから収集する窓」が
別ruleになる。

    venv/Scripts/python scripts/rebuild_collab_windows.py [--apply] [--session N ...]

既定は dry-run で、差分だけを出す。--apply でDBへ書く。
"""
import argparse
import dataclasses
import functools
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import TikTokLive.proto as proto

from tictok.core import config
from tictok.core.collab import COLLAB_WINDOW_VERSION, linkmic_state

_MESSAGE = proto.WebcastLinkLayerMessage


@functools.lru_cache(maxsize=None)
def _proto_fields(tp) -> dict:
    """betterprotoのmessage classの field名 -> (型, repeatedか)。

    注釈は文字列で来る(``List["X"]`` / ``Optional["X"]`` 等)ので、識別子を拾って
    proto moduleから引く。message以外(scalar/enum)は型Noneで、field集合の判定にだけ使う。"""
    if tp is None or not hasattr(tp, "__dataclass_fields__"):
        return {}
    out = {}
    for f in dataclasses.fields(tp):
        text = str(f.type)
        cls = None
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text):
            cls = getattr(proto, token, None)
            if cls is not None and hasattr(cls, "__dataclass_fields__"):
                break
            cls = None
        out[f.name] = (cls, text.startswith("List[") or "List[" in text)
    return out


class _Obj:
    """生capture(JSON)を実eventと同じ経路で読ませる衣。

    ただのdictでは判定が本番と違う枝を通る。betterprotoは **protoに在るfield**を未設定でも
    空messageで返し、**在らないfield**はAttributeErrorになる。判定側は
    ``getattr(content, "user_list", None) or getattr(content, "all_users", None)`` のように
    その差で枝を選んでいるため、どちらも空objectで返すと ``closed_by`` が本番と違う名前に
    なる(実際に list_content と join_direct_content が入れ替わった)。ここではprotoの型を
    連れて歩き、field集合まで実物に合わせる。"""

    __slots__ = ("_d", "_t")

    def __init__(self, d, tp):
        self._d = d
        self._t = tp

    def __getattr__(self, name):
        fields = _proto_fields(self._t)
        if fields and name not in fields:
            raise AttributeError(name)       # protoに無いfield: 実物と同じく生えていない
        tp, repeated = fields.get(name, (None, False))
        v = self._d.get(name)
        if isinstance(v, dict):
            return _Obj(v, tp)
        if isinstance(v, list):
            return [_Obj(x, tp) if isinstance(x, dict) else x for x in v]
        if v is not None:
            return v
        if repeated:
            return []                        # 未設定のrepeatedは空list
        if tp is not None and hasattr(tp, "__dataclass_fields__"):
            return _Obj({}, tp)              # 未設定のmessageは空message
        return None

    def __bool__(self):
        return bool(self._d)


def rebuild(rows: list, last_data_at: float) -> list:
    """collectorと同じ手順で窓を作る。

    ``last_data_at`` は配信が生きていた最後の時刻。開いたままの窓の終端に使う
    (collector._open_collab_end と同じ)。"""
    own = str(rows[0].get("owner_id") or "")
    open_: dict = {}
    windows: list = []

    def record(channel_id, state, end, closed_by):
        return {
            "channel_id": channel_id,
            "start": state["start"],
            "end": end,
            "guests_max": state["guests_max"],
            "version": COLLAB_WINDOW_VERSION,
            "peers": sorted(state["peers"]),
            "opened_by": state["opened_by"],
            "closed_by": closed_by,
        }

    for row in rows:
        payload = row.get("payload") or {}
        channel_id = str(payload.get("channel_id") or "")
        if not channel_id:
            continue
        now = row["t"]
        state = open_.get(channel_id)
        result = linkmic_state(
            _Obj(payload, _MESSAGE), own, str(row.get("room_id") or ""),
            {uid: (state or {}).get("peer_rooms", {}).get(uid, "")
             for uid in (state or {}).get("now_peers", ())},
        )
        connected = result["connected"]
        if connected is None:
            continue
        if connected and state is None:
            state = {"start": now, "guests_max": 0, "peers": set(), "now_peers": set(),
                     "peer_rooms": {}, "opened_by": result["source"]}
            open_[channel_id] = state
        if state is not None and connected:
            peers = {p for p in result["peers"] if p != own}
            state["peers"] |= peers
            state["now_peers"] = peers
            state["guests_max"] = max(state["guests_max"], len(peers))
            state["peer_rooms"].update(
                {uid: room for uid, room in (result["peer_rooms"] or {}).items()
                 if room and uid in peers}
            )
        if not connected and state is not None:
            open_.pop(channel_id, None)
            if now > state["start"]:
                windows.append(record(channel_id, state, now, result["source"]))
    for channel_id, state in open_.items():
        if last_data_at > state["start"]:
            windows.append(record(channel_id, state, last_data_at, "session_end"))
    windows.sort(key=lambda w: w["start"])
    return windows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="DBへ書く(既定はdry-run)")
    ap.add_argument("--session", type=int, action="append", help="対象session(既定は全件)")
    args = ap.parse_args()

    db = config.get_db_path()
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    raw_dir = Path(os.environ.get("TICTOK_SAMPLE_DIR")
                   or Path(config.PROJECT_ROOT) / "samples") / "raw"
    if not raw_dir.is_dir():
        print(f"生captureのdirectoryがありません: {raw_dir}")
        return 1

    total_old = total_new = 0
    changed = 0
    for path in sorted(raw_dir.glob("LinkLayerEvent_*.jsonl")):
        sid = int(re.search(r"_(\d+)\.jsonl$", path.name).group(1))
        if args.session and sid not in args.session:
            continue
        sess = conn.execute(
            "SELECT id, status, started_at, ended_at FROM sessions WHERE id = ?", (sid,)
        ).fetchone()
        if sess is None:
            continue
        if sess["ended_at"] is None:
            print(f"  sid={sid} は進行中なのでskipします")
            continue
        rows = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        if not rows:
            continue
        # 配信が生きていた最後の時刻(collector._last_stream_at のDB側の代理)。
        # sessionのended_atは配信が切れた後も開いたままになることがあり、その幻の尾を
        # 窓が飲み込む(実測13.6h/8.6h)。kind='system' はcollector自身が書く記録で、
        # 再接続retryの間もそれだけが増え続けるため、配信の生存判定には使えない。
        last = max(
            [t for (t,) in conn.execute(
                "SELECT max(time) FROM events WHERE session_id = ? AND kind <> 'system'",
                (sid,)) if t]
            + [t for (t,) in conn.execute(
                "SELECT max(time) FROM viewer_samples WHERE session_id = ?", (sid,)) if t]
            + [sess["started_at"]]
        )
        last = min(last, sess["ended_at"])
        new = rebuild(rows, last)
        old = conn.execute(
            "SELECT start, end, version FROM collab_windows WHERE session_id = ? ORDER BY start",
            (sid,)).fetchall()
        old_secs = sum((r["end"] or r["start"]) - r["start"] for r in old)
        new_secs = sum(w["end"] - w["start"] for w in new)
        total_old += old_secs
        total_new += new_secs
        if len(old) != len(new) or abs(old_secs - new_secs) > 1:
            changed += 1
            print(f"  sid={sid:<5} 旧 {len(old):>3}窓/{old_secs:>8.0f}s "
                  f"→ 新 {len(new):>3}窓/{new_secs:>8.0f}s ({new_secs - old_secs:+.0f}s)")
        if args.apply:
            conn.execute("DELETE FROM collab_windows WHERE session_id = ?", (sid,))
            conn.executemany(
                "INSERT INTO collab_windows"
                " (session_id, channel_id, start, end, guests_max, version, data_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(sid, w["channel_id"], w["start"], w["end"], w["guests_max"],
                  w["version"], json.dumps(w, ensure_ascii=False)) for w in new],
            )
    if args.apply:
        # 窓を読む解析cacheは版を上げてあるのでlazyに再計算されるが、確定済みsessionの
        # 行は残るため、窓が変わったsessionの行だけ落として取り直させる。
        conn.execute(
            "DELETE FROM analytics_session_cache WHERE kind IN"
            " ('peri_share', 'peri_battle', 'join_context')")
        conn.commit()
    print(f"\n{'書き込みました' if args.apply else 'dry-run(--applyで書き込み)'}: "
          f"変化 {changed} session / 合計 {total_old:.0f}s → {total_new:.0f}s "
          f"({total_new - total_old:+.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
