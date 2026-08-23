"""素材API(/api/assets)。

確かめる軸は3つある:

1. **一覧の源が種別で違う**(Giftアイコン/Emoteはdisk、Userアイコンはusers表)。特に
   Userアイコンは「cacheの無い行を落とさない」ことが契約で、落とすとpageの継ぎ目と
   総数が同時に壊れる。
2. **summaryはdiskを歩かない**。返すのはDBのsnapshotだけで、まだ数えていない種別は
   0件ではなくnullを名乗る。数え直すのは ``POST /api/assets/rescan`` だけである。
3. **まとめDownloadは発券と引き換えの2段**。選んだidをURLへ載せられないためで、
   検証(件数超過・id不正・対象0件)は発券のJSON応答で名乗る。

fileはlayoutが解決するpool(このtestのsandbox)へ、DBの行は ``runtime.storage``(import時に
掴んだsandbox)へ置く。route側も同じ2箇所を見るので、これで実運用と同じ組み合わせになる。
"""

import io
import json
import os
import zipfile

import pytest

from tictok.media.avatar_pool import avatar_key

# 実物の先頭bytes。形式は中身から判定するので、magicが本物でないと名乗りが変わる。
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
_GIF = b"GIF89a" + b"\x00" * 24
_NOT_AN_IMAGE = b"\x00\x01\x02\x03" + b"\x00" * 24


@pytest.fixture
def server(env_guard):
    # env_guard を先に効かせてから import する。tictok.api.runtime は import 時に
    # Storage / instance lock / record dir を掴むため、順序が逆だと本番を掴む。
    from types import SimpleNamespace

    import tictok.server as srv
    from tictok.api import runtime

    assert not str(runtime.RECORD_DIR).lower().endswith("tictok\\recordings")
    return SimpleNamespace(app=srv.app, runtime=runtime)


@pytest.fixture
def client(server):
    # context manager として使わないこと。lifespan が走ると監視復元と queue worker が
    # 立ち上がり、shutdown で storage が閉じられて後続 test が使えなくなる。
    from fastapi.testclient import TestClient

    return TestClient(server.app)


@pytest.fixture
def assets_routes(server):
    """route moduleと、processに残る状態の後始末。

    走査のsnapshotはDB(``asset_scan``)に残り、``runtime.storage`` はprocessで1つなので
    testを跨いで生き残る。poolのrootはtestごとに別のsandboxなので、消してから始めないと
    前のtestが数えた件数を自分のものとして読む。
    """
    from tictok.api.routes import assets

    def _clear():
        storage = server.runtime.storage
        with storage._lock:
            storage._conn.execute("DELETE FROM asset_scan")
            storage._conn.commit()
        assets.reset_tickets()

    _clear()
    yield assets
    _clear()


@pytest.fixture
def pool(server, assets_routes):
    """3種のpool dirを作って返す。"""
    from tictok.core import layout

    dirs = {
        "gift_icon": layout.gift_icon_pool_dir(),
        "emote": layout.emote_pool_dir(),
        "avatar": layout.avatar_pool_dir(),
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


@pytest.fixture
def override_settings(server, monkeypatch):
    """設定値を1つだけ差し替える。``runtime.settings`` ごと置き換えるので、
    ``runtime.settings.get`` を呼び出し時に引いているroute側へ確実に届く。"""

    def _apply(**overrides):
        base = server.runtime.settings

        class _Patched:
            def get(self, key):
                return overrides[key] if key in overrides else base.get(key)

        monkeypatch.setattr(server.runtime, "settings", _Patched())

    return _apply


def _put(directory, name, content=_PNG):
    path = directory / name
    path.write_bytes(content)
    return path


def _seed_user(server, unique_id, nickname, avatar_bytes=None, pool_dir=None):
    """users表へ1人足し、必要ならそのavatarをpoolへ置く。"""
    storage = server.runtime.storage
    session_id = storage.create_session(unique_id + "_owner", 60)
    storage.add_event(session_id, {
        "time": 1000.0, "kind": "comment",
        "user": {"user_id": "", "unique_id": unique_id, "nickname": nickname},
        "comment": "hi",
    })
    storage.flush()
    if avatar_bytes is not None:
        _put(pool_dir, f"{avatar_key(unique_id)}.img", avatar_bytes)
    return avatar_key(unique_id)


def _summary_by_kind(client):
    return {kind["kind"]: kind for kind in client.get("/api/assets/summary").json()["kinds"]}


# ---- summary は走査しない -----------------------------------------------------------


def test_summary_says_null_not_zero_before_the_first_scan(client, pool):
    _put(pool["avatar"], f"{'a' * 40}.img")

    by_kind = _summary_by_kind(client)

    assert [kind for kind in by_kind] == ["gift_icon", "emote", "avatar"]
    # 「素材が無い」と「まだ数えていない」は別の事実。0件に畳むと画面が嘘をつく。
    for kind in by_kind.values():
        assert kind["count"] is None
        assert kind["listable"] is None
        assert kind["bytes"] is None
        assert kind["scanned_at"] is None
        assert kind["duration_ms"] is None
    assert by_kind["avatar"]["label"] == "Userアイコン"
    # 並び順は集計結果ではなく種別の性質なので、走査前から名乗れる。
    assert by_kind["gift_icon"]["sorts"] == ["sends", "coins", "name", "size", "mtime"]
    assert by_kind["emote"]["sorts"] == ["uses", "name", "size", "mtime"]
    assert by_kind["avatar"]["sorts"] == ["freq", "last_seen", "name"]
    # 配信者で絞れる種別。giftは配信者別に集計していないので受けない。
    assert by_kind["gift_icon"]["filters"] == []
    assert by_kind["emote"]["filters"] == ["streamer"]
    assert by_kind["avatar"]["filters"] == ["streamer"]


def test_summary_does_not_walk_the_pool(client, pool, assets_routes, monkeypatch):
    """summaryがdiskを歩かないこと。歩くとavatarのpoolで1回1.2〜2.5秒かかる。"""
    def _forbidden(*_args, **_kwargs):
        raise AssertionError("summaryがpoolを走査しました")

    monkeypatch.setattr(assets_routes, "_scan_pool", _forbidden)

    assert client.get("/api/assets/summary").status_code == 200


def test_rescan_fills_the_snapshot_for_every_kind(client, pool):
    _put(pool["gift_icon"], "10065.img")
    _put(pool["gift_icon"], "10066.img")
    # 焼き込みが同じdirへ置く得点表示用のavatarとgift名のindex。素材ではないので
    # 件数にも容量にも入らない。
    _put(pool["gift_icon"], "savatar_deadbeef_56.png", b"x" * 999)
    (pool["gift_icon"] / "names.json").write_text("{}", encoding="utf-8")
    _put(pool["emote"], "7300000000000000000.img")
    _put(pool["avatar"], f"{'a' * 40}.img")
    # avatarの付随file。点数には入らないが、実占有量には入る。
    (pool["avatar"] / f"{'a' * 40}.type").write_text("image/png", encoding="utf-8")
    (pool["avatar"] / f"{'a' * 40}.meta").write_text('{"w":72,"h":72}', encoding="utf-8")

    body = client.post("/api/assets/rescan").json()

    by_kind = {kind["kind"]: kind for kind in body["kinds"]}
    assert by_kind["gift_icon"]["count"] == 2
    assert by_kind["gift_icon"]["bytes"] == len(_PNG) * 2
    assert by_kind["emote"]["count"] == 1
    assert by_kind["avatar"]["count"] == 1
    assert by_kind["avatar"]["bytes"] > len(_PNG)
    assert all(kind["scanned_at"] > 0 for kind in body["kinds"])
    assert all(kind["duration_ms"] >= 0 for kind in body["kinds"])
    assert body["pool_root"]
    # 走査が終わってから応答を組む。lockを握ったまま組むと必ずtrueになる。
    assert body["scanning"] is False
    # 数えた結果はsummaryが返すsnapshotそのもの。
    assert _summary_by_kind(client)["avatar"]["count"] == 1
    # 名前の源がidそのものの種別は、diskに在る分が全部一覧に出せる。
    assert by_kind["gift_icon"]["listable"] == 2
    assert by_kind["emote"]["listable"] == 1


def test_empty_files_are_left_out_of_the_count_so_it_matches_the_zip(client, pool):
    """0 byteの ``.img`` を数えないこと。

    一覧の ``cached`` 判定もZIPも既にこれを除いているので、ここだけが数えていると
    summaryの件数と全件ZIPの件数がずれる。実poolには今のところ0 byteのfileは無い
    (実測3種とも0件)が、1つ出た日に気付けないずれへ化けるのでtestで固定しておく。"""
    _put(pool["gift_icon"], "10065.img", _PNG)
    _put(pool["gift_icon"], "10066.img", b"")

    count = client.post("/api/assets/rescan?kind=gift_icon").json()["kinds"][0]["count"]

    assert count == 1
    assert _issue(client, "gift_icon").json()["count"] == count


def test_listable_counts_assets_that_can_be_named_not_users(client, pool, server):
    """``count - listable`` が「実体は在るが名前を辿れない素材」の数と一致すること。

    ``listable`` は ``count`` と**同じ母集団**(diskに在る素材)を数える。users表の行数に
    すると母集団が「人」になり、cacheを持たない人まで入るので引き算が事実と合わなくなる。
    """
    # 名前を辿れる素材(users表に居て、poolにも実体が在る)。
    _seed_user(server, "assetslistable", "名乗れる人", _PNG, pool["avatar"])
    # 名前を辿れない素材(poolにだけ残った鍵)。これが差の中身。
    _put(pool["avatar"], f"{'b' * 40}.img", _PNG)
    # users表には居るがpoolに実体が無い人。**素材ではない**ので、どちらの数にも入らない。
    _seed_user(server, "assetsnofile", "cacheの無い人")

    avatar = client.post("/api/assets/rescan?kind=avatar").json()["kinds"][2]

    assert avatar["kind"] == "avatar"
    assert avatar["count"] == 2
    assert avatar["listable"] == 1
    # 差は「名前を辿れない素材」1点ちょうど。cacheの無い人はここに現れない。
    assert avatar["count"] - avatar["listable"] == 1


def test_listable_is_not_the_list_total(client, pool, server):
    """``listable`` と 一覧の ``total`` は別の母集団なので一致しない。

    一覧はusers表(人)が源で、cacheを持たない人も ``cached: false`` の行として並ぶ。
    ここを一致させようとすると、どちらかが自分の問いに答えなくなる。"""
    _seed_user(server, "assetsboth", "在る人", _PNG, pool["avatar"])
    _seed_user(server, "assetsnone", "無い人")

    avatar = client.post("/api/assets/rescan?kind=avatar").json()["kinds"][2]
    total = client.get("/api/assets?kind=avatar&limit=1").json()["total"]

    # 素材は1点、一覧に並ぶ人は2人。
    assert avatar["listable"] == 1
    assert total >= 2


@pytest.mark.parametrize("call", [
    lambda client: client.post("/api/assets/rescan?kind=emote"),
    lambda client: client.post("/api/assets/rescan", json={"kind": "emote"}),
])
def test_rescan_can_target_one_kind_by_query_or_body(client, pool, call):
    """種別はqueryでもbodyでも受ける。片方だけを受ける形にすると、もう片方で呼んだ人には
    全種別の走査(avatarは実測2.7秒)が黙って走り、指定が無視されたことが応答から読めない。"""
    _put(pool["emote"], "7300000000000000000.img")
    _put(pool["avatar"], f"{'a' * 40}.img")

    call(client)

    by_kind = _summary_by_kind(client)
    assert by_kind["emote"]["count"] == 1
    # 指定しなかった種別は触らない(avatarは実測2.7秒。ついでに数え直さない)。
    assert by_kind["avatar"]["count"] is None


def test_rescan_rejects_an_unknown_kind(client, pool):
    assert client.post("/api/assets/rescan?kind=sticker").status_code == 400
    assert client.post("/api/assets/rescan", json={"kind": "sticker"}).status_code == 400


def test_walking_kinds_refresh_their_snapshot_but_avatar_does_not(client, pool, server):
    """一覧を作るためにdirを歩く種別は、そのついでにsnapshotが新しくなる。

    avatarが新しくならないのは、一覧がusers表駆動でdirを歩く機会が無いためである。"""
    _put(pool["gift_icon"], "10065.img")
    _put(pool["emote"], "7300000000000000000.img")
    _seed_user(server, "assetswalk", "歩く人", _PNG, pool["avatar"])

    client.get("/api/assets?kind=gift_icon")
    client.get("/api/assets?kind=emote")
    client.get("/api/assets?kind=avatar")

    by_kind = _summary_by_kind(client)
    assert by_kind["gift_icon"]["count"] == 1
    assert by_kind["emote"]["count"] == 1
    assert by_kind["avatar"]["count"] is None


def test_listing_a_walking_kind_keeps_the_gift_names_taken_at_scan_time(
        client, pool, server):
    """一覧のついでの更新がpayloadを消さないこと。

    一覧の経路はeventsを引かない(実測500ms)ので走査時のgift名を知らない。空で上書き
    すると、一覧を1回開くだけで名前が全部消える。"""
    _put(pool["gift_icon"], "998001.img")
    session_id = server.runtime.storage.create_session("assets_keep_owner", 60)
    server.runtime.storage.add_event(session_id, {
        "time": 10.0, "kind": "gift",
        "user": {"user_id": "u1", "unique_id": "assetskeeper", "nickname": "送り主"},
        "gift_name": "Old Gift", "repeat_count": 1, "diamonds": 1, "gift_id": 998001,
    })
    server.runtime.storage.flush()
    client.post("/api/assets/rescan?kind=gift_icon")

    first = client.get("/api/assets?kind=gift_icon&q=998001").json()
    second = client.get("/api/assets?kind=gift_icon&q=998001").json()

    assert [item["name"] for item in first["items"]] == ["Old Gift"]
    assert [item["name"] for item in second["items"]] == ["Old Gift"]


# ---- 一覧(disk源) -----------------------------------------------------------------


def test_gift_icons_are_listed_with_names_from_the_catalog(client, pool):
    _put(pool["gift_icon"], "10065.img")
    _put(pool["gift_icon"], "10066.img")
    (pool["gift_icon"] / "names.json").write_text(
        json.dumps({"Rose": 10065}), encoding="utf-8")

    body = client.get("/api/assets?kind=gift_icon&sort=name").json()

    assert body["kind"] == "gift_icon"
    assert body["total"] == 2
    items = {item["id"]: item for item in body["items"]}
    # カタログはfileを1本読むだけなので、走査を待たずに名乗れる。
    assert items["10065"]["name"] == "Rose"
    assert items["10065"]["sub"] == "gift_id 10065"
    assert items["10065"]["content_type"] == "image/png"
    assert items["10065"]["cached"] is True
    assert items["10065"]["src"] == "/api/assets/file?kind=gift_icon&id=10065"
    # 名前を引けなかったgiftは空のまま。それらしい代替名を作らない。
    assert items["10066"]["name"] == ""


def test_gift_names_from_events_arrive_with_the_rescan(client, pool, server):
    _put(pool["gift_icon"], "998002.img")
    session_id = server.runtime.storage.create_session("assets_gift_owner", 60)
    server.runtime.storage.add_event(session_id, {
        "time": 10.0, "kind": "gift",
        "user": {"user_id": "u1", "unique_id": "assetsgifter", "nickname": "送り主"},
        "gift_name": "Old Gift", "repeat_count": 1, "diamonds": 1, "gift_id": 998002,
    })
    server.runtime.storage.flush()

    # 走査前はカタログに無いので名乗れない(eventsは一覧のたびには引けない)。
    before = client.get("/api/assets?kind=gift_icon&q=998002").json()
    assert [item["name"] for item in before["items"]] == [""]

    client.post("/api/assets/rescan?kind=gift_icon")

    after = client.get("/api/assets?kind=gift_icon&q=998002").json()
    assert [item["name"] for item in after["items"]] == ["Old Gift"]


def test_the_catalog_wins_over_the_name_seen_in_events(client, pool, server):
    """カタログは「今の名前」、eventsは「その時そう呼ばれていた名前」。探す人が
    知っているのは前者なので、両方在ればカタログを採る。"""
    _put(pool["gift_icon"], "998003.img")
    session_id = server.runtime.storage.create_session("assets_rename_owner", 60)
    server.runtime.storage.add_event(session_id, {
        "time": 10.0, "kind": "gift",
        "user": {"user_id": "u1", "unique_id": "assetsrenamer", "nickname": "送り主"},
        "gift_name": "Team Cheers", "repeat_count": 1, "diamonds": 1, "gift_id": 998003,
    })
    server.runtime.storage.flush()
    (pool["gift_icon"] / "names.json").write_text(
        json.dumps({"Club Cheers": 998003}), encoding="utf-8")
    client.post("/api/assets/rescan?kind=gift_icon")

    body = client.get("/api/assets?kind=gift_icon&q=998003").json()

    assert [item["name"] for item in body["items"]] == ["Club Cheers"]


def test_gift_icon_search_matches_id_and_name(client, pool):
    for gift_id in ("10065", "10066", "20077"):
        _put(pool["gift_icon"], f"{gift_id}.img")
    (pool["gift_icon"] / "names.json").write_text(
        json.dumps({"Rose": 10065, "Rosa": 20077}), encoding="utf-8")

    by_id = client.get("/api/assets?kind=gift_icon&q=1006").json()
    assert {item["id"] for item in by_id["items"]} == {"10065", "10066"}
    assert by_id["total"] == 2

    by_name = client.get("/api/assets?kind=gift_icon&q=ros").json()
    assert {item["id"] for item in by_name["items"]} == {"10065", "20077"}


def test_gift_icon_pagination_splits_the_same_ordering(client, pool):
    for gift_id in range(10, 16):
        _put(pool["gift_icon"], f"{gift_id}.img")

    first = client.get("/api/assets?kind=gift_icon&sort=name&limit=2&offset=0").json()
    second = client.get("/api/assets?kind=gift_icon&sort=name&limit=2&offset=2").json()

    assert first["total"] == second["total"] == 6
    assert first["limit"] == 2 and second["offset"] == 2
    assert len(first["items"]) == len(second["items"]) == 2
    ids = [item["id"] for item in first["items"] + second["items"]]
    assert ids == sorted(ids, key=str)
    assert len(set(ids)) == 4


def test_disk_assets_sort_by_size_and_by_time(client, pool):
    small = _put(pool["emote"], "7300000000000000001.img", _PNG)
    big = _put(pool["emote"], "7300000000000000002.img", _PNG + b"\x00" * 500)
    # mtimeは書いた順(小 -> 大)。同じ秒に落ちないよう明示的にずらす。
    os.utime(small, (1_700_000_000, 1_700_000_000))
    os.utime(big, (1_700_000_100, 1_700_000_100))

    by_size = client.get("/api/assets?kind=emote&sort=size&order=desc").json()
    assert [item["id"] for item in by_size["items"]] == [big.stem, small.stem]

    by_time = client.get("/api/assets?kind=emote&sort=mtime&order=asc").json()
    assert [item["id"] for item in by_time["items"]] == [small.stem, big.stem]


def test_emote_is_named_by_its_id_only(client, pool):
    _put(pool["emote"], "7300000000000000000.img", _GIF)

    item = client.get("/api/assets?kind=emote&sort=name").json()["items"][0]

    # emoteには名前の源が無い。無いものを作らず、idだけで名乗る。
    assert item["name"] == ""
    assert item["sub"] == "emote_id 7300000000000000000"
    assert item["content_type"] == "image/gif"


def test_unknown_kind_is_rejected(client):
    assert client.get("/api/assets?kind=sticker").status_code == 400


def test_limit_out_of_range_is_rejected(client, pool):
    assert client.get("/api/assets?kind=emote&limit=0").status_code == 400
    assert client.get("/api/assets?kind=emote&limit=100000").status_code == 400
    assert client.get("/api/assets?kind=emote&offset=-1").status_code == 400


# ---- 並び順 -------------------------------------------------------------------------


def test_every_sort_the_summary_offers_is_actually_accepted(client, pool, server):
    """summaryが配る並び順と、一覧が受ける並び順がずれていないこと。

    画面はsummaryのsortsからcontrolを作るので、ここがずれると「選べるのに400が返る」
    選択肢が出る。"""
    _put(pool["gift_icon"], "10065.img")
    _put(pool["emote"], "7300000000000000000.img")
    _seed_user(server, "assetssorts", "並び", _PNG, pool["avatar"])

    for kind in _summary_by_kind(client).values():
        for sort in kind["sorts"]:
            for order in ("asc", "desc"):
                response = client.get(
                    f"/api/assets?kind={kind['kind']}&sort={sort}&order={order}")
                assert response.status_code == 200, (kind["kind"], sort, order)


def test_a_sort_the_summary_does_not_offer_is_rejected(client, pool, server):
    _put(pool["gift_icon"], "10065.img")
    _seed_user(server, "assetsnosort", "並べない", _PNG, pool["avatar"])

    for kind_name, sort in (("avatar", "size"), ("avatar", "mtime"),
                            ("gift_icon", "last_seen"), ("emote", "nonsense")):
        offered = _summary_by_kind(client)[kind_name]["sorts"]
        assert sort not in offered
        response = client.get(f"/api/assets?kind={kind_name}&sort={sort}")
        # 黙って別の並びで返さない。押した並び順と出てくる順が違うことに
        # 画面からは気付けない。
        assert response.status_code == 400, (kind_name, sort)
        assert sort in response.json()["detail"]


# ---- 一覧(avatar = users表が源) ----------------------------------------------------


def test_avatar_list_keeps_rows_without_a_cached_file(client, pool, server):
    cached = _seed_user(server, "assetscached", "在る人", _PNG, pool["avatar"])
    _seed_user(server, "assetsmissing", "無い人")

    body = client.get("/api/assets?kind=avatar&q=assets").json()

    items = {item["sub"]: item for item in body["items"]}
    assert body["total"] >= 2
    # cacheが無い行も落とさない。落とすとSQLのCOUNTと実際の件数が食い違い、
    # page送りが進むほどずれる。
    assert items["@assetscached"]["cached"] is True
    assert items["@assetscached"]["id"] == cached
    assert items["@assetscached"]["name"] == "在る人"
    assert items["@assetscached"]["bytes"] == len(_PNG)
    assert items["@assetsmissing"]["cached"] is False
    assert items["@assetsmissing"]["bytes"] == 0
    assert items["@assetsmissing"]["src"] == ""


def test_avatar_cached_is_the_state_right_now_not_the_snapshot(client, pool, server):
    """``cached`` を集計から答えないこと。古い数字から答えると、既に消えた素材に
    Download buttonを出すことになる。"""
    _seed_user(server, "assetsvanish", "消える人", _PNG, pool["avatar"])
    client.post("/api/assets/rescan?kind=avatar")
    assert _summary_by_kind(client)["avatar"]["count"] == 1

    (pool["avatar"] / f"{avatar_key('assetsvanish')}.img").unlink()

    body = client.get("/api/assets?kind=avatar&q=assetsvanish").json()
    assert [item["cached"] for item in body["items"]] == [False]


def test_avatar_search_escapes_like_metacharacters(client, pool, server):
    _seed_user(server, "assets_under", "アンダー", _PNG, pool["avatar"])
    _seed_user(server, "assetsXunder", "エックス", _PNG, pool["avatar"])

    body = client.get("/api/assets?kind=avatar&q=assets_under").json()

    subs = {item["sub"] for item in body["items"]}
    assert "@assets_under" in subs
    assert "@assetsXunder" not in subs


# ---- 1件の取得 ---------------------------------------------------------------------


def test_file_returns_the_bytes_with_a_sniffed_content_type(client, pool):
    _put(pool["gift_icon"], "10065.img", _PNG)

    response = client.get("/api/assets/file?kind=gift_icon&id=10065")

    assert response.status_code == 200
    assert response.content == _PNG
    assert response.headers["content-type"] == "image/png"
    assert "max-age" in response.headers["cache-control"]


def test_file_does_not_claim_a_format_it_cannot_identify(client, pool):
    _put(pool["emote"], "7300000000000000001.img", _NOT_AN_IMAGE)

    response = client.get("/api/assets/file?kind=emote&id=7300000000000000001")

    assert response.headers["content-type"] == "application/octet-stream"


def test_file_download_names_the_gift_by_id_and_name(client, pool):
    _put(pool["gift_icon"], "10065.img")
    (pool["gift_icon"] / "names.json").write_text(
        json.dumps({"Rose/Red": 10065}), encoding="utf-8")

    response = client.get("/api/assets/file?kind=gift_icon&id=10065&download=1")

    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment; filename*=UTF-8''")
    # path区切りはfile名に残さない。
    assert "gift_10065_Rose_Red.png" in disposition


def test_file_download_names_the_avatar_by_unique_id(client, pool, server):
    key = _seed_user(server, "assetsdl", "落とす人", _PNG, pool["avatar"])

    response = client.get(f"/api/assets/file?kind=avatar&id={key}&download=1")

    assert "assetsdl.png" in response.headers["content-disposition"]


def test_file_404s_for_an_asset_that_is_not_on_disk(client, pool):
    assert client.get("/api/assets/file?kind=gift_icon&id=999999").status_code == 404


@pytest.mark.parametrize("kind,asset_id", [
    ("gift_icon", "../../secret"),
    ("gift_icon", "..\\secret"),
    ("gift_icon", "10065/../../x"),
    ("gift_icon", "abc"),
    ("emote", "../names"),
    ("emote", "a/b"),
    ("avatar", "../../../windows/system32"),
    ("avatar", "a" * 39),
    ("avatar", "A" * 40),
    ("avatar", "z" * 40),
])
def test_file_rejects_ids_that_are_not_of_the_pools_own_shape(client, pool, kind, asset_id):
    response = client.get("/api/assets/file", params={"kind": kind, "id": asset_id})
    assert response.status_code == 400


# ---- まとめてDownload(発券 -> 引き換え) --------------------------------------------


def _issue(client, kind, ids=None):
    body = {"kind": kind}
    if ids is not None:
        body["ids"] = ids
    return client.post("/api/assets/archive", json=body)


def _zip_of(client, ticket):
    response = client.get(f"/api/assets/archive/{ticket}")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    return zipfile.ZipFile(io.BytesIO(response.content))


def test_the_ticket_counts_what_the_zip_will_hold(client, pool):
    _put(pool["gift_icon"], "10065.img", _PNG)
    _put(pool["gift_icon"], "10066.img", _GIF)
    (pool["gift_icon"] / "names.json").write_text(
        json.dumps({"Rose": 10065}), encoding="utf-8")

    issued = _issue(client, "gift_icon").json()

    assert issued["kind"] == "gift_icon"
    assert issued["count"] == 2
    assert issued["bytes"] == len(_PNG) + len(_GIF)
    assert issued["expires_at"] > 0
    assert issued["ticket"]

    with _zip_of(client, issued["ticket"]) as archive:
        assert archive.testzip() is None
        # ZIPの中身は発券のときに数えた件数と一致する。
        assert len(archive.namelist()) == issued["count"]
        assert sorted(archive.namelist()) == ["gift_10065_Rose.png", "gift_10066.gif"]
        assert archive.read("gift_10065_Rose.png") == _PNG
        # 画像は圧縮済みなので詰め直さない。
        assert archive.getinfo("gift_10066.gif").compress_type == zipfile.ZIP_STORED


def test_the_ticket_takes_only_the_selected_ids(client, pool):
    for gift_id in ("10065", "10066", "10067"):
        _put(pool["gift_icon"], f"{gift_id}.img")

    issued = _issue(client, "gift_icon", ["10065", "10067"]).json()

    assert issued["count"] == 2
    with _zip_of(client, issued["ticket"]) as archive:
        assert sorted(archive.namelist()) == ["gift_10065.png", "gift_10067.png"]


def test_a_ticket_can_be_redeemed_more_than_once(client, pool):
    """538MBの転送は途中で切れ得るので、期限内なら何度でも引き換えられる。
    使い切りにすると、再試行のたびに選び直しからやり直すことになる。"""
    _put(pool["gift_icon"], "10065.img")

    ticket = _issue(client, "gift_icon").json()["ticket"]

    with _zip_of(client, ticket) as first:
        assert first.namelist() == ["gift_10065.png"]
    with _zip_of(client, ticket) as second:
        assert second.namelist() == ["gift_10065.png"]


def test_an_expired_ticket_is_404_not_a_new_zip(client, pool, assets_routes):
    _put(pool["gift_icon"], "10065.img")
    ticket = _issue(client, "gift_icon").json()["ticket"]
    assets_routes._tickets[ticket]["expires_at"] = 0

    response = client.get(f"/api/assets/archive/{ticket}")

    # 券を作り直して黙って続けない。選んだ物は画面にしか無い。
    assert response.status_code == 404
    assert "期限" in response.json()["detail"]


def test_an_unknown_ticket_is_404(client, pool):
    assert client.get("/api/assets/archive/not-a-real-ticket").status_code == 404


def test_too_many_selected_ids_are_refused_before_counting(client, pool, override_settings):
    for gift_id in ("10065", "10066", "10067"):
        _put(pool["gift_icon"], f"{gift_id}.img")
    override_settings(asset_archive_max_ids=2)

    response = _issue(client, "gift_icon", ["10065", "10066", "10067"])

    assert response.status_code == 400
    assert "2件" in response.json()["detail"]
    # 全件は選んだ物を持ち回らないので上限を受けない。
    assert _issue(client, "gift_icon").json()["count"] == 3


def test_the_ticket_refuses_an_id_of_the_wrong_shape(client, pool):
    _put(pool["gift_icon"], "10065.img")

    response = _issue(client, "gift_icon", ["10065", "../etc"])

    # 黙って除かない。除くと押した件数より少ないZIPが理由なしで出来る。
    assert response.status_code == 400


def test_the_ticket_refuses_an_unknown_kind(client, pool):
    assert _issue(client, "sticker").status_code == 400


def test_the_ticket_is_404_when_there_is_nothing_to_bundle(client, pool):
    assert _issue(client, "emote").status_code == 404


def test_files_that_cannot_be_read_are_left_out_of_both_the_count_and_the_zip(
        client, pool):
    _put(pool["gift_icon"], "10065.img", _PNG)
    _put(pool["gift_icon"], "10066.img", b"")

    issued = _issue(client, "gift_icon").json()

    assert issued["count"] == 1
    with _zip_of(client, issued["ticket"]) as archive:
        assert archive.namelist() == ["gift_10065.png"]


def test_archive_of_avatars_names_them_by_user(client, pool, server):
    _seed_user(server, "assetszipa", "ZIPの人", _PNG, pool["avatar"])

    issued = _issue(client, "avatar").json()

    with _zip_of(client, issued["ticket"]) as archive:
        assert "assetszipa.png" in archive.namelist()


def test_the_avatar_archive_covers_the_whole_pool_not_just_the_listable_rows(
        client, pool, server):
    """全件ZIPは**diskに在る全件**。一覧に出せる分だけにすると、summaryが名乗る点数に
    対応する物を取り出す手段が無くなる（「片付けたら空く容量」の中身が取れない）。

    名前を引けない鍵は ``<avatar_key>.<ext>`` で名乗る。鍵はその素材の身元そのものなので
    捏造ではない。"""
    _seed_user(server, "assetszipb", "名乗れる人", _PNG, pool["avatar"])
    orphan = "c" * 40
    _put(pool["avatar"], f"{orphan}.img", _GIF)

    scanned = client.post("/api/assets/rescan?kind=avatar").json()["kinds"][2]
    issued = _issue(client, "avatar").json()

    # summaryの点数と全件ZIPの件数が一致する。
    assert issued["count"] == scanned["count"] == 2
    with _zip_of(client, issued["ticket"]) as archive:
        assert len(archive.namelist()) == issued["count"]
        assert "assetszipb.png" in archive.namelist()
        assert f"{orphan}.gif" in archive.namelist()


# ---- 集計(stats)と配信者filter ------------------------------------------------------


def _gift_event(server, owner, gift_id, name, count, diamonds, at=10.0):
    storage = server.runtime.storage
    session_id = storage.create_session(owner, 60)
    storage.add_event(session_id, {
        "time": at, "kind": "gift",
        "user": {"user_id": "u1", "unique_id": "statgifter", "nickname": "送り主"},
        "gift_name": name, "repeat_count": count, "diamonds": diamonds,
        "gift_id": gift_id,
    })
    storage.flush()
    return session_id


def _comment_with_emotes(server, owner, emote_ids, unique_id="statviewer"):
    storage = server.runtime.storage
    session_id = storage.create_session(owner, 60)
    storage.add_event(session_id, {
        "time": 20.0, "kind": "comment",
        "user": {"user_id": "", "unique_id": unique_id, "nickname": "使う人"},
        "comment": "hi",
        # collectorが入れるのと同じ形。events.emotes はJSON listをそのまま入れたTEXT列で、
        # listのまま渡すとbindでこける(_emote_payload が返すのは文字列)。
        "emotes": json.dumps([{"index": i, "id": emote_id, "url": ""}
                              for i, emote_id in enumerate(emote_ids)]),
    })
    storage.flush()
    return session_id


def test_gift_stats_carry_sends_and_unit_price(client, pool, server):
    """``sends`` は送られた**個数**（event数ではない）、``coins`` は1個あたりの単価。

    連打は1 eventに repeat_count 個まとまって届くので、event数で数えると100連打が1回に
    なる。単価は diamonds / gift_count で、これはgiftごとに一定の値である。"""
    _put(pool["gift_icon"], "998010.img")
    _gift_event(server, "stat_owner_a", 998010, "Rose", count=10, diamonds=50)
    _gift_event(server, "stat_owner_a", 998010, "Rose", count=3, diamonds=15, at=11.0)
    client.post("/api/assets/rescan?kind=gift_icon")

    item = client.get("/api/assets?kind=gift_icon&q=998010").json()["items"][0]

    stats = {row["key"]: row for row in item["stats"]}
    assert stats["sends"]["value"] == 13
    # labelとunitは「回」ではなく「個」。10連は1 eventだが10個で、「回数」と名乗ると
    # 隣に出る数字と食い違う。
    assert stats["sends"]["label"] == "送られた個数"
    assert stats["sends"]["unit"] == "個"
    assert stats["coins"]["value"] == 5
    # gift 1つを送るのにかかるコインの数。連打の総額ではないので gift_count で割る。
    assert stats["coins"]["label"] == "コイン数"
    assert stats["coins"]["unit"] is None


def test_stat_keys_match_the_sort_identifiers(client, pool, server):
    """``stats`` のkeyと並び順の識別子が同じ語であること。

    画面が「今どの数字で並んでいるか」を、対応表を持たずに示せるための約束である。"""
    _put(pool["gift_icon"], "998011.img")
    _put(pool["emote"], "7300000000000000010.img")
    _gift_event(server, "stat_owner_b", 998011, "Gift", count=1, diamonds=1)
    _comment_with_emotes(server, "stat_owner_b", ["7300000000000000010"])
    _seed_user(server, "statavatar", "並ぶ人", _PNG, pool["avatar"])
    client.post("/api/assets/rescan")

    summary = _summary_by_kind(client)
    for kind, query in (("gift_icon", "&q=998011"), ("emote", ""), ("avatar", "")):
        body = client.get(f"/api/assets?kind={kind}{query}").json()
        keys = {row["key"] for item in body["items"] for row in item["stats"]}
        assert keys, kind
        # statsのkeyは必ずその種別のsortsに在る語である。
        assert keys <= set(summary[kind]["sorts"]), (kind, keys)


def test_sorting_by_a_stat_never_drops_rows(client, pool):
    """並べ替えでは行を落とさないこと。

    落とす形にすると、まだ一度も再走査していない環境で既定の並び(集計順)が空の一覧に
    なる。集計を持たない素材は末尾へ回り、``stats`` からはその項目が落ちる。"""
    _put(pool["gift_icon"], "998012.img")
    _put(pool["gift_icon"], "998013.img")

    body = client.get("/api/assets?kind=gift_icon&sort=sends").json()

    assert body["total"] == 2
    # 記録が無いので0を入れず、項目ごと落とす。
    assert all(item["stats"] == [] for item in body["items"])


def test_emote_uses_are_counted_per_streamer(client, pool, server):
    _put(pool["emote"], "7300000000000000011.img")
    _put(pool["emote"], "7300000000000000012.img")
    _comment_with_emotes(server, "stat_owner_c",
                         ["7300000000000000011", "7300000000000000011"])
    _comment_with_emotes(server, "stat_owner_d", ["7300000000000000012"])
    client.post("/api/assets/rescan?kind=emote")

    everyone = client.get("/api/assets?kind=emote&sort=uses&order=desc").json()
    only_c = client.get(
        "/api/assets?kind=emote&streamer=stat_owner_c&sort=uses").json()

    uses = {item["id"]: (item["stats"][0]["value"] if item["stats"] else None)
            for item in everyone["items"]}
    assert uses["7300000000000000011"] == 2
    assert uses["7300000000000000012"] == 1
    # 配信者で絞ると、その配信者が使った絵文字だけになる(母集団が変わる)。
    assert [item["id"] for item in only_c["items"]] == ["7300000000000000011"]
    assert only_c["total"] == 1


def test_avatar_freq_is_counted_per_streamer(client, pool, server):
    storage = server.runtime.storage
    session = storage.create_session("stat_owner_e", 60)
    for at in (1.0, 2.0, 3.0):
        storage.add_event(session, {
            "time": at, "kind": "comment",
            "user": {"user_id": "", "unique_id": "statfreq", "nickname": "よく出る人"},
            "comment": "hi"})
    other = storage.create_session("stat_owner_f", 60)
    storage.add_event(other, {
        "time": 1.0, "kind": "comment",
        "user": {"user_id": "", "unique_id": "statrare", "nickname": "たまに出る人"},
        "comment": "hi"})
    storage.flush()
    _put(pool["avatar"], f"{avatar_key('statfreq')}.img", _PNG)
    _put(pool["avatar"], f"{avatar_key('statrare')}.img", _PNG)
    client.post("/api/assets/rescan?kind=avatar")

    only_e = client.get(
        "/api/assets?kind=avatar&streamer=stat_owner_e&sort=freq").json()

    subs = [item["sub"] for item in only_e["items"]]
    assert subs == ["@statfreq"]
    assert only_e["items"][0]["stats"][0]["key"] == "freq"
    assert only_e["items"][0]["stats"][0]["value"] == 3
    # 別の配信者にしか出ていない人は、この配信者の一覧には出ない。
    assert "@statrare" not in subs


def test_avatar_freq_sort_keeps_people_without_appearances(client, pool, server):
    """出現順を選んだだけで人が消えないこと（絞り込みと並べ替えの区別）。

    eventを1件も持たないusers行は実在する（貢献者Ranking・コラボ相手の身元から入る）ので、
    ここでも同じ形 —— users表にだけ居る人 —— を作る。"""
    storage = server.runtime.storage
    with storage._lock:
        storage._conn.execute(
            "INSERT OR REPLACE INTO users (identity_key, user_id, unique_id, nickname,"
            " avatar, first_seen, last_seen) VALUES (?, '', ?, ?, '', 1.0, 1.0)",
            ("statnoevent", "statnoevent", "出ない人"))
        storage._conn.commit()
    _put(pool["avatar"], f"{avatar_key('statnoevent')}.img", _PNG)
    client.post("/api/assets/rescan?kind=avatar")

    by_freq = client.get("/api/assets?kind=avatar&sort=freq&q=statnoevent").json()

    assert [item["sub"] for item in by_freq["items"]] == ["@statnoevent"]
    # 出現の記録が無いので、その項目ごと落ちる(0で埋めない)。
    assert by_freq["items"][0]["stats"] == []


def test_streamer_filter_is_refused_by_kinds_that_do_not_offer_it(client, pool):
    _put(pool["gift_icon"], "998014.img")

    response = client.get("/api/assets?kind=gift_icon&streamer=stat_owner_a")

    # 黙って無視しない。無視すると、絞ったつもりの人が絞れていないことに気付けない。
    assert response.status_code == 400
    assert "配信者" in response.json()["detail"]


def test_an_unknown_streamer_is_refused_not_treated_as_empty(client, pool):
    _put(pool["emote"], "7300000000000000013.img")

    response = client.get("/api/assets?kind=emote&streamer=no_such_streamer")

    # 綴りを1文字間違えただけの人に「素材が無い」と答えない。
    assert response.status_code == 400


def test_summary_lists_the_streamers_from_the_server(client, pool, server):
    """配信者の一覧はserverが配る。画面に書かせると監視対象が増えた日に古くなる。"""
    _comment_with_emotes(server, "stat_owner_g", ["7300000000000000014"])

    streamers = client.get("/api/assets/summary").json()["streamers"]

    ids = [row["unique_id"] for row in streamers]
    assert "stat_owner_g" in ids
    # labelは他画面と同じrule(最新sessionのowner_nickname、無ければunique_id)。
    assert all(row["label"] for row in streamers)


def test_every_stat_label_is_fixed_wording(client, pool, server):
    """``stats.label`` の語を固定する。

    画面の並替の選択肢は画面側の対応表、tileの項目名はserverの ``stats.label`` という
    二重の出所なので、1文字違うと同じ数字が2つの語で並ぶ。"""
    _put(pool["gift_icon"], "998020.img")
    _put(pool["emote"], "7300000000000000020.img")
    _gift_event(server, "label_owner", 998020, "Gift", count=1, diamonds=1)
    _comment_with_emotes(server, "label_owner", ["7300000000000000020"])
    storage = server.runtime.storage
    session = storage.create_session("label_owner2", 60)
    storage.add_event(session, {
        "time": 1.0, "kind": "comment",
        "user": {"user_id": "", "unique_id": "labeluser", "nickname": "出る人"},
        "comment": "hi"})
    storage.flush()
    _put(pool["avatar"], f"{avatar_key('labeluser')}.img", _PNG)
    client.post("/api/assets/rescan")

    seen = {}
    for kind, query in (("gift_icon", "&q=998020"), ("emote", ""),
                        ("avatar", "&streamer=label_owner2")):
        for item in client.get(f"/api/assets?kind={kind}{query}").json()["items"]:
            for row in item["stats"]:
                seen[row["key"]] = (row["label"], row["unit"])

    assert seen["sends"] == ("送られた個数", "個")
    assert seen["coins"] == ("コイン数", None)
    assert seen["uses"] == ("使われた回数", "回")
    assert seen["freq"] == ("出現回数", "回")


def test_every_refusal_speaks_japanese(client, pool, server):
    """400の理由は日本語で返すこと。

    画面の ``httpError`` は日本語を含むdetailだけをそのまま出し、英語だと汎用文へ落とす。
    英語で返すと、断った理由がuserに一切届かない。"""
    _put(pool["gift_icon"], "998021.img")
    _put(pool["emote"], "7300000000000000021.img")
    _seed_user(server, "jauser", "日本語", _PNG, pool["avatar"])
    refusals = [
        "/api/assets?kind=sticker",
        "/api/assets?kind=emote&limit=0",
        "/api/assets?kind=emote&limit=99999",
        "/api/assets?kind=emote&offset=-1",
        "/api/assets?kind=avatar&sort=size",
        "/api/assets?kind=emote&order=sideways",
        "/api/assets?kind=gift_icon&streamer=jauser",
        "/api/assets?kind=emote&streamer=no_such_streamer",
        "/api/assets/file?kind=gift_icon&id=../etc",
    ]
    for url in refusals:
        response = client.get(url)
        assert response.status_code == 400, url
        detail = response.json()["detail"]
        assert any("\u3040" <= ch <= "\u30ff" or "\u4e00" <= ch <= "\u9fff"
                   for ch in detail), (url, detail)

    posted = client.post("/api/assets/archive",
                         json={"kind": "gift_icon", "ids": ["../etc"]})
    assert posted.status_code == 400
    assert "素材のid" in posted.json()["detail"]
