import math
G=500_000; m=0.70; c=0.05; T=18; H=7*52/12; rev=G/m
def M_of(B,c=0.05,T=18): return c*B/(1-math.exp(-c*T))

print("="*76)
print("[C] Is 'raise the price' monotone? Couple s and tau to price.")
print("="*76)
print("""
Required acquisition hours per month (cold-only, ignoring warm for the asymptotics):
   Hreq = R*tau = (M/s)*tau ,  M ∝ B ∝ 1/P
   Let s(P)=s0*(P/P0)^(-eps) , tau(P)=tau0*(P/P0)^(+gam)
   =>  Hreq ∝ P^(eps+gam-1)
   The doc assumes eps=gam=0  -> Hreq ∝ 1/P  (monotone decreasing: its whole conclusion)
   Hreq is FLAT in P  iff  eps+gam = 1        (the 'CAC scales with ACV' regularity)
   Hreq INCREASES in P iff eps+gam > 1
""")
P0=15000; s0=0.005; tau0=0.25
def hours(P,eps,gam,warm=True):
    B=rev/P; M=M_of(B)
    s=s0*(P/P0)**(-eps); tau=tau0*(P/P0)**(gam)
    wM=(60/T)*0.10 if warm else 0.0
    need=max(M-wM,0.0)
    return (need/s)*tau
print("Required hours/month at 4 prices, for several (eps,gam):")
print(f"{'eps':>5}{'gam':>5} | " + "".join(f"{p:>12}" for p in (4500,15000,50000,150000)) + "   verdict")
for eps,gam in [(0,0),(0.2,0.2),(0.3,0.3),(0.5,0.5),(0.0,1.0),(0.4,0.8),(0.8,0.8)]:
    hs=[hours(p,eps,gam) for p in (4500,15000,50000,150000)]
    ok=[("OK" if h<=H else "x") for h in hs]
    print(f"{eps:>5.1f}{gam:>5.1f} | " + "".join(f"{h:>10.1f}{o:>2}" for h,o in zip(hs,ok)) +
          f"   sum={eps+gam:.1f} -> "+("decreasing" if eps+gam<1 else ("FLAT" if abs(eps+gam-1)<1e-9 else "INCREASING")))

print("\n[C-2] What eps+gam is needed for the doc's ranking to survive?")
print("  The doc's claim 'only 150,000 works' requires Hreq(150000) <= H < Hreq(50000).")
for tot in [i/20 for i in range(0,21)]:
    h150=hours(150000,tot,0.0); h50=hours(50000,tot,0.0)
    print(f"   eps+gam={tot:4.2f}: h(150k)={h150:8.1f} h(50k)={h50:8.1f} "
          + ("doc-conclusion holds" if h150<=H<h50 else ("ALL fail" if h150>H else "50k also OK")))

print("\n[C-3] Implied CAC in hours per customer (doc's own assumptions, cold):")
for P in (4500,15000,50000,150000):
    contacts=1/0.005; hrs=contacts*0.25
    ltv=P*0.70*20  # profit margin * mean lifetime 20mo
    print(f"   P={P:>7}: 200 contacts = {hrs:.0f} h/customer ; gross-profit LTV = {ltv:>12,.0f} yen"
          f" ; yen per hour of selling = {ltv/hrs:>9,.0f}")
print("  -> doc assumes the SAME 50 h of selling wins a 63,000-yen-LTV customer and a")
print("     2,100,000-yen-LTV customer. That is the entire source of 'only 150,000 works'.")
