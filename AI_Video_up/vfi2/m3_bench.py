"""model 1つの速度と品質を測る。**1 process 1 model**。

    python m3_bench.py <model_key> [clip ...]

各 repo が `models` `model` `config` を自分の root から import するので、
同じ process に2つ載せると sys.modules が壊れる。呼び出しは m3_run.py。

速度は2つに分ける。
  gpu_ms  … predict() の GPU 時間(cuda event)。model 側の pad/正規化も含む
  e2e_ms  … numpy から載せて uint8 で降ろすまでの wall clock

品質は試験集合(m1_testset.py)の各組で D1 を D0,D2 と tau から作り、
本物と比べる。metric は GPU 版(vfi/gpumetric.py)。
"""
import gc
import sys
import time

import numpy as np
import torch

import lib
import vfimodels

sys.path.insert(0, str(lib.VFI1))
import gpumetric as GM        # noqa: E402
import vfilib as V            # noqa: E402

QDTYPE = [("r1", "i4"), ("bin", "i1"), ("span", "f4"), ("tau", "f4"),
          ("weight", "f4"), ("psnr", "f8"), ("lpips", "f8"), ("gmsd", "f8"),
          ("bad", "i8")]


def bench_speed(m, iters=30, warm=8):
    a = lib.load("C_act")
    g0, g1 = vfimodels.to_gpu(np.array(a[100])), vfimodels.to_gpu(np.array(a[104]))
    n0, n1 = np.array(a[100]), np.array(a[104])
    for _ in range(warm):
        m.predict(g0, g1, 0.5)
    torch.cuda.synchronize()

    e0 = [torch.cuda.Event(enable_timing=True) for _ in range(iters)]
    e1 = [torch.cuda.Event(enable_timing=True) for _ in range(iters)]
    for k in range(iters):
        e0[k].record()
        m.predict(g0, g1, 0.5)
        e1[k].record()
    torch.cuda.synchronize()
    gpu_ms = float(np.median([x.elapsed_time(y) for x, y in zip(e0, e1)]))

    torch.cuda.synchronize()
    t0 = time.time()
    for _ in range(iters):
        y = m.predict(vfimodels.to_gpu(n0), vfimodels.to_gpu(n1), 0.5)
        y.cpu().numpy()
    torch.cuda.synchronize()
    e2e_ms = (time.time() - t0) / iters * 1000
    return gpu_ms, e2e_ms, torch.cuda.max_memory_allocated() / 2 ** 30


def bench_quality(m, clip):
    a = lib.load(clip)
    ts = np.load(lib.RESULTS / f"testset_{clip}.npy")
    rows = []
    for rec in ts:
        r0, r1, r2 = int(rec["r0"]), int(rec["r1"]), int(rec["r2"])
        tau = float(rec["tau"])
        gt = GM.to_gpu(np.array(a[r1]))
        y = m.predict(vfimodels.to_gpu(np.array(a[r0])),
                      vfimodels.to_gpu(np.array(a[r2])), tau)
        rows.append((r1, int(rec["bin"]), float(rec["span"]), tau,
                     float(rec["weight"]), GM.psnr(y, gt), V.lpips_score(y, gt),
                     GM.gmsd(y, gt), GM.bad_pixels(y, gt)))
    return np.array(rows, dtype=QDTYPE)


def summarise(arr):
    """重み付き平均が母集団の代表値。素の平均は層別抽出のぶん難所へ寄る。"""
    w = arr["weight"] / arr["weight"].sum()
    out = dict(n=len(arr))
    for f in ("psnr", "lpips", "gmsd"):
        out[f] = round(float((arr[f] * w).sum()), 5)
        out[f + "_flat"] = round(float(arr[f].mean()), 5)
    out["bad"] = int(round(float((arr["bad"] * w).sum())))
    out["lpips_worst"] = round(float(arr["lpips"].max()), 5)
    out["psnr_worst"] = round(float(arr["psnr"].min()), 3)
    for b in range(7):
        s = arr[arr["bin"] == b]
        if len(s):
            out[f"lpips_b{b}"] = round(float(s["lpips"].mean()), 5)
            out[f"psnr_b{b}"] = round(float(s["psnr"].mean()), 3)
            out[f"gmsd_b{b}"] = round(float(s["gmsd"].mean()), 5)
            out[f"n_b{b}"] = len(s)
    return out


def run(key, clips):
    done_s = {r["key"] for r in lib.read_records("speed2") if "error" not in r}
    done_q = {(r["key"], r["clip"]) for r in lib.read_records("quality2")}
    need_q = [c for c in clips if (key, c) not in done_q]
    if key in done_s and not need_q:
        lib.log(f"{key}: 済み")
        return

    lib.log(f"=== {key}")
    torch.cuda.reset_peak_memory_stats()
    t0 = time.time()
    m = vfimodels.build(key, lib.W, lib.H, log=lib.log)
    prep = time.time() - t0
    name = getattr(m, "name", key)

    if key not in done_s:
        with lib.gpu_lock("models"):
            busy0 = lib.gpu_busy_pct()
            gpu_ms, e2e_ms, peak = bench_speed(m)
        lib.record("speed2", dict(key=key, model=name, busy_before=busy0,
                                  impl=getattr(m, "impl", "?"),
                                  w=lib.W, h=lib.H,
                                  gpu_ms=round(gpu_ms, 3),
                                  gpu_fps=round(1000 / gpu_ms, 2),
                                  e2e_ms=round(e2e_ms, 3),
                                  e2e_fps=round(1000 / e2e_ms, 2),
                                  vram_peak_gb=round(peak, 2),
                                  load_s=round(prep, 1)))
        lib.log(f"  速度: model {gpu_ms:.2f}ms ({1000/gpu_ms:.1f}枚/秒)  "
                f"e2e {e2e_ms:.2f}ms  VRAM {peak:.2f}GB")

    for clip in need_q:
        # 品質の計算は時間を測らないが GPU は使う。他の実測を汚さないよう
        # 共有側で囲む(clip ごとに抜けて、排他の待ち手へ譲る)
        with lib.gpu_use("models"):
            arr = bench_quality(m, clip)
        np.save(lib.RESULTS / f"q2_{key}_{clip}.npy", arr)
        s = summarise(arr)
        lib.record("quality2", dict(key=key, model=name, clip=clip, **s))
        lib.log(f"  {clip}: LPIPS {s['lpips']:.4f} / GMSD {s['gmsd']:.4f} "
                f"/ PSNR {s['psnr']:.2f}")

    del m
    gc.collect()
    torch.cuda.empty_cache()


def speed_only(key):
    """速度だけを測り直す。他 Agent の実測と時間帯がずれて条件が揃わない時に、
    最後にまとめて1回で取り直すための口(kind=speed3)。"""
    m = vfimodels.build(key, lib.W, lib.H, log=lib.log)
    torch.cuda.reset_peak_memory_stats()
    with lib.gpu_lock("models"):
        busy0 = lib.gpu_busy_pct()
        gpu_ms, e2e_ms, peak = bench_speed(m)
        busy1 = lib.gpu_busy_pct()
    lib.record("speed3", dict(key=key, model=getattr(m, "name", key),
                              impl=getattr(m, "impl", "?"), w=lib.W, h=lib.H,
                              gpu_ms=round(gpu_ms, 3), gpu_fps=round(1000 / gpu_ms, 2),
                              e2e_ms=round(e2e_ms, 3), e2e_fps=round(1000 / e2e_ms, 2),
                              vram_peak_gb=round(peak, 2),
                              busy_before=busy0, busy_after=busy1))
    lib.log(f"  {key}: model {gpu_ms:.2f}ms / e2e {e2e_ms:.2f}ms / "
            f"VRAM {peak:.2f}GB (GPU使用率 {busy0}->{busy1})")


if __name__ == "__main__":
    if sys.argv[1] == "--speed":
        speed_only(sys.argv[2])
    else:
        run(sys.argv[1], sys.argv[2:] or list(lib.CLIPS))
