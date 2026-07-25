"""通知(alert)基盤のtest: 判定・重複抑止・payload整形・送信失敗の扱い。"""

import asyncio

import httpx
import pytest

from tictok.core import notify
from tictok.core.alert import Alert, AlertGate, AlertRules, OPS_KIND_LIVE_STARTED
from tictok.core.settings import SETTING_DEFS
from tictok.storage import OPS_ERROR, OPS_INFO, OPS_WARNING


class FakeSettings:
    """SETTING_DEFSの既定値から出発し、testが必要な分だけ差し替える。"""

    def __init__(self, **overrides) -> None:
        self._values = {k: d["default"] for k, d in SETTING_DEFS.items()}
        self._values.update(overrides)

    def get(self, key):
        return self._values[key]

    def set(self, key, value):
        self._values[key] = value


@pytest.fixture
def rules():
    return AlertRules(FakeSettings(notify_enabled=1))


# ---- 判定 -------------------------------------------------------------------------


def test_disabled_produces_no_alert():
    rules = AlertRules(FakeSettings(notify_enabled=0))
    assert rules.from_ops_event("collector.disconnected", OPS_ERROR, "x", "u1", None) is None
    assert rules.from_coin_rate("u1", 999999) is None
    assert rules.from_battle_started("u1", 1, 1) is None


def test_live_started_fires_on_session_started(rules):
    alert = rules.from_ops_event(OPS_KIND_LIVE_STARTED, OPS_INFO, "session started", "u1", {})
    assert alert is not None
    assert alert.rule == "live_started"
    assert "u1" in alert.title


def test_ops_severity_gate_respects_min_severity():
    settings = FakeSettings(notify_enabled=1, notify_ops_min_severity=1)
    rules = AlertRules(settings)
    assert rules.from_ops_event("collector.stream_lost", OPS_ERROR, "m", "u1", None) is not None
    assert rules.from_ops_event("session.restricted", OPS_WARNING, "m", "u2", None) is not None
    # info は warning以上の設定では拾わない(job開始完了まで通知が飛ぶのを防ぐ)。
    assert rules.from_ops_event("media_queue.job_started", OPS_INFO, "m", "u3", None) is None


def test_notify_own_ops_events_never_loop(rules):
    """送信失敗の記録が次の通知を生むと、失敗するたびに無限に増える。"""
    assert rules.from_ops_event("notify.delivery_failed", OPS_ERROR, "m", "u1", None) is None
    assert rules.from_ops_event("notify.queue_overflow", OPS_ERROR, "m", None, None) is None


# ---- 重複抑止 ---------------------------------------------------------------------


def test_refractory_suppresses_repeat_of_same_event(rules):
    first = rules.from_ops_event("collector.disconnected", OPS_ERROR, "m", "u1", None, now=1000.0)
    assert first is not None
    assert rules.from_ops_event("collector.disconnected", OPS_ERROR, "m", "u1", None, now=1100.0) is None
    # 既定の不応期(300秒)を越えれば再び通る。
    assert rules.from_ops_event("collector.disconnected", OPS_ERROR, "m", "u1", None, now=1400.0) is not None


def test_refractory_is_per_kind_and_per_target(rules):
    assert rules.from_ops_event("collector.disconnected", OPS_ERROR, "m", "u1", None, now=1000.0)
    # 別の配信者・別のkindは互いの枠を奪わない。
    assert rules.from_ops_event("collector.disconnected", OPS_ERROR, "m", "u2", None, now=1000.0)
    assert rules.from_ops_event("collector.stream_lost", OPS_ERROR, "m", "u1", None, now=1000.0)


def test_coin_rate_fires_once_per_crossing():
    settings = FakeSettings(notify_enabled=1, notify_rule_coin_rate=1,
                            notify_coin_rate_threshold=1000, notify_refractory_seconds=0)
    rules = AlertRules(settings)
    assert rules.from_coin_rate("u1", 500) is None
    first = rules.from_coin_rate("u1", 1500)
    assert first is not None and first.rule == "coin_rate"
    # 閾値の上に居続ける間は鳴らない。不応期だけでは、明けるたびに鳴り続けてしまう。
    assert rules.from_coin_rate("u1", 2000) is None
    assert rules.from_coin_rate("u1", 5000) is None
    # 一度下回ってから再び超えたら次の通知が出る。
    assert rules.from_coin_rate("u1", 100) is None
    assert rules.from_coin_rate("u1", 1200) is not None


def test_coin_rate_threshold_zero_disables():
    settings = FakeSettings(notify_enabled=1, notify_rule_coin_rate=1,
                            notify_coin_rate_threshold=0)
    assert AlertRules(settings).from_coin_rate("u1", 10**9) is None


def test_battle_alert_is_one_per_battle():
    settings = FakeSettings(notify_enabled=1, notify_rule_battle_started=1)
    rules = AlertRules(settings)
    assert rules.from_battle_started("u1", 77, 1) is not None
    # 同一Battleのaction更新でも_on_battleは毎回ここへ来るので、2件目は出してはならない。
    assert rules.from_battle_started("u1", 77, 2) is None
    assert rules.from_battle_started("u1", 78, 1) is not None


def test_gate_forget_clears_state():
    gate = AlertGate()
    assert gate.allow("coin_rate:u1", 300.0, now=1000.0)
    assert not gate.allow("coin_rate:u1", 300.0, now=1010.0)
    gate.forget("coin_rate:u1")
    assert gate.allow("coin_rate:u1", 300.0, now=1010.0)


# ---- payload整形 ------------------------------------------------------------------


def _alert():
    return Alert(rule="live_started", dedup_key="k", severity=OPS_INFO,
                 title="LIVE開始: u1", message="配信が始まりました。",
                 unique_id="u1", detail={"room_id": 42}, ts=1700000000.0)


def test_resolve_format_by_host(monkeypatch):
    monkeypatch.setenv("TICTOK_NOTIFY_WEBHOOK_FORMAT", "auto")
    assert notify.resolve_format("https://discord.com/api/webhooks/1/abc") == notify.FORMAT_DISCORD
    assert notify.resolve_format("https://hooks.slack.com/services/T/B/x") == notify.FORMAT_SLACK
    assert notify.resolve_format("http://127.0.0.1:9/hook") == notify.FORMAT_GENERIC


def test_resolve_format_explicit_overrides_host(monkeypatch):
    monkeypatch.setenv("TICTOK_NOTIFY_WEBHOOK_FORMAT", "slack")
    assert notify.resolve_format("https://discord.com/api/webhooks/1/abc") == notify.FORMAT_SLACK


def test_resolve_format_rejects_unknown_value(monkeypatch):
    monkeypatch.setenv("TICTOK_NOTIFY_WEBHOOK_FORMAT", "teams")
    with pytest.raises(ValueError):
        notify.resolve_format("https://example.test/hook")


def test_payloads_carry_the_message():
    alert = _alert()
    discord = notify.build_payload(alert, notify.FORMAT_DISCORD)
    assert discord["embeds"][0]["title"] == "LIVE開始: u1"
    assert discord["embeds"][0]["description"] == "配信が始まりました。"
    slack = notify.build_payload(alert, notify.FORMAT_SLACK)
    assert "LIVE開始: u1" in slack["text"] and "配信が始まりました。" in slack["text"]
    generic = notify.build_payload(alert, notify.FORMAT_GENERIC)
    assert generic["alert"]["rule"] == "live_started"
    assert generic["alert"]["detail"] == {"room_id": 42}


def test_redact_url_hides_the_token():
    url = "https://discord.com/api/webhooks/123456789/SECRET-TOKEN-VALUE"
    redacted = notify.redact_url(url)
    assert "SECRET-TOKEN-VALUE" not in redacted
    assert "discord.com" in redacted


# ---- 送信 -------------------------------------------------------------------------


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _run_notifier(storage, settings, handler, feed):
    notifier = notify.Notifier(storage, settings, client=_client(handler))
    notifier.start()
    try:
        feed(notifier)
        await asyncio.wait_for(notifier._queue.join(), timeout=5)
    finally:
        await notifier.stop()
    return notifier


def test_delivery_succeeds_and_is_counted(tmp_db, monkeypatch):
    monkeypatch.setenv("TICTOK_NOTIFY_WEBHOOK_URL", "http://127.0.0.1:9/hook")
    received = []

    def handler(request):
        received.append((str(request.url), request.read()))
        return httpx.Response(204)

    settings = FakeSettings(notify_enabled=1)
    notifier = asyncio.run(_run_notifier(
        tmp_db, settings, handler,
        lambda n: n.on_ops_event(OPS_KIND_LIVE_STARTED, OPS_INFO, "started", "u1", {}),
    ))
    assert notifier.sent == 1
    assert notifier.failed == 0
    assert len(received) == 1
    assert b"u1" in received[0][1]


def test_delivery_goes_to_every_configured_target(tmp_db, monkeypatch):
    monkeypatch.setenv(
        "TICTOK_NOTIFY_WEBHOOK_URL",
        "http://127.0.0.1:9/a, http://127.0.0.1:9/b",
    )
    hits = []

    def handler(request):
        hits.append(request.url.path)
        return httpx.Response(200)

    notifier = asyncio.run(_run_notifier(
        tmp_db, FakeSettings(notify_enabled=1), handler,
        lambda n: n.on_ops_event(OPS_KIND_LIVE_STARTED, OPS_INFO, "started", "u1", {}),
    ))
    assert sorted(hits) == ["/a", "/b"]
    assert notifier.sent == 2


def test_permanent_failure_is_recorded_as_an_ops_event(tmp_db, db_read, monkeypatch):
    """握り潰さない。届かなかったことは運用logにerrorとして必ず残る。"""
    monkeypatch.setenv("TICTOK_NOTIFY_WEBHOOK_URL", "http://127.0.0.1:9/hook")
    attempts = []

    def handler(request):
        attempts.append(1)
        return httpx.Response(404, text="no such webhook")

    settings = FakeSettings(notify_enabled=1, notify_retry_max=3, notify_retry_base_delay=0.5)
    notifier = asyncio.run(_run_notifier(
        tmp_db, settings, handler,
        lambda n: n.on_ops_event(OPS_KIND_LIVE_STARTED, OPS_INFO, "started", "u1", {}),
    ))
    # 4xx(429以外)は再試行しても結果が変わらないので、待たずに1回で打ち切る。
    assert len(attempts) == 1
    assert notifier.failed == 1
    tmp_db.flush()
    rows = db_read.execute(
        "SELECT kind, severity FROM ops_events WHERE kind = 'notify.delivery_failed'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["severity"] == OPS_ERROR


def test_transient_failure_is_retried_up_to_the_configured_cap(tmp_db, monkeypatch):
    monkeypatch.setenv("TICTOK_NOTIFY_WEBHOOK_URL", "http://127.0.0.1:9/hook")
    attempts = []

    def handler(request):
        attempts.append(1)
        if len(attempts) < 3:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200)

    settings = FakeSettings(notify_enabled=1, notify_retry_max=3, notify_retry_base_delay=0.5)
    notifier = asyncio.run(_run_notifier(
        tmp_db, settings, handler,
        lambda n: n.on_ops_event(OPS_KIND_LIVE_STARTED, OPS_INFO, "started", "u1", {}),
    ))
    assert len(attempts) == 3
    assert notifier.sent == 1
    assert notifier.failed == 0


def test_submit_never_raises_when_the_notifier_is_not_running(tmp_db, monkeypatch):
    """通知の失敗が本体の収集・録画を止めないこと。"""
    monkeypatch.setenv("TICTOK_NOTIFY_WEBHOOK_URL", "http://127.0.0.1:9/hook")
    notifier = notify.Notifier(tmp_db, FakeSettings(notify_enabled=1))
    # start()していない(= loopもqueueも無い)状態でも、呼び出し元へ例外を返さない。
    notifier.on_ops_event("collector.stream_lost", OPS_ERROR, "m", "u1", None)
    notifier.on_coin_rate("u1", 10**9)
    notifier.on_battle_started("u1", 1, 1)


def test_no_targets_means_nothing_is_sent(tmp_db, monkeypatch):
    monkeypatch.setenv("TICTOK_NOTIFY_WEBHOOK_URL", "")
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200)

    notifier = asyncio.run(_run_notifier(
        tmp_db, FakeSettings(notify_enabled=1), handler,
        lambda n: n.on_ops_event(OPS_KIND_LIVE_STARTED, OPS_INFO, "started", "u1", {}),
    ))
    assert calls == []
    assert notifier.sent == 0


def test_ops_observer_wires_storage_to_the_notifier(tmp_db, monkeypatch):
    """storage側の観測点が繋がっていること(繋がっていなければ何も通知されない)。"""
    monkeypatch.setenv("TICTOK_NOTIFY_WEBHOOK_URL", "http://127.0.0.1:9/hook")
    import logging

    received = []

    def handler(request):
        received.append(request.read())
        return httpx.Response(200)

    async def run():
        notifier = notify.Notifier(tmp_db, FakeSettings(notify_enabled=1),
                                   client=_client(handler))
        notifier.start()
        tmp_db.set_ops_observer(notifier.on_ops_event)
        try:
            tmp_db.record_ops_event(
                logging.getLogger("tictok.test"), "collector.stream_lost",
                "stream lost", severity=OPS_ERROR, unique_id="u1",
            )
            await asyncio.wait_for(notifier._queue.join(), timeout=5)
        finally:
            tmp_db.set_ops_observer(None)
            await notifier.stop()
        return notifier

    notifier = asyncio.run(run())
    assert notifier.sent == 1
    assert b"collector.stream_lost" in received[0]


def test_observer_failure_does_not_break_ops_event_recording(tmp_db, db_read):
    """観測者が壊れても、運用logへの記録という本来の役目は止まらない。"""
    import logging

    def broken(*args, **kwargs):
        raise RuntimeError("observer is broken")

    tmp_db.set_ops_observer(broken)
    try:
        tmp_db.record_ops_event(
            logging.getLogger("tictok.test"), "collector.stream_lost", "stream lost",
            severity=OPS_ERROR, unique_id="u1",
        )
    finally:
        tmp_db.set_ops_observer(None)
    tmp_db.flush()
    rows = db_read.execute(
        "SELECT kind FROM ops_events WHERE kind = 'collector.stream_lost'"
    ).fetchall()
    assert len(rows) == 1
