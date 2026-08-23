"""「差が小さいのは model のせいか、構造か」を分ける。

補間frameが「複製」から動かせる量の上限は、元の2枚がどれだけ違うかで決まる。
tau=0.5 なら、元の2枚で違っている画素のうち **およそ半分**が動くのが目安。

  0% に近い      -> model が何もしていない（model の問題）
  50% 前後       -> model は出せる分を出している（構造の問題）
"""
import sys

import numpy as np
import torch

import gpumetric as GM
import rifelib as R
import vfilib as V


def run(clip, model="v4.6"):
    a = V.load(clip)
    scd = np.load(V.RESULTS / f"scd_{clip}.npy")
    m = R.Rife(model, V.W, V.H, fp16=True, log=lambda s: None)
    prev = GM.to_gpu(np.array(a[0]))
    rows = []
    for i in range(len(a) - 1):
        cur = GM.to_gpu(np.array(a[i + 1]))
        if scd[i] >= 10.0:
            prev = cur
            continue
        src = GM.bad_pixels(prev, cur, 48)
        R.pack(prev, cur, 0.5, m.dtype, out=m.dev_in)
        out = GM.bad_pixels(R.unpack(m.infer()), prev, 48)
        rows.append((src, out))
        prev = cur
    r = np.array(rows, dtype=[("src", "i8"), ("out", "i8")])
    frozen = int((r["src"] == 0).sum())
    nz = r[r["src"] > 0]
    ratio = nz["out"] / nz["src"]
    info = dict(clip=clip, model=model, positions=len(r),
                frozen=frozen, frozen_pct=round(frozen / len(r) * 100, 1),
                movable=len(nz),
                ratio_p10=round(float(np.percentile(ratio, 10)) * 100, 1),
                ratio_p50=round(float(np.percentile(ratio, 50)) * 100, 1),
                ratio_p90=round(float(np.percentile(ratio, 90)) * 100, 1),
                src_med=int(np.median(nz["src"])),
                out_med=int(np.median(nz["out"])))
    V.record("capacity", info)
    print(f"=== {clip}  cut以外の補間位置 {len(r)}")
    print(f"元の2枚が |d|>48 で違う画素 0 の位置: {frozen} ({info['frozen_pct']}%)")
    print(f"  -> ここは何を使っても複製と同じ絵にしかならない（構造）")
    print(f"残り {len(nz)} 箇所で model が動かした割合: "
          f"p10 {info['ratio_p10']}% / 中央 {info['ratio_p50']}% / "
          f"p90 {info['ratio_p90']}%   （目安 50%）")
    print(f"  元の違う画素数 中央 {info['src_med']} -> "
          f"model が動かした画素数 中央 {info['out_med']}")
    del m
    torch.cuda.empty_cache()
    return info


if __name__ == "__main__":
    for c in (sys.argv[1:] or list(V.CLIPS)):
        run(c)
