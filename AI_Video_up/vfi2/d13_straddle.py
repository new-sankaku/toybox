"""3.8 の straddle の扱いが正しいかを、時間で一様に測った値の側から検算する。

3.8 は「straddle frame を除くと 60絵 の数字が良くなる」と書いた。しかし
**除いてよいとは限らない**。straddle frame は表示区間の後半で本当に古い絵を
出しているので、そこには実害がある。frame 数で平均する `smooth.measure` は
その1枚に「表示区間まるごと」の重みで誤差を課すが、時間で測れば実際に
古い絵が出ていた時間ぶんしか課さない。**どちらが実態に近いかは測れば判る。**

d12_fair が保存した標本(評価時刻・誤差)を、その時刻に画面へ出ている出力
frame が「絵の切り替わりを跨いでいるか」で分けて集計する。GPU は使わない。
"""
import sys

import numpy as np

import lib
import smooth
import d9_metric as M
import d12_fair as F


def split(clip, cond, grid_hz=F.GRID_HZ):
    p = M.CACHE / f"fair_{clip}_{cond}_{grid_hz:g}.npz"
    z = np.load(p)
    lags, t = z["lags"], z["t"]
    fps = F.EXACT[cond]
    runs = np.array([int(x) / lib.FPS for x in lib.drawing_runs(clip)])
    eps = 1e-9
    ks = (t * fps).astype(np.int64)
    st = np.array([bool(((runs > k / fps + eps)
                         & (runs < (k + 1) / fps - eps)).any()) for k in ks])
    # 跨いだ後(古い絵を出し続けている)時間だけをさらに切り出す
    stale = np.zeros(len(t), bool)
    for i, (ti, k) in enumerate(zip(t, ks)):
        if not st[i]:
            continue
        r = runs[(runs > k / fps + eps) & (runs < (k + 1) / fps - eps)]
        stale[i] = bool((ti >= r.min()))
    return dict(clip=clip, cond=cond, fps=round(fps, 3),
                samples=len(lags),
                lag_time_px=round(float(lags.mean()), 2),
                straddle_time_pct=round(float(st.mean()) * 100, 1),
                stale_time_pct=round(float(stale.mean()) * 100, 1),
                lag_stale_px=round(float(lags[stale].mean()), 2)
                if stale.any() else None,
                lag_fresh_px=round(float(lags[~stale].mean()), 2),
                # 「古い絵を出している時間」を全部除いた場合の値
                lag_excl_stale_px=round(float(lags[~stale].mean()), 2))


if __name__ == "__main__":
    for c in (sys.argv[1:] or list(lib.CLIPS)):
        for k in F.CONDS:
            p = M.CACHE / f"fair_{c}_{k}_{F.GRID_HZ:g}.npz"
            if not p.exists():
                continue
            r = split(c, k)
            lib.record("straddle_time", r)
            print(r, flush=True)
