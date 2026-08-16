"""出力済みclip(``_clips``)の一覧・再生・削除と、書き出しの在り処の名乗り。

ここが守るのは「作った成果物の在り処を、利用者が画面から辿れること」である。切り出したmp4は
DBに行を持たず、置き場は配信者folderの下(``<root>/<配信者>/_clips/``)で、最終保存先へ移動
した録画のぶんは向こう側にも在るため、成果物は一時保存先と最終保存先の2箇所へ散らばる。
散らばること自体は設計どおりなので、testは「片方しか見ない」退行と、「作ったのに出力先を
名乗らない」退行の両方を落とす。
"""
import asyncio
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tictok.media.clipper import parse_clip_name

from tests.test_server import (  # noqa: F401  (fixtureとして使う)
    client, make_srv_recording, server,
)


# ===== file名の読み戻し =====
# 一覧は範囲もラベルもfile名からしか読めない。組み立て(clip_path / reel_path)と対で守る。


def test_clip_name_round_trips_range_and_label():
    parsed = parse_clip_name("00400_pomiiiip_20260729_220601_025716-025719_ガンダム.mp4")
    assert parsed["stem"] == "00400_pomiiiip_20260729_220601"
    assert parsed["streamer"] == "pomiiiip"
    assert (parsed["start"], parsed["end"]) == (2 * 3600 + 57 * 60 + 16,
                                                2 * 3600 + 57 * 60 + 19)
    assert parsed["label"] == "ガンダム"
    assert parsed["kind"] == "clip"


def test_clip_name_tells_the_variants_apart():
    """焼き込み切り抜きと連結は素の切り出しと別物として名乗る(素材の素性が違う)。"""
    assert parse_clip_name("00042_u_20250101_120000_000010-000020.overlay.mp4")["kind"] == "overlay"
    reel = parse_clip_name("00042_u_20250101_120000_reel3_000010-000230_まとめ.mp4")
    assert reel["kind"] == "reel" and reel["parts"] == 3


def test_clip_name_refuses_to_guess():
    """規約外の名前に素性を作らない。読めないものは読めないまま並べる。"""
    assert parse_clip_name("メモ.mp4") is None
    assert parse_clip_name("00042_u_20250101_120000_000010-000020.txt") is None
    assert parse_clip_name("メモ.png") is None


def test_still_name_round_trips_position_and_variant():
    """スクショは範囲を持たない。位置は1/100秒まで残し、endは作らない。

    秒へ丸めると、同じ秒の中で位置を変えて撮った2枚が黙って同じfileを奪い合う(静止画は
    1 frameそのものが成果物なので、秒の中のどこかが結果の全てである)。"""
    from tictok.media.clipper import still_path

    src = Path("K:/rec/pomiiiip/mp4/00400_pomiiiip_20260729_220601.mp4")
    out = still_path(src, 2 * 3600 + 57 * 60 + 16.35, "ガンダム", suffix="overlay")
    parsed = parse_clip_name(out.name)
    assert parsed["stem"] == "00400_pomiiiip_20260729_220601"
    assert parsed["start"] == pytest.approx(2 * 3600 + 57 * 60 + 16.35)
    assert parsed["end"] is None
    assert parsed["label"] == "ガンダム"
    assert parsed["kind"] == "still" and parsed["variant"] == "overlay"
    # 同じ秒でも位置が違えば別のfileになる。
    assert still_path(src, 10.20).name != still_path(src, 10.80).name


# ===== 一覧 =====


@pytest.fixture
def clip_roots(server, tmp_path):
    """work / final の2つのrootを張り、それぞれの置き場へfileを置ける状態にする。

    置き場は種別で分かれる(動画は ``_clips``・静止画は ``_screenshots``)ので、fixtureも
    production(``clipper.clip_path`` / ``still_path``)と同じ決め方をする — ここだけが同じdirへ
    置いていると、置き場を跨いで並べられているかをtestが確かめられない。

    2 rootにするのがこのfixtureの要点である。成果物が両方に散らばるのは実際の運用状態
    (実測で7本と11本に分かれていた)で、片方しか見ない実装はその場では動いて見える。

    rootは ``runtime.RECORD_DIR`` ではなくこのtestのtmpへ張る。runtimeはimport時に1度だけ
    root を掴むmodule singletonで、全testが**最初のtestのsandbox**を共有する。そこへ置くと
    前のtestが作ったfileを次のtestが自分のものとして数える。"""
    from tictok.core import layout

    work = tmp_path / "work"
    final = tmp_path / "final"
    work.mkdir(parents=True, exist_ok=True)
    final.mkdir(parents=True, exist_ok=True)
    layout.set_record_roots([work, final])

    def _place(root: Path, streamer: str, name: str, size: int = 32) -> Path:
        target = (layout.stills_dir(root, streamer) if name.lower().endswith(".png")
                  else layout.clips_dir(root, streamer))
        target.mkdir(parents=True, exist_ok=True)
        path = target / name
        path.write_bytes(b"\x00" * size)
        return path

    return {"work": work, "final": final, "place": _place}


def test_clips_lists_both_roots(client, clip_roots, make_srv_recording):
    """一時保存先と最終保存先の両方を並べる。

    rootは録画の所在で決まるので、切り出しは必ず2箇所へ散らばり得る。片方だけを見る一覧は
    「そこには無い」を「どこにも無い」と読ませる。"""
    _, recording_id, path = make_srv_recording()
    stem = path.stem
    clip_roots["place"](clip_roots["work"], "tester", f"{stem}_000010-000020.mp4", 100)
    clip_roots["place"](clip_roots["final"], "tester", f"{stem}_000030-000045_歓声.mp4", 200)

    body = client.get("/api/clips").json()
    assert {item["root"] for item in body["items"]} == {"work", "final"}
    assert body["total_bytes"] == 300
    by_root = {root["key"]: root for root in body["roots"]}
    assert by_root["work"]["count"] == 1 and by_root["final"]["bytes"] == 200
    # 置き場のpathは画面がそのまま出す。配信者ごとに分かれたので、この保存先を代表する
    # 1つのdirはrootそのものになる。
    assert by_root["final"]["path"] == str(clip_roots["final"])
    # 名前はrootからの相対。実pathは配信者folderの下の ``_clips``。
    work_item = [i for i in body["items"] if i["root"] == "work"][0]
    assert work_item["name"].startswith("tester/_clips/")
    assert Path(work_item["path"]).parent == clip_roots["work"] / "tester" / "_clips"

    labelled = [i for i in body["items"] if i["label"] == "歓声"][0]
    assert labelled["start"] == 30.0 and labelled["end"] == 45.0
    assert labelled["unique_id"] == "tester"
    # 元録画へ辿れること。stemが当たれば録画の身元を添える。
    assert labelled["recording_id"] == recording_id


def test_clips_keeps_files_whose_recording_is_gone(client, clip_roots):
    """録画が消えた切り出しも成果物としては実在する。隠さず、素性なしで並べる。

    切り出しは録画の削除に道連れされない(派生物の範囲外)ため、この状態は普通に起きる。"""
    clip_roots["place"](clip_roots["work"], "ghost", "00999_ghost_20250101_000000_000010-000020.mp4")
    items = client.get("/api/clips").json()["items"]
    assert len(items) == 1
    assert items[0]["recording_id"] is None
    assert items[0]["unique_id"] == "ghost" and items[0]["kind"] == "clip"


def test_clips_reports_leftover_work_dirs_separately(client, clip_roots):
    """落ちた回の中間dirは成果物として数えない(数えると容量も本数も嘘になる)。

    中間は出力と同じvolumeへ置く決まりなので ``_clips`` の中に現れる。正常終了なら消える
    ため、残っているものは掃除の手掛かりとして件数だけ別に出す。"""
    from tictok.core import layout

    work = layout.clips_dir(clip_roots["work"], "tester")
    (work / ".smartcut-abcd").mkdir(parents=True, exist_ok=True)
    (work / ".smartcut-abcd" / "part0.ts").write_bytes(b"\x00" * 500)
    (work / "00001_tester_20250101_000000_000010-000020.mp4").write_bytes(b"\x00" * 10)

    body = client.get("/api/clips").json()
    assert [item["filename"] for item in body["items"]] == [
        "00001_tester_20250101_000000_000010-000020.mp4"]
    assert body["total_bytes"] == 10
    root = [r for r in body["roots"] if r["key"] == "work"][0]
    assert root["leftover_count"] == 1 and root["leftover_bytes"] == 500


def test_clips_counts_the_scene_cache_apart_from_leftovers(client, clip_roots):
    """作品のシーンcacheは残骸ではない。消すべき物と、消さない方が得な物を同じ数字に
    混ぜると、画面はどちらの意味でも読めない量を出すことになる。

    成果物としても並べない — 1本の作品の材料であって、それ自体を配ったり観たりする物では
    ないため。
    """
    from tictok.core import layout
    from tictok.media import work as work_media

    base = layout.clips_dir(clip_roots["work"], "tester")
    scenes = base / work_media.SCENE_CACHE_DIR
    scenes.mkdir(parents=True, exist_ok=True)
    (scenes / "00001_tester_20250101_000000_000010-000020.cut.mp4").write_bytes(b"\x00" * 700)
    (base / ".clip_dead").mkdir(parents=True, exist_ok=True)
    (base / ".clip_dead" / "x.mp4").write_bytes(b"\x00" * 40)
    (base / "00001_tester_20250101_000000_000010-000020.mp4").write_bytes(b"\x00" * 10)

    body = client.get("/api/clips").json()
    assert [item["filename"] for item in body["items"]] == [
        "00001_tester_20250101_000000_000010-000020.mp4"]
    root = [r for r in body["roots"] if r["key"] == "work"][0]
    assert root["cache_count"] == 1 and root["cache_bytes"] == 700
    # 残骸の集計へ混ざらないこと(混ざると「掃除すれば減る」量を誤って大きく見せる)。
    assert root["leftover_count"] == 1 and root["leftover_bytes"] == 40


# ===== 配信・削除 =====


def test_clip_file_is_served_and_deleted(client, clip_roots):
    """画面から中身を観て、要らなければその場で消せる。

    保持policyは切り出しを対象にしていない(人が範囲を選んで作った成果物のため)ので、
    消す口はここにしか無い。"""
    name = "00001_tester_20250101_000000_000010-000020.mp4"
    path = clip_roots["place"](clip_roots["work"], "tester", name, 64)
    rel = f"tester/_clips/{name}"

    served = client.get("/api/clips/file", params={"root": "work", "name": rel})
    assert served.status_code == 200 and len(served.content) == 64

    removed = client.request("DELETE", "/api/clips/file",
                             params={"root": "work", "name": rel}).json()
    assert removed["freed_bytes"] == 64
    assert not path.exists()
    assert client.get("/api/clips").json()["items"] == []


def test_clips_lists_stills_from_the_screenshots_dir(client, clip_roots):
    """スクショ(png)は別のdir(``_screenshots``)へ出るが、同じ一覧に並ぶ。

    置き場を分けた目的はfile managerで探せることだけで、画面から辿る口を分けることではない。
    走査が ``_clips`` しか見ない形のままpngの置き場だけを移すと、作った1枚が画面のどこからも
    辿れなくなる(この置き場はDBに行を持たず、一覧が唯一の台帳である)。"""
    stem = "00999_ghost_20250101_000000"
    clip_roots["place"](clip_roots["work"], "ghost", f"{stem}_shot00001235_歓声.png", 50)

    items = client.get("/api/clips").json()["items"]
    assert [item["kind"] for item in items] == ["still"]
    still = items[0]
    assert still["name"].startswith("ghost/_screenshots/")
    assert still["unique_id"] == "ghost"
    assert still["start"] == pytest.approx(12.35) and still["end"] is None
    assert still["label"] == "歓声"
    # 配信はpngとして返す(video/mp4のまま返すと画面がplayerで開こうとする)。
    served = client.get("/api/clips/file",
                        params={"root": "work", "name": still["name"]})
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"
    # 消す口も同じ1つ。置き場の照合(``layout.is_clip_path``)が ``_clips`` しか通さないと、
    # 画面に並んでいるのに消せない1枚が残る。
    removed = client.request("DELETE", "/api/clips/file",
                             params={"root": "work", "name": still["name"]}).json()
    assert removed["freed_bytes"] == 50
    assert client.get("/api/clips").json()["items"] == []


def test_clips_lists_subtitle_sidecars_and_serves_them_as_text(client, clip_roots):
    """切り抜きへ添えた字幕fileも同じ一覧に並ぶ。

    mp4と同じ名前で拡張子だけが違うので、範囲もラベルも同じ規則で読める。走査から漏らすと、
    出したはずのfileが画面のどこからも辿れない(この置き場はDBに行を持たない)。"""
    stem = "00001_tester_20250101_000000"
    clip_roots["place"](clip_roots["work"], "tester", f"{stem}_000010-000020.mp4", 64)
    clip_roots["place"](clip_roots["work"], "tester", f"{stem}_000010-000020.srt", 20)

    items = client.get("/api/clips").json()["items"]
    subtitle = [i for i in items if i["kind"] == "subtitle"][0]
    assert subtitle["subtitle_format"] == "srt"
    assert (subtitle["start"], subtitle["end"]) == (10.0, 20.0)
    served = client.get("/api/clips/file", params={"root": "work", "name": subtitle["name"]})
    assert served.status_code == 200
    # video/mp4のまま返すと画面がplayerで開こうとする。中身は文字である。
    assert served.headers["content-type"].startswith("application/x-subrip")


def test_deleting_a_clip_takes_its_subtitle_files_with_it(client, clip_roots):
    """字幕fileは単独では使い道が無い(時刻が対のmp4の軸に載っている)。

    残すと、消えた動画の字幕だけが一覧に並び続ける。逆向き(字幕fileを消してもmp4は残る)は
    成り立つので、そちらは1本ずつのままである。"""
    stem = "00001_tester_20250101_000000"
    mp4 = clip_roots["place"](clip_roots["work"], "tester", f"{stem}_000010-000020.mp4", 64)
    srt = clip_roots["place"](clip_roots["work"], "tester", f"{stem}_000010-000020.srt", 20)
    ass = clip_roots["place"](clip_roots["work"], "tester", f"{stem}_000010-000020.ass", 30)

    removed = client.request(
        "DELETE", "/api/clips/file",
        params={"root": "work", "name": f"tester/_clips/{mp4.name}"}).json()
    assert sorted(removed["subtitle_files"]) == sorted([srt.name, ass.name])
    assert removed["freed_bytes"] == 114
    assert not mp4.exists() and not srt.exists() and not ass.exists()
    assert client.get("/api/clips").json()["items"] == []


def test_deleting_a_subtitle_file_leaves_the_clip(client, clip_roots):
    stem = "00001_tester_20250101_000000"
    mp4 = clip_roots["place"](clip_roots["work"], "tester", f"{stem}_000010-000020.mp4", 64)
    srt = clip_roots["place"](clip_roots["work"], "tester", f"{stem}_000010-000020.srt", 20)

    removed = client.request(
        "DELETE", "/api/clips/file",
        params={"root": "work", "name": f"tester/_clips/{srt.name}"}).json()
    assert removed["freed_bytes"] == 20 and removed["subtitle_files"] == []
    assert mp4.exists() and not srt.exists()


def test_clip_file_refuses_to_leave_the_clips_dir(client, clip_roots):
    """root外を指すpathは配信も削除もしない。名前はclient由来である。"""
    outside = clip_roots["work"] / "secret.mp4"
    outside.write_bytes(b"\x00" * 8)
    for method in ("GET", "DELETE"):
        response = client.request(method, "/api/clips/file",
                                  params={"root": "work", "name": "../secret.mp4"})
        assert response.status_code == 400
    assert outside.exists()
    assert client.get("/api/clips/file",
                      params={"root": "nowhere", "name": "x.mp4"}).status_code == 400


def test_clip_file_refuses_the_recordings_beside_the_clips(client, clip_roots):
    """同じrootに在る録画本体は扱わない。

    置き場が配信者folderの下へ移り、名前もrootからの相対になった。rootの下に居ることだけを
    確かめると、``<配信者>/mp4/`` の元mp4まで名前指定で配信・削除できてしまう。"""
    source = clip_roots["work"] / "tester" / "mp4"
    source.mkdir(parents=True, exist_ok=True)
    mp4 = source / "00001_tester_20250101_000000.mp4"
    mp4.write_bytes(b"\x00" * 8)

    for method in ("GET", "DELETE"):
        response = client.request(
            method, "/api/clips/file",
            params={"root": "work", "name": "tester/mp4/00001_tester_20250101_000000.mp4"})
        assert response.status_code == 400
    assert mp4.exists()


def test_clips_still_lists_the_old_shared_placement(client, clip_roots):
    """配信者folderの下へ移す前の実体(``<root>/_clips/<配信者>/``)も並べる。

    移行(``scripts/migrate_clips_layout.py``)は手で走らせる1度きりの操作なので、走らせる前
    でも走らせた後でも一覧は同じ物を名乗る必要がある。走らせるまで画面から消えるなら、
    利用者は成果物を失ったと読む。"""
    from tictok.core import layout

    old = layout.clips_dir(clip_roots["work"]) / "tester"
    old.mkdir(parents=True, exist_ok=True)
    (old / "00001_tester_20250101_000000_000010-000020.mp4").write_bytes(b"\x00" * 20)

    items = client.get("/api/clips").json()["items"]
    assert [item["unique_id"] for item in items] == ["tester"]
    assert items[0]["name"] == "_clips/tester/00001_tester_20250101_000000_000010-000020.mp4"
    served = client.get("/api/clips/file",
                        params={"root": "work", "name": items[0]["name"]})
    assert served.status_code == 200


def test_clip_file_missing_is_not_found(client, clip_roots):
    response = client.get("/api/clips/file",
                          params={"root": "work", "name": "tester/_clips/no.mp4"})
    assert response.status_code == 404


# ===== 書き出しが在り処を名乗る =====


def _fake_clip_result(out: Path) -> dict:
    return {"path": str(out), "filename": out.name, "bytes": 7, "start": 0.0, "end": 5.0,
            "mode": "copy", "precise": False, "encoder": "copy", "normalized": False,
            "output_duration_seconds": 5.0, "keyframe_lead_seconds": 0.0,
            "actual_start_seconds": 0.0}


async def _run_batch(server, job):
    async def report(stage, pct):
        return None

    return await server.media_jobs._run_media_job(job, report)


async def test_clip_batch_result_names_where_the_files_went(
    server, make_srv_recording, monkeypatch, tmp_path
):
    """一括書き出しの結果は出力先まで名乗る。

    以前はfile名のlistだけを返しており、単発の切り出しだけがpathを返す非対称な状態だった。
    Job画面はこの結果しか材料を持たないため、そこが欠けると利用者は成果物を探せない。"""
    _, recording_id, _ = make_srv_recording(ts_segments=2)
    out_dir = tmp_path / "tester" / "_clips"
    out_dir.mkdir(parents=True, exist_ok=True)

    made = []

    async def fake_make_clip(src, start, end, label=None, **kwargs):
        out = out_dir / f"clip{len(made)}.mp4"
        out.write_bytes(b"\x00" * 7)
        made.append(out)
        return _fake_clip_result(out)

    monkeypatch.setattr(server.media_jobs, "make_clip", fake_make_clip)
    result = await _run_batch(server, {
        "kind": "clip_batch", "recording_id": recording_id, "job_id": "batch1",
        "params": {"ranges": [{"start": 0.0, "end": 5.0, "label": None},
                              {"start": 9.0, "end": 12.0, "label": None}]},
    })
    assert result["count"] == 2
    assert result["output_dir"] == str(out_dir)
    assert result["paths"] == [str(p) for p in made]


async def test_clip_batch_records_the_export_on_the_bookmark_row(
    server, make_srv_recording, monkeypatch, tmp_path
):
    """由来の見どころへ「いつ・どこへ出したか」を書き戻す。

    書き戻さないと、一覧は何度書き出しても同じ見た目のままで、どの行が成果物を
    持っているのか読み取れない。"""
    _, recording_id, _ = make_srv_recording(ts_segments=2)
    storage = server.runtime.storage
    cut = storage.add_bookmark(recording_id, "tester", 0.0, 5.0, "歓声")
    out = tmp_path / "out.mp4"
    out.write_bytes(b"\x00" * 7)

    async def fake_make_clip(*args, **kwargs):
        return _fake_clip_result(out)

    monkeypatch.setattr(server.media_jobs, "make_clip", fake_make_clip)
    before = time.time()
    await _run_batch(server, {
        "kind": "clip_batch", "recording_id": recording_id, "job_id": "batch2",
        "params": {"ranges": [{"start": 0.0, "end": 5.0, "label": "歓声",
                               "bookmark_id": cut["id"]}]},
    })
    row = storage.get_bookmark(cut["id"])
    assert row["exported_path"] == str(out)
    assert row["exported_at"] >= before


async def test_clip_batch_does_not_fail_when_the_row_is_gone(
    server, make_srv_recording, monkeypatch, tmp_path
):
    """書き戻し先の行が消えていても切り出し自体は成功のまま終える。

    mp4は既に出来ている。記録の失敗を成果物の失敗として報告すると、実在する出力を
    「失敗した」と読ませることになる。"""
    _, recording_id, _ = make_srv_recording(ts_segments=2)
    out = tmp_path / "out.mp4"
    out.write_bytes(b"\x00" * 7)

    async def fake_make_clip(*args, **kwargs):
        return _fake_clip_result(out)

    monkeypatch.setattr(server.media_jobs, "make_clip", fake_make_clip)
    result = await _run_batch(server, {
        "kind": "clip_batch", "recording_id": recording_id, "job_id": "batch3",
        "params": {"ranges": [{"start": 0.0, "end": 5.0, "bookmark_id": 999999}]},
    })
    assert result["count"] == 1


def test_clip_batch_carries_the_bookmark_id_into_the_job(client, server,
                                                         make_srv_recording):
    """投入時にbookmark_idをparamsへ載せる。載らなければworkerは書き戻し先を知らない。"""
    _, recording_id, _ = make_srv_recording(ts_segments=2)
    cut = server.runtime.storage.add_bookmark(recording_id, "tester", 0.0, 5.0, "")
    client.post("/api/clips/batch", json={"items": [
        {"recording_id": recording_id, "start": 0.0, "end": 5.0,
         "bookmark_id": cut["id"]}]})
    job = [j for j in server.runtime.storage.list_media_jobs() if j["kind"] == "clip_batch"][0]
    assert job["params"]["ranges"][0]["bookmark_id"] == cut["id"]
