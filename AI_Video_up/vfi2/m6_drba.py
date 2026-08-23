"""DRBA の中身(DistanceRatioMap)がこの素材で成立するかを測る。

## DRBA が何をしているか

連続する3枚 I0, I1, I2 について flow(I1→I0) と flow(I1→I2) を取り、
その長さ d10, d12 から画素ごとに

    drm10 = d10 / (d10 + d12)

を作る。これは「I1 は I0 と I2 の間の**どこの時刻**に居るか」の推定で、
**動いた距離を時間の代わりに使っている**。I1 から I0 へ2倍動いていれば
I1 は I2 寄りの時刻に居る、と読む。

そして RIFE / GMFSS の timestep 引数に **scalar ではなくこの map** を渡す。
1枚の中でキャラが3コマ打ち・背景が1コマ打ち、のように cadence が混ざっていても
領域ごとに違う時刻で補間できる、というのが売り。

## ここで測る2つ

1. **推定は当たるか**   drm10 の代表値 と 真の tau=(r1-r0)/(r2-r0) を比べる。
   我々は frame 番号から真の時刻を**知っている**ので、当たるかどうかは
   「DRBA の推定段が要るか」の判断に直結する。
2. **画素ごとに割る意味があるか**  drm10 の画素間のばらつき。
   ばらつきが小さいなら scalar tau で足り、DRBA の per-pixel は要らない。

流れの無い画素は 0/0 で意味が無いので、代表値は (d10+d12) を重みにした
重み付き分位数で取る。
"""
import sys

import numpy as np
import torch

import lib
import vfimodels

DRBA = vfimodels.MODELS / "DRBA"
MOVE_MIN_PX = 1.0     # 低解像 flow でこれ未満の画素は「動いていない」として除く


def weighted_quantile(v, w, q):
    o = torch.argsort(v)
    v, w = v[o], w[o]
    c = torch.cumsum(w, 0)
    c = c / c[-1]
    i = int(torch.searchsorted(c, torch.tensor(q, device=v.device)).clamp(0, len(v) - 1))
    return float(v[i])


def run(clips):
    sys.path.insert(0, str(DRBA))
    from models.rife import RIFE
    from models.utils.tools import distance_calculator

    m = RIFE(weights=str(DRBA / "weights" / "train_log_rife_426_heavy"), scale=1.0)
    pw, ph = vfimodels._pad_to(lib.W, 64), vfimodels._pad_to(lib.H, 64)

    for clip in clips:
        a = lib.load(clip)
        ts = np.load(lib.RESULTS / f"testset_{clip}.npy")
        rows = []
        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.float16):
            for rec in ts:
                r0, r1, r2 = int(rec["r0"]), int(rec["r1"]), int(rec["r2"])
                I = [vfimodels._bgr_to_rgb_f32(vfimodels.to_gpu(np.array(a[r])),
                                               ph, pw, lib.H, lib.W)
                     for r in (r0, r1, r2)]
                flow10 = m.calc_flow(I[1], I[0])[0]
                flow12 = m.calc_flow(I[1], I[2])[0]
                d10 = distance_calculator(flow10).float().flatten()
                d12 = distance_calculator(flow12).float().flatten()
                tot = d10 + d12
                keep = tot > MOVE_MIN_PX
                if keep.sum() < 100:
                    rows.append((float(rec["tau"]), float(rec["span"]),
                                 np.nan, np.nan, np.nan, 0.0))
                    continue
                drm = (d10[keep] / tot[keep])
                w = tot[keep]
                rows.append((float(rec["tau"]), float(rec["span"]),
                             weighted_quantile(drm, w, 0.5),
                             weighted_quantile(drm, w, 0.1),
                             weighted_quantile(drm, w, 0.9),
                             float(keep.float().mean())))
        r = np.array(rows, dtype=[("tau", "f4"), ("span", "f4"), ("drm50", "f4"),
                                  ("drm10", "f4"), ("drm90", "f4"), ("cover", "f4")])
        np.save(lib.RESULTS / f"drba_drm_{clip}.npy", r)

        ok = np.isfinite(r["drm50"])
        d, t = r["drm50"][ok], r["tau"][ok]
        info = dict(clip=clip, n=int(ok.sum()), n_skipped=int((~ok).sum()),
                    mae_drm_vs_tau=round(float(np.abs(d - t).mean()), 4),
                    mae_half_vs_tau=round(float(np.abs(0.5 - t).mean()), 4),
                    corr=round(float(np.corrcoef(d, t)[0, 1]), 3)
                    if t.std() > 1e-6 else None,
                    drm_mean=round(float(d.mean()), 4),
                    tau_mean=round(float(t.mean()), 4),
                    spread_p90_minus_p10=round(
                        float((r["drm90"][ok] - r["drm10"][ok]).mean()), 4),
                    moving_pixels_pct=round(float(r["cover"][ok].mean()) * 100, 1))
        lib.record("drba_drm", info)
        for k, v in info.items():
            print(f"  {k}: {v}")




# ---------------------------------------------------------------- 生 frame 側
#
# 上の試験は「絵の列」の上で測っている。絵へ畳んだ後の tau は既にほぼ 0.5 で
# (実測 |tau-0.5| の平均が 0.016〜0.060)、直す時刻がほとんど無い。
# DRBA が本来相手にするのは **畳む前の生の frame 列** で、I1 が I0 の複製に
# なっている場合。そちらでも測る。
#
# 真の答え: frame i,i+1,i+2 が属する絵の番号を k0,k1,k2 として
#   true = (k1-k0)/(k2-k0)      (k2==k0 の組は「間が無い」ので除く)
# 2コマ打ちなら true は 0 か 1 の二択で、DRBA が当てるべきはそこ。

N_RAW = 150


def run_raw(clips):
    sys.path.insert(0, str(DRBA))
    from models.rife import RIFE
    from models.utils.tools import distance_calculator

    m = RIFE(weights=str(DRBA / "weights" / "train_log_rife_426_heavy"), scale=1.0)
    pw, ph = vfimodels._pad_to(lib.W, 64), vfimodels._pad_to(lib.H, 64)

    for clip in clips:
        a = lib.load(clip)
        scd = lib.scdet(clip)
        runs = lib.drawing_runs(clip)
        di = np.zeros(len(a), dtype=np.int32)
        for k in range(len(runs)):
            end = int(runs[k + 1]) if k + 1 < len(runs) else len(a)
            di[int(runs[k]):end] = k

        cand = []
        for i in range(len(a) - 2):
            k0, k1, k2 = int(di[i]), int(di[i + 1]), int(di[i + 2])
            if k2 == k0 or (scd[i:i + 2] >= lib.SCD_CUT).any():
                continue
            cand.append((i, (k1 - k0) / (k2 - k0)))
        if len(cand) < 20:
            lib.log(f"{clip}: 生 frame の組が {len(cand)} しかありません")
            continue
        rng = np.random.default_rng(2)
        idx = sorted(rng.choice(len(cand), min(len(cand), N_RAW), replace=False))
        sel = [cand[j] for j in idx]

        rows = []
        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.float16):
            for i, true in sel:
                I = [vfimodels._bgr_to_rgb_f32(vfimodels.to_gpu(np.array(a[i + k])),
                                               ph, pw, lib.H, lib.W) for k in (0, 1, 2)]
                d10 = distance_calculator(m.calc_flow(I[1], I[0])[0]).float().flatten()
                d12 = distance_calculator(m.calc_flow(I[1], I[2])[0]).float().flatten()
                tot = d10 + d12
                keep = tot > MOVE_MIN_PX
                if keep.sum() < 100:
                    # 3枚とも動きが無いのに絵が変わっている = flow が拾えていない
                    rows.append((true, np.nan, 0.0))
                    continue
                rows.append((true,
                             weighted_quantile(d10[keep] / tot[keep], tot[keep], 0.5),
                             float(keep.float().mean())))
        r = np.array(rows, dtype=[("true", "f4"), ("drm50", "f4"), ("cover", "f4")])
        np.save(lib.RESULTS / f"drba_raw_{clip}.npy", r)
        ok = np.isfinite(r["drm50"])
        d, t = r["drm50"][ok], r["true"][ok]
        info = dict(clip=clip, n=int(ok.sum()), n_skipped=int((~ok).sum()),
                    pool=len(cand),
                    mae_drm_vs_true=round(float(np.abs(d - t).mean()), 4),
                    mae_half_vs_true=round(float(np.abs(0.5 - t).mean()), 4),
                    corr=round(float(np.corrcoef(d, t)[0, 1]), 3)
                    if t.std() > 1e-6 else None,
                    true_hist={str(v): int((np.round(t, 3) == v).sum())
                               for v in sorted(set(np.round(t, 3).tolist()))},
                    drm_mean=round(float(d.mean()), 4),
                    true_mean=round(float(t.mean()), 4))
        lib.record("drba_raw", info)
        print(f"[生frame] {clip}")
        for k, v in info.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    if which in ("both", "drawing"):
        run(list(lib.CLIPS))
    if which in ("both", "raw"):
        run_raw(list(lib.CLIPS))
