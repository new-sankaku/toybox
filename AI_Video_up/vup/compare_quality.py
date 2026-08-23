"""model別の画質を、同一frameの同一箇所を切り出して並べて比べる

正解となるHD版が無いので、数値で順位は付けられない。線の太さ・輪郭のリンギング・
平坦部のノイズ・文字の潰れを目で見るための素材を作る。
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
OUT = HERE / "compare"
OUT.mkdir(exist_ok=True)

# (時刻, 切り出し位置x, y, 幅, 高さ) 入力座標
SHOTS = [
    (850.0, 0, 250, 240, 160),     # 金網・高周波
    (850.0, 470, 60, 240, 160),    # 金網と空の境界
    (700.0, 200, 120, 240, 160),   # 線画
]
MODELS = sys.argv[1:] or ["sd-fast", "sd", "sd-janai", "sd-span", "toon",
                          "sd-hq", "anime"]
torch.backends.cudnn.benchmark = True


def grab(ss):
    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(ss), "-i", SRC, "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True)
    return np.frombuffer(p.stdout[:W * H * 3], np.uint8).reshape(H, W, 3).copy()


frames = {ss: grab(ss) for (ss, *_) in SHOTS}
results = {}

for name in MODELS:
    path = resolve(name)
    model, scale, arch = load_model(path)
    model = model.to(memory_format=torch.channels_last)
    outs = {}
    with torch.no_grad():
        for ss, f in frames.items():
            x = torch.from_numpy(f).cuda().permute(2, 0, 1).unsqueeze(0)
            x = x.half().div_(255.0).contiguous(memory_format=torch.channels_last)
            y = model(x).clamp_(0, 1)
            if scale == 4:
                y = torch.nn.functional.avg_pool2d(y, 2)
            outs[ss] = (y[0].permute(1, 2, 0) * 255).round().to(
                torch.uint8).cpu().numpy()
    results[name] = outs
    n = sum(p.numel() for p in model.parameters())
    print(f"{name:10s} {arch[:30]:30s} x{scale} {n / 1e6:.2f}M")
    del model
    torch.cuda.empty_cache()

# 比較用として lanczos も置く
results["(lanczos)"] = {ss: cv2.resize(f, (1440, 960),
                                       interpolation=cv2.INTER_LANCZOS4)
                        for ss, f in frames.items()}

names = list(results)
for i, (ss, cx, cy, cw, ch) in enumerate(SHOTS):
    tiles = []
    for name in names:
        crop = results[name][ss][cy * 2:(cy + ch) * 2, cx * 2:(cx + cw) * 2]
        crop = np.ascontiguousarray(crop)
        cv2.rectangle(crop, (0, 0), (crop.shape[1] - 1, 26), (0, 0, 0), -1)
        cv2.putText(crop, name, (6, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (255, 255, 255), 1, cv2.LINE_AA)
        tiles.append(crop)
    cols = 4
    rows = [np.hstack(tiles[r:r + cols]) for r in range(0, len(tiles), cols)]
    wmax = max(r.shape[1] for r in rows)
    rows = [np.pad(r, ((0, 0), (0, wmax - r.shape[1]), (0, 0))) for r in rows]
    grid = np.vstack(rows)
    p = OUT / f"shot{i}_{int(ss)}s.png"
    cv2.imwrite(str(p), grid)
    print("書きました:", p)
