"""vfi.scan (低解像度・memmap 無し) を、原寸の実測と突き合わせる。

比較相手は検証で使った物そのもの:
  絵の列   lib.drawing_runs  (原寸 BGR の box4 >= 16)
  cut      lib.cut_frames    (原寸 scdet + 画素で規約を揃えた物)
  絵間変位 r1_cadence.pairs  (原寸から 480x270 gray へ落とした Farneback p95)

一致率だけでなく **関門の判定が変わるか** を見る。速度の tool なので絵の列が
数枚違うのは許すが、封じる pair が変わると出力の見た目が変わる。
"""
import sys

import numpy as np

import lib
import r1_cadence as R1
import vfi


def compare(clip, mode="gpu"):
    src = lib.CLIPS[clip]["path"]
    info = vfi.probe(src)
    sc = vfi.scan(src, info, mode=mode)
    sc["fps_in"] = info["fps"]

    ref_runs = np.asarray(lib.drawing_runs(clip), dtype=np.int64)
    ref_cuts = np.asarray(lib.cut_frames(clip), dtype=np.int64)
    got_runs, got_cuts = sc["runs"], sc["cuts"]

    inter = np.intersect1d(ref_runs, got_runs)
    rec = dict(clip=clip, mode=mode, frames_ref=len(lib.load(clip)),
               frames=sc["n_frames"],
               runs_ref=len(ref_runs), runs=len(got_runs),
               runs_common=len(inter),
               runs_recall=round(len(inter) / len(ref_runs) * 100, 1),
               runs_prec=round(len(inter) / len(got_runs) * 100, 1),
               cuts_ref=sorted(int(x) for x in ref_cuts),
               cuts=sorted(int(x) for x in got_cuts))

    # 変位。両方で絵の先頭が一致する pair だけ突き合わせる
    p = R1.pairs(clip)
    ref_mv = {(int(a["r0"]), int(a["r1"])): float(a["mv"]) for a in p}
    pairs, dif = [], []
    for k in range(len(got_runs) - 1):
        key = (int(got_runs[k]), int(got_runs[k + 1]))
        if key in ref_mv:
            pairs.append((ref_mv[key], float(sc["mv"][k])))
            dif.append(abs(ref_mv[key] - float(sc["mv"][k])))
    if pairs:
        a = np.array([x[0] for x in pairs])
        b = np.array([x[1] for x in pairs])
        rec.update(mv_pairs=len(pairs),
                   mv_ref_p50=round(float(np.median(a)), 2),
                   mv_p50=round(float(np.median(b)), 2),
                   mv_absdiff_p50=round(float(np.median(dif)), 2),
                   mv_absdiff_p95=round(float(np.percentile(dif, 95)), 2),
                   gate_flip=int(((a > vfi.SPAN_LIMIT) != (b > vfi.SPAN_LIMIT)).sum()))

    blocked, detail = vfi.build_block(sc)
    rec["gate"] = detail
    lib.record("t1_scan", rec)
    for k, v in rec.items():
        print(f"  {k}: {v}")
    return rec


if __name__ == "__main__":
    args = sys.argv[1:]
    mode = "gpu"
    if args and args[0] in ("gpu", "cpu"):
        mode = args.pop(0)
    for c in (args or list(lib.CLIPS)):
        print(f"=== {c} ({mode})")
        compare(c, mode)
