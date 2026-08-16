import numpy as np, math
P=print
# expected hours to reach ONE workable candidate, with vs without the 段階2 gate.
# 段階0+1 = 4.8+8.8 = 13.6h per fresh candidate ; 段階2 gate = 3.6h ; downstream 段階3-5 = 79.5h
CGEN, CG, CD = 13.6, 3.6, 79.5
def hours(pi, s, LR, gate=True):
    if not gate: return (CGEN+CD)/pi
    f = s/LR
    if f>1: return math.inf
    q = pi*s+(1-pi)*f
    return (CGEN+CG+q*CD)/(pi*s)
P("expected hours to reach one workable candidate (pi = prior that a 段階1 candidate is workable)")
P(f"{'pi':>5} {'no gate':>9} | " + " | ".join(f"LR={lr:<4}" for lr in [1.0,1.6,3.0,8.0]))
for pi in [0.1,0.2,0.3,0.5]:
    row=[]
    for LR in [1.0,1.6,3.0,8.0]:
        best=min(((hours(pi,s,LR),s,pi*s+(1-pi)*s/LR) for s in np.linspace(0.02,1.0,99) if s/LR<=1),
                 key=lambda t:t[0])
        row.append(f"{best[0]:7.0f}h(q={best[2]:.2f})")
    P(f"{pi:5.2f} {(CGEN+CD)/pi:8.0f}h | " + " | ".join(row))
P()
P("gate held at the measured operating point q=0.36 (2-of-4):")
P(f"{'pi':>5} {'LR':>5} {'s':>6} {'f':>6} {'hours':>8} {'vs no gate':>11}")
for pi in [0.2]:
    for LR in [1.0,1.3,1.6,2.0,3.0,5.0]:
        # solve q=0.36 -> pi*s+(1-pi)*s/LR = 0.36
        s = 0.36/(pi+(1-pi)/LR); f=s/LR
        if s>1: P(f"{pi:5.2f} {LR:5.1f}   s>1 (unattainable at q=0.36)"); continue
        h=(CGEN+CG+0.36*CD)/(pi*s)
        P(f"{pi:5.2f} {LR:5.1f} {s:6.3f} {f:6.3f} {h:8.0f}h {h/((CGEN+CD)/pi):10.2f}x")
P()
P("break-even LR at q=0.36 (gate worth running at all):")
for pi in [0.1,0.2,0.3,0.5]:
    lo,hi=1.0,50.0
    for _ in range(200):
        mid=(lo+hi)/2
        s=0.36/(pi+(1-pi)/mid)
        h=(CGEN+CG+0.36*CD)/(pi*min(s,1.0)) if s<=1 else 0
        if s>1 or h<(CGEN+CD)/pi: hi=mid
        else: lo=mid
    P(f"  pi={pi:.2f}: LR must exceed {(lo+hi)/2:.2f}")
