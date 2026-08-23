"""素材そのものの実測。「効かない」の分母になる数字。

  - 1秒あたりの異なる絵の枚数(effective drawing rate)
  - 隣接 frame の組のうち「両端が同じ絵」の割合
    = x2 が中間を作っても複製にしかならない割合
  - 保持長の分布
  - 隣接する絵の間の変位(model が跨ぐ量)
"""
import sys

import numpy as np

import lib
import smooth


def run(clip):
    a = lib.load(clip)
    n = len(a)
    runs = lib.drawing_runs(clip)
    cuts = set(int(c) for c in lib.cut_frames(clip))
    dur = n / lib.FPS

    # 隣接 frame の組 (i, i+1)。i+1 が絵の開始でなければ「両端が同じ絵」
    starts = set(int(x) for x in runs)
    pairs = n - 1
    same = sum(1 for i in range(1, n) if i not in starts)
    cut_pairs = sum(1 for i in range(1, n) if i in cuts)

    holds = np.diff(np.append(runs, n))
    gaps, spans = smooth.gap_spans(clip)

    r = dict(clip=clip, frames=n, dur_s=round(dur, 2),
             drawings=int(len(runs)),
             drawing_rate=round(len(runs) / dur, 2),
             frames_per_drawing=round(n / len(runs), 2),
             pairs=pairs, same_pairs=same,
             same_pct=round(same / pairs * 100, 1),
             cut_pairs=cut_pairs,
             hold_p50=int(np.percentile(holds, 50)),
             hold_p95=int(np.percentile(holds, 95)),
             hold_max=int(holds.max()),
             hold_ms_p50=round(float(np.percentile(holds, 50)) / lib.FPS * 1000, 1),
             hold_ms_p95=round(float(np.percentile(holds, 95)) / lib.FPS * 1000, 1),
             gaps=len(gaps),
             span_p50=round(float(np.percentile(spans, 50)), 1),
             span_p75=round(float(np.percentile(spans, 75)), 1),
             span_p90=round(float(np.percentile(spans, 90)), 1),
             span_max=round(float(spans.max()), 1),
             span_over32_pct=round(float((spans > 32).mean()) * 100, 1))
    lib.record("source", r)
    print(r)
    smooth.measure(clip, clip, tag=f"src/{clip}")
    return r


if __name__ == "__main__":
    for c in (sys.argv[1:] or list(lib.CLIPS)):
        run(c)
