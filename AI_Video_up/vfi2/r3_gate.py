"""補間してはいけない所を実測で決める。cut / 大変位 / 意図的な静止。

3つ組 D_k-1, D_k, D_k+1 の真ん中を両端から作り、本物と比べる(正解がある)。
model が跨ぐのは D_k-1 -> D_k+1 なので、**横軸はその span の変位と尺**にする。
本番の schedule も「1つの pair を跨ぐ」形なので、同じ軸で読める。

対照は2つ。hold(D_k-1 をそのまま) と blend(tau_head の重み付き平均)。
model がこの2つに負ける領域が、補間してはいけない領域。
"""
import concurrent.futures as cf
import os
import sys
import threading

import cv2
import numpy as np
import torch

import lib
import r1_cadence as R1
import r_model
import retime

SMALL = (480, 270)
MAX_SPAN = 120        # frame。長い静止も含めて測るので広く取る

MV_BINS = [0, 4, 8, 16, 32, 64, 128, 1e9]
MV_LABEL = ["0-4", "4-8", "8-16", "16-32", "32-64", "64-128", "128-"]
SPAN_BINS = [0, 2, 4, 6, 8, 12, 16, 24, 1e9]
SPAN_LABEL = ["2", "3-4", "5-6", "7-8", "9-12", "13-16", "17-24", "25-"]

ROW = np.dtype([("k", "i4"), ("r0", "i4"), ("r1", "i4"), ("r2", "i4"),
                ("span", "i4"), ("mv", "f4"), ("tau", "f8"), ("cut", "?"),
                ("lp_model", "f8"), ("lp_hold", "f8"), ("lp_blend", "f8"),
                ("gm_model", "f8"), ("gm_hold", "f8"), ("gm_blend", "f8")])


class _TL(threading.local):
    @property
    def flow(self):
        f = getattr(self, "_f", None)
        if f is None:
            f = cv2.FarnebackOpticalFlow_create(
                numLevels=5, pyrScale=0.5, winSize=25, numIters=3,
                polyN=5, polySigma=1.2)
            self._f = f
        return f


_T = _TL()


def _gray(a, i):
    return cv2.cvtColor(cv2.resize(np.array(a[i]), SMALL,
                                   interpolation=cv2.INTER_AREA),
                        cv2.COLOR_BGR2GRAY)


def span_mv(clip):
    """D_k-1 -> D_k+1 の flow p95(原寸 px)。model が実際に跨ぐ量。"""
    dst = lib.RESULTS / f"spanmv2_{clip}.npy"
    if dst.exists():
        return np.load(dst)
    a = lib.load(clip)
    runs = lib.drawing_runs(clip)
    g = {k: _gray(a, int(runs[k])) for k in range(len(runs))}

    def one(k):
        f = _T.flow.calc(g[k - 1], g[k + 1], None)
        m = np.sqrt(f[..., 0] ** 2 + f[..., 1] ** 2)
        return float(np.percentile(m, 95)) * (lib.W / SMALL[0])

    with cf.ThreadPoolExecutor(max_workers=os.cpu_count()) as ex:
        v = list(ex.map(one, range(1, len(runs) - 1)))
    out = np.array(v, dtype=np.float32)
    np.save(dst, out)
    return out


def run(clip, model_name=r_model.DEFAULT):
    dst = lib.RESULTS / f"gate_{clip}_{model_name}.npy"
    if dst.exists():
        return np.load(dst)
    a = lib.load(clip)
    runs = lib.drawing_runs(clip)
    n = len(a)
    p = R1.pairs(clip)
    smv = span_mv(clip)
    th = retime.loo_tau(runs, n, "head")
    M = r_model.Model(model_name)
    lib.log(f"{clip}: 3つ組 {len(runs)-2} 件")

    rows = []
    for k in range(1, len(runs) - 1):
        r0, r1, r2 = int(runs[k - 1]), int(runs[k]), int(runs[k + 1])
        if r2 - r0 > MAX_SPAN:
            continue
        cut = bool(p["cut"][k - 1] or p["cut"][k])
        tau = float(th[k - 1])
        f0 = M.to_gpu(np.array(a[r0]))
        f2 = M.to_gpu(np.array(a[r2]))
        gt = M.to_gpu(np.array(a[r1]))
        y = M.infer(f0, f2, tau).clone()
        bl = (f0.float() * (1 - tau) + f2.float() * tau).round().to(torch.uint8)
        rows.append((k, r0, r1, r2, r2 - r0, float(smv[k - 1]), tau, cut,
                     lib.lpips_score(y, gt), lib.lpips_score(f0, gt),
                     lib.lpips_score(bl, gt),
                     lib.gmsd(y, gt), lib.gmsd(f0, gt), lib.gmsd(bl, gt)))
        del f0, f2, gt, y, bl

    arr = np.array(rows, dtype=ROW)
    np.save(dst, arr)
    del M
    torch.cuda.empty_cache()
    return arr


def _bucket(arr, values, bins, labels, title):
    print(f"\n  --- {title}")
    print("  | 区間 | 組数 | model | hold | blend | model勝ち |")
    print("  |---|---|---|---|---|---|")
    out = {}
    idx = np.digitize(values, bins) - 1
    for b, lab in enumerate(labels):
        s = arr[idx == b]
        if not len(s):
            continue
        win = float((s["lp_model"] < np.minimum(s["lp_hold"], s["lp_blend"])).mean())
        out[lab] = dict(n=len(s), model=round(float(s["lp_model"].mean()), 5),
                        hold=round(float(s["lp_hold"].mean()), 5),
                        blend=round(float(s["lp_blend"].mean()), 5),
                        win=round(win * 100, 1))
        print(f"  | {lab} | {len(s)} | {s['lp_model'].mean():.5f} | "
              f"{s['lp_hold'].mean():.5f} | {s['lp_blend'].mean():.5f} | "
              f"{win*100:.0f}% |")
    return out


def report(clip, model_name=r_model.DEFAULT):
    arr = run(clip, model_name)
    live = arr[~arr["cut"]]
    cutr = arr[arr["cut"]]
    print(f"\n=== {clip} (3つ組 {len(arr)} / うち cut を跨ぐ {len(cutr)})")
    info = dict(clip=clip, model=model_name, n=len(arr), n_cut=len(cutr))
    if len(cutr):
        info["cut"] = dict(
            n=len(cutr), model=round(float(cutr["lp_model"].mean()), 5),
            hold=round(float(cutr["lp_hold"].mean()), 5),
            blend=round(float(cutr["lp_blend"].mean()), 5))
        print(f"  cut を跨ぐ組: model {cutr['lp_model'].mean():.5f} / "
              f"hold {cutr['lp_hold'].mean():.5f} / "
              f"blend {cutr['lp_blend'].mean():.5f}")
    info["by_mv"] = _bucket(live, live["mv"], MV_BINS, MV_LABEL,
                            "跨ぐ変位 (flow p95, 原寸px)")
    # 変位の影響を切り離すため、mv が model の効く範囲にある組だけで尺を見る
    small = live[live["mv"] <= 32]
    info["by_span"] = _bucket(small, small["span"], SPAN_BINS, SPAN_LABEL,
                              "跨ぐ尺 (frame, 変位32px以下の組だけ)")
    lib.record("retime_gate", info)
    return info


if __name__ == "__main__":
    for c in (sys.argv[1:] or list(lib.CLIPS)):
        report(c)
