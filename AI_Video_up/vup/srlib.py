"""GPU推論最適化の実験で共有する小道具 (exp_gpu_* / exp_trt / exp_ab が使う)。

exp_quality.py は他の担当が別用途で使っているため、名前を分けている。
"""
import subprocess
from pathlib import Path

import numpy as np
import torch

HERE = Path(__file__).resolve().parent
W, H = 720, 480
# SRVGGNetCompact(64feat/16conv) の積和 x2。fps -> TFLOPS 換算用
FLOP_PER_FRAME = W * H * (16 * 64 * 64 * 9 + 3 * 64 * 9 + 64 * 12 * 9) * 2


def grab_frames(video, n, step=97, w=W, h=H):
    """実素材から等間隔に n frame 抜く (rgb24)"""
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video),
         "-vf", f"select='not(mod(n\\,{step}))',scale={w}:{h}",
         "-vsync", "0", "-frames:v", str(n),
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True).stdout
    k = len(out) // (w * h * 3)
    return np.frombuffer(out[:k * w * h * 3], dtype=np.uint8).reshape(k, h, w, 3)


def to_gpu(frames):
    x = torch.from_numpy(frames.copy()).cuda()
    return x.permute(0, 3, 1, 2).float().div_(255.0)


def psnr(a, b):
    mse = ((a - b) ** 2).mean().item()
    return float("inf") if mse == 0 else 10 * np.log10(255.0 ** 2 / mse)


def best_med(times, bs):
    t = sorted(times)
    return bs / t[0], bs / t[len(t) // 2]
