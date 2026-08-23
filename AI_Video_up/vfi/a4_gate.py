"""補間を「呼ばない」判定の実測。速度の話の本体。

x2(24->48fps)の出力 2N frame のうち、偶数番は source frame そのままで model は
要らない。奇数番だけが補間で、その中にも呼ばずに済む物がある。

  (a) 前後が同じ絵   -> 前の frame を写すだけで厳密に正しい
  (b) cut を跨ぐ     -> 補間してはいけない。hold が正解

問題は (a) の閾値をどこに置くかで、**節約と誤差の両方を実測する**。
誤差は「model を呼んだ場合の絵」と「写した絵」の差で測る。本物の中間frameは
存在しないので、model の出力を基準にするのが唯一の筋。
"""
import sys

import numpy as np
import torch

import rifelib as R
import vfilib as V

THRESHOLDS = (0, 4, 8, 12, 16, 20, 24, 32, 48)
MODEL = "v4.25_lite"
SAMPLE = 90          # 閾値ごとに実際に model を回して差を測る組数


def run(clip, model=MODEL, seed=0):
    a = V.load(clip)
    scd = np.load(V.RESULTS / f"scd_{clip}.npy")
    n = len(a)

    box4 = np.array([V.box4_max(a[i], a[i + 1]) for i in range(n - 1)])
    is_cut = scd[:n - 1] >= 10.0

    # x2 の出力: 偶数番は source そのまま。奇数番 (n-1個) が補間の対象
    n_out = 2 * n - 1
    rows = []
    for t in THRESHOLDS:
        skip_static = int(((box4 < t) & ~is_cut).sum())
        calls = int((~is_cut & (box4 >= t)).sum())
        rows.append(dict(thresh=int(t), calls=calls,
                         skip_static=skip_static, skip_cut=int(is_cut.sum()),
                         call_pct_of_out=round(calls / n_out * 100, 1),
                         speedup_vs_nogate=round((n - 1 - is_cut.sum())
                                                 / max(calls, 1), 3)))
    V.record("gate_count", dict(clip=clip, frames=n, out_frames=n_out,
                                cuts=int(is_cut.sum()), rows=rows))
    print(f"  {clip}: 出力{n_out} frame / 補間対象 {n-1}")
    for r in rows:
        print(f"    閾値{r['thresh']:3d}: 呼ぶ {r['calls']:4d} "
              f"(出力の{r['call_pct_of_out']:4.1f}%)  "
              f"静止で省く {r['skip_static']:4d}  "
              f"呼ばない場合比 {r['speedup_vs_nogate']:.2f}倍")

    # 省いた組で、model を呼んだ絵と写した絵がどれだけ違うか
    m = R.Rife(model, V.W, V.H, fp16=True)
    rng = np.random.default_rng(seed)
    err_rows = []
    for t in THRESHOLDS[1:]:
        idx = np.where((box4 < t) & ~is_cut)[0]
        if len(idx) == 0:
            continue
        take = idx if len(idx) <= SAMPLE else rng.choice(idx, SAMPLE, replace=False)
        d_box4, d_bad, d_psnr = [], [], []
        for i in sorted(int(x) for x in take):
            R.pack(R.to_gpu(a[i]), R.to_gpu(a[i + 1]), 0.5, m.dtype, out=m.dev_in)
            y = R.unpack(m.infer()).cpu().numpy()
            copy = a[i]
            d_box4.append(V.box4_max(y, copy))
            d_bad.append(V.bad_pixels(y, copy))
            d_psnr.append(V.psnr(y, copy))
        e = dict(clip=clip, model=model, thresh=int(t), n=len(d_box4),
                 box4_med=int(np.median(d_box4)), box4_max=int(np.max(d_box4)),
                 bad_med=int(np.median(d_bad)), bad_max=int(np.max(d_bad)),
                 psnr_med=round(float(np.median(d_psnr)), 2),
                 psnr_min=round(float(np.min(d_psnr)), 2))
        err_rows.append(e)
        V.record("gate_error", e)
        print(f"    閾値{t:3d}: 省いた{len(d_box4)}組で model出力との差 "
              f"box4 中央{e['box4_med']}/最大{e['box4_max']}  "
              f"|d|>48画素 中央{e['bad_med']}/最大{e['bad_max']}  "
              f"PSNR 最小{e['psnr_min']}")
    del m
    torch.cuda.empty_cache()
    return rows, err_rows


if __name__ == "__main__":
    for c in (sys.argv[1:] or list(V.CLIPS)):
        V.log(f"=== {c}")
        run(c)
