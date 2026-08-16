import numpy as np
from scipy import stats

rng = np.random.default_rng(20260811)
out = []
def P(*a):
    s = " ".join(str(x) for x in a)
    print(s); out.append(s)

P("="*70)
P("[1] power law: category mean is NOT stable when alpha<=2")
P("="*70)
# Pareto(alpha, xm=1). mean = alpha/(alpha-1) for alpha>1. var infinite for alpha<=2.
N_per_cat = 35995 // 5   # 7199
for alpha in [1.5, 2.0, 2.5, 3.0, 5.0]:
    means = []
    for _ in range(2000):
        x = (rng.pareto(alpha, N_per_cat) + 1.0)   # Pareto Type I, xm=1
        means.append(x.mean())
    means = np.array(means)
    theo = alpha/(alpha-1)
    P(f"alpha={alpha:>4}  theoretical mean={theo:6.3f}  "
      f"sample-mean over {N_per_cat} draws: median={np.median(means):8.3f} "
      f"CV={means.std()/means.mean():7.4f}  p05={np.percentile(means,5):7.3f} p95={np.percentile(means,95):9.3f} "
      f"max/min={means.max()/means.min():8.2f}")

P("")
P("-- 5 categories drawn from the SAME Pareto: observed between-category max/min of the mean")
for alpha in [1.5, 2.0, 2.5, 3.0]:
    ratios = []
    for _ in range(3000):
        ms = [(rng.pareto(alpha, N_per_cat)+1.0).mean() for _ in range(5)]
        ratios.append(max(ms)/min(ms))
    ratios = np.array(ratios)
    P(f"alpha={alpha:>4}: between-cat mean ratio  median={np.median(ratios):6.3f}  p95={np.percentile(ratios,95):8.3f}  max={ratios.max():9.2f}")

P("")
P("-- same for log-normal (sigma=2) and for a light tail (exponential), for comparison")
for name, gen in [("lognormal s=2", lambda n: rng.lognormal(0,2,n)),
                  ("exponential",   lambda n: rng.exponential(1,n))]:
    ratios = [max(g)/min(g) for g in ([[gen(N_per_cat).mean() for _ in range(5)] for _ in range(2000)])]
    ratios = np.array(ratios)
    P(f"{name:>14}: between-cat mean ratio median={np.median(ratios):6.3f} p95={np.percentile(ratios,95):6.3f}")

P("")
P("-- scale parameter: same alpha, different xm -> means differ EXACTLY by the xm ratio")
alpha = 2.5
for xm in [1.0, 3.0, 10.0]:
    x = (rng.pareto(alpha, 200000)+1.0)*xm
    P(f"  alpha={alpha} xm={xm:5.1f}  sample mean={x.mean():8.3f}  (theory {xm*alpha/(alpha-1):8.3f})")

P("")
P("="*70)
P("[2] variance decomposition from 5.6x vs 400x")
P("="*70)
# between: 4 category values, log-range ln(5.6); d2(n=4)=2.059
lr_b = np.log(5.6)
sd_b = lr_b/2.059
# within: p95 vs p25 ratio 400 -> z gap
zg = stats.norm.ppf(0.95) - stats.norm.ppf(0.25)
sd_w = np.log(400)/zg
eta2 = sd_b**2/(sd_b**2+sd_w**2)
P(f"log-scale SD between categories ~ {sd_b:.3f}   (range {lr_b:.3f} / d2=2.059, n=4)")
P(f"log-scale SD within category    ~ {sd_w:.3f}   (ln400={np.log(400):.3f} / dz={zg:.3f})")
P(f"=> eta^2 (share of variance explained by category) = {eta2*100:.1f}%")
P("   Cohen: eta^2 0.01 small / 0.06 medium / 0.14 large")
# sensitivity
for dz_lo, dz_hi, lbl in [(stats.norm.ppf(0.95)-stats.norm.ppf(0.25),0,'p95/p25'),
                          (stats.norm.ppf(0.975)-stats.norm.ppf(0.25),0,'p97.5/p25')]:
    s_w = np.log(400)/dz_lo
    P(f"   sensitivity ({lbl}): sd_w={s_w:.3f} -> eta^2={sd_b**2/(sd_b**2+s_w**2)*100:.1f}%")
P("")
P("decision value of 5.6x: reaching $10k/mo  Gaming 8.9% vs Business 1.6%")
P(f"  odds ratio = {(0.089/0.911)/(0.016/0.984):.2f}")
P(f"  expected value of the choice, if payoff is binary: 8.9%/1.6% = {0.089/0.016:.2f}x")
P(f"  n needed to distinguish 8.9% vs 1.6% (alpha .05, power .8) per arm:")
z=stats.norm.ppf(0.975)+stats.norm.ppf(0.8)
p1,p2=0.016,0.089
P(f"    n = {z**2*(p1*(1-p1)+p2*(1-p2))/(p2-p1)**2:.0f}  -> it is an easily detectable, not a null, difference")

P("")
P("="*70)
P("[3] sequential independent-source filters")
P("="*70)
def joint_fpr(rho, k, alpha=0.05):
    # k correlated standard-normal scores, exchangeable correlation rho, all exceed 1-alpha quantile
    thr = stats.norm.ppf(1-alpha)
    n=400000
    z = rng.standard_normal((n,k))
    common = rng.standard_normal((n,1))
    x = np.sqrt(rho)*common + np.sqrt(1-rho)*z
    return (x>thr).all(axis=1).mean()
for k in [2,3,5]:
    row=[f"k={k}: independent(product)={0.05**k:.6f}"]
    for rho in [0.0,0.3,0.5,0.8,0.95]:
        row.append(f"rho={rho}: {joint_fpr(rho,k):.6f}")
    P("  " + " | ".join(row))
P("")
P("  -> with rho=0.5 and k=5 the FPR is inflated by a factor of "
  f"{joint_fpr(0.5,5)/0.05**5:.0f} vs the independence assumption")
P("")
P("  overall sensitivity of an AND-funnel (each stage power 0.8):")
for k in [2,3,5]:
    P(f"    k={k}: {0.8**k:.3f}")

P("")
P("  winner's curse framing (not FWER): shrinkage = noise_var/(noise_var+signal_var)")
for sig in [0.4, 1.0, 1.5, 2.0]:
    noise = np.log(1.5)   # +-50% tool error on log scale
    P(f"    signal SD(log)={sig:4.2f}, noise SD(log)={noise:.3f}  -> shrinkage={noise**2/(noise**2+sig**2)*100:5.1f}% "
      f"; corr(observed,true)={sig/np.sqrt(sig**2+noise**2):.3f}")

P("")
P("="*70)
P("[4] Phase 3 stopping rules")
P("="*70)
P("interim gate: continue only if X>=3 of 6  (stop if <=2)")
for p in [0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8]:
    P(f"  p={p:.1f}: P(stop at 6) = P(X<=2) = {stats.binom.cdf(2,6,p):.4f}   P(continue)={1-stats.binom.cdf(2,6,p):.4f}")
P("")
P("final gate: X>=8 of 12 share the same trigger")
for p in [0.3,0.4,0.5,0.6,0.7,0.8,0.9]:
    P(f"  p={p:.1f}: P(X>=8|n=12) = {1-stats.binom.cdf(7,12,p):.4f}")
P("")
P("joint (same underlying p, interim on first 6, final on all 12) -- exact:")
for p in [0.3,0.4,0.5,0.6,0.7,0.8,0.9]:
    tot=0.0
    for a in range(3,7):          # first 6: at least 3
        for b in range(0,7):      # next 6
            if a+b>=8:
                tot += stats.binom.pmf(a,6,p)*stats.binom.pmf(b,6,p)
    P(f"  p={p:.1f}: P(pass both) = {tot:.4f}   (false-negative rate = {1-tot:.4f})")
P("")
P("multiplicity inside 'same trigger': max count over k trigger labels, n=12, uniform null")
for k in [2,3,4,5,6]:
    sim = rng.multinomial(12, [1/k]*k, size=400000)
    P(f"  k={k} labels: P(some label >=8) = {(sim.max(axis=1)>=8).mean():.4f}"
      f"   P(some label >=6) = {(sim.max(axis=1)>=6).mean():.4f}")

P("")
P("="*70)
P("[5] A/B test 2% -> 3%")
P("="*70)
p1,p2=0.02,0.03
za,zb=stats.norm.ppf(0.975),stats.norm.ppf(0.80)
n_simple=(za+zb)**2*(p1*(1-p1)+p2*(1-p2))/(p2-p1)**2
pbar=(p1+p2)/2
n_pooled=(za*np.sqrt(2*pbar*(1-pbar))+zb*np.sqrt(p1*(1-p1)+p2*(1-p2)))**2/(p2-p1)**2
P(f"  simple form : n per arm = {n_simple:.0f}   total = {2*n_simple:.0f}")
P(f"  pooled form : n per arm = {n_pooled:.0f}   total = {2*n_pooled:.0f}")
# verify by simulation
n=int(np.ceil(n_pooled))
a=rng.binomial(n,p1,20000); b=rng.binomial(n,p2,20000)
ph=(a+b)/(2*n); se=np.sqrt(ph*(1-ph)*2/n)
z=(b/n-a/n)/se
P(f"  simulated power at n={n}/arm: {(np.abs(z)>1.96).mean():.3f}")
# how long at personal traffic
for v in [200,500,1000,3000]:
    P(f"    at {v:>5} visits/month -> {2*n_pooled/v:6.1f} months to fill both arms")
P("")
P("  what can n=1..few say?  Clopper-Pearson 95% CI")
for k,n_ in [(0,30),(1,30),(1,12),(2,12),(3,30),(0,300)]:
    lo = stats.beta.ppf(0.025,k,n_-k+1) if k>0 else 0.0
    hi = stats.beta.ppf(0.975,k+1,n_-k) if k<n_ else 1.0
    P(f"    {k}/{n_:>3}: [{lo*100:6.3f}%, {hi*100:6.2f}%]  (rule of three 3/n = {3/n_*100:.2f}%)")

P("")
P("="*70)
P("[6] D-5 benchmark")
P("="*70)
for grr,lbl in [(0.23,'<$50'),(0.45,'$50-249'),(0.70,'>$250')]:
    P(f"  annual GRR {grr:.0%} ({lbl}) -> implied monthly logo churn = {(1-grr**(1/12))*100:5.2f}%/mo")
P(f"  manual 2.3 quotes 3%/mo median -> annual retention = {0.97**12:.3f} = {0.97**12:.1%}")
P("  the two figures quoted side by side in the manual differ by a factor of "
  f"{(1-0.23**(1/12))/0.03:.1f} in monthly churn")

open("v5_out.txt","w",encoding="utf-8").write("\n".join(out))
