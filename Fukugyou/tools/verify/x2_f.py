import math
G=500_000; m=0.70; c=0.05; T=18; H=7*52/12; rev=G/m
def M_of(B,c=0.05,T=18): return c*B/(1-math.exp(-c*T))

print("="*78)
print("[J] Cumulative reach actually required -- put next to the doc's own install data")
print("="*78)
print(f"{'price':>8}{'B':>8}{'M/mo':>8} | cumulative reach over 18mo at s = 0.5% / 1% / 2%")
for P in (4500,15000,50000,150000):
    B=rev/P; M=M_of(B); tot=M*T
    print(f"{P:>8}{B:>8.1f}{M:>8.2f} | "+"  ".join(f"{tot/s:>10,.0f}" for s in (0.005,0.01,0.02)))
print("""
  The doc's own Phase 2 threshold C2 (WordPress) is: a top-8 plugin has >= 52,500 active
  installs. A listing that delivers 24,000 page views over 18 months is far below that.
  The doc measures this quantity with a free API (5.2) and then does not use it in 6.5.1.
""")

print("="*78)
print("[K] Corrected feasibility table: hours/month by channel ARCHITECTURE, not by price")
print("="*78)
def sim(reach_fn,s,c=0.05,T=18,n=40000):
    dt=T/n;b=0.0
    for i in range(n): b+=(reach_fn(i*dt)*s-c*b)*dt
    return b
tau=0.25
def flow_hours(P,s_cold=0.005,warm_pool=60,warm_s=0.10):
    B=rev/P; M=M_of(B); need=max(M-(warm_pool/T)*warm_s,0)
    return (need/s_cold)*tau
# stock: one marketplace listing, one-off build h_build, emits a0 reach/mo, delta decay,
# plus upkeep h_up per month
def stock_feasible(P,a0,h_build=40,h_up=4,delta=0.02,s=0.01):
    B=rev/P
    f=lambda t: a0*math.exp(-delta*t)
    got=sim(f,s)
    return got,B,h_build/T+h_up   # amortized hours/month
print("(a) FLOW ONLY (the doc's model): hours/month of 1-to-1 contact")
for P in (4500,15000,50000,150000):
    h=flow_hours(P); print(f"    {P:>8}: {h:8.1f} h/mo  {'OK' if h<=H else 'x  (%.1fx over)'%(h/H)}")
print("\n(b) ONE marketplace listing, built once in 40h, upkeep 4h/mo, visit->paid s=1%, decay 2%/mo")
print("    amortized hours/month = 40/18 + 4 = %.1f h/mo  (fits in 30.3h with room to build)"%(40/18+4))
print(f"    {'price':>8}{'B needed':>10} | contracts at 18mo for listing reach a0 = 100/300/1000 per month")
for P in (4500,15000,50000,150000):
    got=[stock_feasible(P,a0)[0] for a0 in (100,300,1000)]
    B=rev/P
    print(f"    {P:>8}{B:>10.1f} | "+"  ".join(f"{g:>8.1f}{'OK' if g>=B else ' x'}" for g in got))
print("""
  Reading: at 300 visits/month from a single listing (a modest plugin), the 4,500-yen row --
  the row the doc declares impossible at 21x -- clears its 159-contract target, using ~6 h/mo.
  Nothing about the price changed. The channel architecture changed.
""")

print("="*78)
print("[L] Minimum viable price under the doc's model vs under a stock channel")
print("="*78)
def minprice(s_cold,warm_pool=60,warm_s=0.10):
    lo,hi=1000.0,2_000_000.0
    for _ in range(200):
        mid=(lo+hi)/2
        if flow_hours(mid,s_cold,warm_pool,warm_s)>H: lo=mid
        else: hi=mid
    return hi
for s in (0.005,0.01,0.02,0.05):
    print(f"   flow-only, cold s={s*100:4.1f}%: minimum price = {minprice(s):>10,.0f} yen/mo")
print("   (reproduces the doc's 64,024 / 38,911 / 21,805 / 9,404 -- arithmetic confirmed)")
print()
for a0 in (100,300,1000,3000):
    for s in (0.005,0.01):
        lo,hi=100.0,2_000_000.0
        for _ in range(120):
            mid=(lo+hi)/2
            got=sim(lambda t: a0*math.exp(-0.02*t), s, n=4000)
            if got < rev/mid: lo=mid
            else: hi=mid
        print(f"   one listing a0={a0:>5}/mo, s={s*100:4.1f}%: minimum price = {hi:>10,.0f} yen/mo")
