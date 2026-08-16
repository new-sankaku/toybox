"""Battle(PK)をrouteへ渡す単一の入口。

Battleは**session終了時にしか永続化されない**(_persist_final)。収集中はlive collectorが
持つ一覧が唯一の最新なので、そちらを渡す。どちらの経路も勝敗はcore.battleの確定判定へ
揃って返る(live側はbattles_snapshot、保存側はbattles_for_sessionがannotate_result済み)。

routeごとにこの分岐を書いてはならない。同じ「そのsessionのBattle」を2箇所が別実装で
持つと、片方だけが収集中のsessionでPKを1戦も出さない状態になる(doc/BUG_CHECKLIST.mdの
gift窓の二重実装と同じ壊れ方)。
"""
import asyncio

from tictok.api import runtime


async def battles_for_session(unique_id: str, session_id: int) -> list:
    """そのsessionのBattle一覧。

    live側だけevent loopに残すのは、あれがprocess内のsnapshotで、別threadから覗くと
    収集中のcollectorが書き換えている最中の状態を掴むため。終わったsessionを読む側は
    DBなので、書き込みlockを待つあいだloopを明け渡す。
    """
    collector = runtime.manager.get(unique_id)
    if collector is not None and collector.session_id == session_id:
        return collector.battles_snapshot()["battles"]
    return await asyncio.to_thread(runtime.storage.battles_for_session, session_id)
