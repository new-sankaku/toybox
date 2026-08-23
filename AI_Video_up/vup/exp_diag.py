"""TensorRT 出力のズレが「精度」なのか「1画素ずれ」なのかを切り分ける。"""
import sys
from pathlib import Path

import numpy as np
import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from models_registry import load_model, resolve  # noqa: E402
from exp_trt import TrtRunner, build_engine, export_onnx  # noqa: E402
from srlib import grab_frames, to_gpu, psnr  # noqa: E402

W, H = 720, 480

fr = grab_frames(HERE.parent / "サンプル.mp4", 4)
x = to_gpu(fr)
m32, scale, _ = load_model(resolve("sd"), device="cuda", half=False)
trt = TrtRunner(build_engine(export_onnx("sd", 1, half=True), "fp16", 1))
tin, tout = trt.inp[0], trt.out[0]

xi = x[0:1]
with torch.no_grad():
    ref = m32(xi).clamp(0, 1).mul(255).round()
trt.buf[tin].copy_(xi.half())
trt.ctx.execute_async_v3(trt.stream.cuda_stream)
trt.stream.synchronize()
y = trt.buf[tout].float().clamp(0, 1).mul(255).round()

print(f"ずれ無し           PSNR {psnr(ref, y):6.2f}")
for dy in (-1, 0, 1):
    for dx in (-1, 0, 1):
        if dx == 0 and dy == 0:
            continue
        r = torch.roll(ref, shifts=(dy, dx), dims=(2, 3))
        print(f"  refを ({dy:+d},{dx:+d}) ずらす  PSNR {psnr(r, y):6.2f}")

d = (ref - y).abs()
print(f"\n誤差>8/255 の画素割合 {(d > 8).float().mean().item()*100:.3f}%"
      f"   誤差>32 {(d > 32).float().mean().item()*100:.4f}%")
# 誤差の空間分布: 出力の 2x2 位相ごと (PixelShuffle/Resize 由来なら偏る)
for py in range(2):
    for px in range(2):
        print(f"  位相({py},{px}) 平均誤差 {d[:, :, py::2, px::2].mean().item():.4f}")
