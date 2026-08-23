"""候補 model の速度を、GPU を他 process と共有していても比較できる形で測る

この機体の GPU は他の作業と共有されている。素朴に model を順番に測ると、
たまたま重い作業と重なった model だけが遅く出て、順位が入れ替わる。

対策は2つ。
1. round-robin。全 model を1回ずつ測る回を R 回繰り返す。混雑は全 model に
   等しく掛かるので、順位は保たれる。
2. 各回の間に nvidia-smi で他 process の GPU 使用を記録し、最も空いていた回
   （= 自分だけが使えた回）の値を「最良値」として別に出す。混雑の影響を
   受けていない値はこちらになる。

出力は model ごとに median / best / GMAC / 理論効率。
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from models_registry import load_model  # noqa: E402

MODELS_DIR = HERE / "models"
W, H = 720, 480
torch.backends.cudnn.benchmark = True

# 測る対象。(表示名, file名)
CANDIDATES = [
    ("sd", "2x_AniSD_AC_G6i2a_Compact_72500.pth"),
    ("sd-fast", "2x_Ani4Kv2_G6i2_UltraCompact_105K.pth"),
    ("sd-janai", "2x_AnimeJaNai_SD_V1beta34_Compact.pth"),
    ("sd-span", "2x_AniSD_G6i1_SPAN_215K.pth"),
    ("span-ac", "2x_AniSD_AC_G6i2b_SPAN_190K.pth"),
    ("span-dc", "2x_AniSD_DC_SPAN_92500.pth"),
    ("ditn", "2x_AniScale2_DITN_i16_75K.pth"),
    ("suc", "2x_AnimeJaNai_HD_V3_SuperUltraCompact.pth"),
    ("uc-janai", "2x_AnimeJaNai_HD_V3_UltraCompact.pth"),
    ("craft", "2x_AniSD_AC_CRAFT_92500.pth"),
    ("omni", "2x_AniScale2_Omni_i16_40K.pth"),
    ("toon", "2x_AniToon_RPLKSRS_242500.pth"),
    ("sd-hq", "2x_AniSD_RealPLKSR_140K.pth"),
    ("mosr", "2x-AnimeSharpV2_MoSR_Soft.pth"),
    ("anime", "realesr-animevideov3.pth"),
    ("distill-uc", "2x_distilled_UltraCompact.pth"),
]

ap = argparse.ArgumentParser()
ap.add_argument("--rounds", type=int, default=5)
ap.add_argument("--compile", action="store_true")
ap.add_argument("--only", nargs="*")
ap.add_argument("--out", default="bench_msel.json")
args = ap.parse_args()

cands = CANDIDATES
if args.only:
    cands = [c for c in CANDIDATES if c[0] in args.only]


def gpu_busy():
    """他 process 込みの GPU 使用率(%)。取れなければ -1"""
    try:
        p = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5)
        return int(p.stdout.strip().splitlines()[0])
    except Exception:
        return -1


x = torch.rand(1, 3, H, W, device="cuda", dtype=torch.half)
x = x.contiguous(memory_format=torch.channels_last)

loaded = {}
for name, fname in cands:
    path = MODELS_DIR / fname
    if not path.exists():
        print(f"{name}: 重みがありません {path}")
        continue
    try:
        model, scale, arch = load_model(path)
    except Exception as exc:
        print(f"{name}: 読込失敗 {type(exc).__name__}: {str(exc)[:60]}")
        continue
    model = model.to(memory_format=torch.channels_last)
    n = sum(q.numel() for q in model.parameters())
    fn = model
    if args.compile:
        fn = torch.compile(model)
    loaded[name] = dict(fn=fn, model=model, scale=scale, arch=arch, param=n,
                        fps=[], busy=[])
    print(f"読込 {name:10s} {arch.split('(')[0][:20]:20s} x{scale} {n / 1e6:.3f}M",
          flush=True)

# warmup（compile も含めてここで済ませる）
for name, d in loaded.items():
    with torch.no_grad():
        for _ in range(6):
            d["fn"](x)
torch.cuda.synchronize()
print("warmup 完了", flush=True)


def timed(fn, it):
    with torch.no_grad():
        torch.cuda.synchronize()
        t = time.perf_counter()
        for _ in range(it):
            fn(x)
        torch.cuda.synchronize()
    return it / (time.perf_counter() - t)


for r in range(args.rounds):
    for name, d in loaded.items():
        it = 30 if d["param"] < 1e6 else (15 if d["param"] < 3e6 else 6)
        b0 = gpu_busy()
        f = timed(d["fn"], it)
        d["fps"].append(f)
        d["busy"].append(b0)
    print(f"round {r + 1}/{args.rounds} 済", flush=True)

print()
print(f"{'name':10s} {'arch':16s} {'param':>8s} {'median':>9s} {'best':>9s} "
      f"{'ばらつき':>8s}")
out = []
for name, d in loaded.items():
    a = np.array(d["fps"])
    med, best = float(np.median(a)), float(a.max())
    spread = (a.max() - a.min()) / med * 100
    print(f"{name:10s} {d['arch'].split('(')[0][:16]:16s} {d['param'] / 1e6:7.3f}M "
          f"{med:7.1f}fps {best:7.1f}fps {spread:7.1f}%")
    out.append(dict(name=name, arch=d["arch"], scale=d["scale"], param=d["param"],
                    median_fps=med, best_fps=best, all_fps=list(a),
                    busy=d["busy"], compiled=args.compile))
(HERE / args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1),
                             encoding="utf-8")
print(f"\n書きました: {HERE / args.out}")
