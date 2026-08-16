import math
G=500_000; m=0.70; T=18; H=7*52/12; rev=G/m; tau=0.25; c=0.05
print("="*78)
print("[R] The doc's 4-row table is one number in disguise: the flow-channel ceiling")
print("="*78)
print("  flow-only steady state:  b_inf = (H/tau)*s / c   -- independent of price, of T, of the target")
for s in (0.002,0.005,0.01,0.02):
    print(f"    s_cold={s*100:4.2f}%: max reach {H/tau:6.1f}/mo -> b_inf = {(H/tau)*s/c:7.2f} contracts, EVER")
b_inf=(H/tau)*0.005/c
print(f"\n  doc's parameters -> b_inf = {b_inf:.2f} contracts.")
print(f"  Targets B: "+"  ".join(f"{P}->{rev/P:.1f}" for P in (4500,15000,50000,150000)))
print("  The four verdicts are just B vs 12.13:")
for P in (4500,15000,50000,150000):
    B=rev/P
    print(f"    {P:>7}: B={B:6.1f} {'>' if B>b_inf else '<='} 12.13 -> {'不可' if B>b_inf else '可'}   (doc's verdict matches)")
print(f"\n  Revenue ceiling of the doc's model, at ANY price: {b_inf:.2f} contracts.")
print(f"  It says nothing about 4,500 yen. It says: a solo founder doing only cold 1-to-1")
print(f"  outreach can sustain ~12 customers. Charge enough that 12 customers = your target,")
print(f"  i.e. P >= {rev/b_inf:,.0f} yen -- which is exactly the doc's 64,024 yen figure ({rev/b_inf:,.0f}).")

print("\n"+"="*78)
print("[S] Stock-channel ceiling: the decay rate replaces the price as the binding quantity")
print("="*78)
print("  asset stock: dA/dt = h/kappa - delta*A ;  reach = a*A ;  b_inf = a*A_inf*s/c")
print("  A_inf = (h/kappa)/delta  =>  b_inf = a*h*s / (kappa*delta*c)")
print("  Flow has NO delta term. That single missing parameter is the whole difference.\n")
kappa=5.0; a=20.0
print(f"  example: kappa={kappa}h/asset, a={a} reach/mo/asset, s=1%, all {H:.1f}h/mo into assets")
for delta in (0.20,0.10,0.05,0.03,0.01):
    b=a*(H/kappa)*0.01/(delta*c)
    print(f"    delta={delta*100:5.1f}%/mo (half-life {math.log(2)/delta:5.1f}mo): b_inf = {b:9.1f} contracts"
          + f"  -> supports price >= {rev/b:>9,.0f} yen" if b>0 else "")
print("""
  The correct 段階0 gate is therefore NOT '必要時間 = 必要到達 x 1接触の所要 <= 30.3h'.
  It is: 'does a channel exist whose reach persists after I stop paying hours for it,
  and can I measure its throughput before I build?' -- which is exactly what 6.5.3 says
  and 6.5.1 / 第4章の判定基準表 then contradict.
""")
print("="*78)
print("[T] Fairness check: constraints the doc OMITS that cut the other way")
print("="*78)
print(f"  budget H = {H:.1f} h/mo is assumed 100% available for acquisition.")
print("  Actually it must also cover build + support + admin. With support sigma h/customer/mo:")
for P in (4500,15000,50000,150000):
    B=rev/P
    print(f"    P={P:>7} B={B:6.1f}: support alone at 0.25h/cust = {B*0.25:6.1f} h/mo "
          f"({B*0.25/H*100:5.1f}% of the entire weekly budget)")
print("\n  Using the doc's OWN price-tier churn (ChartMogul, L534) instead of a flat 5%:")
for P,grr in ((4500,0.23),(15000,0.23),(50000,0.70),(150000,0.70)):
    cc=-math.log(grr)/12; B=rev/P
    print(f"    P={P:>7}: c={cc*100:5.2f}%/mo -> flow ceiling b_inf={(H/tau)*0.005/cc:6.2f}, need B={B:6.1f}"
          f" -> {'不可' if B>(H/tau)*0.005/cc else '可'}")
print("  Both of these make the LOW-price rows worse, not better. The doc's direction of")
print("  conclusion is not uniformly wrong; its magnitude (21x) and its causal attribution")
print("  (to price rather than to channel architecture) are.")
