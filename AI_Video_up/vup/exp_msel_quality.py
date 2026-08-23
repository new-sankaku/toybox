"""model 別の画質を、正解画像のある形と無い形の両方で測る

既存の metric_quality.py は正解が無いため「鮮鋭度・平坦部ノイズ・整合性」の
3つの無参照量だけを見ている。この3つには次の弱点がある。

- 鮮鋭度(Sobel 99%点) は輪郭を過剰に立てた model ほど高く出る。リンギングと
  本物の細部を区別できないので、単体では品質の順位付けに使えない。
- 平坦部ノイズ は「平坦」の判定を出力自身の勾配から作っている。全体を
  ぼかした model ほど平坦と判定される面積が広がり、自分に有利な mask を
  自分で作ってしまう(循環)。mask は入力から作るべき。
- 整合性(縮小して原本とのPSNR) は何もしない恒等写像で最大になる。
  「原本から離れていない」ことしか言えず、上がったか下がったかを言えない。

そこで正解のある課題を1つ足す。

【A】半分に落として戻す（正解あり）
  実素材 720x480 を正解とし、360x240 へ縮小 + h264 再圧縮して劣化させ、
  各 model で 720x480 へ戻して正解と比べる。PSNR / SSIM / LPIPS が測れる。
  この課題の劣化(縮小+圧縮)は本番(DVD 720x480 を 1440x960 へ)と同種なので、
  model の順位はそのまま移る。
  注意: 正解自体が DVD 由来のリンギングや dot crawl を含むので、それらを
  「直してしまう」model は PSNR で損をする。輪郭部だけの PSNR も併記して、
  線の位置と太さが合っているかを分けて見る。

【B】高品質 model との一致度（本番の解像度で）
  本番と同じ 720x480 -> 1440x960 で、実用枠で最高品質の sd-hq(RealPLKSR
  7.37M) の出力を基準に、候補の出力がどれだけ離れるかを測る。
  「速い model にして何を失うか」を直接見るための量。

【C】無参照量（平坦 mask の循環を直した版）
【D】時間方向の安定性
  連続する2 frame を通し、出力側の変化量が入力側の変化量の何倍になるかを見る。
  1.0 より大きいほど、入力の僅かな揺れを増幅している = ちらつく。
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
REF = "sd-hq"

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

ap = argparse.ArgumentParser()
ap.add_argument("--models", nargs="*")
ap.add_argument("--crf", type=int, default=20, help="Aの劣化で使う h264 crf")
args = ap.parse_args()
names = args.models or list(MODELS)
torch.backends.cudnn.benchmark = True


# ---------------------------------------------------------------- 素材の用意
def grab_pair(ss):
    """時刻 ss から連続2 frame を 720x480 で取る"""
    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(ss), "-i", SRC, "-frames:v", "2",
         "-vf", f"scale={W}:{H}:flags=neighbor", "-f", "rawvideo",
         "-pix_fmt", "bgr24", "-"], capture_output=True)
    n = W * H * 3
    return [np.frombuffer(p.stdout[i * n:(i + 1) * n], np.uint8).reshape(H, W, 3).copy()
            for i in range(2)]


def degrade(frames, crf):
    """720x480 -> 360x240 へ縮小し h264 で往復させる（Aの入力を作る）"""
    CACHE.mkdir(exist_ok=True)
    raw = CACHE / "lr_raw.bin"
    small = [cv2.resize(f, (W // 2, H // 2), interpolation=cv2.INTER_AREA)
             for f in frames]
    raw.write_bytes(b"".join(f.tobytes() for f in small))
    mp4 = CACHE / "lr.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
         "-s", f"{W // 2}x{H // 2}", "-r", "24", "-i", str(raw),
         "-c:v", "libx264", "-crf", str(crf), "-pix_fmt", "yuv420p",
         "-g", "1", str(mp4)], check=True)   # frame同士は無関係なので all-intra
    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(mp4), "-f", "rawvideo",
         "-pix_fmt", "bgr24", "-"], capture_output=True)
    n = (W // 2) * (H // 2) * 3
    return [np.frombuffer(p.stdout[i * n:(i + 1) * n], np.uint8)
            .reshape(H // 2, W // 2, 3).copy() for i in range(len(small))]


print("素材を用意します", flush=True)
pairs = [grab_pair(t) for t in TIMES]
gt = [p[0] for p in pairs]              # 720x480 正解（Aで使う）
gt2 = [p[1] for p in pairs]             # その次の frame（Dで使う）
lr = degrade(gt, args.crf)              # 360x240 劣化（Aの入力）
print(f"  正解 {len(gt)}枚 / 劣化入力 {len(lr)}枚", flush=True)

import lpips  # noqa: E402
LP = lpips.LPIPS(net="alex", verbose=False).cuda()


def to_t(img):
    x = torch.from_numpy(img).cuda().permute(2, 0, 1).unsqueeze(0)
    return x.half().div_(255.0).contiguous(memory_format=torch.channels_last)


def to_np(y):
    return (y[0].permute(1, 2, 0) * 255).round().clamp(0, 255).to(
        torch.uint8).cpu().numpy()


def lpips_of(a, b):
    """a,b: BGR uint8 同サイズ"""
    def prep(im):
        t = torch.from_numpy(im[:, :, ::-1].copy()).cuda().permute(2, 0, 1)
        return (t.float() / 127.5 - 1.0).unsqueeze(0)
    with torch.no_grad():
        return float(LP(prep(a), prep(b)).item())


def psnr(a, b):
    mse = float(np.mean((a.astype(np.float32) - b.astype(np.float32)) ** 2))
    return 99.0 if mse == 0 else 10 * np.log10(255.0 ** 2 / mse)


def edge_mask(ref):
    """正解側の輪郭から mask を作る（出力から作ると循環するので必ず正解側）"""
    g = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY)
    m = cv2.Laplacian(cv2.GaussianBlur(g, (0, 0), 1.0), cv2.CV_32F)
    m = np.abs(m)
    return m > np.percentile(m, 92)


def psnr_masked(a, b, mask):
    d = (a.astype(np.float32) - b.astype(np.float32)) ** 2
    mse = float(d[mask].mean())
    return 99.0 if mse == 0 else 10 * np.log10(255.0 ** 2 / mse)


def ssim_of(a, b):
    from skimage.metrics import structural_similarity as ss
    return float(ss(cv2.cvtColor(a, cv2.COLOR_BGR2GRAY),
                    cv2.cvtColor(b, cv2.COLOR_BGR2GRAY), data_range=255))


def noref(out, src_up):
    """C: 鮮鋭度と平坦部ノイズ。平坦 mask は入力(src_up)から作る"""
    g = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gs = cv2.cvtColor(src_up, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, 3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, 3)
    sharp = float(np.percentile(np.sqrt(gx * gx + gy * gy), 99))
    mx = cv2.Sobel(gs, cv2.CV_32F, 1, 0, 3)
    my = cv2.Sobel(gs, cv2.CV_32F, 0, 1, 3)
    mag_src = np.sqrt(mx * mx + my * my)
    # anime は勾配ちょうど0の画素が4割を超えるので、< だと mask が空になり
    # 平坦部ノイズが nan になる。<= にする。
    flat = mag_src <= np.percentile(mag_src, 40)
    k = np.ones((5, 5), np.float32) / 25
    mean = cv2.filter2D(g, -1, k)
    var = cv2.filter2D(g * g, -1, k) - mean * mean
    noise = float(np.sqrt(np.maximum(var[flat], 0)).mean())
    return sharp, noise


def run(model, scale, imgs):
    outs = []
    with torch.no_grad():
        for f in imgs:
            y = model(to_t(f)).clamp_(0, 1)
            if scale == 4:
                y = torch.nn.functional.avg_pool2d(y, 2)
            outs.append(to_np(y))
    return outs


# ---------------------------------------------------------------- 測定
masks = [edge_mask(g) for g in gt]
src_up = [cv2.resize(f, (W * 2, H * 2), interpolation=cv2.INTER_LANCZOS4) for f in gt]

results = {}
ref_out = None
order = [n for n in names if n != REF]
if REF in names or True:
    order = [REF] + order          # 基準を先に走らせて保持する

for name in order:
    if name not in MODELS:
        print(f"{name}: 未登録")
        continue
    path = MODELS_DIR / MODELS[name]
    if not path.exists():
        print(f"{name}: 重み無し")
        continue
    model, scale, arch = load_model(path)
    model = model.to(memory_format=torch.channels_last)
    param = sum(q.numel() for q in model.parameters())

    # A: 劣化入力 -> 720x480、正解と比較
    a_out = run(model, scale, lr)
    A = np.array([[psnr(o, g), ssim_of(o, g), lpips_of(o, g),
                   psnr_masked(o, g, m)]
                  for o, g, m in zip(a_out, gt, masks)]).mean(axis=0)

    # B/C/D: 本番解像度 720x480 -> 1440x960
    b_out = run(model, scale, gt)
    b_out2 = run(model, scale, gt2)
    C = np.array([noref(o, s) for o, s in zip(b_out, src_up)]).mean(axis=0)

    din = np.array([np.abs(a.astype(np.float32) - b.astype(np.float32)).mean()
                    for a, b in zip(gt, gt2)])
    dout = np.array([np.abs(a.astype(np.float32) - b.astype(np.float32)).mean()
                     for a, b in zip(b_out, b_out2)])
    D = float((dout / np.maximum(din, 1e-6)).mean())

    if name == REF:
        ref_out = b_out
        B = (99.0, 0.0)
    else:
        B = (float(np.mean([psnr(o, r) for o, r in zip(b_out, ref_out)])),
             float(np.mean([lpips_of(o, r) for o, r in zip(b_out, ref_out)])))

    results[name] = dict(arch=arch.split("(")[0], param=param,
                         a_psnr=A[0], a_ssim=A[1], a_lpips=A[2], a_epsnr=A[3],
                         b_psnr=B[0], b_lpips=B[1],
                         c_sharp=C[0], c_noise=C[1], d_amp=D)
    print(f"済 {name}", flush=True)
    del model
    torch.cuda.empty_cache()

# lanczos を対照に置く
a_lanc = [cv2.resize(f, (W, H), interpolation=cv2.INTER_LANCZOS4) for f in lr]
A = np.array([[psnr(o, g), ssim_of(o, g), lpips_of(o, g), psnr_masked(o, g, m)]
              for o, g, m in zip(a_lanc, gt, masks)]).mean(axis=0)
C = np.array([noref(s, s) for s in src_up]).mean(axis=0)
dout = np.array([np.abs(cv2.resize(a, (W * 2, H * 2), interpolation=cv2.INTER_LANCZOS4)
                        .astype(np.float32)
                        - cv2.resize(b, (W * 2, H * 2), interpolation=cv2.INTER_LANCZOS4)
                        .astype(np.float32)).mean() for a, b in zip(gt, gt2)])
din = np.array([np.abs(a.astype(np.float32) - b.astype(np.float32)).mean()
                for a, b in zip(gt, gt2)])
results["(lanczos)"] = dict(
    arch="-", param=0, a_psnr=A[0], a_ssim=A[1], a_lpips=A[2], a_epsnr=A[3],
    b_psnr=float(np.mean([psnr(cv2.resize(f, (W * 2, H * 2),
                                          interpolation=cv2.INTER_LANCZOS4), r)
                          for f, r in zip(gt, ref_out)])),
    b_lpips=float(np.mean([lpips_of(cv2.resize(f, (W * 2, H * 2),
                                               interpolation=cv2.INTER_LANCZOS4), r)
                           for f, r in zip(gt, ref_out)])),
    c_sharp=C[0], c_noise=C[1], d_amp=float((dout / np.maximum(din, 1e-6)).mean()))

print()
hdr = (f"{'model':12s} {'param':>7s} | {'A_PSNR':>7s} {'A_SSIM':>7s} "
       f"{'A_LPIPS':>8s} {'A_輪郭':>7s} | {'B_一致':>7s} {'B_LP':>6s} | "
       f"{'鮮鋭':>6s} {'平坦雑':>7s} {'増幅':>6s}")
print(hdr)
print("-" * len(hdr))
for n, r in sorted(results.items(), key=lambda kv: -kv[1]["a_psnr"]):
    print(f"{n:12s} {r['param'] / 1e6:6.2f}M | {r['a_psnr']:7.3f} {r['a_ssim']:7.4f} "
          f"{r['a_lpips']:8.4f} {r['a_epsnr']:7.3f} | {r['b_psnr']:7.2f} "
          f"{r['b_lpips']:6.3f} | {r['c_sharp']:6.1f} {r['c_noise']:7.3f} "
          f"{r['d_amp']:6.3f}")

import json  # noqa: E402
(HERE / "quality_msel.json").write_text(
    json.dumps(results, ensure_ascii=False, indent=1, default=float),
    encoding="utf-8")
print(f"\n書きました: {HERE / 'quality_msel.json'}")
