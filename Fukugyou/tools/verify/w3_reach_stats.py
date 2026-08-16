# W3 reach model audit -- deterministic, no RNG (seed irrelevant but fixed for any future MC)
import math, random
random.seed(20260811)

def line(t=""): print(t)

# ---------- A. formula re-derivation & recomputation ----------
line("="*70); line("A-1. formula check: M = c*B / (1 - exp(-c*T))"); line("="*70)
# db/dt = M - c*b, b(0)=0  ->  b(t) = (M/c)(1 - e^{-ct});  b(T)=B -> M = cB/(1-e^{-cT})
# generalized: with survival S(u), b(T) = M * int_0^T S(u) du  ->  M = B / int_0^T S
def M_const(c,B,T): return c*B/(1-math.exp(-c*T))
def simulate(M,c,T,steps=100000):
    dt=T/steps; b=0.0
    for _ in range(steps): b += (M - c*b)*dt
    return b
c=0.05; T=18; Btest=158.73
Mt = M_const(c,Btest,T)
line(f"  closed form M={Mt:.6f}  ODE integration b(T)={simulate(Mt,c,T):.6f} (target {Btest:.6f})")

line(); line("="*70); line("A-2. table recomputation"); line("="*70)
G=500_000; margin=0.70; s=0.02
rev = G/margin
line(f"  required monthly revenue = {G:,}/{margin} = {rev:,.1f} yen  (text: 'about 710,000')")
for rv,tag in [(rev,"exact 714,285.7"),(710_000,"rounded 710,000")]:
    line(f"  --- base revenue {rv:,.1f} ({tag}) ---")
    line(f"  {'price':>8} {'B':>9} {'maint':>7} {'M(18m)':>8} {'reach/mo':>9} {'/4.33w':>8} {'/4.3w':>7} {'x12/52':>7}")
    for p in (4500,15000,50000):
        B=rv/p; M=M_const(c,B,T); R=M/s
        line(f"  {p:>8,} {B:>9.2f} {B*c:>7.2f} {M:>8.2f} {R:>9.1f} {R/(365.25/7/12):>8.1f} {R/4.3:>7.1f} {R*12/52:>7.1f}")

line(); line("  --- text values: 158/7.9/13.3/666/155 ; 47/2.4/4.0/198/46 ; 14/0.7/1.2/59/14 ---")

line(); line("="*70); line("A-3. period variation, price 15,000"); line("="*70)
B15=rev/15000
line(f"  B(15,000 yen) = {B15:.3f} contracts")
for Tm in (12,18,24,36):
    M=M_const(c,B15,Tm); R=M/s
    line(f"   T={Tm:>2}m  M={M:5.2f}/mo  reach={R:6.1f}/mo   (text: 12->260, 18->198, 24->168, 36->141)")

line(); line("="*70); line("A-4. the '92 months' claim"); line("="*70)
line("  With M = c*B exactly: b(t) = B(1 - e^{-ct}) -> b(t) < B for all finite t (never reaches).")
for frac in (0.90,0.95,0.99,0.995,0.999):
    t=-math.log(1-frac)/c
    line(f"   time to reach {frac*100:5.1f}% of B : {t:7.2f} months")
line("  => 92 months is the time to reach 99% of B, not 'the time it eventually arrives'.")
# alternative reading: M = 1.01 * c*B
line("  alt reading: M = 1.01*c*B -> b(t) = 1.01*B(1-e^{-ct}) = B at t =")
line(f"   t = {-math.log(1-1/1.01)/c:.2f} months  (does NOT give 92)")

# ---------- B. constant-hazard assumption ----------
line(); line("="*70); line("B-1. constant hazard vs declining hazard (Weibull / mover-stayer)"); line("="*70)
S12=0.548
def weib(k):
    lam = 12/((-math.log(S12))**(1/k))
    return (lambda u: math.exp(-(u/lam)**k)), lam
def integ(S,T,n=200000):
    h=T/n; tot=0.0
    for i in range(n): tot += S((i+0.5)*h)*h
    return tot
def ms(p_churner, c_fast):
    # fraction p churns at monthly hazard c_fast, rest never churn; calibrated so S(12)=0.548
    return lambda u: (1-p_churner) + p_churner*math.exp(-c_fast*u)

models=[]
Sc = lambda u: math.exp(-0.05*u)
models.append(("constant hazard c=0.05 (text)", Sc))
for k in (1.0,0.7,0.5,0.4):
    S,lam = weib(k); models.append((f"Weibull k={k} (lambda={lam:.1f})", S))
# mover-stayer: choose p so that with c_fast=0.20, S(12)=0.548
for cf in (0.15,0.25):
    # (1-p) + p*e^{-cf*12} = 0.548  -> p = (1-0.548)/(1-e^{-cf*12})
    p=(1-S12)/(1-math.exp(-cf*12))
    models.append((f"mover-stayer p={p:.3f} churn-hazard={cf}", ms(p,cf)))

line(f"  all calibrated to S(12)=0.548 (the only data-backed anchor)")
line(f"  {'model':<44}{'S(12)':>7}{'S(24)':>7}{'S(36)':>7}{'INT0-18':>9}{'M rel':>7}")
base=None
for name,S in models:
    I=integ(S,18)
    if base is None: base=I
    line(f"  {name:<44}{S(12):>7.3f}{S(24):>7.3f}{S(36):>7.3f}{I:>9.3f}{base/I:>7.3f}")
line("  'M rel' = required acquisition relative to the constant-hazard model (M = B / INT).")

line(); line("  effect on the 15,000-yen row (B=47.6, T=18, s=2%):")
for name,S in models:
    I=integ(S,18); M=B15/I; R=M/s
    line(f"   {name:<44} M={M:5.2f}/mo  reach={R:6.1f}/mo")

line(); line("  long-run steady state book per 1 acquisition/month = E[lifetime] = INT_0^inf S:")
for name,S in models:
    line(f"   {name:<44} E[life]={integ(S,600,300000):8.2f} months")

# ---------- B-2. route-decomposed model ----------
line(); line("="*70); line("B-2. route-decomposed model"); line("="*70)
line("  single-rate : R_total = M / s_bar")
line("  route model : M = sum_i R_i * s_i ,  s.t. sum_i R_i*tau_i <= H (time),  R_i <= N_i/T (pool)")
line("  s_bar is the REACH-weighted mean: s_bar = sum(R_i s_i)/sum(R_i)")

# scenario: warm referral pool finite, cold unbounded
routes = [
    # name, s_i, pool N_i (people reachable over T months), tau_i hours per contact
    ("warm (ex-colleagues, named)", 0.15,  40, 0.50),
    ("referral from interviews",    0.10,  30, 0.40),
    ("community where you belong",  0.03, 200, 0.20),
    ("cold outreach",               0.005, 10**9, 0.25),
    ("ads (impressions)",           0.0002,10**9, 0.0),
]
H = 7*52/12   # hours per month available = 30.33
line(f"  time budget H = {H:.2f} h/month (7h/week)")
need_M = M_const(c,B15,18)
line(f"  required M (price 15,000, T=18, constant hazard) = {need_M:.2f} contracts/month")
line()
line(f"  {'route':<32}{'s_i':>8}{'cap R_i/mo':>12}{'M_i':>8}{'h/mo':>8}{'M per hour':>12}")
cum_M=0; cum_h=0
for n,si,Ni,tau in routes:
    cap = Ni/18 if Ni<10**8 else float('inf')
    Mi = cap*si if cap!=float('inf') else float('nan')
    hi = cap*tau if cap!=float('inf') else float('nan')
    eff = si/tau if tau>0 else float('inf')
    capstr = f"{cap:.1f}" if cap!=float('inf') else "inf"
    Mistr  = f"{Mi:.2f}" if cap!=float('inf') else "-"
    histr  = f"{hi:.2f}" if cap!=float('inf') else "-"
    line(f"  {n:<32}{si:>8.4f}{capstr:>12}{Mistr:>8}{histr:>8}{eff:>12.4f}")
    if cap!=float('inf'): cum_M+=Mi; cum_h+=hi
line(f"  finite-pool routes total: M={cum_M:.2f}/mo using {cum_h:.2f} h/mo")
line(f"  shortfall to be covered by unbounded routes: {need_M-cum_M:.2f} contracts/mo")
rem_h = H-cum_h
s_cold=0.005; tau_cold=0.25
line(f"  remaining time {rem_h:.2f} h/mo -> cold contacts {rem_h/tau_cold:.0f}/mo -> {rem_h/tau_cold*s_cold:.2f} contracts/mo")
line(f"  => achievable M = {cum_M + rem_h/tau_cold*s_cold:.2f} vs required {need_M:.2f}")
# implied s_bar
tot_R = sum((Ni/18) for _,_,Ni,_ in routes if Ni<10**8) + rem_h/tau_cold
tot_M = cum_M + rem_h/tau_cold*s_cold
line(f"  implied reach-weighted s_bar = {tot_M/tot_R:.4f}  (text assumes 0.02)")
line(f"  MARGINAL s (the rate that governs the next contact) = {s_cold:.4f}")

# ---------- C. measurement power ----------
line(); line("="*70); line("C-1. Phase 1: 15 contacts, 3 replies"); line("="*70)
def wilson(k,n,z=1.959963985):
    p=k/n; d=1+z*z/n
    cen=(p+z*z/(2*n))/d
    hw=z/d*math.sqrt(p*(1-p)/n + z*z/(4*n*n))
    return cen-hw, cen+hw
def betainv_cdf(a,b,x):
    return None
# Clopper-Pearson via bisection on binomial tail
def binom_cdf(k,n,p):
    return sum(math.comb(n,i)*p**i*(1-p)**(n-i) for i in range(0,k+1))
def cp(k,n,alpha=0.05):
    lo,hi=0.0,1.0
    if k==0: L=0.0
    else:
        a,b=0.0,1.0
        for _ in range(200):
            m=(a+b)/2
            if 1-binom_cdf(k-1,n,m) > alpha/2: b=m
            else: a=m
        L=(a+b)/2
    if k==n: U=1.0
    else:
        a,b=0.0,1.0
        for _ in range(200):
            m=(a+b)/2
            if binom_cdf(k,n,m) < alpha/2: b=m
            else: a=m
        U=(a+b)/2
    return L,U
for k,n in ((3,15),(2,15),(4,15),(0,15),(1,15)):
    w=wilson(k,n); c_=cp(k,n)
    line(f"  {k}/{n} = {k/n:.1%}  Wilson95 [{w[0]:.1%}, {w[1]:.1%}] width {(w[1]-w[0])*100:.1f}pp | ClopperPearson [{c_[0]:.1%}, {c_[1]:.1%}]")
line("  ratio of CI bounds for 3/15 (Wilson): %.1f x" % (wilson(3,15)[1]/wilson(3,15)[0]))
line("  -> required reach = M/s ; propagating the CI:")
Mneed = M_const(c,B15,18)
lo,hi = wilson(3,15)
line(f"     if this rate were the conversion rate: reach in [{Mneed/hi:.0f}, {Mneed/lo:.0f}] people/month (factor {hi/lo:.1f})")

line(); line("="*70); line("C-2. sample size for +-10pp / +-5pp"); line("="*70)
def wilson_hw(p,n,z=1.959963985):
    d=1+z*z/n
    return z/d*math.sqrt(p*(1-p)/n + z*z/(4*n*n))
for p in (0.05,0.10,0.20,0.30,0.50):
    for tgt in (0.10,0.05):
        n=2
        while wilson_hw(p,n) > tgt and n<200000: n+=1
        line(f"   p={p:.2f}  half-width <= {tgt*100:.0f}pp  ->  n = {n}")
line("   normal-approx check n = z^2 p(1-p)/e^2 :")
for p in (0.20,0.50):
    for tgt in (0.10,0.05):
        line(f"     p={p} e={tgt} -> n={1.959963985**2*p*(1-p)/tgt**2:.1f}")

line(); line("="*70); line("C-3. rule of three, 0/30"); line("="*70)
for n in (15,20,30,50,100):
    U1 = 1-0.05**(1/n)          # one-sided 95% upper
    U2 = 1-0.025**(1/n)         # two-sided 95% upper
    line(f"   0/{n}: exact one-sided 95% upper = {U1:.2%} ; two-sided = {U2:.2%} ; 3/n rule = {3/n:.2%}")
line("   text says 'about 10-12% or less (one-sided 9.5% / two-sided 11.6%)'")
line("   power: probability of observing 0/30 when the TRUE rate is:")
for tp in (0.02,0.03,0.05,0.10):
    line(f"     s={tp:.0%} -> P(0 successes in 30) = {(1-tp)**30:.1%}")

# ---------- D. sensitivity / elasticity ----------
line(); line("="*70); line("D. elasticity of required reach R"); line("="*70)
line("  R = (G/(m*price)) * c / (s * (1 - e^{-cT}))")
def R_of(G=500_000,m=0.70,price=15000,s=0.02,c=0.05,T=18):
    B=G/m/price
    return M_const(c,B,T)/s
base_R=R_of()
line(f"  base R = {base_R:.2f} people/month")
line()
line(f"  {'variable':<12}{'analytic d lnR/d ln x':>24}{'numeric':>12}{'R at -20%':>12}{'R at +20%':>12}")
def numel(var):
    h=1e-5
    up=R_of(**{var:{'G':500_000,'m':0.70,'price':15000,'s':0.02,'c':0.05,'T':18}[var]*(1+h)})
    dn=R_of(**{var:{'G':500_000,'m':0.70,'price':15000,'s':0.02,'c':0.05,'T':18}[var]*(1-h)})
    return (math.log(up)-math.log(dn))/(2*math.log((1+h)/(1-h)))*2/2*1.0/( (math.log(1+h)-math.log(1-h))/ (math.log(1+h)-math.log(1-h)) )
def numel2(var,val):
    h=1e-6
    up=R_of(**{var:val*(1+h)}); dn=R_of(**{var:val*(1-h)})
    return (math.log(up/dn))/(math.log((1+h)/(1-h)))
cT=c*T; ec=math.exp(-cT)
ana={'G':1.0,'m':-1.0,'price':-1.0,'s':-1.0,
     'c':1-cT*ec/(1-ec),
     'T':-cT*ec/(1-ec)}
vals={'G':500_000,'m':0.70,'price':15000,'s':0.02,'c':0.05,'T':18}
for v in ('s','m','price','G','c','T'):
    line(f"  {v:<12}{ana[v]:>24.4f}{numel2(v,vals[v]):>12.4f}{R_of(**{v:vals[v]*0.8}):>12.1f}{R_of(**{v:vals[v]*1.2}):>12.1f}")
line()
line("  |elasticity| ranking: s = m = price = 1.000 > T = %.3f > c = %.3f" % (abs(ana['T']),abs(ana['c'])))
line()
line("  halving each variable (or doubling for c/T):")
for v,mult in (('s',0.5),('m',0.5),('price',0.5),('price',2.0),('c',2.0),('T',2.0)):
    line(f"   {v} x{mult}: R = {R_of(**{v:vals[v]*mult}):.1f}  ({R_of(**{v:vals[v]*mult})/base_R:.2f}x)")

line(); line("  joint: margin 50% + s 1% + Weibull k=0.5 churn, price 15,000, T=18")
S,_=weib(0.5); I=integ(S,18)
B2=500_000/0.50/15000
line(f"   B={B2:.1f}  M={B2/I:.2f}  reach={B2/I/0.01:.0f}/month  (text row says 198)")

# ---------- E. corrected table ----------
line(); line("="*70); line("E. corrected table (route-aware, hazard-aware)"); line("="*70)
line("  reach expressed as 1:1 contacts; warm pool 70 people consumed over T, then cold")
for price in (4500,15000,50000):
    for label,S in (("const c=0.05",Sc),("Weibull k=0.5",weib(0.5)[0])):
        I=integ(S,18); B=rev/price; M=B/I
        # warm pool: 70 people over 18 months at s=0.12
        warm_R=70/18; warm_M=warm_R*0.12
        rest=max(M-warm_M,0.0)
        cold_R=rest/0.005
        line(f"   {price:>6,} {label:<15} B={B:6.1f} M={M:5.2f}/mo  warm gives {warm_M:.2f}/mo, "
             f"remaining {rest:5.2f}/mo needs {cold_R:8.1f} cold contacts/mo ({cold_R*0.25:7.1f} h/mo)")
line(f"  available time = {H:.1f} h/month")
