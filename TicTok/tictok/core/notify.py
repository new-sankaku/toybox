"""通知(alert)の送信層。webhookでDiscord/Slack/汎用receiverへ送る。

判定は core.alert、送信はここ。分けてあるのは、送信が唯一のI/O境界であり、失敗の扱いが
判定とは全く別の話だからである。

この層の最優先の性質は「通知の失敗が本体を止めないこと」である。alertの投入(submit)は
collectorやrecorderやDB書き込みthreadから呼ばれるので、submitは絶対にblockせず、絶対に
例外を上へ返さない。実送信はserverのevent loop上の単一workerがqueueから取り出して行う。

fallbackは置かない。宛先が未設定なら送らない(送れないものを別経路で握り潰さない)、送信に
失敗したら設定回数まで再試行し、それでも駄目なら諦めた事実を ``ops_events`` へerrorで残す。
「送ったつもりで実は届いていない」が最悪の失敗様式なので、失敗は必ず1行残る。

desktop通知(toast)は実装しない。Windows/Linuxで別々の追加libraryが要るうえ、このserverは
無人運転で常時上がっている前提であり、toastは画面の前に人が居るときにしか届かない。それは
WebSocket broadcastで既に満たされている条件で、この機能が埋めようとしている穴
(「画面を見ていない間に起きたことに気付けない」)には届かない。webhookはphoneまで届く。
"""

import asyncio
import logging
import time
from typing import Optional
from urllib.parse import urlsplit

import httpx

from tictok.core.alert import Alert, AlertRules
from tictok.core.config import (
    get_notify_queue_max,
    get_notify_shutdown_drain_seconds,
    get_notify_webhook_format,
    get_notify_webhook_urls,
)
from tictok.storage import OPS_ERROR, OPS_INFO, OPS_WARNING

logger = logging.getLogger("tictok.notify")

FORMAT_DISCORD = "discord"
FORMAT_SLACK = "slack"
FORMAT_GENERIC = "generic"
WEBHOOK_FORMATS = (FORMAT_DISCORD, FORMAT_SLACK, FORMAT_GENERIC)

# host -> payload形式。protocolの差(bodyのschema)を吸収するための対応表であって、policyでは
# ない。宛先を増やすときはここへ足すか、TICTOK_NOTIFY_WEBHOOK_FORMATで明示する。
_FORMAT_BY_HOST = {
    "discord.com": FORMAT_DISCORD,
    "discordapp.com": FORMAT_DISCORD,
    "ptb.discord.com": FORMAT_DISCORD,
    "canary.discord.com": FORMAT_DISCORD,
    "hooks.slack.com": FORMAT_SLACK,
}

# Discordのembed左端の色。severityを色で分けるためだけの値。
_DISCORD_COLORS = {OPS_ERROR: 0xD64541, OPS_WARNING: 0xE0A32E, OPS_INFO: 0x4A90D9}
_SEVERITY_MARK = {OPS_ERROR: "[ERROR]", OPS_WARNING: "[WARN]", OPS_INFO: "[INFO]"}


def resolve_format(url: str) -> str:
    """1つの宛先URLのpayload形式を決める。

    設定が auto 以外なら全宛先をその形式で送る。autoはhostで判定し、判定できないものは
    汎用JSON(alertをそのまま入れたbody)にする。汎用JSONは「判定に失敗したのでとりあえず何か
    送る」のではなく、自作receiver向けの正式な形式である。
    """
    configured = get_notify_webhook_format()
    if configured in WEBHOOK_FORMATS:
        return configured
    if configured != "auto":
        raise ValueError(
            f"TICTOK_NOTIFY_WEBHOOK_FORMAT が不正です: {configured!r} "
            f"(auto / {' / '.join(WEBHOOK_FORMATS)} のいずれか)"
        )
    host = (urlsplit(url).hostname or "").lower()
    return _FORMAT_BY_HOST.get(host, FORMAT_GENERIC)


def redact_url(url: str) -> str:
    """log・画面へ出すためのwebhook URL。webhook URLはpathに投稿tokenを含む資格情報なので、
    hostとpathの先頭だけを残す。"""
    parts = urlsplit(url)
    host = parts.hostname or "?"
    # portまで残す。落とすと、同一host別portの宛先が画面上で見分けられなくなる。
    if parts.port:
        host = f"{host}:{parts.port}"
    head = (parts.path or "/").split("/")
    keep = "/".join(head[:3])
    return f"{parts.scheme}://{host}{keep}/***"


def _plain_text(alert: Alert) -> str:
    mark = _SEVERITY_MARK.get(alert.severity, "")
    return f"{mark} {alert.title}\n{alert.message}".strip()


def build_payload(alert: Alert, fmt: str) -> dict:
    """1件のalertを、その宛先形式のrequest bodyへ組む。"""
    if fmt == FORMAT_DISCORD:
        fields = [
            {"name": key, "value": f"{value}"[:1024], "inline": True}
            for key, value in list(alert.detail.items())[:10]
        ]
        return {
            "content": _SEVERITY_MARK.get(alert.severity, ""),
            "embeds": [{
                "title": alert.title[:256],
                "description": alert.message[:4096],
                "color": _DISCORD_COLORS.get(alert.severity, _DISCORD_COLORS[OPS_INFO]),
                "timestamp": time.strftime(
                    "%Y-%m-%dT%H:%M:%S", time.gmtime(alert.ts)) + "Z",
                "fields": fields,
            }],
        }
    if fmt == FORMAT_SLACK:
        return {"text": _plain_text(alert)}
    return {"source": "tictok", "text": _plain_text(alert), "alert": alert.as_dict()}


class Notifier:
    """alertをwebhookへ送るbackground worker。

    ``submit`` はthread safeでnon-blocking。``start``/``stop`` はserverのlifespanから呼ぶ。
    """

    def __init__(self, storage, settings, rules: Optional[AlertRules] = None,
                 client: Optional[httpx.AsyncClient] = None) -> None:
        self._storage = storage
        self._settings = settings
        self.rules = rules if rules is not None else AlertRules(settings)
        self._client = client
        self._owns_client = client is None
        self._queue: Optional[asyncio.Queue] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._task: Optional[asyncio.Task] = None
        self._dropped = 0
        self._drop_reported = False
        self.sent = 0
        self.failed = 0

    # ----- lifecycle ---------------------------------------------------------------
    def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("Notifierは既に開始されています。")
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=float(self._settings.get("notify_timeout_seconds"))
            )
        self._task = asyncio.create_task(self._worker(), name="tictok-notifier")
        targets = get_notify_webhook_urls()
        logger.info(
            "notifierを開始しました（webhookの宛先 %d 件）", len(targets),
            extra={"event": "notify.started",
                   "ctx": {"targets": [redact_url(u) for u in targets],
                           "enabled": bool(self._settings.get("notify_enabled"))}},
        )

    async def stop(self) -> None:
        if self._task is None:
            return
        # 送信待ちを吐き切ってから止める。上限を切るのは、宛先が落ちているときに終了できなく
        # なるのを防ぐため。
        try:
            await asyncio.wait_for(self._queue.join(),
                                   timeout=get_notify_shutdown_drain_seconds())
        except asyncio.TimeoutError:
            logger.warning(
                "alertが %d 件queueに残ったままnotifierを停止しました", self._queue.qsize(),
                extra={"event": "notify.drain_timeout",
                       "ctx": {"pending": self._queue.qsize()}},
            )
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        # queueを引き取るworkerが居なくなったので、投入口も閉じる。開けたままにすると、
        # shutdown中に出るops_eventが誰も読まないqueueへ積まれ続ける。
        self._queue = None
        self._loop = None
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None
        logger.info(
            "notifierを停止しました（送信=%d 失敗=%d 破棄=%d）",
            self.sent, self.failed, self._dropped,
            extra={"event": "notify.stopped",
                   "ctx": {"sent": self.sent, "failed": self.failed,
                           "dropped": self._dropped}},
        )

    # ----- 投入 --------------------------------------------------------------------
    def submit(self, alert: Optional[Alert]) -> bool:
        """alertを送信queueへ積む。呼び出し元のthreadを問わず、blockも例外も無い。

        本体(収集・録画・DB書き込み)から呼ばれるので、ここで何が起きても呼び出し元へは
        返さない。積めなかったことは数え、ops_eventsへ1度だけ報告する。
        """
        if alert is None:
            return False
        try:
            if self._loop is None or self._queue is None:
                return False
            if not get_notify_webhook_urls():
                return False
            if self._queue.qsize() >= get_notify_queue_max():
                self._note_drop(alert)
                return False
            self._loop.call_soon_threadsafe(self._queue.put_nowait, alert)
            return True
        except RuntimeError:
            # event loopが既に閉じている(shutdown中)。通知は落ちるが本体は止めない。
            return False
        except Exception:
            logger.exception(
                "alertをqueueへ積めなかったため破棄します",
                extra={"event": "notify.enqueue_failed", "ctx": {"rule": alert.rule}},
            )
            return False

    def _note_drop(self, alert: Alert) -> None:
        self._dropped += 1
        if self._drop_reported:
            return
        self._drop_reported = True
        self._storage.record_ops_event(
            logger, "notify.queue_overflow",
            "通知queueが満杯です。捌けるまで通知は捨てられます",
            severity=OPS_ERROR,
            detail={"queue_max": get_notify_queue_max(), "rule": alert.rule},
        )

    def status(self) -> dict:
        """設定画面用。URLはredactして返す(画面に資格情報を出さない)。"""
        targets = get_notify_webhook_urls()
        return {
            "enabled": bool(self._settings.get("notify_enabled")),
            "running": self._task is not None,
            "targets": [{"url": redact_url(u), "format": resolve_format(u)}
                        for u in targets],
            "queued": self._queue.qsize() if self._queue is not None else 0,
            "sent": self.sent,
            "failed": self.failed,
            "dropped": self._dropped,
        }

    # ----- 送信 --------------------------------------------------------------------
    async def _worker(self) -> None:
        while True:
            alert = await self._queue.get()
            try:
                await self._deliver_all(alert)
            except asyncio.CancelledError:
                raise
            except Exception:
                # workerが例外で死ぬと以後の通知が全て無音になる。ここは必ず握って続行する
                # (握った事実はlogに残る)。
                logger.exception(
                    "alertの送信中に想定外の失敗が発生しました",
                    extra={"event": "notify.deliver_crashed",
                           "ctx": {"rule": alert.rule}},
                )
            finally:
                self._queue.task_done()

    async def _deliver_all(self, alert: Alert) -> None:
        for url in get_notify_webhook_urls():
            await self._deliver(alert, url)

    async def _deliver(self, alert: Alert, url: str) -> None:
        attempts = max(1, int(self._settings.get("notify_retry_max")) + 1)
        backoff = float(self._settings.get("notify_retry_base_delay"))
        fmt = resolve_format(url)
        payload = build_payload(alert, fmt)
        started = time.perf_counter()
        last_error = ""
        for attempt in range(1, attempts + 1):
            try:
                response = await self._client.post(url, json=payload)
                if response.status_code < 400:
                    self.sent += 1
                    logger.info(
                        "alertを送信しました（%s）: 宛先 %s, 試行 %d 回",
                        alert.rule, redact_url(url), attempt,
                        extra={"event": "notify.delivered",
                               "ctx": {"rule": alert.rule, "format": fmt,
                                       "status": response.status_code,
                                       "attempt": attempt,
                                       "target": redact_url(url)}},
                    )
                    return
                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                if 400 <= response.status_code < 500 and response.status_code != 429:
                    # 宛先URLが違う・payloadを受け付けない類。再試行しても同じ結果なので、
                    # 待ち時間を積まずに即座に諦めて報告する。
                    break
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            if attempt < attempts:
                await asyncio.sleep(backoff * (2 ** (attempt - 1)))
        self.failed += 1
        self._storage.record_ops_event(
            logger, "notify.delivery_failed",
            f"通知を{attempts}回試しましたが送信できませんでした: {last_error}",
            severity=OPS_ERROR,
            unique_id=alert.unique_id,
            duration_ms=round((time.perf_counter() - started) * 1000.0, 1),
            detail={"rule": alert.rule, "target": redact_url(url), "format": fmt,
                    "attempts": attempts, "error": last_error,
                    "alert_title": alert.title},
        )

    # ----- 事象ごとの入口 -----------------------------------------------------------
    def on_ops_event(self, kind: str, severity: str, message: str,
                     unique_id: Optional[str], detail: Optional[dict]) -> None:
        """``Storage.record_ops_event`` から呼ばれる観測点。任意のthreadから来る。

        ここで例外を出すとops_eventの記録側へ波及するので、判定ごと握る。
        """
        try:
            self.submit(self.rules.from_ops_event(kind, severity, message,
                                                  unique_id, detail))
        except Exception:
            logger.exception(
                "ops event %s に対するalert ruleの評価に失敗しました", kind,
                extra={"event": "notify.rule_failed", "ctx": {"kind": kind}},
            )

    def on_coin_rate(self, unique_id: str, coins_per_minute: float) -> None:
        try:
            self.submit(self.rules.from_coin_rate(unique_id, coins_per_minute))
        except Exception:
            logger.exception(
                "coin rateに対するalert ruleの評価に失敗しました",
                extra={"event": "notify.rule_failed", "ctx": {"unique_id": unique_id}},
            )

    def on_battle_started(self, unique_id: str, battle_id, opponents: int) -> None:
        try:
            self.submit(self.rules.from_battle_started(unique_id, battle_id, opponents))
        except Exception:
            logger.exception(
                "battleの開始に対するalert ruleの評価に失敗しました",
                extra={"event": "notify.rule_failed", "ctx": {"unique_id": unique_id}},
            )

    async def send_test(self) -> dict:
        """設定画面の「テスト送信」。queueを通さず同期的に送り、結果をそのまま返す。

        queue越しにすると「積めた」しか返せず、宛先が正しいかを確かめるという目的を果たせない。
        """
        targets = get_notify_webhook_urls()
        if not targets:
            raise ValueError(
                "通知の宛先が未設定です。TicTok/.env に TICTOK_NOTIFY_WEBHOOK_URL を設定して"
                "Serverを再起動してください。"
            )
        if self._client is None:
            raise RuntimeError("Notifierが開始されていません。")
        alert = Alert(
            rule="test", dedup_key="test", severity=OPS_INFO,
            title="TicTok 通知テスト",
            message="この通知が届いていれば、webhookの宛先設定は正しく機能しています。",
            detail={"sent_at": time.strftime("%Y-%m-%d %H:%M:%S")},
        )
        results = []
        for url in targets:
            fmt = resolve_format(url)
            entry = {"target": redact_url(url), "format": fmt}
            try:
                response = await self._client.post(url, json=build_payload(alert, fmt))
                entry["status"] = response.status_code
                entry["ok"] = response.status_code < 400
                if not entry["ok"]:
                    entry["error"] = response.text[:200]
            except httpx.HTTPError as exc:
                entry["ok"] = False
                entry["error"] = f"{type(exc).__name__}: {exc}"
            results.append(entry)
        self._storage.record_ops_event(
            logger, "notify.test_sent",
            "通知testを{n}件の宛先へ送信しました（成功 {ok}件）".format(
                n=len(results), ok=sum(1 for r in results if r["ok"])),
            severity=OPS_INFO if all(r["ok"] for r in results) else OPS_WARNING,
            detail={"results": results},
        )
        return {"results": results}
