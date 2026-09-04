"""書き出しを**実際にffmpegで通す**test。出来上がったmp4とその素性を実物で確かめる。

計画の段(``tests/test_highlight_export.py``)と素性の照合(``tests/test_highlight_export_
provenance.py``)はffmpegを起こさない。そこまでで「誰の何がどの名前で出るか」は確かめられる
が、**実際にfileが出来ることと、その隣に素性が残ること**は素材を通さないと判らない。

事故のとき7本のmp4は「素性の無いfile」として残った。ここが守るのはその一点である ——
製品の経路を通れば、mp4と素性は必ず対で出る。
"""
import asyncio
import json
import shutil
import subprocess

import pytest

from tictok.media import highlight_export as hx

from tests.test_server import (  # noqa: F401  (fixtureとして使う)
    client, make_srv_recording, server,
)
from tests.test_highlight_api import (  # noqa: F401  (fixtureとして使う)
    clean_highlights, highlight_roots,
)
from tests.test_highlight_export_provenance import _user, STREAMER

pytestmark = [
    pytest.mark.requires_ffmpeg,
    pytest.mark.slow,
    pytest.mark.skipif(
        not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
        reason="needs a real ffmpeg/ffprobe on PATH",
    ),
]

# 素材の作り。実物のhighlightは 720x1280 / 30fps / 最長61秒だが、ここで確かめたいのは
# 「経路が通ること」なので小さく作る。**音声は必ず入れる** —— 出来上がりの検証
# (``_verify_output``)は映像と音声の両方のpacketを測るので、無音のmp4では経路の後半が
# そもそも走らない。
HIGHLIGHT_SECONDS = 12


def _make_highlight(path) -> None:
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", f"testsrc2=size=160x288:rate=30:duration={HIGHLIGHT_SECONDS}",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={HIGHLIGHT_SECONDS}",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
         "-profile:v", "high", "-g", "30", "-c:a", "aac", "-ar", "44100", "-ac", "2",
         "-shortest", str(path)],
        check=True, capture_output=True)


def test_書き出すとmp4と素性が対で出来る(client, server, highlight_roots,
                                        make_srv_recording, gift_builder):
    """製品の経路(``export_highlights``)をそのまま通す。

    確かめるのは3つ。(1) gifterごとに1本のmp4が実在して尺を持つこと、(2) 隣に素性のJSONが
    在り、gift演出1件ずつがDBの鍵(highlight/segment/gift event/録画)を名乗ること、(3) その素性が
    ``verified: true`` であること —— 製品の口から出たfileは必ずDBと突き合わせ済みである。"""
    storage = server.runtime.storage
    session_id, recording_id, _mp4 = make_srv_recording(unique_id=STREAMER, ts_segments=4)
    started = storage.get_recording(recording_id)["started_at"]
    storage.add_event(session_id, gift_builder(
        "Goal Highlight", diamonds=6000, at=started + 100.0,
        user=_user("視聴者A", user_id="7001", unique_id="viewer_a")))
    storage.add_event(session_id, gift_builder(
        "Fireworks", diamonds=1088, at=started + 200.0,
        user=_user("視聴者A", user_id="7001", unique_id="viewer_a")))
    storage.flush()
    gifts = storage.highlight_gift_events(session_id, started, started + 1000.0)

    path = highlight_roots["place"](highlight_roots["work"], STREAMER, "highlights",
                                    "a.mp4")
    _make_highlight(path)
    client.post("/api/highlights/scan", json={"streamer": STREAMER})
    highlight_id = client.get(
        f"/api/highlights?streamer={STREAMER}").json()["items"][0]["id"]
    storage.save_highlight_match(highlight_id, {
        "seconds": float(HIGHLIGHT_SECONDS), "pool": 1, "pool_hours": 1.0, "elapsed": 1.0,
        "scope": {"scope": "gift", "days": 14.0},
        "segments": [
            {"index": index, "start": 4.0 * index, "end": 4.0 * index + 3.0,
             "recording_id": recording_id, "media_start": 100.0 + 100.0 * index,
             "votes": 900, "ratio": 220.0, "corr": 0.98, "confidence": "high",
             "effect": [],
             # 照合側は **gifts(複数)** を返す。1つのgift演出に複数のgiftが乗るためで、
             # 高額な1件だけを持つ形へ戻すと画面に映っている演出の主が落ちる。
             "gifts": [{**gift, "event_id": gift["gift_event_id"],
                        "media_time": 100.0 + 100.0 * index,
                        "inside": True, "primary": True, "has_effect": False}]}
            for index, gift in enumerate(gifts)],
    })

    result = asyncio.run(hx.export_highlights(storage, [highlight_id]))
    assert result["verified"] is True
    assert len(result["files"]) == 1
    entry = result["files"][0]
    out = hx.Path(entry["path"])
    assert out.is_file() and out.stat().st_size > 0
    assert hx.UNVERIFIED_MARK not in out.name and out.name.endswith("_story.mp4")
    # 2件のgift演出×3秒。実測は映像・音声の両方が届いていることまで見た値である。
    assert entry["parts"] == 2
    assert entry["measured"]["video_seconds"] == pytest.approx(6.0, abs=0.3)
    assert entry["measured"]["audio_seconds"] == pytest.approx(6.0, abs=0.3)

    side = hx.provenance_path(out)
    assert side.is_file()
    record = json.loads(side.read_text(encoding="utf-8"))
    assert record["verified"] is True and record["schema"] == hx.PROVENANCE_SCHEMA
    assert record["gifter"]["nickname"] == "視聴者A"
    assert record["output"]["bytes"] == out.stat().st_size
    assert [s["gift_name"] for s in record["segments"]] == ["Goal Highlight", "Fireworks"]
    assert [s["gift_event_id"] for s in record["segments"]] == [
        g["gift_event_id"] for g in gifts]
    assert all(s["highlight_id"] == highlight_id and s["segment_id"]
               and s["recording_id"] == recording_id for s in record["segments"])

    # **窓ごとの実測の尺が素性に在ること。** 出力tabは書き出したfileの章(繋ぎ目)を、この
    # 尺の累計から作る —— NULL のままだと章が1つも出せず、書き出した1本を通しで確かめる
    # 道がそこで途切れる。計画の段では判らない値なので、切り終えてから書き直している。
    assert len(record["cuts"]) == 2
    assert all(cut["seconds"] and cut["seconds"] > 0 for cut in record["cuts"])
    assert sum(cut["seconds"] for cut in record["cuts"]) == pytest.approx(
        record["output"]["measured"]["video_seconds"], abs=0.3)

    # 後から確かめる道(``scripts/verify_highlight_export.py``)が、この1本を通すこと。
    # **素性を信用せずにDBへ引き直す**judgeなので、通れば中身とDBが一致している。
    import scripts.verify_highlight_export as verify

    checked = verify._check_file(storage._conn, out)
    assert checked["ok"], checked["problems"]
    assert checked["owner"] == "視聴者A" and checked["segments"] == 2
    # 素性が無いfileは「出所を辿れない」と言うこと —— 事故で残った7本がこの状態だった。
    side.unlink()
    assert not verify._check_file(storage._conn, out)["ok"]


def test_検証用の経路はそれと判る名前で出る(client, server, highlight_roots,
                                            make_srv_recording, gift_builder):
    """``verification_rows`` を通ったfileは、名前にも素性にも印が残ること。

    **この道はHTTPからは通らない**(``tests/test_highlight_export_provenance.py``)。ここで
    確かめるのは、通したときに成果物と見分けが付くかどうかである。"""
    storage = server.runtime.storage
    session_id, recording_id, _mp4 = make_srv_recording(unique_id=STREAMER, ts_segments=4)
    started = storage.get_recording(recording_id)["started_at"]
    storage.add_event(session_id, gift_builder(
        "Goal Highlight", diamonds=6000, at=started + 100.0,
        user=_user("視聴者A", user_id="7001", unique_id="viewer_a")))
    storage.flush()
    gift = storage.highlight_gift_events(session_id, started, started + 1000.0)[0]

    path = highlight_roots["place"](highlight_roots["work"], STREAMER, "highlights",
                                    "a.mp4")
    _make_highlight(path)
    client.post("/api/highlights/scan", json={"streamer": STREAMER})
    highlight_id = client.get(
        f"/api/highlights?streamer={STREAMER}").json()["items"][0]["id"]

    # **DBには照合結果が1件も無い。** 事故のときと同じ状態で、手で組んだ行だけを渡す。
    rows = [{"highlight_id": highlight_id, "idx": 0, "start": 1.0, "end": 4.0,
             # gift演出の窓。手で組む行でも、giftを切る窓(``start``/``end``)とは別に要る。
             "segment_start": 1.0, "segment_end": 4.0,
             "recording_id": recording_id, "media_start": 100.0, "confidence": "high",
             "gift_event_id": gift["gift_event_id"], "gift_name": gift["gift_name"],
             "diamonds": gift["diamonds"], "identity_key": gift["identity_key"],
             "user_nickname": gift["user_nickname"],
             "unique_id": STREAMER, "filename": "a.mp4", "path": str(path),
             "highlight_duration_seconds": float(HIGHLIGHT_SECONDS)}]
    result = asyncio.run(hx.export_highlights(storage, [highlight_id],
                                              verification_rows=rows))
    assert result["verified"] is False
    out = hx.Path(result["files"][0]["path"])
    assert out.name.endswith(f"{hx.UNVERIFIED_MARK}{hx.STORY_EXT}")
    record = json.loads(hx.provenance_path(out).read_text(encoding="utf-8"))
    assert record["verified"] is False


def test_連投は記録6件のまま1つの連続した映像になる(client, server, highlight_roots,
                                                    make_srv_recording, gift_builder):
    """**利用者の指示の確認。** 連投はたたまず、そのまま連続して見せる。

    実測: 60.8秒のhighlight 1本に gift が21件(Hearts 199💎×6 等)。1 gift = 1切り出しに
    すると同じ場面が6本並ぶ —— それは「連続して表示」ではなく同じ場面の6回繰り返しである。
    記録は6件のまま、映像は1つの連続したgift演出になることを、実際に切って確かめる。"""
    storage = server.runtime.storage
    session_id, recording_id, _mp4 = make_srv_recording(unique_id=STREAMER, ts_segments=4)
    started = storage.get_recording(recording_id)["started_at"]
    for n in range(6):
        storage.add_event(session_id, gift_builder(
            "Hearts", diamonds=199, at=started + 100.0 + n * 0.4,
            user=_user("視聴者D", user_id="7003", unique_id="viewer_do")))
    storage.flush()
    gifts = storage.highlight_gift_events(session_id, started, started + 1000.0)
    assert len(gifts) == 6

    path = highlight_roots["place"](highlight_roots["work"], STREAMER, "highlights",
                                    "a.mp4")
    _make_highlight(path)
    client.post("/api/highlights/scan", json={"streamer": STREAMER})
    highlight_id = client.get(
        f"/api/highlights?streamer={STREAMER}").json()["items"][0]["id"]
    # 6件とも**同じgift演出**の中に在る(実測でも Hearts 6件は1つのgift演出に収まっていた)。
    storage.save_highlight_match(highlight_id, {
        "seconds": float(HIGHLIGHT_SECONDS), "pool": 1, "pool_hours": 1.0, "elapsed": 1.0,
        "scope": {"scope": "gift", "days": 14.0},
        "segments": [{
            "index": 0, "start": 2.0, "end": 8.0,
            "recording_id": recording_id, "media_start": 100.0,
            "votes": 900, "ratio": 220.0, "corr": 0.98, "confidence": "high", "effect": [],
            "gifts": [{**gift, "event_id": gift["gift_event_id"],
                       "media_time": 100.0 + index * 0.4, "inside": True,
                       "primary": index == 0, "has_effect": False}
                      for index, gift in enumerate(gifts)]}],
    })

    result = asyncio.run(hx.export_highlights(storage, [highlight_id]))
    entry = result["files"][0]
    # 記録は6件・💎は6件ぶん。「Hearts ×6」と1行に潰さない。
    assert entry["count"] == 6 and entry["diamonds"] == 199 * 6
    # 映像は1本の連続した6秒。同じ場面が6回は出ない。
    assert entry["cut_count"] == 1 and entry["parts"] == 1
    assert entry["measured"]["video_seconds"] == pytest.approx(6.0, abs=0.3)
    out = hx.Path(entry["path"])
    record = json.loads(hx.provenance_path(out).read_text(encoding="utf-8"))
    assert len(record["segments"]) == 6      # 記録
    assert len(record["cuts"]) == 1          # 切り出し
    assert record["cuts"][0]["gift_event_ids"] == [g["gift_event_id"] for g in gifts]

    import scripts.verify_highlight_export as verify

    checked = verify._check_file(storage._conn, out)
    assert checked["ok"], checked["problems"]
    assert checked["segments"] == 6
