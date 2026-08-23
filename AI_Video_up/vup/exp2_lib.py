"""実験用の共通部品。dump した真の source frame を読む。"""
from pathlib import Path

import numpy as np

DS = Path(r"C:\Users\sanka\AppData\Local\Temp\claude"
          r"\C--01-work-00-Git-toybox-AI-Video-up"
          r"\a69516b7-fb23-4024-ad85-73e2610bad30\scratchpad\ds")
W, H = 720, 480
SEGS = ["0060", "0240", "0420", "0600", "0780", "0900"]


def load(tag):
    """(frames[n,H,W,3], size[n], key[n]) を返す。frameとpacketの短い方に揃える。"""
    raw = np.fromfile(DS / f"seg{tag}.raw", dtype=np.uint8)
    n_f = raw.size // (H * W * 3)
    meta = np.load(DS / f"seg{tag}.npz")
    n = min(n_f, len(meta["size"]))
    frames = raw[: n * H * W * 3].reshape(n, H, W, 3)
    return frames, meta["size"][:n], meta["key"][:n]


def all_segments():
    for tag in SEGS:
        yield (tag,) + load(tag)
