import pytest

from tictok.core import config
from tictok.media import hls_source
from tictok.record import telop_styles
from tictok.record import video_overlay as vo
from tictok.record.recorder import timing_path


# ===== ASS primitives =====


def test_ass_timestamp_formats_and_clamps():
    assert vo._ass_timestamp(0.0) == "0:00:00.00"
    assert vo._ass_timestamp(-3.0) == "0:00:00.00"
    assert vo._ass_timestamp(3661.23) == "1:01:01.23"
    assert vo._ass_timestamp(0.999) == "0:00:01.00"
    assert vo._ass_timestamp(59.995) == "0:01:00.00"


def test_ass_escape_neutralizes_override_syntax():
    assert vo._ass_escape("{\\pos}\nx") == "(/pos) x"
    assert vo._ass_escape("  hi\r  ") == "hi"
    assert vo._ass_escape(None) == ""
    assert vo._ass_escape("") == ""


def test_ass_bgr_and_back_roundtrip():
    assert vo._ass_bgr("#F5A60A") == "&H0AA6F5&"
    assert vo._ass_bgr("f5a60a") == "&H0AA6F5&"
    assert vo._ass_color_to_rgb(vo._ass_bgr("#F5A60A")) == (0xF5, 0xA6, 0x0A)
    for literal in vo._AVATAR_COLORS:
        r, g, b = vo._ass_color_to_rgb(literal)
        assert 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255


def test_fmt_clock():
    assert vo._fmt_clock(0) == "0:00"
    assert vo._fmt_clock(-9) == "0:00"
    assert vo._fmt_clock(65.6) == "1:06"
    assert vo._fmt_clock(600) == "10:00"


def test_round_rect_path_rounds_only_requested_corners():
    both = vo._round_rect_path(0, 0, 100, 20, 6, left=True, right=True)
    left_only = vo._round_rect_path(0, 0, 100, 20, 6, left=True, right=False)
    neither = vo._round_rect_path(0, 0, 100, 20, 6, left=False, right=False)
    assert both.startswith("m ")
    assert both.count("b ") == 4
    assert left_only.count("b ") == 2
    assert neither.count("b ") == 0
    # radius is clamped to half the smaller side, so a huge r cannot invert the path
    clamped = vo._round_rect_path(0, 0, 100, 20, 999, left=True, right=True)
    assert "b 0 20 0 20 0 10" in clamped


# ===== text measuring / wrapping =====


def test_estimate_width_separates_wide_and_narrow():
    assert vo._estimate_width("abc", 10) == pytest.approx(3 * vo.NOMINAL_NARROW_EM * 10)
    assert vo._estimate_width("あ", 10) == pytest.approx(vo.NOMINAL_WIDE_EM * 10)
    assert vo._estimate_width("", 10) == 0.0


def test_truncate_adds_ellipsis_only_when_needed():
    full = vo._estimate_width("abcdef", 10)
    assert vo._truncate("abcdef", 10, full) == "abcdef"
    assert vo._truncate("abcdef", 10, 20) == "ab…"
    # max_w <= 0 disables truncation entirely rather than returning a bare ellipsis
    assert vo._truncate("abcdef", 10, 0) == "abcdef"


def test_wrap_text_breaks_at_spaces_for_ascii():
    assert vo._wrap_text("aaaa bbbb", 10, 5 * vo.NOMINAL_NARROW_EM * 10) == ["aaaa", "bbbb"]


def test_wrap_text_breaks_per_character_for_cjk():
    assert vo._wrap_text("あいうえお", 10, 25) == ["あい", "うえ", "お"]


def test_wrap_text_degenerate_inputs():
    assert vo._wrap_text("", 10, 100) == [""]
    assert vo._wrap_text("abc", 10, 0) == ["abc"]
    # a single unbreakable run longer than the line still gets split (never dropped)
    lines = vo._wrap_text("aaaaaa", 10, 11)
    assert "".join(lines) == "aaaaaa"
    assert all(vo._estimate_width(ln, 10) <= 11 for ln in lines)


# ===== unicode sanitising / emoji clustering =====


def test_strip_bidi_controls_keeps_emoji_joiners():
    assert vo._strip_bidi_controls("a‪b") == "ab"
    assert vo._strip_bidi_controls("‍") == "‍"
    assert vo._strip_bidi_controls(None) == ""
    assert vo._strip_bidi_controls("️") == "️"


def test_tokenize_emoji_clusters():
    assert vo._tokenize_emoji("a\U0001F44Db") == [
        ("text", "a"), ("emoji", "\U0001F44D"), ("text", "b")]
    assert vo._tokenize_emoji("\U0001F468‍\U0001F469") == [
        ("emoji", "\U0001F468‍\U0001F469")]
    assert vo._tokenize_emoji("\U0001F44D\U0001F44D") == [
        ("emoji", "\U0001F44D"), ("emoji", "\U0001F44D")]
    # skin tone modifier is absorbed by the preceding base
    assert vo._tokenize_emoji("\U0001F44D\U0001F3FD") == [
        ("emoji", "\U0001F44D\U0001F3FD")]
    # a dangling ZWJ is absorbed by the preceding base rather than left as text
    assert vo._tokenize_emoji("\U0001F44D‍") == [("emoji", "\U0001F44D‍")]


def test_tokenize_emoji_keeps_zwj_sequences_in_one_cluster():
    woman_tech = "\U0001F469‍\U0001F4BB"
    assert vo._tokenize_emoji(woman_tech) == [("emoji", woman_tech)]
    heart_fire = "❤️‍\U0001F525"
    assert vo._tokenize_emoji(heart_fire) == [("emoji", heart_fire)]
    family = "\U0001F468‍\U0001F469‍\U0001F467‍\U0001F466"
    assert vo._tokenize_emoji(family) == [("emoji", family)]
    assert vo._emoji_units("a" + family) == [("text", "a"), ("emoji", family)]
    # the ZWJ branch must not swallow codepoints the base predicate rejects
    assert vo._tokenize_emoji(woman_tech, is_base=lambda cp: cp == 0x1F469) == [
        ("emoji", "\U0001F469‍"), ("text", "\U0001F4BB")]


def test_tokenize_emoji_non_zwj_clusters_unchanged():
    # skin tone modifier, VS16 alone and a regional-indicator flag pair must keep
    # tokenising exactly as before the ZWJ fix
    assert vo._tokenize_emoji("\U0001F44F\U0001F3FF") == [
        ("emoji", "\U0001F44F\U0001F3FF")]
    assert vo._tokenize_emoji("❤️") == [("emoji", "❤️")]
    assert vo._tokenize_emoji("\U0001F1EF\U0001F1F5") == [
        ("emoji", "\U0001F1EF"), ("emoji", "\U0001F1F5")]
    assert vo._tokenize_emoji("\U0001F1EF\U0001F1F5‍") == [
        ("emoji", "\U0001F1EF"), ("emoji", "\U0001F1F5‍")]


def test_emoji_units_splits_text_per_character():
    assert vo._emoji_units("ab\U0001F44D") == [
        ("text", "a"), ("text", "b"), ("emoji", "\U0001F44D")]


def test_tokenize_emoji_respects_custom_base_predicate():
    # the shaper passes a coverage-aware predicate; range codepoints it rejects must
    # stay in text runs instead of vanishing as a blank tile
    tokens = vo._tokenize_emoji("☀x", is_base=lambda cp: False)
    assert tokens == [("text", "☀x")]


# ===== comment feed geometry =====


def test_comment_metrics_are_internally_consistent():
    m = vo._comment_metrics(720, 1280, 32)
    assert m["x_text"] == m["x_left"] + m["avatar_d"] + m["gap"]
    assert m["text_max_w"] > 0
    assert m["band_top"] < m["y_bottom"]
    assert m["fade_height"] >= 2 * m["line_h"]
    assert m["avatar_d"] == 2 * m["avatar_r"]


def test_pos_alpha_fade_zone_boundaries():
    assert vo._pos_alpha(200.0, 100.0, 50.0) == 1.0
    assert vo._pos_alpha(150.0, 100.0, 50.0) == 1.0
    assert vo._pos_alpha(125.0, 100.0, 50.0) == pytest.approx(0.5)
    assert vo._pos_alpha(100.0, 100.0, 50.0) == 0.0
    assert vo._pos_alpha(10.0, 100.0, 50.0) == 0.0
    assert vo._pos_alpha(0.0, 100.0, 0.0) == 1.0


def _comment(offset, text="hello", nick="Alice", user_id="u1"):
    return {"offset": offset, "text": text, "nick": nick, "user_id": user_id}


def test_layout_comment_feed_single_comment_holds_until_end():
    m = vo._comment_metrics(720, 1280, 32)
    placed = vo._layout_comment_feed([_comment(5.0)], m, 32, 30.0, set())
    assert len(placed) == 1
    p = placed[0]
    assert p["initial"] == "A"
    assert p["has_avatar"] is False
    assert p["empty"] is False
    seg = p["segments"][0]
    assert len(p["segments"]) == 1
    assert seg["start"] == 5.0
    assert seg["end"] == 30.0
    assert seg["prev_top"] == m["y_bottom"]
    assert seg["top"] == m["y_bottom"] - p["block_h"]
    assert seg["fad_in"] == 150
    assert seg["tail"] is True


def test_layout_comment_feed_stacks_newer_below_older():
    m = vo._comment_metrics(720, 1280, 32)
    placed = vo._layout_comment_feed(
        [_comment(5.0, nick="Alice"), _comment(10.0, nick="Bob")], m, 32, 30.0, set())
    older, newer = placed
    assert len(older["segments"]) == 2
    # the older comment is pushed up by the newer block plus the vertical gap
    assert older["segments"][1]["top"] == (
        older["segments"][0]["top"] - newer["block_h"] - m["gap_v"])
    assert older["segments"][0]["end"] == 10.0
    assert older["segments"][1]["fad_in"] == 0
    # the newest comment occupies the bottom slot
    assert newer["segments"][0]["top"] == m["y_bottom"] - newer["block_h"]


def test_layout_comment_feed_stops_when_scrolled_off_the_band():
    m = vo._comment_metrics(720, 1280, 32)
    comments = [_comment(float(i)) for i in range(40)]
    placed = vo._layout_comment_feed(comments, m, 32, 100.0, set())
    oldest = placed[0]
    assert len(oldest["segments"]) < len(comments)
    assert all(s["top"] > m["band_top"] or s is oldest["segments"][0]
               for s in oldest["segments"])
    # the last emitted segment is either faded out or the band edge
    assert oldest["segments"][-1]["grad"] <= 1.0


def test_layout_comment_feed_flags_avatar_and_empty():
    m = vo._comment_metrics(720, 1280, 32)
    placed = vo._layout_comment_feed(
        [_comment(1.0, user_id="u1"), _comment(2.0, text="", nick="", user_id="u2")],
        m, 32, 10.0, {"u1"})
    assert placed[0]["has_avatar"] is True
    assert placed[1]["has_avatar"] is False
    assert placed[1]["empty"] is True
    assert placed[1]["initial"] == "?"


def test_layout_comment_feed_caps_body_lines_to_the_band():
    m = vo._comment_metrics(720, 1280, 32)
    max_body_lines = max(1, (m["y_bottom"] - m["band_top"]) // m["line_h"] - 1)
    placed = vo._layout_comment_feed([_comment(1.0, text="あ" * 400)], m, 32, 10.0, set())
    assert len(placed[0]["body_lines"]) == max_body_lines


# ===== gift band layout =====


def _gift(offset, diamonds=1, nick="fan", gift_id=100):
    return {"offset": offset, "diamonds": diamonds, "nick": nick,
            "gift_id": gift_id, "gift_name": "Rose", "image": "http://x/i.png"}


def test_build_gift_layout_assigns_distinct_slots():
    texts, overlays = vo._build_gift_layout(
        [_gift(0.0), _gift(1.0), _gift(2.0)], 720, 1280, 30, 100, 10)
    assert len(texts) == 3 and len(overlays) == 3
    ys = [o["y"] for o in overlays]
    assert len(set(ys)) == 3
    assert all(o["x_rest"] == max(8, round(720 * 0.025)) for o in overlays)


def test_build_gift_layout_truncates_previous_occupant_on_slot_reuse():
    # 5 gifts, 4 slots: the 5th evicts the oldest, whose end must be pulled back to
    # the new gift's start so two labels never share a slot at the same instant.
    gifts = [_gift(float(i)) for i in range(4)] + [_gift(4.0)]
    _texts, overlays = vo._build_gift_layout(gifts, 720, 1280, 30, 100, 10)
    by_start = {o["start"]: o for o in overlays}
    assert by_start[0.0]["end"] == 4.0
    assert by_start[4.0]["start"] == 4.0
    # no two overlays in the same slot (same y) overlap in time
    for y in {o["y"] for o in overlays}:
        same = sorted((o for o in overlays if o["y"] == y), key=lambda o: o["start"])
        for a, b in zip(same, same[1:]):
            assert a["end"] <= b["start"]


def test_build_gift_layout_drops_zero_length_entries():
    # all 5 at the same instant: the evicted one collapses to zero length and is skipped
    gifts = [_gift(0.0) for _ in range(5)]
    texts, overlays = vo._build_gift_layout(gifts, 720, 1280, 30, 100, 10)
    assert len(texts) == 4
    assert len(overlays) == 4


def test_build_gift_layout_label_and_unidentifiable_gift():
    texts, overlays = vo._build_gift_layout(
        [{"offset": 0.0, "diamonds": 1234, "nick": "fan"}], 720, 1280, 30, 100, 10)
    # no gift_id/name/image -> a text label only, no icon overlay spec
    assert overlays == []
    assert "1,234 (fan)" in texts[0]
    assert "\\pos(" in texts[0]

    texts_named, overlays_named = vo._build_gift_layout(
        [_gift(0.0, diamonds=5, nick="")], 720, 1280, 30, 100, 10)
    assert len(overlays_named) == 1
    assert "\\move(" in texts_named[0]
    # a slide-in never starts off-frame
    assert "\\move(0," in texts_named[0] or "\\move(%d," % max(8, round(720 * 0.025)) in texts_named[0]


# ===== timing: media -> pts =====


def test_media_pts_mapper_interpolates_and_clamps():
    to_pts = vo._media_pts_mapper([(0.0, 0.0), (10.0, 11.0), (20.0, 22.0)])
    assert to_pts(0.0) == 0.0
    assert to_pts(5.0) == pytest.approx(5.5)
    assert to_pts(15.0) == pytest.approx(16.5)
    assert to_pts(-100.0) == 0.0
    assert to_pts(1000.0) == 22.0


def test_media_pts_mapper_is_monotonic():
    to_pts = vo._media_pts_mapper([(0.0, 0.0), (10.0, 11.0), (20.0, 22.0)])
    values = [to_pts(x / 10.0) for x in range(0, 250)]
    assert values == sorted(values)


def test_detect_media_breaks_ignores_genuine_freeze():
    # media advances in step with wall -> a freeze, not a source-timestamp glitch
    assert vo._detect_media_breaks([0.0, 100.0], [0.0, 100.0]) == []
    # media jumps 190s while only 1s of wall passed -> break
    breaks = vo._detect_media_breaks([0.0, 10.0, 11.0, 21.0], [0.0, 10.0, 200.0, 210.0])
    assert breaks == [(10.0, 200.0)]


def test_detect_media_breaks_below_min_seconds_is_jitter():
    # a 20s media jump is under PTS_DISCONTINUITY_MIN_SECONDS, so not a break
    assert vo._detect_media_breaks([0.0, 1.0], [0.0, 20.0]) == []


def test_media_to_pts_uses_one_scale_without_discontinuities():
    to_pts = vo._media_to_pts([0.0, 100.0], [0.0, 100.0], 110.0, None)
    assert to_pts(50.0) == pytest.approx(55.0)
    assert to_pts(100.0) == pytest.approx(110.0)


def test_media_to_pts_is_identity_without_a_video_duration():
    to_pts = vo._media_to_pts([0.0, 100.0], [0.0, 100.0], None, None)
    assert to_pts(42.0) == 42.0


def test_media_to_pts_pins_a_break_to_the_matching_mp4_gap():
    medias = [0.0, 10.0, 200.0, 210.0]
    walls = [0.0, 10.0, 11.0, 21.0]
    to_pts = vo._media_to_pts(medias, walls, 212.0, [(12.0, 202.0)])
    # each clean region gets its own scale instead of smearing the gap globally
    assert to_pts(5.0) == pytest.approx(6.0)
    assert to_pts(10.0) == pytest.approx(12.0)
    assert to_pts(200.0) == pytest.approx(202.0)
    assert to_pts(205.0) == pytest.approx(207.0)


def test_media_to_pts_falls_back_when_no_gap_matches():
    medias = [0.0, 10.0, 200.0, 210.0]
    walls = [0.0, 10.0, 11.0, 21.0]
    to_pts = vo._media_to_pts(medias, walls, 212.0, [(12.0, 15.0)])
    # unmatched break -> a single endpoint-pinned scale, still monotonic and bounded
    assert to_pts(0.0) == 0.0
    assert to_pts(210.0) == pytest.approx(212.0)
    assert to_pts(105.0) == pytest.approx(212.0 * 105.0 / 210.0)


# ===== timing: wall -> pts =====


def test_anchor_mappers_interpolate_wall_to_media():
    wall_to_media, media_to_pts = vo._anchor_mappers(
        [(1000.0, 0.0), (1100.0, 100.0)], 1000.0, 1100.0, 110.0)
    assert wall_to_media(1050.0) == pytest.approx(50.0)
    assert wall_to_media(900.0) == 0.0
    assert wall_to_media(9999.0) == 100.0
    assert media_to_pts(50.0) == pytest.approx(55.0)


def test_anchor_mappers_prefer_exact_media_pts_over_the_scale_model():
    _wall_to_media, media_to_pts = vo._anchor_mappers(
        [(1000.0, 0.0), (1100.0, 100.0)], 1000.0, 1100.0, 110.0,
        media_pts=[(0.0, 0.0), (50.0, 51.0), (100.0, 110.0)])
    # per-segment correspondence, not the global 1.1x scale
    assert media_to_pts(50.0) == pytest.approx(51.0)


def test_anchor_mappers_without_anchors_fit_the_capture_window():
    wall_to_media, media_to_pts = vo._anchor_mappers(None, 100.0, 200.0, 50.0)
    assert wall_to_media(150.0) == pytest.approx(25.0)
    assert media_to_pts(25.0) == 25.0


def test_anchor_mappers_last_resort_is_the_raw_wall_offset():
    wall_to_media, media_to_pts = vo._anchor_mappers(None, 100.0, None, None)
    assert wall_to_media(160.0) == 60.0
    assert media_to_pts(60.0) == 60.0


def test_make_time_mapper_composes_both_halves():
    to_pts = vo._make_time_mapper(
        [(1000.0, 0.0), (1100.0, 100.0)], 1000.0, 1100.0, 110.0)
    assert to_pts(1050.0) == pytest.approx(55.0)
    assert to_pts(1000.0) == 0.0


# ===== timing: Mode B source clock =====


def test_live_create_samples_drops_the_connection_backlog():
    events = [
        {"time": 100.0, "create_time": 99.0},
        {"time": 100.0, "create_time": 50.0},   # backlog flush, far in the past
        {"time": 90.0, "create_time": 89.5},
        {"time": 95.0},                          # no create_time
        {"create_time": 95.0},                   # no arrival
    ]
    assert vo._live_create_samples(events) == [(90.0, 89.5), (100.0, 99.0)]


def test_make_source_mappers_returns_none_without_enough_samples():
    events = [{"time": 1000.0 + i, "create_time": 1500.0 + i} for i in range(4)]
    assert vo._make_source_mappers(events, None, 1000.0, None, None) is None


def test_make_source_mappers_anchors_origin_and_matches_mode_a_at_the_start():
    events = [{"time": 1000.0 + i, "create_time": 1500.0 + i} for i in range(6)]
    src = vo._make_source_mappers(events, None, 1000.0, None, None)
    assert src is not None
    assert src["c_value"] == pytest.approx(1500.0)
    assert src["n_samples"] == 6
    assert src["n_backlog"] == 0
    # create_time -> pts equals the Mode A arrival offset while the two clocks agree
    assert src["source_to_pts"](1502.0) == pytest.approx(2.0)
    assert src["wall_to_pts"](1002.0) == pytest.approx(2.0)


def test_make_source_mappers_counts_but_excludes_the_backlog():
    events = [{"time": 1000.0 + i, "create_time": 1500.0 + i} for i in range(6)]
    events.append({"time": 1000.0, "create_time": 900.0})
    src = vo._make_source_mappers(events, None, 1000.0, None, None)
    assert src["n_backlog"] == 1
    assert src["n_samples"] == 6
    assert src["c_value"] == pytest.approx(1500.0)


def test_make_source_mappers_extrapolates_the_wall_bridge_outside_the_samples():
    events = [{"time": 1000.0 + i, "create_time": 1500.0 + i} for i in range(6)]
    src = vo._make_source_mappers(events, None, 1000.0, None, None)
    # beyond the last sample the bridge continues at 1:1 rather than saturating
    assert src["wall_to_pts"](1100.0) == pytest.approx(100.0)
    assert src["wall_to_pts"](900.0) == pytest.approx(-100.0)


# ===== score bar helpers =====


def test_sample_lanes_sums_scores_per_side_and_pads_absentees():
    sample = {"parts": [{"id": "a", "score": 3}, {"id": "b", "score": 5}]}
    lanes = vo._sample_lanes(sample, [(["a", "b"], True), (["c"], False)])
    assert lanes == [(8, True), (0, False)]


def test_proportional_widths_keeps_every_side_wide_enough_for_its_icon():
    """scoreがどれだけ離れてもsegmentは最小幅までしか痩せない(潰れると陣営が名乗れない)。
    削られるのは余裕のある側で、合計は常にbar幅のまま。"""
    w = vo._proportional_widths([1, 9999], 1000.0, 100.0)
    assert w[0] == pytest.approx(100.0)
    assert sum(w) == pytest.approx(1000.0)
    # 最小幅に当たらない配分は score の比のまま。
    assert vo._proportional_widths([3, 1], 1000.0, 100.0) == \
        [pytest.approx(750.0), pytest.approx(250.0)]
    # 複数のsegmentが最小幅に当たっても、残りは残score比で割れる。
    w = vo._proportional_widths([0, 1, 40, 59], 1000.0, 100.0)
    assert w[0] == pytest.approx(100.0) and w[1] == pytest.approx(100.0)
    assert w[2] == pytest.approx(800.0 * 40 / 99)
    assert sum(w) == pytest.approx(1000.0)


def test_proportional_widths_falls_back_to_an_even_split():
    """全員ぶんの最小幅が取れない狭さ、または全score=0(開始直後)なら均等割り。"""
    assert vo._proportional_widths([5, 1], 100.0, 60.0) == \
        [pytest.approx(50.0), pytest.approx(50.0)]
    assert vo._proportional_widths([0, 0, 0], 900.0, 100.0) == \
        [pytest.approx(300.0)] * 3
    assert vo._proportional_widths([], 900.0, 100.0) == []


def test_step_xexpr_collapses_repeated_positions():
    assert vo._step_xexpr([(1.0, 10), (2.0, 10), (3.0, 20)]) == \
        "if(lt(t\\,2.000)\\,10\\,20)"
    assert vo._step_xexpr([(5.0, 7)]) == "7"


def test_battle_mode_label_uses_participants_not_the_stored_type():
    personal = {"type": "team", "participants": [
        {"user_id": "u1", "team_id": "u1", "is_own": True, "score": 9},
        {"user_id": "u2", "team_id": "u2", "score": 4},
        {"user_id": "u3", "team_id": "u3", "score": 1},
    ]}
    assert vo._battle_mode_label(personal) == "個人戦 3コラ"
    assert vo._battle_mode_label({"participants": [{"user_id": "a"}, {"user_id": "b"}]}) \
        == "個人戦 1v1"
    team = {"participants": [
        {"user_id": "u1", "team_id": "1", "is_own": True, "score": 10},
        {"user_id": "u2", "team_id": "1", "score": 5},
        {"user_id": "u3", "team_id": "2", "score": 8},
        {"user_id": "u4", "team_id": "2", "score": 3},
    ]}
    assert vo._battle_mode_label(team) == "チーム戦 2v2"


def test_bonus_task_label_only_names_a_known_condition():
    mission = {"prompts": [{"key": "pm_mt_live_match_instructions_2",
                            "fields": {"multi": "5"}}]}
    assert vo._bonus_task_label(mission) == "ギフト5個"
    assert vo._bonus_task_label({"prompts": [{"key": "pm_mt_unknown_key"}]}) == ""
    assert vo._bonus_task_label({}) == ""
    # known key without the substitution value must not print a bare template
    assert vo._bonus_task_label(
        {"prompts": [{"key": "pm_mt_live_match_instructions_2", "fields": {}}]}) == ""


# ===== encoder / dimension helpers =====


def test_parse_fps():
    assert vo._parse_fps("30000/1001") == pytest.approx(29.97, abs=0.01)
    assert vo._parse_fps("30/1") == 30.0
    assert vo._parse_fps("25") == 25.0
    assert vo._parse_fps("0/0") == vo.DEFAULT_FPS
    assert vo._parse_fps("") == vo.DEFAULT_FPS
    assert vo._parse_fps(None) == vo.DEFAULT_FPS


def test_render_dimensions_upscales_and_keeps_even():
    assert vo._render_dimensions(720, 1280, 1920) == (1080, 1920)
    # already tall enough -> untouched
    assert vo._render_dimensions(1080, 1920, 1920) == (1080, 1920)
    assert vo._render_dimensions(1080, 2400, 1920) == (1080, 2400)
    # degenerate probe result is passed through, never divided by
    assert vo._render_dimensions(0, 0, 1920) == (0, 0)
    w, h = vo._render_dimensions(719, 1280, 1921)
    assert w % 2 == 0 and h % 2 == 0
    assert w / h == pytest.approx(719 / 1280, rel=0.01)


def test_codec_family_and_encoder_family():
    assert vo.codec_family(0) == "auto"
    assert vo.codec_family(None) == "auto"
    assert vo.codec_family(1) == "h264"
    assert vo.codec_family(2) == "hevc"
    assert vo.codec_family(3) == "av1"
    assert vo.codec_family(99) == "auto"
    assert vo._encoder_family("av1_nvenc") == "av1"
    assert vo._encoder_family("libx265") == "hevc"
    assert vo._encoder_family("hevc_qsv") == "hevc"
    assert vo._encoder_family("libx264") == "h264"


def test_mapped_quality_offsets_and_clamps_per_codec():
    assert vo._mapped_quality("libx264", 23) == 23
    assert vo._mapped_quality("hevc_nvenc", 23) == 27
    assert vo._mapped_quality("av1_nvenc", 23) == 39
    assert vo._mapped_quality("av1_nvenc", 55) == 63
    assert vo._mapped_quality("libx264", -5) == 0


def test_encoder_args_carry_the_quality_for_each_backend():
    for name in ("h264_nvenc", "h264_qsv", "h264_amf", "libsvtav1", "libx265", "libx264"):
        args = vo._encoder_args(name, 27)
        assert args[0] == "-c:v" and args[1] == name
        assert "27" in args


# ===== cache signature / meta =====


def test_events_fingerprint_is_stable_and_order_sensitive():
    a = [{"a": 1, "b": 2}, {"c": 3}]
    b = [{"b": 2, "a": 1}, {"c": 3}]
    assert vo._events_fingerprint(a) == vo._events_fingerprint(b)
    assert vo._events_fingerprint(a) != vo._events_fingerprint(list(reversed(a)))
    assert vo._events_fingerprint(a) != vo._events_fingerprint(a + [{"d": 4}])
    assert vo._events_fingerprint([]) == vo._events_fingerprint([])


def _cfg():
    return {key: 0 for key in vo.OVERLAY_KEYS}


def test_signature_reacts_to_every_input_that_changes_the_output(make_recording):
    _stem, mp4 = make_recording()
    cfg = _cfg()
    base = vo._signature(mp4, cfg)
    assert vo._signature(mp4, cfg) == base

    other = dict(cfg, video_overlay_font_size=99)
    assert vo._signature(mp4, other) != base
    assert vo._signature(mp4, cfg, variant="b") != base
    assert vo._signature(mp4, cfg, events_sig="x") != base
    assert vo._signature(mp4, cfg, events_sig="x") != vo._signature(mp4, cfg, events_sig="y")
    assert vo._signature(mp4, cfg, subtitles_sig="s") != base


def test_signature_invalidates_when_the_timing_sidecar_appears(make_recording):
    _stem, mp4 = make_recording()
    cfg = _cfg()
    tpath = timing_path(mp4)
    tpath.parent.mkdir(parents=True, exist_ok=True)
    without = vo._signature(mp4, cfg, timing=tpath)
    tpath.write_text('{"anchors": [[0, 0], [1, 1]]}', encoding="utf-8")
    with_map = vo._signature(mp4, cfg, timing=tpath)
    assert with_map != without
    tpath.write_text('{"anchors": [[0, 0], [1, 1], [2, 2]]}', encoding="utf-8")
    assert vo._signature(mp4, cfg, timing=tpath) != with_map


def test_signature_invalidates_when_the_source_segments_change(make_recording):
    """焼き込みの入力は原本の .ts なので、鍵は .ts の側で動く。"""
    _stem, mp4 = make_recording()
    session = hls_source.session_dir_for(mp4)
    cfg = _cfg()
    base = vo._signature(mp4, cfg)
    (session / "seg00000.ts").write_bytes(b"\x47" * 376)
    assert vo._signature(mp4, cfg) != base


def test_signature_ignores_the_mp4_when_the_segments_are_the_source(make_recording):
    """mp4はもう焼き込みの入力ではない。書き換わってもcacheを捨てる理由にならない
    (捨てると、mp4を作り直しただけで全録画の焼き直しが走る)。"""
    _stem, mp4 = make_recording()
    cfg = _cfg()
    base = vo._signature(mp4, cfg)
    mp4.write_bytes(b"\x00" * 32)
    assert vo._signature(mp4, cfg) == base


def test_signature_falls_back_to_the_mp4_when_no_segments_remain(make_recording):
    """.tsが無い古い録画では従来どおりmp4のstatが鍵になる。"""
    _stem, mp4 = make_recording()
    session = hls_source.session_dir_for(mp4)
    for seg in session.glob("seg*.ts"):
        seg.unlink()
    cfg = _cfg()
    base = vo._signature(mp4, cfg)
    mp4.write_bytes(b"\x00" * 32)
    assert vo._signature(mp4, cfg) != base


def test_read_meta_distinguishes_miss_from_a_non_audio_only_hit(tmp_path):
    meta = tmp_path / "x.meta"
    assert vo._read_meta(meta, "sig") is None
    meta.write_text("sig\n", encoding="utf-8")
    assert vo._read_meta(meta, "sig") is False
    assert vo._read_meta(meta, "other") is None
    meta.write_text(f"sig\n{vo.AUDIO_ONLY_MARK}\n", encoding="utf-8")
    assert vo._read_meta(meta, "sig") is True
    meta.write_text("", encoding="utf-8")
    assert vo._read_meta(meta, "sig") is None


# ===== artifact paths =====


def test_overlay_paths_keep_output_beside_source_and_artifacts_in_sidecars(make_recording):
    _stem, mp4 = make_recording()
    out, ass, meta = vo.overlay_paths(mp4)
    assert out.parent == mp4.parent
    assert out.name == mp4.stem + vo.OVERLAY_SUFFIX
    assert ass.parent.name == ".sidecars"
    assert meta.parent.name == ".sidecars"
    out_b, ass_b, meta_b = vo.overlay_paths_b(mp4)
    assert len({out, ass, meta, out_b, ass_b, meta_b}) == 6


def test_overlay_artifact_and_transient_paths_do_not_overlap(make_recording):
    _stem, mp4 = make_recording()
    artifacts = set(vo.overlay_artifact_paths(mp4))
    transient = set(vo.overlay_transient_paths(mp4))
    assert artifacts and transient
    assert artifacts.isdisjoint(transient)
    assert mp4 not in artifacts and mp4 not in transient


def test_cleanup_overlay_files_removes_artifacts_but_not_the_source(make_recording):
    _stem, mp4 = make_recording()
    targets = vo.overlay_artifact_paths(mp4) + vo.overlay_transient_paths(mp4)
    for path in targets:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    vo.cleanup_overlay_files(mp4)
    assert not [p for p in targets if p.exists()]
    assert mp4.is_file()
    # idempotent: a second sweep with nothing left must not raise
    vo.cleanup_overlay_files(mp4)


# ===== settings gates =====


def test_overlay_enabled_requires_at_least_one_layer():
    off = {"video_overlay_comments": 0, "video_overlay_gifts": 0,
           "video_overlay_score_bar": 0, "video_overlay_subtitles": 0}
    settings = dict.fromkeys(vo.OVERLAY_KEYS, 0)
    settings.update(off)
    assert vo.overlay_enabled(settings) is False
    for key in off:
        one = dict(settings)
        one[key] = 1
        assert vo.overlay_enabled(one) is True


# ===== comment layer frame maths =====


def test_comment_frame_state_slides_then_settles():
    tile = object()
    live = [(tile, 10.0, 20.0, 100.0, 60.0, 150, 1.0)]
    sig_before, ops_before = vo._comment_frame_state(9.0, live, 50)
    assert ops_before == [] and sig_before == ()

    _sig, ops_start = vo._comment_frame_state(10.0, live, 50)
    assert ops_start[0][1] == 50          # still at prev_top (100) minus region_y0
    assert ops_start[0][2] == pytest.approx(0.0)  # fade-in has not started yet

    _sig, ops_mid = vo._comment_frame_state(10.075, live, 50)
    assert 10 < ops_mid[0][1] < 50

    _sig, ops_done = vo._comment_frame_state(10.2, live, 50)
    assert ops_done[0][1] == 10           # settled at top (60) minus region_y0
    assert ops_done[0][2] == pytest.approx(1.0)


def test_comment_frame_state_signature_is_stable_across_static_stretches():
    tile = object()
    live = [(tile, 10.0, 20.0, 100.0, 60.0, 0, 1.0)]
    sig_a, _ = vo._comment_frame_state(12.0, live, 50)
    sig_b, _ = vo._comment_frame_state(18.0, live, 50)
    assert sig_a == sig_b
    # a different faded opacity must change the signature (else a frame is skipped wrongly)
    faded = [(tile, 10.0, 20.0, 100.0, 60.0, 0, 0.5)]
    sig_c, _ = vo._comment_frame_state(12.0, faded, 50)
    assert sig_c != sig_a


def test_alpha_lut_scales_and_caches():
    full = vo._alpha_lut(255)
    assert full[0] == 0 and full[255] == 255 and full[128] == 128
    zero = vo._alpha_lut(0)
    assert set(zero) == {0}
    half = vo._alpha_lut(128)
    assert half[255] == 128
    assert vo._alpha_lut(128) is half


# ===== preview window selection =====


def test_preview_points_respects_the_layer_toggles_and_diamond_floor():
    rows = [
        {"kind": "comment", "offset": 1.0},
        {"kind": "gift", "offset": 2.0, "diamonds": 5},
        {"kind": "gift", "offset": 3.0, "diamonds": 1},
        {"kind": "comment", "offset": -1.0},   # before the video
        {"kind": "comment", "offset": 999.0},  # past the video
        {"kind": "comment", "offset": None},
    ]
    cfg = {"video_overlay_comments": 1, "video_overlay_gifts": 1,
           "video_overlay_gift_min_diamonds": 5, "video_overlay_score_bar": 0}
    points = vo._preview_points(rows, cfg, [], 100.0)
    assert points == [(1.0, 1.0), (2.0, vo.PREVIEW_GIFT_WEIGHT)]

    cfg_off = dict(cfg, video_overlay_comments=0, video_overlay_gifts=0)
    assert vo._preview_points(rows, cfg_off, [], 100.0) == []


def test_preview_points_samples_battle_windows_periodically():
    cfg = {"video_overlay_comments": 0, "video_overlay_gifts": 0,
           "video_overlay_gift_min_diamonds": 0, "video_overlay_score_bar": 1}
    points = vo._preview_points([], cfg, [(0.0, 45.0)], 100.0)
    assert [p[0] for p in points] == [0.0, 15.0, 30.0]
    assert all(p[1] == vo.PREVIEW_BATTLE_WEIGHT for p in points)


def test_pick_preview_window_covers_the_densest_stretch():
    points = [(50.0, 1.0), (51.0, 1.0), (52.0, 1.0), (5.0, 1.0)]
    points.sort()
    start, end = vo._pick_preview_window(points, 100.0, 10.0)
    assert start <= 50.0 and end >= 52.0
    assert end - start == pytest.approx(10.0)


def test_pick_preview_window_degenerate_inputs():
    assert vo._pick_preview_window([], 5.0, 10.0) == (0.0, 5.0)
    assert vo._pick_preview_window([], 100.0, 10.0) == (0.0, 10.0)
    # never runs past the end of the video
    start, end = vo._pick_preview_window([(99.0, 1.0)], 100.0, 10.0)
    assert end <= 100.0 and start >= 0.0


def test_comments_in_window_uses_half_open_overlap():
    plan = {"placements": [
        {"empty": False, "segments": [{"start": 10.0, "end": 20.0}]},
    ]}
    assert vo._comments_in_window(plan, (15.0, 16.0)) is True
    assert vo._comments_in_window(plan, (0.0, 10.0)) is True
    assert vo._comments_in_window(plan, (20.0, 30.0)) is False
    assert vo._comments_in_window(plan, (0.0, 5.0)) is False
    assert vo._comments_in_window(None, (0.0, 5.0)) is False
    assert vo._comments_in_window({"placements": [{"empty": True, "segments": []}]},
                                  (0.0, 100.0)) is False


def _ass_cfg(**over):
    cfg = {key: 0 for key in vo.OVERLAY_KEYS}
    cfg.update({"video_overlay_comments": 1, "video_overlay_gift_min_diamonds": 0,
                "video_overlay_min_height": 720, "video_overlay_font_size": 3,
                "video_overlay_gift_seconds": 5, "video_overlay_icon_percent": 5,
                "video_overlay_quality": 19})
    cfg.update(over)
    return cfg


def _comment_at(t, text="hi"):
    return {"kind": "comment", "time": t, "comment": text, "user_nickname": "n",
            "user_unique_id": "u"}


def test_events_after_the_material_ends_are_dropped_not_piled_on_the_last_frame():
    """録画が終わった後に届いたeventを最終frameへ積み上げない。

    wall->media mapperは補間の安全のため両端でclampする。そのままupper判定へ渡すと、
    終了後のeventが全部「最終frameちょうど」になり ``offset > upper`` を素通りする。
    実測(00346)では末尾7件がこれに当たり、mp4経由か.ts直読みかで1マイクロ秒差の偶然
    だけがdropの成否を分けていた。"""
    anchors = [[1000.0, 0.0], [1100.0, 100.0]]
    events = [_comment_at(1050.0, "in"), _comment_at(1101.0, "after"),
              _comment_at(1130.0, "well after")]
    _text, _ov, stats, _plan = vo._build_ass(
        events, 1000.0, 1100.0, 100.0, 720, 1280, _ass_cfg(), anchors, None,
        1.0, 0.5, None, None, media_pts=[(0.0, 0.0), (100.0, 100.0)],
    )
    assert stats["placed"] == 1
    assert stats["dropped_after_end"] == 2


def test_events_before_the_first_anchor_still_show_at_the_start():
    """先頭側はclampのまま残す。接続の先行ぶんだけ早く着いたcommentは冒頭に出るのが
    正しく、末尾と対称に落とすと本来映るcommentが消える。"""
    anchors = [[1000.0, 0.0], [1100.0, 100.0]]
    events = [_comment_at(995.0, "early")]
    _text, _ov, stats, _plan = vo._build_ass(
        events, 1000.0, 1100.0, 100.0, 720, 1280, _ass_cfg(), anchors, None,
        1.0, 0.5, None, None, media_pts=[(0.0, 0.0), (100.0, 100.0)],
    )
    assert stats["placed"] == 1
    assert stats["dropped_before_start"] == 0


# ===== 窓焼き込み(プレビュー / 範囲焼き込み) =====
# 窓経路は「描画planは全尺のまま組み、窓はffmpegのseekと-copytsでしか効かせない」という
# 不変条件の上に立っている。ここのtestは (1)プレビューへ出るffmpeg引数列が変わっていない
# こと (2)成果物側だけが音声・0起点・tmp→renameを足していること を固定する。


def fake_ffmpeg(monkeypatch, captured, stdout=b""):
    """vo内のffmpeg/ffprobe起動を捕まえ、出力fileだけ作る。argvは捕まえたまま返す。"""
    import types

    async def fake_exec(*cmd, **kwargs):
        captured.append([str(c) for c in cmd])
        out = vo.Path(cmd[-1])
        if out.suffix in (".mp4", ".mov", ".png"):
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"\x00" * 8)

        async def wait():
            return 0

        async def communicate():
            return stdout, b""

        return types.SimpleNamespace(returncode=0, wait=wait, communicate=communicate,
                                     stdout=None, kill=lambda: None)

    async def encoder(codec):
        return "libx264"

    monkeypatch.setattr(vo.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(vo, "video_encoder_name", encoder)
    return captured


async def test_hls_source_is_vfr_without_asking_ffprobe(tmp_path, monkeypatch):
    """HLS入力は ``avg_frame_rate`` を見ずにVFRと判定する。

    hls demuxerが返すavgはsegmentの実測平均ではなくcontainerのhintで、00398では実測
    22.10fps(283,793 packet / 12843.2s)に対して ``25/1`` を名乗った。公称
    (``r_frame_rate`` = 299/12 = 24.9167)より上なので比較式は必ずCFR側へ倒れ、CFR base
    pre-passが飛んで、24.917fps CFRのcomment層がVFRのHLSへ直接合成される。ffmpegはそれを
    rc=0のまま片側trackを途中で止める形で壊す(実測4件)。probeを引かないことまで含めて
    固定する — 引いた時点で同じ嘘を信じる余地が戻る。"""
    async def refuse(*args, **kwargs):
        raise AssertionError("HLS入力でffprobeを引いてはいけません")

    monkeypatch.setattr(vo.ffprobe, "run", refuse)
    assert await vo._probe_is_vfr(tmp_path / "src.m3u8", 24.9166666,
                                  ("-allowed_extensions", "ALL"), True) is True


async def test_mp4_source_still_decides_by_measured_average(tmp_path, monkeypatch):
    """mp4入力側の判定は据え置き。avgが公称の95%を下回るときだけVFR。"""
    import types

    async def fake_run(args, **kwargs):
        return types.SimpleNamespace(stdout=fake_run.avg, stderr="", ok=True)

    monkeypatch.setattr(vo, "ffprobe_available", lambda: True)
    monkeypatch.setattr(vo.ffprobe, "run", fake_run)
    fake_run.avg = "25/1\n"
    assert await vo._probe_is_vfr(tmp_path / "src.mp4", 24.9166666) is False
    fake_run.avg = "2210/100\n"
    assert await vo._probe_is_vfr(tmp_path / "src.mp4", 24.9166666) is True


def window_call(tmp_path, **overrides):
    """プレビューが _run_ffmpeg へ渡す形(HLS入力・窓あり・comment層なし)。"""
    kwargs = dict(
        src=tmp_path / "src.m3u8", overlays=[], icon_px=64, ass_name="x.preview.ass",
        out=tmp_path / "x.preview.mp4", cwd=tmp_path, quality=21, codec="h264",
        comment_layer=None, on_progress=None, scale_to=(720, 1280), cfr_fps=30.0,
        window=(120.0, 180.0), seek_source=True, layer_offset=0.0,
        input_args=("-allowed_extensions", "ALL"), seek_offset=1.402,
    )
    kwargs.update(overrides)
    return kwargs


async def test_preview_window_argv_is_frozen(tmp_path, monkeypatch):
    """プレビューのffmpeg引数列のsnapshot。

    範囲焼き込みの実装はこの経路を汎用化して作られている。窓経路は実測で確定したoption群
    (-copyts / 入力側の-ss+-t / -itsoffsetのmedia軸寄せ)の上に立っており、1つ動かすと
    「プレビューでは合っているのに本出力はズレる」あるいは出力が空になる。引数列そのものを
    固定して、汎用化の側から静かに変わることを防ぐ。"""
    cmds = fake_ffmpeg(monkeypatch, [])
    await vo._run_ffmpeg(**window_call(tmp_path))
    assert cmds[0] == [
        "ffmpeg", "-nostdin", "-y", "-loglevel", config.get_ffmpeg_loglevel(),
        "-allowed_extensions", "ALL", "-copyts",
        "-itsoffset", "-1.402000", "-ss", "121.402000", "-t", "60.000000",
        "-i", str(tmp_path / "src.m3u8"),
        "-filter_complex_script", str(tmp_path / "x.preview.filter.txt"),
        "-map", "[vout]", "-an",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(tmp_path / "x.preview.mp4"),
    ]


async def test_preview_window_stays_silent_even_when_a_source_is_offered(tmp_path,
                                                                        monkeypatch):
    """``audio_from`` が渡っていても ``with_audio`` が偽なら音声inputは開かない。

    comment層を合成する窓経路は常に原本のpathを持って回るため、gateがflagではなくpathの
    有無になっていると、プレビューにまで音声のinputとencodeが増える。"""
    cmds = fake_ffmpeg(monkeypatch, [])
    await vo._run_ffmpeg(**window_call(tmp_path, audio_from=tmp_path / "src.m3u8",
                                       audio_input_args=("-allowed_extensions", "ALL"),
                                       audio_seek_offset=1.402))
    assert "-an" in cmds[0]
    assert cmds[0].count("-i") == 1
    assert not [a for a in cmds[0] if a.endswith(":a?")]


async def test_clip_window_adds_audio_and_a_zero_based_output(tmp_path, monkeypatch):
    """成果物側の差分。音声は ``-map 0:a?`` だけで戻り、0起点化は ``-output_ts_offset``
    のみ(``-avoid_negative_ts``/``-muxdelay`` は使わない)。尺の切り出しは**入力側**の-tで、
    出力側へ置くと-copyts下では出力が空になる。"""
    cmds = fake_ffmpeg(monkeypatch, [])
    await vo._run_ffmpeg(**window_call(tmp_path, with_audio=True, zero_base=True))
    argv = cmds[0]
    assert "-an" not in argv
    assert argv[argv.index("-map", argv.index("[vout]")) + 1] == "0:a?"
    assert argv[argv.index("-output_ts_offset") + 1] == "-120.000000"
    assert "-avoid_negative_ts" not in argv and "-muxdelay" not in argv
    assert argv.index("-t") < argv.index("-i") and argv.count("-t") == 1
    assert "-copyts" in argv


async def test_clip_opens_the_source_for_audio_when_input0_is_the_cfr_base(tmp_path,
                                                                          monkeypatch):
    """comment層を合成する経路では input 0 が ``-an`` のCFR baseなので ``-map 0:a?`` は
    静かに空振りする。原本を**最後の**inputとして開き、そのindexへmapすること(最後で
    なければならないのは、comment層のinput番号をfilter graphが参照しているため)。"""
    cmds = fake_ffmpeg(monkeypatch, [])
    layer = (tmp_path / "x.clip.comments.mov", 0, 128, {"n_frames": 3})
    await vo._run_ffmpeg(**window_call(
        tmp_path, src=tmp_path / "base.clip.cfrbase.mp4", comment_layer=layer,
        cfr_fps=None, seek_source=False, layer_offset=120.0, input_args=(),
        seek_offset=0.0, with_audio=True, zero_base=True,
        audio_from=tmp_path / "src.m3u8",
        audio_input_args=("-allowed_extensions", "ALL"), audio_seek_offset=1.402,
        artifact_dir=tmp_path))
    argv = cmds[0]
    assert argv[argv.index("-map", argv.index("[vout]")) + 1] == "2:a?"
    inputs = [argv[i + 1] for i, a in enumerate(argv) if a == "-i"]
    assert inputs == [str(tmp_path / "base.clip.cfrbase.mp4"),
                      str(tmp_path / "x.clip.comments.mov"),
                      str(tmp_path / "src.m3u8")]
    # -ss は -itsoffset より前の時刻で解釈されるので、media offsetを足し戻している
    assert "121.402000" in argv
    assert argv[argv.index("-output_ts_offset") + 1] == "-120.000000"


async def test_clip_writes_its_work_files_under_the_recordings_sidecars(tmp_path,
                                                                       monkeypatch):
    """filter script / ffmpeg logは成果物のdirへ置かない。clips dir側へ置くと
    record_root_of がそこをrootと解釈して起動sweepの射程から外れる。"""
    sidecars = tmp_path / "sidecars"
    sidecars.mkdir()
    cmds = fake_ffmpeg(monkeypatch, [])
    await vo._run_ffmpeg(**window_call(tmp_path, out=tmp_path / "clips" / "c.tmp.mp4",
                                       with_audio=True, zero_base=True,
                                       artifact_dir=sidecars))
    assert cmds[0][cmds[0].index("-filter_complex_script") + 1] == str(
        sidecars / "c.tmp.filter.txt")
    assert not list((tmp_path / "clips").glob("*.txt"))


# ===== 明示窓 =====


def test_explicit_window_never_moves_the_in_point():
    """自動選定は尺ぶんの確認材料を確保するため窓を後ろから押し戻すが、切り抜きで同じ
    ことをすると利用者のIN点が勝手にずれる。末尾だけを素材の実尺で切る。"""
    assert vo._explicit_window((10.0, 70.0), 600.0) == (10.0, 70.0)
    assert vo._explicit_window((590.0, 700.0), 600.0) == (590.0, 600.0)
    # 尺が不明(probe不能)なら要求のまま通す
    assert vo._explicit_window((590.0, 700.0), None) == (590.0, 700.0)


def test_explicit_window_rejects_ranges_that_cannot_exist():
    for bad in ((-1.0, 10.0), (10.0, 10.0), (20.0, 10.0), (None, 10.0), ()):
        with pytest.raises(ValueError):
            vo._explicit_window(bad, 600.0)
    with pytest.raises(ValueError):
        vo._explicit_window((700.0, 800.0), 600.0)


def _window_plan_settings():
    settings = dict.fromkeys(vo.OVERLAY_KEYS, 0)
    settings.update({"video_overlay_comments": 1, "video_overlay_min_height": 720,
                     "video_overlay_quality": 21, "video_overlay_gift_seconds": 5,
                     "video_overlay_preview_seconds": 30})
    return settings


def _patch_plan_internals(monkeypatch, video_dur=600.0):
    """_preview_plan の外側(probeと配置)を固定し、窓の決め方だけを見えるようにする。"""
    ctx = {"video_dur": video_dur, "anchors": [], "media_pts": None, "pts_gaps": None,
           "src_w": 512, "src_h": 1024, "fps": 30.0, "width": 512, "height": 1024,
           "scale_to": None, "icon_px": 64, "avatar_dir": None, "wide_em": 1.0,
           "narrow_em": 0.5, "telop_em": (1.0, 0.5), "fontsdir": None,
           "quality": 21, "codec": "h264", "subtitle_segments": []}
    stats = {"comments": 1, "gifts": 0, "score": 0, "subtitles": 0}

    async def fake_ctx(*a, **kw):
        return ctx

    monkeypatch.setattr(vo, "_render_context", fake_ctx)
    monkeypatch.setattr(vo, "_build_ass",
                        lambda *a, **kw: ("[Script Info]\n", [], stats, None))
    monkeypatch.setattr(vo, "_make_time_mapper", lambda *a, **kw: (lambda t: t))
    monkeypatch.setattr(vo, "ffmpeg_available", lambda: True)
    return ctx


async def test_preview_plan_clamps_at_seconds_but_not_an_explicit_window(tmp_path,
                                                                         monkeypatch):
    """``at_seconds`` の押し戻しclampはプレビューの正しい挙動なので残し、明示窓だけが
    それを通らないこと。両者が同じ関数に同居するので、片方の変更が他方へ漏れる。"""
    _patch_plan_internals(monkeypatch, video_dur=600.0)
    source = hls_source.Source(tmp_path / "src.m3u8", (), True, 1.402)
    src = tmp_path / "rec.mp4"
    args = (src, source, _window_plan_settings(), 1000.0, 1600.0, [], None, None)

    plan = await vo._preview_plan(*args, 30.0, 590.0)
    assert plan["window"] == (570.0, 600.0)  # 尺30秒ぶんを確保するため押し戻される
    assert plan["window_auto"] is False

    plan = await vo._preview_plan(*args, 30.0, None, window=(590.0, 620.0))
    assert plan["window"] == (590.0, 600.0)  # IN点は動かさない
    assert plan["window_auto"] is False


# ===== 中間物の置き場と名前 =====


def test_clip_sidecars_are_per_output_and_live_with_the_recording(make_recording,
                                                                 tmp_path):
    """名前が録画ごとの固定名だと、同一録画の2範囲を並行renderした時に互いの中間物を
    壊し合う。置き場は元録画の .sidecars(出力先dirへは1 fileも置かない)。"""
    _stem, mp4 = make_recording()
    first = vo.clip_overlay_sidecars(mp4, tmp_path / "clips" / "a.mp4")
    second = vo.clip_overlay_sidecars(mp4, tmp_path / "clips" / "b.mp4")
    # CFR baseは中間fileでなくstream供給になったので、sidecarは(ass, layer, meta)の3つ。
    assert len(set(first) | set(second)) == 6
    for path in first + second:
        assert path.parent == vo.sidecar_dir(mp4)
        assert path.parent.name == ".sidecars"


def test_clip_intermediates_are_reachable_by_the_startup_sweep(make_recording,
                                                              tmp_path):
    """落ちたrenderが残す中間物(数十GB)を回収できる唯一の経路がsuffix sweepなので、
    範囲焼き込みのsuffixが必ずそこに載っていること。meta(cache印)は中間物ではない。"""
    from tictok.core import layout

    _stem, mp4 = make_recording()
    ass, layer, meta = vo.clip_overlay_sidecars(mp4, tmp_path / "clips" / "a.mp4")
    suffixes = vo._transient_sweep_suffixes()
    for path in (ass, layer):
        assert any(path.name.endswith(s) for s in suffixes), path.name
    assert not any(meta.name.endswith(s) for s in suffixes)

    # 旧build(中間のCFR base file)の残骸もsweepが拾えること。
    base = ass.with_name(ass.name.replace(vo.CLIP_ASS_SUFFIX, vo.CLIP_BASE_SUFFIX))
    for path in (ass, layer, base, meta):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * 4)
    removed, freed = vo.sweep_orphaned_transients([layout.record_root_of(mp4)])
    assert (removed, freed) == (3, 12)
    assert meta.is_file() and not base.exists() and not layer.exists()


def test_cleanup_removes_the_clip_markers_of_a_deleted_recording(make_recording,
                                                                tmp_path):
    """録画を消したら、その録画で作った範囲焼き込みのcache印も残さない(出力名でしか
    特定できないので、sidecar dirを掃く側で拾う)。"""
    _stem, mp4 = make_recording()
    sidecars = vo.clip_overlay_sidecars(mp4, tmp_path / "clips" / "a.mp4")
    for path in sidecars:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    vo.cleanup_overlay_files(mp4)
    assert not [p for p in sidecars if p.exists()]
    assert mp4.is_file()


# ===== 字幕の前提条件 =====


def test_burnable_transcript_refuses_a_stale_or_missing_timemap():
    """焼き込みは元に戻せないので、字幕ONで転写が無い/時刻mapが旧版/出せるsegmentが無い
    場合は字幕なしで焼かずに拒否する(本出力と同じ規則)。"""
    from tictok.record import transcription

    on = {"video_overlay_subtitles": 1}
    current = transcription.TIMEMAP_VERSION
    good = {"timemap_version": current,
            "segments": [{"start": 0.0, "end": 1.0, "text": "hi"}]}
    vo._require_burnable_transcript(on, good)
    vo._require_burnable_transcript({"video_overlay_subtitles": 0}, None)
    for bad in (None,
                {"timemap_version": None, "segments": good["segments"]},
                {"timemap_version": current + 1, "segments": good["segments"]},
                {"timemap_version": current, "segments": []}):
        with pytest.raises(vo.TranscriptNotBurnableError):
            vo._require_burnable_transcript(on, bad)
    # 呼び出し側が既に4xxへ落としている型を継いでいること
    assert issubclass(vo.TranscriptNotBurnableError, vo.NothingToDrawError)


# ===== テロップpreset =====


def _telop_cfg(**over):
    cfg = {"video_overlay_subtitles": 1, "video_overlay_subtitle_font_size": 26,
           "video_overlay_subtitle_position_percent": 58,
           "video_overlay_subtitle_style": 1, "video_overlay_subtitle_animation": 1,
           "video_overlay_subtitle_max_lines": 4}
    cfg.update(over)
    return cfg


SEGS = [{"start": 1.0, "end": 3.0, "text": "こんばんは"}]


def test_every_preset_is_selectable_and_unknown_values_are_refused():
    """未知のstyleを既定へ読み替えないこと。読み替えると、選んだのと違う書体で恒久的に
    焼き込まれる(成果物を見るまで誰も気付けない)。"""
    for value, style in telop_styles.STYLE_VALUES.items():
        assert telop_styles.style_for(value) is style
        assert telop_styles.style_for(str(value)) is style
    # 選択肢はpresetの一覧そのもの(画面用に別の一覧を持たない)
    assert [o["value"] for o in telop_styles.settings_options()] == list(
        telop_styles.STYLE_VALUES)
    for bad in (0, 99, None, "x"):
        with pytest.raises(ValueError):
            telop_styles.style_for(bad)


def test_preset_font_families_are_backed_by_a_bundled_font():
    """presetが名乗る家族名は同梱fontから解決される必要がある。manifestに無いfileを
    指したpresetは、fontsdirを渡しているのに黙ってhostのfontで焼ける。"""
    from tictok.record import fonts

    for style in telop_styles.TELOP_STYLES:
        assert style.font_file in fonts.TELOP_FONT_MANIFEST, style.key
    assert set(telop_styles.font_files()) == set(fonts.TELOP_FONT_MANIFEST)


def test_a_preset_with_a_second_border_draws_two_layers_under_the_text():
    """縁2本のpresetは1件の字幕を2行のDialogueで描く。下層が上に来ると本文が塊で
    覆われるので、layerの上下は逆にできない。"""
    style = next(s for s in telop_styles.TELOP_STYLES if s.has_glow)
    value = next(v for v, s in telop_styles.STYLE_VALUES.items() if s is style)
    lines, stats = vo._build_subtitle_dialogues(
        SEGS, 10.0, 1080, 1920, _telop_cfg(video_overlay_subtitle_style=value), 1.0, 0.5)

    assert stats["placed"] == 1 and len(lines) == 2
    edge, text = lines
    assert edge.startswith(f"Dialogue: {telop_styles.EDGE_LAYER},")
    assert text.startswith(f"Dialogue: {telop_styles.TEXT_LAYER},")
    assert telop_styles.EDGE_LAYER < telop_styles.TEXT_LAYER
    # 2層は同じ本文・同じ時刻・同じ動きで重なる(ずれると縁が剥がれる)
    assert edge.split(",,")[-1].split("}")[-1] == text.split(",,")[-1].split("}")[-1]
    assert edge.split(",")[1:3] == text.split(",")[1:3]


def test_a_preset_without_a_second_border_stays_one_layer():
    plain = next(s for s in telop_styles.TELOP_STYLES if not s.has_glow and not s.ghosts)
    value = next(v for v, s in telop_styles.STYLE_VALUES.items() if s is plain)
    lines, stats = vo._build_subtitle_dialogues(
        SEGS, 10.0, 1080, 1920, _telop_cfg(video_overlay_subtitle_style=value), 1.0, 0.5)

    assert stats["placed"] == 1 and len(lines) == 1
    assert telop_styles.EDGE_STYLE_NAME not in lines[0]


def test_ghost_layers_sit_below_the_text_and_keep_their_direction():
    """ずらして敷く層(ベタ影・色ずれ)。ずれは負にもなるので、px換算で下限clampを
    通してはならない — 通すと片側のghostだけ本体へ吸い付いて色ずれが片側だけになる。"""
    two_way = next(s for s in telop_styles.TELOP_STYLES
                   if len(s.ghosts) >= 2 and any(g.dx_ratio < 0 for g in s.ghosts))
    fs = 60
    layers = telop_styles.cue_layers(two_way, 500, 300, fs)

    ghosts = [tag for layer, _n, tag in layers if layer == telop_styles.GHOST_LAYER]
    assert len(ghosts) == len(two_way.ghosts)
    assert telop_styles.GHOST_LAYER < telop_styles.TEXT_LAYER
    xs = [int(tag.split("\\pos(")[1].split(",")[0]) for tag in ghosts]
    assert min(xs) < 500 < max(xs)        # 左右へ振れていること
    # 本体は動かさない
    body = [tag for layer, _n, tag in layers if layer == telop_styles.TEXT_LAYER][0]
    assert "\\pos(500,300)" in body


def test_the_layering_is_decided_in_one_place_for_both_renderers():
    """焼き込みと見本が各々で層を組み立てると、見本と成果物で重なりが変わる。どちらも
    cue_layers を回していること(層の数・順序・Style名が一致)。"""
    from tictok.record import telop_preview

    for value, style in telop_styles.STYLE_VALUES.items():
        expected = [(layer, name) for layer, name, _t in
                    telop_styles.cue_layers(style, 1, 2, 40, animate=False)]
        lines, _ = vo._build_subtitle_dialogues(
            SEGS, 10.0, 1080, 1920,
            _telop_cfg(video_overlay_subtitle_style=value,
                       video_overlay_subtitle_animation=0), 1.0, 0.5)
        burned = [(int(x.split(" ")[1].split(",")[0]), x.split(",")[3]) for x in lines]
        preview = telop_preview._ass_text(style, animate=True)
        sampled = [(int(x.split(" ")[1].split(",")[0]), x.split(",")[3])
                   for x in preview.splitlines() if x.startswith("Dialogue:")]

        assert burned == expected, style.key
        assert sampled == expected, style.key
        # 使うStyle行が全て定義されていること(名前を間違えるとlibassは既定styleで描く)
        defined = {line.split(",")[0].removeprefix("Style: ")
                   for line in telop_styles.style_lines(style, 40)}
        assert {name for _l, name in expected} <= defined, style.key


def test_turning_the_animation_off_keeps_the_look_but_drops_the_motion():
    animated = next(s for s in telop_styles.TELOP_STYLES if s.animated)
    value = next(v for v, s in telop_styles.STYLE_VALUES.items() if s is animated)
    on, _ = vo._build_subtitle_dialogues(
        SEGS, 10.0, 1080, 1920, _telop_cfg(video_overlay_subtitle_style=value), 1.0, 0.5)
    off, stats = vo._build_subtitle_dialogues(
        SEGS, 10.0, 1080, 1920,
        _telop_cfg(video_overlay_subtitle_style=value, video_overlay_subtitle_animation=0),
        1.0, 0.5)

    assert any("\\fad(" in line or "\\t(" in line for line in on)
    assert not any("\\fad(" in line or "\\t(" in line for line in off)
    assert stats["animated"] is False
    # 書体と色はStyle行が持つので、動きを止めても見た目は変わらない
    assert len(on) == len(off)


def test_the_wrap_width_follows_the_telop_font_not_the_comment_font():
    """折り返しはテロップの書体で測ったem advanceで計算する。commentの書体の値で折り返すと
    presetを変えた瞬間に折り返し位置が実物とずれる。"""
    long_text = [{"start": 0.0, "end": 2.0, "text": "あ" * 60}]
    cfg = _telop_cfg()
    narrow, _ = vo._build_subtitle_dialogues(long_text, 10.0, 1080, 1920, cfg, 0.6, 0.4)
    wide, _ = vo._build_subtitle_dialogues(long_text, 10.0, 1080, 1920, cfg, 1.2, 0.8)

    assert narrow[-1].count("\\N") < wide[-1].count("\\N")


def test_letter_spacing_is_charged_to_the_wrap_width():
    """字間はglyphの送りに上乗せされるので、折り返しの計算にも同じだけ足す。足さないと
    字間のあるpresetだけ画面幅からはみ出す。"""
    spaced = max(telop_styles.TELOP_STYLES, key=lambda s: s.spacing_ratio)
    value = next(v for v, s in telop_styles.STYLE_VALUES.items() if s is spaced)
    long_text = [{"start": 0.0, "end": 2.0, "text": "あ" * 200}]

    def first_line(style_value):
        lines, _ = vo._build_subtitle_dialogues(
            long_text, 10.0, 1080, 1920,
            _telop_cfg(video_overlay_subtitle_style=style_value,
                       video_overlay_subtitle_max_lines=6), 1.0, 0.5)
        return lines[-1].split("}")[-1].split("\\N")[0]

    assert spaced.spacing_ratio > 0
    assert len(first_line(value)) < len(first_line(1))


def test_the_max_line_setting_bounds_the_lines_and_is_reported():
    long_text = [{"start": 0.0, "end": 2.0, "text": "あ" * 200}]
    lines, stats = vo._build_subtitle_dialogues(
        long_text, 10.0, 1080, 1920,
        _telop_cfg(video_overlay_subtitle_max_lines=2), 1.0, 0.5)

    assert lines[-1].count("\\N") == 1          # 2行 = 区切り1つ
    assert stats["truncated"] == 1 and stats["max_lines"] == 2


def test_the_style_lines_carry_the_presets_colours_and_scale_with_the_font():
    """縁・影・字間はfont sizeとの比で持つ。絶対pxで持つと解像度で見た目が変わる。"""
    style = telop_styles.STYLE_VALUES[1]
    small = telop_styles.style_lines(style, 20)[-1].split(",")
    large = telop_styles.style_lines(style, 40)[-1].split(",")

    assert small[1] == style.font_family and small[2] == "20"
    assert small[3] == telop_styles.ass_colour(style.fill)
    assert small[5] == telop_styles.ass_colour(style.edge)
    assert int(large[16]) == 2 * int(small[16])   # Outline
    # 太さは最低1pxを割らない(0にすると縁が消えて映像に埋もれる)
    assert int(telop_styles.style_lines(style, 4)[-1].split(",")[16]) >= 1


def test_the_style_and_the_motion_are_part_of_the_cache_signature():
    """presetを変えたのに前の書体のままcache hit、を防ぐ。"""
    for key in ("video_overlay_subtitle_style", "video_overlay_subtitle_animation",
                "video_overlay_subtitle_max_lines"):
        assert key in vo.OVERLAY_KEYS


def test_a_band_preset_draws_a_box_instead_of_a_border():
    """帯presetはBorderStyle 3(不透明box)で、縁と同じfieldが帯の色と余白の意味になる。
    下層は作らない — 帯の上に帯を重ねても濃くなるだけで縁は生えない。"""
    band = next((s for s in telop_styles.TELOP_STYLES if s.box), None)
    assert band is not None
    lines = telop_styles.style_lines(band, 40)

    assert len(lines) == 1 and band.has_glow is False
    fields = lines[0].split(",")
    assert fields[15] == "3"                                    # BorderStyle
    assert fields[5] == telop_styles.ass_colour(band.edge, band.edge_alpha)   # 帯の色
    assert band.edge_alpha > 0                                  # 透けない帯は映像を殺す


def test_a_stretched_preset_pops_back_to_its_own_shape_not_to_100_percent():
    """popの到達先はpresetの縦横比。100%へ戻すと、縦長のpresetがpopの最後で
    普通の字形へ化ける。"""
    tall = next(s for s in telop_styles.TELOP_STYLES
                if (s.scale_x, s.scale_y) != (100, 100) and s.pop_percent != 100)
    tags = telop_styles.dialogue_tags(tall, 100, 200, 40)

    assert f"\\fscx{tall.scale_x}\\fscy{tall.scale_y})" in tags
    assert f"\\fscx{round(tall.scale_x * tall.pop_percent / 100)}" in tags
    # Style側の基準も同じ縦横比であること(片方だけだと出だしと定常で形が変わる)
    fields = telop_styles.style_lines(tall, 40)[-1].split(",")
    assert (fields[11], fields[12]) == (str(tall.scale_x), str(tall.scale_y))


def test_tilt_and_shear_reach_the_ass_output():
    tilted = next(s for s in telop_styles.TELOP_STYLES if s.angle)
    sheared = next(s for s in telop_styles.TELOP_STYLES if s.shear_x)

    # 回転はStyleのAngle欄、shearは行ごとの\fax(Styleに欄が無い)
    assert telop_styles.style_lines(tilted, 40)[-1].split(",")[14] == f"{tilted.angle:g}"
    assert f"\\fax{sheared.shear_x:g}" in telop_styles.dialogue_tags(sheared, 1, 2, 40)


def test_every_preset_keeps_its_fill_visible_against_its_own_border():
    """縁は字画を内側から食う。極太体・細線体で同じ比を使うと塗りが消えるので、
    内側の縁は控えめに保ち、太さは外側(glow)で稼ぐ。"""
    for style in telop_styles.TELOP_STYLES:
        if style.box:
            continue
        assert style.edge_ratio <= 0.18, style.key
        if style.edge_ratio > 0.12:
            # 太い内側の縁を持つpresetは、外側でさらに太らせない
            assert style.glow_ratio <= 0.30, style.key


def test_a_windows_drive_path_survives_the_filter_graph_parser():
    """``fontsdir`` のescapeは実測でbackslash 2つ。1つだとgraph側で剥がされたあと
    option parserが素の ``:`` を見て落ちる(No option name near ...)。"""
    arg = vo.fontsdir_arg(vo.Path(r"C:\dir\fonts"))

    assert arg == "C\\\\:/dir/fonts"
    assert "\\" not in arg.replace("\\\\:", "")   # path区切りにbackslashを残さない


def test_each_telop_font_gets_its_own_directory():
    """libassはfontsdirの全fileを読む。1部屋にまとめると、その回に使わない書体まで
    毎processで読み込まれる(通常presetのfontだけで17MB)。"""
    from tictok.record import fonts

    dirs = {name: fonts.telop_font_dir(name) for name in fonts.TELOP_FONT_MANIFEST}

    assert len(set(dirs.values())) == len(dirs)
    for name, path in dirs.items():
        assert path.name == vo.Path(name).stem
        assert path.parent.name == "telop"


# ===== テロップの見本画像 =====


def test_the_preview_is_built_from_the_same_style_definition_as_the_output():
    """見本をCSSやSVGで似せて描くと、本番と別実装になって黙ってずれる。見本のASSは
    本番と同じStyle行・同じtag生成を通っていること。"""
    from tictok.record import telop_preview

    style = telop_styles.STYLE_VALUES[1]
    text = telop_preview._ass_text(style, animate=True)

    for line in telop_styles.style_lines(style, telop_preview.FONT_SIZE):
        assert line in text
    assert telop_preview.SAMPLE_TEXT in text
    # 静止画なのでfadeの途中を焼かない(薄く写ると別の色のpresetに見える)
    assert "\\fad(" not in text


def test_a_preview_of_a_two_layer_preset_carries_both_layers():
    from tictok.record import telop_preview

    glow = next(s for s in telop_styles.TELOP_STYLES if s.has_glow and not s.ghosts)
    plain = next(s for s in telop_styles.TELOP_STYLES if not s.has_glow and not s.ghosts)

    assert telop_preview._ass_text(glow, True).count("Dialogue:") == 2
    assert telop_preview._ass_text(plain, True).count("Dialogue:") == 1


def test_every_preset_sample_is_drawn_on_the_same_background():
    """見本の背景が preset ごとに違うと、比べているのが書体なのか背景なのか分からない。

    ``gradients`` filterは既定で乱数(seed=-1)かつ時間で回る(speed=0.01)ので、色と両端の
    座標を明示しても描くたびに別の背景になる(実測: 同一commandの3回が全て別hash)。
    seedの固定とspeed=0がその2つを止めている。"""
    from tictok.record import telop_preview

    assert telop_preview.BG_SEED >= 0
    assert telop_preview.BG_SPEED == 0
    # 背景は全presetで同じ引数から作る(presetごとに色や向きを変えない)
    assert telop_preview.BG_DARK != telop_preview.BG_LIGHT


def test_the_preview_filename_changes_when_the_preset_changes(monkeypatch, tmp_path):
    """署名をfile名へ畳んでおかないと、presetの定義を直したのに古い見本が出続ける。"""
    from dataclasses import replace
    from tictok.record import telop_preview

    monkeypatch.setattr(telop_preview, "preview_dir", lambda: tmp_path)
    style = telop_styles.STYLE_VALUES[1]
    recoloured = replace(style, fill="#123456")

    before = telop_preview.preview_path(style, True)
    after = telop_preview.preview_path(recoloured, True)

    assert before != after
    assert before.name.startswith(f"{style.key}-") and before.suffix == ".png"


def test_a_new_preview_removes_the_previous_one_for_that_preset(monkeypatch, tmp_path):
    """署名つきの名前は定義を触るたびに増える。古い方を残すとpoolが際限なく太る。"""
    from tictok.record import telop_preview

    monkeypatch.setattr(telop_preview, "preview_dir", lambda: tmp_path)
    style = telop_styles.STYLE_VALUES[1]
    stale = tmp_path / f"{style.key}-deadbeef0000.png"
    other = tmp_path / "other-deadbeef0000.png"
    for p in (stale, other):
        p.write_bytes(b"x")
    keep = telop_preview.preview_path(style, True)
    keep.write_bytes(b"y")

    telop_preview._prune_stale(style, keep)

    assert keep.is_file() and other.is_file()      # 別presetの見本は残す
    assert not stale.exists()


def test_burnable_transcript_refuses_a_transcript_from_a_different_timeline():
    """版が同じでも、作られたときの入力が別物なら時刻はずれる。版だけを見ていた頃は
    実尺+191秒の転写が素通りし、ズレた字幕が恒久的に焼き付いていた。"""
    from tictok.record import transcription

    on = {"video_overlay_subtitles": 1}
    stale = {"timemap_version": transcription.TIMEMAP_VERSION, "duration": 5265.93,
             "segments": [{"start": 0.0, "end": 1.0, "text": "hi"}]}
    with pytest.raises(vo.TranscriptNotBurnableError, match="時間軸が違います"):
        vo._require_burnable_transcript(on, stale, 5074.8)
    # 同じ素材から作られた転写は通る。実尺が測れないときも通す(ズレの証拠が無い)。
    fresh = dict(stale, duration=5074.78)
    vo._require_burnable_transcript(on, fresh, 5074.8)
    vo._require_burnable_transcript(on, stale, None)


# ===== 音声を落としたら失敗させる =====


async def test_missing_audio_in_the_output_fails_instead_of_shipping_silence(
        tmp_path, monkeypatch):
    """``-map <n>:a?`` の ``?`` は取り出し先を間違えても黙って空振りする。無音の成果物は
    userが再生して初めて気付く劣化なので、成果物を消して失敗させる。"""
    src = tmp_path / "src.mp4"
    src.write_bytes(b"x")
    out = tmp_path / "clip.mp4"
    out.write_bytes(b"x")
    source = hls_source.Source(src, (), False, 0.0)
    answers = {src: True, out: False}

    async def fake_probe(path, input_args=()):
        return answers[vo.Path(path)]

    monkeypatch.setattr(vo, "_probe_has_audio", fake_probe)
    with pytest.raises(RuntimeError, match="音声"):
        await vo._require_audio_kept(source, out, stem="s")
    assert not out.exists()

    # 出力にも音声が在れば通す。probe不能(None)は真偽を捏造せず、落としもしない。
    out.write_bytes(b"x")
    answers[out] = True
    await vo._require_audio_kept(source, out, stem="s")
    answers[src] = None
    await vo._require_audio_kept(source, out, stem="s")
    assert out.is_file()


# ===== 範囲焼き込みの本体 =====


def _clip_settings():
    settings = _window_plan_settings()
    settings["video_output_normalize_audio"] = 0
    return settings


def _patch_clip_render(monkeypatch, calls, fail=False):
    """_render_window_clip を捕まえる(実際のencode引数は上のargv testが見ている)。"""
    async def fake_render(src, plan, out, meta_path, signature, on_progress, **kw):
        calls.append({"out": out, "meta": meta_path, "signature": signature,
                      "source": plan["source"], "window": plan["window"], **kw})
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\x00" * 8)
        if fail:
            raise RuntimeError("render failed")
        publish = kw.get("publish_as")
        if publish is not None:
            out.replace(publish)
            out = publish
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(signature, encoding="utf-8")

    monkeypatch.setattr(vo, "_render_window_clip", fake_render)
    return calls


async def _run_clip(monkeypatch, mp4, out, window=(120.0, 180.0)):
    _patch_plan_internals(monkeypatch)
    source = hls_source.Source(mp4, (), False, 0.0)
    return await vo._render_clip_overlay(mp4, source, 1000.0, 1600.0, [],
                                        _clip_settings(), out, window, None, None, None)


async def test_clip_render_publishes_through_a_tmp_file(make_recording, tmp_path,
                                                        monkeypatch):
    """出力pathへ直接書くと、中断が「完成品の顔をした断片mp4」を残す。tmpへ書いてrename
    する(upscaleと同じ流儀)。中間物は録画のsidecarへ、成果物だけがclips dirへ。"""
    _stem, mp4 = make_recording()
    out = tmp_path / "clips" / "clip-a.mp4"
    calls = _patch_clip_render(monkeypatch, [])
    result = await _run_clip(monkeypatch, mp4, out)
    assert result["path"] == out and result["cached"] is False
    assert out.is_file()
    assert calls[0]["out"] == tmp_path / "clips" / "clip-a.tmp.mp4"
    assert calls[0]["publish_as"] == out
    assert calls[0]["with_audio"] is True and calls[0]["zero_base"] is True
    assert calls[0]["artifact_dir"] == vo.sidecar_dir(mp4)
    assert calls[0]["meta"].parent == vo.sidecar_dir(mp4)
    assert list((tmp_path / "clips").iterdir()) == [out]


async def test_clip_render_leaves_no_fragment_when_it_fails(make_recording, tmp_path,
                                                            monkeypatch):
    _stem, mp4 = make_recording()
    out = tmp_path / "clips" / "clip-a.mp4"
    _patch_clip_render(monkeypatch, [], fail=True)
    with pytest.raises(RuntimeError):
        await _run_clip(monkeypatch, mp4, out)
    assert not out.exists()
    assert not (tmp_path / "clips" / "clip-a.tmp.mp4").exists()


async def test_clip_cache_is_scoped_to_the_window_and_the_output(make_recording,
                                                                tmp_path, monkeypatch):
    """窓が違えば中身が違うので、cacheを共有してはならない。同じ窓の再要求だけがencodeを
    飛ばす。本出力のsignature空間とも交差しない。"""
    _stem, mp4 = make_recording()
    out = tmp_path / "clips" / "clip-a.mp4"
    calls = _patch_clip_render(monkeypatch, [])
    first = await _run_clip(monkeypatch, mp4, out)
    again = await _run_clip(monkeypatch, mp4, out)
    assert again["cached"] is True and len(calls) == 1
    assert again["path"] == first["path"]

    other = await _run_clip(monkeypatch, mp4, out, window=(200.0, 260.0))
    assert other["cached"] is False and len(calls) == 2
    assert calls[0]["signature"] != calls[1]["signature"]
    cfg = vo.overlay_settings(_clip_settings())
    main = vo._signature(mp4, cfg, vo.timing_path(mp4), variant="a",
                         events_sig=vo._events_fingerprint([]), subtitles_sig="")
    assert calls[0]["signature"] != main


async def test_clip_render_refuses_when_nothing_would_be_drawn(make_recording,
                                                              tmp_path):
    """描く層が1つも無い設定でこの経路を通す意味は無い(素の切り出しは呼び出し側の仕事で、
    ここが素通しへ倒れてはならない)。"""
    _stem, mp4 = make_recording()
    settings = dict.fromkeys(vo.OVERLAY_KEYS, 0)
    with pytest.raises(vo.NothingToDrawError):
        await vo.render_clip_overlay(str(mp4), 1000.0, 1600.0, [], settings,
                                     str(tmp_path / "c.mp4"), 10.0, 20.0)


async def test_render_clip_overlay_reads_the_segments_like_the_whole_burn_in(
        tmp_root, tmp_path, monkeypatch):
    """公開経路。入力はmp4が在っても原本の .ts(prefer_hls) — 本出力と同じ素材でなければ
    時刻軸(mp4のmux inflation補正の有無)が食い違い、同じ設定でも別の位置にcommentが出る。"""
    from tests.test_hls_source import build_recording

    mp4, _session = build_recording(tmp_root)
    _patch_plan_internals(monkeypatch)
    calls = _patch_clip_render(monkeypatch, [])
    out = tmp_path / "clips" / "clip-p.mp4"
    result = await vo.render_clip_overlay(str(mp4), 1000.0, 1600.0, [], _clip_settings(),
                                          str(out), 120.0, 180.0)
    assert result["path"] == out and out.is_file()
    assert result["window"] == (120.0, 180.0)
    assert calls[0]["source"].is_hls is True
    assert calls[0]["window"] == (120.0, 180.0)


async def test_render_clip_overlay_rejects_an_impossible_window_before_encoding(
        tmp_root, tmp_path, monkeypatch):
    """窓の検証は公開経路まで通っていること(GPU slotとencodeへ入る前に落ちる)。"""
    from tests.test_hls_source import build_recording

    mp4, _session = build_recording(tmp_root)
    _patch_plan_internals(monkeypatch)
    calls = _patch_clip_render(monkeypatch, [])
    with pytest.raises(ValueError):
        await vo.render_clip_overlay(str(mp4), 1000.0, 1600.0, [], _clip_settings(),
                                     str(tmp_path / "clips" / "c.mp4"), 180.0, 120.0)
    assert calls == []


# ===== 成果物の尾切れ判定 =====
# rc=0のまま片側trackだけが3〜4割で終わる出力が実測で3件出ている(video 4859s/audio
# 12252s、逆向きのvideo 14381s/audio 4315s)。container尺は長い側を名乗るため、
# format=duration を見る既存のcheckでは素通りする。ここはtrack単位で測る最後の関門。


def fake_spans(monkeypatch, video, audio):
    async def spans(_path):
        out = {}
        if video is not None:
            out["video"] = {"seconds": video, "frames": int(video * 25), "fps": 25.0,
                            "codec": "av1"}
        if audio is not None:
            out["audio"] = {"seconds": audio, "frames": None, "fps": None, "codec": "aac"}
        return out

    monkeypatch.setattr(vo, "_probe_stream_spans", spans)


async def test_output_spans_pass_when_tracks_agree(tmp_path, monkeypatch):
    """正常な回のv/a差は実測0.3秒未満。ここで落ちては関門にならない。"""
    fake_spans(monkeypatch, 12252.30, 12252.24)
    assert await vo._verify_output_spans(tmp_path / "a.mp4", expect_seconds=12252.302,
                                         strict=True, ctx={}) is True


async def test_output_spans_reject_a_truncated_video_track(tmp_path, monkeypatch):
    """00391の形。映像が4859sで終わり音声だけ全尺 — container尺は12252sを名乗る。"""
    fake_spans(monkeypatch, 4859.40, 12252.30)
    with pytest.raises(RuntimeError, match="途中で終わっています"):
        await vo._verify_output_spans(tmp_path / "a.mp4", expect_seconds=12252.302,
                                      strict=True, ctx={})


async def test_output_spans_reject_a_truncated_audio_track(tmp_path, monkeypatch):
    """00392の形。切れる側は回ごとに入れ替わるので、片側だけを見る判定では捕まらない。"""
    fake_spans(monkeypatch, 14381.48, 4315.30)
    with pytest.raises(RuntimeError, match="途中で終わっています"):
        await vo._verify_output_spans(tmp_path / "a.mp4", expect_seconds=14381.443,
                                      strict=True, ctx={})


async def test_output_spans_catch_a_mismatch_without_an_expected_length(tmp_path,
                                                                       monkeypatch):
    """期待尺が渡らない経路でも、両trackの不揃いだけで尾切れは判る。"""
    fake_spans(monkeypatch, 4859.40, 12252.30)
    with pytest.raises(RuntimeError):
        await vo._verify_output_spans(tmp_path / "a.mp4", expect_seconds=None,
                                      strict=True, ctx={})


async def test_output_spans_do_not_fail_a_windowed_render(tmp_path, monkeypatch):
    """窓の終端は素材末尾で正当に切られ、-ssの着地もv/aで非対称。窓経路は記録だけに留める
    (同じ基準で落とすと、本物の尾切れが誤検知に埋もれる)。"""
    fake_spans(monkeypatch, 40.0, 60.0)
    assert await vo._verify_output_spans(tmp_path / "a.mp4", expect_seconds=60.0,
                                         strict=False, ctx={}) is False


async def test_output_spans_tolerate_a_video_only_output(tmp_path, monkeypatch):
    """プレビューは -an で音声を持たない。音声が無いことを不足と読んではならない。"""
    fake_spans(monkeypatch, 60.0, None)
    assert await vo._verify_output_spans(tmp_path / "a.mp4", expect_seconds=60.0,
                                         strict=True, ctx={}) is True


async def test_run_ffmpeg_discards_a_truncated_output_and_keeps_the_evidence(
        tmp_path, monkeypatch):
    """全尺の焼き込みでffmpegがrc=0を返しても、trackが足りなければ成果物を名乗らせない。
    原因はwarning段のstderrにしか出ないので、logとfilter graphは残す。"""
    fake_ffmpeg(monkeypatch, [])
    fake_spans(monkeypatch, 4859.40, 12252.30)
    out = tmp_path / "x.overlay.mp4"
    with pytest.raises(RuntimeError, match="途中で終わっています"):
        await vo._run_ffmpeg(tmp_path / "src.m3u8", [], 64, "x.ass", out, tmp_path, 21,
                             codec="h264", expect_seconds=12252.302)
    assert not out.exists()
    assert (tmp_path / "x.overlay.ffmpeg.log").is_file()
    assert (tmp_path / "x.overlay.filter.txt").is_file()


async def test_run_ffmpeg_cleans_up_after_a_sound_output(tmp_path, monkeypatch):
    """合格した回は今までどおり掃除する(成功logを無条件に残すと録画ごとに溜まる)。"""
    fake_ffmpeg(monkeypatch, [])
    fake_spans(monkeypatch, 12252.30, 12252.24)
    out = tmp_path / "x.overlay.mp4"
    await vo._run_ffmpeg(tmp_path / "src.m3u8", [], 64, "x.ass", out, tmp_path, 21,
                         codec="h264", expect_seconds=12252.302)
    assert out.is_file()
    assert not (tmp_path / "x.overlay.ffmpeg.log").exists()
    assert not (tmp_path / "x.overlay.filter.txt").exists()
