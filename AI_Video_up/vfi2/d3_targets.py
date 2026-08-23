"""目標 fps ごとの見積もり。GPU は使わない(spanの実測値だけを使う)。

  - 絵と絵の間を何等分することになるのか
  - そのとき model が跨ぐ変位(= 絵と絵の変位そのもの。fps に依らない)
  - 破綻領域(跨ぎ 32px 超)が、区間数・画面に出ている時間・生成frame数の
    それぞれで何%になるか
"""
import sys

import numpy as np

import lib
import smooth

SPAN_LIMIT = 32.0
TARGETS = [lib.FPS * 2, 60.0, 120.0]


def run(clip):
    gaps, spans = smooth.gap_spans(clip)
    n = len(lib.load(clip))
    dur = n / lib.FPS
    runs = lib.drawing_runs(clip)
    rate = len(runs) / dur

    hold_s = np.array([(b - a) / lib.FPS for a, b in gaps], dtype=np.float64)
    over = spans > SPAN_LIMIT
    # 時間で見た破綻領域。区間数で見ると、長い保持(=ほぼ静止)の1件と
    # 一瞬の大変位の1件が同じ重みになり、画面の見え方と合わなくなる
    t_over = float(hold_s[over].sum() / hold_s.sum())

    rows = []
    for f in TARGETS:
        n_out = dur * f
        per_gap = hold_s * f                      # その区間に落ちる出力frame数
        gen_pct = 1.0 - min(rate / f, 1.0)        # 生成frameの割合
        rows.append(dict(
            clip=clip, fps=round(f, 1),
            split_mean=round(f / rate, 1),
            split_p50=round(float(np.percentile(per_gap, 50)), 1),
            split_p95=round(float(np.percentile(per_gap, 95)), 1),
            calls_per_s=round(f - rate, 0),
            gen_pct=round(gen_pct * 100, 1),
            gen_over32_pct=round(gen_pct * t_over * 100, 1),
            out_frames=int(n_out)))
    r = dict(clip=clip, drawing_rate=round(rate, 2),
             gaps=len(gaps),
             span_p50=round(float(np.percentile(spans, 50)), 1),
             span_p75=round(float(np.percentile(spans, 75)), 1),
             span_p90=round(float(np.percentile(spans, 90)), 1),
             span_max=round(float(spans.max()), 1),
             over32_gap_pct=round(float(over.mean()) * 100, 1),
             over32_time_pct=round(t_over * 100, 1),
             targets=rows)
    lib.record("targets", r)
    for k, v in r.items():
        if k != "targets":
            print(f"  {k}: {v}")
    for row in rows:
        print("   ", row)
    return r


if __name__ == "__main__":
    for c in (sys.argv[1:] or list(lib.CLIPS)):
        run(c)
