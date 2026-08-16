import re
from pypdf import PdfReader
r=PdfReader((sys.argv[1] if len(sys.argv)>1 else 'tenji2026.pdf'))
full="".join((p.extract_text() or "")+"\n" for p in r.pages)
open('tenji_pypdf.txt','w',encoding='utf-8').write(full)
pat = re.compile(r'(\d{1,2})月(\d{1,2})日\s*[-‐−–—]\s*(\d{1,2})月(\d{1,2})日')
print("pypdf ranges:",len(pat.findall(full)))
print("pypdf urls:",len(re.findall(r'https?://',full)))
print("pypdf bare 月日:",len(re.findall(r'\d{1,2}月\d{1,2}日',full)))
# lines containing both a date and a url
lines=[l for l in full.splitlines() if re.search(r'https?://',l)]
print("url lines:",len(lines))
