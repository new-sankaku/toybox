"""現行 x2 の cut 判定(mad>18)が何を落としているかを確かめる。

a1_cadence.py の cut 判定は mad>18 **かつ** 輝度分布の相関<0.90 だったが、
a8_e2e.py は mad>18 だけを見ている。anime は閃光や white-out で mad が跳ねる
ので、これだけでは cut でない所まで「cut」として複製に落ちる。
"""
import sys

import cv2
import numpy as np
import torch

import lib
import smooth

CUT_MAD = 18.0
HIST_CORR = 0.90


def run(clip):
    a = lib.load(clip)
    g = smooth.scan(clip)["grays"]
    n = len(a)
    # GPU は他の Agent が使っているので CPU で出す(1本 720枚で十数秒)
    mad = np.empty(n - 1, np.float32)
    hc = np.empty(n - 1, np.float32)
    prev = a[0].astype(np.int16)
    for i in range(n - 1):
        cur = a[i + 1].astype(np.int16)
        mad[i] = float(np.abs(cur - prev).mean())
        prev = cur
    for i in range(n - 1):
        h0 = cv2.calcHist([g[i]], [0], None, [64], [0, 256])
        h1 = cv2.calcHist([g[i + 1]], [0], None, [64], [0, 256])
        hc[i] = cv2.compareHist(h0, h1, cv2.HISTCMP_CORREL)

    true_cut = np.zeros(n - 1, bool)
    for c in lib.cut_frames(clip):
        true_cut[int(c) - 1] = True
    fired = mad > CUT_MAD
    both = fired & (hc < HIST_CORR)
    r = dict(clip=clip, pairs=n - 1,
             scdet_cuts=int(true_cut.sum()),
             mad_only=int(fired.sum()),
             mad_and_hist=int(both.sum()),
             mad_only_false=int((fired & ~true_cut).sum()),
             mad_and_hist_false=int((both & ~true_cut).sum()),
             mad_only_missed=int((~fired & true_cut).sum()),
             mad_and_hist_missed=int((~both & true_cut).sum()),
             false_pct=round(float((fired & ~true_cut).sum()) / max(fired.sum(), 1) * 100, 1))
    lib.record("cutgate", r)
    print(r)
    return r


if __name__ == "__main__":
    for c in (sys.argv[1:] or list(lib.CLIPS)):
        run(c)
