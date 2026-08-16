import math
# ---- A. base table reproduction (incl. 150,000 row) ----
G=500_000; m=0.70; c=0.05; T=18
rev=G/m
print("required monthly revenue:", rev)
def M_of(B,c=0.05,T=18): return c*B/(1-math.exp(-c*T))
rows=[4500,15000,50000,150000]
print("\n[A-1] doc table rows (floor vs round vs raw)")
for P in rows:
    Braw=rev/P
    for lbl,B in (("raw",Braw),("floor",math.floor(Braw)),("round",round(Braw))):
        M=M_of(B)
        print(f"  P={P:>7} {lbl:<5} B={B:8.3f} M={M:7.4f}")
    print()

# doc's warm/cold split: warm pool 60 over 18mo at s=10%; cold s=0.5%, tau=0.25h
print("[A-2] warm/cold time computation, reproduce doc table")
warm_pool=60; warm_s=0.10; cold_s=0.005; tau=0.25; H=7*52/12
print("H (monthly disposable) =", H)
warm_R=warm_pool/T; warm_M=warm_R*warm_s
print("warm reach/mo", warm_R, "warm contracts/mo", warm_M)
for P in rows:
    for lbl,B in (("floor",math.floor(rev/P)),("round",round(rev/P)),("raw",rev/P)):
        M=M_of(B); need=M-warm_M
        cold_R=need/cold_s; hours=cold_R*tau
        print(f"  P={P:>7} {lbl:<5} B={B:8.3f} M={M:6.3f} cold_reach={cold_R:9.1f} hours={hours:8.2f} ratio={hours/H:6.2f}")
    print()
