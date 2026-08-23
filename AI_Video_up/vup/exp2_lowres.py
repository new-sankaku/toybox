"""低解像度SR + 差分補正が成立するかを測る。

SR の計算量は入力画素数にほぼ比例するので、入力を半分(360x240)に落として
x4 model を通せば 1440x960 が 1/4 の計算量で出る。理屈の上では4倍速い。

問題は情報が消えることなので、客観的に測れる指標として
「出力を入力解像度へ box 縮小したとき、元の source frame とどれだけ一致するか」
を使う。SR は元の画素を作り直す作業なので、縮小して元に戻らない出力は
少なくとも元の情報を保っていない。
"""
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as F

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from models_registry import load_model, resolve  # noqa: E402

SRC = r"C:\01_work\00_Git\toybox\AI_Video_up\サンプル.mp4"
W, H = 720, 480


def frames(n, ss=240):
    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(ss), "-i", SRC,
         "-frames:v", str(n), "-fps_mode", "passthrough",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True)
    b = np.frombuffer(p.stdout, np.uint8)
    k = b.size // (H * W * 3)
    return b[: k * H * W * 3].reshape(k, H, W, 3)


def sr(model, bgr, scale, out_scale, pre_down=1):
    x = torch.from_numpy(np.ascontiguousarray(bgr)).cuda()
    x = x.permute(2, 0, 1).unsqueeze(0).half().div_(255.0)
    if pre_down > 1:
        x = F.avg_pool2d(x, pre_down)
    x = x.contiguous(memory_format=torch.channels_last)
    with torch.no_grad():
        y = model(x).clamp_(0, 1)
    eff = scale / pre_down
    if eff != out_scale:
        y = F.interpolate(y.float(), scale_factor=out_scale / eff,
                          mode="bicubic", align_corners=False,
                          antialias=out_scale < eff).clamp_(0, 1)
    return y


def psnr(a, b):
    mse = float(np.mean((a.astype(np.float32) - b.astype(np.float32)) ** 2))
    return 99.0 if mse == 0 else 10 * np.log10(255.0 ** 2 / mse)


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "anime"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    torch.backends.cudnn.benchmark = True
    model, scale, arch = load_model(resolve(name), device="cuda", half=True)
    model = model.to(memory_format=torch.channels_last)
    fs = frames(n)
    print(f"{arch} x{scale}  評価 {len(fs)} frame  出力 x2 (1440x960)")

    ways = [("通常 (720x480 入力)", 1),
            ("半分入力 (360x240)", 2)]
    if scale >= 4:
        ways.append(("1/4入力 (180x120)", 4))
    print(f"{'やり方':22s} {'入力画素比':>9s} {'縮小戻しPSNR':>12s} "
          f"{'SR実測 fps':>11s}")
    for label, pd in ways:
        eff_in = 1.0 / (pd * pd)
        vals = []
        for f in fs:
            y = sr(model, f, scale, 2, pre_down=pd)
            # 出力を入力解像度へ box 縮小して source と比べる
            back = F.avg_pool2d(y, 2)
            back = (back.mul_(255.0).round_().clamp_(0, 255)
                    .to(torch.uint8).squeeze(0).permute(1, 2, 0)
                    .cpu().numpy())
            vals.append(psnr(back, f))
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        for f in fs[:20]:
            sr(model, f, scale, 2, pre_down=pd)
        torch.cuda.synchronize()
        fps = 20 / (time.perf_counter() - t0)
        print(f"{label:22s} {eff_in * 100:8.1f}% {np.mean(vals):12.1f} "
              f"{fps:11.1f}")
    print("\n縮小戻しPSNR = 出力を1/2に box 縮小して元の source frame と比べた値。")
    print("SR が元の画素を保っていれば高く、情報を捨てていれば低い。")


if __name__ == "__main__":
    main()
