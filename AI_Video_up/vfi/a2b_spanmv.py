"""試験組が実際に跨ぐ変位を測る。品質を読む時の横軸。

testset の `mv` は「隣り合うframe間の変位の最大」で、model が実際に跨ぐ量
(D0 から D2 まで)ではない。x2 本番で model が跨ぐのは隣接pair1つぶんなので、
横軸を「跨ぎ幅」に揃えないと、試験の数字を本番へ読み替えられない。
"""
import sys

import cv2
import numpy as np

import vfilib as V

SMALL = (480, 270)


def flow_p95(a, i, j, flow):
    g0 = cv2.cvtColor(cv2.resize(a[i], SMALL, interpolation=cv2.INTER_AREA),
                      cv2.COLOR_BGR2GRAY)
    g1 = cv2.cvtColor(cv2.resize(a[j], SMALL, interpolation=cv2.INTER_AREA),
                      cv2.COLOR_BGR2GRAY)
    f = flow.calc(g0, g1, None)
    mag = np.sqrt(f[..., 0] ** 2 + f[..., 1] ** 2)
    return float(np.percentile(mag, 95)) * (V.W / SMALL[0])


def run(clip):
    a = V.load(clip)
    ts = np.load(V.RESULTS / f"testset_{clip}.npy")
    flow = cv2.FarnebackOpticalFlow_create(numLevels=5, pyrScale=0.5, winSize=25,
                                           numIters=3, polyN=5, polySigma=1.2)
    span = np.array([flow_p95(a, int(r["r0"]), int(r["r2"]), flow) for r in ts],
                    dtype=np.float32)
    np.save(V.RESULTS / f"spanmv_{clip}.npy", span)
    V.record("spanmv", dict(clip=clip, n=len(span),
                            p50=round(float(np.percentile(span, 50)), 1),
                            p75=round(float(np.percentile(span, 75)), 1),
                            p90=round(float(np.percentile(span, 90)), 1),
                            max=round(float(span.max()), 1)))
    V.log(f"  {clip}: 跨ぎ幅 p50={np.percentile(span,50):.1f} "
          f"p75={np.percentile(span,75):.1f} p90={np.percentile(span,90):.1f} "
          f"max={span.max():.1f} px")


if __name__ == "__main__":
    for c in (sys.argv[1:] or list(V.CLIPS)):
        run(c)
