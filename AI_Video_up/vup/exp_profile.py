"""kernel別の内訳を出す。conv と PReLU のどちらに時間が乗っているかを見る。"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path

import torch
from torch.profiler import ProfilerActivity, profile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from models_registry import load_model, resolve  # noqa: E402

W, H = 720, 480


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="sd")
    ap.add_argument("--mode", default="none")
    ap.add_argument("--bs", type=int, default=1)
    args = ap.parse_args()

    torch.backends.cudnn.benchmark = True
    model, scale, arch = load_model(resolve(args.model), device="cuda", half=True)
    model = model.to(memory_format=torch.channels_last)
    if args.mode == "default":
        model = torch.compile(model)
    elif args.mode != "none":
        model = torch.compile(model, mode=args.mode)

    x = torch.rand((args.bs, 3, H, W), dtype=torch.half, device="cuda").contiguous(
        memory_format=torch.channels_last)
    with torch.no_grad():
        for _ in range(30):
            model(x)
        torch.cuda.synchronize()
        with profile(activities=[ProfilerActivity.CUDA]) as prof:
            for _ in range(20):
                model(x)
            torch.cuda.synchronize()

    agg = defaultdict(lambda: [0.0, 0])
    for e in prof.key_averages():
        if e.self_device_time_total > 0:
            agg[e.key][0] += e.self_device_time_total / 1000.0 / 20
            agg[e.key][1] += e.count // 20
    total = sum(v[0] for v in agg.values())
    print(f"{args.model} {args.mode} bs={args.bs}  GPU計 {total:.2f} ms/iter"
          f"  = {args.bs / (total/1000):.1f} fps")
    for k, (ms, n) in sorted(agg.items(), key=lambda kv: -kv[1][0])[:14]:
        print(f"  {ms:7.3f} ms ({ms/total*100:5.1f}%) x{n:3d}  {k[:88]}")


if __name__ == "__main__":
    main()
