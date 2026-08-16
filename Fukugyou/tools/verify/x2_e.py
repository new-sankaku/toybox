import math
G=500_000; m=0.70; c=0.05; T=18; H=7*52/12; rev=G/m
def M_of(B,c=0.05,T=18): return c*B/(1-math.exp(-c*T))
def sim(reach_fn,s,c=0.05,T=18,n=40000,k=0.0):
    dt=T/n;b=0.0
    for i in range(n):
        b+=(reach_fn(i*dt)*s + k*b - c*b)*dt
    return b

print("="*76)
print("[E] Break-even asset productivity (inverted, so no invented number decides it)")
print("="*76)
print("Question: with ALL 30.3 h/mo spent building stock assets (h_a hours each, delta=3%/mo),")
print("what reach-per-asset-per-month a0 is needed to hit B by month 18?\n")
for P,label in [(4500,"月4,500円"),(15000,"月15,000円"),(50000,"月50,000円")]:
    B=rev/P
    print(f"  {label}  B={B:.1f} contracts")
    for h_a in (5,10,40):
        x=H/h_a
        for s in (0.005,0.01,0.02):
            lo,hi=1e-6,1e7
            for _ in range(200):
                mid=(lo+hi)/2
                f=lambda t,x=x,a0=mid: (x*a0/0.03)*(1-math.exp(-0.03*t))
                if sim(f,s,n=4000)<B: lo=mid
                else: hi=mid
            print(f"    h_a={h_a:>2}h/asset ({x:5.2f} assets/mo), s={s*100:4.2f}% -> "
                  f"need a0 = {lo:8.1f} reach/month per asset")
    print()

print("="*76)
print("[F] Referral / word-of-mouth term (the doc sets k=0 silently)")
print("="*76)
print("  db/dt = R*s + k*b - c*b   =>   M = (c-k)*B/(1-e^{-(c-k)T})  for k<c")
B=rev/15000
for k in (0.0,0.005,0.01,0.02,0.03,0.04,0.05,0.06):
    ce=c-k
    if abs(ce)<1e-9: M=B/T
    elif ce>0: M=ce*B/(1-math.exp(-ce*T))
    else: M=ce*B/(1-math.exp(-ce*T))
    print(f"   k={k:5.3f}/mo  effective c-k={ce:+6.3f}  M={M:7.3f}/mo  "
          f"reach@s=0.5% = {M/0.005:8.0f}  hours={M/0.005*0.25:8.1f}"
          + ("   <-- doc" if k==0 else "")
          + ("   *** self-sustaining (k>c)" if k>c else ""))
print("  k=0.02/mo means each customer refers one new customer every 50 months.")

print("\n"+"="*76)
print("[G] Price-dependent churn, using the DOC'S OWN ChartMogul table (L534)")
print("="*76)
print("  doc cites: 月$50未満 tier GRR 23%/yr ; 月$250超 GRR 70%/yr  -- then uses c=5% for all rows")
for P,grr,lab in [(4500,0.23,"~$30 tier"),(15000,0.23,"~$100 (below $250)"),
                  (50000,0.70,">$250 tier"),(150000,0.70,">$250 tier")]:
    cc=-math.log(grr)/12
    B=rev/P; M=cc*B/(1-math.exp(-cc*T))
    Mdoc=M_of(B)
    print(f"   P={P:>7} GRR={grr:.2f} -> c={cc*100:5.2f}%/mo  M={M:7.3f} (doc c=5%: {Mdoc:7.3f})  ratio={M/Mdoc:5.2f}")
print("  -> using the doc's own price-tier data instead of a flat 5% moves the low-price rows")
print("     by the factor above. The doc cites this table in 6.4 and ignores it in 6.5.")

print("\n"+"="*76)
print("[H] 'Constant M' is not a constraint -- it is the WORST feasible schedule")
print("="*76)
B=rev/15000
print(f"  target B={B:.2f} at T=18, c=0.05")
print(f"  constant M: M={M_of(B):.3f}/mo, TOTAL acquisitions over 18mo = {M_of(B)*T:.2f}")
print(f"  all-at-the-end:                 TOTAL acquisitions          = {B:.2f}")
print(f"  => flat schedule needs {M_of(B)*T/B:.2f}x more total acquisitions than back-loaded.")
print("  A solo founder's budget is total hours over T, not hours in every single month.")
print("  Testing feasibility as 'monthly rate <= H' rather than 'total <= H*T' is a")
print("  different (and here stricter, and mis-specified) constraint.")

print("\n"+"="*76)
print("[I] The constraint the doc omits and that DOES favour high price: support load")
print("="*76)
for P in (4500,15000,50000,150000):
    B=rev/P
    for sigma in (0.1,0.25,0.5):
        print(f"   P={P:>7} B={B:6.1f}  support {sigma:4.2f}h/customer/mo -> {B*sigma:7.1f} h/mo"
              + ("  EXCEEDS 30.3h budget" if B*sigma>H else ""))
    print()
