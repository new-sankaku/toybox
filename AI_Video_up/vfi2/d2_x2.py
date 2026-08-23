"""素直な x2(現行実装)を作り、滑らかさを測る。

現行の a8_e2e.py と同じ規則で組む:
  出力 frame 2i   = 素材 frame i
  出力 frame 2i+1 = box4 < gate なら素材 frame i をそのまま写す
                    cut なら素材 frame i をそのまま写す
                    それ以外は model の tau=0.5

file へ書かずに、生成した frame をその場で smooth.scan_frames() へ流す。
1080p を lossless で置くと1本 9GB になり、3本ぶんの置き場が無い。
目で見る用の動画だけ、あとから区間を切って別に作る(d5_look.py)。
"""
import sys

import numpy as np
import torch

import lib
import smooth

sys.path.insert(0, str(lib.VFI1))
import rifelib as R          # noqa: E402
import gpumetric as GM       # noqa: E402

MODEL = "v4.6"
GATE = 16                    # a8_e2e の既定と同値
CUT_MAD = 18.0               # a8_e2e の cut 判定と同値


def x2_frames(clip, model=MODEL, gate=GATE, stat=None):
    a = lib.load(clip)
    m = R.Rife(model, lib.W, lib.H, fp16=True)
    prev = None
    for i in range(len(a)):
        cur = GM.to_gpu(np.array(a[i]))
        if prev is not None:
            d = (cur.float() - prev.float()).abs_()
            box4 = float(torch.nn.functional.avg_pool2d(
                d.permute(2, 0, 1).unsqueeze(0), 4).round_().amax())
            mad = float(d.mean())
            if box4 < gate:
                stat["skip_static"] += 1
                yield prev
            elif mad > CUT_MAD:
                stat["skip_cut"] += 1
                yield prev
            else:
                R.pack(prev, cur, 0.5, m.dtype, out=m.dev_in)
                stat["calls"] += 1
                yield R.unpack(m.infer())
        yield cur
        prev = cur


def run(clip):
    key = f"x2_{clip}_{MODEL}_g{GATE}"
    stat = dict(calls=0, skip_static=0, skip_cut=0)
    # 時間は測らないので共有側で囲む(排他にすると速度計測班が止まる)
    with lib.gpu_use("shindan"):
        sc = smooth.scan_frames(x2_frames(clip, stat=stat), key,
                                lib.W, lib.H, lib.FPS * 2)
    if stat["calls"]:
        n_mid = stat["calls"] + stat["skip_static"] + stat["skip_cut"]
        lib.record("x2_gen", dict(clip=clip, model=MODEL, gate=GATE,
                                  out_frames=sc["n"], mid=n_mid, **stat,
                                  dup_pct=round(stat["skip_static"] / n_mid * 100, 1)))
    r = smooth.measure(sc, clip, fps_out=lib.FPS * 2, tag=f"x2/{clip}")
    print(r)
    return r


if __name__ == "__main__":
    for c in (sys.argv[1:] or list(lib.CLIPS)):
        run(c)
