"""fp16 より下（int8 / fp8）へ落とす価値があるかを、品質側から先に判定する

engine を組む前に、torch 上の擬似量子化で「品質がどれだけ落ちるか」を測る。
落ちるなら速度を測るまでもなく棄却できる。

擬似量子化の作り方:
  重み  : conv の出力channelごとに対称 int8（per-channel）。TensorRT と同じ粒度。
  活性化: 層ごとに対称 int8（per-tensor）。実素材の frame で calibration し、
          絶対値の分布から percentile 点を範囲に取る。
  fp8   : E4M3 を per-tensor scale 付きで模擬（Ada の tensor core と同じ形）。

SR は活性化の動的範囲が層ごとに大きく違う（平坦部はほぼ0、輪郭で跳ねる）ので、
per-tensor int8 が効くかどうかはここで決まる。
"""
import argparse
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn as nn

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from models_registry import load_model  # noqa: E402

SRC = r"C:\01_work\00_Git\toybox\AI_Video_up\サンプル.mp4"
MODELS_DIR = HERE / "models"
W, H = 720, 480
CAL_T = [45, 160, 300, 480, 660, 810, 940]
TEST_T = [30, 200, 415, 620, 850, 970]

ap = argparse.ArgumentParser()
ap.add_argument("--weights", default="2x_AniSD_AC_G6i2a_Compact_72500.pth")
ap.add_argument("--pct", type=float, default=99.99, help="活性化範囲のpercentile")
args = ap.parse_args()


def grab(ss):
    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(ss), "-i", SRC, "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True)
    return np.frombuffer(p.stdout[:W * H * 3], np.uint8).reshape(H, W, 3).copy()


def to_t(img, dt=torch.float32):
    x = torch.from_numpy(img).cuda().permute(2, 0, 1).unsqueeze(0)
    return x.to(dt).div_(255.0)


def to_np(y):
    return (y[0].permute(1, 2, 0) * 255).round().clamp(0, 255).to(
        torch.uint8).cpu().numpy()


def psnr(a, b):
    mse = float(np.mean((a.astype(np.float32) - b.astype(np.float32)) ** 2))
    return 99.0 if mse == 0 else 10 * np.log10(255.0 ** 2 / mse)


model, scale, arch = load_model(MODELS_DIR / args.weights, half=False)
convs = [m for m in model.modules() if isinstance(m, nn.Conv2d)]
print(f"{args.weights}  {arch}  x{scale}  conv {len(convs)}個")

cal = [grab(t) for t in CAL_T]
test = [grab(t) for t in TEST_T]

# ---- 各 conv 入力の動的範囲を実素材で調べる ----
ranges = [[] for _ in convs]
hooks = []
for i, c in enumerate(convs):
    hooks.append(c.register_forward_pre_hook(
        lambda m, inp, i=i: ranges[i].append(
            float(torch.quantile(inp[0].detach().abs().flatten().float()[::7],
                                 args.pct / 100)))))
with torch.no_grad():
    for f in cal:
        model(to_t(f))
for h in hooks:
    h.remove()
amax = [max(r) for r in ranges]

print(f"\n{'層':>3s} {'in_ch':>6s} {'out_ch':>7s} {'活性化amax':>11s} {'重みamax':>9s} "
      f"{'重みch間の幅比':>14s}")
for i, (c, a) in enumerate(zip(convs, amax)):
    wmax = c.weight.detach().abs().amax(dim=(1, 2, 3))
    print(f"{i:3d} {c.in_channels:6d} {c.out_channels:7d} {a:11.4f} "
          f"{float(wmax.max()):9.4f} {float(wmax.max() / wmax.min()):13.1f}x")
print(f"\n活性化 amax の層間の幅比: {max(amax) / min(amax):.1f}x  "
      f"(最小 {min(amax):.4f} / 最大 {max(amax):.4f})")


# ---- 擬似量子化 ----
def q_int8_w(w):
    s = w.abs().amax(dim=(1, 2, 3), keepdim=True).clamp_min(1e-8) / 127.0
    return (w / s).round().clamp(-127, 127) * s


def q_int8_a(x, a):
    s = max(a, 1e-8) / 127.0
    return (x / s).round().clamp(-127, 127) * s


def q_fp8_e4m3(x, a):
    """E4M3: 仮数3bit・最大値448。per-tensor scale で 448 に合わせてから丸める"""
    s = max(a, 1e-8) / 448.0
    y = (x / s).clamp(-448, 448)
    e = torch.floor(torch.log2(y.abs().clamp_min(2 ** -9)))
    step = torch.pow(2.0, (e - 3).clamp_min(-9))
    return (y / step).round() * step * s


class QConv(nn.Module):
    """量子化した重みを持つ conv。元の Conv2d は保持しない
    （子として抱えると named_modules が無限再帰する）。"""

    def __init__(self, c, a, mode):
        super().__init__()
        self.a, self.mode = a, mode
        self.stride, self.padding = c.stride, c.padding
        self.dilation, self.groups = c.dilation, c.groups
        w = c.weight.data
        self.register_buffer(
            "w", q_int8_w(w) if mode == "int8"
            else q_fp8_e4m3(w, float(w.abs().max())))
        self.register_buffer("b", None if c.bias is None else c.bias.data.clone())

    def forward(self, x):
        qx = q_int8_a(x, self.a) if self.mode == "int8" else q_fp8_e4m3(x, self.a)
        return nn.functional.conv2d(qx, self.w, self.b, self.stride,
                                    self.padding, self.dilation, self.groups)


def swap(model, mode):
    # 先に置換先を全部拾ってから入れ替える（走査中の変更は再帰を招く）
    targets = []
    for parent in model.modules():
        for nm, ch in parent.named_children():
            if isinstance(ch, nn.Conv2d):
                targets.append((parent, nm, ch))
    mapping = {}
    for parent, nm, ch in targets:
        i = convs.index(ch)
        setattr(parent, nm, QConv(ch, amax[i], mode).cuda())
        mapping[(parent, nm)] = ch
    return mapping


def restore(mapping):
    for (parent, nm), ch in mapping.items():
        setattr(parent, nm, ch)


def outputs(m):
    r = []
    with torch.no_grad():
        for f in test:
            y = m(to_t(f)).clamp_(0, 1)
            if scale == 4:
                y = torch.nn.functional.avg_pool2d(y, 2)
            r.append(to_np(y))
    return r


base = outputs(model)

# fp16 を対照に置く（現行の運用値）
model.half()
half_out = []
with torch.no_grad():
    for f in test:
        y = model(to_t(f, torch.half)).clamp_(0, 1)
        if scale == 4:
            y = torch.nn.functional.avg_pool2d(y, 2)
        half_out.append(to_np(y))
model.float()

print(f"\n{'方式':10s} {'fp32との PSNR':>14s} {'最大画素差':>10s}")
for nm, outs in [("fp16", half_out)]:
    d = max(int(np.abs(a.astype(int) - b.astype(int)).max())
            for a, b in zip(outs, base))
    print(f"{nm:10s} {np.mean([psnr(a, b) for a, b in zip(outs, base)]):14.2f} "
          f"{d:10d}")

for mode in ["fp8", "int8"]:
    mp = swap(model, mode)
    outs = outputs(model)
    restore(mp)
    d = max(int(np.abs(a.astype(int) - b.astype(int)).max())
            for a, b in zip(outs, base))
    print(f"{mode:10s} {np.mean([psnr(a, b) for a, b in zip(outs, base)]):14.2f} "
          f"{d:10d}")
    out = HERE / "compare" / f"quant_{mode}.png"
    cv2.imwrite(str(out), outs[4])
cv2.imwrite(str(HERE / "compare" / "quant_fp32.png"), base[4])
print("\n画像: compare/quant_fp32.png / quant_fp8.png / quant_int8.png")
