"""コラボ(非BattleのLinkMic)で「今この配信者が誰かと繋がっているか」の判定。

collector(収集時)がこのruleで窓を開閉する。窓は分析画面の「共演構成」の分子になる。

**なぜ判定を作り直したか(v1の失敗)**:
v1は create/finish の2 eventだけで窓を開閉していた。ところが実配信で届くLinkLayerEventを
数えると、40 shape中 create 4 / finish 6 に対し group_change_content 29 で、接続状態の主信号は
group_change_content の方だった。結果、窓は「最初に繋いだ時刻」から「channelが終了した時刻」まで
伸び、その間のソロ時間を全部コラボに数えていた。録画映像で照合すると、窓の中で実際に分割画面
だったのは 20点中3点 / 19点中7点しかない。さらに `roster is not None` が空集合でもTrueだったため、
「誰も居ない」eventでも窓が開いていた。

**v2のrule**: 接続状態は roster(誰がLINKEDか)で決める。
  - group_change_content は参加room単位のsnapshotで、各entryが channel_id(=そのroomのid)、
    status(LINKED/WAITING)、all_user.linked_list[].link_user.{uid, room_id} を持つ。
    自室のentryも含まれる(実dataで確認済み)。
  - **自室がLINKED かつ 他室にLINKEDが1つ以上** のときだけ「繋がっている」とみなす。
    自室がWAITINGの間は招待/参加待ちで、まだ画面に一緒には映っていない(実dataに
    「自室WAITING + 他室3つLINKED」のsnapshotが在る)。
  - roster snapshotに自室が居ないeventは、こちらの状態を何も語っていないので状態を変えない
    (欠落を「切断」と読むと、無関係なgroupのeventで窓が閉じる)。
  - list_content / join_direct_content は linked_list をそのまま接続者集合として扱う
    (group構造を持たない1:1のLinkMic経路)。**空集合は「切断」**で、v1のように窓を開かない。
  - finish / leave / kick_out / leave_group は明示的な切断。

**v3のrule(v2からの差分)**: 切断contentを「誰の切断か」で読み分ける。
  - v2は当事者を見ずに、切断contentが在れば自分の切断として窓を閉じていた。ところが
    finish_content が名乗るのは ``owner:{room_id, uid}`` = **終了したroom**であり、group
    コラボでは他の参加者のroomが入る。結果、他人が抜けただけで自分の窓が閉じ、次に
    group_change snapshotが届くまで(実測で数十〜数百秒)コラボが記録されなかった。
    録画18本の照合で、この中間の穴が取りこぼしの最大成分(1586秒)だった。
  - v3: 名指しが**自分**(uid or room)なら切断。名指しが**他人**なら、その相手を現在の
    接続者集合から外し、**残りが居ればまだ繋がっている**とみなす。相手を1人しか持たない
    1:1経路ではこれで従来どおり切断になる。当事者を名乗らない切断contentは、1:1経路で
    唯一の終了通知になり得るのでv2どおり切断として扱う。
  - 現在の接続者集合は呼び出し側(collector)が ``current_peers`` で渡す。判定に外部状態を
    持ち込むのはここだけで、渡されなければ「判らない」を返し状態を変えない。

**v4のrule(v3からの差分)**: 退出/取消/拒否で出たsnapshotは**状態を語っていない**。
  - group_change_content の ``source`` は、そのsnapshotが**何の操作で出たか**を名乗る
    (``click_quick_leave_button`` / ``leave_with_user_click_disconnect`` /
    ``REPLY_STATUS_REFUSE_*`` 等)。退出のsnapshotは、抜ける本人をまだ LINKED のまま
    載せた**変化前のroster**である。v3はこれを「own LINKED + 他室LINKED」と読んで
    コラボが終わった瞬間に窓を開き、次のsnapshotが届くまで(実測で最長1時間40分)
    ソロ時間をコラボとして数えていた。
  - v4: 退出系の source が付いた group_change_content では状態を変えない。真の状態は
    直後の別のcontent(finish/join_direct)か、次の通常snapshotが名乗る。
  - ただし ``leave_with_user_click_disconnect`` は**自分が切った**ことの名乗りなので、
    rosterを読まずに切断として扱う。これを無視すると、コラボが終わっても閉じる合図が
    無くなり、次のsnapshotまで窓が開いたままになる(実測47分)。
  - list_content / join_direct_content で、相手が**自室に居る**entryはco-hostではない
    (自室へゲストを上げるmulti-guest)。group_change側は自室entryを is_own として既に
    除いており、こちらだけ残っていた。実測1件(35分)を映像で確かめたところ、画面は
    最後まで配信者ひとりで、共演は映っていなかった。
  - 録画47本(33.3GB・映像38.36h)との照合で、幻が 7.68h → 0.11h、取りこぼしは
    0.87h → 0.88h(不変)。退出の当事者をrosterから外して読む案も試したが、group
    コラボで本物の窓まで閉じ、取りこぼしが8.50hへ悪化したので採らない。

判定は純関数にしてある: 実proto objectでもtestのstubでも getattr で同じように読めるため、
collectorを起動せずにruleだけを検証できる。
"""
from typing import Optional

# 保存済みcollab窓がどのruleで作られたかのversion。ruleを変えたら+1する。
# 分析側はこの値が現行と一致する窓だけを集計対象にする(旧ruleの窓は過大計上で、
# 補正する材料もDBに残っていないため、混ぜずに捨てる)。
# v3の窓は samples/raw の生captureから scripts/rebuild_collab_windows.py で作り直せる。
COLLAB_WINDOW_VERSION = 4

# group_change_content の status。TikTokは文字列enum名で送ってくる。
_GROUP_STATUS_LINKED = "GROUP_STATUS_LINKED"

# source が名乗る「このsnapshotを出した操作」のうち、誰かが抜ける/断る側のもの。
# TikTokは固定enumではなく実装内部の識別子(``click_quick_leave_button`` 等)も混ぜて
# 送るため、完全一致ではなく部分一致で拾う。実配信の生captureに現れた値:
#   click_quick_leave_button / leave_with_user_click_disconnect / inviteCancel_new_arc /
#   applyCancel_new_arc / resetGroupData_cancelAll_cross_arc / sdk_timeout /
#   clear_cross_states:CrossStateToIdle:userLeaveTriggerToIdle /
#   SOURCE_TYPE_*[REPLY_STATUS_REFUSE_*] / SOURCE_TYPE_*[REPLY_STATUS_REJECT]
_LEAVE_SOURCE_MARKS = (
    "leave", "cancel", "refuse", "reject", "timeout", "toidle", "disconnect",
)

# 退出系のうち、**自分が切った**ことを名乗るもの。rosterは変化前のままだが、この名乗り
# 自体が切断の通知である。実配信の生captureに4件あり、4件とも映像のコラボはその1〜4秒後に
# 終わっていた。似た値の ``clear_cross_states:...userLeaveTriggerToIdle`` は3件中1件しか
# 終端と一致せず(1件は730秒後、1件はコラボ中ですらない)、合図として使えないので採らない。
_OWN_DISCONNECT_MARKS = ("leave_with_user_click_disconnect",)


def _uids(all_user) -> list:
    """all_user.linked_list から (uid, room_id) を取り出す。"""
    out = []
    for item in getattr(all_user, "linked_list", None) or []:
        link_user = getattr(item, "link_user", None)
        if link_user is None:
            continue
        uid = getattr(link_user, "uid", 0)
        room = getattr(link_user, "room_id", 0)
        if uid:
            out.append((str(uid), str(room or "")))
    return out


def _party(content) -> tuple:
    """切断contentが名指ししている当事者の (uid, room_id)。名乗りが無ければ ("", "")。

    finish_content は ``owner``、leave/kick_out 系は ``user``/``link_user`` に入る。
    どちらも uid と room_id の少なくとも一方しか埋まっていないことがある。"""
    for name in ("owner", "user", "link_user", "from_user"):
        obj = getattr(content, name, None)
        if obj is None:
            continue
        uid = str(getattr(obj, "uid", 0) or "")
        room = str(getattr(obj, "room_id", 0) or "")
        if not (uid or room):
            # 1段包まれている形(user.link_user 等)。
            inner = getattr(obj, "link_user", None) or getattr(obj, "user", None)
            if inner is not None:
                uid = str(getattr(inner, "uid", 0) or "")
                room = str(getattr(inner, "room_id", 0) or "")
        if uid or room:
            return uid, room
    return "", ""


def _is_own_disconnect(event) -> bool:
    """このsnapshotが「自分が切った」ことを名乗っているか。"""
    source = str(getattr(event, "source", "") or "").lower()
    return any(mark in source for mark in _OWN_DISCONNECT_MARKS)


def _is_leave_snapshot(event) -> bool:
    """このsnapshotが「誰かが抜ける/断る」操作で出たものか。

    ``source`` はpayloadが自分で名乗る発生理由で、退出時のsnapshotは抜ける本人を
    まだLINKEDのまま載せた変化前のrosterである(実配信の生captureで確認)。"""
    source = str(getattr(event, "source", "") or "").lower()
    return any(mark in source for mark in _LEAVE_SOURCE_MARKS)


def _explicit_disconnect(event) -> Optional[tuple]:
    """明示的な切断content。あれば (content名, uid, room_id) を返す。"""
    for name in ("finish_content", "leave_content", "kick_out_content", "leave_group_content"):
        content = getattr(event, name, None)
        if content is None:
            continue
        # betterprotoは未設定fieldも空messageで返すため、中身の有無まで見る。
        if any(
            getattr(content, attr, None)
            for attr in ("owner", "finish_reason", "user", "link_user", "channel_id", "reason")
        ):
            uid, room = _party(content)
            return name, uid, room
    return None


def linkmic_state(event, own_user_id: str, own_room_id: str,
                  current_peers: Optional[dict] = None) -> dict:
    """1 LinkLayerEventから接続状態を読む。

    ``current_peers`` は「今この配信者が繋がっている相手」の ``{user_id: room_id}``。
    切断contentが他人を名指ししたとき、残りの相手が居るかを判断するためだけに使う。

    戻り値:
      connected   True=繋がっている / False=繋がっていない / None=このeventからは判らない
      peers       繋がっている相手のuser_id(自分を除く)
      peer_rooms  相手のuser_id -> その相手のroom_id。LinkLayerは表示名を載せないため、
                  相手の身元はこのroomを引いて解決する(collector._resolve_peer_identities)。
      source      判定に使ったfield名(logと後からの検証用)
    """
    unknown = {"connected": None, "peers": [], "peer_rooms": {}, "source": None}
    own_user_id = str(own_user_id or "")
    own_room_id = str(own_room_id or "")
    current = {str(uid): str(room or "") for uid, room in (current_peers or {}).items()}

    disconnect = _explicit_disconnect(event)
    if disconnect:
        name, uid, room = disconnect
        own = (uid and uid == own_user_id) or (room and room == own_room_id)
        if own or not (uid or room):
            # 自分の切断か、当事者を名乗らない切断(1:1経路では唯一の終了通知になる)。
            return {"connected": False, "peers": [], "peer_rooms": {}, "source": name}
        if not current:
            # 他人が抜けたが、こちらが誰と繋がっているか判らない。状態を変えない。
            return {**unknown, "source": name + ":peer_unknown"}
        remaining = {
            u: r for u, r in current.items()
            if not ((uid and u == uid) or (room and r and r == room))
        }
        return {"connected": bool(remaining), "peers": list(remaining),
                "peer_rooms": remaining, "source": name + ":peer"}

    group = getattr(event, "group_change_content", None)
    group_user = getattr(group, "group_user", None) if group is not None else None
    entries = list(getattr(group_user, "user", None) or []) if group_user is not None else []
    if entries and _is_own_disconnect(event):
        # 自分の切断の名乗り。rosterは変化前のままなので読まず、切断として扱う。
        return {"connected": False, "peers": [], "peer_rooms": {},
                "source": "group_change_content:own_disconnect"}
    if entries and _is_leave_snapshot(event):
        # 退出/取消/拒否で出たsnapshotは変化前のrosterを載せている。ここで読むと
        # コラボが終わった瞬間に「まだ繋がっている」と読み違える。
        return {**unknown, "source": "group_change_content:leave"}
    if entries:
        own_linked = False
        own_seen = False
        peers = []
        peer_rooms: dict = {}
        for entry in entries:
            status = str(getattr(entry, "status", "") or "")
            members = _uids(getattr(entry, "all_user", None))
            channel = str(getattr(entry, "channel_id", "") or "")
            is_own = channel == own_room_id or any(
                uid == own_user_id or room == own_room_id for uid, room in members
            )
            if is_own:
                own_seen = True
                own_linked = status == _GROUP_STATUS_LINKED
                continue
            if status == _GROUP_STATUS_LINKED:
                for uid, room in members:
                    if uid == own_user_id:
                        continue
                    peers.append(uid)
                    # 相手のroom_idは身元解決の唯一の手掛かり。空を入れて上書きしない
                    # (同じ相手が room 無しのentryでも現れる)。
                    if room and not peer_rooms.get(uid):
                        peer_rooms[uid] = room
        if not own_seen:
            # 自室が載っていないsnapshot。こちらの状態を語っていないので触らない。
            return {**unknown, "source": "group_change_content:no_self"}
        return {
            "connected": bool(own_linked and peers),
            "peers": peers,
            "peer_rooms": peer_rooms,
            "source": "group_change_content",
        }

    for name in ("list_content", "join_direct_content"):
        content = getattr(event, name, None)
        if content is None:
            continue
        all_user = getattr(content, "user_list", None) or getattr(content, "all_users", None)
        if all_user is None:
            continue
        # 相手が**自室に居る**entryはco-hostではない。自室へゲストを上げるmulti-guestで、
        # group_change側は自室entryを is_own として既に除いている(こちらだけ残っていた)。
        # 実測1件(35分)を映像で確かめたところ、画面は最後まで配信者ひとりだった。
        members = [(uid, room) for uid, room in _uids(all_user)
                   if uid != own_user_id and str(room or "") != own_room_id]
        peers = [uid for uid, _room in members]
        peer_rooms = {uid: room for uid, room in members if room}
        # 空のlinked_listは「もう誰も居ない」。v1はここで窓を開いていた。
        return {"connected": bool(peers), "peers": peers,
                "peer_rooms": peer_rooms, "source": name}

    return unknown
