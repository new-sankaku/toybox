"""下流処理の入力解決(media/hls_source)。

mp4は原本ではなく派生物になったので、mp4が無い録画でも .ts から読めなければ、
その録画は下流(転写・切抜き・sprite・波形・Up出力)から丸ごと消える。ここが誤ると
「素材はあるのに無いと言われる」か「派生物の代わりに原本が黙って出てくる」の
どちらかになるので、その2つの境目を直接固定する。
"""
import pytest

from tictok.core import layout
from tictok.media import hls_source
from tictok.record import recorder as rec


def build_recording(tmp_root, stem="00001_tester_20260101_120000", streamer="tester",
                    segments=3, sizes=None, with_mp4=True, with_index=True):
    """録画1本ぶんのlayout(<root>/<streamer>/{ts,mp4}/)を作り、mp4のpathを返す。"""
    session = layout.session_dir(tmp_root, stem, streamer)
    session.mkdir(parents=True, exist_ok=True)
    names = []
    for i in range(segments):
        name = "seg%05d.ts" % i
        (session / name).write_bytes(b"\x47" * ((sizes or [188] * segments)[i]))
        names.append(name)
    if with_index:
        body = ["#EXTM3U", "#EXT-X-VERSION:6", "#EXT-X-TARGETDURATION:3"]
        for name in names:
            body.append("#EXTINF:2.000000,")
            body.append(name)
        (session / "index.m3u8").write_text("\n".join(body) + "\n", encoding="utf-8")
    mp4 = layout.mp4_path(tmp_root, stem, streamer)
    mp4.parent.mkdir(parents=True, exist_ok=True)
    if with_mp4:
        mp4.write_bytes(b"\x00" * 32)
    return mp4, session


# --------------------------------------------------------------------------
# session_dir_for — 原本へ落ちてよい場合の線引き
# --------------------------------------------------------------------------


def test_a_recordings_own_mp4_resolves_to_its_segments(tmp_root):
    mp4, session = build_recording(tmp_root)

    assert hls_source.session_dir_for(mp4) == session


def test_a_derived_output_never_resolves_to_the_raw_segments(tmp_root):
    """焼き込み(.overlay.mp4)や高画質化(.up.mp4)が無いときに原本の.tsへ落ちると、
    userが求めた出力の代わりに素の映像が黙って出てくる。落としてよいのはその録画
    自身のmp4のときだけ。"""
    mp4, _ = build_recording(tmp_root)

    for derived in ("overlay.mp4", "overlay.b.mp4", "up.mp4"):
        path = mp4.with_name(mp4.stem + "." + derived)
        assert hls_source.session_dir_for(path) is None, derived


def test_a_recording_whose_segments_are_gone_does_not_resolve(tmp_root):
    """.tsを消した録画で空のsession dirへ落ちると、素材が在るかのように進んで
    ffmpegが空listで失敗する。無いことは無いと答える。"""
    mp4, session = build_recording(tmp_root)
    for seg in session.glob("seg*.ts"):
        seg.unlink()

    assert hls_source.session_dir_for(mp4) is None


def test_a_packed_recording_still_resolves(tmp_root):
    """束ねた録画はseg*.tsが1本も無い(pack*.tsだけ)。seg*.tsだけを見ると、束ねた
    録画が全部「素材無し」になる。"""
    mp4, session = build_recording(tmp_root)
    for seg in session.glob("seg*.ts"):
        seg.unlink()
    (session / "pack000.ts").write_bytes(b"\x47" * 564)

    assert hls_source.session_dir_for(mp4) == session


def test_a_path_outside_the_naming_convention_does_not_resolve(tmp_root):
    stray = tmp_root / "tester" / "mp4" / "notarecording.mp4"
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_bytes(b"")

    assert hls_source.session_dir_for(stray) is None


# --------------------------------------------------------------------------
# ffmpeg_source
# --------------------------------------------------------------------------


def test_an_existing_mp4_is_used_as_is(tmp_root):
    """mp4が在る録画の経路は今までと1 bitも変えない。HLSへ回すと、stream copyの
    原本ではなく再生用listを読むことになり、下流の速さも結果も変わる。"""
    mp4, session = build_recording(tmp_root)

    with hls_source.ffmpeg_source(mp4) as source:
        assert source.path == mp4
        assert source.input_args == ()
        assert source.is_hls is False
        assert list(session.glob(hls_source.CURATED_PREFIX + "*")) == []


def test_a_missing_mp4_falls_back_to_a_curated_playlist(tmp_root):
    """captureのindex.m3u8をそのまま渡してはいけない(源のtimestampが壊れたsegmentが
    EXTINF 7.8時間として残っており、2.9時間の録画が10.7時間として読まれる)。採用集合
    だけの終端済みVOD playlistを渡すこと、そのlistがsegmentと同じdirに在ることを見る
    — 相対名で指しているので、別の場所へ置くと1本も解決できない。"""
    mp4, session = build_recording(tmp_root, with_mp4=False)

    with hls_source.ffmpeg_source(mp4) as source:
        assert source.is_hls is True
        assert source.input_args == rec.HLS_INPUT_ARGS
        assert source.path.parent == session
        body = source.path.read_text(encoding="utf-8")
        assert "#EXT-X-PLAYLIST-TYPE:VOD" in body
        assert body.rstrip().endswith("#EXT-X-ENDLIST")
        assert [line for line in body.splitlines() if not line.startswith("#")] == [
            "seg00000.ts", "seg00001.ts", "seg00002.ts"]


def test_the_curated_playlist_is_removed_afterwards(tmp_root):
    """session dirは録画実体の置き場で、retentionと容量集計が数えている。使い捨ての
    listを置きっぱなしにすると録画ごとに溜まる。"""
    mp4, session = build_recording(tmp_root, with_mp4=False)

    with hls_source.ffmpeg_source(mp4) as source:
        written = source.path
        assert written.is_file()

    assert not written.exists()
    assert list(session.glob(hls_source.CURATED_PREFIX + "*")) == []


def test_the_curated_playlist_is_removed_even_when_the_body_fails(tmp_root):
    """下流はffmpegの失敗で普通に例外を投げる。そこで消し残すと、失敗した録画にだけ
    ゴミが積もっていく。"""
    mp4, session = build_recording(tmp_root, with_mp4=False)

    with pytest.raises(RuntimeError, match="boom"):
        with hls_source.ffmpeg_source(mp4):
            raise RuntimeError("boom")

    assert list(session.glob(hls_source.CURATED_PREFIX + "*")) == []


def test_two_readers_of_the_same_recording_do_not_share_a_playlist(tmp_root):
    """同じ録画にsprite生成と波形生成が同時に入る。名前が同じだと、先に抜けた方が
    もう一方が読んでいる最中のlistを消す。"""
    mp4, _ = build_recording(tmp_root, with_mp4=False)

    with hls_source.ffmpeg_source(mp4) as first:
        with hls_source.ffmpeg_source(mp4) as second:
            assert first.path != second.path
            assert first.path.is_file() and second.path.is_file()
        assert first.path.is_file(), "抜けた側が他方のlistを消してはいけない"


def test_a_recording_with_no_material_at_all_is_reported_missing(tmp_root):
    mp4, session = build_recording(tmp_root, with_mp4=False)
    for seg in session.glob("seg*.ts"):
        seg.unlink()

    with pytest.raises(hls_source.SourceMissing):
        with hls_source.ffmpeg_source(mp4):
            pass


def test_segments_without_a_playlist_are_reported_missing(tmp_root):
    """index.m3u8はsegmentの順序と尺(media軸)の唯一の権威。無ければ並べ方が決まらない
    ので、順序を推測して読むより無いと答える方が安全。"""
    mp4, _ = build_recording(tmp_root, with_mp4=False, with_index=False)

    with pytest.raises(hls_source.SourceMissing):
        with hls_source.ffmpeg_source(mp4):
            pass


# --------------------------------------------------------------------------
# fingerprint — cacheの鍵
# --------------------------------------------------------------------------


def test_the_fingerprint_of_an_existing_mp4_is_its_own_stat(tmp_root):
    """既にあるcache(sprite・波形・Up出力)の鍵を変えない。ここが1 fieldでもずれると、
    全録画のcacheが一斉に外れて作り直しになる(Up出力は1本で数時間)。"""
    mp4, _ = build_recording(tmp_root)
    stat = mp4.stat()

    assert hls_source.fingerprint(mp4) == {"mtime": stat.st_mtime, "size": stat.st_size}


def test_the_fingerprint_of_a_segment_set_counts_the_material_itself(tmp_root):
    """playlistのstatでは足りない: segmentが入れ替わってもplaylistのmtimeは動かないので、
    素材が変わったのにcacheが当たり続ける。"""
    mp4, session = build_recording(tmp_root, segments=3, sizes=[188, 376, 188],
                                   with_mp4=False)

    key = hls_source.fingerprint(mp4)

    assert key["segments"] == 3
    assert key["size"] == 188 + 376 + 188
    assert key["mtime"] == max((session / n).stat().st_mtime
                               for n in ("seg00000.ts", "seg00001.ts", "seg00002.ts"))


def test_the_fingerprint_moves_when_a_segment_does(tmp_root):
    import os

    mp4, session = build_recording(tmp_root, with_mp4=False)
    before = hls_source.fingerprint(mp4)

    (session / "seg00001.ts").write_bytes(b"\x47" * 376)
    os.utime(session / "seg00001.ts", (1_800_000_000.0, 1_800_000_000.0))

    assert hls_source.fingerprint(mp4) != before


def test_the_fingerprint_ignores_files_that_are_not_the_recording(tmp_root):
    """session dirにはplaylistや束ねのsnapshot、使い捨てのlistも同居する。数えると、
    録画の中身が変わっていないのに鍵が動いてcacheが外れ続ける。"""
    mp4, session = build_recording(tmp_root, with_mp4=False)
    before = hls_source.fingerprint(mp4)

    (session / "segments.json").write_text("{}", encoding="utf-8")
    (session / rec.VOD_PLAYLIST_NAME).write_text("#EXTM3U\n", encoding="utf-8")

    assert hls_source.fingerprint(mp4) == before


def test_the_fingerprint_of_a_recording_with_no_material_is_reported_missing(tmp_root):
    mp4, session = build_recording(tmp_root, with_mp4=False)
    for seg in session.glob("seg*.ts"):
        seg.unlink()

    with pytest.raises(hls_source.SourceMissing):
        hls_source.fingerprint(mp4)


# --------------------------------------------------------------------------
# 移送が片方だけ済んだ録画 — mp4のrootに素材が無い場合
# --------------------------------------------------------------------------


def test_material_is_found_in_the_other_root_when_the_move_only_half_finished(
        tmp_root, monkeypatch):
    """mp4はfinal rootへ移ったが素材はwork rootに残っている、という録画を読めること。

    移送は素材とmp4をまとめて動かすが、途中で失敗すると片方だけが移る。実測でDBの
    331件中28件がこの状態だった。mp4のrootだけを見ると、その28件は「素材が無い」に
    なる — mp4が原本だった頃は成果物が残るので露見しにくかったが、素材が原本になった
    今は録画が丸ごと画面から消える。"""
    final_root = tmp_root.parent / "final"
    _mp4_in_work, session = build_recording(tmp_root, with_mp4=False)

    # mp4だけがfinal rootに在る形にする。
    stem, streamer = "00001_tester_20260101_120000", "tester"
    moved_mp4 = layout.mp4_path(final_root, stem, streamer)
    moved_mp4.parent.mkdir(parents=True, exist_ok=True)
    moved_mp4.write_bytes(b"\x00" * 32)

    layout.set_record_roots([tmp_root, final_root])
    try:
        assert hls_source.session_dir_for(moved_mp4) == session
        assert hls_source.has_hls_source(moved_mp4)
    finally:
        layout.reset_record_roots()


def test_the_mp4s_own_root_still_wins_when_both_hold_material(tmp_root, monkeypatch):
    """両rootに素材がある録画では、mp4と同じrootの方を採る。

    探索順を緩めた副作用で「別rootの同名録画」を掴むと、別の素材を指したまま焼き込みも
    文字起こしも走ってしまう。優先順位は必ずmp4自身のroot。"""
    other_root = tmp_root.parent / "other"
    mp4, session = build_recording(tmp_root)
    _other_mp4, other_session = build_recording(other_root)

    layout.set_record_roots([other_root, tmp_root])   # わざとotherを先頭にする
    try:
        assert hls_source.session_dir_for(mp4) == session
        assert hls_source.session_dir_for(mp4) != other_session
    finally:
        layout.reset_record_roots()
