"""通知(alert)の判定層。

無人運転が前提の監視toolでありながら、これまで外部への通知経路が1本も無く、届くのは画面を
開いている間のWebSocket broadcastだけだった。「配信の切断に翌日まで気付かない」を構造的に
防ぐのがこの層の目的である。

判定material(何が起きたか)は既に揃っているので、この層は新しい観測を足さない:

* 障害系・session lifecycle は ``ops_events`` が既に単一の口になっている。severity付きで
  collector・recorder・serverの状態遷移が全てここを通るため、通知はops_eventsの観測者として
  ぶら下がるだけでよい(切断・録画停止・再接続の打ち切り・LIVE開始が追加の計装なしで揃う)。
* coin rate と Battle開始 だけはops_eventsに乗らないので、collector側から明示的に渡す。

``core.spike`` の z-score 判定はここでは使わない。spike.pyが冒頭で明記しているとおり、あれは
母集団をsession内に閉じることで「配信ごとに規模が桁で違う」問題を回避する事後解析用の判定で
あり、配信開始直後(母集団がMIN_BUCKETS未満)には値を出せない。通知は配信の頭から効いている
必要があるので、絶対値の閾値(coin/分)で判定し、spike.pyの設計意図には触れない。

この層はI/Oを持たない。送信は core.notify、判定はここ、という分割にしてあるので、閾値と
不応期(refractory)の挙動はserverもwebhookも起こさずにtestできる。
"""

import time
from dataclasses import dataclass, field
from typing import Optional

from tictok.storage import OPS_ERROR, OPS_INFO, OPS_WARNING

# ops_eventsのkindのうち、severityではなく「その事象そのもの」を通知条件にするもの。
# server.pyが OPS_SETTINGS_KIND を定数で持っているのと同じ扱いで、kind文字列はmodule間の
# 契約なので定数に名前を付けて1箇所に置く。
OPS_KIND_LIVE_STARTED = "session.started"
# 通知機構自身が出すops_eventのkind接頭辞。この接頭辞のeventを通知対象にすると、送信失敗の
# 記録が次の通知を生み、それがまた失敗する無限循環になる。観測側で必ず落とすこと。
OPS_KIND_PREFIX_NOTIFY = "notify."

# 設定画面の notify_ops_min_severity が取る値。数値が大きいほど広く拾う。
SEVERITY_RANK = {OPS_ERROR: 0, OPS_WARNING: 1, OPS_INFO: 2}

# alertの重要度。webhook側の見た目(色・接頭辞)にしか使わないので、ops_eventsのseverityを
# そのまま流用する。
ALERT_SEVERITIES = (OPS_ERROR, OPS_WARNING, OPS_INFO)


@dataclass
class Alert:
    """1件の通知。

    ``dedup_key`` は不応期の単位である。同じ事象の繰り返しを1件に畳むためのkeyなので、
    「同じと見なしたい範囲」で組む(例: 配信者×rule)。
    """

    rule: str
    dedup_key: str
    severity: str
    title: str
    message: str
    unique_id: Optional[str] = None
    detail: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def as_dict(self) -> dict:
        return {
            "rule": self.rule,
            "dedup_key": self.dedup_key,
            "severity": self.severity,
            "title": self.title,
            "message": self.message,
            "unique_id": self.unique_id,
            "detail": dict(self.detail),
            "ts": self.ts,
        }


class AlertGate:
    """重複抑止。不応期(refractory)と、状態変化での立ち上がり検出の2つを持つ。

    2つとも要るのは、抑止したい重複が2種類あるからである。ops_events由来のalertは同じ障害が
    短時間に何度も記録される(再接続を繰り返す等)ので時間窓で畳む。coin rateのような閾値判定
    は、閾値の上に居る限り毎回条件を満たし続けるので、時間窓だけでは不応期が明けるたびに
    鳴り続ける。後者は「下→上」に変わった瞬間だけ発火させる必要がある。
    """

    def __init__(self) -> None:
        self._last_fired: dict = {}
        self._levels: dict = {}

    def allow(self, dedup_key: str, refractory_seconds: float,
              now: Optional[float] = None) -> bool:
        """不応期を過ぎていれば発火を許可し、発火時刻を記録する。"""
        now = time.time() if now is None else now
        last = self._last_fired.get(dedup_key)
        if last is not None and refractory_seconds > 0 and now - last < refractory_seconds:
            return False
        self._last_fired[dedup_key] = now
        return True

    def crossed_up(self, dedup_key: str, above: bool) -> bool:
        """閾値の「下→上」への変化だけTrueを返す。上に居続ける間はFalseのまま。

        初回観測が既にaboveなら発火する(serverを再起動した瞬間に既に盛り上がっている配信を
        黙って見送らないため)。
        """
        previous = self._levels.get(dedup_key)
        self._levels[dedup_key] = above
        return above and previous is not True

    def forget(self, dedup_key_prefix: str) -> None:
        """session終了などで状態を落とす。次のsessionの1件目を不応期で消さないため。"""
        for store in (self._last_fired, self._levels):
            for key in [k for k in store if k.startswith(dedup_key_prefix)]:
                del store[key]


class AlertRules:
    """設定値を読んで、事象をalertへ変換する。

    設定は ``settings.get(key)`` 越しにその都度読む。保持すると設定画面での変更が次のserver
    再起動まで効かなくなる。
    """

    def __init__(self, settings, gate: Optional[AlertGate] = None) -> None:
        self._settings = settings
        self.gate = gate if gate is not None else AlertGate()

    def _enabled(self, key: str) -> bool:
        return bool(self._settings.get("notify_enabled")) and bool(self._settings.get(key))

    def _refractory(self) -> float:
        return float(self._settings.get("notify_refractory_seconds"))

    def from_ops_event(self, kind: str, severity: str, message: str,
                       unique_id: Optional[str], detail: Optional[dict],
                       now: Optional[float] = None) -> Optional[Alert]:
        """ops_eventを1件受けてalertを組む。対象外・抑止中はNone。"""
        if kind.startswith(OPS_KIND_PREFIX_NOTIFY):
            return None
        if not bool(self._settings.get("notify_enabled")):
            return None
        target = unique_id or "-"
        if kind == OPS_KIND_LIVE_STARTED:
            if not self._enabled("notify_rule_live_started"):
                return None
            alert = Alert(
                rule="live_started",
                dedup_key=f"live_started:{target}",
                severity=OPS_INFO,
                title=f"LIVE開始: {target}",
                message=message,
                unique_id=unique_id,
                detail=dict(detail or {}),
            )
        else:
            if not self._enabled("notify_rule_ops"):
                return None
            rank = SEVERITY_RANK.get(severity)
            if rank is None or rank > int(self._settings.get("notify_ops_min_severity")):
                return None
            alert = Alert(
                rule="ops_event",
                # kind単位で畳む。severityで畳むと、再接続の打ち切りと録画停止が同じ枠を
                # 奪い合って片方が消える。
                dedup_key=f"ops:{kind}:{target}",
                severity=severity,
                title=f"{kind} ({target})" if unique_id else kind,
                message=message,
                unique_id=unique_id,
                detail={"kind": kind, **(detail or {})},
            )
        if not self.gate.allow(alert.dedup_key, self._refractory(), now=now):
            return None
        return alert

    def from_coin_rate(self, unique_id: str, coins_per_minute: float,
                       now: Optional[float] = None) -> Optional[Alert]:
        """直近1分のcoin(diamond)量が閾値を超えた瞬間に1件。

        閾値の上に居続ける間は鳴らさない(crossed_up)。不応期は「下がってすぐ上がる」揺れを
        畳むために重ねて掛ける。
        """
        if not self._enabled("notify_rule_coin_rate"):
            return None
        threshold = float(self._settings.get("notify_coin_rate_threshold"))
        if threshold <= 0:
            return None
        dedup_key = f"coin_rate:{unique_id}"
        if not self.gate.crossed_up(dedup_key, coins_per_minute >= threshold):
            return None
        if not self.gate.allow(dedup_key, self._refractory(), now=now):
            return None
        return Alert(
            rule="coin_rate",
            dedup_key=dedup_key,
            severity=OPS_WARNING,
            title=f"coin急増: {unique_id}",
            message=f"直近1分のcoinが {int(coins_per_minute)} で閾値 {int(threshold)} を超えました。",
            unique_id=unique_id,
            detail={"coins_per_minute": coins_per_minute, "threshold": threshold},
        )

    def from_battle_started(self, unique_id: str, battle_id, opponents: int,
                            now: Optional[float] = None) -> Optional[Alert]:
        """Battle開始。battle_idごとに1件で、同一Battleの続報(action更新)では鳴らさない。"""
        if not self._enabled("notify_rule_battle_started"):
            return None
        alert = Alert(
            rule="battle_started",
            dedup_key=f"battle:{unique_id}:{battle_id}",
            severity=OPS_INFO,
            title=f"Battle開始: {unique_id}",
            message=f"Battle #{battle_id} が始まりました(対戦相手 {opponents} 人)。",
            unique_id=unique_id,
            detail={"battle_id": battle_id, "opponents": opponents},
        )
        # 同一battle_idは不応期に関係なく1回だけにしたいので、不応期を極大にはせず
        # crossed_upで「未発火→発火」の1回に閉じる。
        if not self.gate.crossed_up(alert.dedup_key, True):
            return None
        return alert
