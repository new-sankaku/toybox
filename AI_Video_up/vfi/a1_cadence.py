"""素材の実測: コマ打ち・cut・動き量。

VFIの設計はここで決まる。
  - 同一frameがどれだけ続くか → model を呼ばずに済む出力frameの割合
  - cut がどこか            → 補間してはいけない箇所(品質・速度とも)
  - 動きが何画素か          → VFI が破綻する領域に入っているか
"""
import concurrent.futures as cf
import os
import sys
import threading
import time

import cv2
import numpy as np

import gpumetric as GM
import vfilib as V


class _ThreadLocal(threading.local):
    """Farneback の instance は thread ごとに持つ(内部bufferを使い回すため)。"""

    @property
    def flow(self):
        f = getattr(self, "_f", None)
        if f is None:
            f = cv2.FarnebackOpticalFlow_create(
                numLevels=4, pyrScale=0.5, winSize=21, numIters=3,
                polyN=5, polySigma=1.2)
            self._f = f
        return f


_TL = _ThreadLocal()

SMALL = (480, 270)   # 動き量とhistogramはここで測る


def _prep_gray(a):
    """縮小 + gray 化を GPU でまとめて済ませる。cv2 と同じ値になるよう丸める。"""
    import torch
    import torch.nn.functional as F
    n = len(a)
    out = np.empty((n, SMALL[1], SMALL[0]), np.uint8)
    k = V.W // SMALL[0]                       # 4 (整数分の1縮小 = box平均)
    w = torch.tensor([0.114, 0.587, 0.299], device="cuda").view(1, 3, 1, 1)
    for i in range(n):
        t = GM.to_gpu(np.array(a[i])).permute(2, 0, 1).unsqueeze(0).float()
        t = F.avg_pool2d(t, k).round_()        # INTER_AREA と同値
        g = (t * w).sum(1).round_().clamp_(0, 255).to(torch.uint8)
        out[i] = g[0].cpu().numpy()
    return out


def _pair_stats(a, i):
    """1組ぶんの画素統計を GPU で。np.percentile は 6.2M 要素の sort で重い。"""
    import torch
    x = GM.to_gpu(np.array(a[i])).float()
    y = GM.to_gpu(np.array(a[i + 1])).float()
    d = (x - y).abs_()
    mad = float(d.mean())
    p999 = int(torch.quantile(d.flatten()[::7].contiguous(), 0.999))
    box4 = int(round(GM.box4_max(x.to(torch.uint8), y.to(torch.uint8))))
    return mad, p999, box4


def analyse(clip):
    a = V.load(clip)
    n = len(a)
    V.log(f"{clip}: {n} frame を解析します")

    t0 = time.time()
    grays = _prep_gray(a)
    V.log(f"  縮小+gray化 {time.time()-t0:.1f}秒")

    # Farneback は cv2 が GIL を離すので thread pool が効く(12コア)
    t0 = time.time()
    def flow_pair(i):
        fl = _TL.flow
        f = fl.calc(grays[i], grays[i + 1], None)
        mag = np.sqrt(f[..., 0] ** 2 + f[..., 1] ** 2)
        k = V.W / SMALL[0]
        return (float(np.median(mag)) * k, float(np.percentile(mag, 95)) * k,
                float(mag.max()) * k)
    with cf.ThreadPoolExecutor(max_workers=os.cpu_count()) as ex:
        flows = list(ex.map(flow_pair, range(n - 1)))
    V.log(f"  optical flow {time.time()-t0:.1f}秒")

    t0 = time.time()
    rows = []
    for i in range(n - 1):
        exact = bool(np.array_equal(a[i], a[i + 1]))
        if exact:
            rows.append(dict(i=i, exact=True, box4=0, mad=0.0, p999=0,
                             histcorr=1.0, mv_med=0.0, mv_p95=0.0, mv_max=0.0))
            continue
        mad, p999, box4 = _pair_stats(a, i)
        h0 = cv2.calcHist([grays[i]], [0], None, [64], [0, 256])
        h1 = cv2.calcHist([grays[i + 1]], [0], None, [64], [0, 256])
        hc = float(cv2.compareHist(h0, h1, cv2.HISTCMP_CORREL))
        mv_med, mv_p95, mv_max = flows[i]
        rows.append(dict(i=i, exact=False, box4=box4, mad=mad, p999=p999,
                         histcorr=hc, mv_med=mv_med, mv_p95=mv_p95,
                         mv_max=mv_max))
    V.log(f"  画素統計 {time.time()-t0:.1f}秒")

    mad = np.array([r["mad"] for r in rows])
    hc = np.array([r["histcorr"] for r in rows])
    exact = np.array([r["exact"] for r in rows])

    # cut判定: 画素差が大きく、かつ輝度分布まで入れ替わっている物。
    # animeは閃光やwhite-outで画素差だけなら跳ねるので、histogramを併用する。
    cut = (mad > 18.0) & (hc < 0.90)
    for r, c in zip(rows, cut):
        r["cut"] = bool(c)

    # コマ打ち: 完全一致で繋がる run の長さ
    runs, cur = [], 1
    for e in exact:
        if e:
            cur += 1
        else:
            runs.append(cur)
            cur = 1
    runs.append(cur)
    runs = np.array(runs)
    rl = {int(k): int(v) for k, v in zip(*np.unique(runs, return_counts=True))}

    moving = ~exact & ~cut
    summary = dict(
        clip=clip, frames=n, pairs=len(rows),
        exact_dup=int(exact.sum()), exact_dup_pct=round(float(exact.mean()) * 100, 1),
        cuts=int(cut.sum()),
        moving_pairs=int(moving.sum()),
        run_lengths=rl,
        mean_run=round(float(runs.mean()), 2),
        drawings=int(len(runs)),
        drawings_per_sec=round(len(runs) / (n / (V.FPS_NUM / V.FPS_DEN)), 1),
        mv_med_of_moving=round(float(np.median([r["mv_med"] for r, m in zip(rows, moving) if m] or [0])), 2),
        mv_p95_of_moving=round(float(np.median([r["mv_p95"] for r, m in zip(rows, moving) if m] or [0])), 2),
        mv_p95_worst=round(float(max([r["mv_p95"] for r, m in zip(rows, moving) if m] or [0])), 2),
    )
    # box4 の分布(vupのdedup閾値がそのまま使えるか)
    b4 = np.array([r["box4"] for r in rows])
    summary["box4_pct"] = {f"<{t}": round(float((b4 < t).mean()) * 100, 1)
                           for t in (1, 4, 8, 12, 16, 20, 32)}

    np.save(V.RESULTS / f"cadence_{clip}.npy",
            np.array([(r["i"], r["exact"], r["box4"], r["mad"], r["p999"],
                       r["histcorr"], r["mv_med"], r["mv_p95"], r["mv_max"], r["cut"])
                      for r in rows],
                     dtype=[("i", "i4"), ("exact", "?"), ("box4", "i4"),
                            ("mad", "f4"), ("p999", "i4"), ("histcorr", "f4"),
                            ("mv_med", "f4"), ("mv_p95", "f4"), ("mv_max", "f4"),
                            ("cut", "?")]))
    V.record("cadence", summary)
    for k, v in summary.items():
        print(f"  {k}: {v}")
    return summary


if __name__ == "__main__":
    for c in (sys.argv[1:] or list(V.CLIPS)):
        analyse(c)
