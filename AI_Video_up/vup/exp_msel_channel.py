"""model へ渡す channel順 (BGR のまま / RGB へ直す) で品質がどれだけ変わるか

vup.py は ffmpeg から bgr24 で受け、そのまま permute(2,0,1) して model へ入れる。
つまり model の R channel に B が入っている。Real-ESRGAN 系は RGB で訓練されて
いるので、model は「赤らしさ」を学んだ重みを青へ適用している。

出力側は _to_nv12 が channel 0 を B として扱うので、pipeline 全体としては
BGR で首尾一貫しており、**色が入れ替わって出力されるわけではない**。
壊れるのは model の内部だけで、channel ごとに強さの違う処理（色にじみの除去や
輪郭の立て方）が別の channel に掛かる。

ここでは同じ正解に対して2経路を比べる。
  現行: model(BGR) -> 出力をBGRとして扱う -> 正解(BGR) と比較
  修正: model(RGB) -> 出力をRGBとして扱いBGRへ戻す -> 正解(BGR) と比較
"""
import argparse
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from models_registry import load_model  # noqa: E402

SRC = r"C:\01_work\00_Git\toybox\AI_Video_up\サンプル.mp4"
MODELS_DIR = HERE / "models"
CACHE = HERE / "_qcache"
W, H = 720, 480
TIMES = [30, 90, 150, 200, 260, 340, 415, 500, 560, 620, 700, 780, 850, 920, 970, 990]

MODELS = {
    "sd": "2x_AniSD_AC_G6i2a_Compact_72500.pth",
    "sd-fast": "2x_Ani4Kv2_G6i2_UltraCompact_105K.pth",
    "distill-uc": "2x_distilled_UltraCompact.pth",
    "suc": "2x_AnimeJaNai_HD_V3_SuperUltraCompact.pth",
    "sd-hq": "2x_AniSD_RealPLKSR_140K.pth",
    "anime": "realesr-animevideov3.pth",
}

ap = argparse.ArgumentParser()
ap.add_argument("--models", nargs="*", default=list(MODELS))
args = ap.parse_args()
torch.backends.cudnn.benchmark = True


def grab(ss):
    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(ss), "-i", SRC, "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True)
    return np.frombuffer(p.stdout[:W * H * 3], np.uint8).reshape(H, W, 3).copy()


def degrade(frames):
    CACHE.mkdir(exist_ok=True)
    raw = CACHE / "ch_lr.bin"
    small = [cv2.resize(f, (W // 2, H // 2), interpolation=cv2.INTER_AREA)
             for f in frames]
    raw.write_bytes(b"".join(f.tobytes() for f in small))
    mp4 = CACHE / "ch_lr.mp4"
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

LP = None   # lock を取るまで GPU に触らない（他 process の計測を乱さないため）


def lpips_of(a, b):
    global LP
    if LP is None:
        import lpips
        LP = lpips.LPIPS(net="alex", verbose=False).cuda()

    def prep(im):
        t = torch.from_numpy(im[:, :, ::-1].copy()).cuda().permute(2, 0, 1)
        return (t.float() / 127.5 - 1.0).unsqueeze(0)
    with torch.no_grad():
        return float(LP(prep(a), prep(b)).item())


def psnr(a, b):
    mse = float(np.mean((a.astype(np.float32) - b.astype(np.float32)) ** 2))
    return 99.0 if mse == 0 else 10 * np.log10(255.0 ** 2 / mse)


def chroma_psnr(a, b):
    """色差(Cb/Cr)だけの PSNR。channel順の誤りはここに出るはず"""
    ay = cv2.cvtColor(a, cv2.COLOR_BGR2YCrCb)[:, :, 1:]
    by = cv2.cvtColor(b, cv2.COLOR_BGR2YCrCb)[:, :, 1:]
    mse = float(np.mean((ay.astype(np.float32) - by.astype(np.float32)) ** 2))
    return 99.0 if mse == 0 else 10 * np.log10(255.0 ** 2 / mse)


def run(model, scale, img, rgb):
    """rgb=False: 現行(BGRのまま渡す)。rgb=True: RGBへ直して渡し、BGRへ戻す。"""
    a = img[:, :, ::-1].copy() if rgb else img
    x = torch.from_numpy(a).cuda().permute(2, 0, 1).unsqueeze(0)
    x = x.half().div_(255.0).contiguous(memory_format=torch.channels_last)
    with torch.no_grad():
        y = model(x).clamp_(0, 1)
        if scale == 4:
            y = torch.nn.functional.avg_pool2d(y, 2)
    o = (y[0].permute(1, 2, 0) * 255).round().to(torch.uint8).cpu().numpy()
    return np.ascontiguousarray(o[:, :, ::-1]) if rgb else o


sys.path.insert(0, r"C:\Users\sanka\AppData\Local\Temp\claude"
                   r"\C--01-work-00-Git-toybox-AI-Video-up"
                   r"\a69516b7-fb23-4024-ad85-73e2610bad30\scratchpad")
from gpulock import gpu_lock  # noqa: E402

print(f"{'model':12s} | {'現行BGR PSNR':>13s} {'RGB修正 PSNR':>13s} {'差':>7s} | "
      f"{'色差BGR':>8s} {'色差RGB':>8s} {'差':>6s} | {'LPIPS現行':>10s} {'LPIPS修正':>10s}")
print("-" * 108)
with gpu_lock("model-arch", "channel順 A/B 6model"):
    for name in args.models:
        path = MODELS_DIR / MODELS[name]
        if not path.exists():
            print(f"{name}: 重み無し")
            continue
        model, scale, arch = load_model(path)
        model = model.to(memory_format=torch.channels_last)
        rows = []
        for f, g in zip(lr, gt):
            ob, orr = run(model, scale, f, False), run(model, scale, f, True)
            rows.append([psnr(ob, g), psnr(orr, g), chroma_psnr(ob, g),
                         chroma_psnr(orr, g), lpips_of(ob, g), lpips_of(orr, g)])
        m = np.array(rows).mean(axis=0)
        print(f"{name:12s} | {m[0]:13.3f} {m[1]:13.3f} {m[1] - m[0]:+7.3f} | "
              f"{m[2]:8.3f} {m[3]:8.3f} {m[3] - m[2]:+6.3f} | "
              f"{m[4]:10.4f} {m[5]:10.4f}", flush=True)

        # 目視用: 本番解像度で2経路の出力と差分を出す
        f = gt[10]
        ob, orr = run(model, scale, f, False), run(model, scale, f, True)
        d = np.clip(np.abs(ob.astype(int) - orr.astype(int)).sum(2) * 6,
                    0, 255).astype(np.uint8)
        out = HERE / "compare" / f"channel_{name}.png"
        cv2.imwrite(str(out), np.hstack([ob, orr, cv2.cvtColor(d, cv2.COLOR_GRAY2BGR)]))
        del model
        torch.cuda.empty_cache()
print("\n画像: compare/channel_*.png (左=現行BGR / 中=RGB修正 / 右=差分x6)")
