"""3本すべての目視。1/4 速の比較動画と、診断担当が読む連続 frame 画像。

窓の選び方は2つ:
  代表   … cut が少なく、絵と絵の変位の合計が最大の所(`busy_window`)
  最悪   … `lag_px` が元より最も悪化した区間(`d9_metric.regressions`)。
           「指標が壊れると言っている所」を名指しで見に行くための窓

GPU は使わない(出来上がった out/*.mp4 と cache を読むだけ)。
"""
import sys

import cv2
import numpy as np

import lib
import d9_metric as M
import d10_visual as V

CONDS = ("元", "x2素直", "60絵")


def worst_windows(clip, n=3, half=0.75, merge=0.6):
    """悪化の大きい区間を中心にした窓。近い物は1つに畳む。"""
    rs = M.regressions(clip)[:n]
    wins = []
    for a, b, span, la, lb, d in rs:
        t = a / lib.FPS
        wins.append([t - half, t + half, [(t, d)]])
    wins.sort()
    out = [wins[0]]
    for w in wins[1:]:
        if w[0] - out[-1][1] <= merge:
            out[-1][1] = max(out[-1][1], w[1])
            out[-1][2] += w[2]
        else:
            out.append(w)
    n_out = len(lib.load(clip)) / lib.FPS
    segs = []
    for t0, t1, marks in out:
        t0, t1 = max(t0, 0.0), min(t1, n_out - 0.05)
        cap = "metric worst: " + " ".join(f"t={t:.2f}s({d:+.0f}px)" for t, d in marks)
        segs.append((round(t0, 2), round(t1, 2), cap))
    return segs


def mark_times(clip, n=3):
    """悪化の大きい区間の中心時刻(秒)。連続 frame 画像はここへ合わせる。"""
    return [a / lib.FPS for a, b, s, la, lb, d in M.regressions(clip)[:n]]


def contact_multi(clip, t0, dur, dst, conds=CONDS, side=384, tile=176):
    """同じ時刻に各条件で何が出ているかを、連続 frame の帯にして並べる。"""
    rows, box = [], None
    got = []
    for path, fps, name in V.cols_of(clip, conds):
        n = max(int(round(dur * fps)), 2)
        fr = V.grab(path, int(round(t0 * fps)), n)
        got.append((fr, fps, name))
    box = V.motion_box(got[-1][0], side)     # 一番 frame の多い列で動きを探す
    for fr, fps, name in got:
        rows.append(V.strip(fr, box, tile,
                            label=f"{name}  ({len(fr)} frames = {dur*1000:.0f}ms)"
                                  "   * = new drawing  |  = = duplicate"))
    w = max(r.shape[1] for r in rows)
    pad = lambda x: np.pad(x, ((0, 0), (0, w - x.shape[1]), (0, 0)))
    gap = np.zeros((8, w, 3), np.uint8)
    sheet = np.concatenate([x for r in rows for x in (pad(r), gap)][:-1], axis=0)
    ok, enc = cv2.imencode(".png", sheet)
    if not ok:
        raise RuntimeError("png へ encode できません")
    dst.write_bytes(enc.tobytes())
    return dst, box


NAME = {"元": "元", "x2素直": "x2素直", "x2絵": "48絵", "60絵": "60絵",
        "120絵": "120絵"}


def run(clip, conds=CONDS, tile=(640, 360), busy=True, n_worst=3, suffix=""):
    segs = []
    if busy:
        b0, b1, score = V.busy_window(clip)
        segs.append((round(b0, 2), round(b1, 2),
                     f"busy: t={b0:.2f}-{b1:.2f}s (sum span {score:.0f}px)"))
    segs += worst_windows(clip, n=n_worst)
    lib.log(f"{clip}: 窓 {segs}")
    tag = "と".join(NAME[c] for c in conds)
    dst = lib.OUT / f"目視_{clip}_{tag}_4分の1速{suffix}.mp4"
    V.slow_grid(V.cols_of(clip, conds), segs, dst, tile=tile)
    lib.record("look3", dict(clip=clip, conds=list(conds), segments=segs,
                             tile=list(tile), out=str(dst)))
    lib.log(f"  {dst}")
    sheets = []
    for i, (t0, t1, cap) in enumerate(segs):
        p = lib.RESULTS / f"目視_{clip}_連続frame{suffix}_{i}.png"
        contact_multi(clip, t0 + 0.02, 0.25, p, conds)
        sheets.append((cap, str(p)))
        lib.log(f"  {p}  ({cap})")
    lib.record("look3_sheet", dict(clip=clip, conds=list(conds), sheets=sheets))
    return dst, sheets


if __name__ == "__main__":
    for c in (sys.argv[1:] or ["C_act", "A_op", "B_talk"]):
        run(c)
