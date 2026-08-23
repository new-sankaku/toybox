"""低解像度SRの評価をやり直す。

縮小戻しPSNRは低周波が支配して差が出なかった(bicubicでも高く出る)。
SR で欲しいのは線画の解像感なので、
  - 通常入力の出力を基準にした PSNR (どれだけ別物になるか)
  - 高周波の量 (Laplacian の分散。線画がぼければ下がる)
の2つで見る。bicubic を下限の目盛りとして並べる。
"""
import sys
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as F

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from exp2_lowres import frames, psnr  # noqa: E402
from models_registry import load_model, resolve  # noqa: E402


def to_np(y):
    return (y.clamp(0, 1).mul(255.0).round().to(torch.uint8)
            .squeeze(0).permute(1, 2, 0).cpu().numpy())


def sharp(img):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(g, cv2.CV_32F).var())


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "anime"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    torch.backends.cudnn.benchmark = True
    model, scale, arch = load_model(resolve(name), device="cuda", half=True)
    model = model.to(memory_format=torch.channels_last)
    fs = frames(n)
    print(f"{arch} x{scale}  評価 {len(fs)} frame  出力 1440x960")

    res = {}
    for f in fs:
        x0 = torch.from_numpy(np.ascontiguousarray(f)).cuda()
        x0 = x0.permute(2, 0, 1).unsqueeze(0).half().div_(255.0)
        outs = {}
        for label, pd in (("通常 720x480 入力", 1), ("半分 360x240 入力", 2),
                          ("1/4 180x120 入力", 4)):
            x = F.avg_pool2d(x0, pd) if pd > 1 else x0
            x = x.contiguous(memory_format=torch.channels_last)
            with torch.no_grad():
                y = model(x).clamp_(0, 1)
            eff = scale / pd
            if eff != 2:
                y = F.interpolate(y.float(), scale_factor=2 / eff,
                                  mode="bicubic", align_corners=False,
                                  antialias=2 < eff).clamp_(0, 1)
            outs[label] = to_np(y)
        b = F.interpolate(x0.float(), scale_factor=2, mode="bicubic",
                          align_corners=False).clamp_(0, 1)
        outs["bicubic x2 (SR無し)"] = to_np(b)
        ref = outs["通常 720x480 入力"]
        for k, v in outs.items():
            r = res.setdefault(k, {"psnr": [], "sharp": []})
            r["psnr"].append(psnr(v, ref))
            r["sharp"].append(sharp(v))
    print(f"{'やり方':22s} {'通常出力比PSNR':>14s} {'高周波量':>10s} {'通常比':>8s}")
    base = np.mean(res["通常 720x480 入力"]["sharp"])
    for k, v in res.items():
        p = np.mean(v["psnr"])
        s = np.mean(v["sharp"])
        print(f"{k:22s} {(99.0 if p > 90 else p):14.1f} {s:10.1f} "
              f"{s / base:7.2f}倍")


if __name__ == "__main__":
    main()
