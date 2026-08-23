"""品質試験集合を「絵の列」で組む。3 clip 全部。

## 組み方

生成した中間 frame には正解が無い。実測できるのは **1枚落として復元** だけ。
ただし anime を frame の3つ組で組むと、1枚の絵が数 frame 保持されるせいで
真ん中が両端のどちらかと同一になり、hold(何もしない)が満点を取って
model の巧拙が消える。

そこで **絵の列** で組む。連続する3枚の絵 D0, D1, D2 を取り、両端 D0, D2 から
真ん中 D1 を作って本物と比べる。時刻は絵の frame 番号から出す:

    tau = (r1 - r0) / (r2 - r0)

これは「絵と絵の間を任意時刻で補間して時刻を張り直す」という本番の問題と
同じ形で、しかも間隔が1段広いぶん本番より辛い。

## 層

model の得意領域は跨ぐ変位で違う。D0 から D2 への optical flow の p95 を
1080p 画素で測り、0-4 / 4-8 / 8-16 / 16-32 / 32-64 / 64-128 / 128- px の
7層へ分ける。各層から同数を取るので、**全体平均は層の母数で重み付けし直す**
必要がある(weight 欄。素の平均は稀な難所を過大評価する)。

## 除く物

- cut を跨ぐ組。cut は補間せず hold するのが正解で model の優劣と無関係
- D0 から D2 までが MAX_SPAN frame を超える組。1秒近く止まった後の絵は
  補間の対象ではない
"""
import sys

import cv2
import numpy as np

import lib

MAX_SPAN = 12         # D0 から D2 までの frame 数の上限
PER_BIN = 24          # 各層から取る組の数
BINS = [0, 4, 8, 16, 32, 64, 128, 1e9]
BIN_LABELS = ["0-4", "4-8", "8-16", "16-32", "32-64", "64-128", "128-"]
SMALL = (480, 270)

DTYPE = [("r0", "i4"), ("r1", "i4"), ("r2", "i4"), ("tau", "f4"),
         ("span", "f4"), ("box4", "i4"), ("bin", "i1"), ("weight", "f4")]


def _flow_p95(flow, a, i, j):
    """D0 から D2 への変位の p95(1080p の画素で)。"""
    g0 = cv2.cvtColor(cv2.resize(np.array(a[i]), SMALL, interpolation=cv2.INTER_AREA),
                      cv2.COLOR_BGR2GRAY)
    g1 = cv2.cvtColor(cv2.resize(np.array(a[j]), SMALL, interpolation=cv2.INTER_AREA),
                      cv2.COLOR_BGR2GRAY)
    f = flow.calc(g0, g1, None)
    mag = np.sqrt(f[..., 0] ** 2 + f[..., 1] ** 2)
    return float(np.percentile(mag, 95)) * (lib.W / SMALL[0])


def build(clip, seed=0):
    a = lib.load(clip)
    scd = lib.scdet(clip)
    runs = lib.drawing_runs(clip)
    lib.log(f"{clip}: frame {len(a)} / 絵 {len(runs)}枚 "
            f"({len(a)/len(runs):.2f} frame/枚)")

    flow = cv2.FarnebackOpticalFlow_create(numLevels=5, pyrScale=0.5, winSize=25,
                                           numIters=3, polyN=5, polySigma=1.2)
    cand = []
    for k in range(len(runs) - 2):
        r0, r1, r2 = int(runs[k]), int(runs[k + 1]), int(runs[k + 2])
        if r2 - r0 > MAX_SPAN:
            continue
        if (scd[r0:r2] >= lib.SCD_CUT).any():
            continue
        span = _flow_p95(flow, a, r0, r2)
        cand.append((r0, r1, r2, (r1 - r0) / (r2 - r0), span,
                     lib.box4_max(a[r0], a[r2]), 0, 0.0))
    if len(cand) < 20:
        raise RuntimeError(f"{clip}: 試験に使える組が {len(cand)} しかありません")
    cand = np.array(cand, dtype=DTYPE)
    cand["bin"] = np.clip(np.digitize(cand["span"], BINS) - 1, 0, len(BIN_LABELS) - 1)

    rng = np.random.default_rng(seed)
    picked = []
    pop = {}
    for b in range(len(BIN_LABELS)):
        idx = np.where(cand["bin"] == b)[0]
        pop[b] = len(idx)
        if not len(idx):
            continue
        take = rng.choice(idx, min(len(idx), PER_BIN), replace=False)
        picked.extend(take.tolist())
    sel = cand[sorted(picked)].copy()
    # 母集団の割合へ戻す重み。層別に同数取っているので素の平均は難所へ寄る
    for b in range(len(BIN_LABELS)):
        m = sel["bin"] == b
        if m.any():
            sel["weight"][m] = pop[b] / len(cand) / m.sum()

    np.save(lib.RESULTS / f"testset_{clip}.npy", sel)
    info = dict(clip=clip, frames=len(a), drawings=len(runs),
                frames_per_drawing=round(len(a) / len(runs), 2),
                candidates=len(cand), picked=len(sel),
                max_span=MAX_SPAN, per_bin=PER_BIN,
                span_p50=round(float(np.percentile(cand["span"], 50)), 1),
                span_p95=round(float(np.percentile(cand["span"], 95)), 1),
                span_max=round(float(cand["span"].max()), 1),
                tau_median=round(float(np.median(sel["tau"])), 3),
                pop={BIN_LABELS[b]: pop[b] for b in range(len(BIN_LABELS))},
                picked_per_bin={BIN_LABELS[b]: int((sel["bin"] == b).sum())
                                for b in range(len(BIN_LABELS))})
    lib.record("testset2", info)
    for k, v in info.items():
        print(f"  {k}: {v}")
    return sel


if __name__ == "__main__":
    for c in (sys.argv[1:] or list(lib.CLIPS)):
        build(c)
