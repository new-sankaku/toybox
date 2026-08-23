"""1巡目の走査を GPU へ移した結果を、CPU 経路と突き合わせる。

見るのは3段。**上から順に、食い違ったら下は見なくて良い**ように並べてある。

  1. decode      NVDEC の Y/U/V が libavcodec と bit 一致するか。
                 ここが一致すれば「decode の差でずれた」という説明は消える
  2. 判定用 gray CPU は `scale=area,format=gray`、GPU は面積平均 + 範囲拡張。
                 dither が無いぶん画素は完全一致しない。**どれだけずれるか**
  3. 判定       絵の切り替わり frame の集合・cut の集合・絵間変位・関門。
                 出力の見た目を決めるのはここだけ

原寸の実測 (lib.drawing_runs / lib.cut_frames) とも両方を突き合わせる。
CPU と GPU が互いに一致していても、両方が原寸からずれていたら意味が無い。
"""
import os
import pathlib
import subprocess
import sys
import time

import numpy as np
import torch
import torch.nn.functional as F

import lib
import vfi


def decode_exact(clip, n=60):
    """NVDEC の NV12 と libavcodec の yuv420p を bit で比べる。"""
    src = str(lib.CLIPS[clip]["path"])
    w, h = lib.W, lib.H
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", src, "-frames:v", str(n),
                        "-pix_fmt", "yuv420p", "-f", "rawvideo", "-"],
                       capture_output=True)
    cpu = np.frombuffer(p.stdout, np.uint8)[:n * w * h * 3 // 2]
    cpu = cpu.reshape(-1, h * 3 // 2, w)

    os.add_dll_directory(str(pathlib.Path(torch.__file__).parent / "lib"))
    import PyNvVideoCodec as nvc
    dmx = nvc.CreateDemuxer(filename=src)
    dec = nvc.CreateDecoder(gpuid=0, codec=dmx.GetNvCodecId(), cudacontext=0,
                            cudastream=0, usedevicememory=True)
    gpu = []
    for pkt in dmx:
        for f in dec.Decode(pkt):
            gpu.append(torch.from_dlpack(f).clone().cpu().numpy())
            if len(gpu) >= len(cpu):
                break
        if len(gpu) >= len(cpu):
            break
    dec = dmx = None
    gpu = np.stack(gpu[:len(cpu)])
    m = min(len(cpu), len(gpu))
    d = np.abs(cpu[:m].astype(np.int32) - gpu[:m].astype(np.int32))
    # NV12 は UV が interleave されているので、平面ごとではなく全 byte で見る
    # (U と V の byte 集合は同じで並びだけが違う)
    dy = d[:, :lib.H]
    return dict(frames=m, y_bit一致=bool((dy == 0).all()),
                y_max差=int(dy.max()),
                uv_byte数一致=bool(cpu[:m, lib.H:].sum() == gpu[:m, lib.H:].sum()))


def gray_diff(clip, scan_w=vfi.SCAN_W, n=200):
    """判定に使う縮小 Y が CPU と GPU でどれだけ違うか。画素で測る。"""
    src = lib.CLIPS[clip]["path"]
    info = vfi.probe(src)
    sw, sh, _ = vfi.scan_dims(info, scan_w)
    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(src), "-frames:v", str(n),
         "-vf", f"scale={sw}:{sh}:flags=area,format=yuv420p,extractplanes=y",
         "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True)
    a = np.frombuffer(p.stdout, np.uint8)[:n * sw * sh].reshape(-1, sh, sw)

    os.add_dll_directory(str(pathlib.Path(torch.__file__).parent / "lib"))
    import PyNvVideoCodec as nvc
    dmx = nvc.CreateDemuxer(filename=str(src))
    dec = nvc.CreateDecoder(gpuid=0, codec=dmx.GetNvCodecId(), cudacontext=0,
                            cudastream=0, usedevicememory=True)
    b = []
    for pkt in dmx:
        for f in dec.Decode(pkt):
            y = torch.from_dlpack(f)[:info["h"]].to(torch.float32)
            g = F.adaptive_avg_pool2d(y[None, None], (sh, sw))[0, 0]
            g = g.round_().clamp_(0, 255)
            b.append(g.to(torch.uint8).cpu().numpy())
            if len(b) >= len(a):
                break
        if len(b) >= len(a):
            break
    dec = dmx = None
    b = np.stack(b[:len(a)])
    m = min(len(a), len(b))
    d = np.abs(a[:m].astype(np.int32) - b[:m].astype(np.int32))
    # 判定は「1枚の中の max|差|」なので、画素の平均より **frame ごとの max**
    # がずれ幅として効く
    per = d.reshape(m, -1).max(axis=1)
    return dict(frames=m, 画素_平均差=round(float(d.mean()), 3),
                画素_max差=int(d.max()),
                frame毎max差_p50=int(np.median(per)),
                frame毎max差_max=int(per.max()))


def compare(clip, scan_w=vfi.SCAN_W):
    src = lib.CLIPS[clip]["path"]
    info = vfi.probe(src)
    out = {}
    for mode in ("cpu", "gpu"):
        t = time.time()
        sc = vfi.scan(src, info, scan_w=scan_w, mode=mode)
        sc["fps_in"] = info["fps"]
        sc["_sec"] = time.time() - t
        out[mode] = sc
    c, g = out["cpu"], out["gpu"]

    rc, rg = c["runs"], g["runs"]
    inter = np.intersect1d(rc, rg)
    rec = dict(clip=clip, scan_w=scan_w,
               cpu秒=round(c["_sec"], 2), gpu秒=round(g["_sec"], 2),
               cpu_fps=round(c["n_frames"] / c["_sec"]),
               gpu_fps=round(g["n_frames"] / g["_sec"]),
               frames_cpu=c["n_frames"], frames_gpu=g["n_frames"],
               絵_cpu=len(rc), 絵_gpu=len(rg), 絵_共通=len(inter),
               絵_完全一致=bool(len(rc) == len(rg) and np.array_equal(rc, rg)),
               cut_cpu=len(c["cuts"]), cut_gpu=len(g["cuts"]),
               cut_完全一致=bool(np.array_equal(c["cuts"], g["cuts"])))

    # 食い違った絵の先頭が「別の絵」なのか「同じ絵の1 frame ずれ」なのかを分ける。
    # 縮小 Y は最大 1 しか違わないので、閾値の際どい frame では前後どちらを
    # 先頭に選ぶかが入れ替わる。それは絵を取り違えた事とは意味が違う
    only_c = np.setdiff1d(rc, rg)
    if len(only_c):
        shift = np.array([int(np.min(np.abs(rg - x))) for x in only_c])
        rec["絵_不一致"] = len(only_c)
        rec["絵_不一致のうち1frameずれ"] = int((shift <= 1).sum())
        rec["絵_ずれ幅max"] = int(shift.max())

    # scdet の score。GPU は自前の式、CPU は ffmpeg の出力
    n = min(len(c["scd"]), len(g["scd"]))
    ds = np.abs(c["scd"][:n].astype(np.float64) - g["scd"][:n].astype(np.float64))
    rec.update(scd_max差=round(float(ds.max()), 6),
               scd_平均差=round(float(ds.mean()), 8),
               scd_cut判定一致=bool(((c["scd"][:n] >= vfi.SCD_CUT)
                                 == (g["scd"][:n] >= vfi.SCD_CUT)).all()))

    # 絵間変位。絵の先頭が両方で一致する pair だけ突き合わせる
    mc = {(int(rc[k]), int(rc[k + 1])): float(c["mv"][k]) for k in range(len(rc) - 1)}
    pa, pb = [], []
    for k in range(len(rg) - 1):
        key = (int(rg[k]), int(rg[k + 1]))
        if key in mc:
            pa.append(mc[key])
            pb.append(float(g["mv"][k]))
    if pa:
        pa, pb = np.array(pa), np.array(pb)
        rec.update(変位_pair=len(pa),
                   変位_p50_cpu=round(float(np.median(pa)), 2),
                   変位_p50_gpu=round(float(np.median(pb)), 2),
                   変位_差p50=round(float(np.median(np.abs(pa - pb))), 3),
                   変位_差max=round(float(np.abs(pa - pb).max()), 3),
                   変位_関門反転=int(((pa > vfi.SPAN_LIMIT)
                                  != (pb > vfi.SPAN_LIMIT)).sum()))

    # 関門。出力の見た目を決めるのはここ
    for mode, sc in out.items():
        _blk, det = vfi.build_block(sc)
        rec[f"関門_{mode}"] = {k: v["尺_pct"] for k, v in det.items()}
    rec["関門_尺差_最大pt"] = round(max(
        abs(rec["関門_cpu"][k] - rec["関門_gpu"][k]) for k in rec["関門_cpu"]), 2)

    # 原寸の実測との突き合わせ。CPU/GPU が互いに一致していても、両方が
    # 原寸からずれていたら意味が無い
    try:
        ref_runs = np.asarray(lib.drawing_runs(clip), dtype=np.int64)
        ref_cuts = np.asarray(lib.cut_frames(clip), dtype=np.int64)
        for mode, r in (("cpu", rc), ("gpu", rg)):
            it = np.intersect1d(ref_runs, r)
            rec[f"原寸_recall_{mode}"] = round(len(it) / len(ref_runs) * 100, 1)
            rec[f"原寸_prec_{mode}"] = round(len(it) / len(r) * 100, 1)
        rec["原寸cut_cpu一致"] = bool(np.array_equal(np.sort(ref_cuts),
                                                np.sort(c["cuts"])))
        rec["原寸cut_gpu一致"] = bool(np.array_equal(np.sort(ref_cuts),
                                                np.sort(g["cuts"])))
    except Exception as exc:                      # 原寸の memmap が無い環境
        rec["原寸"] = f"比較できません: {exc}"
    return rec


def main():
    clips = sys.argv[1:] or list(lib.CLIPS)
    for clip in clips:
        print(f"\n=== {clip}")
        d = decode_exact(clip)
        print(f"  1. decode  {d}")
        gd = gray_diff(clip)
        print(f"  2. gray    {gd}")
        rec = compare(clip)
        rec["decode"] = d
        rec["gray"] = gd
        lib.record("t4_scangpu", rec)
        print("  3. 判定")
        for k, v in rec.items():
            if k not in ("decode", "gray", "clip"):
                print(f"     {k}: {v}")


if __name__ == "__main__":
    main()
