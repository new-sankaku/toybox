"""絵の列を実測する。時刻の張り直しに要る量をここで全部そろえる。

出す物 (results/retime_pairs_<clip>.npy):
  k        絵 index
  r0, r1   絵 D_k / D_k+1 の先頭 frame
  L0       D_k が保持される frame 数
  gap      r1 - r0 (代表時刻 head での間隔。frame)
  mv       D_k -> D_k+1 の optical flow p95 (原寸 px)。跨ぐ変位
  box4     D_k -> D_k+1 の box4 max
  cut      この pair に cut が入っているか

frame ごとの same(隣の frame と同じ絵か) も出す。素直な x2 の対照に要る。
"""
import concurrent.futures as cf
import os
import sys
import threading

import cv2
import numpy as np

import lib

SMALL = (480, 270)

PAIR = np.dtype([("k", "i4"), ("r0", "i4"), ("r1", "i4"), ("L0", "i4"),
                 ("gap", "i4"), ("mv", "f4"), ("box4", "f4"), ("cut", "?")])


class _TL(threading.local):
    @property
    def flow(self):
        f = getattr(self, "_f", None)
        if f is None:
            f = cv2.FarnebackOpticalFlow_create(
                numLevels=5, pyrScale=0.5, winSize=25, numIters=3,
                polyN=5, polySigma=1.2)
            self._f = f
        return f


_T = _TL()


def _gray(a, i):
    return cv2.cvtColor(cv2.resize(np.array(a[i]), SMALL,
                                   interpolation=cv2.INTER_AREA),
                        cv2.COLOR_BGR2GRAY)


def pairs(clip):
    dst = lib.RESULTS / f"retime_pairs_{clip}.npy"
    if dst.exists():
        return np.load(dst)
    a = lib.load(clip)
    n = len(a)
    runs = lib.drawing_runs(clip)
    scd = lib.scdet(clip)
    K = len(runs)
    lib.log(f"{clip}: frame {n} / 絵 {K}")

    grays = {}
    for k in range(K):
        grays[k] = _gray(a, int(runs[k]))

    def one(k):
        f = _T.flow.calc(grays[k], grays[k + 1], None)
        mag = np.sqrt(f[..., 0] ** 2 + f[..., 1] ** 2)
        return float(np.percentile(mag, 95)) * (lib.W / SMALL[0])

    with cf.ThreadPoolExecutor(max_workers=os.cpu_count()) as ex:
        mv = list(ex.map(one, range(K - 1)))

    rows = []
    for k in range(K - 1):
        r0, r1 = int(runs[k]), int(runs[k + 1])
        cut = bool((scd[r0:r1] >= lib.SCD_CUT).any())
        rows.append((k, r0, r1, r1 - r0, r1 - r0, mv[k],
                     lib.box4_max(a[r0], a[r1]), cut))
    out = np.array(rows, dtype=PAIR)
    np.save(dst, out)
    return out


def same_frames(clip):
    """frame i と i+1 が同じ絵か(素直な x2 が model を呼ばずに済む所)。"""
    dst = lib.RESULTS / f"same_{clip}.npy"
    if dst.exists():
        return np.load(dst)
    a = lib.load(clip)
    out = np.array([lib.box4_max(a[i], a[i + 1]) < lib.MOVE_MIN
                    for i in range(len(a) - 1)], dtype=bool)
    np.save(dst, out)
    return out


def report(clip):
    a = lib.load(clip)
    n = len(a)
    p = pairs(clip)
    sm = same_frames(clip)
    runs = lib.drawing_runs(clip)
    L = np.append(np.diff(runs), n - runs[-1])
    dur = n / lib.FPS

    hist = {int(k): int(v) for k, v in zip(*np.unique(L, return_counts=True))}
    live = p[~p["cut"]]
    info = dict(
        clip=clip, frames=n, drawings=len(runs), duration_s=round(dur, 3),
        drawings_per_sec=round(len(runs) / dur, 2),
        hold_hist=hist,
        hold_mean=round(float(L.mean()), 2),
        hold_p90=int(np.percentile(L, 90)),
        hold_max=int(L.max()),
        cut_pairs=int(p["cut"].sum()),
        cut_pct=round(float(p["cut"].mean()) * 100, 1),
        same_frame_pairs=int(sm.sum()),
        same_frame_pct=round(float(sm.mean()) * 100, 1),
        mv_p50=round(float(np.percentile(live["mv"], 50)), 1),
        mv_p90=round(float(np.percentile(live["mv"], 90)), 1),
        mv_max=round(float(live["mv"].max()), 1),
        mv_over32_pct=round(float((live["mv"] > 32).mean()) * 100, 1),
        mv_over64_pct=round(float((live["mv"] > 64).mean()) * 100, 1),
    )
    lib.record("retime_cadence", info)
    for k, v in info.items():
        print(f"  {k}: {v}")
    return info


if __name__ == "__main__":
    for c in (sys.argv[1:] or list(lib.CLIPS)):
        lib.log(f"=== {c}")
        report(c)
