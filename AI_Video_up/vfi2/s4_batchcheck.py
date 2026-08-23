"""batch 化した engine が bs=1 と同じ絵を返すかを実画像で確かめる。

s2_batch.py の乱数入力で bs=1 との PSNR が 11.4dB しか出なかった。
乱数のせいなのか、graph が sample を混ぜているのかを分ける。

  同一入力を並べる  … 混線していても気付けない。engine 自体の健全性の確認
  別入力を並べる    … 混線するならここで落ちる
"""
import sys

import numpy as np
import torch

import lib
import rifelib as R

W, H = lib.W, lib.H


def psnr01(a, b):
    d = (a.float() - b.float())
    mse = float((d * d).mean())
    return 100.0 if mse <= 0 else float(10 * np.log10(1.0 / mse))


def run(model="v4.25_lite", bs=4, clip="C_act"):
    a = lib.load(clip)
    runs = lib.drawing_runs(clip)
    # 別々の絵の組を bs 個
    pairs = [(int(runs[k]), int(runs[k + 1])) for k in range(2, 2 + bs)]
    m1 = R.Rife(model, W, H, bs=1, fp16=True)
    mb = R.Rife(model, W, H, bs=bs, fp16=True)

    def pack_one(i0, i1, tau, dtype):
        f0 = R.to_gpu(a[i0])
        f1 = R.to_gpu(a[i1])
        return R.pack(f0, f1, tau, dtype)

    for label, ps in (("同一入力", [pairs[0]] * bs), ("別入力", pairs)):
        ref = []
        for (i0, i1) in ps:
            m1.dev_in.copy_(pack_one(i0, i1, 0.5, m1.dtype))
            ref.append(m1.infer().clone())
        ref = torch.cat(ref, 0)
        for i, (i0, i1) in enumerate(ps):
            mb.dev_in[i:i + 1].copy_(pack_one(i0, i1, 0.5, mb.dtype))
        got = mb.infer()
        torch.cuda.synchronize()
        per = [round(psnr01(got[i], ref[i]), 2) for i in range(bs)]
        r = dict(model=model, bs=bs, clip=clip, case=label,
                 psnr_all=round(psnr01(got, ref), 2), psnr_each=per)
        lib.record("batch_check", r)
        lib.log(f"  {label}: 全体 {r['psnr_all']}dB  各 {per}")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "v4.25_lite",
        int(sys.argv[2]) if len(sys.argv) > 2 else 4)
