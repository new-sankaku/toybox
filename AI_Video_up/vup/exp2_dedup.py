"""真の source frame での dedup 判定を掃引する。

比較相手は実装と同じく「最後に実際にSRしたframe」。
削減率と、使い回した frame の誤差(PSNR)、および
「動きを取りこぼしたか」を見るための局所指標(16x16 block の平均|d| の最大)を出す。
局所指標は、瞬きや口のような小さくて濃い変化を PSNR より鋭く捉える。
"""
import time

import cv2
import numpy as np

from exp2_lib import H, W, all_segments

MB = 16
MBH, MBW = H // MB, W // MB
PX3 = H * W * 3


def local_score(d):
    """16x16 block ごとの平均|d| の最大値。局所的で濃い変化に反応する。"""
    g = d.max(axis=2)
    return float(g.reshape(MBH, MB, MBW, MB).mean(axis=(1, 3)).max())


def crit_global(thr, ratio):
    lim = ratio * PX3

    def f(cur, ref):
        d = cv2.absdiff(cur, ref)
        nz = cv2.countNonZero(
            cv2.threshold(d.reshape(H, -1), thr, 255, cv2.THRESH_BINARY)[1])
        return nz <= lim, d
    return f


def crit_mbcount(k):
    """変化した16x16 macroblock が k 個以下なら同じ絵とみなす。
    完全一致判定なので h264 の encode noise の影響を受けない。"""
    def f(cur, ref):
        d = cv2.absdiff(cur, ref)
        m = d.max(axis=2).reshape(MBH, MB, MBW, MB).max(axis=(1, 3)) > 0
        return int(m.sum()) <= k, d
    return f


def crit_block(thr):
    """16x16 block の平均|d| の最大が thr 未満なら同じ絵とみなす。
    noise は面で薄く乗るので平均で潰れ、局所的な動きだけが残る。"""
    def f(cur, ref):
        d = cv2.absdiff(cur, ref)
        return local_score(d) < thr, d
    return f


def crit_down(shrink, thr):
    """INTER_AREA で 1/shrink に縮めてから max|d|。box 平均で noise を潰す。"""
    dw, dh = W // shrink, H // shrink
    def f(cur, ref):
        a = cv2.resize(cur, (dw, dh), interpolation=cv2.INTER_AREA)
        b = cv2.resize(ref, (dw, dh), interpolation=cv2.INTER_AREA)
        return int(cv2.absdiff(a, b).max()) < thr, cv2.absdiff(cur, ref)
    return f


CRITS = [("厳密一致", lambda c, r: (np.array_equal(c, r), cv2.absdiff(c, r)))]
CRITS += [(f"現行balanced |d|>4が0.15%未満", crit_global(4, 0.0015))]
CRITS += [(f"現行aggressive |d|>12が1.2%未満", crit_global(12, 0.012))]
CRITS += [(f"変化MB<={k}個", crit_mbcount(k)) for k in (1, 2, 4, 8, 16, 32)]
CRITS += [(f"block平均|d|max<{t}", crit_block(t)) for t in (1, 2, 3, 4, 6, 8)]
CRITS += [(f"1/{s}縮小 max|d|<{t}", crit_down(s, t))
          for s, t in ((4, 3), (4, 6), (4, 10), (8, 3), (8, 6), (8, 10))]


def main():
    segs = list(all_segments())
    rows = []
    for name, fn in CRITS:
        reused, scores, psnrs = 0, [], []
        total = 0
        t0 = time.perf_counter()
        for _, f, _, _ in segs:
            ref = None
            for i in range(len(f)):
                total += 1
                if ref is None:
                    ref = f[i]
                    continue
                same, d = fn(f[i], ref)
                if same:
                    reused += 1
                    scores.append(local_score(d))
                    mse = float(np.mean(d.astype(np.float32) ** 2))
                    psnrs.append(99.0 if mse == 0 else
                                 10 * np.log10(255.0 ** 2 / mse))
                else:
                    ref = f[i]
        el = (time.perf_counter() - t0) / total * 1000
        rate = reused / total
        rows.append((name, rate, 1 / max(1 - rate, 1e-9),
                     min(psnrs) if psnrs else 99.0,
                     max(scores) if scores else 0.0,
                     float(np.percentile(scores, 95)) if scores else 0.0,
                     el))
    print(f"{'判定基準':30s} {'使回率':>7s} {'SR削減':>7s} {'PSNR最小':>8s} "
          f"{'局所最悪':>8s} {'局所p95':>8s} {'判定ms':>7s}")
    for r in rows:
        print(f"{r[0]:30s} {r[1]*100:6.1f}% {r[2]:6.2f}倍 {r[3]:8.1f} "
              f"{r[4]:8.1f} {r[5]:8.1f} {r[6]:7.2f}")
    print("\n局所最悪 = 使い回した frame の 16x16 block 平均|d| の最大。")
    print("この値が大きいほど「動いているのに止めた」ことを意味する。")


if __name__ == "__main__":
    main()
