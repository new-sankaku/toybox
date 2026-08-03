"""MoraとPhonemeの相互変換

Phoneme出力のCTC Modelを扱うため、正解Kanaを同じPhoneme体系へ変換する。
記号はOpenJTalk系のPhoneme集合に合わせる。
Phoneme単位で検出した誤り位置は、Overlay表示のためMora indexへ戻す必要があるため、
変換時にPhoneme→Mora の対応も同時に返す。
"""
from typing import Dict,List,Sequence,Tuple

_VOWELS=frozenset("aiueo")
_SUSTAINABLE=frozenset(("a","i","u","e","o","N"))
_PROLONGED="ー"
_GEMINATE="ッ"
_MORAIC_N="ン"
_DEVOICED={"I":"i","U":"u"}
_NON_SPEECH=frozenset(("pau","sil","PAD","UNK","SOS","EOS","<pad>","<s>","</s>","<unk>","|"))

_TABLE:Dict[str,List[str]]={
 "ア":["a"],"イ":["i"],"ウ":["u"],"エ":["e"],"オ":["o"],
 "ヰ":["i"],"ヱ":["e"],"ヲ":["o"],
 "アァ":["a","a"],"イィ":["i","i"],"ウゥ":["u","u"],"エェ":["e","e"],"オォ":["o","o"],
 "ァ":["a"],"ィ":["i"],"ゥ":["u"],"ェ":["e"],"ォ":["o"],
 "カ":["k","a"],"キ":["k","i"],"ク":["k","u"],"ケ":["k","e"],"コ":["k","o"],
 "ヵ":["k","a"],"ヶ":["k","e"],
 "キャ":["ky","a"],"キュ":["ky","u"],"キョ":["ky","o"],"キェ":["ky","e"],
 "ガ":["g","a"],"ギ":["g","i"],"グ":["g","u"],"ゲ":["g","e"],"ゴ":["g","o"],
 "ギャ":["gy","a"],"ギュ":["gy","u"],"ギョ":["gy","o"],"ギェ":["gy","e"],
 "サ":["s","a"],"シ":["sh","i"],"ス":["s","u"],"セ":["s","e"],"ソ":["s","o"],
 "シャ":["sh","a"],"シュ":["sh","u"],"ショ":["sh","o"],"シェ":["sh","e"],
 "スィ":["s","i"],
 "ザ":["z","a"],"ジ":["j","i"],"ズ":["z","u"],"ゼ":["z","e"],"ゾ":["z","o"],
 "ジャ":["j","a"],"ジュ":["j","u"],"ジョ":["j","o"],"ジェ":["j","e"],
 "ズィ":["z","i"],
 "タ":["t","a"],"チ":["ch","i"],"ツ":["ts","u"],"テ":["t","e"],"ト":["t","o"],
 "チャ":["ch","a"],"チュ":["ch","u"],"チョ":["ch","o"],"チェ":["ch","e"],
 "ティ":["t","i"],"トゥ":["t","u"],"テャ":["ty","a"],"テュ":["ty","u"],"テョ":["ty","o"],
 "ツァ":["ts","a"],"ツィ":["ts","i"],"ツェ":["ts","e"],"ツォ":["ts","o"],
 "ダ":["d","a"],"ヂ":["j","i"],"ヅ":["z","u"],"デ":["d","e"],"ド":["d","o"],
 "ヂャ":["j","a"],"ヂュ":["j","u"],"ヂョ":["j","o"],
 "ディ":["d","i"],"ドゥ":["d","u"],"デャ":["dy","a"],"デュ":["dy","u"],"デョ":["dy","o"],
 "ナ":["n","a"],"ニ":["n","i"],"ヌ":["n","u"],"ネ":["n","e"],"ノ":["n","o"],
 "ニャ":["ny","a"],"ニュ":["ny","u"],"ニョ":["ny","o"],"ニェ":["ny","e"],
 "ハ":["h","a"],"ヒ":["h","i"],"フ":["f","u"],"ヘ":["h","e"],"ホ":["h","o"],
 "ヒャ":["hy","a"],"ヒュ":["hy","u"],"ヒョ":["hy","o"],"ヒェ":["hy","e"],
 "ファ":["f","a"],"フィ":["f","i"],"フェ":["f","e"],"フォ":["f","o"],"フュ":["fy","u"],
 "バ":["b","a"],"ビ":["b","i"],"ブ":["b","u"],"ベ":["b","e"],"ボ":["b","o"],
 "ビャ":["by","a"],"ビュ":["by","u"],"ビョ":["by","o"],"ビェ":["by","e"],
 "パ":["p","a"],"ピ":["p","i"],"プ":["p","u"],"ペ":["p","e"],"ポ":["p","o"],
 "ピャ":["py","a"],"ピュ":["py","u"],"ピョ":["py","o"],"ピェ":["py","e"],
 "マ":["m","a"],"ミ":["m","i"],"ム":["m","u"],"メ":["m","e"],"モ":["m","o"],
 "ミャ":["my","a"],"ミュ":["my","u"],"ミョ":["my","o"],"ミェ":["my","e"],
 "ヤ":["y","a"],"ユ":["y","u"],"ヨ":["y","o"],"ャ":["y","a"],"ュ":["y","u"],"ョ":["y","o"],
 "イェ":["y","e"],
 "ラ":["r","a"],"リ":["r","i"],"ル":["r","u"],"レ":["r","e"],"ロ":["r","o"],
 "リャ":["ry","a"],"リュ":["ry","u"],"リョ":["ry","o"],"リェ":["ry","e"],
 "ワ":["w","a"],"ヮ":["w","a"],"ウィ":["w","i"],"ウェ":["w","e"],"ウォ":["w","o"],
 "ヴ":["v","u"],"ヴァ":["v","a"],"ヴィ":["v","i"],"ヴェ":["v","e"],"ヴォ":["v","o"],
 "クヮ":["kw","a"],"グヮ":["gw","a"],
 _GEMINATE:["cl"],
 _MORAIC_N:["N"],
}


def mora_to_phonemes(mora:Sequence[str])->Tuple[List[str],List[int]]:
 """Mora列をPhoneme列へ変換し、Phonemeごとの由来Mora indexを併せて返す"""
 phonemes:List[str]=[]
 origins:List[int]=[]
 for index,unit in enumerate(mora):
  if unit==_PROLONGED:
   previous=next((item for item in reversed(phonemes) if item in _SUSTAINABLE),None)
   if previous is None:
    raise ValueError(f"prolonged mark has no preceding vowel: {''.join(mora)}")
   converted=[previous]
  else:
   if unit not in _TABLE:
    raise ValueError(f"unmapped mora: {unit} in {''.join(mora)}")
   converted=_TABLE[unit]
  phonemes.extend(converted)
  origins.extend([index]*len(converted))
 return phonemes,origins


def normalize_phonemes(tokens:Sequence[str])->List[str]:
 """Engine出力のPhoneme列を比較可能な形へ正規化する

 無声化母音は話者と環境で揺れるため有声形へ寄せ、無音記号は除去する。
 """
 normalized=[]
 for token in tokens:
  if token in _NON_SPEECH:
   continue
  normalized.append(_DEVOICED.get(token,token))
 return normalized


def supported_mora()->List[str]:
 """変換表に登録済みのMoraを返す"""
 return sorted(_TABLE)
