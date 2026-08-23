"""指標そのものを検算する。GPU は使わない(smooth の cache を読むだけ)。

見るのは2点:

1. lag_px は「封じた区間(意図的な静止・cut・大変位)」を含んだままの平均なので、
   そこが尺の半分を占める素材では動きようがない。区間を分けて測り直す。
   frame -> 区間 の対応は smooth._lag_step と同じ式で組み直せる(純粋な算術)。

2. step_cv が効かない理由。cv = std/mean は無次元なので、跳び幅が px で
   小さくなった事を原理的に見られない。分解して数字で示す。
"""
import re
import sys
from pathlib import Path

import numpy as np

import lib
import smooth

CACHE = smooth.CACHE
STILL_HOLD = 9        # 保持がこれ以上の絵は「意図的に止めてある」(時刻張り直し 3.3)
SPAN_LIMIT = 64.0     # 跨ぐ変位がこれを超える区間は封じる(同 3.5)


def outputs():
    """cache に在る「測り終えた出力」を (tag, key, clip, fps) で列挙する。"""
    out = []
    for p in sorted(CACHE.glob("lag_*_ph0.5.npz")):
        rest = p.name[len("lag_"):-len("_ph0.5.npz")]
        key, clip, fps = None, None, None
        for c in lib.CLIPS:
            m = re.match(rf"^(.*)_{c}_(\d+\.\d+)$", rest)
            if m:
                key, clip, fps = m.group(1), c, float(m.group(2))
                break
        if key is None:
            raise ValueError(f"{p.name}: clip 名を読めません")
        sp = CACHE / f"scan_{key}.npz"
        if not sp.exists():
            raise FileNotFoundError(f"{sp} が在りません")
        out.append((key, clip, fps, p, sp))
    return out


def jobs_of(clip, n_out, fps):
    """出力 frame k -> 区間 (a, b)。smooth._lag_step と同じ式。

    lags 配列は「区間に入った k」の順に並ぶので、この列と1対1で対応する。
    """
    gaps, spans = smooth.gap_spans(clip)
    span_of = {g: float(s) for g, s in zip(gaps, spans)}
    js = []
    for k in range(n_out):
        t = (k + smooth.PHASE) / fps
        for (a, b) in gaps:
            if a / lib.FPS <= t < b / lib.FPS:
                js.append((a, b, span_of[(a, b)]))
                break
    return js


def find(clip, cond):
    """条件名(元 / x2素直 / 60絵 …)から cache の lag/scan を引く。"""
    for p in CACHE.glob(f"lag_{clip}_{cond}_*_ph0.5.npz"):
        rest = p.name[len("lag_"):-len("_ph0.5.npz")]
        m = re.match(rf"^(.*)_{clip}_(\d+\.\d+)$", rest)
        return m.group(1), float(m.group(2)), p
    raise FileNotFoundError(f"{clip}/{cond} の lag cache が在りません")


def per_gap_lag(clip, cond):
    """区間ごとの平均 lag(px)。出力の frame rate が違っても比較できる。"""
    key, fps, lagp = find(clip, cond)
    n_out = int(np.load(CACHE / f"scan_{key}.npz")["n"])
    lags = np.load(lagp)["lags"]
    js = jobs_of(clip, n_out, fps)
    if len(js) != len(lags):
        raise ValueError(f"{key}: 割り当て {len(js)} と lags {len(lags)} が違います")
    acc = {}
    for (a, b, s), v in zip(js, lags):
        acc.setdefault((a, b, s), []).append(float(v))
    return {k: float(np.mean(v)) for k, v in acc.items()}


def regressions(clip, base="元", cond="60絵", free_only=True):
    """base に対して cond がどれだけ悪化した区間か。悪化の大きい順。

    戻り: [(a, b, span, lag_base, lag_cond, 悪化px), ...]
    """
    A, B = per_gap_lag(clip, base), per_gap_lag(clip, cond)
    out = []
    for k in A:
        if k not in B:
            continue
        a, b, s = k
        if free_only and ((b - a) >= STILL_HOLD or s > SPAN_LIMIT):
            continue
        out.append((a, b, s, A[k], B[k], B[k] - A[k]))
    out.sort(key=lambda r: -r[5])
    return out


def split_lag(key, clip, fps, lagp, scanp):
    z = np.load(lagp)
    lags, steps = z["lags"], z["steps"]
    n_out = int(np.load(scanp)["n"])
    js = jobs_of(clip, n_out, fps)
    if len(js) != len(lags):
        raise ValueError(f"{key}: 区間の割り当てが {len(js)} で lags {len(lags)} と違います")
    blocked = np.array([(b - a) >= STILL_HOLD or s > SPAN_LIMIT for a, b, s in js])
    return dict(key=key, clip=clip, fps=round(fps, 3), frames=n_out,
                covered=len(lags),
                lag_all=round(float(lags.mean()), 2),
                lag_free=round(float(lags[~blocked].mean()), 2),
                lag_blocked=round(float(lags[blocked].mean()), 2),
                free_frames=int((~blocked).sum()),
                blocked_frames=int(blocked.sum()),
                blocked_pct=round(float(blocked.mean()) * 100, 1),
                step_mean=round(float(steps.mean()), 3),
                step_std=round(float(steps.std()), 3),
                step_cv=round(float(steps.std() / max(steps.mean(), 1e-9)), 2),
                step_p95=round(float(np.percentile(steps, 95)), 2),
                step_zero_pct=round(float((steps < 0.5).mean()) * 100, 1),
                step_big_mean=round(float(steps[steps >= 4.0].mean())
                                    if (steps >= 4.0).any() else 0.0, 2),
                step_big_pct=round(float((steps >= 4.0).mean()) * 100, 1))


def main():
    rows = []
    for key, clip, fps, lagp, scanp in outputs():
        r = split_lag(key, clip, fps, lagp, scanp)
        rows.append(r)
        lib.record("metric_split", r)
        print(r)
    return rows


if __name__ == "__main__":
    main()
