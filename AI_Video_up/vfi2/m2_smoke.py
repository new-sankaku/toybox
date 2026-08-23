"""model が本当に動くか、tau を本当に見るかを1つずつ確かめる。

1 process 1 model。`python m2_smoke.py <name>` で呼ぶ。

見る物:
  - 1080p の実 frame 2枚で predict が通るか
  - tau=0 / 0.25 / 0.5 / 0.75 / 1 の出力が互いに違うか
    (tau を無視する model は max|y(0)-y(1)| がほぼ 0 になる)
  - VRAM の山
"""
import sys
import time

import torch

import lib
import vfimodels


def main(name):
    a = lib.load("C_act")
    ts = __import__("numpy").load(lib.RESULTS / "testset_C_act.npy")
    rec = ts[len(ts) // 2]
    f0 = vfimodels.to_gpu(a[int(rec["r0"])])
    f1 = vfimodels.to_gpu(a[int(rec["r2"])])

    torch.cuda.reset_peak_memory_stats()
    t0 = time.time()
    m = vfimodels.build(name, lib.W, lib.H, log=lib.log)
    load_s = time.time() - t0

    outs = {}
    for tau in (0.0, 0.25, 0.5, 0.75, 1.0):
        t0 = time.time()
        y = m.predict(f0, f1, tau)
        torch.cuda.synchronize()
        outs[tau] = y.float()
        if tau == 0.5:
            first_ms = (time.time() - t0) * 1000
    peak = torch.cuda.max_memory_allocated() / 2 ** 30

    d01 = float((outs[0.0] - outs[1.0]).abs().max())
    d_mid = float((outs[0.25] - outs[0.75]).abs().max())
    # tau=0 の出力が f0 そのものへ寄るか(端の扱い)
    e0 = float((outs[0.0] - f0.float()).abs().mean())
    e1 = float((outs[1.0] - f1.float()).abs().mean())

    info = dict(model=getattr(m, "name", name), key=name,
                impl=getattr(m, "impl", "?"),
                load_s=round(load_s, 1), first_ms=round(first_ms, 1),
                vram_peak_gb=round(peak, 2),
                max_abs_diff_tau0_tau1=round(d01, 4),
                max_abs_diff_tau025_tau075=round(d_mid, 4),
                mae_tau0_vs_f0=round(e0, 3), mae_tau1_vs_f1=round(e1, 3),
                tau_aware=bool(d_mid > 1.0))
    lib.record("smoke", info)
    for k, v in info.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main(sys.argv[1])
