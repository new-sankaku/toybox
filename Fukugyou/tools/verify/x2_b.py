import math
G=500_000; m=0.70; c=0.05; T=18; H=7*52/12
rev=G/m
def M_of(B,c=0.05,T=18): return c*B/(1-math.exp(-c*T))

print("="*70)
print("[B] Elasticity structure: is the ranking informative?")
print("="*70)
# R = (G/(m P)) * c / (s (1-e^{-cT}))
def R(G=G,m=m,P=15000,s=0.02,c=c,T=T):
    return (G/(m*P))*c/(s*(1-math.exp(-c*T)))
base=R()
print("base R =",base)
def elast(f,x,**kw):
    h=1e-6
    a=f(**{**kw,x:kw[x]*(1-h)}); b=f(**{**kw,x:kw[x]*(1+h)})
    return (math.log(b)-math.log(a))/(math.log(kw[x]*(1+h))-math.log(kw[x]*(1-h)))
kw=dict(G=G,m=m,P=15000,s=0.02,c=c,T=T)
for v in ("G","m","P","s","c","T"):
    print(f"  d lnR/d ln{v} = {elast(R,v,**kw):+.6f}")
x=c*T*math.exp(-c*T)/(1-math.exp(-c*T))
print(f"\n  analytic: eps_T = -x = {-x:.6f} ; eps_c = 1-x = {1-x:.6f}")
print(f"  identity check eps_c - eps_T = {(1-x)-(-x):.6f}  (exactly 1, always)")
print("  => the whole 'sensitivity analysis' has ONE free number x=cT e^-cT/(1-e^-cT).")
print("     4 of the 6 elasticities are +-1 by the algebraic form (pure product/quotient).")

print("\n  x as function of cT:")
for cT in (0.1,0.3,0.6,0.9,1.2,2.0,3.0,5.0):
    xx=cT*math.exp(-cT)/(1-math.exp(-cT))
    print(f"    cT={cT:4.1f}  eps_T={-xx:+.3f}  eps_c={1-xx:+.3f}")

print("\n  elasticity x plausible log-range (the quantity that actually ranks levers):")
# plausible multiplicative ranges
ranges={"s (channel choice 0.02%-15%)":750,"P (4500-150000)":33.3,"m (0.3-0.9)":3.0,
        "G (5万-100万)":20.0,"c (2%-12%)":6.0,"T (12-36mo)":3.0}
els={"s (channel choice 0.02%-15%)":1.0,"P (4500-150000)":1.0,"m (0.3-0.9)":1.0,
     "G (5万-100万)":1.0,"c (2%-12%)":1-x,"T (12-36mo)":x}
for k in ranges:
    print(f"    {k:<32} |eps|={els[k]:.3f}  range={ranges[k]:7.1f}x  -> R moves {ranges[k]**els[k]:9.1f}x")
