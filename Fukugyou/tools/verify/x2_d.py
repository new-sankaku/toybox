import math
G=500_000; m=0.70; c=0.05; T=18; H=7*52/12; rev=G/m
def M_of(B,c=0.05,T=18): return c*B/(1-math.exp(-c*T))

print("="*76)
print("[D] Flow channel vs stock channel: the structural break")
print("="*76)
print("""
FLOW (1-to-1 contact): reach R = h/tau. Hours buy reach ONCE. Cap = H/tau, constant forever.
STOCK (article / marketplace listing / integration): h_a hours build ONE asset that emits
      a0 reach per month thereafter, decaying at delta. Reach accumulates.
      Investing at x = h_x/h_a assets per month gives
          R_s(t) = (x*a0/delta) * (1 - e^{-delta t})
      and cumulative reach over [0,T] is  (x*a0/delta)*(T - (1-e^{-delta T})/delta).
""")
tau=0.25
print(f"FLOW cap with all {H:.1f} h/month: {H/tau:.0f} contacts/month, FOREVER FLAT.")
print(f"  cumulative reach over 18 months = {H/tau*T:,.0f}\n")

def stock_reach(t,x,a0,delta):
    return (x*a0/delta)*(1-math.exp(-delta*t))
def stock_cum(T,x,a0,delta):
    return (x*a0/delta)*(T-(1-math.exp(-delta*T))/delta)

print("STOCK, all hours into assets. h_a = hours per asset, a0 = reach/month per asset, delta = monthly decay")
for h_a,a0,delta,label in [(5,20,0.03,"blog/Qiita article (modest)"),
                           (5,20,0.10,"article, fast decay"),
                           (40,300,0.02,"one marketplace listing (WP/VSCode)"),
                           (40,1000,0.02,"marketplace listing, mid rank"),
                           (20,50,0.05,"integration/directory listing")]:
    x=H/h_a
    print(f"  {label:<36} x={x:5.2f}/mo  R(6)={stock_reach(6,x,a0,delta):9.0f} "
          f"R(18)={stock_reach(18,x,a0,delta):9.0f}  cum18={stock_cum(18,x,a0,delta):11,.0f}")
print("\n  A single WordPress listing is a one-off 40h build; its reach is not bought with hours at all.")

print("\n[D-2] Contracts reached in 18 months, per channel type (visit->paid s=0.5%, 1%, 2%)")
def contracts_from_reach_path(reach_fn, s, c=0.05, T=18, n=20000):
    # db/dt = reach(t)*s - c b
    dt=T/n; b=0.0
    for i in range(n):
        t=i*dt
        b += (reach_fn(t)*s - c*b)*dt
    return b
for s in (0.005,0.01,0.02):
    flow=lambda t: H/tau
    print(f"  s={s*100:4.2f}%  flow(cold,121/mo): b(18)={contracts_from_reach_path(flow,s):7.2f}")
    for h_a,a0,delta,label in [(5,20,0.03,"articles"),(40,1000,0.02,"marketplace")]:
        x=H/h_a
        f=lambda t,x=x,a0=a0,delta=delta: stock_reach(t,x,a0,delta)
        print(f"           {label:<12} b(18)={contracts_from_reach_path(f,s):7.2f}")
print(f"\n  Targets B: 4500->{rev/4500:.0f}  15000->{rev/15000:.0f}  50000->{rev/50000:.0f}  150000->{rev/150000:.0f}")
