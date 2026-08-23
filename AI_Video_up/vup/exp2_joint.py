"""dedup を掛けた「残り」に対して、空間方向の削減がまだ効くかを測る。

dedup は「ほぼ変化しない frame」を先に取り除くので、残った frame は当然汚れている。
tile 差分の評価は必ずこの残りに対して行わなければ意味が無い。

併せて、いちばん筋の良い空間手法である層別の縮小再計算も見積もる。
SRVGGNetCompact は 3x3 conv を L 段重ねただけなので、層 l の再計算に必要な
領域は「変化領域を (L-l) 画素だけ膨らませたもの」で足りる。
tile 差分が全層に受容野いっぱいの halo (15px) を付けるのに対し、
層が進むほど halo が縮む分だけ得をする。これが元を取れるかを面積で見積もる。
"""
import cv2
import numpy as np

from exp2_lib import H, W, all_segments

MB = 16
MBH, MBW = H // MB, W // MB
FULL = H * W
LAYERS = 16          # realesr-animevideov3 の conv 段数


def box4max(cur, ref):
    d = cv2.absdiff(cur, ref)
    return int(cv2.resize(d, (W // 4, H // 4),
                          interpolation=cv2.INTER_AREA).max()), d


def dirty_mb(d):
    return d.max(axis=2).reshape(MBH, MB, MBW, MB).max(axis=(1, 3)) > 0


def bbox(m):
    ys, xs = np.nonzero(m)
    if len(ys) == 0:
        return None
    return ys.min(), ys.max() + 1, xs.min(), xs.max() + 1


def main():
    segs = list(all_segments())
    n_all = 0
    n_sr = 0
    acc = {"矩形1個(halo16px)": 0.0, "横帯(halo16px)": 0.0,
           "tile128(halo16px)": 0.0, "層別縮小(矩形)": 0.0,
           "層別縮小(理論下限/MB単位)": 0.0}
    dirty_rate = []
    for _, f, _, _ in segs:
        ref = None
        for i in range(len(f)):
            n_all += 1
            if ref is None:
                ref = f[i]
                n_sr += 1
                for k in acc:
                    acc[k] += FULL
                continue
            v, d = box4max(f[i], ref)
            if v < 14:
                continue                      # dedup が拾う。SR しない
            n_sr += 1
            m = dirty_mb(d)
            dirty_rate.append(m.mean())
            ref = f[i]

            bb = bbox(m)
            if bb is None:
                for k in acc:
                    acc[k] += 0.0
                continue
            y0, y1, x0, x1 = bb

            # 矩形1個 + halo 1MB
            a = ((min(MBH, y1 + 1) - max(0, y0 - 1)) *
                 (min(MBW, x1 + 1) - max(0, x0 - 1))) * MB * MB
            acc["矩形1個(halo16px)"] += min(a, FULL)

            # 横帯
            rows = m.any(axis=1)
            g = np.convolve(rows.astype(np.int32), np.ones(3, np.int32),
                            mode="same") > 0
            acc["横帯(halo16px)"] += min(int(g.sum()) * MB * W, FULL)

            # tile 128px (=8MB) + halo 1MB
            t = 0
            for yy in range(0, MBH, 8):
                for xx in range(0, MBW, 8):
                    yy1, xx1 = min(yy + 8, MBH), min(xx + 8, MBW)
                    if m[max(0, yy - 1):min(MBH, yy1 + 1),
                         max(0, xx - 1):min(MBW, xx1 + 1)].any():
                        t += ((min(yy1 + 1, MBH) - max(0, yy - 1)) *
                              (min(xx1 + 1, MBW) - max(0, xx - 1))) * MB * MB
            acc["tile128(halo16px)"] += min(t, FULL)

            # 層別縮小: 層 l では (LAYERS-l) 画素の余白で足りる
            s = 0.0
            for l in range(LAYERS):
                pad = LAYERS - l
                hgt = min(H, (y1 * MB) + pad) - max(0, y0 * MB - pad)
                wid = min(W, (x1 * MB) + pad) - max(0, x0 * MB - pad)
                s += min(hgt * wid, FULL)
            acc["層別縮小(矩形)"] += s / LAYERS

            # 層別縮小の理論下限: 矩形にまとめず MB 集合のまま膨らませた面積
            s = 0.0
            base = m.astype(np.uint8)
            for l in range(LAYERS):
                pad = LAYERS - l
                k = 2 * int(np.ceil(pad / MB)) + 1
                g2 = cv2.dilate(base, np.ones((k, k), np.uint8))
                s += float(g2.sum()) * MB * MB
            acc["層別縮小(理論下限/MB単位)"] += min(s / LAYERS, FULL)

    print(f"評価 {n_all} frame  dedup(box4 max<14)後に SR する frame {n_sr} "
          f"({n_sr / n_all * 100:.1f}%)  → dedup単体 {n_all / n_sr:.2f}倍")
    dr = np.asarray(dirty_rate)
    print(f"SR する frame の変化MB率: 中央 {np.median(dr) * 100:.1f}%  "
          f"平均 {dr.mean() * 100:.1f}%  p10 {np.percentile(dr, 10) * 100:.1f}%")
    print(f"\n{'空間手法':26s} {'SR frameあたり面積':>16s} {'総合削減':>9s} "
          f"{'dedup比の上積み':>13s}")
    for k, a in acc.items():
        per = a / n_sr / FULL
        total = n_all / (n_sr * per)
        print(f"{k:26s} {per * 100:15.1f}% {total:8.2f}倍 "
              f"{1 / per:12.2f}倍")
    print(f"{'(空間削減なし)':26s} {100.0:15.1f}% {n_all / n_sr:8.2f}倍 "
          f"{1.0:12.2f}倍")


if __name__ == "__main__":
    main()
