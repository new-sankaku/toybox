"""pixel-unshuffle 前置きの SPAN（SPANPlus 系）を ONNX のまま評価する

models/ にある AnimeJaNai V3.1 の ONNX は、最初の conv が (48,12,3,3) すなわち
入力を 2x2 の pixel-unshuffle で 12ch に畳んでから本体へ入れている。本体は
入力の半分の解像度（720x480 なら 360x240）で動くので、空間位置が 1/4 になる。
最後に pixel-shuffle(4) で 1440x960 へ戻す。

理論 MAC は Compact 206.8 GMAC に対して 30〜85 GMAC。arch 側の最大の速度手段は
これ。ただし spandrel 0.4.2 は SPANPlus に対応しておらず（SPAN のみ）、
torch 側では読めないので ONNX Runtime で測る。

比較の公平のため、torch でも読める Compact の ONNX を同じ runtime で並べる。
ORT と torch の実装差はこの対照で吸収できる。
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
MODELS_DIR = HERE / "models"
SRC = r"C:\01_work\00_Git\toybox\AI_Video_up\サンプル.mp4"
W, H = 720, 480
TIMES = [30, 90, 150, 200, 260, 340, 415, 500, 560, 620, 700, 780, 850, 920, 970, 990]

ONNX = {
    "janai31-perf": "2x_AnimeJaNai_HD_V3.1_Performance_SPANF3_b5f48_unshuffle_fp16.onnx",
    "janai31-bal": "2x_AnimeJaNai_HD_V3.1_Balanced_SPANF3_b8f64_unshuffle_fp16.onnx",
    "janai31-perf-s": "2x_AnimeJaNai_HD_V3.1Sharp1_Performance_SPANF3_b5f48_unshuffle_fp16.onnx",
    "janai31-bal-s": "2x_AnimeJaNai_HD_V3.1Sharp1_Balanced_SPANF3_b8f64_unshuffle_fp16.onnx",
    # 対照: torch 側でも測っている Compact。ORT と torch の差はこれで見る。
    "sd-janai(onnx)": "2x_AnimeJaNai_SD_V1beta34_Compact_1x3xHxW_dyn-HW_strong_fp16_op21_dynamo.onnx",
}

ap = argparse.ArgumentParser()
ap.add_argument("--rounds", type=int, default=12)
ap.add_argument("--trt", action="store_true", help="TensorRT EP を使う")
args = ap.parse_args()

import onnxruntime as ort  # noqa: E402
import lpips  # noqa: E402
import torch  # noqa: E402

LP = lpips.LPIPS(net="alex", verbose=False).cuda()


def grab(ss):
    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(ss), "-i", SRC, "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True)
    return np.frombuffer(p.stdout[:W * H * 3], np.uint8).reshape(H, W, 3).copy()


def degrade(frames):
    """720x480 -> 360x240 縮小 + h264 all-intra 往復（exp_msel_quality と同じ）"""
    cache = HERE / "_qcache"
    cache.mkdir(exist_ok=True)
    raw = cache / "onnx_lr.bin"
    small = [cv2.resize(f, (W // 2, H // 2), interpolation=cv2.INTER_AREA)
             for f in frames]
    raw.write_bytes(b"".join(f.tobytes() for f in small))
    mp4 = cache / "onnx_lr.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo",
                    "-pix_fmt", "bgr24", "-s", f"{W // 2}x{H // 2}", "-r", "24",
                    "-i", str(raw), "-c:v", "libx264", "-crf", "20",
                    "-pix_fmt", "yuv420p", "-g", "1", str(mp4)], check=True)
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp4), "-f", "rawvideo",
                        "-pix_fmt", "bgr24", "-"], capture_output=True)
    n = (W // 2) * (H // 2) * 3
    return [np.frombuffer(p.stdout[i * n:(i + 1) * n], np.uint8)
            .reshape(H // 2, W // 2, 3).copy() for i in range(len(small))]


gt = [grab(t) for t in TIMES]
lr = degrade(gt)


def psnr(a, b):
    mse = float(np.mean((a.astype(np.float32) - b.astype(np.float32)) ** 2))
    return 99.0 if mse == 0 else 10 * np.log10(255.0 ** 2 / mse)


def lpips_of(a, b):
    def prep(im):
        t = torch.from_numpy(im[:, :, ::-1].copy()).cuda().permute(2, 0, 1)
        return (t.float() / 127.5 - 1.0).unsqueeze(0)
    with torch.no_grad():
        return float(LP(prep(a), prep(b)).item())


def edge_psnr(a, b):
    g = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)
    m = np.abs(cv2.Laplacian(cv2.GaussianBlur(g, (0, 0), 1.0), cv2.CV_32F))
    mask = m > np.percentile(m, 92)
    d = (a.astype(np.float32) - b.astype(np.float32)) ** 2
    return 10 * np.log10(255.0 ** 2 / max(float(d[mask].mean()), 1e-9))


if args.trt:
    providers = [("TensorrtExecutionProvider",
                  {"trt_fp16_enable": True,
                   "trt_engine_cache_enable": True,
                   "trt_engine_cache_path": str(HERE / "_trtcache")}),
                 "CUDAExecutionProvider"]
else:
    providers = ["CUDAExecutionProvider"]

print(f"{'name':16s} {'入力dtype':>9s} {'A_PSNR':>7s} {'A_LPIPS':>8s} {'A_輪郭':>7s} "
      f"{'速度best':>9s} {'速度med':>8s}")
for name, fname in ONNX.items():
    path = MODELS_DIR / fname
    if not path.exists():
        print(f"{name}: 無し")
        continue
    try:
        so = ort.SessionOptions()
        so.log_severity_level = 3
        sess = ort.InferenceSession(str(path), so, providers=providers)
    except Exception as exc:
        print(f"{name}: session作成失敗 {type(exc).__name__}: {str(exc)[:60]}")
        continue
    inp = sess.get_inputs()[0]
    dt = np.float16 if "float16" in inp.type else np.float32

    def run(img):
        x = img[:, :, ::-1].transpose(2, 0, 1)[None].astype(dt) / dt(255.0)
        y = sess.run(None, {inp.name: x})[0]
        y = np.clip(y[0].transpose(1, 2, 0), 0, 1) * 255.0
        return np.ascontiguousarray(y.round().astype(np.uint8)[:, :, ::-1])

    # A: 劣化 360x240 -> 720x480
    try:
        outs = [run(f) for f in lr]
    except Exception as exc:
        print(f"{name}: 推論失敗 {type(exc).__name__}: {str(exc)[:60]}")
        continue
    A = np.array([[psnr(o, g), lpips_of(o, g), edge_psnr(o, g)]
                  for o, g in zip(outs, gt)]).mean(axis=0)

    # 速度: 本番と同じ 720x480 入力
    xb = (gt[0][:, :, ::-1].transpose(2, 0, 1)[None].astype(dt) / dt(255.0))
    for _ in range(5):
        sess.run(None, {inp.name: xb})
    fps = []
    for _ in range(args.rounds):
        t = time.perf_counter()
        for _ in range(10):
            sess.run(None, {inp.name: xb})
        fps.append(10 / (time.perf_counter() - t))
    cv2.imwrite(str(HERE / "compare_msel" / f"onnx_{name}.png"),
                run(gt[10]))
    print(f"{name:16s} {str(np.dtype(dt)):>9s} {A[0]:7.3f} {A[1]:8.4f} {A[2]:7.3f} "
          f"{max(fps):7.1f}fps {np.median(fps):6.1f}fps")
    del sess
