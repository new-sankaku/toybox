from hayakuchi.mora import mora_text,normalize_kana,to_mora


def test_hiragana_is_normalized_to_katakana():
 assert normalize_kana("なまむぎ")=="ナマムギ"


def test_non_kana_is_removed():
 assert normalize_kana("生麦 なまごめ、")=="ナマゴメ"


def test_palatalized_kana_forms_single_mora():
 assert to_mora("きゃく")==["キャ","ク"]


def test_geminate_and_moraic_n_are_independent():
 assert to_mora("とっきょ")==["ト","ッ","キョ"]
 assert to_mora("しんしゅん")==["シ","ン","シュ","ン"]


def test_prolonged_mark_is_independent_mora():
 assert to_mora("しょー")==["ショ","ー"]


def test_small_kana_does_not_attach_to_geminate():
 assert to_mora("っゃ")==["ッ","ャ"]


def test_mora_count_of_reference_phrase():
 assert len(to_mora("なまむぎなまごめなまたまご"))==13


def test_mora_text_roundtrip():
 assert mora_text(to_mora("とうきょうとっきょきょかきょく"))=="トウキョウトッキョキョカキョク"
