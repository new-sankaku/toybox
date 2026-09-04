"""画面へdropしたmp4を置き場へ投入する口(``POST /api/highlights/upload``)のtest。

この口はclientが名乗った**file名と配信者名でpathを組み立てる**唯一の場所である。どちらも
外から来る文字列なので、置き場の外へ1 byteでも書けたらそこで終わりになる —— 縛るのは
「置き場の下にしか書かない」「既存のfileを黙って潰さない」「途中で切れたfileを置き場に
残さない」の3つで、残りは投入した物が台帳へ載ることの確認である。

rootは ``runtime.RECORD_DIR`` ではなくこのtestのtmpへ張る。runtimeはimport時に1度だけ
rootを掴むmodule singletonで、全testが**最初のtestのsandbox**を共有するため、そこへ置くと
前のtestが作ったfileを次のtestが自分のものとして数える(tests/test_highlight_api.py と
同じ理由)。
"""

from pathlib import Path

import pytest

from tests.test_server import (  # noqa: F401  (fixtureとして使う)
    client, make_srv_recording, server,
)

UPLOAD_URL = "/api/highlights/upload"

# 本物のmp4は要らない(この口はfileを開かない)。中身が違うことが判る2つを使う。
BODY_A = b"\x00\x01mp4-a" * 64
BODY_B = b"\x00\x02mp4-b" * 64


@pytest.fixture(autouse=True)
def clean_highlights(server):
    """testごとに台帳を空にする。

    ``runtime.storage`` はimport時に1度だけ作られるmodule singletonで、DBはtest間で
    共有される(置き場のtmpだけが毎回変わる)。台帳を消さないと、前のtestが投入した行が
    次のtestの一覧に並び、件数を数えるassertが実行順で通ったり落ちたりする。"""
    storage = server.runtime.storage

    def _wipe() -> None:
        with storage._lock:
            storage._conn.execute("DELETE FROM highlight_segments")
            storage._conn.execute("DELETE FROM highlight_videos")
            storage._conn.commit()

    _wipe()
    yield
    _wipe()


@pytest.fixture
def upload_roots(server, tmp_path):
    """work / final の2つのrootを張り、投入先を返す。

    2 rootにするのは、**投入先が1つであること**を確かめるためである(読む側の
    ``highlight_dirs`` は両rootと旧来の ``LiveHightlite`` も辿る)。work rootだけを張ると、
    どこへ書いても「正規の置き場へ書いた」ように見える。"""
    from tictok.core import layout

    work = tmp_path / "work"
    final = tmp_path / "final"
    work.mkdir(parents=True, exist_ok=True)
    final.mkdir(parents=True, exist_ok=True)
    layout.set_record_roots([work, final])
    layout.set_pool_root(work)
    return {"work": work, "final": final, "layout": layout,
            "dir": work / "streamer_a" / layout.HIGHLIGHT_DIRNAME}


def upload(client, files, streamer="streamer_a"):
    """multipartで投入する。``files`` は ``[(file名, bytes), …]``。"""
    payload = [("files", (name, body, "video/mp4")) for name, body in files]
    return client.post(UPLOAD_URL, data={"streamer": streamer}, files=payload)


def names_in(directory: Path) -> set:
    return {path.name for path in directory.iterdir()} if directory.is_dir() else set()


def ledger(client, streamer="streamer_a") -> dict:
    items = client.get(f"/api/highlights?streamer={streamer}").json()["items"]
    return {item["filename"]: item for item in items}


# ===== 投入先 =====


def test_upload_places_the_file_into_the_canonical_dir_and_lists_it(client, upload_roots):
    """正規の置き場(``<work root>/<配信者>/highlights``)へ置き、**同じ口の中で台帳へ載せる**。

    走査を画面の続きの操作にすると、投入は済んだのに台帳には無い状態が画面から見える。"""
    res = upload(client, [("g65hl0000001.mp4", BODY_A)])
    assert res.status_code == 200
    body = res.json()

    assert body["streamer"] == "streamer_a"
    assert Path(body["directory"]) == upload_roots["dir"]
    assert body["saved"] == 1 and body["rejected"] == 0

    (item,) = body["items"]
    assert item["filename"] == "g65hl0000001.mp4"
    assert item["saved"] is True
    assert item["bytes"] == len(BODY_A)
    assert Path(item["path"]) == upload_roots["dir"] / "g65hl0000001.mp4"

    # 実体は正規の置き場の下にだけ在る。旧来の置き場にも final root にも作らない。
    assert (upload_roots["dir"] / "g65hl0000001.mp4").read_bytes() == BODY_A
    assert not (upload_roots["work"] / "streamer_a" / "LiveHightlite").exists()
    assert not (upload_roots["final"] / "streamer_a").exists()

    # 走査まで済んでいる。画面は「載った」と言い切れる。
    assert body["scan"]["added"] == 1
    row = ledger(client)["g65hl0000001.mp4"]
    assert row["root_key"] == "work"
    assert row["source_dir"] == "streamer_a/highlights"
    assert row["bytes"] == len(BODY_A)
    assert row["status"] == "new"


def test_upload_requires_a_streamer(client, upload_roots):
    """配信者が決まらないまま受けない。置き場が配信者folderの下だからである。

    適当な場所へ置くと、そのhighlightは別人の週のgiftと突き合わせられて当たらないだけで、
    失敗として見えない。"""
    res = upload(client, [("a.mp4", BODY_A)], streamer="")
    assert res.status_code == 400
    assert "配信者" in res.json()["detail"]
    # 置き場は1つも作らない(空のfolderだけが増えることが無い)。
    assert not (upload_roots["work"] / "streamer_a").exists()

    # fileを1つも付けない投入も断る。0件を成功として返すと、画面は投入した気になる。
    assert client.post(UPLOAD_URL, data={"streamer": "streamer_a"}).status_code == 400


# ===== 断るのは1件だけ =====


def test_a_rejected_file_does_not_take_the_others_down(client, upload_roots):
    """扱えない拡張子はその1件だけを理由付きで断り、**他のfileは通す**。

    まとめてdropしたときに1本のせいで全部落ちると、利用者は駄目な1本を自分で見つけて
    取り除くまで何も投入できない(どれが駄目だったかは画面から見えない)。"""
    res = upload(client, [("a.mp4", BODY_A), ("thumb.jpg", b"jpeg"),
                          ("b.mp4", BODY_B)])
    assert res.status_code == 200
    body = res.json()
    assert body["saved"] == 2 and body["rejected"] == 1

    rows = {item["filename"]: item for item in body["items"]}
    assert rows["a.mp4"]["saved"] is True and rows["b.mp4"]["saved"] is True
    bad = rows["thumb.jpg"]
    assert bad["saved"] is False
    # 黙って捨てない。断った理由を1件ずつ名乗る。
    assert ".mp4" in bad["reason"]
    assert bad["path"] is None and bad["bytes"] is None

    assert names_in(upload_roots["dir"]) == {"a.mp4", "b.mp4"}
    assert set(ledger(client)) == {"a.mp4", "b.mp4"}


def test_an_empty_file_is_rejected(client, upload_roots):
    """0 bytesのfileは断る。据えると走査が「新しいhighlight」として台帳へ載せ、
    照合が開けないfileを掴む。"""
    body = upload(client, [("empty.mp4", b""), ("a.mp4", BODY_A)]).json()
    rows = {item["filename"]: item for item in body["items"]}
    assert rows["empty.mp4"]["saved"] is False
    assert "空" in rows["empty.mp4"]["reason"]
    assert names_in(upload_roots["dir"]) == {"a.mp4"}


# ===== file名の無害化 =====


@pytest.mark.parametrize("name", [
    "../evil.mp4",
    "..\\evil.mp4",
    "../../evil.mp4",
    "sub/evil.mp4",
    "sub\\evil.mp4",
    "C:evil.mp4",
    "C:/windows/evil.mp4",
    "/etc/evil.mp4",
    "..",
])
def test_a_crafted_name_cannot_write_outside_the_placement(client, upload_roots, name):
    """置き場の外を指すfile名は書かずに断る。**名前を黙って削らない。**

    削って据えると、利用者の知らない名前のfileが置き場に増える(しかも断られたことも
    判らない)。理由を名乗る方が早く直せる。"""
    body = upload(client, [(name, BODY_A)]).json()
    (item,) = body["items"]
    assert item["saved"] is False
    assert "置き場の外" in item["reason"] or ".mp4" in item["reason"]

    # 置き場の外(work root直下・親・final root)に何も生まれていないこと。
    assert names_in(upload_roots["dir"]) == set()
    assert {p.name for p in upload_roots["work"].iterdir()} <= {"streamer_a"}
    assert "evil.mp4" not in {p.name for p in upload_roots["work"].parent.rglob("*")}
    assert ledger(client) == {}


@pytest.mark.parametrize("streamer", ["../evil", "streamer_a/sub", r"streamer_a\sub", ".."])
def test_a_crafted_streamer_cannot_write_outside_the_root(client, upload_roots, streamer):
    """**配信者名もclient由来である。** 置き場のpathの一部になるので、file名と同じ厳しさで
    見る —— 区切りを含む名前は、rootの中とはいえ走査が二度と辿らない深さへfileを積む。"""
    res = upload(client, [("a.mp4", BODY_A)], streamer=streamer)
    assert res.status_code == 400
    assert "配信者名" in res.json()["detail"]
    assert "evil" not in {p.name for p in upload_roots["work"].parent.rglob("*")}
    assert not (upload_roots["work"] / "streamer_a").exists()


# ===== 同名 =====


def test_same_name_same_bytes_is_not_replaced(client, upload_roots):
    """中身が同じなら置き換えない。**同じ物なので台帳の行は1文字も変わらない。**

    置き換えて得る物が無く、投入の途中で切れた側で無事な原本を潰す目だけが残る。
    置き換えなかったことは ``reason`` が名乗る(黙って捨てたのではない)。"""
    assert upload(client, [("a.mp4", BODY_A)]).json()["saved"] == 1
    body = upload(client, [("a.mp4", BODY_A)]).json()

    (item,) = body["items"]
    assert item["saved"] is False
    assert "同じ内容" in item["reason"]
    assert Path(item["path"]) == upload_roots["dir"] / "a.mp4"
    assert body["saved"] == 0
    # 1本も置いていないので走査もしない(走ったという名乗りだけを増やさない)。
    assert body["scan"] is None

    assert names_in(upload_roots["dir"]) == {"a.mp4"}
    assert (upload_roots["dir"] / "a.mp4").read_bytes() == BODY_A
    assert set(ledger(client)) == {"a.mp4"}


def test_same_name_different_bytes_gets_a_new_name(client, upload_roots):
    """中身が違う同名は別名で受ける。**既存のfileは触らない。**

    409で断ると、まとめてdropした中の1本だけが落ちるうえ、断られたfileは利用者の手元に
    戻らない(browserのdropはその場でfileを渡すだけで、拾い直す道が無い)。台帳はfile名で
    行を作るので、2本並べれば人がどちらを使うか選べる。"""
    upload(client, [("a.mp4", BODY_A)])
    body = upload(client, [("a.mp4", BODY_B)]).json()

    (item,) = body["items"]
    assert item["saved"] is True
    assert Path(item["path"]).name == "a_2.mp4"
    # どちらを選んだかを応答が名乗る。
    assert "a_2.mp4" in item["reason"]

    assert (upload_roots["dir"] / "a.mp4").read_bytes() == BODY_A
    assert (upload_roots["dir"] / "a_2.mp4").read_bytes() == BODY_B
    assert set(ledger(client)) == {"a.mp4", "a_2.mp4"}


# ===== 半端なfileを残さない =====


def test_nothing_half_written_is_left_in_the_placement(client, upload_roots, monkeypatch):
    """書き込みが途中で落ちても、置き場に半端なfileが残らない。

    走査は置き場に在る ``.mp4`` を無条件で台帳へ載せる。途中で切れたfileが ``.mp4`` の名前で
    残ると、それが「新しいhighlight」として並び、照合に回されて失敗する。書き込み中の名前
    (``UPLOAD_TEMP_PREFIX``)は走査の対象外で、据えるのは ``os.replace`` の1手である。"""
    from tictok.api.routes import highlights

    real_store = highlights._store_upload

    def _boom(base, name, temp):
        # 据える直前に落ちた回。一時fileはこの時点で置き場に在る。
        raise OSError("disk full")

    monkeypatch.setattr(highlights, "_store_upload", _boom)
    body = upload(client, [("a.mp4", BODY_A), ("b.mp4", BODY_B)]).json()
    assert body["saved"] == 0 and body["rejected"] == 2
    # 落ちた理由は1件ずつ名乗る(まとめて「失敗」にしない)。
    assert all("disk full" in item["reason"] for item in body["items"])
    # 半端なfileも一時fileも残っていない。
    assert names_in(upload_roots["dir"]) == set()
    assert ledger(client) == {}

    # 元へ戻せば同じ名前で投入できる(片付けが名前を塞いでいない)。
    monkeypatch.setattr(highlights, "_store_upload", real_store)
    assert upload(client, [("a.mp4", BODY_A)]).json()["saved"] == 1
    assert names_in(upload_roots["dir"]) == {"a.mp4"}


# ===== 置き場の下のfolderへ投入する =====
#
# 素材は週ごとのfolder(``20260829-20260905``)へ仕分けられている。投入した後に人が手で
# fileを動かしていたが、一覧には既にその棚が出ているので、棚へ落とせれば移す手間が丸ごと
# 消える。**受けるのは一覧が名乗った ``root_key`` / ``source_dir`` だけ**で、pathは受けない
# —— pathを受ければ、そこから任意のdirへ書ける口になる。


def upload_into(client, folder, files, streamer="streamer_a", root_key="work"):
    """folderを指定して投入する。``folder`` は一覧が名乗る ``source_dir``。"""
    payload = [("files", (name, body, "video/mp4")) for name, body in files]
    return client.post(UPLOAD_URL,
                       data={"streamer": streamer, "root_key": root_key,
                             "source_dir": folder},
                       files=payload)


def test_upload_can_target_a_folder_under_the_placement(client, upload_roots):
    """一覧が名乗ったfolderへ入り、そこで走査されて台帳に載る。"""
    week = upload_roots["dir"] / "20260829-20260905"
    week.mkdir(parents=True, exist_ok=True)
    layout = upload_roots["layout"]

    res = upload_into(client, layout.source_dir_of(week, "work"),
                      [("g65hl0000001.mp4", BODY_A)])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["saved"] == 1
    assert Path(body["directory"]) == week
    # 置き場の直下ではなく、指したfolderの中に在る。
    assert names_in(week) == {"g65hl0000001.mp4"}
    assert names_in(upload_roots["dir"]) == {"20260829-20260905"}
    # 走査はsubfolderまで辿るので、そのまま台帳へ載る。
    assert set(ledger(client)) == {"g65hl0000001.mp4"}


def test_upload_refuses_a_folder_outside_the_streamers_placement(client, upload_roots):
    """**置き場の外は指せない。** 指せると別人のfolderへ投入できる口になり、そのハイライトは
    「照合で当たらないだけ」の形で静かに増える(後から気付く手立てが無い)。"""
    other = upload_roots["work"] / "someone-else" / "highlights"
    other.mkdir(parents=True, exist_ok=True)
    layout = upload_roots["layout"]

    res = upload_into(client, layout.source_dir_of(other, "work"),
                      [("a.mp4", BODY_A)])
    assert res.status_code == 400
    assert "置き場の外" in res.json()["detail"]
    assert names_in(other) == set()

    # ``..`` で抜けようとしても同じ。名前の見た目ではなく、解決したpathで照合している。
    res = upload_into(client, "streamer_a/highlights/../../someone-else/highlights",
                      [("a.mp4", BODY_A)])
    assert res.status_code == 400
    assert names_in(other) == set()


def test_upload_names_a_folder_that_is_gone(client, upload_roots):
    """消えたfolderは404で名乗る。**黙って置き場の直下へ落とさない** —— 週で仕分けたはずの
    素材が根に散らばると、どこへ入ったのかを人が追えない。"""
    res = upload_into(client, "streamer_a/highlights/20260829-20260905", [("a.mp4", BODY_A)])
    assert res.status_code == 404
    assert "20260829-20260905" in res.json()["detail"]


# ===== 週のfolderを作る =====


FOLDER_URL = "/api/highlights/folders"


def week_names():
    from tictok.api.routes.highlights import WEEK_FOLDER_CHOICES
    from tictok.store.streamers import week_folder_choices

    return [item["name"] for item in week_folder_choices(WEEK_FOLDER_CHOICES)]


def test_create_week_folder_makes_it_under_the_upload_dir(client, upload_roots):
    """作る場所は投入先の直下に固定する。読む側が複数の置き場を辿るのに対し、**作る側の
    場所が1つでなければ人が自分の作ったfolderへ戻れない**(投入と同じ約束)。"""
    name = week_names()[0]
    res = client.post(FOLDER_URL, json={"streamer": "streamer_a", "name": name})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["created"] is True
    assert Path(body["path"]) == upload_roots["dir"] / name
    assert (upload_roots["dir"] / name).is_dir()
    # 一覧はそのfolderを棚として名乗る。画面はここの綴りでdropの投入先を指す。
    folders = client.get("/api/highlights?streamer=streamer_a").json()["folders"]
    assert body["source_dir"] in {folder["source_dir"] for folder in folders}


def test_create_week_folder_is_idempotent(client, upload_roots):
    """既に在るなら作らずに ``created: false``。409で断ると、押しても何も起きないbuttonに
    見える —— 利用者の望む結末(そのfolderが在ること)は既に満たされている。"""
    name = week_names()[0]
    assert client.post(FOLDER_URL, json={"streamer": "streamer_a", "name": name}).status_code == 200
    res = client.post(FOLDER_URL, json={"streamer": "streamer_a", "name": name})
    assert res.status_code == 200
    assert res.json()["created"] is False


def test_create_week_folder_takes_only_names_the_server_offers(client, upload_roots):
    """**任意の名前でdirを作れる口にしない。** 週の境目(土曜7時)を知らない綴りが混ざると、
    対象の週と1日ずれた名前のfolderが静かに増えるうえ、pathの区切りを名乗られれば置き場の
    外にも作れる。"""
    for bad in ["20260830-20260906", "../someone-else", "適当なfolder", ""]:
        res = client.post(FOLDER_URL, json={"streamer": "streamer_a", "name": bad})
        assert res.status_code == 400, bad
        assert "週のfolder" in res.json()["detail"]
    assert names_in(upload_roots["dir"]) == set()


def test_week_folder_choices_match_the_week_used_by_the_screens(client):
    """候補の名前は**土曜7時始まりの週**の窓そのものである。ランキングの週(月曜0時)で
    切ると、対象の週(検証・出力の面)と1日ずれたfolderが並ぶ。"""
    from datetime import datetime

    from tictok.store.streamers import week_folder_choices

    body = client.get("/api/highlights").json()
    names = [item["name"] for item in body["week_folders"]]
    assert names == [item["name"] for item in week_folder_choices(len(names))]
    for item in body["week_folders"]:
        start, end = item["name"].split("-")
        # 端は土曜どうしで、ちょうど7日。
        first = datetime.strptime(start, "%Y%m%d")
        last = datetime.strptime(end, "%Y%m%d")
        assert first.weekday() == 5 and last.weekday() == 5
        assert (last - first).days == 7
        # 窓の名乗りは時刻付き(日付だけでは境目が朝7時だと読めない)。
        assert "07:00" in item["label"]
    # 受け取れる拡張子もServerが名乗る(画面が綴りを持たない)。
    assert body["extensions"] == [".mp4"]
