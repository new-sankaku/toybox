"""cut 検出を GPU へ移せるかを、ffmpeg scdet の出力そのものと突き合わせる。

**閾値を作り直すのではなく、scdet の式を GPU で書き直す**。この違いが要点。

results.jsonl の kind="cutgate" に、自前の差分閾値で scdet に勝てるかを試した
記録がある。A_op で `mad>18` は 195回発火して 158回が誤検出だった。
つまり「差分が大きい所を cut と呼ぶ」やり方では scdet に勝てない。

そこで scdet の中身をそのまま持ってくる。ffmpeg の vf_scdet は

    mafd  = sad(Y平面) * 100 / (w * h * 256)
    score = clip(min(mafd, |mafd - 1つ前の mafd|), 0, 100)

で、**輝度平面しか見ない**(色差は使わない)。sad は原寸の Y の絶対差の総和なので
NVDEC の surface からそのまま計算できる。しかも NVDEC の Y は libavcodec と
bit 一致する(t4_scangpu.py で実測)ので、GPU 側の score は近似ではなく
**同じ値**になるはずである。それを確かめるのがこの script。

比べるのは3つ:
  1. score の値そのもの (ffmpeg の metadata は小数3桁までなので誤差の下限は 0.0005)
  2. cut と判定される frame の集合
  3. 速度 (CPU の scdet と GPU の式)
"""
import os
import pathlib
import subprocess
import sys
import time

import numpy as np
import torch

import lib
import vfi


def ff_scdet(src, n):
    """ffmpeg の scdet を単独で走らせて score を取る。速度も測る。"""
    txt = lib.RESULTS / f"t5_scene_{os.getpid()}.txt"
    txt.unlink(missing_ok=True)
    t = time.time()
    subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(src), "-vf",
         f"scdet=threshold=0,metadata=print:file={txt.name}",
         "-an", "-f", "null", "-"], check=True, cwd=str(lib.RESULTS))
    sec = time.time() - t
    out = np.zeros(n, dtype=np.float64)
    cur = None
    for line in txt.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line.startswith("frame:"):
            cur = int(line.split()[0].split(":")[1])
        elif "lavfi.scd.score=" in line and cur is not None and cur < n:
            out[cur] = float(line.split("=")[1])
    txt.unlink(missing_ok=True)
    return out, sec


def gpu_scdet(src, w, h):
    """NVDEC の Y 平面から scdet と同じ式で score を出す。"""
    os.add_dll_directory(str(pathlib.Path(torch.__file__).parent / "lib"))
    import PyNvVideoCodec as nvc
    dmx = nvc.CreateDemuxer(filename=str(src))
    dec = nvc.CreateDecoder(gpuid=0, codec=dmx.GetNvCodecId(), cudacontext=0,
                            cudastream=0, usedevicememory=True)
    cnt = float(w * h) * 256.0 / 100.0
    prev = torch.empty((h, w), dtype=torch.int16, device="cuda")
    out, prev_mafd, i = [0.0], None, 0
    t = time.time()
    for pkt in dmx:
        for f in dec.Decode(pkt):
            y = torch.from_dlpack(f)[:h].to(torch.int16)
            if i:
                sad = float((y - prev).abs_().sum(dtype=torch.float64).cpu())
                mafd = sad / cnt
                out.append(min(100.0, min(mafd, abs(mafd - prev_mafd))
                               if prev_mafd is not None else mafd))
                prev_mafd = mafd
            prev.copy_(y)
            i += 1
    sec = time.time() - t
    dec = dmx = None
    return np.array(out[:i], dtype=np.float64), sec


def check(clip):
    src = lib.CLIPS[clip]["path"]
    info = vfi.probe(src)
    g, g_sec = gpu_scdet(src, info["w"], info["h"])
    a, a_sec = ff_scdet(src, len(g))
    d = np.abs(a - g)
    ca, cg = a >= vfi.SCD_CUT, g >= vfi.SCD_CUT
    rec = dict(clip=clip, frames=len(g),
               score_max差=round(float(d.max()), 6),
               score_平均差=round(float(d.mean()), 8),
               metadata丸め=0.0005,
               丸めの範囲内=bool(d.max() <= 0.0005 + 1e-9),
               cut_ffmpeg=int(ca.sum()), cut_gpu=int(cg.sum()),
               cut_集合一致=bool((ca == cg).all()),
               scdet秒_cpu=round(a_sec, 2), scdet秒_gpu=round(g_sec, 2),
               cpu_fps=round(len(g) / a_sec), gpu_fps=round(len(g) / g_sec))
    lib.record("t5_scdgpu", rec)
    for k, v in rec.items():
        print(f"  {k}: {v}")
    return rec


if __name__ == "__main__":
    for c in (sys.argv[1:] or list(lib.CLIPS)):
        print(f"=== {c}")
        check(c)
