"""GMFSS_Fortuna(RIFE以外の対照)の速度と品質。RIFE と同じ試験集合で測る。

**TensorRT には載せていません**(GMFlow を ONNX へ出すのに手が要るため)。
torch fp16 autocast の値なので、RIFE 側(TensorRT)より不利な条件です。
それでも桁が違えば結論は動きません。
"""
import time

import numpy as np
import torch

import a3_bench as B
import gmfsslib as G
import rifelib as R
import vfilib as V


def bench_speed(m, iters=20, warm=5):
    a = V.load("B_talk")
    g0, g1 = R.to_gpu(a[100]), R.to_gpu(a[101])
    for _ in range(warm):
        m.predict(g0, g1, 0.5)
    torch.cuda.synchronize()
    t0 = time.time()
    for _ in range(iters):
        m.predict(g0, g1, 0.5)          # pair ごとに flow から測る(x2 と同じ)
    torch.cuda.synchronize()
    per = (time.time() - t0) / iters * 1000
    # flow を使い回す場合(1 pair から複数枚作る時)
    m.predict(g0, g1, 0.5, key=99)
    torch.cuda.synchronize()
    t0 = time.time()
    for _ in range(iters):
        m.predict(g0, g1, 0.5, key=99)
    torch.cuda.synchronize()
    reuse = (time.time() - t0) / iters * 1000
    return per, reuse


def quality(m, clip):
    a = V.load(clip)
    ts = np.load(V.RESULTS / f"testset_{clip}.npy")
    rows = []
    for rec in ts:
        r0, r1, r2, tau = (int(rec["r0"]), int(rec["r1"]), int(rec["r2"]),
                           float(rec["tau"]))
        gt = a[r1]
        y = m.predict(R.to_gpu(a[r0]), R.to_gpu(a[r2]), tau).cpu().numpy()
        rows.append((r1, int(rec["tier"]), float(rec["mv"]),
                     V.psnr(y, gt), V.lpips_score(y, gt), V.gmsd(y, gt),
                     V.bad_pixels(y, gt)))
    return np.array(rows, dtype=B.QDTYPE)


if __name__ == "__main__":
    m = G.Gmfss(V.W, V.H, fp16=True)
    per, reuse = bench_speed(m)
    V.log(f"  速度: pairごと {per:.1f}ms ({1000/per:.1f} fps)  "
          f"flow使い回し {reuse:.1f}ms ({1000/reuse:.1f} fps)")
    V.record("speed_other", dict(model=m.name, impl="torch fp16 autocast",
                                 w=V.W, h=V.H, gpu_ms=round(per, 2),
                                 gpu_fps=round(1000 / per, 2),
                                 reuse_ms=round(reuse, 2)))
    for clip in V.CLIPS:
        arr = quality(m, clip)
        np.save(V.RESULTS / f"q_{m.name}_{clip}.npy", arr)
        s = B.summarise(arr)
        V.record("quality", dict(model=m.name, clip=clip, prec="fp16", **s))
        V.log(f"  {clip}: PSNR {s['psnr']:.2f}  LPIPS {s['lpips']:.4f} "
              f"(小 {s.get('lpips_t0')} 中 {s.get('lpips_t1')} "
              f"大 {s.get('lpips_t2')})  GMSD {s['gmsd']:.4f}")
