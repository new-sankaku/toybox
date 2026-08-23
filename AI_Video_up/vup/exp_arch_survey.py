"""候補 model を CPU で読んで arch / param / 理論MAC を並べる（GPUを使わない）

MAC は 96x64 入力で conv/linear の hook を取り、720x480 へ面積比で外挿する。
attention の spatial 二乗項は外挿でずれるので、arch が transformer 系の物は
参考値として扱う（* 印）。
"""
import sys
from pathlib import Path

import torch
import torch.nn as nn

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from models_registry import load_model  # noqa: E402

MODELS_DIR = HERE / "models"
PROBE_W, PROBE_H = 96, 64
REAL_W, REAL_H = 720, 480
AREA = (REAL_W * REAL_H) / (PROBE_W * PROBE_H)

TRANSFORMER = {"DAT", "SwinIR", "OmniSR", "ATD", "HAT", "RGT", "DRCT", "SRFormer",
               "CRAFT", "MoSR", "SeemoRe"}


def count_macs(model):
    macs = [0]
    hooks = []

    def hk(mod, inp, out):
        if isinstance(mod, nn.Conv2d):
            o = out.shape
            k = mod.kernel_size[0] * mod.kernel_size[1]
            macs[0] += o[1] * o[2] * o[3] * k * mod.in_channels // mod.groups
        elif isinstance(mod, nn.Linear):
            n = 1
            for d in out.shape[:-1]:
                n *= d
            macs[0] += n * mod.in_features * mod.out_features

    for m in model.modules():
        if isinstance(m, (nn.Conv2d, nn.Linear)):
            hooks.append(m.register_forward_hook(hk))
    x = torch.zeros(1, 3, PROBE_H, PROBE_W)
    with torch.no_grad():
        model(x)
    for h in hooks:
        h.remove()
    return macs[0]


paths = sorted(MODELS_DIR.glob("*.pth")) + sorted(MODELS_DIR.glob("*.safetensors"))
if len(sys.argv) > 1:
    paths = [MODELS_DIR / a for a in sys.argv[1:]]

print(f"{'file':46s} {'arch':16s} {'x':>2s} {'param':>8s} {'GMAC@720x480':>13s}")
rows = []
for p in paths:
    try:
        model, scale, arch = load_model(p, device="cpu", half=False)
    except Exception as exc:
        print(f"{p.name[:46]:46s} 読込失敗 {type(exc).__name__}: {str(exc)[:40]}")
        continue
    n = sum(q.numel() for q in model.parameters())
    try:
        g = count_macs(model) * AREA / 1e9
        mark = "*" if arch.split("(")[0] in TRANSFORMER else " "
    except Exception as exc:
        g, mark = float("nan"), "?"
    print(f"{p.name[:46]:46s} {arch.split('(')[0][:16]:16s} {scale:2d} "
          f"{n / 1e6:7.3f}M {g:12.1f}{mark}")
    rows.append((p.name, arch, scale, n, g))
    del model
