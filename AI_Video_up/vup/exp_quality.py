"""exp_quality - NVENC が遊んでいる余力を画質へ回せるか、実素材で境界を出す。

lead 計測より end-to-end 中の enc utilization は 8〜22%、sm は 90〜97%。
つまり encode 側には 4〜10倍の余力があり、総時間を増やさずに画質へ回せる。
どこまで盛れるかの境界を、実際の SR 出力を可逆で残したものを基準に測る。

  1. vup.py で実SR出力を作り、可逆(ffv1)で保存 -> 基準
  2. 基準から各 encoder 設定で encode し、size と VMAF/PSNR/SSIM を出す
  3. 同じ設定の encode 脚だけの速度を、生 nv12 の pipe 投入で測る
     (SR が回す ~100 fps に対して余裕があるかの判定に使う)
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\Users\sanka\AppData\Local\Temp\claude"
                   r"\C--01-work-00-Git-toybox-AI-Video-up"
                   r"\a69516b7-fb23-4024-ad85-73e2610bad30\scratchpad")
from gpulock import gpu_lock  # noqa: E402

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "サンプル.mp4"
TMP = Path(os.environ["TEMP"])
REF = TMP / "sr_ref.mkv"
FW, FH = 1440, 960
NVSZ = FW * FH * 3 // 2
SPEED_N = 600

# 現行は -preset p7 -cq 24。preset は既に最高なので、余力は
#   (a) cq を下げる (bitrate を上げて画質を上げる)
#   (b) multipass / AQ / b-frame / lookahead を盛る (bitrate 据え置きで効率を上げる)
# の2方向。両方測る。
FULL = ["-multipass", "fullres", "-rc-lookahead", "32", "-bf", "4",
        "-b_ref_mode", "middle", "-spatial-aq", "1", "-temporal-aq", "1",
        "-aq-strength", "8"]
CONFIGS = [
    ("現行 p7 cq24", ["-preset", "p7", "-cq", "24"]),
    ("p7 cq22", ["-preset", "p7", "-cq", "22"]),
    ("p7 cq20", ["-preset", "p7", "-cq", "20"]),
    ("p7 cq18", ["-preset", "p7", "-cq", "18"]),
    ("p7 cq24 + multipass", ["-preset", "p7", "-cq", "24",
                             "-multipass", "fullres"]),
    ("p7 cq24 + bf4 + bref", ["-preset", "p7", "-cq", "24", "-bf", "4",
                              "-b_ref_mode", "middle"]),
    ("p7 cq24 + AQ", ["-preset", "p7", "-cq", "24", "-spatial-aq", "1",
                      "-temporal-aq", "1", "-aq-strength", "8"]),
    ("p7 cq24 + lookahead32", ["-preset", "p7", "-cq", "24",
                               "-rc-lookahead", "32"]),
    ("p7 cq24 + 全部盛り", ["-preset", "p7", "-cq", "24"] + FULL),
    ("p7 cq20 + 全部盛り", ["-preset", "p7", "-cq", "20"] + FULL),
    ("p7 cq18 + 全部盛り", ["-preset", "p7", "-cq", "18"] + FULL),
]


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="ignore", **kw)


def bg_sm(label):
    r = sh(["nvidia-smi", "dmon", "-s", "u", "-c", "4"])
    print(f"[背景sm {label}]")
    for ln in r.stdout.strip().splitlines():
        print("   ", ln)


def make_ref(limit=40):
    """実SR出力を可逆で残す。ここだけ SM を使う。"""
    if REF.exists():
        print(f"基準は既にあります: {REF}")
        return
    out = HERE.parent / "サンプル_ref.mkv"
    r = sh([str(HERE / "venv/Scripts/python.exe"), str(HERE / "vup.py"),
            str(SRC), "--scale", "2", "--limit", str(limit),
            "--suffix", "_ref", "--encoder", "ffv1",
            "--encoder-args", "-level 3"])
    print(r.stdout[-600:] if r.returncode == 0 else r.stdout[-1500:])
    src = out if out.exists() else out.with_suffix(".mp4")
    if not src.exists():
        raise SystemExit(f"基準を作れませんでした: {r.stderr[-500:]}")
    src.replace(REF)
    print(f"基準: {REF} {REF.stat().st_size/1e6:.0f} MB")


def metrics(enc_path):
    """基準に対する VMAF / PSNR / SSIM。CPU のみ。"""
    out = {}
    r = sh(["ffmpeg", "-v", "info", "-i", str(enc_path), "-i", str(REF),
            "-lavfi", "[0:v][1:v]libvmaf", "-f", "null", "-"])
    m = re.search(r"VMAF score: ([\d.]+)", r.stderr)
    out["vmaf"] = float(m.group(1)) if m else float("nan")
    r = sh(["ffmpeg", "-v", "info", "-i", str(enc_path), "-i", str(REF),
            "-lavfi", "[0:v][1:v]psnr", "-f", "null", "-"])
    m = re.search(r"average:([\d.]+)", r.stderr)
    out["psnr"] = float(m.group(1)) if m else float("nan")
    r = sh(["ffmpeg", "-v", "info", "-i", str(enc_path), "-i", str(REF),
            "-lavfi", "[0:v][1:v]ssim", "-f", "null", "-"])
    m = re.search(r"All:([\d.]+)", r.stderr)
    out["ssim"] = float(m.group(1)) if m else float("nan")
    return out


def load_nv12(n=300):
    """基準から生 nv12 を RAM へ。encode 脚の速度計測に使う。"""
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(REF),
                          "-f", "rawvideo", "-pix_fmt", "nv12", "-"],
                         stdout=subprocess.PIPE, bufsize=NVSZ * 4)
    frames = []
    while len(frames) < n:
        buf = p.stdout.read(NVSZ)
        if len(buf) < NVSZ:
            break
        frames.append(buf)
    try:
        p.stdout.close()
        p.terminate()
    except Exception:
        pass
    p.wait()
    print(f"生nv12 {len(frames)} frame を RAM へ "
          f"({len(frames)*NVSZ/1e6:.0f} MB)")
    return frames


def enc_speed(frames, eargs, n=SPEED_N):
    cmd = (["ffmpeg", "-v", "error", "-y", "-f", "rawvideo",
            "-pix_fmt", "nv12", "-s", f"{FW}x{FH}", "-r", "30", "-i", "-",
            "-c:v", "hevc_nvenc"] + eargs + ["-f", "null", "-"])
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, bufsize=NVSZ * 4)
    t0 = time.perf_counter()
    try:
        for i in range(n):
            p.stdin.write(frames[i % len(frames)])
        p.stdin.close()
    except Exception:
        pass
    p.wait()
    el = time.perf_counter() - t0
    return n / el if p.returncode == 0 else 0.0


def main():
    make_ref()
    frames = load_nv12()
    res = []
    # 速度は round robin で2周し、drift を条件間で均す
    spd = {c[0]: [] for c in CONFIGS}
    enc_speed(frames, ["-preset", "p5"])           # warm up
    for r in range(2):
        for label, eargs in CONFIGS:
            spd[label].append(enc_speed(frames, eargs))
    for label, eargs in CONFIGS:
        o = TMP / ("qq_" + re.sub(r"\W+", "", label) + ".mp4")
        sh(["ffmpeg", "-v", "error", "-y", "-i", str(REF),
            "-c:v", "hevc_nvenc"] + eargs + ["-an", str(o)])
        m = metrics(o)
        m["label"] = label
        m["size"] = o.stat().st_size
        m["fps"] = max(spd[label])
        res.append(m)
        print(f"  {label:24s} {m['size']/1e6:6.2f}MB "
              f"VMAF {m['vmaf']:6.2f} PSNR {m['psnr']:6.3f} "
              f"SSIM {m['ssim']:.6f} encode {m['fps']:6.1f} fps", flush=True)
    base = res[0]
    print(f"\n=== 基準 {REF.name} に対して (現行 = {base['label']}) ===")
    print(f"{'設定':26s} {'size':>9s} {'VMAF':>7s} {'ΔVMAF':>7s} "
          f"{'PSNR':>7s} {'SSIM':>9s} {'encode':>9s}")
    for m in res:
        print(f"{m['label']:26s} {m['size']/1e6:6.2f}MB "
              f"{m['vmaf']:7.2f} {m['vmaf']-base['vmaf']:+7.2f} "
              f"{m['psnr']:7.3f} {m['ssim']:9.6f} {m['fps']:6.1f}fps "
              f"({m['size']/base['size']:.2f}x size)")
    (HERE / "exp_quality_result.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    bg_sm("測定前")
    with gpu_lock("io-pipeline", "nvenc 画質余力 sweep"):
        main()
    bg_sm("測定後")
