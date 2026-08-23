"""exp_x4q2 - exp_x4enc で取り損ねた画質を埋める。

最速だった `-tune ll` の画質が空欄のままでは推奨が出せない。
基準 (sr_x4_ref.mkv) は前回の物をそのまま使う。
"""
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\sanka\AppData\Local\Temp\claude"
                   r"\C--01-work-00-Git-toybox-AI-Video-up"
                   r"\a69516b7-fb23-4024-ad85-73e2610bad30\scratchpad")
from gpulock import gpu_lock  # noqa: E402

TMP = Path(os.environ["TEMP"])
REF = TMP / "sr_x4_ref.mkv"
QUAL = [
    ("p7 cq24 (基準)", "hevc_nvenc", "-preset p7 -cq 24"),
    ("p7 cq24 -tune ll", "hevc_nvenc", "-preset p7 -cq 24 -tune ll"),
    ("p4 cq24 -tune ll", "hevc_nvenc", "-preset p4 -cq 24 -tune ll"),
    ("p4 cq24 + split3", "hevc_nvenc", "-preset p4 -cq 24 -split_encode_mode 3"),
    ("p4 cq22 + split3", "hevc_nvenc", "-preset p4 -cq 22 -split_encode_mode 3"),
    ("x264 superfast crf20", "libx264", "-preset superfast -crf 20"),
    ("x264 veryfast crf22", "libx264", "-preset veryfast -crf 22"),
]


def sh(c):
    return subprocess.run(c, capture_output=True, text=True,
                          encoding="utf-8", errors="ignore")


def main():
    for label, enc, ea in QUAL:
        o = TMP / ("x4r_" + re.sub(r"\W+", "", label) + ".mp4")
        r = sh(["ffmpeg", "-v", "error", "-y", "-i", str(REF), "-c:v", enc]
               + ea.split() + ["-an", str(o)])
        if r.returncode != 0 or not o.exists():
            print(f"{label:24s} FAILED {r.stderr[-200:]}", flush=True)
            continue
        m = {}
        for lav, pat, key in (("libvmaf", r"VMAF score: ([\d.]+)", "vmaf"),
                              ("psnr", r"average:([\d.]+)", "psnr"),
                              ("ssim", r"All:([\d.]+)", "ssim")):
            rr = sh(["ffmpeg", "-v", "info", "-i", str(o), "-i", str(REF),
                     "-lavfi", f"[0:v][1:v]{lav}", "-f", "null", "-"])
            g = re.search(pat, rr.stderr)
            m[key] = float(g.group(1)) if g else float("nan")
        print(f"{label:24s} {o.stat().st_size/1e6:7.2f}MB VMAF {m['vmaf']:6.2f}"
              f" PSNR {m['psnr']:7.3f} SSIM {m['ssim']:.6f}", flush=True)
        o.unlink(missing_ok=True)


if __name__ == "__main__":
    with gpu_lock("io-pipeline", "x4 画質の埋め合わせ", timeout=3600):
        main()
