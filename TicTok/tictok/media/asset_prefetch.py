"""配信中に、焼き込みが使うasset(gift icon / user avatar / custom emote)を先行取得する。

焼き込み(tictok.record.video_overlay)は実行時に不足assetをURLからdownloadするが、TikTokの
CDN URLは署名/地域hostのため配信が終わると403になり、そのassetは二度と取れない。取り逃した
ぶんは頭文字円盤や透明な余白へ縮退し、後から直す手段が無い。そこでevent着信の時点で同じ
pool・同じfile名へ落としておき、焼き込み側をcache hitだけで済ませる。

pool と file名は焼き込みが読むものと同一である必要があり、実体は既存のstore側が持つ:
  gift icon : :class:`tictok.media.gift_icons.GiftIconCache` -> ``<gift_id>.img``
  avatar    : :class:`tictok.media.avatar_pool.AvatarPool`   -> ``<avatar_key(user)>.img``
  emote     : :class:`tictok.media.emote_pool.EmotePool`     -> ``<emote_id>.img``
ここが持つのは「いつ・どれだけ取りに行くか」だけで、名前も置き場も決めない。

event ingestのhot pathから呼ばれるため、投入(``submit_*``)は同期・非blockingで、queueへ積む
だけで戻る。実際のdownloadは有界queueを消費するworkerが行う。queueが満杯なら**捨てる**
(積み増して収集を詰まらせない)。捨てたことはlogに残す — 黙って落とすとそのassetが焼き込みで
欠ける理由が後から辿れない。

GPUは使わない。avatarの超解像は録画・文字起こしとGPUを奪い合うので、ここでは行わない。
"""

import asyncio
import json
import logging
import time
from typing import Optional

from tictok.media.avatar_pool import _avatar_identity, _url_res_hint, avatar_key

logger = logging.getLogger("tictok.asset_prefetch")

KIND_GIFT_ICON = "gift_icon"
KIND_AVATAR = "avatar"
KIND_EMOTE = "emote"

# 1件あたりの取得試行回数。GiftIconCache / EmotePool は自前の再試行を持たないのでここで
# 1回だけ再試行する。AvatarPool は attempts/backoff を設定で持ち内部で再試行するため、
# ここで重ねると試行回数が積算され、rate limit blockを早める。
_ATTEMPTS = {KIND_GIFT_ICON: 2, KIND_AVATAR: 1, KIND_EMOTE: 2}
_RETRY_DELAY_SECONDS = 1.0

# queue溢れの報告間隔(秒)。溢れるときは毎eventで溢れるので、1件1行だとlogが埋まる。
_DROP_REPORT_INTERVAL_SECONDS = 60.0
# 「取得済み」として覚えるassetの上限(件)。1件は数十byteなので5万件でも数MBに収まる。
_KNOWN_LIMIT = 50000


class _RateGate:
    """要求の開始間隔をならすgate。毎秒 ``per_second`` 件を上限に、次に開始してよい時刻を
    予約していく。worker本数(=同時DL数)とは別の軸で、短時間に集中した取得がCDNの
    rate limitへ当たるのを防ぐ。"""

    def __init__(self, per_second: float) -> None:
        self._interval = 1.0 / per_second if per_second > 0 else 0.0
        self._next_at = 0.0

    async def wait(self) -> None:
        if self._interval <= 0:
            return
        loop = asyncio.get_running_loop()
        now = loop.time()
        start_at = max(now, self._next_at)
        self._next_at = start_at + self._interval
        delay = start_at - now
        if delay > 0:
            await asyncio.sleep(delay)


class AssetPrefetcher:
    """有界queue＋worker で焼き込みassetを配信中に先行取得する。

    投入側(collector)は ``submit_*`` を同期で呼ぶだけ。同じassetが多重に積まれないよう
    処理中/待機中のkeyでdedupし、既にdiskに在るものはstore側の安価な判定(``has`` /
    ``needs_update``)で投入前に落とす。"""

    def __init__(
        self,
        gift_icons=None,
        avatar_pool=None,
        emote_pool=None,
        concurrency: int = 8,
        queue_size: int = 4000,
        rate_per_second: float = 16.0,
    ) -> None:
        self._gift_icons = gift_icons
        self._avatar_pool = avatar_pool
        self._emote_pool = emote_pool
        self._concurrency = max(1, int(concurrency))
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=max(1, int(queue_size)))
        self._gate = _RateGate(rate_per_second)
        self._workers: list = []
        # 待機中/処理中のasset key。完了時に外すので、常にqueue長で頭打ちになる。
        self._pending: set = set()
        self._counts = {"submitted": 0, "done": 0, "failed": 0, "dropped": 0, "deduped": 0}
        self._last_drop_report = 0.0
        # 「もうpoolに在る」と確かめ済みのasset。(kind, key) -> avatarは(識別子, 解像度)、
        # 他はTrue。submit側の「既にcache済みか」の判定はこれだけを見て、diskには触らない。
        # 以前はeventごとにpoolのstat(+meta読み)をevent loop上で行っていて、diskが応答
        # しない間(Windows Updateの復元ポイント作成)はcommentの処理でloopが止まった。
        # 初見のassetはqueueへ積み、worker側(thread)でdiskを見て、結果をここへ覚える。
        self._known: dict = {}

    def start(self) -> None:
        """workerを起こす。event loopの中から呼ぶこと(serverのlifespan)。"""
        if self._workers:
            return
        self._workers = [
            asyncio.create_task(self._worker(i), name=f"asset-prefetch-{i}")
            for i in range(self._concurrency)
        ]
        logger.info(
            "assetの先行取得を開始しました（worker %d本, queue上限 %d件）",
            self._concurrency, self._queue.maxsize,
            extra={"event": "prefetch.started",
                   "ctx": {"workers": self._concurrency, "queue_size": self._queue.maxsize}},
        )

    async def aclose(self) -> None:
        """workerを止める。取得元のstore(httpx client)を閉じる**前**に呼ぶこと。"""
        for task in self._workers:
            task.cancel()
        for task in self._workers:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._workers = []
        logger.info(
            "assetの先行取得を停止しました（取得 %d件, 失敗 %d件, 溢れ %d件, 未処理 %d件）",
            self._counts["done"], self._counts["failed"], self._counts["dropped"],
            self._queue.qsize(),
            extra={"event": "prefetch.stopped", "ctx": {**self._counts,
                                                        "queued": self._queue.qsize()}},
        )

    def stats(self) -> dict:
        """投入・取得・溢れの累計と現在のqueue長。"""
        return {**self._counts, "queued": self._queue.qsize(), "pending": len(self._pending)}

    def submit_gift_icon(self, gift_id: int, url: str) -> None:
        """gift eventのicon URLを先行取得へ積む。既にcache済みなら何もしない。"""
        if self._gift_icons is None or not gift_id or not url:
            return
        gift_id = int(gift_id)
        if self._known.get((KIND_GIFT_ICON, str(gift_id))):
            return
        self._submit(KIND_GIFT_ICON, str(gift_id), gift_id, url)

    def submit_avatar(self, user_key: Optional[str], url: Optional[str]) -> None:
        """comment/gift等のuser avatarを先行取得へ積む。

        既にpoolが同じか良いrenditionを持つ場合は積まない。判定(``needs_update``)はstat＋
        小さなmeta読みだけで、同一userの再送・再署名URLをここで落とすためhot pathでも安い。"""
        if self._avatar_pool is None or not user_key or not url:
            return
        # dedup keyは保存先file名(avatar_key)に揃える。unique_idとnicknameが混ざって
        # 届いても、同じ人物のavatarが二重に積まれない。
        key = avatar_key(user_key)
        known = self._known.get((KIND_AVATAR, key))
        # 同じavatar(識別子が同じ)で、覚えている解像度以下の再送・再署名URLはdiskを見ずに
        # 落とす。別のavatarや高解像度版はpool側の判定(needs_update)へ回す。
        if known is not None and known[0] == _avatar_identity(url) and _url_res_hint(url) <= known[1]:
            return
        self._submit(KIND_AVATAR, key, user_key, url)

    def submit_emotes(self, raw) -> None:
        """commentの ``emotes`` payload(JSON文字列またはlist)からemote画像を積む。"""
        if self._emote_pool is None or not raw:
            return
        try:
            emotes = raw if isinstance(raw, list) else json.loads(raw)
        except (ValueError, TypeError):
            logger.warning(
                "commentのemote payloadを解釈できないため先行取得しません",
                extra={"event": "prefetch.emote_payload_invalid", "ctx": {}},
                exc_info=True,
            )
            return
        if not isinstance(emotes, list):
            return
        for emote in emotes:
            if not isinstance(emote, dict):
                continue
            emote_id = str(emote.get("id") or "")
            url = emote.get("url") or ""
            # 既にdiskに在るもの、file名に使えないid、許可外hostのURLはqueueに載せない。
            # 後ろ2つは何度試しても結果が変わらないので、slotも再試行も使わせない。
            # idとURLの検証(diskを見ない)はここで、cacheの有無(stat)はworker側の
            # persist -> should_fetch が見る。ここで見るのは覚えている「取得済み」だけ。
            if not self._emote_pool.is_fetchable(emote_id, url):
                continue
            if self._known.get((KIND_EMOTE, emote_id)):
                continue
            self._submit(KIND_EMOTE, emote_id, emote_id, url)

    def _submit(self, kind: str, key: str, target, url: str) -> None:
        """有界queueへ1件積む。既に同じassetが待機/処理中なら積まない。満杯なら捨てる。"""
        dedup_key = (kind, key)
        if dedup_key in self._pending:
            self._counts["deduped"] += 1
            return
        try:
            self._queue.put_nowait((kind, dedup_key, target, url))
        except asyncio.QueueFull:
            self._counts["dropped"] += 1
            self._report_drop(kind)
            return
        self._pending.add(dedup_key)
        self._counts["submitted"] += 1

    def _remember(self, kind: str, target, url: str) -> None:
        """poolに在ると確かめたassetを覚える(submit側の判定用)。上限を超えたら全部忘れる —
        忘れても次の投入がworkerで確かめ直すだけで、取り逃しは起きない。"""
        if len(self._known) >= _KNOWN_LIMIT:
            self._known.clear()
        if kind == KIND_AVATAR:
            key = (KIND_AVATAR, avatar_key(target))
            res = _url_res_hint(url)
            previous = self._known.get(key)
            if previous is not None and previous[0] == _avatar_identity(url):
                res = max(res, previous[1])
            self._known[key] = (_avatar_identity(url), res)
        else:
            self._known[(kind, str(target))] = True

    def _report_drop(self, kind: str) -> None:
        """溢れの報告。溢れる状況では毎eventで起きるので間隔を空けて出す。"""
        now = time.monotonic()
        if self._last_drop_report and (now - self._last_drop_report) < _DROP_REPORT_INTERVAL_SECONDS:
            return
        self._last_drop_report = now
        logger.warning(
            "assetの先行取得queueが満杯のため取得を見送りました（累計 %d件, 直近 kind=%s）。"
            "見送ったassetは署名URLの失効後は取得できず、焼き込みで欠けます",
            self._counts["dropped"], kind,
            extra={"event": "prefetch.queue_overflow",
                   "ctx": {"kind": kind, "dropped": self._counts["dropped"],
                           "queue_size": self._queue.maxsize,
                           "workers": self._concurrency}},
        )

    async def _worker(self, index: int) -> None:
        while True:
            kind, dedup_key, target, url = await self._queue.get()
            try:
                await self._fetch(kind, target, url)
            except asyncio.CancelledError:
                raise
            except Exception:
                self._counts["failed"] += 1
                # store側が握るはずの例外がここまで来た = 想定外。握り潰さず残す。
                logger.warning(
                    "assetの先行取得が想定外の例外で終わりました（kind=%s）: %s", kind, url,
                    extra={"event": "prefetch.fetch_failed",
                           "ctx": {"kind": kind, "worker": index}},
                    exc_info=True,
                )
            finally:
                self._pending.discard(dedup_key)
                self._queue.task_done()

    async def _fetch(self, kind: str, target, url: str) -> None:
        """1件を取得する。取得結果が偽なら ``_ATTEMPTS`` の範囲で1度だけ試し直す。"""
        attempts = _ATTEMPTS[kind]
        for attempt in range(1, attempts + 1):
            await self._gate.wait()
            if kind == KIND_GIFT_ICON:
                ok = await self._gift_icons.persist(target, url)
            elif kind == KIND_AVATAR:
                ok = await self._avatar_pool.persist(target, url)
            else:
                ok = await self._emote_pool.persist(target, url)
            if ok:
                self._counts["done"] += 1
                self._remember(kind, target, url)
                return
            if attempt < attempts:
                await asyncio.sleep(_RETRY_DELAY_SECONDS * attempt)
        # 個々の失敗理由はstore側が既にlogへ出している。ここは「再試行も尽きた」件数だけ数える。
        self._counts["failed"] += 1
