"""真の source frame 間で「どこがどれだけ変わるか」を測る。

decode bug を直すと前frameとの完全一致は 3.1% しか無い。
frame 単位の使い回しが成立しないなら、残る手は
  - noise に強い判定で「同じ絵」をもっと拾えるか
  - 変化が空間的に局在しているか (tile 差分の再評価)
のどちらか。その両方の材料をここで出す。
"""
import cv2
import numpy as np

from exp2_lib import H, W, all_segments


def main():
    segs = list(all_segments())

    print("=== |diff| の値そのものの分布 (連続する真のsource frame) ===")
    hist = np.zeros(256, np.int64)
    for _, f, _, _ in segs:
        for i in range(1, len(f)):
            d = cv2.absdiff(f[i], f[i - 1])
            hist += np.bincount(d.reshape(-1), minlength=256)
    tot = hist.sum()
    cum = np.cumsum(hist) / tot
    for t in [0, 1, 2, 4, 8, 12, 16, 24, 32, 48, 64, 96, 128]:
        print(f"  |d|<={t:3d} の channel値: {cum[t] * 100:6.3f}%")

    print("\n=== 変化の空間的な広がり (120px tile, 24 tile/frame) ===")
    core = 120
    ys = list(range(0, H, core))
    xs = list(range(0, W, core))
    n_tile = len(ys) * len(xs)
    crits = [("max|d|>2 (現行tilediff)", "max", 2, 0),
             ("max|d|>8", "max", 8, 0),
             ("max|d|>16", "max", 16, 0),
             ("max|d|>32", "max", 32, 0),
             ("|d|>8 の値が16個超", "cnt", 8, 16),
             ("|d|>8 の値が64個超", "cnt", 8, 64),
             ("|d|>16 の値が16個超", "cnt", 16, 16),
             ("|d|>16 の値が64個超", "cnt", 16, 64),
             ("|d|>24 の値が32個超", "cnt", 24, 32)]
    hit = {c[0]: 0 for c in crits}
    nf = 0
    for _, f, _, _ in segs:
        for i in range(1, len(f)):
            d = cv2.absdiff(f[i], f[i - 1])
            nf += 1
            for name, kind, thr, cnt in crits:
                b = (d > thr)
                for y in ys:
                    for x in xs:
                        sub = b[y:y + core, x:x + core]
                        if (sub.any() if kind == "max" else
                                sub.sum() > cnt):
                            hit[name] += 1
    print(f"  評価 {nf} frame x {n_tile} tile = {nf * n_tile}")
    for name, _, _, _ in crits:
        r = hit[name] / (nf * n_tile)
        # halo 15px を core 120px に付けた場合の面積比
        area = r * (150 * 150) / (120 * 120)
        print(f"  {name:26s} 変化tile {r * 100:5.1f}%  "
              f"halo込み計算量比 {min(area, 1.0):.2f}")


if __name__ == "__main__":
    main()
