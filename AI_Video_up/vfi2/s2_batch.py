"""batch 化の効き。新設計では1組の絵から複数の tau を作るので batch が要になる。

前回 (vfi/a7_scale.py) の実測では v4.25_lite の 1080p は bs2 で **遅くなった**
(11.72 -> 12.35 ms/枚)。960x540 では 1.90倍速くなっている。1080p では1枚で
既に SM が埋まっている、という読みが立つが bs4/8 は測っていない。ここで測る。

VRAM は他の Agent の使用量が混ざるので、bs ごとに別 process で起動し
「その process が確保する前後の free の差」を採る。
"""
import json
import subprocess
import sys

import numpy as np
import torch

import lib
import sgpu
import rifelib as R

PY = sys.executable
W, H = lib.W, lib.H


def measure(model, bs, w=W, h=H, iters=30):
    free0, _ = torch.cuda.mem_get_info()
    m = R.Rife(model, w, h, bs=bs, fp16=True)          # build は lock の外
    f = torch.rand((bs, 7, h, w), dtype=m.dtype, device="cuda")
    m.dev_in.copy_(f)
    for _ in range(10):
        m.infer()
    torch.cuda.synchronize()
    free1, _ = torch.cuda.mem_get_info()

    with sgpu.measuring() as env:
        e0 = [torch.cuda.Event(enable_timing=True) for _ in range(iters)]
        e1 = [torch.cuda.Event(enable_timing=True) for _ in range(iters)]
        for k in range(iters):
            e0[k].record()
            m.infer()
            e1[k].record()
        torch.cuda.synchronize()
    ms_batch = float(min(a.elapsed_time(b) for a, b in zip(e0, e1)))

    # bs=1 と同じ絵が返るかを確かめる。並びが狂えば PSNR が桁で落ちる
    ref = None
    if bs > 1:
        m1 = R.Rife(model, w, h, bs=1, fp16=True)
        outs = []
        for i in range(bs):
            m1.dev_in.copy_(f[i:i + 1])
            outs.append(m1.infer().clone())
        ref = torch.cat(outs, 0)
        m.dev_in.copy_(f)
        got = m.infer()
        torch.cuda.synchronize()
        d = (got.float() - ref.float())
        mse = float((d * d).mean())
        ref = 100.0 if mse <= 0 else float(10 * np.log10(1.0 / mse))
        del m1, outs

    return dict(model=model, w=w, h=h, bs=bs, **env,
                ms_batch=round(ms_batch, 3),
                ms_per_frame=round(ms_batch / bs, 3),
                fps=round(1000 * bs / ms_batch, 1),
                vram_mb=round((free0 - free1) / 2 ** 20, 0),
                psnr_vs_bs1=(None if ref is None else round(ref, 2)))


if __name__ == "__main__":
    model = sys.argv[1]
    bs = int(sys.argv[2])
    w = int(sys.argv[3]) if len(sys.argv) > 3 else W
    h = int(sys.argv[4]) if len(sys.argv) > 4 else H
    try:
        r = measure(model, bs, w, h)
    except Exception as exc:
        r = dict(model=model, w=w, h=h, bs=bs, error=str(exc)[:300])
    lib.record("batch", r)
    print(json.dumps(r, ensure_ascii=False), flush=True)
