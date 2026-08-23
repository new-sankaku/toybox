"""低解像度の「同じ絵」判定の閾値を、原寸の実測に合わせて選ぶ。

原寸は BGR の box4 max >= 16 (lib.MOVE_MIN)。走査は 480幅 gray の max|差|。
lead_coverage.py は 6 を使っていたが、それを合わせたのは B_talk 1本だけ。
3本すべてで、絵の列と **関門の判定** がどれだけ合うかで選び直す。

見る物:
  recall     原寸の絵の先頭のうち、走査でも先頭になった割合
  prec       走査の絵の先頭のうち、原寸でも先頭だった割合
  静止尺差   意図的な静止(保持9以上)が占める尺の、原寸との差。
             ここがずれると「止めてある絵を溶かす」事故になる
"""
import sys

import numpy as np

import lib
import r1_cadence as R1
import r5_render as R5
import vfi


def ref_gate(clip):
    """原寸の実測から作った関門 (r5_render.schedule_for と同じ式)。"""
    n = len(lib.load(clip))
    runs = np.asarray(lib.drawing_runs(clip), dtype=np.int64)
    p = R1.pairs(clip)
    gap = p["gap"].astype(np.int64)
    still = gap > R5.HOLD_MAX
    far = p["mv"] > R5.MV_GATE
    blocked = p["cut"] | still | far
    dur = gap / lib.FPS
    total = float(dur.sum())
    return dict(runs=runs, n=n, total=total,
                still_pct=float(dur[still].sum()) / total * 100,
                block_pct=float(dur[blocked].sum()) / total * 100)


def sweep(clip, ths):
    src = lib.CLIPS[clip]["path"]
    info = vfi.probe(src)
    ref = ref_gate(clip)
    print(f"\n=== {clip}  原寸: 絵 {len(ref['runs'])} / "
          f"静止尺 {ref['still_pct']:.1f}% / 封じた尺 {ref['block_pct']:.1f}%")
    print("  | 閾値 | 絵 | recall | prec | 静止尺% | 差 | 封じた尺% | 差 |")
    print("  |---|---|---|---|---|---|---|---|")
    rows = []
    for th in ths:
        sc = vfi.scan(src, info, same_th=th)
        sc["fps_in"] = info["fps"]
        _blk, det = vfi.build_block(sc)
        got = sc["runs"]
        inter = np.intersect1d(ref["runs"], got)
        row = dict(clip=clip, th=th, runs=len(got),
                   recall=round(len(inter) / len(ref["runs"]) * 100, 1),
                   prec=round(len(inter) / len(got) * 100, 1),
                   still_pct=det["意図的な静止"]["尺_pct"],
                   still_d=round(det["意図的な静止"]["尺_pct"] - ref["still_pct"], 1),
                   block_pct=det["封じた計"]["尺_pct"],
                   block_d=round(det["封じた計"]["尺_pct"] - ref["block_pct"], 1))
        rows.append(row)
        print(f"  | {th} | {row['runs']} | {row['recall']}% | {row['prec']}% | "
              f"{row['still_pct']} | {row['still_d']:+} | "
              f"{row['block_pct']} | {row['block_d']:+} |")
        lib.record("t2_thresh", row)
    return rows


if __name__ == "__main__":
    ths = [int(x) for x in (sys.argv[1].split(",") if len(sys.argv) > 1
                            else "4,6,8,10,12,14,16".split(","))]
    for c in list(lib.CLIPS):
        sweep(c, ths)
