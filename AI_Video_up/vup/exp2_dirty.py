"""h264 の skip macroblock を「画素の完全一致」から無料で取り出す。

tile 差分が失敗した理由は encode noise だが、noise が乗るのは
「再coding された macroblock」だけで、skip した macroblock は参照frameから
そのままcopyされるので **decode 結果が bit 単位で一致** する。
つまり 16x16 の完全一致判定は、bitstream を読まずに skip map を得ることと同じで、
閾値が要らない = noise に一切影響されない。

その dirty map から、実際に SR へ通す形(矩形1個 / 横帯 / tile)の面積を測る。
"""
import cv2
import numpy as np

from exp2_lib import H, W, all_segments

MB = 16
MBH, MBW = H // MB, W // MB


def dirty_map(a, b):
    """16x16 macroblock 単位の完全一致判定。True = 変化あり。"""
    d = cv2.absdiff(a, b).max(axis=2)
    blk = d.reshape(MBH, MB, MBW, MB)
    return blk.max(axis=(1, 3)) > 0


def bbox_area(m, halo_mb):
    ys, xs = np.nonzero(m)
    if len(ys) == 0:
        return 0
    y0 = max(0, ys.min() - halo_mb) * MB
    y1 = min(MBH, ys.max() + 1 + halo_mb) * MB
    x0 = max(0, xs.min() - halo_mb) * MB
    x1 = min(MBW, xs.max() + 1 + halo_mb) * MB
    return (y1 - y0) * (x1 - x0)


def band_area(m, halo_mb):
    rows = m.any(axis=1)
    if not rows.any():
        return 0
    grown = np.convolve(rows.astype(np.int32),
                        np.ones(2 * halo_mb + 1, np.int32), mode="same") > 0
    return int(grown.sum()) * MB * W


def tile_area(m, core_mb, halo_mb):
    total = 0
    for y in range(0, MBH, core_mb):
        for x in range(0, MBW, core_mb):
            y1, x1 = min(y + core_mb, MBH), min(x + core_mb, MBW)
            if m[max(0, y - halo_mb):min(MBH, y1 + halo_mb),
                 max(0, x - halo_mb):min(MBW, x1 + halo_mb)].any():
                total += ((min(y1 + halo_mb, MBH) - max(0, y - halo_mb)) *
                          (min(x1 + halo_mb, MBW) - max(0, x - halo_mb))) * MB * MB
    return total


def main():
    segs = list(all_segments())
    halo_mb = 1                     # 15px の受容野 -> 16px = MB 1個で足りる
    full = H * W
    acc = {}
    dirty_mb = 0
    n_mb = 0
    nf = 0
    for _, f, _, _ in segs:
        for i in range(1, len(f)):
            m = dirty_map(f[i], f[i - 1])
            nf += 1
            dirty_mb += int(m.sum())
            n_mb += m.size
            for name, a in (("矩形1個(bbox)", bbox_area(m, halo_mb)),
                            ("横帯(全幅)", band_area(m, halo_mb)),
                            ("tile 128px", tile_area(m, 8, halo_mb)),
                            ("tile 64px", tile_area(m, 4, halo_mb)),
                            ("tile 32px", tile_area(m, 2, halo_mb))):
                acc[name] = acc.get(name, 0) + min(a, full)
    print(f"評価 {nf} frame")
    print(f"変化した macroblock: {dirty_mb / n_mb * 100:.1f}%  "
          f"(halo無しの理論下限 計算量比 {dirty_mb / n_mb:.3f})")
    print(f"\n{'切り出し方':16s} {'平均面積比':>10s} {'削減':>7s}")
    for name, a in acc.items():
        r = a / (nf * full)
        print(f"{name:16s} {r * 100:9.1f}% {1 / max(r, 1e-9):6.2f}倍")

    print("\n=== 変化macroblock率の frame 分布 ===")
    rates = []
    for _, f, _, _ in segs:
        for i in range(1, len(f)):
            rates.append(dirty_map(f[i], f[i - 1]).mean())
    rates = np.asarray(rates)
    for q in [10, 25, 50, 75, 90, 95, 99]:
        print(f"  p{q:2d}  {np.percentile(rates, q) * 100:5.1f}%")
    for t in [0.05, 0.2, 0.4, 0.6, 0.8]:
        print(f"  変化MB率<={t*100:3.0f}% の frame: {(rates <= t).mean() * 100:5.1f}%")


if __name__ == "__main__":
    main()
