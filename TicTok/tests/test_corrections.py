"""文字起こしの訂正: 重ね合わせ・語枠への反映・再文字起こし時の引き継ぎ/破棄。"""
import pytest

from tictok.record.corrections import apply_to_segments, rematch, remap_words


def _words(*pairs):
    return [{"start": start, "end": start + 0.1, "text": text} for start, text in pairs]


# ===== 語枠への反映 =====


def test_remap_words_keeps_untouched_words_and_inherits_span_of_replaced_run():
    words = _words((1.0, "え、"), (1.2, "これ"), (1.4, "いつ"), (1.6, "け"),
                   (1.8, "貢"), (2.0, "献"))
    out = remap_words(words, "え、これいつけ貢献", "え、これ一気に貢献")
    assert "".join(w["text"] for w in out) == "え、これ一気に貢献"
    # 触れていない語はそのまま
    assert out[0] == words[0] and out[1] == words[1]
    # 置換された連なりは、置き換えた元の連なりのspanをそのまま継ぐ
    replaced = out[2]
    assert replaced["text"] == "一気に"
    assert replaced["start"] == words[2]["start"]
    assert replaced["end"] == words[3]["end"]


def test_remap_words_keeps_insertion_at_a_word_boundary():
    """語と語のちょうど境目に入る文字を落とさない。

    文字位置の対応表で実装すると、境目の挿入がどちらの語の受け持ちにもならず黙って
    消える(実測1,069件中112件)。ここが回帰していないことを守る。
    """
    words = _words((1.0, "くれた"), (1.3, "ん"), (1.6, "ね"), (1.9, "ー"))
    out = remap_words(words, "くれたんねー", "くれたんだねー")
    assert "".join(w["text"] for w in out) == "くれたんだねー"


def test_remap_words_drops_deleted_run_entirely():
    words = _words((1.0, "あ"), (1.2, "えー"), (1.4, "っと"))
    out = remap_words(words, "あえーっと", "あっと")
    assert "".join(w["text"] for w in out) == "あっと"
    assert all(w["text"] for w in out)


def test_remap_words_refuses_when_words_do_not_join_to_the_source():
    """語の連結が原文と違えば貼り直さない（別の語の時刻へ訂正が乗るため）。"""
    words = _words((1.0, "ええ"), (1.2, "うれしい"))
    assert remap_words(words, "ええうれしい�しい", "ええ嬉しい") is None


# ===== segmentへの重ね合わせ =====


def _segment(start, text, words=None):
    seg = {"start": start, "end": start + 2.0, "text": text}
    if words:
        seg["words"] = words
    return seg


def test_apply_replaces_text_and_words_without_moving_any_timestamp():
    segments = [_segment(10.0, "サイウスちゃん",
                         _words((10.0, "サイ"), (10.3, "ウス"), (10.6, "ちゃん")))]
    result = apply_to_segments(segments, [
        {"start": 10.0, "src": "サイウスちゃん", "dst": "サイフォスちゃん"}])
    assert result["applied"] == 1 and result["orphans"] == []
    seg = result["segments"][0]
    assert seg["text"] == "サイフォスちゃん"
    assert "".join(w["text"] for w in seg["words"]) == "サイフォスちゃん"
    assert (seg["start"], seg["end"]) == (10.0, 12.0)
    for word in seg["words"]:
        assert seg["start"] <= word["start"] <= word["end"] <= seg["end"]
    # 生のsegmentは書き換えない
    assert segments[0]["text"] == "サイウスちゃん"


def test_apply_drops_words_when_they_cannot_be_remapped():
    segments = [_segment(10.0, "ええうれしい�しい",
                         _words((10.0, "ええ"), (10.3, "うれしい")))]
    result = apply_to_segments(segments, [
        {"start": 10.0, "src": "ええうれしい�しい", "dst": "ええ嬉しい"}])
    seg = result["segments"][0]
    assert seg["text"] == "ええ嬉しい"
    assert "words" not in seg
    assert result["words_dropped"] == 1


def test_apply_needs_both_time_and_text_to_match():
    segments = [_segment(10.0, "うん"), _segment(300.0, "うん")]
    # 原文は合うが時刻が遠い
    assert apply_to_segments(segments, [
        {"start": 150.0, "src": "うん", "dst": "うーん"}])["applied"] == 0
    # 時刻は合うが原文が違う
    assert apply_to_segments(segments, [
        {"start": 10.0, "src": "はい", "dst": "うーん"}])["applied"] == 0
    # 両方合えば当たる。当たるのは近い方だけで、同じ語の別の発話は巻き込まない
    result = apply_to_segments(segments, [
        {"start": 10.4, "src": "うん", "dst": "うーん"}])
    assert [s["text"] for s in result["segments"]] == ["うーん", "うん"]


def test_apply_does_not_put_two_corrections_on_the_same_segment():
    """言い直しが並ぶ区間で、同じsegmentへ複数の訂正が乗らない。"""
    segments = [_segment(10.0, "トイリ"), _segment(11.0, "トイリ")]
    result = apply_to_segments(segments, [
        {"start": 10.0, "src": "トイリ", "dst": "トイレ"},
        {"start": 10.1, "src": "トイリ", "dst": "トイレ行きたい"}])
    assert [s["text"] for s in result["segments"]] == ["トイレ", "トイレ行きたい"]


def test_apply_returns_unmatched_corrections_as_orphans():
    result = apply_to_segments([_segment(10.0, "うん")], [
        {"start": 900.0, "src": "どこにも無い", "dst": "x"}])
    assert result["applied"] == 0
    assert [c["src"] for c in result["orphans"]] == ["どこにも無い"]


# ===== 再文字起こし後の貼り直し =====


def test_rematch_follows_the_segment_even_when_its_time_shifted_slightly():
    corrections = [{"id": 7, "start": 10.0, "src": "サイウスちゃん", "dst": "サイフォスちゃん"}]
    result = rematch([_segment(11.5, "サイウスちゃん")], corrections)
    assert result["matched"] == [(7, 11.5)]
    assert result["orphaned"] == []


def test_rematch_orphans_a_correction_whose_source_text_changed():
    corrections = [{"id": 7, "start": 10.0, "src": "サイウスちゃん", "dst": "サイフォスちゃん"}]
    result = rematch([_segment(10.0, "サイフォースちゃん")], corrections)
    assert result["matched"] == []
    assert result["orphaned"] == [7]


# ===== DB層 =====


@pytest.fixture
def recording(tmp_db, make_session):
    session_id = make_session("pomiiiip", status="connected")
    return tmp_db.create_recording(session_id, "pomiiiip", "/a.mp4", "a.mp4", "hd", 1.0)


def _save(tmp_db, recording, texts, **kwargs):
    tmp_db.save_transcript(recording, {
        "text": "".join(t for _, t in texts),
        "segments": [_segment(start, text) for start, text in texts],
        "duration": 100.0, "timemap_version": 2,
    }, **kwargs)


def test_get_transcript_overlays_corrections_and_raw_bypasses_them(tmp_db, recording):
    _save(tmp_db, recording, [(10.0, "サイウスちゃん")])
    tmp_db.upsert_corrections(recording, [
        {"start": 10.0, "src": "サイウスちゃん", "dst": "サイフォスちゃん",
         "origin": "ai", "confidence": "高", "note": "視聴者名"}])

    got = tmp_db.get_transcript(recording)
    assert got["segments"][0]["text"] == "サイフォスちゃん"
    assert got["text"] == "サイフォスちゃん"
    assert got["corrections_applied"] == 1

    raw = tmp_db.get_transcript(recording, raw=True)
    assert raw["segments"][0]["text"] == "サイウスちゃん"
    assert raw["corrections_applied"] == 0


def test_upsert_is_idempotent_and_refuses_a_non_correction(tmp_db, recording):
    row = {"start": 10.0, "src": "あ", "dst": "ああ"}
    assert tmp_db.upsert_corrections(recording, [row])["added"] == 1
    assert tmp_db.upsert_corrections(recording, [row])["added"] == 0
    assert len(tmp_db.list_corrections(recording)) == 1
    with pytest.raises(ValueError):
        tmp_db.upsert_corrections(recording, [{"start": 1.0, "src": "あ", "dst": "あ"}])


def test_retranscribe_keeps_corrections_by_default(tmp_db, recording):
    _save(tmp_db, recording, [(10.0, "サイウスちゃん")])
    tmp_db.upsert_corrections(recording, [
        {"start": 10.0, "src": "サイウスちゃん", "dst": "サイフォスちゃん"}])

    # 同じ発話が少しずれた時刻で出てきた
    _save(tmp_db, recording, [(11.2, "サイウスちゃん")])
    assert tmp_db.get_transcript(recording)["segments"][0]["text"] == "サイフォスちゃん"
    assert tmp_db.list_corrections(recording)[0]["start"] == 11.2


def test_retranscribe_holds_a_correction_it_cannot_place(tmp_db, recording):
    _save(tmp_db, recording, [(10.0, "サイウスちゃん")])
    tmp_db.upsert_corrections(recording, [
        {"start": 10.0, "src": "サイウスちゃん", "dst": "サイフォスちゃん"}])

    # modelが変わって原文が別の形になった
    _save(tmp_db, recording, [(10.0, "サイフォースちゃん")])
    held = tmp_db.list_corrections(recording)
    assert [c["state"] for c in held] == ["orphan"]
    # 保留は本文へ当てない。近い行へ寄せもしない
    assert tmp_db.get_transcript(recording)["segments"][0]["text"] == "サイフォースちゃん"


def test_retranscribe_can_discard_corrections_without_deleting_them(tmp_db, recording):
    _save(tmp_db, recording, [(10.0, "サイウスちゃん")])
    tmp_db.upsert_corrections(recording, [
        {"start": 10.0, "src": "サイウスちゃん", "dst": "サイフォスちゃん"}])

    _save(tmp_db, recording, [(10.0, "サイウスちゃん")], corrections="discard")
    assert tmp_db.get_transcript(recording)["segments"][0]["text"] == "サイウスちゃん"
    assert tmp_db.list_corrections(recording) == []
    kept = tmp_db.list_corrections(recording, states=("discarded",))
    assert [c["dst"] for c in kept] == ["サイフォスちゃん"]


def test_corrections_go_away_with_the_recording(tmp_db, recording):
    _save(tmp_db, recording, [(10.0, "あ")])
    tmp_db.upsert_corrections(recording, [{"start": 10.0, "src": "あ", "dst": "ああ"}])
    tmp_db.delete_recording(recording)
    assert tmp_db.list_corrections(recording) == []
