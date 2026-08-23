"""実pipelineの中で SR が占める割合を測る。

vup.py の FusedSR (前後処理fuse + nv12) をそのまま使い、
実pipelineと同じ形 (pinned uint8 HWC in / pinned nv12 out, event深さ2) で
N回まわして純粋なSR時間を出す。これを実行時間と突き合わせれば、
「SRを2倍にしたら全体がどれだけ縮むか」が計算できる。
"""
import argparse
import sys
import time
from pathlib import Path

import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import vup  # noqa: E402
from models_registry import resolve  # noqa: E402

W, H = 720, 480


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="sd")
    ap.add_argument("--calls", type=int, default=400)
    ap.add_argument("--bursts", type=int, default=8)
    ap.add_argument("--no-fuse", action="store_true")
    ap.add_argument("--compile-mode", default="default")
    args = ap.parse_args()

    if args.compile_mode != "default":
        # vup.py を書き換えずに compile mode だけ差し替える
        _orig = torch.compile

        def _patched(m=None, **kw):
            kw.setdefault("mode", args.compile_mode)
            return _orig(m, **kw)
        torch.compile = _patched
        vup.torch = torch

    base = vup.TorchSR(resolve(args.model), half=True, out_scale=None,
                       compile_model=True)
    base.nv12 = True
    backend = base if args.no_fuse else vup.FusedSR(base)
    print("backend:", backend.name)

    scale = base.out_scale
    fw, fh = W * scale, H * scale
    src = torch.randint(0, 255, (H, W, 3), dtype=torch.uint8).pin_memory()
    nout = 6
    dst = [torch.empty((fh * 3 // 2, fw), dtype=torch.uint8,
                       pin_memory=True) for _ in range(nout)]

    def burst(n):
        inflight = []
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        for i in range(n):
            ev = backend.run_into(src, dst[i % nout])
            inflight.append(ev)
            if len(inflight) > 2:
                inflight.pop(0).synchronize()
        for e in inflight:
            e.synchronize()
        return time.perf_counter() - t0

    burst(40)
    ts = sorted(burst(args.calls) for _ in range(args.bursts))
    best, med = ts[0], ts[len(ts) // 2]
    print(f"SR {args.calls}回: best {best:.2f}s ({args.calls/best:.1f} fps)"
          f"  med {med:.2f}s ({args.calls/med:.1f} fps)")
    print(f"  1回あたり best {best/args.calls*1000:.2f} ms")


if __name__ == "__main__":
    sys.path.insert(0, r"C:\Users\sanka\AppData\Local\Temp\claude"
                       r"\C--01-work-00-Git-toybox-AI-Video-up"
                       r"\a69516b7-fb23-4024-ad85-73e2610bad30\scratchpad")
    from gpulock import gpu_lock
    with gpu_lock("gpu-inference", "FusedSR compile mode 比較"):
        main()
