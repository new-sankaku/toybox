"""速度計測のための GPU 空き待ち。

`lib.gpu_lock` は lock を取った Agent 同士しか効かない。実際には lock を
取らずに GPU を回している process が居て、同じ推論が 5.32ms と 11.65ms に
分かれた。lock に加えて **nvidia-smi で実際に空いているかを見てから測る**。

測定値には必ずその時の使用率を併記する。後から汚染された値を捨てられる。
"""
import subprocess
import time

import lib


def gpu_state():
    """(使用率%, 使用VRAM MiB)。"""
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True).stdout.strip().splitlines()[0]
    u, m = (int(x.strip()) for x in out.split(","))
    return u, m


def wait_idle(max_util=15, need=3, timeout=1800.0, poll=2.0):
    """使用率が need 回連続で max_util 以下になるまで待つ。

    自分の process も VRAM を持っているので memory は見ない。使用率だけ見る。
    """
    t0 = time.time()
    hit = 0
    said = False
    while True:
        u, m = gpu_state()
        if u <= max_util:
            hit += 1
            if hit >= need:
                return u, m
        else:
            hit = 0
            if not said:
                lib.log(f"gpu: 他が使用中 ({u}% / {m} MiB)。空くまで待ちます")
                said = True
        if time.time() - t0 > timeout:
            lib.log(f"gpu: {timeout:.0f}秒待っても空きません ({u}%)。"
                    "汚染された値として記録します")
            return u, m
        time.sleep(poll)


CANARY_MODEL = "v4.6"
CANARY_MS = 5.32       # GPU が空いている時の v4.6 fp16 bs=1 1080p 推論(実測)
_canary = None


def canary_ms(iters=20):
    """基準の推論。使用率だけでは掴めない汚染を、実際の速さで検出する。"""
    global _canary
    import numpy as np
    import torch
    import rifelib as R
    if _canary is None:
        _canary = R.Rife(CANARY_MODEL, lib.W, lib.H, bs=1, fp16=True)
    m = _canary
    for _ in range(5):
        m.infer()
    torch.cuda.synchronize()
    e0 = [torch.cuda.Event(enable_timing=True) for _ in range(iters)]
    e1 = [torch.cuda.Event(enable_timing=True) for _ in range(iters)]
    for k in range(iters):
        e0[k].record()
        m.infer()
        e1[k].record()
    torch.cuda.synchronize()
    # 他 process の干渉は必ず「遅くする」向きにしか働かない。median だと
    # 干渉が値へ残るので min を採る。
    return float(min(a.elapsed_time(b) for a, b in zip(e0, e1)))


class measuring:
    """lock を取り、GPU が空くのを待ってから測る。

    with sgpu.measuring() as env:  ...  env["util_before"] / env["util_after"]
    """

    def __init__(self, who="speed", max_util=15, canary=True, tol=1.15):
        self.who = who
        self.max_util = max_util
        self.canary = canary
        self.tol = tol
        self.env = {}

    def __enter__(self):
        self._lock = lib.gpu_lock(self.who)
        self._lock.__enter__()
        u, m = wait_idle(self.max_util)
        self.env["util_before"] = u
        self.env["vram_before_mb"] = m
        if self.canary:
            self.env["canary_ms"] = round(canary_ms(), 3)
        return self.env

    def __exit__(self, *exc):
        u, m = gpu_state()
        self.env["util_after"] = u
        ok = self.env["util_before"] <= self.max_util
        if self.canary and exc[0] is None:
            c = round(canary_ms(), 3)
            self.env["canary_ms_after"] = c
            ok = ok and c <= CANARY_MS * self.tol
        self.env["clean"] = ok
        if not ok:
            lib.log(f"gpu: この計測は汚染されています {self.env}")
        return self._lock.__exit__(*exc)
