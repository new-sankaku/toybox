import sys,pymupdf, re
d=pymupdf.open((sys.argv[1] if len(sys.argv)>1 else 'tenji2026.pdf'))
pat = re.compile(r'(\d{1,2})月(\d{1,2})日\s*[-‐−–—]\s*(\d{1,2})月(\d{1,2})日')
tot=0
for i,p in enumerate(d):
    t=p.get_text()
    n=len(pat.findall(t)); u=len(re.findall(r'https?://',t))
    tot+=n
    print(f"p{i+1}: ranges={n} urls={u} chars={len(t)}")
print("total",tot)
