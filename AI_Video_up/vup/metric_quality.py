"""model別の画質を数値で比べる

正解のHD版が無いので絶対評価はできない。代わりに3つの性質を測る。

鮮鋭度      : 輪郭の勾配の強さ。高いほど線がはっきりする。
平坦部ノイズ: 勾配がほぼ無い領域の標準偏差。SRが乗せた粒状感が出る。低い方が良い。
整合性      : 出力を入力解像度へ box 縮小して原本と比べたPSNR。
              低いほど原本から離れた絵を作っている（作り込みが強い／崩れている）。
"""
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from models_registry import resolve, load_model  # noqa: E402

SRC = r"C:\01_work\00_Git\toybox\AI_Video_up\サンプル.mp4"
W, H = 720, 480
TIMES = [30, 90, 120, 200, 260, 340, 415, 500, 620, 700, 780, 850, 920, 970]
MODELS = sys.argv[1:] or ["sd-fast", "sd", "sd-janai", "sd-span", "toon",
                          "sd-hq", "anime"]
torch.backends.cudnn.benchmark = True


def grab(ss):
    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(ss), "-i", SRC, "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True)
    return np.frombuffer(p.stdout[:W * H * 3], np.uint8).reshape(H, W, 3).copy()


frames = [grab(t) for t in TIMES]


def measure(out, src):
    g = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.sqrt(gx * gx + gy * gy)
    sharp = float(np.percentile(mag, 99))

    flat = mag < np.percentile(mag, 40)
    k = np.ones((5, 5), np.float32) / 25
    mean = cv2.filter2D(g, -1, k)
    var = cv2.filter2D(g * g, -1, k) - mean * mean
    noise = float(np.sqrt(np.maximum(var[flat], 0)).mean())

    small = cv2.resize(out, (W, H), interpolation=cv2.INTER_AREA)
    mse = float(np.mean((small.astype(np.float32) - src.astype(np.float32)) ** 2))
    cons = 99.0 if mse == 0 else 10 * np.log10(255.0 ** 2 / mse)
    return sharp, noise, cons


print(f"{'model':10s} {'param':>7s} {'鮮鋭度':>8s} {'平坦部ノイズ':>12s} {'整合性dB':>9s}")
rows = []
for name in MODELS + ["(lanczos)"]:
    if name == "(lanczos)":
        outs = [cv2.resize(f, (1440, 960), interpolation=cv2.INTER_LANCZOS4)
                for f in frames]
        n = 0
    else:
        model, scale, arch = load_model(resolve(name))
        model = model.to(memory_format=torch.channels_last)
        n = sum(p.numel() for p in model.parameters())
        outs = []
        with torch.no_grad():
            for f in frames:
                x = torch.from_numpy(f).cuda().permute(2, 0, 1).unsqueeze(0)
                x = x.half().div_(255.0).contiguous(
                    memory_format=torch.channels_last)
                y = model(x).clamp_(0, 1)
                if scale == 4:
                    y = torch.nn.functional.avg_pool2d(y, 2)
                outs.append((y[0].permute(1, 2, 0) * 255).round().to(
                    torch.uint8).cpu().numpy())
        del model
        torch.cuda.empty_cache()
    m = np.array([measure(o, f) for o, f in zip(outs, frames)])
    s, no, c = m.mean(axis=0)
    print(f"{name:10s} {n / 1e6:6.2f}M {s:8.1f} {no:12.3f} {c:9.2f}")
    rows.append((name, n, s, no, c))
