"""出力 file の画素を、元 file の画素と突き合わせる。

schedule が正しくても、絵の受け渡しが1つずれていれば見た目は壊れる。
数えた frame 数では捕まらないので、**出力の画素そのもの**を見る。

  写しの出力 (kind=copy)  元の絵と同じはず。NVDEC の色変換と encode の損だけ
                          が乗るので PSNR は高く出る
  補間の出力 (kind=model) 両端の絵のどちらとも違うはず。同じなら model が
                          呼ばれていないか、tau が効いていない
"""
import subprocess
import sys
from pathlib import Path

import numpy as np

import lib
import vfi


def stream(path, w, h):
    p = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(path), "-fps_mode", "passthrough",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
        stdout=subprocess.PIPE)          # bufsize は渡さない
    buf = np.empty((h, w, 3), np.uint8)
    try:
        while p.stdout.readinto(memoryview(buf.reshape(-1))) == w * h * 3:
            yield buf
    finally:
        try:
            p.stdout.close()
        except OSError:
            pass
        p.wait()


def psnr(a, b):
    d = a.astype(np.float32) - b.astype(np.float32)
    mse = float((d * d).mean())
    return 99.0 if mse == 0 else 10 * np.log10(255.0 ** 2 / mse)


def check(src, out):
    src, out = Path(src).resolve(), Path(out).resolve()
    info = vfi.probe(src)
    sc = vfi.scan(src, info)
    sc["fps_in"] = info["fps"]
    fps_out = vfi.parse_fps("x2", info["fps"])
    sched, _detail, st = vfi.make_schedule(sc, fps_out)
    w, h = info["w"], info["h"]

    # 出力 frame j の「見るべき元 frame」。写しと保持は絵 k の先頭 frame
    runs = sc["runs"]
    want = {}
    for j, s in enumerate(sched):
        if int(s["kind"]) != vfi.retime.MODEL:
            want[j] = int(runs[int(s["k"])])

    srcs = {}
    need = set(want.values())
    for i, f in enumerate(stream(src, w, h)):
        if i in need:
            srcs[i] = f.copy()

    copy_ps, model_ps = [], []
    prev = None
    for j, f in enumerate(stream(out, w, h)):
        s = sched[j]
        if j in want:
            copy_ps.append(psnr(srcs[want[j]], f))
        elif prev is not None:
            k = int(s["k"])
            model_ps.append((psnr(srcs.get(int(runs[k]), f), f)
                             if int(runs[k]) in srcs else np.nan))
        prev = f

    copy_ps = np.array(copy_ps)
    model_ps = np.array([x for x in model_ps if not np.isnan(x)])
    rec = dict(src=src.name, out=out.name, out_frames=len(sched),
               copy_n=len(copy_ps), copy_psnr_min=round(float(copy_ps.min()), 2),
               copy_psnr_p50=round(float(np.median(copy_ps)), 2),
               model_n=len(model_ps),
               model_vs_left_psnr_p50=round(float(np.median(model_ps)), 2)
               if len(model_ps) else None,
               model_vs_left_psnr_max=round(float(model_ps.max()), 2)
               if len(model_ps) else None,
               sched=st)
    lib.record("t3_look", rec)
    for k, v in rec.items():
        print(f"  {k}: {v}")
    return rec


if __name__ == "__main__":
    check(sys.argv[1], sys.argv[2])
