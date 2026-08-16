import math
G=500_000; m=0.70; T=18; H=7*52/12; rev=G/m
print("="*78)
print("[O] Live WordPress API (2026-08-12) vs the doc's 'impossible' rows")
print("="*78)
obs=[("woocommerce-pdf-invoices-packing-slips",300000,23402712),
     ("print-invoices-packing-slip-labels",50000,2593944),
     ("woocommerce-delivery-notes",30000,1420349),
     ("flexible-invoices",6000,408736),
     ("sliced-invoices",5000,257320),
     ("easy-invoice",600,21233)]
print(f"{'plugin':<40}{'installs':>9}{'downloads':>11} | free->paid % needed for B at each price")
print(" "*60+"  4,500   15,000   50,000")
for name,inst,dl in obs:
    need=[rev/P/inst*100 for P in (4500,15000,50000)]
    print(f"{name:<40}{inst:>9}{dl:>11} | "+"".join(f"{n:>8.2f}%" for n in need))
print("""
  Reading: a plugin with 5,000-6,000 active installs -- the 4th/5th result for one ordinary
  business keyword, not a hit -- reaches the 4,500-yen row's 159-contract target at a
  2.6-3.2% free->paid rate. The 15,000-yen row needs 0.8%. Zero 1-to-1 contacts.
  The doc's model says the 4,500-yen row needs 2,608 human contacts EVERY MONTH.
""")
print("="*78)
print("[P] Required hours under the doc's model vs the same target via the listing")
print("="*78)
for P in (4500,15000,50000):
    B=rev/P
    print(f"  P={P:>6} B={B:6.1f}: doc says {(B and 0) or ''}", end="")
    print(f" flow-only {'652' if P==4500 else '184' if P==15000 else '44'} h/mo ;"
          f" listing route = build once + upkeep, ~6 h/mo, and the reach is ALREADY OBSERVED"
          f" ({'5,000-6,000 installs' if P==4500 else 'less'} needed)")
print("""
  This is not a claim that a listing is easy. It is the claim that hours and reach are
  NOT proportional in the channel the doc itself ranks '最高' (6.5.3), and the 6.5.1 table
  assumes they are proportional in every row.
""")
print("="*78)
print("[Q] Dimensional check of '必要到達人数 = 必要月次獲得 ÷ 成約率'")
print("="*78)
print("""
  R [people/month] = M [contracts/month] / s [contracts per person reached]  -- consistent.
  The error is not in the equation. It is that R is then converted to hours by R*tau with a
  single tau, i.e. the model silently asserts

      hours = M * (tau / s)

  and treats (tau/s) as a channel-independent constant. tau/s is 'hours of the founder's own
  time per contract won'. For a listing tau ~ 0 per reach, so tau/s -> the build cost divided
  over all contracts, which FALLS as volume rises. For 1-to-1 it is constant. These are
  different functional forms, not different constants. No choice of s repairs it.
""")
