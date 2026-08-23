"""素材の性質を測る。

  1. 黒帯/固定境界 — SRしなくてよい領域が画面端にあるか
  2. 真の source frame での完全一致率 — dedup の下限
  3. packet size と画素差の関係 — bitstream 情報が判定に使えるか
  4. 平坦領域の割合 — anime 特有の構造が使えるか
"""
import numpy as np

from exp2_lib import H, W, all_segments


def main():
    segs = list(all_segments())

    print("=== 1. 画面端の固定領域 ===")
    mn = np.full((H, W, 3), 255, np.uint8)
    mx = np.zeros((H, W, 3), np.uint8)
    for _, f, _, _ in segs:
        np.minimum(mn, f.min(axis=0), out=mn)
        np.maximum(mx, f.max(axis=0), out=mx)
    span = (mx.astype(np.int16) - mn).max(axis=2)
    rows = span.max(axis=1)
    cols = span.max(axis=0)
    def edge(v, lim=4):
        a = 0
        while a < len(v) and v[a] <= lim:
            a += 1
        b = len(v)
        while b > a and v[b - 1] <= lim:
            b -= 1
        return a, len(v) - b
    t, b = edge(rows)
    l, r = edge(cols)
    print(f"  全frameを通して変化しない帯: 上{t}px 下{b}px 左{l}px 右{r}px")
    keep = (H - t - b) * (W - l - r)
    print(f"  内側だけSRすると {keep / (H * W) * 100:.1f}% の面積 "
          f"(削減 {H * W / max(keep, 1):.3f}倍)")

    print("\n=== 2. 真の source frame の完全一致 ===")
    tot = same = 0
    for tag, f, _, _ in segs:
        n = len(f)
        eq = np.array([np.array_equal(f[i], f[i - 1]) for i in range(1, n)])
        tot += n - 1
        same += int(eq.sum())
        print(f"  seg{tag}  frame {n}  直前と完全一致 {int(eq.sum())} "
              f"({eq.mean() * 100:.1f}%)")
    print(f"  合計 {same}/{tot} = {same / tot * 100:.1f}%  "
          f"→ 厳密一致dedupの削減 {1 / (1 - same / tot):.2f}倍")

    print("\n=== 3. packet size と画素差 ===")
    import cv2
    sizes, dmax, dmean = [], [], []
    for tag, f, sz, key in segs:
        for i in range(1, len(f)):
            d = cv2.absdiff(f[i], f[i - 1])
            sizes.append(int(sz[i]))
            dmax.append(int(d.max()))
            dmean.append(float(d.mean()))
    sizes = np.asarray(sizes); dmax = np.asarray(dmax); dmean = np.asarray(dmean)
    print(f"  {'packet size':>16s} {'件数':>6s} {'max|d| 中央':>11s} "
          f"{'mean|d| 中央':>12s} {'max|d|<=2の率':>13s}")
    edges = [0, 30, 60, 120, 250, 500, 1000, 2500, 10 ** 9]
    for a, b in zip(edges[:-1], edges[1:]):
        m = (sizes >= a) & (sizes < b)
        if not m.any():
            continue
        print(f"  {a:7d}-{b if b < 10**8 else 0:7d} {int(m.sum()):6d} "
              f"{np.median(dmax[m]):11.0f} {np.median(dmean[m]):12.3f} "
              f"{(dmax[m] <= 2).mean() * 100:12.1f}%")

    print("\n=== 4. 平坦領域 (8x8 block の輝度分散が小さい割合) ===")
    flat_tot = 0.0
    cnt = 0
    for tag, f, _, _ in segs:
        for i in range(0, len(f), 20):
            g = cv2.cvtColor(f[i], cv2.COLOR_BGR2GRAY).astype(np.float32)
            bh, bw = H // 8, W // 8
            blk = g.reshape(bh, 8, bw, 8)
            var = blk.var(axis=(1, 3))
            flat_tot += float((var < 4.0).mean())
            cnt += 1
    print(f"  分散<4 の 8x8 block: {flat_tot / cnt * 100:.1f}%")


if __name__ == "__main__":
    main()
