"""Battle event probe — diagnostic raw-dump tool.

目的: 現状のCollectorが利用していないBattle系eventとfieldを、実Live PK中に生で
取得し、TikTokが実際にどのfieldを送信してくるかを確認するための検証用script。
本番のdata flowには一切影響しない読み取り専用の独立tool。

使い方 (Windows / Linux 共通):
    python scripts/battle_event_probe.py <unique_id>
    python scripts/battle_event_probe.py @kawaii_live --seconds 600

対象アカウントが PK (Battle) 中であれば、以下のeventを丸ごとJSONL化して
logs/battle_probe_<unique_id>_<ts>.jsonl に追記し、要約をconsoleへ出力する:
  - LinkMicBattleEvent         (battle_combos / battle_result / display_config など未使用field)
  - LinkMicArmiesEvent         (陣営別score推移)
  - LinkMicBattleItemCardEvent (critical strike=倍率 / smoke / extra time / potion / wave / top2,3)
  - LinkMicBattleTaskEvent     (Speed系bonus task: preview/task/reward period, gift guide)
  - LinkMicBattleNoticeEvent   (battle notice)
  - LinkMicBattleVictoryLapEvent / LinkMicBattlePunishFinishEvent (延長・罰 game)
  - GiftEvent                  (PK中のgift倍率/comboの実値確認用)

取得したJSONLを基に、どのfieldが実際に埋まるかを確認してから本実装の設計へ進む。
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

# Collectorを取り込むと import時に locale と sign API key が WebDefaults へ適用される。
# 本番と同じ認証/locale設定を流用するため、設定処理を再実装せずこれに依存する。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tictok.collect import collector  # noqa: E402  (import side effects: _apply_locale / _apply_sign_api_key)
from tictok.core.config import get_log_dir  # noqa: E402

from TikTokLive import TikTokLiveClient  # noqa: E402
from TikTokLive.events import (  # noqa: E402
    GiftEvent,
    LinkMicArmiesEvent,
    LinkMicBattleEvent,
    LinkMicBattleItemCardEvent,
    LinkMicBattlePunishFinishEvent,
    LinkMicBattleVictoryLapEvent,
    LinkmicBattleNoticeEvent,
    LinkmicBattleTaskEvent,
)

import json  # noqa: E402


def _event_to_dict(event) -> dict:
    """betterproto message を素のdictへ。失敗時は repr で握りつぶさず情報を残す。"""
    to_dict = getattr(event, "to_dict", None)
    if callable(to_dict):
        try:
            return to_dict(include_default_values=False)
        except TypeError:
            return to_dict()
    return {"_repr": repr(event)}


class BattleProbe:
    def __init__(self, unique_id: str, out_path: Path):
        self.unique_id = unique_id
        self.out_path = out_path
        self.counts: dict = {}

    def _dump(self, kind: str, event) -> None:
        self.counts[kind] = self.counts.get(kind, 0) + 1
        payload = _event_to_dict(event)
        record = {"ts": time.time(), "kind": kind, "payload": payload}
        with self.out_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        # console には埋まっている top-level field 名だけを出して当たりを付ける。
        keys = sorted(payload.keys()) if isinstance(payload, dict) else []
        print(f"[{self.counts[kind]:>4}] {kind:<28} fields={keys}")

    def register(self, client: TikTokLiveClient) -> None:
        pairs = [
            ("LinkMicBattleEvent", LinkMicBattleEvent),
            ("LinkMicArmiesEvent", LinkMicArmiesEvent),
            ("LinkMicBattleItemCardEvent", LinkMicBattleItemCardEvent),
            ("LinkmicBattleTaskEvent", LinkmicBattleTaskEvent),
            ("LinkmicBattleNoticeEvent", LinkmicBattleNoticeEvent),
            ("LinkMicBattleVictoryLapEvent", LinkMicBattleVictoryLapEvent),
            ("LinkMicBattlePunishFinishEvent", LinkMicBattlePunishFinishEvent),
            ("GiftEvent", GiftEvent),
        ]
        for kind, evt in pairs:
            client.add_listener(evt, lambda e, k=kind: self._dump(k, e))


async def run(unique_id: str, seconds: int) -> int:
    out_dir = Path(get_log_dir())
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = unique_id.lstrip("@").replace("/", "_")
    out_path = out_dir / f"battle_probe_{safe}_{int(time.time())}.jsonl"

    probe = BattleProbe(unique_id, out_path)
    client = TikTokLiveClient(unique_id=unique_id)
    probe.register(client)

    print(f"probe: @{unique_id.lstrip('@')} -> {out_path}")
    print(f"PK(Battle)中に各eventを記録します。最長 {seconds}s。Ctrl+C で停止。\n")

    async def _stop_later() -> None:
        await asyncio.sleep(seconds)
        await client.disconnect()

    stop_task = asyncio.create_task(_stop_later())
    try:
        await client.start()
    except Exception as exc:  # 検証toolなので原因をそのまま見せて終了する
        print(f"\n接続/実行エラー: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        stop_task.cancel()

    print("\n=== 受信eventサマリ ===")
    if not probe.counts:
        print("battle系eventは1件も受信しませんでした（PK中でない可能性）。")
    for kind, n in sorted(probe.counts.items()):
        print(f"  {kind:<30} {n}")
    print(f"\nJSONL: {out_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="TikTok Battle event raw-dump probe")
    parser.add_argument("unique_id", help="対象アカウント (例: @kawaii_live)")
    parser.add_argument(
        "--seconds", type=int, default=900, help="記録継続秒数 (default: 900)"
    )
    args = parser.parse_args()
    try:
        return asyncio.run(run(args.unique_id, args.seconds))
    except KeyboardInterrupt:
        print("\n停止しました。")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
