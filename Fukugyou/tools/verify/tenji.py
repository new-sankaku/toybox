import sys,pymupdf, re, datetime, collections
d=pymupdf.open((sys.argv[1] if len(sys.argv)>1 else 'tenji2026.pdf'))
full=""
for p in d:
    full += p.get_text()+"\n"
open('tenji_raw.txt','w',encoding='utf-8').write(full)
# date range pattern: M月D日 \n - \n M月D日
pat = re.compile(r'(\d{1,2})月(\d{1,2})日\s*[-‐−–—]\s*(\d{1,2})月(\d{1,2})日')
ms = list(pat.finditer(full))
print("date-range matches:", len(ms))
# also any bare M月D日 count
print("bare 月日 count:", len(re.findall(r'\d{1,2}月\d{1,2}日', full)))
print("url count:", len(re.findall(r'https?://', full)))
