"""exp_x4enc - x4出力で nvenc preset が SR の GPU 時間を奪う件を詰める。

lead 実測: 2880x1920 で -preset p7 27.4s / p4 13.8s。SR 側は何も変えていないのに
SR の stream 占有が 25.3ms -> 13.2ms へ半減した。nvenc が別 process の CUDA
context として SR kernel と時分割されている。

出す物:
  A. 総時間: preset 別 + p7 から個別 knob を外した時の回復量 (犯人の特定)
  B. 画質: 同一 cq24 での size と、可逆SR出力に対する VMAF/PSNR/SSIM
  C. p4 の cq を下げて p7 cq24 と同等画質にした時、まだ速いか
  D. libx264 (CPU encode) が同等画質になる preset と、その時の総時間
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
PY = str(HERE / "venv/Scripts/python.exe")
SRC = HERE.parent / "サンプル.mp4"
TMP = Path(os.environ["TEMP"])
REF = TMP / "sr_x4_ref.mkv"
E2E_LIMIT = 15      # 総時間計測に使う source 秒数
REF_LIMIT = 6       # 可逆基準に使う source 秒数 (2880x1920 は嵩む)

# A: 総時間。p7 から knob を1つずつ外し、どれが GPU 時間を食っているか見る。
E2E = [
    ("p7 (現行既定)", "-preset p7 -cq 24"),
    ("p4", "-preset p4 -cq 24"),
    ("p1", "-preset p1 -cq 24"),
    ("p7 -multipass disabled", "-preset p7 -cq 24 -multipass disabled"),
    ("p7 -rc-lookahead 0", "-preset p7 -cq 24 -rc-lookahead 0"),
    ("p7 -bf 0", "-preset p7 -cq 24 -bf 0"),
    ("p7 -spatial-aq 0 -temporal-aq 0",
     "-preset p7 -cq 24 -spatial-aq 0 -temporal-aq 0"),
    ("p7 -weighted_pred 0", "-preset p7 -cq 24 -weighted_pred 0"),
    ("p7 -tune ll", "-preset p7 -cq 24 -tune ll"),
    ("p7 + split_encode_mode 3", "-preset p7 -cq 24 -split_encode_mode 3"),
    ("p4 + split_encode_mode 3", "-preset p4 -cq 24 -split_encode_mode 3"),
    ("libx264 ultrafast crf20", "-preset ultrafast -crf 20"),
    ("libx264 superfast crf20", "-preset superfast -crf 20"),
    ("libx264 veryfast crf20", "-preset veryfast -crf 20"),
]

# B/C/D: 画質。encode のみ (SR を回さないので GPU 時間は僅か)。
QUAL = [
    ("p7 cq24", "hevc_nvenc", "-preset p7 -cq 24"),
    ("p5 cq24", "hevc_nvenc", "-preset p5 -cq 24"),
    ("p4 cq24", "hevc_nvenc", "-preset p4 -cq 24"),
    ("p1 cq24", "hevc_nvenc", "-preset p1 -cq 24"),
    ("p4 cq22", "hevc_nvenc", "-preset p4 -cq 22"),
    ("p4 cq21", "hevc_nvenc", "-preset p4 -cq 21"),
    ("p4 cq20", "hevc_nvenc", "-preset p4 -cq 20"),
    ("x264 ultrafast crf20", "libx264", "-preset ultrafast -crf 20"),
    ("x264 superfast crf20", "libx264", "-preset superfast -crf 20"),
    ("x264 veryfast crf22", "libx264", "-preset veryfast -crf 22"),
]


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="ignore", **kw)


def bg_sm(label):
    r = sh(["nvidia-smi", "dmon", "-s", "u", "-c", "3"])
    print(f"[背景sm {label}]")
    for ln in r.stdout.strip().splitlines()[2:]:
        print("   ", ln)


def e2e(label, eargs, enc=None):
    enc = enc or ("libx264" if "crf" in eargs else "hevc_nvenc")
    t0 = time.perf_counter()
    r = sh([PY, str(HERE / "vup.py"), str(SRC), "--model", "anime",
            "--scale", "4", "--limit", str(E2E_LIMIT), "--suffix", "_x4t",
            "--encoder", enc, "--encoder-args", eargs])
    el = time.perf_counter() - t0
    if r.returncode != 0:
        print(f"{label:34s} FAILED {r.stdout[-300:]}{r.stderr[-300:]}")
        return None
    m = re.search(r"処理 ([\d.]+)s", r.stdout)
    proc = float(m.group(1)) if m else float("nan")
    m = re.search(r"SR ([\d.]+) fps", r.stdout)
    srfps = float(m.group(1)) if m else float("nan")
    m = re.search(r"pipe書込 ([\d.]+)s", r.stdout)
    pw = float(m.group(1)) if m else float("nan")
    print(f"{label:34s} 総{el:6.1f}s  処理{proc:6.1f}s  "
          f"SR {srfps:6.1f}fps  pipe書込{pw:5.2f}s", flush=True)
    return {"label": label, "eargs": eargs, "enc": enc, "wall": el,
            "proc": proc, "sr_fps": srfps, "pipe_w": pw}


def make_ref():
    if REF.exists():
        print(f"基準は既にあります ({REF.stat().st_size/1e6:.0f} MB)")
        return
    out = HERE.parent / "サンプル_x4ref.mkv"
    r = sh([PY, str(HERE / "vup.py"), str(SRC), "--model", "anime",
            "--scale", "4", "--limit", str(REF_LIMIT), "--suffix", "_x4ref",
            "--encoder", "ffv1", "--encoder-args", "-level 3"])
    src = out if out.exists() else out.with_suffix(".mp4")
    if not src.exists():
        raise SystemExit(f"基準を作れません: {r.stdout[-400:]}{r.stderr[-400:]}")
    src.replace(REF)
    print(f"基準: {REF} {REF.stat().st_size/1e6:.0f} MB")


def metrics(path):
    out = {}
    for lav, pat, key in (("libvmaf", r"VMAF score: ([\d.]+)", "vmaf"),
                          ("psnr", r"average:([\d.]+)", "psnr"),
                          ("ssim", r"All:([\d.]+)", "ssim")):
        r = sh(["ffmpeg", "-v", "info", "-i", str(path), "-i", str(REF),
                "-lavfi", f"[0:v][1:v]{lav}", "-f", "null", "-"])
        m = re.search(pat, r.stderr)
        out[key] = float(m.group(1)) if m else float("nan")
    return out


def quality():
    make_ref()
    res = []
    for label, enc, eargs in QUAL:
        o = TMP / ("x4q_" + re.sub(r"\W+", "", label) + ".mp4")
        t0 = time.perf_counter()
        r = sh(["ffmpeg", "-v", "error", "-y", "-i", str(REF),
                "-c:v", enc] + eargs.split() + ["-an", str(o)])
        enc_el = time.perf_counter() - t0
        if r.returncode != 0 or not o.exists():
            print(f"{label:24s} FAILED {r.stderr[-200:]}")
            continue
        m = metrics(o)
        m.update(label=label, enc=enc, eargs=eargs,
                 size=o.stat().st_size, enc_sec=enc_el)
        res.append(m)
        print(f"  {label:24s} {m['size']/1e6:7.2f}MB VMAF {m['vmaf']:6.2f} "
              f"PSNR {m['psnr']:7.3f} SSIM {m['ssim']:.6f}", flush=True)
        o.unlink(missing_ok=True)
    return res


def main():
    print(f"=== A. 総時間 (x4 2880x1920, source {E2E_LIMIT}秒) ===")
    a = [x for x in (e2e(l, e) for l, e in E2E) if x]
    print(f"\n=== B/C/D. 画質 (可逆SR出力 {REF_LIMIT}秒 に対して) ===")
    b = quality()

    if a:
        base = next((x for x in a if x["label"].startswith("p7 (")), a[0])
        print(f"\n--- 総時間まとめ (現行 {base['wall']:.1f}s 比) ---")
        for x in sorted(a, key=lambda y: y["wall"]):
            print(f"{x['label']:34s} {x['wall']:6.1f}s  "
                  f"{base['wall']/x['wall']:4.2f}x速  SR {x['sr_fps']:6.1f}fps")
    if b:
        base = next((x for x in b if x["label"] == "p7 cq24"), b[0])
        print(f"\n--- 画質まとめ ({base['label']} 比) ---")
        for x in b:
            print(f"{x['label']:24s} {x['size']/1e6:7.2f}MB "
                  f"({x['size']/base['size']:4.2f}x)  "
                  f"VMAF {x['vmaf']:6.2f} ({x['vmaf']-base['vmaf']:+5.2f})  "
                  f"PSNR {x['psnr']:7.3f} ({x['psnr']-base['psnr']:+5.3f})")
    (HERE / "exp_x4enc_result.json").write_text(
        json.dumps({"e2e": a, "quality": b}, ensure_ascii=False, indent=1),
        encoding="utf-8")


if __name__ == "__main__":
    bg_sm("測定前")
    with gpu_lock("io-pipeline", "x4 encoder preset の速度と画質", timeout=5400):
        main()
    bg_sm("測定後")
    for p in (HERE.parent / "サンプル_x4t.mp4",):
        p.unlink(missing_ok=True)
    REF.unlink(missing_ok=True)
