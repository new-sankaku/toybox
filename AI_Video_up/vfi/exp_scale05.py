"""flow を低解像度で推定する `scale` の効き。速度と、大変位での品質の両方。

「動きの激しい部分を中心に計算する」という発想を、空間の切り分けではなく
**flow の解像度**でやる版。vup で tile差分が失敗した理由(変化が画面全体に
散っている)を踏まない。

scale=0.5 は flow の推定だけ半分の解像度でやる。計算が減るので速く、
大変位が探索範囲に収まるので破綻しにくい。代わりに細かい動きを取り落とす。
"""
import sys

import numpy as np
import torch

import rifelib as R
import rifev1 as R1
import vfilib as V

MODEL = sys.argv[1] if len(sys.argv) > 1 else "v4.6"
SCALES = (1.0, 0.5, 0.25)


def probe(m):
    """tau=0 で img0 と一致するか。座標面と pad が合っているかの検算。"""
    a = V.load("B_talk")
    f0 = R.to_gpu(a[100])
    f1 = R.to_gpu(a[110])
    m.pack(f0, f1, 0.0)
    y = R.unpack(m.infer()).cpu().numpy()
    p = V.psnr(y, a[100])
    V.log(f"  検算 tau=0 vs img0: PSNR {p:.2f}")
    return p


def bench_speed(m, iters=40, warm=10):
    a = V.load("B_talk")
    m.pack(R.to_gpu(a[100]), R.to_gpu(a[101]), 0.5)
    for _ in range(warm):
        m.infer()
    torch.cuda.synchronize()
    e0 = [torch.cuda.Event(enable_timing=True) for _ in range(iters)]
    e1 = [torch.cuda.Event(enable_timing=True) for _ in range(iters)]
    for k in range(iters):
        e0[k].record()
        m.infer()
        e1[k].record()
    torch.cuda.synchronize()
    return float(np.median([x.elapsed_time(y) for x, y in zip(e0, e1)]))


def quality(m, clip):
    import a3_bench as B
    a = V.load(clip)
    ts = np.load(V.RESULTS / f"testset_{clip}.npy")
    rows = []
    for rec in ts:
        r0, r1, r2, tau = (int(rec["r0"]), int(rec["r1"]), int(rec["r2"]),
                           float(rec["tau"]))
        gt = a[r1]
        m.pack(R.to_gpu(a[r0]), R.to_gpu(a[r2]), tau)
        y = R.unpack(m.infer()).cpu().numpy()
        rows.append((r1, int(rec["tier"]), float(rec["mv"]),
                     V.psnr(y, gt), V.lpips_score(y, gt), V.gmsd(y, gt),
                     V.bad_pixels(y, gt)))
    return np.array(rows, dtype=B.QDTYPE)


def run(model=MODEL):
    import a3_bench as B
    for sc in SCALES:
        try:
            m = R1.RifeV1(model, V.W, V.H, scale=sc, fp16=True)
        except Exception as exc:
            V.record("scale05", dict(model=model, scale=sc, error=str(exc)[:300]))
            V.log(f"  scale={sc}: 失敗 {str(exc)[:160]}")
            continue
        V.log(f"=== {model} v1実装 scale={sc}  pad {m.pw}x{m.ph}")
        p0 = probe(m)
        ms = bench_speed(m)
        rec = dict(model=model, impl="v1", scale=sc, pad=f"{m.pw}x{m.ph}",
                   probe_psnr=round(p0, 2), gpu_ms=round(ms, 3),
                   gpu_fps=round(1000 / ms, 1))
        for clip in V.CLIPS:
            arr = quality(m, clip)
            np.save(V.RESULTS / f"q_{model}_v1s{sc}_{clip}.npy", arr)
            s = B.summarise(arr)
            V.record("scale05", dict(clip=clip, **rec, **s))
            V.log(f"  {clip}: {ms:.2f}ms  PSNR {s['psnr']:.2f}  "
                  f"LPIPS {s['lpips']:.4f} (小 {s.get('lpips_t0')} "
                  f"中 {s.get('lpips_t1')} 大 {s.get('lpips_t2')})")
        del m
        torch.cuda.empty_cache()


if __name__ == "__main__":
    run()
