"""任意 tau を本当に扱えるかを測る。**1 process 1 model**。

    python m4_tau.py <model_key>

## なぜ要るか

チームの中心仮説は「anime は絵が保持されるので frame 間 x2 では動きが変わらない。
**絵と絵の間を任意時刻で補間して時刻を張り直す**」。これが成立する条件は
model が tau を正しく扱えることで、扱えない model は候補から外れる。

IFRNet の Vimeo90K 重みが実際にそうだった(tau=0 と tau=1 の出力の最大差が
2.2e-6)。「signature に t がある」ことは「t を見ている」ことを意味しない。

## 3段階で見る

1. **応答**   tau を振ると出力が変わるか。max|y(0)-y(1)| と max|y(.25)-y(.75)|
2. **利得**   真の tau で作った方が tau=0.5 で作るより本物に近いか。
              **4枚の絵の両端から内側2枚を作る**組(tau≒1/3, 2/3)で対で比べる。
              **tau を無視する model はここで差が 0 になる**
3. **単調性** tau を掃いた時、LPIPS が最小になる tau が真の tau を追うか。
              追わない model は「t を見ているが目盛りが違う」
"""
import sys

import cv2
import numpy as np
import torch

import lib
import vfimodels

sys.path.insert(0, str(lib.VFI1))
import gpumetric as GM        # noqa: E402
import vfilib as V            # noqa: E402

MAX_SPAN = 16         # D0 から D3 までの frame 数の上限
N_PER_CLIP = 80       # 1 clip から取る試験の数(1つの4枚組から2つ作る)
SWEEP = [0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875]
N_SWEEP = 24
SMALL = (480, 270)


def offcenter_set(clip, seed=1):
    """**4枚の絵** D0,D1,D2,D3 を取り、両端 D0,D3 から中の2枚を作る組。

    絵が3枚だと真ん中の tau はほぼ 0.5 に張り付く(実測: |tau-0.5|>=0.15 の組が
    A_op 574中49、B_talk 106中12 しか無い)。4枚にすると内側の2枚は
    tau≈1/3 と 2/3 に落ちるので、**tau を無視する model と扱える model が
    はっきり割れる**。しかも「絵を等間隔でなく任意時刻へ置き直す」という
    本番の使い方そのものになる。
    """
    dst = lib.RESULTS / f"offcenter4_{clip}.npy"
    if dst.exists():
        return np.load(dst)
    a = lib.load(clip)
    scd = lib.scdet(clip)
    runs = lib.drawing_runs(clip)
    flow = cv2.FarnebackOpticalFlow_create(numLevels=5, pyrScale=0.5, winSize=25,
                                           numIters=3, polyN=5, polySigma=1.2)
    cand = []
    for k in range(len(runs) - 3):
        r0, r1, r2, r3 = (int(runs[k + j]) for j in range(4))
        if r3 - r0 > MAX_SPAN or (scd[r0:r3] >= lib.SCD_CUT).any():
            continue
        for rm in (r1, r2):
            cand.append((r0, rm, r3, (rm - r0) / (r3 - r0)))
    if len(cand) < 20:
        raise RuntimeError(f"{clip}: 4枚組が {len(cand)} しかありません")
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(cand), min(len(cand), N_PER_CLIP), replace=False)
    sel = [cand[i] for i in sorted(idx)]
    out = np.zeros(len(sel), dtype=[("r0", "i4"), ("r1", "i4"), ("r2", "i4"),
                                    ("tau", "f4"), ("span", "f4")])
    for i, (r0, r1, r2, tau) in enumerate(sel):
        g0 = cv2.cvtColor(cv2.resize(np.array(a[r0]), SMALL, interpolation=cv2.INTER_AREA),
                          cv2.COLOR_BGR2GRAY)
        g1 = cv2.cvtColor(cv2.resize(np.array(a[r2]), SMALL, interpolation=cv2.INTER_AREA),
                          cv2.COLOR_BGR2GRAY)
        f = flow.calc(g0, g1, None)
        mag = np.sqrt(f[..., 0] ** 2 + f[..., 1] ** 2)
        out[i] = (r0, r1, r2, tau, float(np.percentile(mag, 95)) * (lib.W / SMALL[0]))
    np.save(dst, out)
    lib.record("offcenter_set", dict(clip=clip, n=len(out), pool=len(cand),
                                     tau_min=round(float(out["tau"].min()), 3),
                                     tau_max=round(float(out["tau"].max()), 3),
                                     off_mean=round(float(np.abs(out["tau"] - 0.5).mean()), 3),
                                     span_p50=round(float(np.median(out["span"])), 1)))
    return out


def response(m):
    """tau を振って出力が動くか。1組で足りる。"""
    a = lib.load("C_act")
    ts = np.load(lib.RESULTS / "testset_C_act.npy")
    rec = ts[len(ts) // 2]
    f0 = vfimodels.to_gpu(np.array(a[int(rec["r0"])]))
    f1 = vfimodels.to_gpu(np.array(a[int(rec["r2"])]))
    y = {t: m.predict(f0, f1, t).float() for t in (0.0, 0.25, 0.5, 0.75, 1.0)}
    return dict(d_tau0_tau1=round(float((y[0.0] - y[1.0]).abs().max()), 4),
                d_tau025_tau075=round(float((y[0.25] - y[0.75]).abs().max()), 4),
                mae_tau025_tau075=round(float((y[0.25] - y[0.75]).abs().mean()), 4))


def gain(m, clip, key):
    """真の tau で作った物と tau=0.5 で作った物を同じ組で比べる。"""
    a = lib.load(clip)
    ts = offcenter_set(clip)
    rows = []
    for rec in ts:
        r0, r1, r2 = int(rec["r0"]), int(rec["r1"]), int(rec["r2"])
        tau = float(rec["tau"])
        gt = GM.to_gpu(np.array(a[r1]))
        g0 = vfimodels.to_gpu(np.array(a[r0]))
        g1 = vfimodels.to_gpu(np.array(a[r2]))
        yt = m.predict(g0, g1, tau)
        yh = m.predict(g0, g1, 0.5)
        rows.append((tau, float(rec["span"]),
                     V.lpips_score(yt, gt), V.lpips_score(yh, gt),
                     GM.psnr(yt, gt), GM.psnr(yh, gt)))
    r = np.array(rows, dtype=[("tau", "f4"), ("span", "f4"), ("lp_true", "f8"),
                              ("lp_half", "f8"), ("ps_true", "f8"), ("ps_half", "f8")])
    np.save(lib.RESULTS / f"tau_gain_{key}_{clip}.npy", r)
    return r


def sweep(m, clip):
    """tau を掃いて LPIPS が最小になる位置を見る。"""
    a = lib.load(clip)
    ts = offcenter_set(clip)[:N_SWEEP]
    best, true = [], []
    for rec in ts:
        r0, r1, r2 = int(rec["r0"]), int(rec["r1"]), int(rec["r2"])
        gt = GM.to_gpu(np.array(a[r1]))
        g0 = vfimodels.to_gpu(np.array(a[r0]))
        g1 = vfimodels.to_gpu(np.array(a[r2]))
        lp = [V.lpips_score(m.predict(g0, g1, t), gt) for t in SWEEP]
        best.append(SWEEP[int(np.argmin(lp))])
        true.append(float(rec["tau"]))
    best, true = np.array(best), np.array(true)
    corr = float(np.corrcoef(best, true)[0, 1]) if best.std() > 0 else 0.0
    return dict(n=len(best), corr_argmin_vs_true=round(corr, 3),
                mae_argmin=round(float(np.abs(best - true).mean()), 3),
                argmin_std=round(float(best.std()), 3),
                true_std=round(float(true.std()), 3))


def run(key, clips):
    lib.log(f"=== {key}")
    m = vfimodels.build(key, lib.W, lib.H, log=lib.log)
    name = getattr(m, "name", key)

    with lib.gpu_use("models"):
        res = response(m)
    lib.log(f"  応答: {res}")

    for clip in clips:
        with lib.gpu_use("models"):
            r = gain(m, clip, key)
        d_lp = float((r["lp_half"] - r["lp_true"]).mean())
        info = dict(key=key, model=name, clip=clip, n=len(r),
                    lpips_true_tau=round(float(r["lp_true"].mean()), 5),
                    lpips_tau_half=round(float(r["lp_half"].mean()), 5),
                    lpips_gain=round(d_lp, 5),
                    win_rate=round(float((r["lp_true"] < r["lp_half"]).mean()), 3),
                    psnr_true_tau=round(float(r["ps_true"].mean()), 3),
                    psnr_tau_half=round(float(r["ps_half"].mean()), 3),
                    **res)
        lib.record("tau_gain", info)
        lib.log(f"  {clip}: 真tau {info['lpips_true_tau']:.4f} vs "
                f"0.5固定 {info['lpips_tau_half']:.4f} "
                f"(利得 {d_lp:+.4f} / 勝率 {info['win_rate']:.2f})")

    with lib.gpu_use("models"):
        sw = sweep(m, clips[0])
    lib.record("tau_sweep", dict(key=key, model=name, clip=clips[0], **sw))
    lib.log(f"  掃引: {sw}")


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2:] or ["C_act", "A_op", "B_talk"])
