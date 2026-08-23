"""box4<20 の cache 深さを全長で振る。

先の報告で cache4 の削減率を別条件(閾値16)の値で書いてしまったので、
閾値20 で揃えて測り直す。GPU は使わない。
"""
import sys

import numpy as np

import exp2_final as F


def main():
    pts = F.read_pts()
    counts, _ = F.counts_for(pts, 30000, 1001)
    crits = [F.Crit(f"box4<20 cache{k}", "box", 20, cache_k=k)
             for k in (1, 2, 4, 8, 16)]
    used = F.run_stream(pts, counts, crits, float(sys.argv[1]) if len(sys.argv) > 1 else 0.0)
    print(f"\n出力に使う source frame {used}")
    print(f"{'構成':20s} {'SR回数':>7s} {'削減':>7s} {'欠落合計':>9s} "
          f"{'欠落最大':>8s} {'>100の frame':>12s}")
    for c in crits:
        print(f"{c.name:20s} {c.calls:7d} {used / c.calls:6.2f}倍 "
              f"{c.miss_total:9d} {c.miss_max:8d} {c.miss_frames:12d}")


if __name__ == "__main__":
    main()
