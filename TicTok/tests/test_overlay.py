import pytest

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


def test_signature_invalidates_when_the_source_mp4_changes(make_recording):
    _stem, mp4 = make_recording()
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
