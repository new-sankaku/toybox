"""sd -> sd-fast へ変えて user が劣化に気付く frame があるかを、全長から探す

平均値では「特定の絵柄でだけ目に見える差が出る」場合を見落とす。全長 16分34秒を
等間隔に刻んで両 model を通し、**2つの出力が最も食い違う frame** を見つける。

見るのは2つ。
  (1) 気付くか  : 本番の課題 (720x480 -> 1440x960) で sd と sd-fast の出力同士を
                 比べる。差が小さければ、そもそも見分けようがない。
  (2) 劣化か    : その frame について正解ありの課題を回し、sd と sd-fast の
                 どちらが正解に近いかを見る。差があっても sd-fast の方が
                 正解に近いなら「劣化」ではない。

絵柄別にも分ける。lead の指摘どおり、細い線画・階調・暗部は壊れ方が違う。
  線画  : 輪郭画素の割合が高い frame
  階調  : 平坦な面積が広い frame
  暗部  : 平均輝度が低い frame
"""
import subprocess
import sys
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
OUT = HERE / "compare"
W, H = 720, 480
STRIDE = 4.0          # 何秒ごとに1枚見るか
A = "sd"
B = "sd-fast"
PATHS = {"sd": "2x_AniSD_AC_G6i2a_Compact_72500.pth",
         "sd-fast": "2x_Ani4Kv2_G6i2_UltraCompact_105K.pth"}
torch.backends.cudnn.benchmark = True
OUT.mkdir(exist_ok=True)


def read_all(stride):
    """1回の decode 走査で等間隔に読む（seek を frame 数だけ繰り返すより速い）"""
    p = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", SRC, "-vf", f"fps=1/{stride}",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
        stdout=subprocess.PIPE, bufsize=10 ** 8)
    n = W * H * 3
    out = []
    while True:
        b = p.stdout.read(n)
        if len(b) < n:
            break
        out.append(np.frombuffer(b, np.uint8).reshape(H, W, 3).copy())
    p.wait()
    return out


print("全長を読みます", flush=True)
frames = read_all(STRIDE)
print(f"  {len(frames)}枚 ({STRIDE}秒ごと)", flush=True)


def classify(f):
    g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32)
    sx = cv2.Sobel(g, cv2.CV_32F, 1, 0, 3)
    sy = cv2.Sobel(g, cv2.CV_32F, 0, 1, 3)
    mag = np.sqrt(sx * sx + sy * sy)
    return dict(edge=float((mag > 60).mean()),      # 線画らしさ
                flat=float((mag < 4).mean()),       # 階調らしさ
                dark=float(g.mean()))               # 暗部らしさ


stats = [classify(f) for f in frames]


def to_t(img):
    x = torch.from_numpy(img).cuda().permute(2, 0, 1).unsqueeze(0)
    return x.half().div_(255.0).contiguous(memory_format=torch.channels_last)


def to_np(y):
    return (y[0].permute(1, 2, 0) * 255).round().clamp(0, 255).to(
        torch.uint8).cpu().numpy()


def psnr(a, b):
    m = float(np.mean((a.astype(np.float32) - b.astype(np.float32)) ** 2))
    return 99.0 if m == 0 else 10 * np.log10(255.0 ** 2 / m)


def edge_psnr(a, b):
    g = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)
    m = np.abs(cv2.Laplacian(cv2.GaussianBlur(g, (0, 0), 1.0), cv2.CV_32F))
    mask = m > np.percentile(m, 92)
    d = (a.astype(np.float32) - b.astype(np.float32)) ** 2
    return 10 * np.log10(255.0 ** 2 / max(float(d[mask].mean()), 1e-9))


with gpu_lock("model-arch", f"最悪frame探索 {len(frames)}枚"):
    models = {}
    for k, v in PATHS.items():
        m, sc, _ = load_model(MODELS_DIR / v)
        models[k] = (m.to(memory_format=torch.channels_last), sc)

    # --- pass 1: 全 frame で2つの出力の食い違いを測る（画像は残さない） ---
    gap = np.zeros(len(frames))
    dmax = np.zeros(len(frames))
    with torch.no_grad():
        for i, f in enumerate(frames):
            x = to_t(f)
            oa = to_np(models[A][0](x).clamp_(0, 1))
            ob = to_np(models[B][0](x).clamp_(0, 1))
            gap[i] = psnr(oa, ob)
            dmax[i] = float(np.abs(oa.astype(int) - ob.astype(int)).max())
            if i % 50 == 0:
                print(f"  {i}/{len(frames)}", flush=True)

    print(f"\n2つの出力の一致 PSNR: 中央値 {np.median(gap):.2f}dB / "
          f"最小 {gap.min():.2f}dB / 最大 {gap.max():.2f}dB")
    print(f"画素差の最大: 中央値 {np.median(dmax):.0f} / 最悪 {dmax.max():.0f} (255中)")

    # --- 最悪 frame を選ぶ（全体 + 絵柄別）---
    picks = {"全体最悪": int(gap.argmin())}
    for nm, key, rev in [("線画", "edge", True), ("階調", "flat", True),
                         ("暗部", "dark", False)]:
        v = np.array([s[key] for s in stats])
        # その絵柄の上位25%の中で、最も食い違う frame
        sel = np.where(v >= np.percentile(v, 75) if rev
                       else v <= np.percentile(v, 25))[0]
        picks[nm + "最悪"] = int(sel[gap[sel].argmin()])
    picks["2番目"] = int(np.argsort(gap)[1])

    # --- pass 2: 選んだ frame を詳しく見る ---
    print(f"\n{'区分':10s} {'時刻':>7s} {'一致dB':>7s} {'画素差':>6s} | "
          f"{'正解へのPSNR sd':>15s} {'sd-fast':>9s} {'差':>7s} | "
          f"{'輪郭 sd':>8s} {'sd-fast':>9s} {'差':>7s}")
    print("-" * 104)
    for nm, i in picks.items():
        f = frames[i]
        small = cv2.resize(f, (W // 2, H // 2), interpolation=cv2.INTER_AREA)
        d = HERE / "_qcache"
        d.mkdir(exist_ok=True)
        (d / "w.bin").write_bytes(small.tobytes())
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo",
                        "-pix_fmt", "bgr24", "-s", f"{W // 2}x{H // 2}", "-r", "24",
                        "-i", str(d / "w.bin"), "-c:v", "libx264", "-crf", "20",
                        "-pix_fmt", "yuv420p", "-g", "1", str(d / "w.mp4")],
                       check=True)
        pr = subprocess.run(["ffmpeg", "-v", "error", "-i", str(d / "w.mp4"),
                             "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                            capture_output=True)
        lr = np.frombuffer(pr.stdout[:(W // 2) * (H // 2) * 3], np.uint8) \
            .reshape(H // 2, W // 2, 3).copy()

        row, prod = {}, {}
        with torch.no_grad():
            for k in (A, B):
                m, sc = models[k]
                row[k] = to_np(m(to_t(lr)).clamp_(0, 1))       # 正解ありの課題
                prod[k] = to_np(m(to_t(f)).clamp_(0, 1))       # 本番の課題
        pa, pb = psnr(row[A], f), psnr(row[B], f)
        ea, eb = edge_psnr(row[A], f), edge_psnr(row[B], f)
        print(f"{nm:10s} {i * STRIDE:6.0f}s {gap[i]:7.2f} {dmax[i]:6.0f} | "
              f"{pa:15.3f} {pb:9.3f} {pb - pa:+7.3f} | "
              f"{ea:8.3f} {eb:9.3f} {eb - ea:+7.3f}")

        # 差が最大の 320x320 窓を切り出して並べる
        dif = np.abs(prod[A].astype(np.int16) - prod[B].astype(np.int16)).sum(2)
        k = 320
        s = cv2.boxFilter(dif.astype(np.float32), -1, (k, k), normalize=True)
        cy, cx = np.unravel_index(s.argmax(), s.shape)
        y0 = int(np.clip(cy - k // 2, 0, prod[A].shape[0] - k))
        x0 = int(np.clip(cx - k // 2, 0, prod[A].shape[1] - k))
        tiles = []
        lz = cv2.resize(f, (W * 2, H * 2), interpolation=cv2.INTER_LANCZOS4)
        for lab, im in [("sd", prod[A]), ("sd-fast", prod[B]), ("lanczos", lz)]:
            t = np.ascontiguousarray(im[y0:y0 + k, x0:x0 + k]).copy()
            cv2.rectangle(t, (0, 0), (k - 1, 24), (0, 0, 0), -1)
            cv2.putText(t, lab, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                        (255, 255, 255), 1, cv2.LINE_AA)
            tiles.append(t)
        dv = np.clip(dif[y0:y0 + k, x0:x0 + k] * 8, 0, 255).astype(np.uint8)
        dv = cv2.cvtColor(dv, cv2.COLOR_GRAY2BGR)
        cv2.rectangle(dv, (0, 0), (k - 1, 24), (0, 0, 0), -1)
        cv2.putText(dv, "diff x8", (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (255, 255, 255), 1, cv2.LINE_AA)
        tiles.append(dv)
        cv2.imwrite(str(OUT / f"worst_{nm}_{int(i * STRIDE)}s.png"),
                    np.hstack(tiles))

    print(f"\n画像: {OUT}\\worst_*.png (sd / sd-fast / lanczos / 差分x8、等倍320px)")
