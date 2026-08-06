import pytest

from hayakuchi.mora import to_mora
from hayakuchi.phoneme import mora_to_phonemes,normalize_phonemes,supported_mora


def _phonemes(text:str):
 return mora_to_phonemes(to_mora(text))[0]


def test_basic_mora_expands_to_consonant_and_vowel():
 assert _phonemes("なま")==["n","a","m","a"]


def test_palatalized_mora_uses_dedicated_phoneme():
 assert _phonemes("きゃく")==["ky","a","k","u"]


def test_geminate_and_moraic_n():
 assert _phonemes("とっきょ")==["t","o","cl","ky","o"]
 assert _phonemes("しんしゅん")==["sh","i","N","sh","u","N"]


def test_prolonged_mark_repeats_preceding_vowel():
 assert _phonemes("しょー")==["sh","o","o"]


def test_prolonged_mark_after_moraic_n_repeats_n():
 assert _phonemes("んー")==["N","N"]


def test_prolonged_mark_without_preceding_vowel_raises():
 with pytest.raises(ValueError):
  mora_to_phonemes(["ー"])


def test_origin_maps_each_phoneme_to_source_mora():
 phonemes,origins=mora_to_phonemes(to_mora("とっきょ"))
 assert len(phonemes)==len(origins)
 assert origins==[0,0,1,2,2]


def test_devoiced_vowels_are_normalized():
 assert normalize_phonemes(["m","a","sh","I","t","a"])==["m","a","sh","i","t","a"]
 assert normalize_phonemes(["o","k","U"])==["o","k","u"]


def test_non_speech_tokens_are_dropped():
 assert normalize_phonemes(["pau","k","a","sil","PAD"])==["k","a"]


def test_rare_mora_from_phoneme_balanced_corpus_are_mapped():
 for text in ("ツァ","ツォ","テュ","トゥ","ヴァ","ジェ","フォ","ギェ","ピェ","イェ","デョ"):
  assert _phonemes(text)


def test_unmapped_mora_raises():
 with pytest.raises(ValueError):
  mora_to_phonemes(["漢"])


def test_supported_mora_is_not_empty():
 assert len(supported_mora())>100
