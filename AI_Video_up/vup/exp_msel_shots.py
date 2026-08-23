"""候補 model の出力を、同じ箇所で切り出して並べる（目視用）

数値だけでは線の太さ・リンギング・平坦部の質感の違いが分からないので、
等倍の切り出しを格子に並べた png を出す。
既定の切り出しは 240x160（入力座標）で、出力では 480x320 になる。
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

MODELS = {
    "sd": "2x_AniSD_AC_G6i2a_Compact_72500.pth",
    "sd-fast": "2x_Ani4Kv2_G6i2_UltraCompact_105K.pth",
    "sd-janai": "2x_AnimeJaNai_SD_V1beta34_Compact.pth",
    "sd-span": "2x_AniSD_G6i1_SPAN_215K.pth",
    "span-ac": "2x_AniSD_AC_G6i2b_SPAN_190K.pth",
    "span-dc": "2x_AniSD_DC_SPAN_92500.pth",
    "ditn": "2x_AniScale2_DITN_i16_75K.pth",
    "suc": "2x_AnimeJaNai_HD_V3_SuperUltraCompact.pth",
    "uc-janai": "2x_AnimeJaNai_HD_V3_UltraCompact.pth",
    "craft": "2x_AniSD_AC_CRAFT_92500.pth",
    "omni": "2x_AniScale2_Omni_i16_40K.pth",
    "toon": "2x_AniToon_RPLKSRS_242500.pth",
    "sd-hq": "2x_AniSD_RealPLKSR_140K.pth",
    "mosr": "2x-AnimeSharpV2_MoSR_Soft.pth",
    "anime": "realesr-animevideov3.pth",
    "ld-anime": "2x-LD-Anime-Compact.pth",
    "openproteus": "2x_OpenProteus_Compact_i2_70K.pth",
    "aniscale2": "2x_AniScale2S_Compact_i8_60K.pth",
    "modernspan": "2x_ModernSpanimationV1.pth",
    "dpoke": "digital_pokemon_compact_1_1_0.pth",
    "dpoke-l": "digital_pokemon_omnisr_1_1_0.pth",
    "smbss": "smbss_2x_Compact_16_Animation.pth",
    "uc-v2": "2x_AnimeJaNai_V2_UltraCompact_30k.pth",
    "suc-v2": "2x_AnimeJaNai_V2_SuperUltraCompact_100k.pth",
    "c-v2": "2x_AnimeJaNai_V2_Compact_36k.pth",
    "distill-uc": "2x_distilled_UltraCompact.pth",
}

SRC = r"C:\01_work\00_Git\toybox\AI_Video_up\サンプル.mp4"
MODELS_DIR = HERE / "models"
OUT = HERE / "compare_msel"
W, H = 720, 480

# (時刻, x, y, 幅, 高さ, 見出し) 入力座標
SHOTS = [
    (850.0, 0, 250, 240, 160, "金網 高周波"),
    (850.0, 470, 60, 240, 160, "金網と空の境界"),
    (700.0, 200, 120, 240, 160, "線画"),
    (415.0, 240, 100, 240, 160, "顔"),
    (200.0, 120, 200, 240, 160, "平坦部と輪郭"),
]

ap = argparse.ArgumentParser()
ap.add_argument("--models", nargs="*", default=[
    "sd-fast", "suc", "ditn", "sd", "sd-janai", "sd-span", "span-ac",
    "sd-hq", "anime"])
ap.add_argument("--cols", type=int, default=4)
args = ap.parse_args()
torch.backends.cudnn.benchmark = True
OUT.mkdir(exist_ok=True)


def grab(ss):
    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(ss), "-i", SRC, "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True)
    return np.frombuffer(p.stdout[:W * H * 3], np.uint8).reshape(H, W, 3).copy()


frames = {ss: grab(ss) for (ss, *_) in SHOTS}
results = {}
for name in args.models:
    path = MODELS_DIR / MODELS[name]
    if not path.exists():
        print(f"{name}: 重み無し")
        continue
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
    n = sum(q.numel() for q in model.parameters())
    print(f"{name:12s} {arch.split('(')[0][:20]:20s} x{scale} {n / 1e6:.3f}M")
    del model
    torch.cuda.empty_cache()

results["(lanczos)"] = {ss: cv2.resize(f, (W * 2, H * 2),
                                       interpolation=cv2.INTER_LANCZOS4)
                        for ss, f in frames.items()}
results["(nearest)"] = {ss: cv2.resize(f, (W * 2, H * 2),
                                       interpolation=cv2.INTER_NEAREST)
                        for ss, f in frames.items()}

names = list(results)
for i, (ss, cx, cy, cw, ch, label) in enumerate(SHOTS):
    tiles = []
    for name in names:
        crop = np.ascontiguousarray(
            results[name][ss][cy * 2:(cy + ch) * 2, cx * 2:(cx + cw) * 2])
        cv2.rectangle(crop, (0, 0), (crop.shape[1] - 1, 26), (0, 0, 0), -1)
        cv2.putText(crop, name, (6, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (255, 255, 255), 1, cv2.LINE_AA)
        cv2.rectangle(crop, (0, 0), (crop.shape[1] - 1, crop.shape[0] - 1),
                      (48, 48, 48), 1)
        tiles.append(crop)
    c = args.cols
    rows = [np.hstack(tiles[r:r + c]) for r in range(0, len(tiles), c)]
    wmax = max(r.shape[1] for r in rows)
    rows = [np.pad(r, ((0, 0), (0, wmax - r.shape[1]), (0, 0))) for r in rows]
    p = OUT / f"shot{i}_{int(ss)}s.png"
    cv2.imwrite(str(p), np.vstack(rows))
    print(f"書きました: {p}  ({label})")
