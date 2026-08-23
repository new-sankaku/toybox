"""box 平均判定の詰め。block size と閾値を細かく振る。

判定は cv2.absdiff -> INTER_AREA で 1/blk へ縮小 -> max。
INTER_AREA は倍率が整数分の1のとき box 平均そのものなので、
「blk x blk の平均|d| の最大」を 0.5ms 弱で得られる。
"""
import time

import cv2
import numpy as np

from exp2_lib import H, W, all_segments


def run(blk, thr, segs, drop_top=0):
    dw, dh = W // blk, H // blk
    reused = total = 0
    miss, psnrs = [], []
    t_judge = 0.0
    for _, f, _, _ in segs:
        ref = None
        for i in range(len(f)):
            total += 1
            if ref is None:
                ref = f[i]
                continue
            t0 = time.perf_counter()
            d = cv2.absdiff(f[i], ref)
            s = cv2.resize(d, (dw, dh), interpolation=cv2.INTER_AREA)
            if drop_top:
                v = np.partition(s.reshape(-1), -1 - drop_top)[-1 - drop_top]
                same = int(v) < thr
            else:
                same = int(s.max()) < thr
            t_judge += time.perf_counter() - t0
            if same:
                reused += 1
                miss.append(cv2.countNonZero(
                    cv2.threshold(d.reshape(H, -1), 48, 255,
                                  cv2.THRESH_BINARY)[1]))
                mse = float(np.mean(d.astype(np.float32) ** 2))
                psnrs.append(99.0 if mse == 0 else
                             10 * np.log10(255.0 ** 2 / mse))
            else:
                ref = f[i]
    rate = reused / total
    miss = np.asarray(miss) if miss else np.zeros(1)
    return (1 / max(1 - rate, 1e-9), int(miss.max()), int(miss.sum()),
            min(psnrs) if psnrs else 99.0, t_judge / total * 1000)


def main():
    segs = list(all_segments())
    print(f"{'判定基準':26s} {'SR削減':>7s} {'欠落最大':>8s} {'欠落合計':>9s} "
          f"{'PSNR最小':>8s} {'判定ms':>7s}")
    out = []
    for blk in (4, 8, 16):
        for thr in (4, 6, 8, 10, 12, 14, 16, 20, 24):
            r = run(blk, thr, segs)
            out.append((f"box{blk} max<{thr}",) + r)
    for thr in (8, 12, 16, 20):
        r = run(8, thr, segs, drop_top=1)
        out.append((f"box8 max<{thr} (最大1個無視)",) + r)
    out.sort(key=lambda r: r[1])
    for r in out:
        print(f"{r[0]:26s} {r[1]:6.2f}倍 {r[2]:8d} {r[3]:9d} {r[4]:8.1f} {r[5]:7.2f}")


if __name__ == "__main__":
    main()
