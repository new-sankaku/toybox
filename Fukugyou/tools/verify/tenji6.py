import sys,pymupdf,re,datetime,collections
d=pymupdf.open((sys.argv[1] if len(sys.argv)>1 else 'tenji2026.pdf'))
full="".join(p.get_text()+"\n" for p in d)
pat=re.compile(r'(\d{1,2})月(\d{1,2})日\s*[-‐−–—]\s*(\d{1,2})月(\d{1,2})日')
H={(1,1),(1,12),(2,11),(2,23),(3,20),(4,29),(5,3),(5,4),(5,5),(5,6),(7,20),(8,11),(9,21),(9,22),(9,23),(10,12),(11,3),(11,23)}
wk_all=0; wk_holiday=0; tot=0
for m in pat.finditer(full):
    m1,d1,m2,d2=map(int,m.groups())
    a=datetime.date(2026,m1,d1); b=datetime.date(2026,m2,d2)
    if b<a: continue
    days=[a+datetime.timedelta(days=k) for k in range((b-a).days+1)]
    tot+=1
    if all(x.weekday()<5 for x in days):
        wk_all+=1
        if any((x.month,x.day) in H for x in days): wk_holiday+=1
print("total",tot,"weekday-only",wk_all,"of which include a 2026 national holiday",wk_holiday)
print("=> 平日のみかつ祝日を含まない(真に有給が要る)", wk_all-wk_holiday, f"{(wk_all-wk_holiday)/tot*100:.1f}%")
