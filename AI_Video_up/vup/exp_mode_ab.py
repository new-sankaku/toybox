"""vup.py の FusedSR で compile mode を交互に測る。

sequential に測ると、他processの負荷が乗った側だけ遅く出る。
default と reduce-overhead を同一process内で交互に回して比べる。
"""
import sys
import time
from pathlib import Path

import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, r"C:\Users\sanka\AppData\Local\Temp\claude"
                   r"\C--01-work-00-Git-toybox-AI-Video-up"
                   r"\a69516b7-fb23-4024-ad85-73e2610bad30\scratchpad")
from gpulock import gpu_lock  # noqa: E402
from srlib import H, W  # noqa: E402
from models_registry import resolve  # noqa: E402

CALLS = 120


def build(mode):
    import vup
    _orig = torch.compile
    if mode != "default":
        def _patched(m=None, **kw):
            kw.setdefault("mode", mode)
            return _orig(m, **kw)
        torch.compile = _patched
    try:
        base = vup.TorchSR(resolve("sd"), half=True, out_scale=None,
                           compile_model=True)
        base.nv12 = True
        return vup.FusedSR(base), base.out_scale
    finally:
        torch.compile = _orig


def main():
    torch._dynamo.config.recompile_limit = 64
    runners = {}
    for mode in ("default", "reduce-overhead"):
        runners[mode] = build(mode)
    scale = runners["default"][1]
    fw, fh = W * scale, H * scale
    src = torch.randint(0, 255, (H, W, 3), dtype=torch.uint8).pin_memory()
    dst = [torch.empty((fh * 3 // 2, fw), dtype=torch.uint8, pin_memory=True)
           for _ in range(6)]

    def burst(backend, n=CALLS):
        inflight = []
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        for i in range(n):
            inflight.append(backend.run_into(src, dst[i % 6]))
            if len(inflight) > 2:
                inflight.pop(0).synchronize()
        for e in inflight:
            e.synchronize()
        return time.perf_counter() - t0

    for m in runners:
        burst(runners[m][0], 40)
    res = {m: [] for m in runners}
    for _ in range(10):
        for m in runners:
            res[m].append(burst(runners[m][0]))
    out = {}
    for m, v in res.items():
        v.sort()
        out[m] = CALLS / v[0]
        print(f"  FusedSR {m:16s} best {CALLS/v[0]:7.1f} fps  "
              f"med {CALLS/v[len(v)//2]:7.1f} fps")
    print(f"  → reduce-overhead / default = "
          f"{out['reduce-overhead']/out['default']:.2f}x")


if __name__ == "__main__":
    with gpu_lock("gpu-inference", "FusedSR compile mode 交互測定"):
        main()
