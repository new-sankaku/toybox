"""(1) 蒸留を「前半で学習 / 後半で評価」に分けて、汚染の無い値を出す
   (2) 線の太り・平坦部の高周波（原画に無い模様）を数値で測る

(1) の理由: 先の蒸留は サンプル.mp4 の全長から等間隔に 200 frame 取って学習した。
その後の品質評価も同じ動画の frame で行っているので、**学習に使った絵で採点して
いる**。値は楽観側に偏る。既定 model を決める根拠には使えない。
ここでは前半 (0〜半分) だけで学習し、後半だけで評価する。

(2) の理由: lead から「線が細る/太る」「平坦部の noise」「原画に無い模様」で
言い切れるかと問われた。目視の印象ではなく数値で答える。
   線の太さ   : 出力の暗画素の面積 / 原本を nearest で2倍した物の暗画素の面積。
                1.00 より大きければ太り、小さければ細る。
   高周波の混入: 原本側で平坦な領域だけを mask にし（出力から作ると循環する）、
                出力の高周波成分の標準偏差を測る。lanczos が下限の目安。
"""
import argparse
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
sys.path.insert(0, r"C:\Users\sanka\AppData\Local\Temp\claude"
                   r"\C--01-work-00-Git-toybox-AI-Video-up"
                   r"\a69516b7-fb23-4024-ad85-73e2610bad30\scratchpad")
from models_registry import load_model  # noqa: E402
from gpulock import gpu_lock  # noqa: E402

SRC = r"C:\01_work\00_Git\toybox\AI_Video_up\サンプル.mp4"
MODELS_DIR = HERE / "models"
W, H = 720, 480

ap = argparse.ArgumentParser()
ap.add_argument("--train-frames", type=int, default=140)
ap.add_argument("--steps", type=int, default=5000)
ap.add_argument("--out", default="2x_distilled_UC_firsthalf.pth")
args = ap.parse_args()
torch.backends.cudnn.benchmark = True


def grab(ss):
    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{ss:.3f}", "-i", SRC, "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True)
    b = p.stdout[:W * H * 3]
    if len(b) < W * H * 3:
        return None
    return np.frombuffer(b, np.uint8).reshape(H, W, 3).copy()


dur = float(subprocess.run(
    ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
     "csv=p=0", SRC], capture_output=True, text=True).stdout.strip())
half = dur / 2
print(f"素材 {dur:.1f}秒。学習=前半 0〜{half:.0f}秒 / 評価=後半 {half:.0f}〜{dur:.0f}秒",
      flush=True)

train_t = [i * (half / args.train_frames) for i in range(args.train_frames)]
test_t = [half + 15 + i * ((half - 30) / 16) for i in range(16)]
train_f = [f for f in (grab(t) for t in train_t) if f is not None]
test_f = [f for f in (grab(t) for t in test_t) if f is not None]
print(f"  学習 {len(train_f)}枚 / 評価 {len(test_f)}枚", flush=True)


def degrade(frames, tag):
    d = HERE / "_qcache"
    d.mkdir(exist_ok=True)
    raw, mp4 = d / f"ho_{tag}.bin", d / f"ho_{tag}.mp4"
    small = [cv2.resize(f, (W // 2, H // 2), interpolation=cv2.INTER_AREA)
             for f in frames]
    raw.write_bytes(b"".join(f.tobytes() for f in small))
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt",
                    "bgr24", "-s", f"{W // 2}x{H // 2}", "-r", "24", "-i", str(raw),
                    "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p",
                    "-g", "1", str(mp4)], check=True)
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp4), "-f", "rawvideo",
                        "-pix_fmt", "bgr24", "-"], capture_output=True)
    n = (W // 2) * (H // 2) * 3
    return [np.frombuffer(p.stdout[i * n:(i + 1) * n], np.uint8)
            .reshape(H // 2, W // 2, 3).copy() for i in range(len(small))]


test_lr = degrade(test_f, "test")

# ---------------------------------------------------------------- 指標
def psnr(a, b):
    m = float(np.mean((a.astype(np.float32) - b.astype(np.float32)) ** 2))
    return 99.0 if m == 0 else 10 * np.log10(255.0 ** 2 / m)


def edge_psnr(a, b):
    g = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)
    m = np.abs(cv2.Laplacian(cv2.GaussianBlur(g, (0, 0), 1.0), cv2.CV_32F))
    mask = m > np.percentile(m, 92)
    d = (a.astype(np.float32) - b.astype(np.float32)) ** 2
    return 10 * np.log10(255.0 ** 2 / max(float(d[mask].mean()), 1e-9))


def line_and_texture(out, ref_nn):
    """out, ref_nn ともに 1440x960。ref_nn は原本の nearest 2倍"""
    go = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
    gr = cv2.cvtColor(ref_nn, cv2.COLOR_BGR2GRAY)
    # 線の太さ: 原本の暗画素の分布から閾値を決め、両者の暗画素面積を比べる
    t = np.percentile(gr, 8)
    n_ref = int((gr <= t).sum())
    width = float((go <= t).sum()) / max(n_ref, 1)
    # 平坦部の高周波: 原本側で平坦な所だけ見る
    sx = cv2.Sobel(gr.astype(np.float32), cv2.CV_32F, 1, 0, 3)
    sy = cv2.Sobel(gr.astype(np.float32), cv2.CV_32F, 0, 1, 3)
    mag = np.sqrt(sx * sx + sy * sy)
    flat = (mag <= np.percentile(mag, 45)).astype(np.uint8)
    flat = cv2.erode(flat, np.ones((9, 9), np.uint8)).astype(bool)
    hi = go.astype(np.float32) - cv2.GaussianBlur(go.astype(np.float32), (0, 0), 1.5)
    return width, float(hi[flat].std()) if flat.any() else float("nan")


def run(model, scale, imgs):
    outs = []
    with torch.no_grad():
        for f in imgs:
            x = torch.from_numpy(f).cuda().permute(2, 0, 1).unsqueeze(0)
            x = x.half().div_(255.0).contiguous(memory_format=torch.channels_last)
            y = model(x).clamp_(0, 1)
            if scale == 4:
                y = F.avg_pool2d(y, 2)
            outs.append((y[0].permute(1, 2, 0) * 255).round().to(
                torch.uint8).cpu().numpy())
    return outs


with gpu_lock("model-arch", "holdout蒸留 + 線/模様の指標"):
    # ---------------- 前半だけで蒸留 ----------------
    teacher, ts, _ = load_model(MODELS_DIR / "2x_AniSD_RealPLKSR_140K.pth")
    teacher = teacher.to(memory_format=torch.channels_last)
    lo, hi_t = [], []
    with torch.no_grad():
        for f in train_f:
            x = torch.from_numpy(f).cuda().permute(2, 0, 1).unsqueeze(0)
            x = x.half().div_(255.0).contiguous(memory_format=torch.channels_last)
            y = teacher(x).clamp_(0, 1)
            lo.append(x[0].float().cpu())
            hi_t.append(y[0].float().cpu())
    del teacher
    torch.cuda.empty_cache()
    print(f"教師の出力 {len(hi_t)}組", flush=True)

    student, ss, _ = load_model(
        MODELS_DIR / "2x_Ani4Kv2_G6i2_UltraCompact_105K.pth", half=False)
    student = student.to(memory_format=torch.channels_last).train()
    opt = torch.optim.AdamW(student.parameters(), lr=2e-4, weight_decay=0)
    sch = torch.optim.lr_scheduler.CosineAnnealingLR(opt, args.steps, eta_min=1e-5)
    scaler = torch.amp.GradScaler("cuda")
    rng = np.random.default_rng(0)
    c, bs = 128, 16
    t0 = time.perf_counter()
    for step in range(1, args.steps + 1):
        xs, ys = [], []
        for _ in range(bs):
            i = int(rng.integers(len(lo)))
            px, py = int(rng.integers(0, W - c)), int(rng.integers(0, H - c))
            xs.append(lo[i][:, py:py + c, px:px + c])
            ys.append(hi_t[i][:, py * 2:(py + c) * 2, px * 2:(px + c) * 2])
        x = torch.stack(xs).cuda().contiguous(memory_format=torch.channels_last)
        y = torch.stack(ys).cuda().contiguous(memory_format=torch.channels_last)
        with torch.autocast("cuda", torch.float16):
            loss = F.l1_loss(student(x), y)
        opt.zero_grad(set_to_none=True)
        scaler.scale(loss).backward()
        scaler.step(opt)
        scaler.update()
        sch.step()
        if step % 1000 == 0:
            print(f"  step {step}/{args.steps} loss {loss.item():.5f} "
                  f"{time.perf_counter() - t0:.0f}秒", flush=True)
    out_p = MODELS_DIR / args.out
    torch.save({"params": {k: v.cpu() for k, v in student.state_dict().items()}},
               out_p)
    del student, lo, hi_t
    torch.cuda.empty_cache()
    print(f"保存: {out_p}", flush=True)

    # ---------------- 後半だけで評価 ----------------
    ref_nn = [cv2.resize(f, (W * 2, H * 2), interpolation=cv2.INTER_NEAREST)
              for f in test_f]
    cand = {
        "sd": "2x_AniSD_AC_G6i2a_Compact_72500.pth",
        "sd-fast": "2x_Ani4Kv2_G6i2_UltraCompact_105K.pth",
        "distill-uc(汚染)": "2x_distilled_UltraCompact.pth",
        "distill-holdout": args.out,
        "suc": "2x_AnimeJaNai_HD_V3_SuperUltraCompact.pth",
        "sd-hq": "2x_AniSD_RealPLKSR_140K.pth",
    }
    print(f"\n{'model':18s} {'PSNR':>7s} {'輪郭PSNR':>9s} | "
          f"{'線の太さ':>8s} {'平坦部の高周波':>14s}")
    print("-" * 66)
    rows = {}
    for nm, fn in cand.items():
        p = MODELS_DIR / fn
        if not p.exists():
            print(f"{nm}: 重み無し")
            continue
        m, sc, _ = load_model(p)
        m = m.to(memory_format=torch.channels_last)
        a_out = run(m, sc, test_lr)                 # 劣化入力 -> 720x480
        b_out = run(m, sc, test_f)                  # 本番 720x480 -> 1440x960
        A = np.mean([[psnr(o, g), edge_psnr(o, g)]
                     for o, g in zip(a_out, test_f)], axis=0)
        Bm = np.mean([line_and_texture(o, r) for o, r in zip(b_out, ref_nn)], axis=0)
        rows[nm] = (A[0], A[1], Bm[0], Bm[1])
        print(f"{nm:18s} {A[0]:7.3f} {A[1]:9.3f} | {Bm[0]:8.4f} {Bm[1]:14.4f}",
              flush=True)
        del m
        torch.cuda.empty_cache()

    lz = [cv2.resize(f, (W, H), interpolation=cv2.INTER_LANCZOS4) for f in test_lr]
    lz2 = [cv2.resize(f, (W * 2, H * 2), interpolation=cv2.INTER_LANCZOS4)
           for f in test_f]
    A = np.mean([[psnr(o, g), edge_psnr(o, g)] for o, g in zip(lz, test_f)], axis=0)
    Bm = np.mean([line_and_texture(o, r) for o, r in zip(lz2, ref_nn)], axis=0)
    print(f"{'(lanczos)':18s} {A[0]:7.3f} {A[1]:9.3f} | {Bm[0]:8.4f} {Bm[1]:14.4f}")
    Bm = np.mean([line_and_texture(r, r) for r in ref_nn], axis=0)
    print(f"{'(nearest=原本)':18s} {'':>7s} {'':>9s} | {Bm[0]:8.4f} {Bm[1]:14.4f}")
