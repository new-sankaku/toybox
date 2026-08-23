"""SR を frame 単位で束ねると速くなるか。

720x480 は 4070 Ti には小さく、batch 1 では GPU が埋まりきらない可能性がある。
dedup は「SRすべき frame」を連続で吐くので、束ねること自体は自然にできる。
束ねると先読みが必要になり遅延も増えるので、実測で元が取れるかを見る。
"""
import sys
import time
from pathlib import Path

import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from models_registry import load_model, resolve  # noqa: E402

W, H = 720, 480


def bench(model, bs, scale, out_scale, n=40, warm=8):
    x = torch.rand(bs, 3, H, W, device="cuda", dtype=torch.half)
    x = x.contiguous(memory_format=torch.channels_last)
    down = scale // out_scale if out_scale and scale % out_scale == 0 else 1
    with torch.no_grad():
        for _ in range(warm):
            y = model(x).clamp_(0, 1)
            if down > 1:
                y = torch.nn.functional.avg_pool2d(y, down)
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        for _ in range(n):
            y = model(x).clamp_(0, 1)
            if down > 1:
                y = torch.nn.functional.avg_pool2d(y, down)
        torch.cuda.synchronize()
        el = time.perf_counter() - t0
    return bs * n / el


def main():
    torch.backends.cudnn.benchmark = True
    name = sys.argv[1] if len(sys.argv) > 1 else "anime"
    use_compile = "--no-compile" not in sys.argv
    model, scale, arch = load_model(resolve(name), device="cuda", half=True)
    model = model.to(memory_format=torch.channels_last)
    tag = "eager"
    if use_compile:
        try:
            import triton  # noqa: F401
            model = torch.compile(model, dynamic=False)
            tag = "compile"
        except Exception as exc:
            print(f"compile 不可 ({type(exc).__name__})")
    print(f"{arch} x{scale}  {tag}  入力 {W}x{H}")
    print(f"{'batch':>6s} {'fps':>9s} {'batch1比':>9s} {'VRAM MB':>9s}")
    base = None
    for bs in (1, 2, 3, 4, 6, 8):
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        try:
            fps = bench(model, bs, scale, 2)
        except torch.cuda.OutOfMemoryError:
            print(f"{bs:6d}   VRAM不足")
            break
        base = base or fps
        mem = torch.cuda.max_memory_allocated() / 2 ** 20
        print(f"{bs:6d} {fps:9.1f} {fps / base:8.2f}x {mem:9.0f}")


if __name__ == "__main__":
    main()
