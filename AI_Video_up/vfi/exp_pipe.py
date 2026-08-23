"""1080p の rawvideo を pipe で受け取る速さ。end-to-end の律速がここだったので測る。

720x480 の vup では 695 fps 出ていたが、1920x1080 は 1枚 6.2MB で 6.3倍重い。
補間で出力frameが倍になる前に、**入力を読む所**が天井になっていないかを確かめる。
"""
import subprocess
import time

import numpy as np
import torch

import vfilib as V

W, H = V.W, V.H
N = W * H * 3
SRC = str(V.WORK / "B_talk.mkv")


def read_loop(bufsize, pinned, pool=24, chunked=False):
    p = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", SRC, "-fps_mode", "passthrough",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
        stdout=subprocess.PIPE, bufsize=bufsize)
    if pinned:
        bufs = [torch.empty((H, W, 3), dtype=torch.uint8, pin_memory=True)
                for _ in range(pool)]
        views = [b.numpy() for b in bufs]
    else:
        views = [np.empty((H, W, 3), np.uint8) for _ in range(pool)]
    k = 0
    t0 = time.time()
    while True:
        mv = memoryview(views[k % pool].reshape(-1))
        if chunked:
            off = 0
            while off < N:
                g = p.stdout.readinto(mv[off:])
                if not g:
                    break
                off += g
            got = off
        else:
            got = p.stdout.readinto(mv)
        if not got or got < N:
            break
        k += 1
    dt = time.time() - t0
    try:
        p.stdout.close()
    except Exception:
        pass
    p.wait()
    return k, dt


CASES = [
    ("bufsize=W*H*3*8 / pinned", N * 8, True, False),
    ("bufsize=既定(-1) / pinned", -1, True, False),
    ("bufsize=既定(-1) / 通常memory", -1, False, False),
    ("bufsize=1MB / pinned / 分割読み", 1 << 20, True, True),
]

if __name__ == "__main__":
    for label, bs, pin, ch in CASES:
        k, dt = read_loop(bs, pin, chunked=ch)
        fps = k / dt if dt else 0
        print(f"  {label:34s} {k:4d} frame / {dt:5.2f}s = {fps:6.1f} fps "
              f"({k*N/dt/1e6:5.0f} MB/s)", flush=True)
        V.record("pipe_read", dict(case=label, w=W, h=H, frames=k,
                                   sec=round(dt, 2), fps=round(fps, 1),
                                   mbps=round(k * N / dt / 1e6, 1)))
