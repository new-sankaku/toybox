import sys,pymupdf, re, datetime, collections
d=pymupdf.open((sys.argv[1] if len(sys.argv)>1 else 'tenji2026.pdf'))
full="".join(p.get_text()+"\n" for p in d)
pat = re.compile(r'(\d{1,2})月(\d{1,2})日\s*[-‐−–—]\s*(\d{1,2})月(\d{1,2})日')
WD="月火水木金土日"
cnt=collections.Counter(); wk=0; we=0; bad=0; total=0; spans=[]
for m in pat.finditer(full):
    m1,d1,m2,d2=map(int,m.groups())
    try:
        a=datetime.date(2026,m1,d1); b=datetime.date(2026,m2,d2)
    except ValueError:
        bad+=1; continue
    if b<a: b=datetime.date(2027,m2,d2)
    days=(b-a).days+1
    if days<1 or days>60: bad+=1; continue
    total+=1; spans.append(days)
    has_we=False
    for k in range(days):
        w=(a+datetime.timedelta(days=k)).weekday()
        cnt[w]+=1
        if w>=5: has_we=True
    if has_we: we+=1
    else: wk+=1
print("total events:",total,"skipped:",bad)
print("weekday-only:",wk, f"{wk/total*100:.1f}%")
print("includes sat/sun:",we, f"{we/total*100:.1f}%")
for i in range(7):
    print(WD[i], cnt[i])
print("avg span", sum(spans)/len(spans))
import collections as c
print("span dist", sorted(c.Counter(spans).items()))
