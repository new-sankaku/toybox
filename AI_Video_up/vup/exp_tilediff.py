"""tile差分SRの実験

確かめること:
  1. 変化した領域だけmodelに通し、残りを前frameの結果で埋めたとき、
     全画面SRの結果とどれだけ一致するか(継ぎ目が出るか)
  2. そのとき必要なhalo(receptive field分の余白)の画素数
  3. 実素材でtileが何%変化するか = 実効的な計算量削減率
"""
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from srvgg import load  # noqa: E402

SRC = r"C:\01_work\00_Git\toybox\AI_Video_up\サンプル.mp4"
W, H = 720, 480
torch.backends.cudnn.benchmark = True


def frames(ss, sec):
    p = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-ss", str(ss), "-i", SRC, "-t", str(sec),
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
        stdout=subprocess.PIPE, bufsize=W * H * 3 * 8)
    n = W * H * 3
    while True:
        b = p.stdout.read(n)
        if len(b) < n:
            break
        yield np.frombuffer(b, np.uint8).reshape(H, W, 3).copy()
    p.stdout.close()
    p.wait()


model, up = load(str(HERE / "models" / "realesr-animevideov3.pth"))
model = model.to(memory_format=torch.channels_last)


def to_t(bgr):
    x = torch.from_numpy(bgr).cuda().permute(2, 0, 1).unsqueeze(0)
    return x.half().div_(255.0).contiguous(memory_format=torch.channels_last)


def sr_full(bgr):
    with torch.no_grad():
        return model(to_t(bgr)).clamp_(0, 1)


def sr_patch(x):
    with torch.no_grad():
        return model(x).clamp_(0, 1)


# ---------------------------------------------------------------- 1) 受容野
print("=== receptive field の実測 ===")
base = np.random.RandomState(0).randint(0, 255, (H, W, 3), np.uint8)
mod = base.copy()
mod[H // 2, W // 2] = 255 - mod[H // 2, W // 2]
a = sr_full(base)[0].float().cpu().numpy()
b = sr_full(mod)[0].float().cpu().numpy()
d = np.abs(a - b).max(axis=0)
ys, xs = np.nonzero(d > 1e-4)
if len(ys):
    ry = max(abs(ys.max() / up - H // 2), abs(ys.min() / up - H // 2))
    rx = max(abs(xs.max() / up - W // 2), abs(xs.min() / up - W // 2))
    print(f"1画素の変更が出力へ及ぶ範囲: 入力換算 半径 y={ry:.1f}px x={rx:.1f}px")
else:
    print("差分が出ませんでした(fp16の丸めで消えた可能性)")

# ---------------------------------------------------------------- 2) tile差分
CORE = 180
HALO_LIST = [0, 4, 8, 16, 20, 24, 32]
print("\n=== halo別: tile差分の結果が全画面SRと一致するか ===")
f0 = None
f1 = None
for f in frames(310, 2):
    if f0 is None:
        f0 = f
        continue
    if not np.array_equal(f0, f):
        f1 = f
        break
    f0 = f
print(f"連続する異なる2 frameを使用 (変化画素 "
      f"{int((np.abs(f0.astype(np.int16) - f1.astype(np.int16)).max(axis=2) > 2).sum())} / {H*W})")

full1 = sr_full(f1)[0]
prev = sr_full(f0)[0]

diff = np.abs(f0.astype(np.int16) - f1.astype(np.int16)).max(axis=2)
changed = diff > 2

for halo in HALO_LIST:
    out = prev.clone()
    n_tiles = 0
    for y in range(0, H, CORE):
        for x in range(0, W, CORE):
            y1, x1 = min(y + CORE, H), min(x + CORE, W)
            ys0, ys1 = max(0, y - halo), min(H, y1 + halo)
            xs0, xs1 = max(0, x - halo), min(W, x1 + halo)
            if not changed[ys0:ys1, xs0:xs1].any():
                continue
            n_tiles += 1
            patch = to_t(f1[ys0:ys1, xs0:xs1])
            o = sr_patch(patch)[0]
            oy0 = (y - ys0) * up
            ox0 = (x - xs0) * up
            out[:, y * up:y1 * up, x * up:x1 * up] = \
                o[:, oy0:oy0 + (y1 - y) * up, ox0:ox0 + (x1 - x) * up]
    err = (out.float() - full1.float()).abs()
    err8 = (err * 255).max().item()
    mean8 = (err * 255).mean().item()
    total = ((H + CORE - 1) // CORE) * ((W + CORE - 1) // CORE)
    print(f"halo={halo:3d}px  処理tile {n_tiles}/{total}  "
          f"最大誤差 {err8:6.2f}/255  平均誤差 {mean8:6.4f}/255")

# ---------------------------------------------------------------- 3) 変化率
print("\n=== 実素材のtile変化率 (halo込みで再計算が必要なtileの割合) ===")
for ss in (60, 300, 600, 900):
    prev_f = None
    tot = chg = 0
    n = 0
    for f in frames(ss, 20):
        if prev_f is not None:
            d = np.abs(prev_f.astype(np.int16) - f.astype(np.int16)).max(axis=2) > 2
            if d.any():
                for y in range(0, H, CORE):
                    for x in range(0, W, CORE):
                        y1, x1 = min(y + CORE, H), min(x + CORE, W)
                        ys0, ys1 = max(0, y - 20), min(H, y1 + 20)
                        xs0, xs1 = max(0, x - 20), min(W, x1 + 20)
                        tot += 1
                        if d[ys0:ys1, xs0:xs1].any():
                            chg += 1
            else:
                tot += ((H + CORE - 1) // CORE) * ((W + CORE - 1) // CORE)
            n += 1
        prev_f = f
    print(f"  {ss:4d}s〜: frame {n}  再計算tile {chg}/{tot} = {chg/max(tot,1)*100:5.1f}%")
