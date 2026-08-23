"""smooth.py の位置ずれ計算を、答えの判っている変位で検算する。

図形(黒地に矩形)では検算にならない。texture が無いと Farneback は輪郭でしか
flow を立てられず、実測が理論の 0.4倍〜2倍まで振れる(d8 の初版で確認)。
実際の絵を既知の画素数だけ平行移動させて測る。

見るのは2点:
  1. span の絶対値が、実際にずらした画素数と合うか(集約の percentile の妥当性)
  2. lag が「あるべき位置からのずれ」= r * span になるか(位置ずれの式そのもの)
"""
import sys

import numpy as np

import lib
import smooth

SHIFTS = (4, 8, 16, 32, 64)      # 原寸の px
PCTS = (90, 95, 99, 99.9)


def shifted(g, px):
    """縮小側(480x270)で px/SCALE だけ横へずらす。端は使わない。"""
    d = int(round(px / smooth.SCALE))
    return np.roll(g, d, axis=1), d


def main(clip="C_act"):
    g = smooth.scan(clip)["grays"]
    idx = [len(g) // 4, len(g) // 2, 3 * len(g) // 4]
    print(f"{clip}: 実際の絵を横へずらして測る(端 32px は除外)")
    print("  ずらし量 | " + " | ".join(f"p{p}" for p in PCTS))
    for px in SHIFTS:
        cols = []
        for p in PCTS:
            vals = []
            for i in idx:
                a = g[i]
                b, d = shifted(a, px)
                f = smooth._flow(a[:, 32:-32], b[:, 32:-32])
                m = np.sqrt(f[..., 0] ** 2 + f[..., 1] ** 2)
                vals.append(float(np.percentile(m, p)) * smooth.SCALE)
            cols.append(np.median(vals))
        print(f"  {px:6d}px | " + " | ".join(f"{c:6.1f}" for c in cols))

    # 位置ずれの式。r の位置にある絵を作って、lag が 0 になることを見る
    px = 32
    a = g[len(g) // 2][:, 32:-32]
    b = np.roll(g[len(g) // 2], int(round(px / smooth.SCALE)), axis=1)[:, 32:-32]
    gap = smooth._flow(a, b)
    span = smooth._mag_p95(gap)
    print(f"\n  区間の変位 {span:.1f}px (ずらし量 {px}px)")
    ok, floor = True, []
    for r in (0.25, 0.5, 0.75):
        mid = np.roll(g[len(g) // 2],
                      int(round(px * r / smooth.SCALE)), axis=1)[:, 32:-32]
        hold = smooth._lag_one(a, None, gap, r)
        at_r = smooth._lag_one(a, mid, gap, r)
        print(f"  r={r}: 保持 {hold:6.1f}px (理論 {r * span:6.1f}px) / "
              f"正しい位置 {at_r:5.2f}px (理論 0)")
        ok &= abs(hold - r * span) < 0.05 * span and at_r < 0.25 * span
        floor.append(at_r / span)
    print(f"  雑音の下限: 区間の変位の {max(floor) * 100:.0f}%"
          f"(正しい位置に置いても、これ以下には下がらない)")
    lib.record("selftest", dict(clip=clip, span_px=round(span, 1),
                                floor_rel=round(float(max(floor)), 3), ok=bool(ok)))
    print("検算:", "合格" if ok else "不合格")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main(*(sys.argv[1:] or []))
