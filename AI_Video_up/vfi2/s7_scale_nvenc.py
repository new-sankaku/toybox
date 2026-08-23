"""(1) flow の scale で推論がどれだけ軽くなるか (2) NVENC が CUDA を待たせるか。

(1) v2実装は scale を掛けられない。v1実装(rifev1.py)だけが flow の推定を
    低解像度で行える。速度だけ測る。品質は別 Agent の担当。

(2) 別件の実測で「NVENC は別 engine でも CUDA context の時分割で自分の kernel
    を待たせる。preset を軽くすると計算が速くなる」という結果が出ている。
    VFI でも起きるなら、encoder の preset は画質だけでなく速度の設定になる。
    nvenc を回しっぱなしにした状態で推論の ms を測る。
"""
import subprocess
import sys
import time

import numpy as np
import torch

import lib
import sgpu
import rifelib as R
import rifev1 as R1

W, H = lib.W, lib.H


def timed(fn, iters=40, warm=10):
    for _ in range(warm):
        fn()
    torch.cuda.synchronize()
    e0 = [torch.cuda.Event(enable_timing=True) for _ in range(iters)]
    e1 = [torch.cuda.Event(enable_timing=True) for _ in range(iters)]
    for k in range(iters):
        e0[k].record()
        fn()
        e1[k].record()
    torch.cuda.synchronize()
    return float(min(a.elapsed_time(b) for a, b in zip(e0, e1)))


def flow_scale(model="v4.6", scales=(1.0, 0.5, 0.25)):
    ms = {}
    built = {}
    for s in scales:                                   # build は lock の外
        built[s] = R1.RifeV1(model, W, H, scale=s, fp16=True)
    with sgpu.measuring("speed") as env:
        for s, m in built.items():
            ms[s] = round(timed(m.infer), 3)
    for s, v in ms.items():
        r = dict(model=model, impl="v1", scale=s, w=W, h=H,
                 pad=f"{built[s].pw}x{built[s].ph}", infer_ms=v,
                 fps=round(1000 / v, 1),
                 speedup=round(ms[1.0] / v, 3) if 1.0 in ms else None, **env)
        lib.record("flowscale", r)
        lib.log(f"  scale={s}: {v} ms ({1000/v:.1f} fps)  "
                f"{ms[1.0]/v:.2f}倍" if 1.0 in ms else "")


class Nvenc:
    """rawvideo を延々流し込んで NVENC を回し続ける。"""

    def __init__(self, args):
        self.p = subprocess.Popen(
            ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "nv12",
             "-s", f"{W}x{H}", "-r", "48000/1001", "-i", "-", "-c:v", "hevc_nvenc"]
            + args.split() + ["-pix_fmt", "yuv420p", "-f", "null", "-"],
            stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.buf = np.random.randint(0, 255, W * H * 3 // 2,
                                     dtype=np.uint8).tobytes()
        self.n = 0
        self.stop = False
        import threading
        self.t = threading.Thread(target=self._feed, daemon=True)
        self.t.start()

    def _feed(self):
        try:
            while not self.stop:
                self.p.stdin.write(self.buf)
                self.n += 1
        except (BrokenPipeError, OSError):
            pass

    def close(self):
        self.stop = True
        self.t.join(timeout=5)
        try:
            self.p.stdin.close()
        except OSError:
            pass
        self.p.kill()
        self.p.wait()


def nvenc_contention(model="v4.6"):
    m = R.Rife(model, W, H, bs=1, fp16=True)
    cases = [("なし", None), ("p1", "-preset p1 -cq 24"),
             ("p4", "-preset p4 -cq 24"), ("p7", "-preset p7 -cq 24"),
             ("p4 split", "-preset p4 -cq 24 -split_encode_mode 3")]
    out = {}
    with sgpu.measuring("speed") as env:
        for label, args in cases:
            enc = Nvenc(args) if args else None
            if enc:
                time.sleep(1.0)               # NVENC が定常になるまで待つ
                n0 = enc.n
            ms = timed(m.infer)
            enc_fps = None
            if enc:
                enc_fps = round((enc.n - n0) / 1.0, 1) if False else None
                enc.close()
            out[label] = ms
            r = dict(model=model, encoder=label, infer_ms=round(ms, 3),
                     ratio_vs_idle=round(ms / out["なし"], 3), **env)
            lib.record("nvenc_contention", r)
            lib.log(f"  encoder {label:9s}: 推論 {ms:.3f} ms "
                    f"({ms/out['なし']:.2f}倍)")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("all", "scale"):
        lib.log("=== flow の scale")
        flow_scale()
    if what in ("all", "nvenc"):
        lib.log("=== NVENC が CUDA を待たせるか")
        nvenc_contention()
