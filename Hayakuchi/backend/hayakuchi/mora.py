"""Kana正規化とMora分解

判定はMora単位で行うため、Engine出力と正解文の双方をここで同一の表現に揃える。
"""
from typing import List

_HIRAGANA_START=0x3041
_HIRAGANA_END=0x3096
_KANA_OFFSET=0x60
_KATAKANA_START=0x30A1
_KATAKANA_END=0x30FA
_PROLONGED="ー"

_COMBINING=frozenset("ャュョァィゥェォヮ")
_NON_HOST=frozenset(("ッ","ン",_PROLONGED))


def _to_katakana(text:str)->str:
 out=[]
 for ch in text:
  code=ord(ch)
  if _HIRAGANA_START<=code<=_HIRAGANA_END:
   out.append(chr(code+_KANA_OFFSET))
  else:
   out.append(ch)
 return "".join(out)


def is_kana(ch:str)->bool:
 """Mora構成に使えるKatakanaかを判定する"""
 code=ord(ch)
 return _KATAKANA_START<=code<=_KATAKANA_END or ch==_PROLONGED


def normalize_kana(text:str)->str:
 """Hiraganaを含む入力をKatakanaへ正規化し、Kana以外を除去する"""
 return "".join(ch for ch in _to_katakana(text) if is_kana(ch))


def to_mora(text:str)->List[str]:
 """KanaをMora列へ分解する

 拗音・小書きKanaは直前Kanaと結合し、促音・撥音・長音は独立Moraとして扱う。
 """
 mora:List[str]=[]
 for ch in normalize_kana(text):
  if mora and ch in _COMBINING and len(mora[-1])==1 and mora[-1] not in _NON_HOST:
   mora[-1]+=ch
  else:
   mora.append(ch)
 return mora


def mora_text(mora:List[str])->str:
 """Mora列を表示用文字列へ戻す"""
 return "".join(mora)
