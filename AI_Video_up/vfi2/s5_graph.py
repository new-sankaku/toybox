"""CUDA Graph で kernel 起動の overhead を落とせるか。

RIFE は層が細かいので、1回の推論で数百の kernel を起動する。
1080p で 5.3ms のうち起動の CPU 費用が何割かを見る。

graph に載せる範囲は「pack → TensorRT → unpack → nv12 → D2H」の全部。
buffer は全部固定 address にする必要があるので、入力 frame も固定 slot へ
copy してから graph を再生する形にする。

TensorRT の enqueue を capture するには、同じ stream で1回 warmup してから
capture に入る必要がある(内部の遅延確保を済ませておく)。
"""
import sys

import numpy as np
import torch
import torch.nn.functional as F

import lib
import sgpu
import rifelib as R
from s1_profile import nv12

W, H = lib.W, lib.H


def build_step(m):
    """固定 buffer だけを触る1 frame ぶんの処理。"""
    f0 = torch.zeros((H, W, 3), dtype=torch.uint8, device="cuda")
    f1 = torch.zeros((H, W, 3), dtype=torch.uint8, device="cuda")
    tau = torch.zeros((), dtype=torch.float32, device="cuda")
    pin = torch.empty((H * 3 // 2, W), dtype=torch.uint8, pin_memory=True)

    def step():
        m.dev_in[0, 0:3] = f0.permute(2, 0, 1).flip(0).to(m.dtype).div_(255.0)
        m.dev_in[0, 3:6] = f1.permute(2, 0, 1).flip(0).to(m.dtype).div_(255.0)
        m.dev_in[0, 6] = tau
        y = m.infer()
        pin.copy_(nv12(R.unpack(y)), non_blocking=True)

    return step, (f0, f1, tau, pin)


def timed(fn, iters=40, warm=10):
    for _ in range(warm):
        fn()
    torch.cuda.synchronize()
    e0 = [torch.cuda.Event(enable_timing=True) for _ in range(iters)]
    e1 = [torch.cuda.Event(enable_timing=True) for _ in range(iters)]
    for k in range(iters):
        e0[k].record()
        fn()
        e1[k].record()
    torch.cuda.synchronize()
    # 他 process の干渉は必ず「遅くする」向きにしか働かない。median だと
    # 干渉が値へ残るので min を採る。
    return float(min(a.elapsed_time(b) for a, b in zip(e0, e1)))


def wall(fn, iters=40, warm=10):
    """CPU 側の投入費用込み。GPU が空いていれば起動 overhead がここに出る。"""
    import time
    for _ in range(warm):
        fn()
    torch.cuda.synchronize()
    t0 = time.time()
    for _ in range(iters):
        fn()
    torch.cuda.synchronize()
    return (time.time() - t0) * 1000 / iters


def run(model="v4.6"):
    m = R.Rife(model, W, H, bs=1, fp16=True)
    step, _bufs = build_step(m)

    with sgpu.measuring() as env:
        eager_gpu = timed(step)
        eager_wall = wall(step)

        # capture は専用 stream で行う
        s = torch.cuda.Stream()
        s.wait_stream(torch.cuda.current_stream())
        with torch.cuda.stream(s):
            for _ in range(3):
                step()
        torch.cuda.current_stream().wait_stream(s)
        torch.cuda.synchronize()

        g = torch.cuda.CUDAGraph()
        try:
            with torch.cuda.graph(g):
                step()
            graph_gpu = timed(g.replay)
            graph_wall = wall(g.replay)
            err = None
        except Exception as exc:
            graph_gpu = graph_wall = None
            err = str(exc)[:300]

    r = dict(model=model, w=W, h=H,
             eager_gpu_ms=round(eager_gpu, 3), eager_wall_ms=round(eager_wall, 3),
             graph_gpu_ms=None if graph_gpu is None else round(graph_gpu, 3),
             graph_wall_ms=None if graph_wall is None else round(graph_wall, 3),
             speedup=None if graph_gpu is None else round(eager_gpu / graph_gpu, 3),
             error=err, **env)
    lib.record("cudagraph", r)
    lib.log(f"  {r}")
    return r


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "v4.6")
