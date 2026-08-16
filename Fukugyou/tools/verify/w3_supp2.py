import math
def M_const(c,B,T): return c*B/(1-math.exp(-c*T))
H=7*52/12
print("time feasibility grid: hours/month of 1:1 outreach required")
print("warm pool 60 people / 18 months at s=10%, remainder cold at s_cold, 0.25 h per contact")
print("budget = %.1f h/month\n"%H)
for G in (92_445,200_000,500_000):
    print(f"  goal {G:,} yen gross profit/month  (revenue {G/0.7:,.0f})")
    print(f"   {'price':>8}{'B':>8}{'M/mo':>8}", "".join(f"{f's_cold={x:.1%}':>14}" for x in (0.005,0.01,0.02)))
    for price in (4500,15000,50000,100000):
        B=G/0.7/price; M=M_const(0.05,B,18)
        cells=[]
        for sc in (0.005,0.01,0.02):
            rest=max(M-(60/18)*0.10,0); h=rest/sc*0.25
            cells.append(f"{h:8.1f}h {'OK' if h<=H else 'NG':>2}")
        print(f"   {price:>8,}{B:>8.1f}{M:>8.2f}", "".join(f"{c:>14}" for c in cells))
    print()
print("required reach if measured in AD IMPRESSIONS instead of 1:1 contacts (s=0.02%):")
for price in (4500,15000,50000):
    B=714285.7/price; M=M_const(0.05,B,18)
    print(f"   {price:>7,}: {M/0.0002:>12,.0f} impressions/month  vs {M/0.02:>8.0f} '1:1 people' -- same word in the table")
