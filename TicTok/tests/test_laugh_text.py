"""commentの笑い判定。

判定の既定値は実DB(84 session / comment 76,368件)で測って決めたもので、testはその測定で
確認した具体例をそのまま固定する。特に「単発wの誤検出が0件だった」は既定をONにする根拠
なので、誤爆しない実例を並べて守る。
"""

import pytest

from tictok.core import laugh_text


@pytest.fixture
def compiled():
    return laugh_text.compile_patterns()


# ===== 連続w: 前後のlookaroundが効いていること =====

@pytest.mark.parametrize("text", [
    "w", "面白いw", "www", "WWW", "ｗｗｗ", "そうなんだwww", "W",
])
def test_w_run_hits(compiled, text):
    assert laugh_text.classify(text, compiled) == "w_run"


@pytest.mark.parametrize("text", [
    # 実dataの目視確認で「誤爆していないこと」を確かめた語。既定を単発ONにする根拠。
    "new", "wow", "Wow!", "welcome", "windows", "follow", "low", "know",
    "How are you", "swim", "WWE", "showw", "w/ friends", "w/",
])
def test_w_run_does_not_hit_english_words(compiled, text):
    assert laugh_text.classify(text, compiled) != "w_run"


def test_min_w_run_can_require_two(compiled):
    strict = laugh_text.compile_patterns(min_w_run=2)
    assert laugh_text.classify("面白いw", strict) is None
    assert laugh_text.classify("面白いww", strict) == "w_run"


# ===== 草: 複合語を除くこと =====

@pytest.mark.parametrize("text", ["草", "大草原", "草生える"])
def test_kusa_hits(compiled, text):
    assert laugh_text.classify(text, compiled) == "kusa"


@pytest.mark.parametrize("text", [
    # 実dataで誤検出していた実例。
    "卵、水草に着いてたら", "午後は除草剤撒かないと", "大人の色気って仕草とかじゃない?",
    "雑草一緒に拾ってくれますか?", "やっぱ公園で草むしるか", "草刈りの時間やん",
])
def test_kusa_does_not_hit_compounds(compiled, text):
    assert laugh_text.classify(text, compiled) != "kusa"


# ===== 笑: 笑顔を除くこと =====

def test_shou_hits(compiled):
    assert laugh_text.classify("それは笑", compiled) == "shou"


def test_shou_does_not_hit_egao(compiled):
    assert laugh_text.classify("笑顔かわいい", compiled) is None


# ===== 除外した種別 =====

def test_wara_kanji_is_not_a_pattern(compiled):
    """藁は唯一のhitが「藁人形」だった(TP 0 / FP 1)ので入れない。"""
    assert "wara" not in compiled
    assert laugh_text.classify("藁人形を打ち付ける時間帯", compiled) is None


def test_thai_555_is_off_by_default(compiled):
    assert "tha" not in compiled
    assert laugh_text.classify("555", compiled) is None


def test_kawaii_is_not_laughter(compiled):
    """好意の表明であって笑いではない。gift誘発の常套句でもある。"""
    assert laugh_text.classify("かわいい", compiled) is None


# ===== 数え方 =====

def test_one_comment_counts_once_however_long_the_w_run(compiled):
    """wwwwwwwwww を10と数えない。何人が笑ったかであって何文字打たれたかではない。"""
    assert laugh_text.classify("w" * 10, compiled) == "w_run"
    assert laugh_text.classify("www 草 笑 😂", compiled) is not None


@pytest.mark.parametrize("text, kind", [
    ("😂", "emoji"), ("🤣", "emoji"), ("ワロタ", "warota"),
    ("ㅋㅋㅋ", "kr"), ("lol", "en"), ("LMAO", "en"), ("hahaha", "en"),
])
def test_other_kinds(compiled, text, kind):
    assert laugh_text.classify(text, compiled) == kind


def test_empty_and_none_are_not_laughter(compiled):
    assert laugh_text.classify(None, compiled) is None
    assert laugh_text.classify("   ", compiled) is None


# ===== gift案内templateの除外 =====

def test_template_bodies_catch_repeated_long_bodies():
    body = "【初見様へ】爆笑ギフリア🤣 魚(🪙1)、野球ボール(🪙1)、ソフトクリーム(🪙1)"
    bodies = laugh_text.template_bodies([body, body, body, "草", "www"])
    assert body in bodies


def test_template_bodies_keep_short_repeats():
    """短い本文は繰り返されて当然。長さの条件が無いと本物の笑いを捨てる。"""
    bodies = laugh_text.template_bodies(["草"] * 50 + ["www"] * 50)
    assert bodies == set()


def test_template_bodies_keep_a_long_body_said_once():
    body = "今日は来てくれてありがとうございました、また明日も配信します🤣"
    assert laugh_text.template_bodies([body]) == set()
