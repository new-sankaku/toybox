"""anime 特有の構造を2つ試す。

A. 整数画素の全画面 pan
   conv net は平行移動に対して等変なので、frame i が frame i-1 の整数画素
   平行移動そのものなら SR(i) = SR(i-1) を scale 倍の量だけずらしたものと
   厳密に一致する(新しく画面に入った縁を除く)。cel の pan は anime に多い。
   → 何%の frame が整数 pan で説明できるかを測る。

B. 中間 frame の生成 (前後から作って SR を半分にする)
   前後の SR 結果から中間を作れれば SR 回数は半分になる。
   ここでは「作れるのか」だけを先に確かめる。前 frame をそのまま使う(hold)、
   前後の平均、DIS optical flow による warp の3つを、真の frame と比べる。
   hold より有意に良くならなければ、どんな補間器を持ってきても成立しない。
"""
import time

import cv2
import numpy as np

from exp2_lib import H, W, all_segments

MAXS = 12          # 探索する平行移動の最大画素


def box4max(d):
    return int(cv2.resize(d, (W // 4, H // 4),
                          interpolation=cv2.INTER_AREA).max())


def best_shift(cur, ref):
    """中央の crop を matchTemplate で照合し、最も合う整数 shift を返す。"""
    m = MAXS
    tpl = cur[m + 60:H - m - 60, m + 60:W - m - 60]
    res = cv2.matchTemplate(ref[60:H - 60, 60:W - 60], tpl, cv2.TM_SQDIFF)
    _, _, loc, _ = cv2.minMaxLoc(res)
    return loc[0] - m, loc[1] - m           # (dx, dy): ref を動かす量


def shifted_diff(cur, ref, dx, dy):
    """ref を (dx,dy) ずらして cur と重なる領域だけで |d| を取る。"""
    x0, x1 = max(0, dx), min(W, W + dx)
    y0, y1 = max(0, dy), min(H, H + dy)
    if x1 - x0 < W // 2 or y1 - y0 < H // 2:
        return None
    a = cur[y0:y1, x0:x1]
    b = ref[y0 - dy:y1 - dy, x0 - dx:x1 - dx]
    return cv2.absdiff(a, b)


def part_a(segs):
    print("=== A. 整数画素 pan で説明できる frame の割合 ===")
    n = still = pan = 0
    t = 0.0
    pans = []
    for _, f, _, _ in segs:
        for i in range(1, len(f)):
            n += 1
            d0 = cv2.absdiff(f[i], f[i - 1])
            if box4max(d0) < 14:
                still += 1
                continue
            t0 = time.perf_counter()
            dx, dy = best_shift(f[i], f[i - 1])
            t += time.perf_counter() - t0
            if dx == 0 and dy == 0:
                continue
            ds = shifted_diff(f[i], f[i - 1], dx, dy)
            if ds is None:
                continue
            v = int(cv2.resize(ds, (ds.shape[1] // 4, ds.shape[0] // 4),
                               interpolation=cv2.INTER_AREA).max())
            if v < 14:
                pan += 1
                pans.append((dx, dy))
    print(f"  評価 {n} frame")
    print(f"  box4 max<14 でそのまま使い回せる: {still} ({still / n * 100:.1f}%)")
    print(f"  残りのうち整数 pan で説明できる:   {pan} ({pan / n * 100:.1f}%)")
    print(f"  併用時の SR 削減: {n / max(n - still - pan, 1):.2f}倍 "
          f"(pan 無しなら {n / max(n - still, 1):.2f}倍)")
    print(f"  shift 探索の実測: {t / max(n - still, 1) * 1000:.2f} ms/frame")
    if pans:
        u, c = np.unique(np.asarray(pans), axis=0, return_counts=True)
        top = np.argsort(-c)[:5]
        print("  よく出た shift: " +
              "  ".join(f"({u[k][0]},{u[k][1]})x{c[k]}" for k in top))


def part_b(segs):
    print("\n=== B. 中間 frame を前後から作れるか ===")
    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    res = {"hold(前frameそのまま)": [], "前後の平均": [], "DIS flow で warp": []}
    t_flow = 0.0
    cnt = 0
    for _, f, _, _ in segs:
        for i in range(1, len(f) - 1, 2):
            a, b, c = f[i - 1], f[i], f[i + 1]
            ga = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
            gc = cv2.cvtColor(c, cv2.COLOR_BGR2GRAY)
            t0 = time.perf_counter()
            fw = dis.calc(ga, gc, None)
            t_flow += time.perf_counter() - t0
            cnt += 1
            gx, gy = np.meshgrid(np.arange(W, dtype=np.float32),
                                 np.arange(H, dtype=np.float32))
            mapx = gx + fw[..., 0] * 0.5
            mapy = gy + fw[..., 1] * 0.5
            warp = cv2.remap(a, mapx, mapy, cv2.INTER_LINEAR)
            for name, pred in (("hold(前frameそのまま)", a),
                               ("前後の平均",
                                cv2.addWeighted(a, 0.5, c, 0.5, 0)),
                               ("DIS flow で warp", warp)):
                mse = float(np.mean(
                    (pred.astype(np.float32) - b.astype(np.float32)) ** 2))
                res[name].append(99.0 if mse == 0 else
                                 10 * np.log10(255.0 ** 2 / mse))
    print(f"  評価 {cnt} frame  (奇数frameを前後から作る想定)")
    print(f"  {'作り方':22s} {'PSNR平均':>9s} {'PSNR中央':>9s} {'PSNR<30の率':>11s}")
    for name, v in res.items():
        v = np.asarray(v)
        print(f"  {name:22s} {v.mean():9.1f} {np.median(v):9.1f} "
              f"{(v < 30).mean() * 100:10.1f}%")
    print(f"  DIS flow の計算だけで {t_flow / cnt * 1000:.1f} ms/frame (CPU)")


def main():
    segs = list(all_segments())
    part_a(segs)
    part_b(segs)


if __name__ == "__main__":
    main()
