"""接続のたびに届き直す「直近messageの遡り分」を落とす。

TikTokのlive websocketは、接続時の初回fetch応答(ProtoMessageFetchResult)にroomの
直近messageを載せて返す(同じ応答が history_comment_cursor / history_no_more を持つ)。
TikTokLiveの ``process_connect_events`` は既定で有効なので、その遡り分は普通のeventと
してlistenerへ届く。接続が起きるのは「配信の開始時」と「切断からの復帰時」なので、
同じcommentが接続回数だけ記録されていた。

実測(2026-08-28 時点のDB, comment 202,654件):
  重複 3,201件(1.6%)。gift 34,633件中 317件(0.92%)も同じ理由。
  1配信で同一commentが最大20行。**1回の接続につき2行**入る — 初回fetchのmessagesと、
  接続直後の最初のpush frameが同じcursorから送り直す分。
  遡り幅は p50 81秒 / p90 655秒 / p99 3,140秒 / 最大 5,171秒。遡りは件数で決まるため、
  静かなroomほど古いmessageまで届く。

落とす鍵は ``base_message.message_id`` だけを使う。TikTokがmessage 1件ごとに振る一意の
idで、遡り分は元と同じidで届く。**text+時刻の一致では判定しない** — 同じ人が同じ短文
("おは"等)を続けて送るのは普通に起きるので、それを重複と見なすと本物のcommentが消える。
"""

import logging
import time
from collections import OrderedDict
from typing import Any, Iterable, Optional

from TikTokLive import TikTokLiveClient

logger = logging.getLogger("tictok.collector")

# 記憶する message_id の件数の上限。**判定の条件ではなくmemoryの天井である。**
# 判定の窓は時間(window_seconds)で切っており、この上限に当たるのは窓の中に収まらない
# ほどmessageが多いroomだけである。実測のpeakは1 sessionあたり4,500 event/時で、
# 記録に残らないevent種(RoomUserSeq/LinkLayer/Unknown等)を含めても既定の2時間窓で
# 3万件前後にしかならない。上限に当たると窓が実質的に縮み、その分だけ遡りを落とし
# 損ねるため、当たったことは1度だけwarningで名乗る。
_MAX_ENTRIES = 60000


def message_id_of(event: Any) -> Optional[int]:
    """eventが載っていたmessageの一意id。持たないeventはNone。

    protobufの未設定intは0で届くので、0は「idが無い」として扱う(0を鍵にすると、
    idを持たないevent同士が互いの重複と判定される)。"""
    base = getattr(event, "base_message", None)
    if base is None:
        return None
    try:
        value = int(getattr(base, "message_id", 0) or 0)
    except (TypeError, ValueError):
        return None
    return value or None


def first_message_id(events: Optional[Iterable[Any]]) -> Optional[int]:
    """1つのmessageから展開されたevent群の中から、そのmessageのidを拾う。

    1つのmessageは最大3つのevent(WebsocketResponseEvent / proto event / custom event)へ
    展開されるが、どれも同じ base_message を持つので、最初に見つかった1つで足りる。"""
    for event in events or ():
        value = message_id_of(event)
        if value is not None:
            return value
    return None


class SeenMessages:
    """処理済み message_id の記憶。

    **配信者1人につき1つ持ち、sessionと再接続を跨いで生かす。** 再接続の遡りだけでなく、
    配信が切れて次のsessionが開いた直後の遡り(実測: session跨ぎの重複369件)も同じ記憶で
    落とす必要があるため、session開始で捨ててはならない。

    窓は時間で切る。件数で切ると、静かなroomでは数分ぶんしか覚えていないのに遡りは
    1時間前まで届く、という取りこぼしが起きる(遡りの件数は一定でも、それが何分ぶんかは
    roomの賑わいで変わる)。``_MAX_ENTRIES`` は判定の条件ではなくmemoryの天井である。

    再訪しても時刻は更新しない。窓は「最初に受け取ってから」で数える — 更新すると、
    接続のたびに届き直すmessageが永久に窓の中へ留まり続ける。
    """

    def __init__(self, window_seconds: float, max_entries: int = _MAX_ENTRIES) -> None:
        self.window_seconds = float(window_seconds)
        self._max_entries = int(max_entries)
        # 挿入順 = 初回受信の時刻順。再訪で更新しないのでこの順序は崩れず、期限切れの
        # 追い出しは先頭から見るだけで済む。
        self._seen: "OrderedDict[int, float]" = OrderedDict()
        self.dropped = 0
        self.capped = 0
        self._capped_logged = False

    def __len__(self) -> int:
        return len(self._seen)

    def add_if_new(self, message_id: int, now: Optional[float] = None) -> bool:
        """初めて見る message_id ならTrueを返して覚える。既出ならFalse。

        時刻は monotonic を使う。system clockが巻き戻ると窓の幅が狂い、遡りを落とし
        損ねる(あるいは覚えたばかりのidを即座に捨てる)。"""
        moment = time.monotonic() if now is None else now
        self._expire(moment)
        if message_id in self._seen:
            self.dropped += 1
            return False
        self._seen[message_id] = moment
        self._enforce_cap()
        return True

    def _expire(self, now: float) -> None:
        cutoff = now - self.window_seconds
        seen = self._seen
        while seen:
            oldest_id, seen_at = next(iter(seen.items()))
            if seen_at > cutoff:
                break
            del seen[oldest_id]

    def _enforce_cap(self) -> None:
        if len(self._seen) <= self._max_entries:
            return
        while len(self._seen) > self._max_entries:
            self._seen.popitem(last=False)
            self.capped += 1
        if not self._capped_logged:
            self._capped_logged = True
            # 窓が実質的に縮んだ = この先の遡りを落とし損ねる可能性がある、という劣化の
            # 名乗り。件数を増やすかwindowを縮めるかは運用の判断なので、値は決め打たない。
            logger.warning(
                "重複除去の記憶が上限 %d 件に達しました。設定した窓(%.0f秒)より短い範囲しか"
                "覚えられないため、接続時の遡りを落とし損ねることがあります",
                self._max_entries, self.window_seconds,
                extra={"event": "collector.dedup_cache_capped",
                       "ctx": {"max_entries": self._max_entries,
                               "window_seconds": self.window_seconds}},
            )


class DedupTikTokLiveClient(TikTokLiveClient):
    """既出 message_id のmessageを、eventへ展開した直後に丸ごと落とすclient。

    落とす位置が ``_parse_webcast_response_message`` なのは、ここが「message 1件 ->
    event 0〜3個」の唯一の分岐点だからである。``emit`` 側で1 eventずつ落とすと、同じ
    messageから生まれる custom event(FollowEvent/ShareEvent/SuperFanEvent)とproto event
    が同じ message_id を共有しているため、最初の1つを通した時点で残りが道連れになる。

    判定を親の展開の**後**に置いているのは、鍵にできるidが ``base_message.message_id``
    しかないためである(展開前のwrapperにも msg_id はあるが、実際に埋まっているかを
    確かめられていない。埋まったり埋まらなかったりする鍵を混ぜると、同じmessageが接続の
    たびに別の鍵で覚えられ、重複が素通りする)。展開の費用は遡りの数百件ぶんだけで、
    hot pathの費用は変わらない。
    """

    def __init__(self, *args, seen: SeenMessages, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._seen_messages = seen

    async def _parse_webcast_response_message(self, webcast_response_message):
        events = await super()._parse_webcast_response_message(webcast_response_message)
        message_id = first_message_id(events)
        if message_id is None:
            # idを持たないmessage(接続の合図など)は判定材料が無いのでそのまま通す。
            return events
        if self._seen_messages.add_if_new(message_id):
            return events
        return []
