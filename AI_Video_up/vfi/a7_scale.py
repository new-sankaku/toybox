"""解像度と batch で速度がどう動くか。設計の分岐がここで決まる。

- **解像度**: SR と組み合わせる時、補間を SR の前(1920x1080)でやるか
  後(3840x2160)でやるかは、ここの比で決まる
- **batch**: vup の SR は TensorRT bs2 で1.8倍になった。RIFE は 1080p で
  1枚あたりの計算量が桁違いに大きいので、同じ事が起きるとは限らない
"""
import sys

import numpy as np
import torch

import a3_bench as B
import rifelib as R
import vfilib as V

MODEL = sys.argv[1] if len(sys.argv) > 1 else "v4.25_lite"
SIZES = [(960, 540), (1280, 720), (1920, 1080), (2560, 1440), (3840, 2160)]
BATCHES = [1, 2]


def bench_bs(m, iters=40, warm=10):
    f = torch.randint(0, 255, (m.bs, 7, m.h, m.w), dtype=m.dtype, device="cuda")
    m.dev_in.copy_(f)
    for _ in range(warm):
        m.infer()
    torch.cuda.synchronize()
    e0 = [torch.cuda.Event(enable_timing=True) for _ in range(iters)]
    e1 = [torch.cuda.Event(enable_timing=True) for _ in range(iters)]
    for k in range(iters):
        e0[k].record()
        m.infer()
        e1[k].record()
    torch.cuda.synchronize()
    ms = float(np.median([a.elapsed_time(b) for a, b in zip(e0, e1)]))
    del f
    return ms / m.bs


def run(model=MODEL):
    done = {(r["model"], r["w"], r["h"], r["bs"])
            for r in V.read_records("scale") if "error" not in r}
    for w, h in SIZES:
        for bs in BATCHES:
            if (model, w, h, bs) in done:
                continue
            if bs > 1 and (w, h) in ((2560, 1440), (3840, 2160)):
                continue                       # VRAM が足りない
            try:
                m = R.Rife(model, w, h, bs=bs, fp16=True)
                ms = bench_bs(m)
            except Exception as exc:
                V.record("scale", dict(model=model, w=w, h=h, bs=bs,
                                       error=str(exc)[:300]))
                V.log(f"  {w}x{h} bs{bs}: 失敗 {str(exc)[:120]}")
                torch.cuda.empty_cache()
                continue
            mpx = w * h / 1e6
            V.record("scale", dict(model=model, w=w, h=h, bs=bs,
                                   ms_per_frame=round(ms, 3),
                                   fps=round(1000 / ms, 1),
                                   ms_per_mpx=round(ms / mpx, 3)))
            V.log(f"  {w}x{h} bs{bs}: {ms:.2f}ms/枚 ({1000/ms:.1f} fps)  "
                  f"{ms/mpx:.2f}ms/Mpx")
            del m
            torch.cuda.empty_cache()


if __name__ == "__main__":
    V.log(f"=== 解像度とbatch {MODEL}")
    run()
