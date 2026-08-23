"""torch.compile と TensorRT の頭合わせ比較。

競合下でも公平になるよう、A と B を交互に短く測って各々の最速burstを採る。
出力一致も同じ入力で確認する。
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np
import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from models_registry import load_model, resolve  # noqa: E402
from exp_trt import TrtRunner, build_engine, export_onnx  # noqa: E402

W, H = 720, 480
FLOP_PER_FRAME = W * H * (16 * 64 * 64 * 9 + 3 * 64 * 9 + 64 * 12 * 9) * 2


def make_torch(name, bs, mode="default", graph=True):
    torch.backends.cudnn.benchmark = True
    model, scale, _ = load_model(resolve(name), device="cuda", half=True)
    model = model.to(memory_format=torch.channels_last)
    if mode != "none":
        model = torch.compile(model) if mode == "default" else \
            torch.compile(model, mode=mode)
    x = torch.rand((bs, 3, H, W), dtype=torch.half, device="cuda").contiguous(
        memory_format=torch.channels_last)
    with torch.no_grad():
        for _ in range(25):
            out = model(x)
        torch.cuda.synchronize()
        if graph:
            s = torch.cuda.Stream()
            s.wait_stream(torch.cuda.current_stream())
            with torch.cuda.stream(s):
                for _ in range(5):
                    model(x)
            torch.cuda.current_stream().wait_stream(s)
            g = torch.cuda.CUDAGraph()
            with torch.cuda.graph(g):
                out = model(x)

            def run():
                g.replay()
            return run, x, out
    return (lambda: model(x)), x, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="sd")
    ap.add_argument("--bs", type=int, default=1)
    ap.add_argument("--mode", default="default")
    ap.add_argument("--no-graph", action="store_true")
    ap.add_argument("--bursts", type=int, default=25)
    ap.add_argument("--iters", type=int, default=20)
    args = ap.parse_args()
    bs = args.bs

    trun, tx, tout = make_torch(args.model, bs, args.mode, not args.no_graph)
    onnx = export_onnx(args.model, bs, half=True)
    eng = build_engine(onnx, "fp16", bs)
    trt = TrtRunner(eng)
    tin, tname_out = trt.inp[0], trt.out[0]

    # --- 出力一致: 同じ入力を両方へ ---
    x_nchw = tx.contiguous()                       # NCHW fp16
    with torch.no_grad():
        y_torch = tout.float()
    y_trt = trt(x_nchw).float().clone()
    # torch側のgraph出力は最後のreplay結果。同じ入力で再実行して揃える
    trun()
    torch.cuda.synchronize()
    y_torch = tout.float()
    d = (y_torch.clamp(0, 1) - y_trt.clamp(0, 1)).abs() * 255
    print(f"出力一致 (uint8換算): max {d.max().item():.2f}/255  "
          f"mean {d.mean().item():.4f}  shape {tuple(y_trt.shape)}")

    # --- 交互に測る ---
    def burst(fn):
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        for _ in range(args.iters):
            fn()
        torch.cuda.synchronize()
        return (time.perf_counter() - t0) / args.iters

    def trt_run():
        trt.ctx.execute_async_v3(trt.stream.cuda_stream)

    for _ in range(10):
        trun(); trt_run()
    torch.cuda.synchronize()

    ta, tb = [], []
    for _ in range(args.bursts):
        ta.append(burst(trun))
        tb.append(burst(trt_run))
    ta.sort(); tb.sort()
    for tag, t in (("torch " + args.mode + ("" if args.no_graph else "+graph"), ta),
                   ("TensorRT fp16", tb)):
        best, med = bs / t[0], bs / t[len(t) // 2]
        print(f"  {tag:24s} bs={bs:<2d} best {best:7.1f} fps  med {med:7.1f} fps"
              f"  {best*FLOP_PER_FRAME/1e12:5.1f} TFLOPS")
    print(f"  → TensorRT / torch = {(ta[0]/tb[0]):.2f}x (best同士)")


if __name__ == "__main__":
    main()
