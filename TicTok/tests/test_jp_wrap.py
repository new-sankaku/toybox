"""日本語字幕の改行位置。

この機能の事故は成果物を再生するまで見えない。SRTはcueに複数行を書ける書式だが、1行のまま
渡すと読み手は折り返さず、縦画面では横へはみ出して端が切れる。折り返しても、文字数だけで
折ると実録画のcue 14,500件のうち**49.7%が語の内側**で切れていた(「〜だか|ら」)。
"""

import pytest

from tictok.record import jp_wrap


def wrapped(text, per_line=16, max_lines=2):
    return jp_wrap.wrap(text, per_line, max_lines)


def test_a_line_that_fits_is_not_folded():
    assert wrapped("みじかい文") == ["みじかい文"]


def test_every_line_stays_within_the_limit():
    lines = wrapped("最近ポミさんの声聞くと涙が出るから")
    assert len(lines) == 2
    assert all(jp_wrap.width(line) <= 16 for line in lines)


def test_no_character_is_dropped():
    """折るのは表示の都合であって、内容を捨てる操作ではない。"""
    text = "ずっと半端で終わらせたくないから辞退したいな"
    assert "".join(wrapped(text)) == text


def test_the_break_lands_on_a_meaning_boundary_not_a_character_count():
    """文字数で折ると「〜だか|ら」「取り|たいから」で切れる。実データでの主症状そのもの。"""
    assert wrapped("最近ポミさんの声聞くと涙が出るから") == ["最近ポミさんの声聞くと", "涙が出るから"]
    assert wrapped("申し訳ないから辞退しようかなって思って") == ["申し訳ないから", "辞退しようかなって思って"]
    assert wrapped("うちら2人でやってるところに突っ込んできたわけ") == [
        "うちら2人でやってる", "ところに突っ込んできたわけ"]


def test_a_bunsetsu_is_not_split_before_a_bound_word():
    """付属語と補助用言は前の語に付いて1文節を成す。「終わらせ|たくない」で折ると読めない。"""
    for line in wrapped("ずっと半端で終わらせたくないから辞退したいな"):
        assert not line.startswith("たく")
        assert not line.startswith("ない")


def test_punctuation_wins_over_a_tidy_line_length():
    """句読点は文が終わっている証拠。多少行が不揃いになってもそこで折る。"""
    assert wrapped("あのさ、マネージャーからされなくて") == ["あのさ、", "マネージャーからされなくて"]


def test_kinsoku_keeps_closing_marks_off_the_head_of_a_line():
    """行頭に句読点・閉じ括弧・促音が来ると、日本語の組版として壊れて見える。"""
    for text in ["そうだねそれでいいと思うよ、うんそうしよう",
                 "ちょっとなんかいつもより暗くない?"]:
        for line in wrapped(text)[1:]:
            assert line[0] not in jp_wrap.HEAD_FORBIDDEN


def test_a_line_never_breaks_inside_a_morpheme_even_when_nothing_fits():
    """収まらないからといって語の内側で折らない。溢れた行を返し、文字は1つも捨てない。

    文字数で折る実装がやっていたのがこれで、実データのcueの49.7%が語の内側で切れていた。
    """
    text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    lines = jp_wrap.wrap(text, 6, 2)
    assert "".join(lines) == text
    boundaries, pos = {0}, 0
    for word in jp_wrap.tagger()(text):
        pos += len(word.surface)
        boundaries.add(pos)
    cut = 0
    for line in lines[:-1]:
        cut += len(line)
        assert cut in boundaries


def test_the_fewest_lines_that_fit_are_used():
    """3行に割れるからといって割らない。行が増えるほど映像を覆う。"""
    text = "今日はいい天気ですね明日も晴れるといいなと思います"
    assert len(wrapped(text, per_line=16, max_lines=4)) == 2


def test_half_width_characters_count_as_half():
    """SRT/VTTは書体を持たない書式なので、全角/半角の別だけが幅の手がかりになる。"""
    assert jp_wrap.width("あい") == 2.0
    assert jp_wrap.width("ab") == 1.0
    # 結合文字と異体字selectorは送りを持たないので数えない
    assert jp_wrap.width("が") == 1.0


def test_the_measure_can_be_replaced_with_real_glyph_advances():
    """焼き込みは実測した送り幅で折る。文字数で折ると書体を変えた瞬間に実物とずれる。"""
    text = "今日はいい天気ですね明日も晴れるといいなと思います"
    narrow = jp_wrap.wrap(text, 16.0, 6, measure=lambda ch: 0.5)
    wide = jp_wrap.wrap(text, 16.0, 6, measure=lambda ch: 2.0)
    assert len(narrow) < len(wide)


def test_a_missing_analyzer_says_so_instead_of_falling_back(monkeypatch):
    """文字数へ静かに落ちると、元の症状(意味不明な位置で切れる)へ戻ったことが誰にも見えない。"""
    monkeypatch.setattr(jp_wrap._local, "tagger", None, raising=False)
    import builtins
    real_import = builtins.__import__

    def no_fugashi(name, *args, **kwargs):
        if name == "fugashi":
            raise ImportError("no fugashi")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_fugashi)
    with pytest.raises(RuntimeError, match="fugashi"):
        jp_wrap.tagger()
