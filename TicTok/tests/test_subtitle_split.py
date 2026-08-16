"""テロップを「出せる長さ」へ割る段。

この機能の事故は、成果物を再生するまで誰にも見えない形で出る。whisperのsegmentは1件が
数十秒になり(実測: 全297文字起こし・459,738件のうち5秒超16.5%・20秒超1.0%・最大5,354秒)、
それを1枚のテロップとして焼くと画面には数十秒ぶんの文が居座り、その間ずっと別の言葉が
喋られる。**時刻軸をどう直しても解けない** — 割る位置がdataに無いからである。
"""

from tictok.record import subtitles


def _words(pairs):
    return [{"start": s, "end": e, "text": t} for s, e, t in pairs]


def test_a_long_segment_is_split_at_word_times():
    """実素材で13.18秒の1枚が出ていた。割った後の最大は3.60秒だった。"""
    seg = {"start": 0.0, "end": 12.0, "text": "あいうえおかきくけこさしすせそ",
           "words": _words([(0.0, 1.0, "あいう"), (1.0, 2.0, "えお"),
                            (8.0, 9.0, "かきく"), (9.0, 10.0, "けこ"),
                            (10.0, 12.0, "さしすせそ")])}
    out = subtitles.split_for_display([seg])
    assert len(out) > 1
    assert max(s["end"] - s["start"] for s in out) <= subtitles.DISPLAY_MAX_SECONDS
    # 語を落とさない。割るのは表示単位であって、内容を捨てる操作ではない。
    assert "".join(s["text"] for s in out) == "あいうえおかきくけこさしすせそ"


def test_a_gap_between_words_breaks_the_display_unit():
    """語と語の間は話の切れ目そのもの。尺や文字数より先に見る。

    実素材で「かわ」と3.4秒空いた「いい」が同じ枚に入り、尺の上限で機械的に割れていた。
    """
    seg = {"start": 0.0, "end": 5.0, "text": "かわいい",
           "words": _words([(0.0, 0.58, "かわ"), (3.4, 4.9, "いい")])}
    out = subtitles.split_for_display([seg])
    assert [s["text"] for s in out] == ["かわ", "いい"]
    # 表示は語が終わったところで消える(次の語まで出しっぱなしにしない)。
    assert out[0]["end"] == 0.58
    assert out[1]["start"] == 3.4


def test_a_segment_without_word_times_is_left_alone():
    """文字数で按分して割るのは時刻の捏造。割れないことは、割った振りより害が小さい。

    語の時刻を持たない文字起こし(既存の297本すべて)がここへ来る。
    """
    seg = {"start": 0.0, "end": 40.0, "text": "とても長い一文がここにある"}
    out = subtitles.split_for_display([seg])
    assert out == [{"start": 0.0, "end": 40.0, "text": "とても長い一文がここにある"}]


def test_a_short_segment_is_not_touched():
    seg = {"start": 1.0, "end": 2.5, "text": "みじかい",
           "words": _words([(1.0, 1.7, "みじ"), (1.7, 2.5, "かい")])}
    assert subtitles.split_for_display([seg]) == [
        {"start": 1.0, "end": 2.5, "text": "みじかい"}]


def test_word_times_survive_the_usable_filter():
    """``usable_segments`` が語を落とすと、その先で割れなくなる(黙って元の長さで焼ける)。"""
    seg = {"start": 0.0, "end": 9.0, "text": "ながい",
           "words": _words([(0.0, 1.0, "な"), (8.0, 9.0, "がい")])}
    rows = subtitles.usable_segments([seg])
    assert rows[0].get("words")
    assert len(subtitles.split_for_display(rows)) == 2


def test_the_transcript_can_say_whether_it_has_word_times():
    """既存の文字起こしと、語の時刻を持つ文字起こしを区別できること(再文字起こしの要否がここで決まる)。"""
    assert not subtitles.has_word_times([{"start": 0.0, "end": 1.0, "text": "x"}])
    assert subtitles.has_word_times(
        [{"start": 0.0, "end": 1.0, "text": "x", "words": _words([(0.0, 1.0, "x")])}])


def test_how_coarse_a_transcript_is_can_be_measured():
    """「この文字起こしはテロップに使えるか」を、焼く前に数字で言えるようにする。"""
    segs = [{"start": 0.0, "end": 1.0, "text": "a"},
            {"start": 2.0, "end": 42.0, "text": "b"}]
    assert subtitles.coarse_ratio(segs) == 0.5
    assert subtitles.coarse_ratio([]) == 0.0


def test_the_whole_recording_export_splits_srt_and_vtt_but_not_txt():
    """録画丸ごとの書き出しが無音までcueで覆っていた。

    whisperはsegmentの終端を次のsegmentの開始まで伸ばすので、間の無音がcueに入る。実測(版2の
    文字起こし331件)でSRTがtimelineを覆う割合は中央値97.7%——実発話は約30%(録画926でVAD実測
    91.9s/306s)で、無音の上に関係のないcueが出続けていた。txtは原稿として使う書式なので割らない。
    """
    seg = {"start": 0.0, "end": 12.0, "text": "あいうえお",
           "words": _words([(0.0, 1.0, "あい"), (11.5, 12.0, "うえお")])}
    transcript = {"segments": [seg], "text": "あいうえお"}

    srt = subtitles.render("srt", transcript)
    # 語と語の間の10.5秒はcueに入らない(1件が0-1.0秒、もう1件が11.5-12.0秒)。
    assert "00:00:00,000 --> 00:00:01,000" in srt
    assert "00:00:11,500 --> 00:00:12,000" in srt
    assert "00:00:00,000 --> 00:00:12,000" not in srt

    vtt = subtitles.render("vtt", transcript)
    assert "00:00:00.000 --> 00:00:01.000" in vtt
    assert "00:00:00.000 --> 00:00:12.000" not in vtt

    assert subtitles.render("txt", transcript) == "あいうえお\n"


def test_the_export_leaves_a_transcript_without_word_times_intact():
    """割る位置がdataに無い文字起こし(既存293件)は、割った振りをせずそのまま出す。"""
    transcript = {"segments": [{"start": 0.0, "end": 12.0, "text": "あいうえお"}]}
    assert "00:00:00,000 --> 00:00:12,000" in subtitles.render("srt", transcript)


def test_the_srt_cue_carries_its_own_line_breaks():
    """SRTはcueに複数行を書ける書式だが、**1行のまま渡すと読み手は折り返さない。**

    縦画面へ載せると横へはみ出して端が切れる。書体を持たない書式なので、幅は全角換算の
    文字数で数えるしかない。
    """
    transcript = {"segments": [{"start": 0.0, "end": 3.0,
                                "text": "最近ポミさんの声聞くと涙が出るから"}]}
    body = subtitles.render("srt", transcript)
    assert "最近ポミさんの声聞くと\n涙が出るから" in body


def test_the_cue_boundaries_are_planned_for_the_whole_segment():
    """左から順に上限まで詰めると、後ろの枚がどうなるかを見ないまま境が決まる。

    segment全体を見渡し、枚の境と行の折りを同時に決める。ここでは2枚に割る方が予算の無駄が
    少なく、境も文節境界に落ちる —— 貪欲だと同じ語列が3枚に刻まれていた。
    """
    words = _words([(0.0, 0.4, "だから"), (0.4, 0.8, "今日は"), (0.8, 1.2, "ちょっと"),
                    (1.2, 1.6, "無理"), (1.6, 2.0, "かなって"), (2.0, 2.4, "思って"),
                    (2.4, 2.8, "いる")])
    seg = {"start": 0.0, "end": 2.8,
           "text": "".join(w["text"] for w in words), "words": words}
    out = subtitles.split_for_display([seg], max_seconds=99.0, max_chars=12, per_line=12)
    assert [row["text"] for row in out] == ["だから今日はちょっと", "無理かなって思っている"]
    # 語も時刻も落ちない
    assert "".join(row["text"] for row in out) == seg["text"]
    assert out[0]["start"] == 0.0 and out[-1]["end"] == 2.8


def test_how_well_a_cue_folds_can_be_measured_before_making_it():
    """枚を割る段が折りやすさを見るための物差し。これが無いと、折れない枚を作ってから
    気付くことになる(気付く手段は成果物を再生することしかない)。"""
    from tictok.record import jp_wrap

    # 1行に収まる文は折らないので0
    short = "みじかい"
    assert jp_wrap.layout_badness(short, jp_wrap.break_costs(short), 16, 2) == 0.0

    # 読点で折れる文は良い(点数が小さい)
    good = "あのさ、マネージャーからされなくて"
    good_score = jp_wrap.layout_badness(good, jp_wrap.break_costs(good), 16, 2)
    # 許される幅の中に文節を割る位置しか無い文は悪い
    bad = "最近ポミさんの声聞くと涙が出るからもう無理かなって思っている"
    bad_score = jp_wrap.layout_badness(bad, jp_wrap.break_costs(bad), 16, 2)
    assert good_score < bad_score
    assert bad_score >= jp_wrap.COST_INSIDE_BUNSETSU


def test_the_safe_margin_shrinks_the_usable_width_everywhere():
    """上限ちょうどまで詰めた行は、読み手の書体やplayerの内側余白が少し違うだけで端が切れる。

    余白は1行の幅と1枚の予算の**両方**から引く。片方だけだと、予算いっぱいの枚が
    「余白を引いた行には収まらない」形で作られる。
    """
    box = subtitles.layout_from_settings(
        {"subtitle_chars_per_line": 20, "subtitle_wrap_lines": 2,
         "subtitle_safe_margin_percent": 10})
    assert box["per_line"] == 18.0
    assert box["max_chars"] == 36.0
    # 余白0%なら上限そのもの
    plain = subtitles.layout_from_settings(
        {"subtitle_chars_per_line": 20, "subtitle_wrap_lines": 2,
         "subtitle_safe_margin_percent": 0})
    assert plain["per_line"] == 20.0 and plain["max_chars"] == 40.0


def test_a_gap_still_wins_over_the_meaning_break():
    """間そのものが話の切れ目で、文字の並びより強い根拠である。場所を選び直さない。"""
    words = _words([(0.0, 0.4, "だから"), (0.4, 0.8, "今日は"), (3.0, 3.4, "無理")])
    seg = {"start": 0.0, "end": 3.4,
           "text": "だから今日は無理", "words": words}
    out = subtitles.split_for_display([seg], max_seconds=99.0, max_chars=99)
    assert [row["text"] for row in out] == ["だから今日は", "無理"]
