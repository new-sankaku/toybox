"""1 process = 1 設定 だけを測る。dynamo の recompile_limit 汚染を避けるため。

この機体は他の処理(TicTokのSTT worker/ffmpeg)がGPUを間欠的に使う。
平均を取ると混み具合を測ってしまうので、短いburstを何度も回して
「最も速かったburst」を採る。競合が無かった瞬間の実力が出る。

使い方: exp_gpu_one.py --mode max-autotune --bs 2
"""
import argparse
import sys
import time
from pathlib import Path

import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from models_registry import load_model, resolve  # noqa: E402

W, H = 720, 480
# SRVGGNetCompact(64feat/16conv) の積和。fps -> TFLOPS 換算用
FLOP_PER_FRAME = 720 * 480 * (16 * 64 * 64 * 9 + 3 * 64 * 9 + 64 * 12 * 9) * 2


def best_of(run, bs, bursts=15, iters=20):
    times = []
    for _ in range(bursts):
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        for _ in range(iters):
            run()
        torch.cuda.synchronize()
        times.append((time.perf_counter() - t0) / iters)
    times.sort()
    return bs / times[0], bs / times[len(times) // 2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="sd")
    ap.add_argument("--mode", default="none")
    ap.add_argument("--bs", type=int, default=1)
    ap.add_argument("--bursts", type=int, default=15)
    ap.add_argument("--iters", type=int, default=20)
    ap.add_argument("--cudagraph", action="store_true")
    ap.add_argument("--no-channels-last", action="store_true")
    args = ap.parse_args()

    torch.backends.cudnn.benchmark = True
    model, scale, arch = load_model(resolve(args.model), device="cuda", half=True)
    if not args.no_channels_last:
        model = model.to(memory_format=torch.channels_last)
    if args.mode == "default":
        model = torch.compile(model)
    elif args.mode != "none":
        model = torch.compile(model, mode=args.mode)

    bs = args.bs
    x = torch.rand((bs, 3, H, W), dtype=torch.half, device="cuda")
    if not args.no_channels_last:
        x = x.contiguous(memory_format=torch.channels_last)

    torch.cuda.reset_peak_memory_stats()
    with torch.no_grad():
        for _ in range(25):
            model(x)
        torch.cuda.synchronize()

        if args.cudagraph:
            s = torch.cuda.Stream()
            s.wait_stream(torch.cuda.current_stream())
            with torch.cuda.stream(s):
                for _ in range(5):
                    model(x)
            torch.cuda.current_stream().wait_stream(s)
            g = torch.cuda.CUDAGraph()
            with torch.cuda.graph(g):
                model(x)
            run = g.replay
        else:
            def run():
                model(x)

        for _ in range(10):
            run()
        best, med = best_of(run, bs, args.bursts, args.iters)

    peak = torch.cuda.max_memory_allocated() / 2**20
    tag = args.mode + ("+graph" if args.cudagraph else "")
    tflops = best * FLOP_PER_FRAME / 1e12
    print(f"{args.model:8s} {tag:16s} bs={bs:<2d} best {best:7.1f} fps  "
          f"med {med:7.1f} fps  {tflops:5.1f} TFLOPS  VRAM {peak:6.0f} MB")


if __name__ == "__main__":
    main()
