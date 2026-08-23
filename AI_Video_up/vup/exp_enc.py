"""encode側が律速になっていないかを見る。

vup.py の既定は `-preset p7` だが README の測定は p5。p7 は NVENC の最遅presetで、
SR を2倍にしても encode が頭打ちなら全体は速くならない。
乱数(最悪値)と実素材の拡大frame(現実に近い)の両方で測る。
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
TMP = Path(r"C:\Users\sanka\AppData\Local\Temp\claude"
           r"\C--01-work-00-Git-toybox-AI-Video-up"
           r"\a69516b7-fb23-4024-ad85-73e2610bad30\scratchpad")


def real_frames(video, w, h, n):
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video), "-frames:v", str(n),
         "-vf", f"scale={w}:{h}:flags=lanczos", "-f", "rawvideo",
         "-pix_fmt", "bgr24", "-"], capture_output=True).stdout
    k = len(out) // (w * h * 3)
    return [out[i * w * h * 3:(i + 1) * w * h * 3] for i in range(k)]


def bench(w, h, frames, args, tag):
    TMP.mkdir(parents=True, exist_ok=True)
    cmd = (["ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
            "-s", f"{w}x{h}", "-r", "30", "-i", "-"] + args +
           ["-y", str(TMP / "enc_test.mp4")])
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    t = time.time()
    for f in frames:
        p.stdin.write(f)
    p.stdin.close()
    p.wait()
    el = time.time() - t
    print(f"  {tag:26s} {w}x{h}: {len(frames)/el:7.1f} fps")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--video", default=str(HERE.parent / "サンプル.mp4"))
    args = ap.parse_args()
    w, h = 1440, 960

    real = real_frames(args.video, w, h, args.n)
    noise = [np.random.randint(0, 255, (h, w, 3), np.uint8).tobytes()
             for _ in range(min(args.n, 60))]

    for label, frames in (("実素材を拡大したframe", real), ("乱数(最悪値)", noise)):
        print(f"{label}  {len(frames)}枚")
        for preset in ("p1", "p4", "p5", "p7"):
            bench(w, h, frames,
                  ["-c:v", "hevc_nvenc", "-preset", preset, "-cq", "24",
                   "-pix_fmt", "yuv420p"], f"hevc_nvenc {preset}")


if __name__ == "__main__":
    main()
