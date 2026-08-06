"""HLS segmentの束ね(hls_pack)。

束ね方を誤ると再生が壊れる: 1 fileの中で解像度が変わると、そのfile用のinit segmentの寸法が
全域へ適用され、切替前へseekした時に縦横比が崩れる。plan_packs はその「切ってはいけない所」
と「切らなければいけない所」を決める唯一の場所なので、ここを直接固定する。

後半(``pack_session``)は実ffmpegで作った合成captureへ本物の結合を掛ける。束ねは元segmentを
**消す**ので、検証が素通りするとその録画は復元できない。argv assertionでは踏めない領域なので、
実際のbyteとfileの増減で見る:

    pytest -m requires_ffmpeg
    pytest -m "not slow"
"""
import shutil
import subprocess

import pytest

from tictok.record import hls_pack

SD = (640, 1280)
HD = (720, 1280)
LOW = (432, 864)


# --------------------------------------------------------------------------
# plan_packs
# --------------------------------------------------------------------------


def test_consecutive_segments_of_one_resolution_become_one_pack():
    assert hls_pack.plan_packs([[SD], [SD], [SD]]) == [[0, 1, 2]]


def test_a_resolution_change_starts_a_new_pack():
    """切れ目で切らないと、切替前へseekした時に縦横比が崩れる。"""
    assert hls_pack.plan_packs([[SD], [SD], [HD], [HD]]) == [[0, 1], [2, 3]]


def test_a_segment_that_changes_resolution_inside_is_isolated():
    """1本の中で変わるsegmentはどう切っても単一解像度にならないので単独にする
    (実測では解像度変化40回のうち29回がこれ)。"""
    assert hls_pack.plan_packs([[SD], [SD, HD], [HD]]) == [[0], [1], [2]]


def test_isolated_segment_does_not_glue_the_runs_around_it():
    """隔離したsegmentを挟んだ前後は、解像度が同じでも別の束のままにする。
    束ね直すと隔離した1本が束の中へ戻り、隔離の意味が消える。"""
    assert hls_pack.plan_packs([[SD], [SD, HD], [SD]]) == [[0], [1], [2]]


def test_repeated_resolution_within_one_segment_is_not_a_change():
    """同じ解像度が連続して並ぶだけなら切替ではない。"""
    assert hls_pack.plan_packs([[SD, SD], [SD]]) == [[0, 1]]


def test_a_segment_with_no_probed_resolution_is_isolated():
    """判定できなかったsegmentを既定の束へ入れると、中身を確かめないまま束ねることになる。"""
    assert hls_pack.plan_packs([[SD], [], [SD]]) == [[0], [1], [2]]


def test_three_way_change_produces_three_packs():
    assert hls_pack.plan_packs([[LOW], [LOW], [SD], [HD], [HD]]) == [[0, 1], [2], [3, 4]]


def test_no_segments_produces_no_packs():
    assert hls_pack.plan_packs([]) == []


# --------------------------------------------------------------------------
# parse_playlist
# --------------------------------------------------------------------------


def test_parse_playlist_keeps_order_extinf_and_discontinuity():
    text = (
        "#EXTM3U\n"
        "#EXT-X-VERSION:6\n"
        "#EXTINF:2.000000,\n"
        "seg00000.ts\n"
        "#EXT-X-DISCONTINUITY\n"
        "#EXTINF:1.500000,\n"
        "seg00001.ts\n"
        "#EXT-X-ENDLIST\n"
    )
    assert hls_pack.parse_playlist(text) == [
        {"name": "seg00000.ts", "extinf": 2.0, "disc": False},
        {"name": "seg00001.ts", "extinf": 1.5, "disc": True},
    ]


def test_parse_playlist_drops_an_entry_without_extinf():
    """EXTINFの無いentryはmedia軸に長さを持たない。黙って0秒として通すと尺がずれる。"""
    text = "#EXTM3U\nstray.ts\n#EXTINF:2.000000,\nseg00000.ts\n"
    assert [e["name"] for e in hls_pack.parse_playlist(text)] == ["seg00000.ts"]


# --------------------------------------------------------------------------
# render_playlist
# --------------------------------------------------------------------------


def _snapshot(segments):
    return {"version": 1, "packed_at": 0.0, "packs": 1, "segments": segments}


def test_render_playlist_points_byte_ranges_into_the_pack():
    text = hls_pack.render_playlist(_snapshot([
        {"name": "seg00000.ts", "extinf": 2.0, "disc": False, "wall": 1.0, "size": 10,
         "pack": "pack000.ts", "offset": 0, "length": 10},
        {"name": "seg00001.ts", "extinf": 2.0, "disc": False, "wall": 3.0, "size": 20,
         "pack": "pack000.ts", "offset": 10, "length": 20},
    ]))
    assert "#EXT-X-BYTERANGE:10@0\npack000.ts" in text
    assert "#EXT-X-BYTERANGE:20@10\npack000.ts" in text
    assert text.rstrip().endswith("#EXT-X-ENDLIST")
    assert "#EXT-X-PLAYLIST-TYPE:VOD" in text


def test_render_playlist_carries_the_discontinuity_marker():
    """捨てるとdemuxerがtimestampの飛びを経過時間として数え、尺が伸びる。"""
    text = hls_pack.render_playlist(_snapshot([
        {"name": "seg00000.ts", "extinf": 2.0, "disc": True, "wall": 1.0, "size": 10,
         "pack": "pack000.ts", "offset": 0, "length": 10},
    ]))
    assert "#EXT-X-DISCONTINUITY\n#EXTINF:2.000000," in text


def test_render_playlist_target_duration_covers_the_longest_segment():
    text = hls_pack.render_playlist(_snapshot([
        {"name": "a.ts", "extinf": 2.0, "disc": False, "wall": 1.0, "size": 1,
         "pack": "pack000.ts", "offset": 0, "length": 1},
        {"name": "b.ts", "extinf": 5.4, "disc": False, "wall": 3.0, "size": 1,
         "pack": "pack000.ts", "offset": 1, "length": 1},
    ]))
    assert "#EXT-X-TARGETDURATION:6" in text


# --------------------------------------------------------------------------
# _parse_res_csv
# --------------------------------------------------------------------------


def test_parse_res_csv_reads_the_trailing_separator_ffprobe_emits():
    """ffprobeは行によって末尾にseparatorを1つ余分に付ける(実出力: 同じfileでも
    ``160,120,`` と ``160,120`` が混ざる)。末尾から数えると余分な行だけ空文字をintに
    掛けて落ち、そのsegmentが解像度不明として単独隔離される。**失敗ではなく静かな
    取りこぼし**なので、束ねの3段の検証も素通りする。"""
    assert hls_pack._parse_res_csv("160,120,\n320,240\n") == [(160, 120), (320, 240)]


def test_parse_res_csv_collapses_a_repeated_resolution():
    """keyframeは1 segmentに何十本も並ぶ。同じ解像度の連続を1つに畳まないと、
    変化していないsegmentが「2種類以上」と見なされて単独隔離される。"""
    assert hls_pack._parse_res_csv("160,120\n160,120\n320,240\n160,120\n") == [
        (160, 120), (320, 240), (160, 120)]


def test_parse_res_csv_skips_lines_it_cannot_read():
    assert hls_pack._parse_res_csv("160\nN/A,N/A\n\n160,120\n") == [(160, 120)]


# --------------------------------------------------------------------------
# render_source_playlist
# --------------------------------------------------------------------------


def _entry(name, extinf=2.0, disc=False):
    return {"name": name, "extinf": extinf, "disc": disc, "wall": 1.0, "size": 1}


def test_render_source_playlist_terminates_the_list():
    """録画中のindexは強制終了で ``#EXT-X-ENDLIST`` が付かない。そのままffprobeへ渡すと
    live streamと見なされて次のsegmentを待ち、結合前の計測が返ってこない。"""
    text = hls_pack.render_source_playlist([_entry("seg00000.ts")])
    assert "#EXT-X-PLAYLIST-TYPE:VOD" in text
    assert text.rstrip().endswith("#EXT-X-ENDLIST")


def test_render_source_playlist_points_at_the_unpacked_segments_in_order():
    """結合の「前」側の計測対象。1本でも並びが狂うと、束ね後との突き合わせが
    別物どうしの比較になる。"""
    text = hls_pack.render_source_playlist(
        [_entry("seg00000.ts"), _entry("seg00001.ts", disc=True)])
    assert [line for line in text.splitlines() if not line.startswith("#")] == [
        "seg00000.ts", "seg00001.ts"]
    assert "#EXT-X-BYTERANGE" not in text
    assert "#EXT-X-DISCONTINUITY\n#EXTINF:2.000000,\nseg00001.ts" in text


def test_render_source_playlist_target_duration_covers_the_longest_segment():
    text = hls_pack.render_source_playlist([_entry("a.ts", 2.0), _entry("b.ts", 5.4)])
    assert "#EXT-X-TARGETDURATION:6" in text


# --------------------------------------------------------------------------
# _write_pack
# --------------------------------------------------------------------------


def test_write_pack_offsets_carve_the_pack_back_into_its_parts(tmp_path):
    """offset/lengthは再生用playlistのbyte rangeそのもの。1 byteでもずれると
    そのsegmentのTS packetが境界からずれて読まれ、その先が丸ごと復号できなくなる。"""
    entries = [{"name": "a.ts"}, {"name": "b.ts"}, {"name": "c.ts"}]
    blobs = {"a.ts": b"a" * 10, "b.ts": b"b" * 25, "c.ts": b"c" * 5}
    for name, data in blobs.items():
        (tmp_path / name).write_bytes(data)
    dst = tmp_path / "pack000.ts"

    placed = hls_pack._write_pack(tmp_path, entries, [0, 1, 2], dst)

    packed = dst.read_bytes()
    assert placed == [(0, 0, 10), (1, 10, 25), (2, 35, 5)]
    for i, offset, length in placed:
        assert packed[offset:offset + length] == blobs[entries[i]["name"]]


def test_write_pack_only_takes_the_segments_it_was_given(tmp_path):
    """束の構成をindexで受ける。listに無いsegmentを混ぜると、snapshotのoffsetが指す
    範囲と実体がずれる。"""
    entries = [{"name": "a.ts"}, {"name": "b.ts"}, {"name": "c.ts"}]
    for name, data in (("a.ts", b"a" * 4), ("b.ts", b"b" * 4), ("c.ts", b"c" * 4)):
        (tmp_path / name).write_bytes(data)
    dst = tmp_path / "pack000.ts"

    placed = hls_pack._write_pack(tmp_path, entries, [0, 2], dst)

    assert placed == [(0, 0, 4), (2, 4, 4)]
    assert dst.read_bytes() == b"aaaacccc"


# --------------------------------------------------------------------------
# pack_session — the real IO. 元segmentを消す側なので実fileで見る。
# --------------------------------------------------------------------------


SEGMENT_SECONDS = 2

_REAL_FFMPEG = (
    pytest.mark.requires_ffmpeg,
    pytest.mark.slow,
    pytest.mark.skipif(
        not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
        reason="needs a real ffmpeg/ffprobe on PATH",
    ),
)


def needs_ffmpeg(fn):
    for mark in _REAL_FFMPEG:
        fn = mark(fn)
    return fn


def _ffmpeg(*args):
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", *args],
                   check=True, capture_output=True)


def _make_ts(path, width, height, start, seconds):
    _ffmpeg("-f", "lavfi", "-i",
            "testsrc2=size=%dx%d:rate=30:duration=%d" % (width, height, seconds),
            "-f", "lavfi", "-i", "sine=frequency=440:duration=%d" % seconds,
            "-c:v", "libx264", "-preset", "ultrafast", "-g", str(seconds * 30),
            "-c:a", "aac", "-copyts", "-output_ts_offset", str(start),
            "-muxdelay", "0", "-muxpreload", "0", str(path))


def build_hls(hls, shapes):
    """A captured HLS directory, one segment per entry of ``shapes``.

    A ``(w, h)`` tuple is a uniform segment; a list of two tuples is a single segment
    that changes resolution *inside* itself, built by byte-concatenating two halves —
    the majority case in the real stream (40回の変化のうち29回) and the shape
    plan_packs has to isolate. The index is deliberately left unterminated, like the
    captured one.
    """
    hls.mkdir(parents=True, exist_ok=True)
    names = []
    for i, shape in enumerate(shapes):
        parts = shape if isinstance(shape, list) else [shape]
        span = SEGMENT_SECONDS // len(parts)
        chunks = []
        for n, (width, height) in enumerate(parts):
            part = hls / ("part%d.ts" % n)
            _make_ts(part, width, height, i * SEGMENT_SECONDS + n * span, span)
            chunks.append(part.read_bytes())
            part.unlink()
        name = "seg%05d.ts" % i
        (hls / name).write_bytes(b"".join(chunks))
        names.append(name)
    body = ["#EXTM3U", "#EXT-X-VERSION:6",
            "#EXT-X-TARGETDURATION:%d" % (SEGMENT_SECONDS + 1)]
    for name in names:
        body.append("#EXTINF:%.6f," % SEGMENT_SECONDS)
        body.append(name)
    (hls / "index.m3u8").write_text("\n".join(body) + "\n", encoding="utf-8")
    return names


@needs_ffmpeg
async def test_packing_joins_one_resolution_into_one_file_and_drops_the_parts(tmp_path):
    """束ねの目的そのもの。1束に入らなければ5,794 fileは5,794 fileのまま残り、
    走査・backup・移送のfile数がまったく減らない。"""
    hls = tmp_path / "hls"
    names = build_hls(hls, [(160, 120)] * 4)
    sizes = {name: (hls / name).stat().st_size for name in names}

    result = await hls_pack.pack_session(hls)

    assert result["packed"] is True
    assert (result["segments"], result["packs"]) == (4, 1)
    assert sorted(p.name for p in hls.glob("*.ts")) == ["pack000.ts"]
    assert (hls / "pack000.ts").stat().st_size == sum(sizes.values())
    assert result["bytes"] == sum(sizes.values())


@needs_ffmpeg
async def test_packing_leaves_every_segment_byte_reachable_through_the_playlist(tmp_path):
    """再生はsnapshotのoffset/lengthしか手がかりが無い。ここがずれると、束ねた
    fileは残っているのに再生できない録画になる。"""
    hls = tmp_path / "hls"
    names = build_hls(hls, [(160, 120)] * 3)
    blobs = [(hls / name).read_bytes() for name in names]

    await hls_pack.pack_session(hls)

    snapshot = hls_pack.read_snapshot(hls)
    packed = (hls / "pack000.ts").read_bytes()
    for entry, blob in zip(snapshot["segments"], blobs):
        assert packed[entry["offset"]:entry["offset"] + entry["length"]] == blob
        assert entry["length"] == entry["size"] == len(blob)
    body = (hls / "index.m3u8").read_text(encoding="utf-8")
    assert body.rstrip().endswith("#EXT-X-ENDLIST")
    assert body.count("#EXT-X-BYTERANGE") == len(names)


@needs_ffmpeg
async def test_packing_keeps_each_segments_own_mtime(tmp_path):
    """このmtimeがtiming mapのwall軸そのもの。束ねるとfileごと消えるので、ここで
    取り違えるとコメントの時刻が静かにずれる(束ごとに1点へ潰れる)。"""
    import os

    hls = tmp_path / "hls"
    names = build_hls(hls, [(160, 120)] * 4)
    stamps = {}
    for i, name in enumerate(names):
        stamps[name] = 1_700_000_000.0 + i * SEGMENT_SECONDS
        os.utime(hls / name, (stamps[name], stamps[name]))

    await hls_pack.pack_session(hls)

    snapshot = hls_pack.read_snapshot(hls)
    assert [s["name"] for s in snapshot["segments"]] == names
    assert [s["wall"] for s in snapshot["segments"]] == [stamps[n] for n in names]


@needs_ffmpeg
async def test_a_segment_that_changes_resolution_inside_is_packed_alone(tmp_path):
    """実stream多数派の形(1本の内部で切替)。どちらかの束へ寄せると、その束の
    init segmentの寸法が全域へ適用され、切替前へseekした時に縦横比が崩れる。"""
    hls = tmp_path / "hls"
    build_hls(hls, [(160, 120), (160, 120),
                    [(160, 120), (320, 240)],
                    (320, 240), (320, 240)])

    result = await hls_pack.pack_session(hls)

    assert result["packed"] is True
    snapshot = hls_pack.read_snapshot(hls)
    assert [s["pack"] for s in snapshot["segments"]] == [
        "pack000.ts", "pack000.ts", "pack001.ts", "pack002.ts", "pack002.ts"]


@needs_ffmpeg
async def test_a_pack_that_does_not_match_its_parts_leaves_every_segment_alone(
        tmp_path, monkeypatch):
    """検証は元segmentを消す前の最後の関門。ここで落ちたのに消してしまうと、
    束ねが壊れていた録画は復元できない。"""
    hls = tmp_path / "hls"
    names = build_hls(hls, [(160, 120)] * 3)
    before = {name: (hls / name).read_bytes() for name in names}
    index_before = (hls / "index.m3u8").read_text(encoding="utf-8")
    real_write = hls_pack._write_pack

    def write_one_byte_too_many(hls_dir, entries, indices, dst):
        placed = real_write(hls_dir, entries, indices, dst)
        with open(dst, "ab") as out:
            out.write(b"\x00")
        return placed

    monkeypatch.setattr(hls_pack, "_write_pack", write_one_byte_too_many)

    result = await hls_pack.pack_session(hls)

    assert result["packed"] is False
    assert "expected" in result["reason"]
    assert {name: (hls / name).read_bytes() for name in names} == before
    assert list(hls.glob("pack*.ts")) == []
    assert hls_pack.read_snapshot(hls) is None
    assert (hls / "index.m3u8").read_text(encoding="utf-8") == index_before


@needs_ffmpeg
async def test_a_pack_carrying_two_resolutions_leaves_every_segment_alone(
        tmp_path, monkeypatch):
    """plan_packsが誤って混在を1束へ入れた場合の受け皿。probeで見つけた時点で
    その束を捨てて元を残す — 消してからでは戻せない。"""
    hls = tmp_path / "hls"
    names = build_hls(hls, [(160, 120), (320, 240)])

    # 解像度が全部同じに見えれば、切ってはいけない所で切らずに1束へ入る。
    async def all_one_resolution(hls_dir, entries, concurrency=4, on_done=None):
        return [[(160, 120)] for _ in entries]

    monkeypatch.setattr(hls_pack, "_resolutions_for", all_one_resolution)

    result = await hls_pack.pack_session(hls)

    assert result["packed"] is False
    assert "resolutions" in result["reason"]
    assert sorted(p.name for p in hls.glob("*.ts")) == names
    assert hls_pack.read_snapshot(hls) is None


@needs_ffmpeg
async def test_packing_an_already_packed_directory_does_nothing(tmp_path):
    """再実行で束ねた物をもう一度束ねると、pack000.tsの中にpack000.tsが入り、
    snapshotのoffsetが全部無効になる。snapshotの存在だけが唯一の歯止め。"""
    hls = tmp_path / "hls"
    build_hls(hls, [(160, 120)] * 3)
    await hls_pack.pack_session(hls)
    before = {p.name: p.read_bytes() for p in hls.iterdir()}

    result = await hls_pack.pack_session(hls)

    assert result == {"packed": False, "reason": "already_packed",
                      "segments": 0, "packs": 0, "bytes": 0}
    assert {p.name: p.read_bytes() for p in hls.iterdir()} == before


@needs_ffmpeg
async def test_packing_a_directory_without_a_playlist_is_a_no_op(tmp_path):
    hls = tmp_path / "hls"
    hls.mkdir()

    assert (await hls_pack.pack_session(hls))["reason"] == "no_playlist"


@needs_ffmpeg
async def test_packing_a_playlist_whose_segments_are_gone_is_a_no_op(tmp_path):
    """再回収sweepは.tsを消した後のdirも通る。listだけを見て束ねに入ると、
    空のpackを書いてsnapshotを残し、その録画を「束ね済み」にしてしまう。"""
    hls = tmp_path / "hls"
    names = build_hls(hls, [(160, 120)] * 2)
    for name in names:
        (hls / name).unlink()

    result = await hls_pack.pack_session(hls)

    assert result["reason"] == "no_segments"
    assert list(hls.glob("pack*.ts")) == []
    assert hls_pack.read_snapshot(hls) is None


def test_is_packed_looks_at_the_pack_files_not_the_snapshot(tmp_path):
    """束ね済みかどうかは snapshot ではなく束ねたfileの実在で決める。snapshotが読めない
    ことと束ねていないことを混同すると、壊れたsnapshotの録画が「素材ごと消えた録画」に
    見える(元のsegment fileはもう無いため)。"""
    assert hls_pack.is_packed(tmp_path) is False
    (tmp_path / "segments.json").write_text("{}", encoding="utf-8")
    assert hls_pack.is_packed(tmp_path) is False
    (tmp_path / "pack000.ts").write_bytes(b"\x47")
    assert hls_pack.is_packed(tmp_path) is True


def test_a_packed_dir_with_a_broken_snapshot_is_not_read_as_unpacked(tmp_path):
    """壊れたsnapshotをplaylist経路へ流すと、全entryが「fileが無い」となって空listが
    返る。空listは「素材が1本も無い」と同義で、finalizeはその録画を捨てる。"""
    from tictok.record.recorder import Recorder

    hls = tmp_path / "ts" / "00042_alice_20260101_120000"
    hls.mkdir(parents=True)
    (hls / "pack000.ts").write_bytes(b"\x47" * 188)
    (hls / "segments.json").write_text("{ broken", encoding="utf-8")
    (hls / "index.m3u8").write_text(
        "#EXTM3U\n#EXTINF:2.000000,\nseg00000.ts\n#EXT-X-ENDLIST\n", encoding="utf-8")

    r = Recorder("alice", str(tmp_path), 1)
    r.hls_dir = hls
    r.playlist = hls / "index.m3u8"
    r.base = hls.name

    assert r._segment_facts() is None
    assert r._playlist_segments() == []


@needs_ffmpeg
async def test_a_kill_during_the_build_leaves_nothing_that_looks_packed(tmp_path, monkeypatch):
    """組み立ての最中に殺されても、束ね済みに見えるfileを残さないこと。

    束を最終名で書いていた頃は、数GBの連結中にprocessが落ちると ``pack*.ts`` だけが
    残った。``is_packed`` はfileの実在で判定するのでTrueになる一方 ``segments.json`` は
    まだ無く、下流はその録画を「素材無し」と読む — playlistは元のseg*.tsを指したままで
    1 byteも欠けていないのにである(実測1件)。一時名で組み立てれば、残るのはどのglobにも
    当たらないゴミだけになる。"""
    session = tmp_path / "hls"
    build_hls(session, [(160, 120)] * 4)
    before = sorted(p.name for p in session.glob("seg*.ts"))

    real_write = hls_pack._write_pack
    calls = {"n": 0}

    def die_on_the_second_pack(hls_dir, entries, indices, dst):
        calls["n"] += 1
        result = real_write(hls_dir, entries, indices, dst)
        if calls["n"] >= 1:
            raise KeyboardInterrupt("simulated kill mid-build")
        return result

    monkeypatch.setattr(hls_pack, "_write_pack", die_on_the_second_pack)
    with pytest.raises(KeyboardInterrupt):
        await hls_pack.pack_session(session)

    assert not hls_pack.is_packed(session), "束ね済みに見えるfileが残っている"
    assert hls_pack.read_snapshot(session) is None
    assert sorted(p.name for p in session.glob("seg*.ts")) == before, "元segmentが失われた"
    # 元のplaylistは触られていない(まだ元のsegmentを指している)。
    text = (session / "index.m3u8").read_text(encoding="utf-8")
    assert "seg00000.ts" in text
