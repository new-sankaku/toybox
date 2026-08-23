"""cut の確定。ffmpeg scdet の score を取り込み、閾値を目で確かめる。

cut を跨いで補間すると2枚が溶けたframeが出る。速度(呼ばずに済む)と品質の
両方に効くので、閾値は当て推量ではなく検出結果を並べて確認する。
"""
import re
import sys

import cv2
import numpy as np

import vfilib as V

THRESH = 10.0   # ffmpeg scdet の既定


def parse_scd(clip):
    txt = (V.RESULTS / f"scene_{clip}.txt").read_text(encoding="utf-8", errors="replace")
    scores = {}
    cur = None
    for line in txt.splitlines():
        m = re.match(r"frame:(\d+)", line)
        if m:
            cur = int(m.group(1))
        m = re.search(r"lavfi\.scd\.score=([\d.]+)", line)
        if m and cur is not None:
            scores[cur] = float(m.group(1))
    n = max(scores) + 1
    out = np.zeros(n, np.float32)
    for k, v in scores.items():
        out[k] = v
    return out


def run(clip, thresh=THRESH):
    scd = parse_scd(clip)          # scd[k] は frame k と k-1 の間の score
    cad = np.load(V.RESULTS / f"cadence_{clip}.npy")
    # cadence の pair i は frame i と i+1 の間 → scd[i+1]
    s = scd[1:len(cad) + 1]
    cuts = np.where(s >= thresh)[0]
    V.log(f"{clip}: scd score p50={np.median(s):.2f} p95={np.percentile(s,95):.2f} "
          f"max={s.max():.2f}  cut={len(cuts)}件 (閾値{thresh})")

    a = V.load(clip)
    # 検出したcutの前後2枚を並べて目で確かめる
    if len(cuts):
        tiles = []
        for i in cuts[:24]:
            pair = np.hstack([cv2.resize(a[i], (240, 135)),
                              cv2.resize(a[i + 1], (240, 135))])
            cv2.putText(pair, f"{i} s={s[i]:.0f}", (4, 14),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
            tiles.append(pair)
        while len(tiles) % 4:
            tiles.append(np.zeros_like(tiles[0]))
        sheet = np.vstack([np.hstack(tiles[r:r + 4]) for r in range(0, len(tiles), 4)])
        cv2.imwrite(str(V.RESULTS / f"cuts_{clip}.png"), sheet)

    # 閾値を1段下げた所に何が居るかも見る(取りこぼしの確認)
    near = np.where((s >= thresh * 0.4) & (s < thresh))[0]
    if len(near):
        tiles = []
        for i in near[:16]:
            pair = np.hstack([cv2.resize(a[i], (240, 135)),
                              cv2.resize(a[i + 1], (240, 135))])
            cv2.putText(pair, f"{i} s={s[i]:.1f}", (4, 14),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
            tiles.append(pair)
        while len(tiles) % 4:
            tiles.append(np.zeros_like(tiles[0]))
        sheet = np.vstack([np.hstack(tiles[r:r + 4]) for r in range(0, len(tiles), 4)])
        cv2.imwrite(str(V.RESULTS / f"cuts_near_{clip}.png"), sheet)

    np.save(V.RESULTS / f"scd_{clip}.npy", s)
    V.record("cuts", dict(clip=clip, thresh=thresh, n_cut=int(len(cuts)),
                          n_near=int(len(near)),
                          scd_p50=round(float(np.median(s)), 3),
                          scd_p95=round(float(np.percentile(s, 95)), 3),
                          cut_idx=[int(x) for x in cuts]))
    return cuts


if __name__ == "__main__":
    for c in (sys.argv[1:] or list(V.CLIPS)):
        run(c)
