"""ギフターが自分でも配信しているか(と、その配信者リーグ帯)を取得するworker。

取得経路は2段で、どちらもHTTP GET1発である。browser(live_resolver)は要らない:

  1. ``/api-live/user/room/`` に @handle を渡す → roomId。**offlineでも返る**。
     LIVE不可/未経験の相手はここで UserNotFoundError になり、これが「配信しない人」の
     判定そのものになる。
  2. ``/webcast/gift/list/`` に room_id を渡す → ``anchor_ranking_league``。
     room が終了済みでも引ける(5日前・7日前の室で実測)。返るのは**その日の**リーグ帯で、
     過去に遡って当時の値を取ることはできない。

room_id無し・存在しないroom_idに対しては D5 が返る。実在のD5と区別できないが、D帯は
1度配信しただけでも付くため表示に値しない。判定は tictok/core/league.py に集約してある。

レートについて: 2秒間隔・約250件で連続14件が応答不能(HTMLが返りJSONとして読めない)に
なることを実測した。既定15秒はその実測に対する余裕であり、詰めると収集本体とは別に
IP単位で弾かれる。LIVE確認(ProbeGate)とは別枠のアクセスなので、あちらの上限では守れない。
"""
import asyncio
import logging
import time
from typing import Optional

from TikTokLive import TikTokLiveClient
from TikTokLive.client.errors import UserNotFoundError
from TikTokLive.client.web.routes.fetch_room_id_api import FetchRoomIdAPIRoute

from tictok.collect.collector import _extract_league
from tictok.core.logctx import log_context

logger = logging.getLogger("tictok.league")

# 待ち行列へ積み直す間隔と、母集合に含めるgiftの窓。窓を24時間の移動窓にするのは、
# 日付境界で「その日ぶん」が切り替わる瞬間に取りこぼしを作らないためである。
ENQUEUE_INTERVAL_SECONDS = 600.0
GIFT_WINDOW_SECONDS = 86400.0
# 同じ相手で失敗を繰り返しても行列を塞がない上限。降ろしても users には何も書かないので、
# 次にgiftすれば未確認として積み直される。
MAX_ATTEMPTS = 5
# 取得に使う内部client。実room(接続先)を持たないweb呼び出し専用なので、@handleは識別子。
_CLIENT_HANDLE = "@_tictok_league"


class GifterLeagueWorker:
    """待ち行列を1件ずつ流すworker。1 processに1本だけ動かす。"""

    def __init__(self, storage, settings) -> None:
        self._storage = storage
        self._settings = settings
        self._client: Optional[TikTokLiveClient] = None
        self._last_enqueue = 0.0

    def _web(self):
        if self._client is None:
            self._client = TikTokLiveClient(unique_id=_CLIENT_HANDLE)
        return self._client.web

    async def _fetch(self, unique_id: str) -> tuple:
        """(配信者か, room_id, league) を返す。呼び出し元が例外種別で再試行を決める。"""
        web = self._web()
        # 前の相手のroom_idを引きずらない。web.paramsは全requestへ混ぜられるため、
        # 残したままだと@handleでの照会に他人の室が付く。
        web.params.pop("room_id", None)
        try:
            room_data = await FetchRoomIdAPIRoute.fetch_user_room_data(web=web, unique_id=unique_id)
        except UserNotFoundError:
            # LIVE不可/一度も配信していない/存在しない。これは変わりにくい恒久属性なので、
            # 失敗ではなく「配信しない人」という確定結果として保存する。
            return False, "", ""
        user = (room_data.get("data") or {}).get("user") or {}
        room_id = str(user.get("roomId") or "")
        if not room_id:
            # 応答は読めたが室が無い。観測結果として確定させる(捏造せず、リーグは空)。
            return False, "", ""
        web.params["room_id"] = room_id
        league = _extract_league(await web.fetch_gift_list())
        return True, room_id, league

    async def _process_one(self) -> bool:
        """待ち行列の先頭を1件処理する。処理したらTrue、行列が空ならFalse。"""
        target = await asyncio.to_thread(self._storage.next_gifter_league_target)
        if target is None:
            return False
        identity_key = target["identity_key"]
        unique_id = target["unique_id"]
        interval = float(self._settings.get("gifter_league_interval_seconds"))
        with log_context(unique_id=unique_id):
            try:
                broadcaster, room_id, league = await self._fetch(unique_id)
            except Exception as exc:
                # 応答が読めない(レート制限のHTML等)/一時的な通信断。attemptsに応じて
                # 間隔を空けて再試行する。行列に残るので取りこぼしにはならない。
                retry_after = interval * (2 ** min(int(target["attempts"]), 4))
                await asyncio.to_thread(
                    self._storage.defer_gifter_league, identity_key,
                    f"{type(exc).__name__}: {exc}", retry_after, MAX_ATTEMPTS,
                )
                logger.warning(
                    "リーグ取得に失敗しました（%.0f秒後に再試行）: %s",
                    retry_after, exc, exc_info=True,
                    extra={"event": "league.fetch_failed",
                           "ctx": {"identity_key": identity_key, "target_unique_id": unique_id,
                                   "attempts": int(target["attempts"]) + 1,
                                   "retry_after_seconds": retry_after,
                                   "error": f"{type(exc).__name__}: {exc}"[:200]}},
                )
                return True
            await asyncio.to_thread(
                self._storage.save_gifter_league, identity_key, broadcaster, room_id, league,
            )
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "リーグを確認しました: broadcaster=%s league=%s",
                    broadcaster, league or "-",
                    extra={"event": "league.checked",
                           "ctx": {"identity_key": identity_key, "target_unique_id": unique_id,
                                   "broadcaster": broadcaster, "league": league,
                                   "room_id": room_id}},
                )
        return True

    async def _enqueue_due(self) -> None:
        now = time.time()
        if (now - self._last_enqueue) < ENQUEUE_INTERVAL_SECONDS:
            return
        self._last_enqueue = now
        added = await asyncio.to_thread(
            self._storage.enqueue_gifter_leagues,
            now - GIFT_WINDOW_SECONDS,
            int(self._settings.get("gifter_league_min_coin")),
            float(self._settings.get("gifter_league_recheck_days")) * 86400.0,
        )
        if added:
            stats = await asyncio.to_thread(self._storage.gifter_league_stats)
            logger.info(
                "リーグ取得の待ち行列へ %d 人を追加しました（待機 %d 人）",
                added, stats["pending"],
                extra={"event": "league.enqueued",
                       "ctx": {"added": added, **stats}},
            )

    async def run(self) -> None:
        while True:
            interval = float(self._settings.get("gifter_league_interval_seconds"))
            try:
                if not int(self._settings.get("gifter_league_enabled")):
                    # offの間は積みも取りもしない。取得済みの表示はDBに残る。
                    await asyncio.sleep(interval)
                    continue
                await self._enqueue_due()
                processed = await self._process_one()
            except asyncio.CancelledError:
                raise
            except Exception:
                # 1件の事故でworkerごと死ぬと、以後リーグは永久に更新されない。
                logger.exception(
                    "リーグ取得workerで想定外の例外が発生しました",
                    extra={"event": "league.worker_failed", "ctx": {}},
                )
                processed = False
            # 行列が空のときまで15秒で回す必要は無いが、次の投入をすぐ拾えるようにする。
            await asyncio.sleep(interval if processed else ENQUEUE_INTERVAL_SECONDS / 10)

    async def aclose(self) -> None:
        if self._client is None:
            return
        # web.close() ではなくhttpx clientを直に閉じる。前者はcurl_cffi(この環境では
        # 未install=None)を無条件に触るため AttributeError で終了処理が止まる。
        # ここで使う経路はhttpxのみなので、閉じるべき資源もそれだけである。
        await self._client.web.httpx_client.aclose()
        self._client = None
