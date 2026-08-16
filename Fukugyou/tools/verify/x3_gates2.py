import numpy as np, itertools, math
from scipy import stats, optimize
rng=np.random.default_rng(20260812)
P=print
src=open("x3_gates.py",encoding="utf-8").read()
blk=src.split("WP = [")[1].split("]\n",1)[0]
exec("WP = ["+blk+"]")
WPm=np.array([[r[6],r[7],r[8],r[9]] for r in WP],float)
hits=np.array([r[1] for r in WP],float); inst=np.array([r[2] for r in WP],float)
mon=np.array([r[5] for r in WP],float)
M=WPm

def meanphi(A):
    v=[]
    for i,j in itertools.combinations(range(A.shape[1]),2):
        a=A[:,i]; b=A[:,j]
        n11=((a==1)&(b==1)).sum(); n10=((a==1)&(b==0)).sum()
        n01=((a==0)&(b==1)).sum(); n00=((a==0)&(b==0)).sum()
        d=(n11+n10)*(n01+n00)*(n11+n01)*(n10+n00)
        if d>0: v.append((n11*n00-n10*n01)/math.sqrt(d))
    return np.mean(v) if v else np.nan

obs=meanphi(M)
B=200000
null=np.empty(B)
cols=[M[:,i].copy() for i in range(4)]
for b in range(B):
    null[b]=meanphi(np.column_stack([rng.permutation(c) for c in cols]))
P(f"[3b] mean phi observed = {obs:+.4f}")
P(f"     permutation null: mean {null.mean():+.4f} sd {null.std():.4f}")
P(f"     one-sided p (phi <= observed) = {(null<=obs).mean():.4f}")
P(f"     null 90% range = [{np.percentile(null,5):+.3f}, {np.percentile(null,95):+.3f}]")
P(f"     -> a 1-factor model requires ALL pairwise phi >= 0; observed direction is the opposite")

# mechanical conflict between C1 (thin search) and C2 (a big incumbent exists)
r,pv=stats.spearmanr(hits,inst)
P(f"[3c] spearman(hit count, top8 median installs) over 22 keywords = {r:+.3f} (p={pv:.3f})")
P(f"     -> 'few results' and 'a large incumbent is present' are partly the same axis, opposite sign")

# pass rate as a function of how many fields the API happens to expose
P("[1b] P(>=2 of n) under independent conditions each firing at 0.2727:")
q=0.2727
for n in [2,3,4,5,6]:
    pr=sum(math.comb(n,k)*q**k*(1-q)**(n-k) for k in range(2,n+1))
    P(f"     n={n}: {pr:.3f}")
P("     measured: Chrome(2 cond) 0.10 / VSCode(3) 0.20 / Atlassian(3) 0.23 / WordPress(4) 0.36")

# what n restores the 9.5% bound under clustering?
def bb_p0(pi,rho,m,k):
    if rho<=1e-9: return (1-pi)**(m*k)
    a=pi*(1-rho)/rho; b=(1-pi)*(1-rho)/rho
    return math.exp(k*(math.lgamma(a+b)-math.lgamma(b)+math.lgamma(b+m)-math.lgamma(a+b+m)))
P("[7b] contacts needed to reach the same 9.5% one-sided bound, m=10 per cluster:")
for rho in [0.05,0.1,0.2,0.3]:
    k=1
    while bb_p0(0.095,rho,10,k)>0.05 and k<500: k+=1
    P(f"     ICC={rho:.2f}: {k} clusters x 10 = {k*10} contacts (independent case: 30)")
P("[7c] and with only ONE channel / one script / one week (k=1, m=n):")
for rho in [0.05,0.1,0.2,0.3]:
    f=lambda pi: bb_p0(pi,rho,30,1)-0.05
    P(f"     ICC={rho:.2f}, 30 contacts all from one cluster -> upper bound {optimize.brentq(f,1e-9,0.9999)*100:.1f}%")

# 12 interviews: same question for the 7/12 trigger gate
P("[10] 7-of-12 trigger gate, power under clustered interviews (same recruiting route)")
def bbpmf(n,pi,rho,rs,N=400000):
    if rho<=0:
        x=rs.binomial(n,pi,N)
    else:
        a=pi*(1-rho)/rho; b=(1-pi)*(1-rho)/rho
        x=rs.binomial(n,rs.beta(a,b,N))
    return x
for pi in [0.4,0.6]:
    row=[]
    for rho in [0.0,0.1,0.2,0.3]:
        x=bbpmf(12,pi,rho,rng); row.append((x>=7).mean())
    P(f"     true concentration {pi:.1f}: P(pass 7/12) by ICC 0/0.1/0.2/0.3 = "+" ".join(f"{v:.3f}" for v in row))
