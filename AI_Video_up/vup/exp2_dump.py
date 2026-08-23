"""実験用の素材dump。

サンプル.mp4 から全長にわたって6区間x10秒を切り出し、raw BGR で保存する。
同じ区間の packet size / flags も揃えて保存し、bitstream 側の情報と
画素側の情報を frame 単位で突き合わせられるようにする。
"""
import subprocess
from pathlib import Path

import numpy as np

SRC = Path(r"C:\01_work\00_Git\toybox\AI_Video_up\サンプル.mp4")
OUT = Path(r"C:\Users\sanka\AppData\Local\Temp\claude"
           r"\C--01-work-00-Git-toybox-AI-Video-up"
           r"\a69516b7-fb23-4024-ad85-73e2610bad30\scratchpad\ds")
W, H = 720, 480
SEGS = [(60, 10), (240, 10), (420, 10), (600, 10), (780, 10), (900, 10)]


def packets():
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "packet=pts_time,size,flags", "-of", "csv=p=0",
         str(SRC)], capture_output=True, text=True, check=True).stdout
    pts, sz, key = [], [], []
    for line in out.splitlines():
        p = line.split(",")
        if not p[0].strip() or p[0].strip() == "N/A":
            continue
        pts.append(float(p[0]))
        sz.append(int(p[1]))
        key.append(1 if "K" in p[2] else 0)
    o = np.argsort(np.asarray(pts), kind="stable")
    return (np.asarray(pts)[o], np.asarray(sz)[o], np.asarray(key)[o])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    pts, sz, key = packets()
    for ss, dur in SEGS:
        tag = f"{ss:04d}"
        raw = OUT / f"seg{tag}.raw"
        p = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", str(ss), "-i", str(SRC),
             "-t", str(dur), "-fps_mode", "passthrough",
             "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
            capture_output=True)
        n = len(p.stdout) // (W * H * 3)
        raw.write_bytes(p.stdout[: n * W * H * 3])
        m = (pts >= ss - 1e-6) & (pts < ss + dur - 1e-6)
        np.savez(OUT / f"seg{tag}.npz", pts=pts[m], size=sz[m], key=key[m])
        print(f"{tag}: frame {n}  packet {int(m.sum())}")


if __name__ == "__main__":
    main()
