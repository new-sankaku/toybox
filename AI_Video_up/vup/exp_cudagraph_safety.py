"""reduce-overhead (CUDA Graphs) を vup.py の depth-2 投入と併用して壊れないか確かめる。

vup.py の sr_worker は SR を2件投入しっぱなしにしてから event を待つ。
CUDA Graph の出力は使い回しの static buffer なので、2件目の replay が
1件目の D2H copy より先に出力を上書きすると結果が壊れる。
速度だけ見て採用すると気づけないので、出力そのものを照合する。
"""
import sys
from pathlib import Path

import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, r"C:\Users\sanka\AppData\Local\Temp\claude"
                   r"\C--01-work-00-Git-toybox-AI-Video-up"
                   r"\a69516b7-fb23-4024-ad85-73e2610bad30\scratchpad")
from gpulock import gpu_lock  # noqa: E402
from srlib import H, W, grab_frames  # noqa: E402
from models_registry import load_model, resolve  # noqa: E402


def run(mode, depth):
    model, _, _ = load_model(resolve("sd"), device="cuda", half=True)
    model = model.to(memory_format=torch.channels_last)
    torch.backends.cudnn.benchmark = True
    compiled = torch.compile(model) if mode == "default" else \
        torch.compile(model, mode=mode)

    fr = grab_frames(HERE.parent / "サンプル.mp4", 8, step=53)
    srcs = [torch.from_numpy(f.copy()).pin_memory() for f in fr]
    dsts = [torch.empty((H * 2, W * 2, 3), dtype=torch.uint8,
                        pin_memory=True) for _ in fr]

    def one(i):
        with torch.no_grad():
            x = srcs[i].cuda(non_blocking=True)
            x = x.permute(2, 0, 1).unsqueeze(0).half().div_(255.0)
            x = x.contiguous(memory_format=torch.channels_last)
            y = compiled(x).clamp_(0, 1).mul_(255.0).round_().to(torch.uint8)
            y = y.squeeze(0).permute(1, 2, 0).contiguous()
            dsts[i].copy_(y, non_blocking=True)
            ev = torch.cuda.Event()
            ev.record()
            return ev

    # 基準: 1件ずつ完全に待つ
    ref = []
    for i in range(len(fr)):
        one(i).synchronize()
        ref.append(dsts[i].clone())
    for d in dsts:
        d.zero_()
    # 検証: depth 件を投入しっぱなしにする (vup.py と同じ)
    inflight = []
    for i in range(len(fr)):
        inflight.append(one(i))
        if len(inflight) > depth - 1:
            inflight.pop(0).synchronize()
    for e in inflight:
        e.synchronize()

    bad = [i for i in range(len(fr)) if not torch.equal(ref[i], dsts[i])]
    diff = max((ref[i].int() - dsts[i].int()).abs().max().item()
               for i in range(len(fr)))
    print(f"  mode={mode:16s} depth={depth}: "
          f"{'一致' if not bad else f'不一致 {len(bad)}/{len(fr)}枚'}  最大画素差 {diff}")
    del compiled, model
    torch.cuda.empty_cache()


if __name__ == "__main__":
    with gpu_lock("gpu-inference", "CUDA Graph と depth-2 投入の整合性"):
        for mode in ("default", "reduce-overhead"):
            for depth in (1, 2):
                try:
                    run(mode, depth)
                except Exception as exc:
                    print(f"  mode={mode} depth={depth}: "
                          f"失敗 {type(exc).__name__}: {str(exc)[:160]}")
