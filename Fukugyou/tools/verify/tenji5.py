import sys,pymupdf, re, datetime
d=pymupdf.open((sys.argv[1] if len(sys.argv)>1 else 'tenji2026.pdf'))
WD="月火水木金土日"
rows=[]
for pi,p in enumerate(d):
    t=p.get_text()
    lines=t.splitlines()
    # reconstruct: date pattern spans 3 lines: "M月D日","-","M月D日" then name
    i=0
    while i < len(lines)-3:
        if re.fullmatch(r'\d{1,2}月\d{1,2}日', lines[i].strip()) and lines[i+1].strip() in '-‐−–—' and re.fullmatch(r'\d{1,2}月\d{1,2}日', lines[i+2].strip()):
            name = lines[i+3].strip() if i+3<len(lines) else ''
            rows.append((pi+1, lines[i].strip(), lines[i+2].strip(), name))
            i+=3
        else:
            i+=1
print("rows parsed:", len(rows))
we=[]
for pg,a,b,name in rows:
    m1,d1=map(int,re.findall(r'\d+',a)); m2,d2=map(int,re.findall(r'\d+',b))
    A=datetime.date(2026,m1,d1); B=datetime.date(2026,m2,d2)
    if B<A: B=datetime.date(2027,m2,d2)
    wds=[(A+datetime.timedelta(days=k)).weekday() for k in range((B-A).days+1)]
    if any(w>=5 for w in wds):
        we.append((pg,a,b,''.join(WD[w] for w in wds),name))
print("weekend-including:",len(we))
for r in we: print(r)
print()
print("2026-02-25 is", WD[datetime.date(2026,2,25).weekday()], "2026-02-27 is", WD[datetime.date(2026,2,27).weekday()])
