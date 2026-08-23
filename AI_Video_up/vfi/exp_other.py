"""RIFE 以外の対照をまとめて測る。RIFE と同じ試験集合・同じ metric。

**いずれも TensorRT には載せていません**(torch fp16 autocast)。
RIFE 側の TensorRT 値より不利な条件です。桁が違うかどうかを見ます。
"""
import sys
import time

import numpy as np
import torch

import a3_bench as B
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
        m.predict(g0, g1, 0.5)
    torch.cuda.synchronize()
    return (time.time() - t0) / iters * 1000


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


def run(m):
    ms = bench_speed(m)
    V.log(f"  {m.name}: {ms:.1f}ms ({1000/ms:.1f} 枚/秒)")
    V.record("speed_other", dict(model=m.name, impl="torch fp16 autocast",
                                 w=V.W, h=V.H, gpu_ms=round(ms, 2),
                                 gpu_fps=round(1000 / ms, 2), reuse_ms=None))
    for clip in V.CLIPS:
        arr = quality(m, clip)
        np.save(V.RESULTS / f"q_{m.name}_{clip}.npy", arr)
        s = B.summarise(arr)
        V.record("quality", dict(model=m.name, clip=clip, prec="fp16", **s))
        V.log(f"  {clip}: PSNR {s['psnr']:.2f}  LPIPS {s['lpips']:.4f} "
              f"(小 {s.get('lpips_t0')} 中 {s.get('lpips_t1')} "
              f"大 {s.get('lpips_t2')})  GMSD {s['gmsd']:.4f}")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "ifrnet"
    if which == "ifrnet":
        import ifrnetlib as I
        run(I.Ifrnet(V.W, V.H, fp16=True))
    elif which == "gmfss":
        import gmfsslib as G
        run(G.Gmfss(V.W, V.H, fp16=True))
