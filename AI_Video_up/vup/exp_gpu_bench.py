"""GPU推論そのものの速度を測る実験script (vup.py は触らない)

測る対象:
  - 現状 (fp16 + channels_last + cudnn.benchmark + torch.compile) の batch 1
  - batch 2/4/8/16
  - torch.compile の mode 違い (default / reduce-overhead / max-autotune)
  - 手書き CUDA Graph
  - pre/post 処理込み (pinned H2D -> uint8 D2H) と model forward 単体
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from models_registry import load_model, resolve  # noqa: E402

W, H = 720, 480


def sync():
    torch.cuda.synchronize()


def make_model(name, compile_mode=None, fullgraph=False):
    model, scale, arch = load_model(resolve(name), device="cuda", half=True)
    model = model.to(memory_format=torch.channels_last)
    if compile_mode == "default":
        model = torch.compile(model)
    elif compile_mode:
        model = torch.compile(model, mode=compile_mode, fullgraph=fullgraph)
    return model, scale, arch


def bench_forward(model, bs, iters=60, warmup=15):
    """model forward だけ。入力は既にGPU上のfp16 channels_last。"""
    x = torch.rand((bs, 3, H, W), dtype=torch.half, device="cuda").contiguous(
        memory_format=torch.channels_last)
    with torch.no_grad():
        for _ in range(warmup):
            model(x)
        sync()
        t0 = time.perf_counter()
        for _ in range(iters):
            model(x)
        sync()
        el = time.perf_counter() - t0
    return bs * iters / el


def bench_fullpath(model, bs, scale, iters=60, warmup=15):
    """vup.run_into と同じ経路: pinned uint8 HWC -> GPU -> model -> uint8 -> pinned"""
    src = [torch.randint(0, 255, (H, W, 3), dtype=torch.uint8).pin_memory()
           for _ in range(bs)]
    dst = torch.empty((bs, H * scale, W * scale, 3), dtype=torch.uint8,
                      device="cpu", pin_memory=True)

    def one():
        with torch.no_grad():
            if bs == 1:
                x = src[0].to("cuda", non_blocking=True)
                x = x.permute(2, 0, 1).unsqueeze(0).to(torch.half).div_(255.0)
            else:
                x = torch.stack([s.to("cuda", non_blocking=True) for s in src])
                x = x.permute(0, 3, 1, 2).to(torch.half).div_(255.0)
            x = x.contiguous(memory_format=torch.channels_last)
            y = model(x).clamp_(0, 1)
            y = y.mul_(255.0).round_().to(torch.uint8)
            y = y.permute(0, 2, 3, 1).contiguous()
            dst.copy_(y, non_blocking=True)
            ev = torch.cuda.Event()
            ev.record()
            return ev

    for _ in range(warmup):
        one().synchronize()
    sync()
    t0 = time.perf_counter()
    evs = []
    for _ in range(iters):
        evs.append(one())
        if len(evs) > 2:
            evs.pop(0).synchronize()
    for e in evs:
        e.synchronize()
    el = time.perf_counter() - t0
    return bs * iters / el


def vram():
    return torch.cuda.max_memory_allocated() / 2**20


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="sd")
    ap.add_argument("--batches", default="1,2,4,8")
    ap.add_argument("--modes", default="none,default")
    ap.add_argument("--iters", type=int, default=60)
    ap.add_argument("--full", action="store_true", help="pre/post込みも測る")
    args = ap.parse_args()

    torch.backends.cudnn.benchmark = True
    batches = [int(b) for b in args.batches.split(",")]
    modes = args.modes.split(",")

    print(f"model={args.model}  {W}x{H}  torch={torch.__version__}")
    print(f"{'mode':18s} {'bs':>3s} {'fwd fps':>10s} {'full fps':>10s} {'VRAM MB':>9s}")
    for mode in modes:
        cm = None if mode == "none" else mode
        for bs in batches:
            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats()
            try:
                model, scale, arch = make_model(args.model, cm)
                f = bench_forward(model, bs, iters=args.iters)
                g = bench_fullpath(model, bs, scale, iters=args.iters) if args.full else 0.0
                print(f"{mode:18s} {bs:3d} {f:10.1f} {g:10.1f} {vram():9.0f}")
            except Exception as exc:
                print(f"{mode:18s} {bs:3d}  失敗: {type(exc).__name__}: {str(exc)[:120]}")
            finally:
                del model
                torch.cuda.empty_cache()


if __name__ == "__main__":
    main()
