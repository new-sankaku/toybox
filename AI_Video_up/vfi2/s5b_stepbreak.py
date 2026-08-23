"""s1 の stage を足すと 6.34ms なのに、繋げた step は 12.8ms だった。
どこで増えるかを、同じ harness で累積的に測って突き止める。
"""
import numpy as np
import torch

import lib
import sgpu
import rifelib as R
from s1_profile import nv12

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
    # 他 process の干渉は必ず「遅くする」向きにしか働かない。median だと
    # 干渉が値へ残るので min を採る。
    return float(min(a.elapsed_time(b) for a, b in zip(e0, e1)))


def run(model="v4.6"):
    m = R.Rife(model, W, H, bs=1, fp16=True)
    f0 = torch.randint(0, 255, (H, W, 3), dtype=torch.uint8, device="cuda")
    f1 = torch.randint(0, 255, (H, W, 3), dtype=torch.uint8, device="cuda")
    pin = torch.empty((H * 3 // 2, W), dtype=torch.uint8, pin_memory=True)

    def a_pack():
        R.pack(f0, f1, 0.5, m.dtype, out=m.dev_in)

    def b_infer():
        m.infer()

    def c_pack_infer():
        R.pack(f0, f1, 0.5, m.dtype, out=m.dev_in)
        m.infer()

    def d_unpack():
        R.unpack(m.dev_out[:, :, :H, :W])

    def e_nv12():
        nv12(f0)

    nv = torch.empty((H * 3 // 2, W), dtype=torch.uint8, device="cuda")

    def f_d2h():
        pin.copy_(nv, non_blocking=True)

    def g_full():
        R.pack(f0, f1, 0.5, m.dtype, out=m.dev_in)
        y = m.infer()
        pin.copy_(nv12(R.unpack(y)), non_blocking=True)

    def h_post():
        pin.copy_(nv12(R.unpack(m.dev_out[:, :, :H, :W])), non_blocking=True)

    with sgpu.measuring() as env:
        r = {k: round(timed(v), 3) for k, v in
             (("pack", a_pack), ("infer", b_infer), ("pack+infer", c_pack_infer),
              ("unpack", d_unpack), ("nv12", e_nv12), ("d2h", f_d2h),
              ("post(unpack+nv12+d2h)", h_post), ("full", g_full))}
    r["model"] = model
    r.update(env)
    lib.record("stepbreak", r)
    for k, v in r.items():
        lib.log(f"  {k}: {v}")


if __name__ == "__main__":
    run()
