"""fp16 で作った engine が fp32 とどれだけ違うかを実測する。

TensorRT 11 は strongly typed network しか作れないので、精度は ONNX 側で
決めてしまう。RIFE は flow を GridSample の正規化座標へ直す所で 2/(W-1) 倍
するため、1920幅では fp16 の分解能と同じ桁に乗る。理屈では危ないが、
**危ないかどうかは測って決める**。
"""
import sys

import numpy as np
import torch

import a3_bench as B
import rifelib as R
import vfilib as V

MODEL = sys.argv[1] if len(sys.argv) > 1 else "v4.25_lite"


def run(model=MODEL):
    for clip in V.CLIPS:
        res = {}
        for fp16 in (False, True):
            m = R.Rife(model, V.W, V.H, fp16=fp16)
            arr = B.bench_quality(m, clip)
            res[fp16] = arr
            gpu_ms, e2e_ms = B.bench_speed(m, iters=40, warm=10)
            s = B.summarise(arr)
            V.record("precision", dict(model=model, clip=clip,
                                       prec="fp16" if fp16 else "fp32",
                                       gpu_ms=round(gpu_ms, 3),
                                       gpu_fps=round(1000 / gpu_ms, 1), **s))
            V.log(f"  {clip} {'fp16' if fp16 else 'fp32'}: "
                  f"{gpu_ms:.2f}ms  PSNR {s['psnr']:.3f}  LPIPS {s['lpips']:.5f}")
            del m
            torch.cuda.empty_cache()

        # 同じ組で直接ぶつける
        m32 = R.Rife(model, V.W, V.H, fp16=False)
        m16 = R.Rife(model, V.W, V.H, fp16=True)
        a = V.load(clip)
        ts = np.load(V.RESULTS / f"testset_{clip}.npy")
        d_psnr, d_box4, d_bad = [], [], []
        for rec in ts:
            r0, r2, tau = int(rec["r0"]), int(rec["r2"]), float(rec["tau"])
            g0, g1 = R.to_gpu(a[r0]), R.to_gpu(a[r2])
            R.pack(g0, g1, tau, m32.dtype, out=m32.dev_in)
            y32 = R.unpack(m32.infer()).cpu().numpy()
            R.pack(g0, g1, tau, m16.dtype, out=m16.dev_in)
            y16 = R.unpack(m16.infer()).cpu().numpy()
            d_psnr.append(V.psnr(y16, y32))
            d_box4.append(V.box4_max(y16, y32))
            d_bad.append(V.bad_pixels(y16, y32))
        e = dict(model=model, clip=clip, n=len(d_psnr),
                 psnr_med=round(float(np.median(d_psnr)), 2),
                 psnr_min=round(float(np.min(d_psnr)), 2),
                 box4_med=int(np.median(d_box4)), box4_max=int(np.max(d_box4)),
                 bad_med=int(np.median(d_bad)), bad_max=int(np.max(d_bad)))
        V.record("precision_diff", e)
        V.log(f"  {clip} fp16 vs fp32 直接比較: PSNR 中央{e['psnr_med']} "
              f"最小{e['psnr_min']}  box4 最大{e['box4_max']}  "
              f"|d|>48画素 最大{e['bad_max']}")
        del m32, m16
        torch.cuda.empty_cache()


if __name__ == "__main__":
    V.log(f"=== 精度 {MODEL}")
    run()
