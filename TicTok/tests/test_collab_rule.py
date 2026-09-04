"""コラボ(非BattleのLinkMic)接続判定 v3 のrule test。

形はsamples/LinkLayerEvent.jsonlで実際に観測したpayloadに合わせてある:
group_change_content.group_user.user[] が参加room単位のsnapshotで、各entryが
channel_id / status / all_user.linked_list[].link_user.{uid, room_id} を持つ。
"""
from types import SimpleNamespace as NS

from tictok.core.collab import linkmic_state

OWN_UID = "7300000000000000101"
OWN_ROOM = "7300000000000000202"


def _member(uid, room):
    return NS(link_user=NS(uid=uid, room_id=room))


def _entry(channel_id, status, members):
    return NS(
        channel_id=channel_id,
        status=status,
        all_user=NS(linked_list=[_member(uid, room) for uid, room in members]),
    )


def _event(entries=None, **kwargs):
    """未設定fieldはNone。betterprotoの空messageはgetattrで潰れるので、testでは
    「そのfieldが無い」= None で表す。"""
    fields = {
        "group_change_content": None,
        "list_content": None,
        "join_direct_content": None,
        "finish_content": None,
        "leave_content": None,
        "kick_out_content": None,
        "leave_group_content": None,
    }
    fields.update(kwargs)
    if entries is not None:
        fields["group_change_content"] = NS(group_user=NS(user=entries))
    return NS(**fields)


def _state(event):
    return linkmic_state(event, OWN_UID, OWN_ROOM)


def test_own_linked_with_a_linked_peer_is_connected():
    """実観測のsnapshot(自室LINKED + 他室LINKED)。これが「繋がっている」の基本形。"""
    event = _event([
        _entry("7300000000000000201", "GROUP_STATUS_LINKED", [("7300000000000000103", "7300000000000000201")]),
        _entry(OWN_ROOM, "GROUP_STATUS_LINKED", [(OWN_UID, OWN_ROOM)]),
    ])
    out = _state(event)
    assert out["connected"] is True
    assert out["peers"] == ["7300000000000000103"]


def test_peer_room_id_is_carried_out_for_identity_resolution():
    """相手のroom_idを返すこと。表示名はLinkLayerに載らず、この室を引くのが唯一の
    解決経路なので、ここで落とすと画面は数値IDしか出せない。"""
    event = _event([
        _entry("7300000000000000201", "GROUP_STATUS_LINKED", [("p1", "7300000000000000201")]),
        _entry("a2", "GROUP_STATUS_LINKED", [("p2", "")]),
        _entry(OWN_ROOM, "GROUP_STATUS_LINKED", [(OWN_UID, OWN_ROOM)]),
    ])
    out = _state(event)
    # 室を名乗らない相手はkeyごと出さない(空文字を室として引きに行かせない)。
    assert out["peer_rooms"] == {"p1": "7300000000000000201"}


def test_peer_rooms_come_from_the_link_list_route_too():
    event = _event(list_content=NS(user_list=NS(linked_list=[_member("p1", "r1")])))
    assert _state(event)["peer_rooms"] == {"p1": "r1"}


def test_own_waiting_is_not_connected_even_with_linked_peers():
    """実観測にある「自室WAITING + 他室3つLINKED」。招待/参加待ちで、まだ一緒には映って
    いない。ここをTrueにすると、繋がる前の時間までコラボに入る。"""
    event = _event([
        _entry("a1", "GROUP_STATUS_LINKED", [("p1", "a1")]),
        _entry("a2", "GROUP_STATUS_LINKED", [("p2", "a2")]),
        _entry(OWN_ROOM, "GROUP_STATUS_WAITING", [(OWN_UID, OWN_ROOM)]),
    ])
    assert _state(event)["connected"] is False


def test_only_self_left_in_the_roster_is_disconnected():
    """相手が抜けてsnapshotが自室だけになった状態。**v1はこれを検出できず**、窓が
    finishまで開きっぱなしだった(録画照合で窓の中の大半がソロ)。"""
    event = _event([_entry(OWN_ROOM, "GROUP_STATUS_LINKED", [(OWN_UID, OWN_ROOM)])])
    out = _state(event)
    assert out["connected"] is False
    assert out["peers"] == []


def test_snapshot_without_self_does_not_decide():
    """自室が載っていないsnapshotはこちらの状態を語っていない。切断と読むと、無関係な
    groupのeventで窓が閉じる。"""
    event = _event([_entry("x1", "GROUP_STATUS_LINKED", [("p1", "x1")])])
    out = _state(event)
    assert out["connected"] is None
    assert out["source"] == "group_change_content:no_self"


def test_peer_that_is_only_waiting_does_not_count():
    event = _event([
        _entry(OWN_ROOM, "GROUP_STATUS_LINKED", [(OWN_UID, OWN_ROOM)]),
        _entry("a1", "GROUP_STATUS_WAITING", [("p1", "a1")]),
    ])
    assert _state(event)["connected"] is False


def test_own_entry_is_matched_by_uid_when_channel_id_differs():
    """自室entryのchannel_idがroom_idと一致しない送られ方でも、memberのuid/room_idで
    自分と判る。ここを取り違えると自分を相手に数えて常時「繋がっている」になる。"""
    event = _event([
        _entry("group-channel", "GROUP_STATUS_LINKED", [(OWN_UID, OWN_ROOM)]),
        _entry("a1", "GROUP_STATUS_LINKED", [("p1", "a1")]),
    ])
    out = _state(event)
    assert out["connected"] is True
    assert out["peers"] == ["p1"]


def test_link_list_with_peers_connects_and_empty_list_disconnects():
    """group構造を持たない経路(list_content)。**空のlinked_listは切断**で、v1のように
    窓を開いてはいけない。"""
    peers = _event(list_content=NS(user_list=NS(linked_list=[_member("p1", "r1")])))
    assert _state(peers)["connected"] is True
    empty = _event(list_content=NS(user_list=NS(linked_list=[])))
    out = _state(empty)
    assert out["connected"] is False
    assert out["source"] == "list_content"


def test_own_disconnect_closes_the_window():
    """自分が名指しされた切断。uidでもroomでも同じに読む。"""
    for name in ("finish_content", "leave_content", "kick_out_content", "leave_group_content"):
        for party in (NS(uid=OWN_UID, room_id=0), NS(uid=0, room_id=OWN_ROOM)):
            out = _state(_event(**{name: NS(owner=party)}))
            assert out["connected"] is False, (name, party)
            assert out["source"] == name


def test_disconnect_without_a_named_party_closes_the_window():
    """当事者を名乗らない切断。1:1経路ではこれが唯一の終了通知になるので閉じる。"""
    out = _state(_event(finish_content=NS(finish_reason=10004)))
    assert out["connected"] is False
    assert out["source"] == "finish_content"


def test_a_peers_departure_does_not_close_a_window_that_still_has_peers():
    """v2の取りこぼしの最大成分。groupコラボで他人が抜けただけで窓を閉じていた。

    finish_contentが名乗るのは「終了したroom」で、他の参加者のroomが入る。残りの相手が
    居る限り、こちらはまだ繋がっている。"""
    event = _event(finish_content=NS(owner=NS(uid="p1", room_id="r1")))
    out = linkmic_state(event, OWN_UID, OWN_ROOM, {"p1": "r1", "p2": "r2"})
    assert out["connected"] is True
    assert out["peers"] == ["p2"]
    assert out["source"] == "finish_content:peer"


def test_the_last_peers_departure_closes_the_window():
    """1:1で相手が抜けたときは従来どおり閉じる。"""
    event = _event(finish_content=NS(owner=NS(uid="p1", room_id="r1")))
    out = linkmic_state(event, OWN_UID, OWN_ROOM, {"p1": "r1"})
    assert out["connected"] is False
    assert out["peers"] == []


def test_a_peers_departure_with_unknown_roster_does_not_decide():
    """誰と繋がっているか判らないまま他人の離脱を受けても、状態を変えない。"""
    event = _event(finish_content=NS(owner=NS(uid="p1", room_id="r1")))
    out = linkmic_state(event, OWN_UID, OWN_ROOM, {})
    assert out["connected"] is None
    assert out["source"] == "finish_content:peer_unknown"


def test_a_peer_named_only_by_room_is_matched_by_room():
    """相手がroom_idしか名乗らない形。uidで突き合わせられないので roomで外す。"""
    event = _event(leave_content=NS(user=NS(uid=0, room_id="r1")))
    out = linkmic_state(event, OWN_UID, OWN_ROOM, {"p1": "r1", "p2": "r2"})
    assert out["connected"] is True
    assert out["peers"] == ["p2"]


def test_event_without_any_membership_signal_does_not_decide():
    """create通知だけ等、状態を語らないevent。ここでNoneを返さないと、無関係なeventの
    たびに窓が開閉する。"""
    assert _state(_event())["connected"] is None
