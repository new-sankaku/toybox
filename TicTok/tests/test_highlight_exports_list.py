"""書き出し済みのmp4を並べる口(``GET /api/highlights/exports``)のtest。

出力の面は「何が出来るか」(下見)と「作れ」(投入)しか持たず、**出来上がった1本を人が観る
手立てが無かった**。成果物はDBに行を持たず、台帳はfile systemそのものなので、この口が
壊れると成果物はどの画面からも辿れないまま置き場に溜まる。

rootは ``runtime.RECORD_DIR`` ではなくこのtestのtmpへ張る。runtimeはimport時に1度だけ
rootを掴むmodule singletonで、全testが**最初のtestのsandbox**を共有するため、そこへ置くと
前のtestが作ったfileを次のtestが自分のものとして数える(tests/test_highlight_api.py と
同じ理由)。この口はDBを読まないので、台帳を空にするfixtureは要らない。
"""

from pathlib import Path
from urllib.parse import quote

import pytest

from tests.test_server import (  # noqa: F401  (fixtureとして使う)
    client, server,
)

# 実物の名前をそのまま使う。先頭の2桁がその週の順位で、名前順がそのまま💎の高い順になる。
FIRST = "01_260829-260905_coin19380_視聴者A_story.mp4"
SECOND = "02_260829-260905_coin5000_よい_story.mp4"
# 順位のprefixを持たない古い名前。読めるが ``position`` は持たない。
OLD = "260822-260829_coin2088_someone_story.mp4"
# 検証用の出力。``_story`` で終わらないので素性は読めない(推測せず空のまま並べる)。
UNVERIFIED = "03_260829-260905_coin1200_ぽん_story.検証用.mp4"

WEEK = "260829-260905"


@pytest.fixture
def export_dir(server, tmp_path):
    """書き出しの置き場を張る。``(dir, 置く関数)`` を返す。

    work / final の2つを張るのは、置き場が work root 固定であることと、URLが名乗る
    ``root=work`` がその root を指すことを、1 rootの構成では取り違えられないためである。"""
    from tictok.core import layout

    work = tmp_path / "work"
    final = tmp_path / "final"
    work.mkdir(parents=True, exist_ok=True)
    final.mkdir(parents=True, exist_ok=True)
    layout.set_record_roots([work, final])
    layout.set_pool_root(work)

    directory = layout.merged_highlight_dir("streamer_a")

    def _place(name: str, size: int = 32) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        path.write_bytes(b"\x00" * size)
        return path

    return directory, _place


def _items(client, query: str = "streamer=streamer_a") -> list:
    body = client.get(f"/api/highlights/exports?{query}")
    assert body.status_code == 200, body.text
    return body.json()["items"]


def test_missing_directory_is_empty_not_a_404(client, export_dir):
    """まだ1本も書き出していないだけで、失敗ではない。

    404にすると画面は「置き場が無い」と「serverが壊れた」を言い分けられない。``exists`` で
    名乗れば、0件と置き場の不在も区別できる。"""
    directory, _place = export_dir
    assert not directory.is_dir()

    body = client.get("/api/highlights/exports?streamer=streamer_a")
    assert body.status_code == 200
    assert body.json() == {"streamer": "streamer_a", "week": "", "items": [],
                           "directory": str(directory), "exists": False}


def test_exports_are_listed_in_file_name_order(client, export_dir):
    """並びはfile名順。file名の先頭にその週の順位が入るので、名前順が💎の高い順になる。

    mtime順にすると、後から書き直した1本だけが先頭へ来て順位が崩れる。"""
    _directory, place = export_dir
    # 置く順序は名前順とわざと逆にする(mtime順で並べていたらここで気付く)。
    place(OLD)
    place(SECOND)
    place(FIRST)

    assert [item["filename"] for item in _items(client)] == [FIRST, SECOND, OLD]


def test_the_url_points_at_the_clip_file_endpoint_and_serves_the_file(client, export_dir):
    """``url`` は既に在る配信の口(``/api/clips/file``)を指し、そのまま配信できること。

    同じ物を配る口を2つ持つと、片方だけがroot外を弾く条件を直した日に、もう片方から
    任意のdirを名乗れる。配信者名にも表示名にも日本語が入るので符号化も要る。"""
    _directory, place = export_dir
    path = place(FIRST, 64)

    item = _items(client)[0]
    assert item["url"] == ("/api/clips/file?root=work"
                           f"&name={quote(f'streamer_a/LiveHightlite_マージ済み/{FIRST}')}")

    played = client.get(item["url"])
    assert played.status_code == 200, played.text
    assert played.headers["content-type"] == "video/mp4"
    assert played.content == path.read_bytes()
    # 実体の素性も名乗る(画面が「まだ書き出していない」と「在るのに再生できない」を
    # 言い分けるための材料)。
    assert item["bytes"] == 64 and item["modified_at"] > 0
    assert item["path"] == str(path)


def test_the_provenance_json_never_appears_as_a_row(client, export_dir):
    """並ぶのはmp4だけ。素性のJSONは隣に在るだけの別fileで、成果物ではない。

    在るかどうかは ``provenance`` が名乗る —— 無い1本は「誰のどのgiftから出来たか」を
    辿れないので、画面がその旨を出せる必要がある。"""
    _directory, place = export_dir
    place(FIRST)
    place(f"{FIRST}.json", 8)
    place(SECOND)

    items = _items(client)
    assert [item["filename"] for item in items] == [FIRST, SECOND]
    assert items[0]["provenance"] is True
    assert items[1]["provenance"] is False


def test_the_name_carries_the_position_and_the_coin(client, export_dir):
    """素性はfile名から読み戻す(``clipper.parse_clip_name``)。一覧は自分で分解しない。

    読めない名前(検証用の出力)は推測せず空のまま並べる —— 順位もコインも持たない1本を
    それらしい値で埋めると、画面はその1本を製品の出力と同じ顔で並べる。"""
    _directory, place = export_dir
    place(FIRST)
    place(OLD)
    place(UNVERIFIED)

    items = {item["filename"]: item for item in _items(client)}
    assert items[FIRST]["position"] == 1
    assert items[FIRST]["coin"] == 19380
    assert items[FIRST]["week"] == WEEK
    assert items[FIRST]["nickname"] == "視聴者A"
    assert items[FIRST]["verified"] is True

    # prefixを持たない古い名前。順位だけが無く、他は読める。
    assert items[OLD]["position"] is None
    assert items[OLD]["coin"] == 2088 and items[OLD]["week"] == "260822-260829"

    # 検証用の出力は名前の印で判る(素性のJSONはmp4を1本運べば付いて行かない)。
    assert items[UNVERIFIED]["verified"] is False
    assert items[UNVERIFIED]["position"] is None
    assert items[UNVERIFIED]["coin"] is None
    assert items[UNVERIFIED]["week"] == "" and items[UNVERIFIED]["nickname"] == ""


def test_week_narrows_the_listing_by_the_name(client, export_dir):
    """``week`` はfile名の週で絞る。素性のJSONは開かない(件数ぶんのfileを読むことになる)。"""
    _directory, place = export_dir
    place(FIRST)
    place(SECOND)
    place(OLD)

    assert [item["filename"] for item in _items(client, f"streamer=streamer_a&week={WEEK}")] \
        == [FIRST, SECOND]
    body = client.get(f"/api/highlights/exports?streamer=streamer_a&week={WEEK}").json()
    assert body["week"] == WEEK and body["exists"] is True

    # 1本も無い週でも失敗ではない(置き場は在る)。
    empty = client.get("/api/highlights/exports?streamer=streamer_a&week=250101-250108").json()
    assert empty["items"] == [] and empty["exists"] is True


def test_exports_needs_a_streamer_and_is_not_read_as_an_id(client, export_dir):
    """``exports`` が ``{highlight_id}`` として解釈されていたら422になる。

    path の並びに意味がある(先に宣言したrouteから照合される)ので、順序が入れ替わった
    ことをこのtestが気付く。置き場は配信者ごとなので、配信者の指定は必須である。"""
    assert client.get("/api/highlights/exports").status_code == 400
    assert client.get("/api/highlights/exports?streamer=  ").status_code == 400


def test_other_files_in_the_directory_are_not_listed(client, export_dir):
    """mp4以外(字幕・logの残骸)は並べない。一覧は「観られる成果物」だけを名乗る。"""
    _directory, place = export_dir
    place(FIRST)
    place("01_260829-260905_coin19380_視聴者A_story.srt", 4)
    place("notes.txt", 4)

    assert [item["filename"] for item in _items(client)] == [FIRST]
