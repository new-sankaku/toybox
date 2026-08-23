"""高品質 model を教師にして、軽い model へ蒸留する（現実性の実証）

狙いは「品質を保ったまま速く」の唯一の正攻法。既製の重みは全て他人の素材で
訓練されているので、この素材の傾向（DVD 由来のリンギング・dot crawl・色の
にじみ）に合わせ込む余地が残っている。

蒸留は SR を1から訓練するより格段に楽である。
- 教師の出力が正解なので、劣化 model も discriminator も要らない。単なる回帰。
- 生徒は既に anime で訓練済みの重みから始めるので、収束が速い。

教師: sd-hq (RealPLKSR 7.37M)
生徒: UltraCompact 0.305M（Ani4Kv2 の重みから開始。MACは教師の1/24）

入力は素材そのもの（720x480）から切り出した crop。教師の出力を目標にする。
教師出力は毎 step 計算せず、先に作って RAM に置く。
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from models_registry import load_model  # noqa: E402

SRC = r"C:\01_work\00_Git\toybox\AI_Video_up\サンプル.mp4"
MODELS_DIR = HERE / "models"
W, H = 720, 480

ap = argparse.ArgumentParser()
ap.add_argument("--teacher", default="2x_AniSD_RealPLKSR_140K.pth")
ap.add_argument("--student", default="2x_Ani4Kv2_G6i2_UltraCompact_105K.pth")
ap.add_argument("--frames", type=int, default=240, help="教師を通す frame 数")
ap.add_argument("--steps", type=int, default=4000)
ap.add_argument("--crop", type=int, default=128, help="入力側の crop 辺")
ap.add_argument("--batch", type=int, default=16)
ap.add_argument("--lr", type=float, default=2e-4)
ap.add_argument("--out", default="2x_distilled_UltraCompact.pth")
args = ap.parse_args()
torch.backends.cudnn.benchmark = True


def read_frames(n):
    """素材から等間隔に n 枚読む"""
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", SRC], capture_output=True, text=True)
    dur = float(p.stdout.strip())
    step = max(dur / n, 0.5)
    out = []
    for i in range(n):
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", str(i * step), "-i", SRC,
             "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            capture_output=True)
        b = r.stdout[:W * H * 3]
        if len(b) < W * H * 3:
            continue
        out.append(np.frombuffer(b, np.uint8).reshape(H, W, 3).copy())
    return out


print(f"素材を {args.frames} 枚読みます", flush=True)
frames = read_frames(args.frames)
print(f"  {len(frames)}枚", flush=True)

teacher, t_scale, t_arch = load_model(MODELS_DIR / args.teacher)
teacher = teacher.to(memory_format=torch.channels_last)
print(f"教師 {t_arch.split('(')[0]} x{t_scale} "
      f"{sum(p.numel() for p in teacher.parameters()) / 1e6:.2f}M", flush=True)

print("教師の出力を作ります", flush=True)
lo, hi = [], []
with torch.no_grad():
    for f in frames:
        x = torch.from_numpy(f).cuda().permute(2, 0, 1).unsqueeze(0)
        x = x.half().div_(255.0).contiguous(memory_format=torch.channels_last)
        y = teacher(x).clamp_(0, 1)
        if t_scale == 4:
            y = F.avg_pool2d(y, 2)
        lo.append(x[0].float().cpu())
        hi.append(y[0].float().cpu())
del teacher
torch.cuda.empty_cache()
print(f"  {len(hi)}組", flush=True)

student, s_scale, s_arch = load_model(MODELS_DIR / args.student, half=False)
student = student.to(memory_format=torch.channels_last).train()
n_s = sum(p.numel() for p in student.parameters())
print(f"生徒 {s_arch.split('(')[0]} x{s_scale} {n_s / 1e6:.3f}M", flush=True)
assert s_scale == 2, "生徒は x2 前提"

opt = torch.optim.AdamW(student.parameters(), lr=args.lr, weight_decay=0)
sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, args.steps, eta_min=args.lr / 20)
scaler = torch.amp.GradScaler("cuda")
c = args.crop
rng = np.random.default_rng(0)


def batch():
    xs, ys = [], []
    for _ in range(args.batch):
        i = rng.integers(len(lo))
        px = int(rng.integers(0, W - c))
        py = int(rng.integers(0, H - c))
        xs.append(lo[i][:, py:py + c, px:px + c])
        ys.append(hi[i][:, py * 2:(py + c) * 2, px * 2:(px + c) * 2])
    x = torch.stack(xs).cuda(non_blocking=True)
    y = torch.stack(ys).cuda(non_blocking=True)
    if rng.random() < 0.5:
        x, y = torch.flip(x, [3]), torch.flip(y, [3])
    return (x.contiguous(memory_format=torch.channels_last),
            y.contiguous(memory_format=torch.channels_last))


# 開始時点の誤差（= 素の生徒が教師からどれだけ離れているか）
def eval_gap():
    student.eval()
    tot = 0.0
    with torch.no_grad():
        for i in range(0, min(len(lo), 24)):
            x = lo[i].unsqueeze(0).cuda().contiguous(memory_format=torch.channels_last)
            with torch.autocast("cuda", torch.float16):
                p = student(x).float().clamp(0, 1)
            e = F.mse_loss(p.cpu(), hi[i].unsqueeze(0)).item()
            tot += 10 * np.log10(1.0 / max(e, 1e-12))
    student.train()
    return tot / min(len(lo), 24)


print(f"開始時の 教師との一致 PSNR = {eval_gap():.2f} dB", flush=True)
t0 = time.perf_counter()
for step in range(1, args.steps + 1):
    x, y = batch()
    with torch.autocast("cuda", torch.float16):
        p = student(x)
        loss = F.l1_loss(p, y)
    opt.zero_grad(set_to_none=True)
    scaler.scale(loss).backward()
    scaler.step(opt)
    scaler.update()
    sched.step()
    if step % 500 == 0:
        el = time.perf_counter() - t0
        print(f"step {step:5d}/{args.steps}  loss {loss.item():.5f}  "
              f"一致 {eval_gap():.2f} dB  {el:.0f}秒 "
              f"(残り {el / step * (args.steps - step):.0f}秒)", flush=True)

out = MODELS_DIR / args.out
sd = {k: v.cpu() for k, v in student.state_dict().items()}
torch.save({"params": sd}, out)
print(f"\n保存しました: {out}")
print(f"最終 教師との一致 PSNR = {eval_gap():.2f} dB")
