import math
def M_const(c,B,T): return c*B/(1-math.exp(-c*T))
def integ(S,T,n=400000):
    h=T/n; return sum(S((i+0.5)*h) for i in range(n))*h

print("="*72); print("A-5. exact reproduction of the text's rounding path"); print("="*72)
c=0.05; T=18; s=0.02
print("  hypothesis: B is rounded to an integer FIRST, weeks = 4.3/month")
for price,Bi in ((4500,158),(15000,47),(50000,14)):
    M=M_const(c,Bi,T); R=M/s
    print(f"   price {price:>6,}: B={Bi:>3}  maint={Bi*c:5.2f}  M={M:6.3f}  reach={R:7.2f}  week={R/4.3:6.2f}")
print("   text:      4,500: 158 / 7.9 / 13.3 / 666 / 155")
print("              15,000: 47 / 2.4 / 4.0 / 198 / 46")
print("              50,000: 14 / 0.7 / 1.2 / 59 / 14")
print()
print("  period table, B=47:")
for Tm in (12,18,24,36):
    print(f"   T={Tm:>2}: reach={M_const(c,47,Tm)/s:7.2f}  (text 260/198/168/141)")
print()
print("  B from revenue: 500,000/0.7 = 714,285.7")
for price in (4500,15000,50000):
    print(f"   {price:>6,}: exact B={714285.7/price:7.3f} -> rounds to {round(714285.7/price)}")
print("  NOTE 4,500 exact B=158.73 -> nearest integer 159, but the text uses 158 (floor).")
print("       weeks/month 4.3 vs true 365.25/7/12 = %.4f" % (365.25/7/12))

print(); print("="*72); print("B-3. crossover: at what horizon does declining hazard help?"); print("="*72)
S12=0.548
def weib(k):
    lam = 12/((-math.log(S12))**(1/k)); return (lambda u: math.exp(-(u/lam)**k)), lam
Sc = lambda u: math.exp(-0.05*u)
print(f"  {'T (months)':>11}", "".join(f"{f'k={k}':>10}" for k in (0.7,0.5,0.4)))
print("  ratio M_declining / M_constant  (>1 means constant hazard UNDERSTATES the need)")
for Tm in (6,12,18,24,30,36,48,60,120,240):
    row=[]
    Ic=integ(Sc,Tm)
    for k in (0.7,0.5,0.4):
        S,_=weib(k); row.append(Ic/integ(S,Tm))
    print(f"  {Tm:>11}", "".join(f"{v:>10.3f}" for v in row))
print()
print("  steady state (maintenance column): required acquisition = B / E[lifetime]")
print(f"  {'model':<22}{'E[life]':>10}{'maint @B=158':>14}{'maint @B=47':>13}{'maint @B=14':>13}")
for name,S in [("constant c=0.05",Sc)]+[(f"Weibull k={k}",weib(k)[0]) for k in (0.7,0.5,0.4)]:
    E=integ(S,1200,400000)
    print(f"  {name:<22}{E:>10.2f}{158/E:>14.2f}{47/E:>13.2f}{14/E:>13.2f}")
print("  text maintenance column: 7.9 / 2.4 / 0.7")

print(); print("="*72); print("C-4. is the Phase 1 measurement decision-relevant at all?"); print("="*72)
print("  chain in the text: pool N -> reply rate r -> conversation -> conversion s -> contracts")
print("  but the formula R = M/s has NO slot for r. r rescales the POOL, not the rate.")
need = {4500:M_const(0.05,158,18)/0.02, 15000:M_const(0.05,47,18)/0.02, 50000:M_const(0.05,14,18)/0.02}
for price,R in need.items():
    print(f"   price {price:>6,}: required reach {R:7.1f} people/MONTH -> {R*18:8.0f} people over 18 months")
print()
print("  a Phase 0 named pool is realistically 30-150 people (one-off, non-renewing).")
for N in (30,50,100,150,300):
    print(f"   pool N={N:>3}: months of supply at the 15,000-yen row ({need[15000]:.0f}/mo) = {N/need[15000]:5.2f} months")
print("  => at ANY reply rate in [0,1] the named pool covers <1 month of the required reach.")
print("     the Phase 1 estimate of r therefore cannot flip the decision; the binding number is N.")
print()
print("  what n=15 CAN decide (Wilson 95%):")
def wilson(k,n,z=1.959963985):
    p=k/n; d=1+z*z/n
    cen=(p+z*z/(2*n))/d
    hw=z/d*math.sqrt(p*(1-p)/n + z*z/(4*n*n))
    return max(cen-hw,0.0), min(cen+hw,1.0)
for k in range(0,16):
    lo,hi=wilson(k,15)
    print(f"   {k:>2}/15 = {k/15:6.1%}  [{lo:6.1%}, {hi:6.1%}]  width {(hi-lo)*100:5.1f}pp")

print(); print("="*72); print("C-5. n needed to separate two candidate rates"); print("="*72)
def n_for_diff(p1,p2,alpha=0.05,power=0.80):
    za=1.959963985; zb=0.8416212336
    pbar=(p1+p2)/2
    n=(za*math.sqrt(2*pbar*(1-pbar))+zb*math.sqrt(p1*(1-p1)+p2*(1-p2)))**2/(p1-p2)**2
    return math.ceil(n)
for a,b in ((0.20,0.10),(0.20,0.30),(0.02,0.01),(0.02,0.04),(0.15,0.005)):
    print(f"   separate {a:.1%} from {b:.1%} (two-sample, 80% power, a=0.05): n = {n_for_diff(a,b)} per arm")

print(); print("="*72); print("D-2. joint sensitivity grid, required reach /month, price 15,000, T=18"); print("="*72)
print("  rows = margin, cols = conversion rate; churn model = constant c=0.05")
cols=(0.005,0.01,0.02,0.05,0.15)
print(f"  {'margin':>8}", "".join(f"{f's={x:.1%}':>12}" for x in cols))
for m in (0.9,0.7,0.5,0.3):
    B=500000/m/15000
    print(f"  {m:>8.0%}", "".join(f"{M_const(0.05,B,18)/x:>12.0f}" for x in cols))
print()
print("  same grid at price 50,000:")
print(f"  {'margin':>8}", "".join(f"{f's={x:.1%}':>12}" for x in cols))
for m in (0.9,0.7,0.5,0.3):
    B=500000/m/50000
    print(f"  {m:>8.0%}", "".join(f"{M_const(0.05,B,18)/x:>12.0f}" for x in cols))

print(); print("="*72); print("D-3. what the goal level does"); print("="*72)
print("  JILPT: median 50,000 yen/mo, mean 92,445, 41.2% under 50,000")
for G in (50_000,92_445,200_000,500_000,1_000_000):
    B=G/0.7/15000
    print(f"   goal {G:>9,} yen gross profit/mo -> B={B:6.1f} contracts, M={M_const(0.05,B,18):5.2f}/mo, reach={M_const(0.05,B,18)/0.02:7.1f}/mo, {M_const(0.05,B,18)/0.02/4.3:6.1f}/week")

print(); print("="*72); print("E-2. proposed replacement table (constant hazard kept, route split added)"); print("="*72)
print("  M = B / INT_0^T S(u)du ;  M = sum_i R_i s_i")
print("  warm pool: 60 named people over 18 months (R_warm=3.33/mo), s_warm=0.10")
print("  cold: s_cold=0.005, tau=0.25 h/contact ; time budget 30.3 h/month")
H=7*52/12
for price in (4500,15000,50000,150000):
    B=714285.7/price; M=M_const(0.05,B,18)
    Rw=60/18; Mw=Rw*0.10
    rest=max(M-Mw,0)
    Rc=rest/0.005; hrs=Rc*0.25
    ok="OK" if hrs<=H else f"x{hrs/H:.0f} over"
    print(f"   {price:>7,}  B={B:6.1f}  M={M:5.2f}/mo  warm {Mw:.2f}  cold needed {Rc:8.1f}/mo = {hrs:7.1f} h/mo  [{ok}]")
print()
print("  price at which the whole thing fits in 30.3 h/month with the warm pool + cold:")
lo,hi=1000,10_000_000
for _ in range(200):
    mid=(lo+hi)/2
    B=714285.7/mid; M=M_const(0.05,B,18)
    rest=max(M-(60/18)*0.10,0); hrs=rest/0.005*0.25
    if hrs>H: lo=mid
    else: hi=mid
print(f"   break-even unit price = {(lo+hi)/2:,.0f} yen/month  (s_cold=0.5%)")
for sc in (0.01,0.02,0.05):
    lo,hi=1000,10_000_000
    for _ in range(200):
        mid=(lo+hi)/2
        B=714285.7/mid; M=M_const(0.05,B,18)
        rest=max(M-(60/18)*0.10,0); hrs=rest/sc*0.25
        if hrs>H: lo=mid
        else: hi=mid
    print(f"   ... if s_cold={sc:.1%}: break-even unit price = {(lo+hi)/2:,.0f} yen/month")
