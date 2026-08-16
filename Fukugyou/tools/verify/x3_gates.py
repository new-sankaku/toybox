# X3: gate (judgement rule) adversarial verification
# seed fixed, reproducible
import numpy as np, itertools, math
from scipy import stats, optimize
rng = np.random.default_rng(20260812)
P = print

# ---------------------------------------------------------------
# data: G_thresholds.md 3.1 (WordPress, n=22)
# keyword, hits, top8_install_median, concentration, rating_median, months_median, C1,C2,C3,C4
WP = [
("accounting",429,950,0.87,98.00,2.3,0,0,1,0),
("appointment scheduling",332,40000,0.30,89.00,0.2,0,1,0,0),
("approval workflow",411,550,0.99,97.00,1.2,0,0,1,1),
("asset management",1946,455000,0.78,92.00,0.4,0,1,0,0),
("booking calendar",721,25000,0.31,93.00,0.2,0,1,0,1),
("compliance audit",750,300000,0.31,96.00,0.6,0,1,0,0),
("contract management",260,35500,0.72,97.00,0.3,1,1,0,0),
("crm",1302,4000,0.96,96.00,0.5,0,1,0,0),
("digital signature",241,950,1.00,83.00,-0.0,1,0,0,0),
("document management",1074,6500,0.88,95.00,0.4,0,0,0,0),
("expense report",69,1000,0.41,96.00,0.7,1,0,0,0),
("helpdesk",332,4000,0.80,91.00,0.8,0,0,0,1),
("inventory management",727,1500,0.44,93.00,0.3,0,0,0,1),
("invoice",1513,5500,0.75,94.00,1.1,0,0,0,1),
("payroll",29,200,0.94,94.00,2.0,1,0,1,0),
("purchase order",2843,3000,0.90,94.00,2.6,0,1,1,0),
("quotation",294,2500,0.95,89.00,1.6,0,1,1,0),
("recruitment",111,3000,0.98,95.00,1.4,1,0,1,0),
("shipping",3601,50000,0.96,91.00,0.1,0,1,0,0),
("subscription billing",857,10000,0.85,93.00,0.3,0,1,0,1),
("tax calculation",515,185000,0.82,90.00,0.2,0,1,0,0),
("timesheet",16,600,0.62,88.00,0.6,1,0,0,0),
]
names=[r[0] for r in WP]
hits=np.array([r[1] for r in WP],float)
mon =np.array([r[5] for r in WP],float)
M   =np.array([[r[6],r[7],r[8],r[9]] for r in WP],float)   # 22x4

ATL=[(0,0,0),(0,1,0),(0,1,0),(0,0,0),(0,1,0),(0,0,0),(0,0,0),(0,1,0),(0,0,0),(0,0,0),
     (0,0,0),(1,0,1),(0,1,0),(1,0,1),(1,1,0),(0,0,1),(1,0,0),(1,0,0),(1,1,1),(0,1,1),
     (0,0,1),(0,1,0)]
VSC=[(0,0,0),(0,1,0),(0,1,0),(0,1,1),(0,1,0),(0,1,0),(1,0,0),(0,0,1),(0,0,0),(0,0,0),
     (1,0,1),(1,0,0),(0,1,0),(0,0,1),(1,0,0),(0,1,1),(1,1,0),(0,0,0),(0,0,0),(0,0,0)]
CHR=[(0,1),(0,0),(0,0),(1,0),(1,1),(1,0),(1,0),(1,0),(1,0),(0,1)]

P("="*70); P("[1] measured pass rate / k-of-n")
def kofn(mat):
    a=np.array(mat,float); s=a.sum(1); n=a.shape[1]
    return s,n
for nm,mat in [("WordPress",M),("Atlassian",ATL),("VSCode dev",VSC),("Chrome",CHR)]:
    s,n=kofn(mat)
    P(f"{nm:12s} n_kw={len(s):3d} cond={n}  marginals={np.array(mat,float).sum(0).astype(int)}"
      f"  >=1:{(s>=1).mean():.3f} >=2:{(s>=2).mean():.3f} >=3:{(s>=3).mean():.3f}")

P()
P("="*70); P("[2] null model: are the conditions doing anything beyond their marginals?")
# independent Bernoulli with observed marginals -> analytic P(pass >=2 of 4)
p=M.mean(0)
P(f"WP marginals p = {np.round(p,4)}")
tot=0.0
for combo in itertools.product([0,1],repeat=4):
    pr=np.prod([p[i] if c else 1-p[i] for i,c in enumerate(combo)])
    if sum(combo)>=2: tot+=pr
P(f"P(>=2 of 4 | independent, observed marginals) = {tot:.4f}   -> expected words {tot*22:.2f}")
P(f"observed                                      = {(M.sum(1)>=2).mean():.4f}   -> observed words {(M.sum(1)>=2).sum()}")
# permutation: shuffle each column independently 200k times
B=200000
cnt=np.zeros(B,int)
cols=[M[:,i].copy() for i in range(4)]
for b in range(B):
    sh=np.column_stack([rng.permutation(c) for c in cols])
    cnt[b]=(sh.sum(1)>=2).sum()
P(f"permutation (columns shuffled independently, B={B}):")
P(f"  mean #pass = {cnt.mean():.2f}, sd = {cnt.std():.2f}, "
  f"P(#pass <= 8) = {(cnt<=8).mean():.4f}, P(#pass == 8)={(cnt==8).mean():.4f}")
P(f"  -> observed 8 sits at percentile {stats.percentileofscore(cnt,8):.1f} of the no-structure null")

P()
P("="*70); P("[3] do the 4 conditions share a common latent 'prospect'?")
# phi coefficients + Fisher exact
lab=["C1","C2","C3","C4"]
phis=[]
for i,j in itertools.combinations(range(4),2):
    a=M[:,i]; b=M[:,j]
    n11=int(((a==1)&(b==1)).sum()); n10=int(((a==1)&(b==0)).sum())
    n01=int(((a==0)&(b==1)).sum()); n00=int(((a==0)&(b==0)).sum())
    phi=(n11*n00-n10*n01)/math.sqrt((n11+n10)*(n01+n00)*(n11+n01)*(n10+n00))
    orr,pv=stats.fisher_exact([[n11,n10],[n01,n00]])
    phis.append(phi)
    P(f"  {lab[i]}x{lab[j]}: n11={n11} n10={n10} n01={n01} n00={n00}  phi={phi:+.3f}  fisher p={pv:.3f}")
phis=np.array(phis)
P(f"  mean phi over 6 pairs = {phis.mean():+.4f}  (median {np.median(phis):+.3f})")
# implied common-factor loading: for a 1-factor probit model, pairwise tetrachoric r = rho^2
# estimate tetrachoric per pair, average, cap at 0
def tetra(n11,n10,n01,n00):
    tot=n11+n10+n01+n00
    p1=(n11+n10)/tot; p2=(n11+n01)/tot; p11=n11/tot
    h=stats.norm.ppf(1-p1); k=stats.norm.ppf(1-p2)
    f=lambda r: stats.multivariate_normal.cdf([-h,-k],mean=[0,0],cov=[[1,r],[r,1]])-p11
    try:
        return optimize.brentq(f,-0.95,0.95)
    except Exception:
        return np.nan
tets=[]
for i,j in itertools.combinations(range(4),2):
    a=M[:,i]; b=M[:,j]
    n11=int(((a==1)&(b==1)).sum()); n10=int(((a==1)&(b==0)).sum())
    n01=int(((a==0)&(b==1)).sum()); n00=int(((a==0)&(b==0)).sum())
    if min(n11,n10,n01,n00)==0:  # continuity correction
        n11,n10,n01,n00=n11+0.5,n10+0.5,n01+0.5,n00+0.5
    tets.append(tetra(n11,n10,n01,n00))
tets=np.array(tets,float)
P(f"  tetrachoric r per pair = {np.round(tets,3)}")
mt=np.nanmean(tets)
P(f"  mean tetrachoric = {mt:+.3f}  -> implied common loading rho = "
  f"{'imaginary (negative)' if mt<0 else round(math.sqrt(mt),3)}")
# 90% CI on mean phi by bootstrap over keywords
bs=[]
for _ in range(20000):
    idx=rng.integers(0,22,22); Mb=M[idx]
    v=[]
    for i,j in itertools.combinations(range(4),2):
        a=Mb[:,i]; b=Mb[:,j]
        n11=((a==1)&(b==1)).sum(); n10=((a==1)&(b==0)).sum()
        n01=((a==0)&(b==1)).sum(); n00=((a==0)&(b==0)).sum()
        d=(n11+n10)*(n01+n00)*(n11+n01)*(n10+n00)
        if d>0: v.append((n11*n00-n10*n01)/math.sqrt(d))
    if v: bs.append(np.mean(v))
bs=np.array(bs)
P(f"  bootstrap 90%CI of mean phi = [{np.percentile(bs,5):+.3f}, {np.percentile(bs,95):+.3f}]")

P()
P("="*70); P("[4] likelihood ratio of the gate under a 1-factor model")
# X_i = rho*Z + sqrt(1-rho^2)*e_i ; condition fires when X_i beyond its marginal threshold
def gate_lr(rho,pmarg,kmin=2,N=400000,zg=1.0,zb=-1.0):
    thr=stats.norm.ppf(1-np.array(pmarg))   # fire if X_i > thr
    out=[]
    for z in (zg,zb):
        e=rng.standard_normal((N,len(pmarg)))
        X=rho*z+math.sqrt(1-rho**2)*e
        out.append(((X>thr).sum(1)>=kmin).mean())
    return out[0],out[1]
P("  rho = loading of each condition on the true 'this niche is workable' latent")
P("  P(pass) for a candidate 1sd above / 1sd below average, and the likelihood ratio")
P(f"  {'rho':>5} {'P(pass|good)':>13} {'P(pass|bad)':>12} {'LR':>7} {'implied pairwise phi':>21}")
for rho in [0.0,0.1,0.2,0.3,0.5,0.7]:
    g,b=gate_lr(rho,p)
    P(f"  {rho:5.2f} {g:13.3f} {b:12.3f} {g/max(b,1e-9):7.2f} {rho**2:21.3f}")
P("  observed pairwise phi ~ -0.05 (90%CI includes 0) -> rho^2 <= ~0.05 -> rho <= ~0.22 -> LR <= ~1.6")

P()
P("="*70); P("[5] threshold instability: bootstrap the keyword sample, refit p25/p75, re-judge")
# C1: hits <= p25(hits); C3: months >= p75(months). C2/C4 flags held fixed (item-level data absent
# -> this UNDERSTATES the instability).
B=20000
flip=np.zeros(22); passcnt=np.zeros(22); npass=np.zeros(B)
for b in range(B):
    idx=rng.integers(0,22,22)
    t1=np.percentile(hits[idx],25); t3=np.percentile(mon[idx],75)
    c1=(hits<=t1).astype(float); c3=(mon>=t3).astype(float)
    Mb=np.column_stack([c1,M[:,1],c3,M[:,3]])
    pr=(Mb.sum(1)>=2).astype(float)
    passcnt+=pr; npass[b]=pr.sum()
passp=passcnt/B
base=(M.sum(1)>=2).astype(int)
P(f"  #passing words: mean {npass.mean():.2f}, 90%CI [{np.percentile(npass,5):.0f}, {np.percentile(npass,95):.0f}] (point estimate 8)")
P(f"  per-keyword P(pass) under resampled thresholds (baseline verdict in brackets):")
for i in np.argsort(-passp):
    P(f"    {names[i]:24s} [{'pass' if base[i] else 'fail'}]  P(pass)={passp[i]:.3f}")
amb=((passp>0.05)&(passp<0.95)).sum()
P(f"  keywords whose verdict is not stable at 95% level: {amb}/22 = {amb/22:.1%}")
P(f"  mean disagreement with the published verdict = {np.mean(np.abs(passp-base)):.3f}")

P()
P("="*70); P("[6] the gate is applied to 1-3 candidates, not 22")
for q in [0.36,0.23,0.20,0.10]:
    P(f"  pass rate {q:.2f}: P(all candidates die) k=1 {1-q:.3f}  k=2 {(1-q)**2:.3f}  k=3 {(1-q)**3:.3f}")
P("  labour gated: 段階3 19.0h + 段階4 53.0h + 段階5 7.5h = 79.5h ; gate itself 3.6h")
for q in [0.36,0.23,0.20,0.10]:
    P(f"  pass rate {q:.2f}: E[labour] = 3.6 + {q:.2f}*79.5 = {3.6+q*79.5:.1f}h (vs 79.5h ungated)")

P()
P("="*70); P("[7] rule of three with clustered (non-independent) contacts")
def bb_p0(pi,rho,m,k):
    """P(0 successes) for k clusters of size m, beta-binomial within cluster."""
    if rho<=1e-9: return (1-pi)**(m*k)
    a=pi*(1-rho)/rho; b=(1-pi)*(1-rho)/rho
    # P(X=0 | cluster) = B(a,b+m)/B(a,b)
    lp=math.lgamma(a+b)-math.lgamma(b)+math.lgamma(b+m)-math.lgamma(a+b+m)
    return math.exp(k*lp)
def upper(rho,m,k,alpha=0.05):
    f=lambda pi: bb_p0(pi,rho,m,k)-alpha
    return optimize.brentq(f,1e-9,0.999999)
P("  n=30 contacts, 0 conversions. one-sided 95% upper bound on the true rate:")
P(f"  {'ICC':>6} {'clusters x size':>16} {'upper bound':>12} {'n_eff':>7} {'vs independent':>15}")
base_u=upper(0,1,30)
for rho in [0.0,0.05,0.1,0.2,0.3,0.5]:
    for (k,m) in [(3,10),(5,6),(10,3)]:
        u=upper(rho,m,k)
        neff=math.log(0.05)/math.log(1-u)
        P(f"  {rho:6.2f} {f'{k} x {m}':>16} {u*100:11.2f}% {neff:7.1f} {u/base_u:14.2f}x")
    if rho==0: P("   ---")
deff=lambda rho,m: 1+(m-1)*rho
P("  design effect DEFF=1+(m-1)*ICC : ", {(m,rho):round(deff(rho,m),2) for m in (10,) for rho in (0.05,0.1,0.2,0.3)})
P("  n_eff = 30/DEFF and rule of three 3/n_eff:")
for rho in [0.05,0.1,0.2,0.3]:
    for m in [3,6,10]:
        ne=30/deff(rho,m); P(f"    ICC={rho:.2f} cluster size {m:2d}: n_eff={ne:5.1f}  3/n_eff={3/ne*100:5.1f}%")

P()
P("="*70); P("[8] winner's curse: what does 'passed' imply about the true value?")
def post(rho,pmarg,kmin=2,N=2000000):
    z=rng.standard_normal(N)
    e=rng.standard_normal((N,len(pmarg)))
    thr=stats.norm.ppf(1-np.array(pmarg))
    X=rho*z[:,None]+math.sqrt(1-rho**2)*e
    sel=(X>thr).sum(1)>=kmin
    return sel.mean(), z[sel].mean(), z[~sel].mean()
P(f"  {'rho':>5} {'P(pass)':>8} {'E[Z|pass]':>10} {'E[Z|fail]':>10} {'separation(sd)':>15}")
for rho in [0.0,0.1,0.2,0.3,0.5,0.7]:
    s,a,b=post(rho,p)
    P(f"  {rho:5.2f} {s:8.3f} {a:10.3f} {b:10.3f} {a-b:15.3f}")

P()
P("="*70); P("[9] cross-check: does the 段階2 ecosystem clear the 段階5/6.5.1 price gate?")
def need(goal_profit, price_m, margin=0.70, c=0.05, T=18,
         known=60, known_cr=0.10, cold_cr=0.005, h_per=0.25, budget=30.3):
    B=goal_profit/margin/price_m
    Mn=c*B/(1-math.exp(-c*T))
    from_known=min(known/T*known_cr, Mn)
    rest=max(Mn-from_known,0)
    people=known/T + rest/cold_cr
    return B, Mn, people, people*h_per, people*h_per<=budget
P(f"  {'goal':>10} {'price/mo':>9} {'contracts':>10} {'M/mo':>7} {'reach/mo':>10} {'h/mo':>8} {'fits 30.3h?':>11}")
for goal in [50000,200000,500000]:
    for price in [500,1000,2000,5000,15000,64000]:
        B_,Mn,pe,hr,ok=need(goal,price)
        P(f"  {goal:10,d} {price:9,d} {B_:10.1f} {Mn:7.2f} {pe:10.0f} {hr:8.1f} {'yes' if ok else 'NO':>11}")
    P("  ---")
# minimum price that fits, per goal
for goal in [50000,92445,200000,500000]:
    f=lambda pr: need(goal,pr)[3]-30.3
    lo,hi=100.0,2_000_000.0
    pr=optimize.brentq(f,lo,hi)
    P(f"  goal {goal:>7,d} yen/mo profit -> minimum viable price = {pr:8,.0f} yen/mo = "
      f"{pr*12:9,.0f} yen/yr = ${pr*12/150:7,.0f}/yr")
