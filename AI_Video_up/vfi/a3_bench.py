"""model ごとの 速度 と 品質 を測る。1 model 終わるたびに記録する。

途中で落としても、済んだ model は results.jsonl に残るので測り直しにならない。
再実行すると未計測の model だけを回す。
"""
import gc
import sys
import time

import numpy as np
import torch

import gpumetric as GM
import rifelib as R
import vfilib as V

W, H = V.W, V.H

# 速い順に見たいので、まず lite 系。heavy は品質の上限を知るための対照
MODELS = ["v4.15_lite", "v4.17_lite", "v4.22_lite", "v4.25_lite",
          "v4.4", "v4.6", "v4.9", "v4.10", "v4.18", "v4.26", "v4.26_heavy"]


# ---------------------------------------------------------------- 速度

def bench_speed(m, iters=60, warm=15):
    """engine 実行だけの GPU 時間と、前後処理を含む end-to-end。"""
    f0 = torch.randint(0, 255, (H, W, 3), dtype=torch.uint8, device="cuda")
    f1 = torch.randint(0, 255, (H, W, 3), dtype=torch.uint8, device="cuda")
    R.pack(f0, f1, 0.5, m.dtype, out=m.dev_in)
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
    gpu_ms = float(np.median([a.elapsed_time(b) for a, b in zip(e0, e1)]))

    torch.cuda.synchronize()
    t0 = time.time()
    for _ in range(iters):
        R.pack(f0, f1, 0.5, m.dtype, out=m.dev_in)
        R.unpack(m.infer())
    torch.cuda.synchronize()
    e2e_ms = (time.time() - t0) / iters * 1000
    del f0, f1
    return gpu_ms, e2e_ms


# ---------------------------------------------------------------- 品質

QDTYPE = [("r1", "i4"), ("tier", "i1"), ("mv", "f4"), ("psnr", "f8"),
          ("lpips", "f8"), ("gmsd", "f8"), ("bad", "i8")]


def bench_quality(m, clip, keep=None):
    """試験集合の各組で D1 を D0,D2 から作り、本物と比べる。

    metric は GPU で計算する。CPU 版は 1080p で 1枚 218ms 掛かり、
    model の 5.7ms の 39倍だった(GPU版は 3.4ms、値は一致を検算済み)。
    出力を .cpu() へ落とさないので D2H も消える。
    """
    a = V.load(clip)
    ts = np.load(V.RESULTS / f"testset_{clip}.npy")
    rows = []
    for rec in ts:
        r0, r1, r2, tau = (int(rec["r0"]), int(rec["r1"]), int(rec["r2"]),
                           float(rec["tau"]))
        gt = GM.to_gpu(a[r1])
        R.pack(R.to_gpu(a[r0]), R.to_gpu(a[r2]), tau, m.dtype, out=m.dev_in)
        y = R.unpack(m.infer())
        rows.append((r1, int(rec["tier"]), float(rec["mv"]),
                     GM.psnr(y, gt), V.lpips_score(y, gt), GM.gmsd(y, gt),
                     GM.bad_pixels(y, gt)))
        if keep is not None and r1 in keep:
            keep[r1] = y.cpu().numpy()
    return np.array(rows, dtype=QDTYPE)


def baselines(clip):
    """model を使わない2つの対照。hold=前のframeをそのまま / blend=単純平均。"""
    if ("baseline", clip) in V.done_keys("baseline", ("kind2", "clip")):
        return
    a = V.load(clip)
    ts = np.load(V.RESULTS / f"testset_{clip}.npy")
    for label in ("hold", "blend"):
        rows = []
        for rec in ts:
            r0, r1, r2, tau = (int(rec["r0"]), int(rec["r1"]), int(rec["r2"]),
                               float(rec["tau"]))
            gt = GM.to_gpu(a[r1])
            if label == "hold":
                y = GM.to_gpu(a[r0])
            else:
                import torch
                y = (GM.to_gpu(a[r0]).float() * (1 - tau)
                     + GM.to_gpu(a[r2]).float() * tau).round().to(torch.uint8)
            rows.append((r1, int(rec["tier"]), float(rec["mv"]),
                         GM.psnr(y, gt), V.lpips_score(y, gt), GM.gmsd(y, gt),
                         GM.bad_pixels(y, gt)))
        arr = np.array(rows, dtype=QDTYPE)
        np.save(V.RESULTS / f"q_{label}_{clip}.npy", arr)
        V.record("baseline", dict(kind2="baseline", clip=clip, model=label,
                                  **summarise(arr)))
        V.log(f"  {clip} {label}: PSNR {arr['psnr'].mean():.2f}")


def summarise(arr):
    out = dict(n=len(arr),
               psnr=round(float(arr["psnr"].mean()), 3),
               lpips=round(float(arr["lpips"].mean()), 5),
               gmsd=round(float(arr["gmsd"].mean()), 5),
               bad_med=int(np.median(arr["bad"])),
               psnr_p5=round(float(np.percentile(arr["psnr"], 5)), 3),
               psnr_worst=round(float(arr["psnr"].min()), 3))
    for t in (0, 1, 2):
        s = arr[arr["tier"] == t]
        if len(s):
            out[f"psnr_t{t}"] = round(float(s["psnr"].mean()), 3)
            out[f"lpips_t{t}"] = round(float(s["lpips"].mean()), 5)
    return out


# ---------------------------------------------------------------- 実行

def run(models, clips):
    for clip in clips:
        baselines(clip)
    done_s = {r["model"] for r in V.read_records("speed") if "error" not in r}
    done_q = {(r["model"], r["clip"]) for r in V.read_records("quality")}

    for name in models:
        need_q = [c for c in clips if (name, c) not in done_q]
        if name in done_s and not need_q:
            V.log(f"{name}: 済み")
            continue
        V.log(f"=== {name}")
        t0 = time.time()
        try:
            m = R.Rife(name, W, H, fp16=True)
        except Exception as exc:
            V.record("speed", dict(model=name, error=str(exc)[:400]))
            V.log(f"  {name}: 失敗 {exc}")
            continue
        prep = time.time() - t0

        if name not in done_s:
            gpu_ms, e2e_ms = bench_speed(m)
            V.record("speed", dict(model=name, w=W, h=H, prec="fp16", bs=1,
                                   gpu_ms=round(gpu_ms, 3),
                                   gpu_fps=round(1000 / gpu_ms, 1),
                                   e2e_ms=round(e2e_ms, 3),
                                   e2e_fps=round(1000 / e2e_ms, 1),
                                   prep_s=round(prep, 1)))
            V.log(f"  速度: engine {gpu_ms:.2f}ms ({1000/gpu_ms:.1f} fps)  "
                  f"e2e {e2e_ms:.2f}ms ({1000/e2e_ms:.1f} fps)")

        for clip in need_q:
            arr = bench_quality(m, clip)
            np.save(V.RESULTS / f"q_{name}_{clip}.npy", arr)
            s = summarise(arr)
            V.record("quality", dict(model=name, clip=clip, prec="fp16", **s))
            V.log(f"  {clip}: PSNR {s['psnr']:.2f} (t0 {s.get('psnr_t0')} / "
                  f"t1 {s.get('psnr_t1')} / t2 {s.get('psnr_t2')})  "
                  f"LPIPS {s['lpips']:.4f}")

        del m
        gc.collect()
        torch.cuda.empty_cache()


if __name__ == "__main__":
    ms = sys.argv[1:] or MODELS
    run(ms, list(V.CLIPS))
