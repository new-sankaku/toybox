"""絵の代表時刻をどこに置くか(run の先頭か中央か)を実測で決める。

## やり方

連続する3枚の絵 D_k-1, D_k, D_k+1 について、両端から tau を 0.05 刻みで
振って中間を作り、本物の D_k と LPIPS が最小になる tau*(= 実際の代表時刻の比)
を求める。これは「1枚落として復元」の tau を推定する操作そのもので、
**正解のある測り方**。

  head   なら tau_pred = L_k-1 / (L_k-1 + L_k)
  center なら tau_pred = (中央時刻の比)

コマ打ちが一定な所では両者は必ず 0.5 で一致するので、
**差が付く所(|tau_head - tau_center| >= 0.05)だけを別掲**する。ここが判定点。
"""
import sys

import numpy as np
import torch

import lib
import r1_cadence as R1
import r_model
import retime

TAUS = np.round(np.arange(0.05, 0.96, 0.05), 3)
MAX_SPAN = 12       # D_k-1 から D_k+1 までの frame 数の上限
MV_MAX = 64.0       # これを超えると model が壊れて tau* が読めない
SPLIT = 0.05        # head と center の予測がこれ以上違う組を「割れる組」とする


def triples(clip):
    """試験に使う3つ組。cut・意図的な静止・大変位を外す。"""
    a = lib.load(clip)
    runs = lib.drawing_runs(clip)
    p = R1.pairs(clip)
    n = len(a)
    L = np.append(np.diff(runs), n - runs[-1])
    th = retime.loo_tau(runs, n, "head")
    tc = retime.loo_tau(runs, n, "center")
    out = []
    for k in range(1, len(runs) - 1):
        r0, r1, r2 = int(runs[k - 1]), int(runs[k]), int(runs[k + 1])
        if r2 - r0 > MAX_SPAN:
            continue
        if p["cut"][k - 1] or p["cut"][k]:
            continue
        mv = max(float(p["mv"][k - 1]), float(p["mv"][k]))
        if mv > MV_MAX:
            continue
        out.append((k, r0, r1, r2, int(L[k - 1]), int(L[k]),
                    float(th[k - 1]), float(tc[k - 1]), mv))
    return out


def _argmin_tau(vals):
    """格子の最小点を放物線で refine する。端に張り付いたら None。"""
    i = int(np.argmin(vals))
    if i == 0 or i == len(vals) - 1:
        return None
    y0, y1, y2 = vals[i - 1], vals[i], vals[i + 1]
    d = y0 - 2 * y1 + y2
    off = 0.0 if d == 0 else 0.5 * (y0 - y2) / d
    return float(TAUS[i] + off * (TAUS[1] - TAUS[0]))


def run(clip, model_name=r_model.DEFAULT):
    key = (clip, model_name)
    if key in lib.done_keys("anchor", ("clip", "model")):
        lib.log(f"{clip}: 済み")
        return
    a = lib.load(clip)
    tri = triples(clip)
    if len(tri) < 20:
        raise RuntimeError(f"{clip}: 試験に使える3つ組が {len(tri)} しかありません")
    lib.log(f"{clip}: 3つ組 {len(tri)} 件 x tau {len(TAUS)} 点")
    M = r_model.Model(model_name)

    rows = []
    for (k, r0, r1, r2, L0, L1, th, tc, mv) in tri:
        f0 = M.to_gpu(np.array(a[r0]))
        f2 = M.to_gpu(np.array(a[r2]))
        gt = M.to_gpu(np.array(a[r1]))
        lp = []
        for tau in TAUS:
            y = M.infer(f0, f2, float(tau))
            lp.append(lib.lpips_score(y, gt))
        lp = np.array(lp)
        best = _argmin_tau(lp)
        # 予測時刻そのもので作った時の品質(実際に効く数字)
        lp_head = float(np.interp(th, TAUS, lp))
        lp_center = float(np.interp(tc, TAUS, lp))
        lp_half = float(np.interp(0.5, TAUS, lp))
        rows.append((k, L0, L1, th, tc, mv,
                     np.nan if best is None else best,
                     float(lp.min()), lp_head, lp_center, lp_half))
        del f0, f2, gt

    arr = np.array(rows, dtype=[("k", "i4"), ("L0", "i4"), ("L1", "i4"),
                                ("th", "f8"), ("tc", "f8"), ("mv", "f4"),
                                ("best", "f8"), ("lp_best", "f8"),
                                ("lp_head", "f8"), ("lp_center", "f8"),
                                ("lp_half", "f8")])
    np.save(lib.RESULTS / f"anchor_{clip}_{model_name}.npy", arr)

    ok = np.isfinite(arr["best"])
    split = np.abs(arr["th"] - arr["tc"]) >= SPLIT
    info = dict(clip=clip, model=model_name, n=len(arr),
                n_resolved=int(ok.sum()),
                n_split=int(split.sum()),
                n_split_resolved=int((split & ok).sum()),
                lp_head=round(float(arr["lp_head"].mean()), 5),
                lp_center=round(float(arr["lp_center"].mean()), 5),
                lp_half=round(float(arr["lp_half"].mean()), 5),
                lp_best=round(float(arr["lp_best"].mean()), 5))
    for label, mask in (("all", ok), ("split", ok & split)):
        s = arr[mask]
        if not len(s):
            continue
        info[f"err_head_{label}"] = round(float(np.abs(s["best"] - s["th"]).mean()), 4)
        info[f"err_center_{label}"] = round(float(np.abs(s["best"] - s["tc"]).mean()), 4)
        info[f"err_half_{label}"] = round(float(np.abs(s["best"] - 0.5).mean()), 4)
        info[f"bias_vs_head_{label}"] = round(float((s["best"] - s["th"]).mean()), 4)
    for label, mask in (("all", np.ones(len(arr), bool)), ("split", split)):
        s = arr[mask]
        if not len(s):
            continue
        info[f"lp_head_{label}"] = round(float(s["lp_head"].mean()), 5)
        info[f"lp_center_{label}"] = round(float(s["lp_center"].mean()), 5)
    lib.record("anchor", info)
    for kk, vv in info.items():
        print(f"  {kk}: {vv}")
    del M
    torch.cuda.empty_cache()


if __name__ == "__main__":
    for c in (sys.argv[1:] or list(lib.CLIPS)):
        lib.log(f"=== 代表時刻 {c}")
        run(c)
