"""model一覧の速度と品質を、同一条件で測る

速度: 720x480 -> 出力 の forward 時間。eager と torch.compile の両方。
品質: 同じsource frameを各modelに通し、拡大した原本(lanczos)からの差と、
      高周波の量(Laplacian分散)を出す。正解画像は無いので順位付けではなく傾向の比較。
"""
import os
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from models_registry import REGISTRY, resolve, load_model  # noqa: E402

SRC = r"C:\01_work\00_Git\toybox\AI_Video_up\サンプル.mp4"
W, H = 720, 480
torch.backends.cudnn.benchmark = True

ONLY = sys.argv[1:] or list(REGISTRY)


def grab(seconds):
    out = []
    for ss in seconds:
        p = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", str(ss), "-i", SRC, "-frames:v", "1",
             "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
            capture_output=True)
        out.append(np.frombuffer(p.stdout[:W * H * 3], np.uint8).reshape(H, W, 3).copy())
    return out


frames = grab([100, 415, 700])
x = torch.from_numpy(frames[0]).cuda().permute(2, 0, 1).unsqueeze(0)
x = x.half().div_(255.0).contiguous(memory_format=torch.channels_last)

print(f"{'model':10s} {'arch':22s} {'x':>2s} {'param':>8s} "
      f"{'eager':>9s} {'compile':>9s} {'鮮鋭度':>8s}")
rows = []
for name in ONLY:
    path = resolve(name)
    try:
        model, scale, arch = load_model(path)
    except Exception as exc:
        print(f"{name:10s} 読み込み失敗 {type(exc).__name__}: {str(exc)[:50]}")
        continue
    model = model.to(memory_format=torch.channels_last)
    n = sum(p.numel() for p in model.parameters())

    def bench(mod, it):
        try:
            with torch.no_grad():
                for _ in range(5):
                    mod(x)
                torch.cuda.synchronize()
                t = time.time()
                for _ in range(it):
                    mod(x)
                torch.cuda.synchronize()
            return it / (time.time() - t)
        except Exception:
            return float("nan")

    it = 40 if n < 1e6 else (20 if n < 3e6 else (8 if n < 9e6 else 4))
    fps_eager = bench(model, it)
    try:
        compiled = torch.compile(model)
        fps_comp = bench(compiled, it)
    except Exception:
        fps_comp = float("nan")

    # 出力を1枚保存して鮮鋭度を測る
    with torch.no_grad():
        y = model(x).clamp(0, 1)
        if scale == 4:
            y = torch.nn.functional.avg_pool2d(y, 2)
        img = (y[0].permute(1, 2, 0) * 255).round().to(torch.uint8).cpu().numpy()
    out_dir = HERE / "compare"
    out_dir.mkdir(exist_ok=True)
    cv2.imwrite(str(out_dir / f"{name}.png"), img)
    lap = cv2.Laplacian(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()

    print(f"{name:10s} {arch[:22]:22s} {scale:2d} {n / 1e6:7.2f}M "
          f"{fps_eager:7.1f}fps {fps_comp:7.1f}fps {lap:8.1f}")
    rows.append((name, arch, scale, n, fps_eager, fps_comp, lap))
    del model
    torch.cuda.empty_cache()

ref = cv2.resize(frames[0], (1440, 960), interpolation=cv2.INTER_LANCZOS4)
cv2.imwrite(str(HERE / "compare" / "_lanczos.png"), ref)
lap_ref = cv2.Laplacian(cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()
print(f"{'(lanczos)':10s} {'':22s} {2:2d} {0:7.2f}M {'':>10s} {'':>10s} {lap_ref:8.1f}")
