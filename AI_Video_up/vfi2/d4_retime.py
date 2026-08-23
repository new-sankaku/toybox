"""「絵の列へ補間して時刻を張り直す」を最小限で作る。指標の検証用。

本実装は別 Agent が作る。ここで作るのは、指標(lag_px)が本当に人の見た目と
対応するかを確かめるための参照実装で、速度は考えていない。

規則:
  出力 frame k の時刻 t = k/F。t が属する「絵と絵の区間」[t_a, t_b) を探し、
  tau = (t-t_a)/(t_b-t_a) の中間絵を model に作らせる。
  tau=0 なら素材の絵をそのまま。cut を跨ぐ区間は補間せず保持する。

  span が大きすぎる区間も保持する(model が単純平均に負ける領域。
  前回の検証で 32px が境目)。--span-limit 0 で無効化できる。
"""
import argparse
import sys

import numpy as np

import lib
import smooth

sys.path.insert(0, str(lib.VFI1))
import rifelib as R          # noqa: E402
import gpumetric as GM       # noqa: E402

MODEL = "v4.6"


def plan(clip, fps_out, span_limit=32.0):
    """出力 frame ごとに (a, b, tau) を決める。a==b は保持。"""
    gaps, spans = smooth.gap_spans(clip)
    span_of = {g: float(s) for g, s in zip(gaps, spans)}
    runs = [int(x) for x in lib.drawing_runs(clip)]
    n_out = int(len(lib.load(clip)) / lib.FPS * fps_out)
    out = []
    for k in range(n_out):
        t = k / fps_out
        i = np.searchsorted(runs, t * lib.FPS, side="right") - 1
        a = runs[max(i, 0)]
        b = runs[i + 1] if i + 1 < len(runs) else None
        if b is None or (a, b) not in span_of:
            out.append((a, a, 0.0))                 # cut を跨ぐ / 末尾
            continue
        if span_limit and span_of[(a, b)] > span_limit:
            out.append((a, a, 0.0))                 # 破綻領域なので保持する
            continue
        tau = (t - a / lib.FPS) / ((b - a) / lib.FPS)
        out.append((a, b, float(tau)))
    return out


def retime_frames(clip, fps_out, span_limit=32.0, model=MODEL, stat=None):
    a = lib.load(clip)
    m = R.Rife(model, lib.W, lib.H, fp16=True)
    if stat is None:
        stat = {}
    stat.setdefault("calls", 0)
    stat.setdefault("hold", 0)
    cache = {}
    for (i, j, tau) in plan(clip, fps_out, span_limit):
        if tau <= 0.0:
            stat["hold"] += 1
            yield GM.to_gpu(np.array(a[i]))
            continue
        f0 = cache.get(i)
        if f0 is None:
            f0 = cache[i] = GM.to_gpu(np.array(a[i]))
        f1 = cache.get(j)
        if f1 is None:
            f1 = cache[j] = GM.to_gpu(np.array(a[j]))
        cache = {i: f0, j: f1}
        R.pack(f0, f1, tau, m.dtype, out=m.dev_in)
        stat["calls"] += 1
        yield R.unpack(m.infer())


def run(clip, fps_out, span_limit=32.0):
    key = f"rt_{clip}_{fps_out:.0f}_{span_limit:g}_{MODEL}"
    stat = {}
    with lib.gpu_use("shindan"):
        sc = smooth.scan_frames(retime_frames(clip, fps_out, span_limit, stat=stat),
                                key, lib.W, lib.H, fps_out)
    if stat.get("calls"):
        lib.record("retime_gen", dict(clip=clip, fps_out=fps_out,
                                      span_limit=span_limit, model=MODEL,
                                      out_frames=sc["n"], **stat))
    r = smooth.measure(sc, clip, fps_out=fps_out,
                       tag=f"retime{fps_out:.0f}/{clip}" +
                           (f"/lim{span_limit:g}" if span_limit else "/nolim"))
    print(r)
    return r


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="*", default=None)
    ap.add_argument("--fps", type=float, default=lib.FPS * 2)
    ap.add_argument("--span-limit", type=float, default=32.0)
    args = ap.parse_args()
    for c in (args.clips or list(lib.CLIPS)):
        run(c, args.fps, args.span_limit)
