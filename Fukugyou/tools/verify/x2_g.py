import math
G=500_000; T=18; H=7*52/12
print("="*78)
print("[M] Partial elasticities are mis-specified because the variables are correlated")
print("="*78)
# c as a function of P, from the doc's OWN ChartMogul price-tier table (L534)
c30 =-math.log(0.23)/12   # <$50/mo tier
c1000=-math.log(0.70)/12  # >$250/mo tier
P30,P1000=4500,150000
dlnc_dlnP=math.log(c1000/c30)/math.log(P1000/P30)
print(f"  c($30 tier)  = {c30*100:.2f}%/mo")
print(f"  c($1000 tier)= {c1000*100:.2f}%/mo")
print(f"  => d ln c / d ln P = {dlnc_dlnP:+.3f}   (from the doc's own cited table)")
cmid=0.05; x=cmid*T*math.exp(-cmid*T)/(1-math.exp(-cmid*T)); eps_c=1-x
print(f"  eps_c (partial) = {eps_c:+.3f}")
print(f"  TOTAL d lnR/d lnP = -1 + eps_c*(dlnc/dlnP) = {-1+eps_c*dlnc_dlnP:+.3f}   (churn channel only)")
print()
print("  Now add the conversion channel s(P): d ln s/d ln P = -eps_s")
for eps_s in (0.0,0.3,0.6,1.0,1.5):
    tot=-1 + eps_c*dlnc_dlnP + eps_s   # dlnR/dlnP = -1 - dlns/dlnP + eps_c dlnc/dlnP ; dlns/dlnP=-eps_s
    print(f"    eps_s={eps_s:4.1f} -> TOTAL d lnR/d lnP = {tot:+.3f} "
          + ("(price still helps)" if tot<0 else "(price HURTS: raising price raises required reach)"))
print("""
  The doc reports d lnR/d lnP = -1.000 'exactly'. That is the partial derivative holding
  c and s fixed. Its own sources say c and s both move with P. The exact -1.000 is a
  property of the algebra, not of the world; the total derivative is not -1 and its sign
  is not even determined by the data the doc has.
""")
print("="*78)
print("[N] What the elasticity table would look like if it ranked by ACTIONABILITY")
print("="*78)
print("  A lever's worth = |elasticity| x (log-range the founder can actually move it)")
print("  x (hours it costs to move it) -- none of which the doc's ranking contains.")
rows=[("channel architecture (flow->stock)","not in the model at all","57x contracts for the same 30.3h (E/K)"),
      ("target G (50万->9.2万)","1.000 x ln(5.4)","the doc offers it only in 6.5.1.1, after the verdict"),
      ("price P (4500->150000)","1.000 x ln(33) BUT total deriv unknown","couples to s and c"),
      ("profit margin m (0.7->0.5)","1.000 x ln(1.4)","fixed by rail choice, near-costless to compute"),
      ("horizon T (18->36)","0.617 x ln(2)","free"),
      ("churn c (5%->3%)","0.383 x ln(1.7)","hardest to move, weakest effect")]
for a,b,cc in rows: print(f"   {a:<38} {b:<38} {cc}")
