"""書き出した1本を**通しで確かめる**ための章(繋いだ窓の並び)のtest。

なぜ要るのか
------------
1本のmp4は3〜8個の窓を繋いだ物で、素材が複数のハイライトに跨ることもある。繋ぎ目は
**mp4の中に印が無い**(containerのchapterは書いていない)ので、fileを再生しただけでは
「いま何本目の何のgiftを観ているか」が判らない。窓の並びが残っているのは素性のJSONだけで
ある。

一覧(``/api/highlights/exports``)は素性を読まない —— 件数ぶんのfileを開くことになるうえ、
名前と素性が食い違ったfileだけが一覧から消える(消えた理由は画面から見えない)。だから
**人が1本を選んだときに、その1本ぶんだけ**読む口を分けてある。

確かめること: 窓ごとの名乗り(gift名・額)が素性に残ること、開始位置が累計で出ること、
素性の無いfileでも404にならないこと、file名で置き場の外を指せないこと。
"""
import json

import pytest

from tests.test_server import client, server  # noqa: F401  (fixtureとして使う)
from tests.test_highlight_api import (  # noqa: F401  (fixtureとして使う)
    clean_highlights, highlight_roots,
)
from tests.test_highlight_export_provenance import STREAMER, clip_roots  # noqa: F401

from tictok.core import layout
from tictok.media import highlight_export as hx


def _cut(start, end, *, gifts, highlight_id=1, diamonds=0):
    return {"src": f"C:/hl{highlight_id}.mp4", "start": start, "end": end,
            "seconds": round(end - start, 3), "lead_seconds": 0.0,
            "highlight_id": highlight_id, "segment_ids": [10 + highlight_id],
            "diamonds": diamonds, "gifts": gifts}


def test_窓の名乗りが素性に残る():
    """章の帯はこれだけを読む。**event idから名前を引き直させない** —— 台帳へ問い合わせ
    ないと章が作れない形にすると、素材を消した後のfileでは章が空になる。"""
    summary = hx._cut_summary(_cut(10.0, 16.0, diamonds=6000, gifts=[
        {"gift_event_id": 111, "gift_name": "Guardian's Pledge", "diamonds": 4999,
         "user_nickname": "よい"},
        {"gift_event_id": 112, "gift_name": "Guardian's Pledge", "diamonds": 4999,
         "user_nickname": "よい"},
    ]))
    assert summary["gift_event_ids"] == [111, 112]
    assert [g["gift_name"] for g in summary["gifts"]] == \
        ["Guardian's Pledge", "Guardian's Pledge"]
    assert summary["gifts"][0]["user_nickname"] == "よい"
    assert summary["seconds"] == 6.0


def _write_output(directory, name, cuts, *, verified=True):
    directory.mkdir(parents=True, exist_ok=True)
    out = directory / name
    out.write_bytes(b"\x00" * 8)
    record = {"schema": hx.PROVENANCE_SCHEMA, "verified": verified,
              "week": "2026-08-29", "gifter": {"nickname": "あきと"},
              "segments": [], "cuts": [hx._cut_summary(cut) for cut in cuts]}
    hx.provenance_path(out).write_text(
        json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return out


def test_章の開始位置は尺の累計で出る(client, clip_roots):
    """素性が持つのは窓ごとの尺だけである。**実測(``output.measured``)で伸縮を案分しない**
    —— 全体の差を各章へ配ると、当たっている章の位置まで動かすことになる。"""
    directory = layout.merged_highlight_dir(STREAMER)
    _write_output(directory, "260829-260905_coin6000_あきと_story.mp4", [
        _cut(10.0, 16.0, diamonds=6000, highlight_id=1,
             gifts=[{"gift_event_id": 111, "gift_name": "Goal Highlight",
                     "diamonds": 6000, "user_nickname": "あきと"}]),
        _cut(2.0, 6.5, diamonds=999, highlight_id=2,
             gifts=[{"gift_event_id": 222, "gift_name": "Travel with You",
                     "diamonds": 999, "user_nickname": "あきと"}]),
    ])
    reply = client.get("/api/highlights/exports/provenance",
                       params={"streamer": STREAMER,
                               "filename": "260829-260905_coin6000_あきと_story.mp4"})
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["provenance"] is True
    assert body["nickname"] == "あきと" and body["verified"] is True
    assert [cut["at"] for cut in body["cuts"]] == [0.0, 6.0]
    assert [cut["seconds"] for cut in body["cuts"]] == [6.0, 4.5]
    assert body["seconds"] == 10.5
    # 素材は窓ごとに違う。**画面は跨いで繋ぐ**ので、どのハイライトの物かが要る。
    assert [cut["highlight_id"] for cut in body["cuts"]] == [1, 2]
    assert [cut["gifts"][0]["gift_name"] for cut in body["cuts"]] == \
        ["Goal Highlight", "Travel with You"]
    # 素材の実pathは渡さない(file名だけ)。client側から任意のdirを名乗る足掛かりにしない。
    assert [cut["src"] for cut in body["cuts"]] == ["hl1.mp4", "hl2.mp4"]


def test_素性の無いfileでも404にしない(client, clip_roots):
    """検証用の書き出しでも素材が消えた後でもmp4は再生できる。**章が出せないだけ**である。"""
    directory = layout.merged_highlight_dir(STREAMER)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "bare_story.mp4").write_bytes(b"\x00" * 8)
    reply = client.get("/api/highlights/exports/provenance",
                       params={"streamer": STREAMER, "filename": "bare_story.mp4"})
    assert reply.status_code == 200
    assert reply.json()["provenance"] is False
    assert reply.json()["cuts"] == []


def test_壊れた素性は黙って無いことにしない(client, clip_roots):
    """**mp4は在るのに出所が読めない**という状態そのものが、この記録を作る理由になった
    事故である。「素性なし」と同じ扱いにすると、壊れていることに誰も気付かない。"""
    directory = layout.merged_highlight_dir(STREAMER)
    directory.mkdir(parents=True, exist_ok=True)
    out = directory / "broken_story.mp4"
    out.write_bytes(b"\x00" * 8)
    hx.provenance_path(out).write_text("{ちぎれた", encoding="utf-8")
    reply = client.get("/api/highlights/exports/provenance",
                       params={"streamer": STREAMER, "filename": "broken_story.mp4"})
    assert reply.status_code == 500
    assert "素性" in reply.json()["detail"]


def test_実在しないfileは404(client, clip_roots):
    reply = client.get("/api/highlights/exports/provenance",
                       params={"streamer": STREAMER, "filename": "nope_story.mp4"})
    assert reply.status_code == 404


@pytest.mark.parametrize("name", ["../x.mp4", "sub/x.mp4", "sub\\x.mp4",
                                  "C:/windows/x.mp4"])
def test_置き場の外は指せない(client, clip_roots, name):
    """file名は置き場の中の1つを指す名前である。区切りを含む値は400で断る ——
    存在確認だけに任せると、置き場の外の実在するfileが読めてしまう。"""
    reply = client.get("/api/highlights/exports/provenance",
                       params={"streamer": STREAMER, "filename": name})
    assert reply.status_code == 400


def test_配信者とfile名の両方が要る(client):
    assert client.get("/api/highlights/exports/provenance").status_code == 400
    assert client.get("/api/highlights/exports/provenance",
                      params={"streamer": STREAMER}).status_code == 400
