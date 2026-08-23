"""出力 fps の違いを公平に比べる。共通の評価時刻で測り直す。

## なぜ測り直すか

`smooth.measure` は **出力 frame ごと**に誤差を測り、frame 数で平均します。
出力 fps が違う条件を並べると、これが2つの系統誤差を生みます。

1. **straddle**(3.8)。出力 frame の表示区間の内側で絵が切り替わると、
   metric は切り替わりの全量をその1枚に課す。出力 fps が素材 fps の
   整数倍(23.976 / 47.952)なら起きず、60 / 120fps では起きる。
2. **複製 frame の誤差ゼロ**。47.952fps では出力 frame の約半分が
   tau=0 ちょうど、つまり素材の絵そのものになる。metric はこれを
   `flow = 0`(厳密)として扱うので、誤差は **ちょうど 0**。
   60fps では tau=0 に乗る frame がほぼ無いので、正しい位置に置いても
   雑音の下限(区間の変位の 15.5%)が必ず乗る。

どちらも「絵が正しい位置に居るか」ではなく「出力 frame の刻みがどこに
乗ったか」で値が動きます。**人が見るのは frame の列ではなく時間**なので、
評価も時間で一様に取るべきです。

## やっていること

1000Hz の格子の各時刻 t について、
  - その時刻に**画面へ出ている**出力 frame を選ぶ(k = floor(t * fps_out))
  - t が属する絵の区間 (D_a, D_b) と、真の tau = (t-t_a)/(t_b-t_a) を出す
  - lag = p95|| flow(D_a → 出力frame) - tau * flow(D_a → D_b) || * SCALE
そのまま時刻で平均します。frame 数ではなく**時間**で重み付けされるので、
出力 fps に依らない量になります。

GPU は使いません(Farneback は CPU、grays は smooth の cache から読む)。
"""
import concurrent.futures as cf
import os
import sys

import numpy as np

import lib
import smooth
import d9_metric as M

EXACT = {"元": lib.FPS, "x2素直": lib.FPS * 2, "x2絵": lib.FPS * 2,
         "60絵": 60.0, "120絵": 120.0,
         "72絵": lib.FPS * 3, "120整絵": lib.FPS * 5}
GRID_HZ = 250.0
CONDS = ("元", "x2素直", "x2絵", "60絵", "120絵", "72絵", "120整絵")

def shows_true_drawing(cond, k, a, b, runs_set):
    """出力 frame k が「素材の絵そのもの」を出しているか。

    画素では判定できない。出力は H.264 なので厳密一致にはならず、
    かといって閾値で見ると B_talk のような小変位素材では生成 frame まで
    「同じ」になってしまう(区間の変位が中央 1.8px しかない)。
    **schedule の幾何**で決める。これは厳密で、素材にも model にも依らない。

    元        … 出力 frame k = 素材 frame k。区間 [a,b) は同じ絵の保持なので常に真
    x2素直    … 偶数 k は素材 frame k/2(区間内なので D_a)。
                奇数 k は素材 (k-1)/2 と (k+1)/2 の中間だが、(k+1)/2 が絵の
                開始でなければ box4 関門で複製に落ちるので、これも D_a
    張り直し  … 出力時刻が絵の開始時刻に厳密に乗る時だけ D_a。
                47.952fps では k=2a、60/120fps では(先頭以外)起きない
    """
    if cond == "元":
        return True
    if cond == "x2素直":
        if k % 2 == 0:
            return True
        return ((k + 1) // 2) not in runs_set
    return abs(k / EXACT[cond] - a / lib.FPS) < 1e-6   # 1us。frame 間隔の 1/8000


def samples(clip, fps, n_out, t_max):
    """評価時刻ごとに (t, k, (a,b), tau)。手を出した区間だけ。"""
    gaps, spans = smooth.gap_spans(clip)
    span_of = {g: float(s) for g, s in zip(gaps, spans)}
    free = [(a, b) for (a, b) in gaps
            if (b - a) < M.STILL_HOLD and span_of[(a, b)] <= M.SPAN_LIMIT]
    out = []
    for (a, b) in free:
        ta, tb = a / lib.FPS, b / lib.FPS
        i0 = int(np.ceil(ta * GRID_HZ))
        i1 = int(np.ceil(tb * GRID_HZ))
        for i in range(i0, i1):
            t = i / GRID_HZ
            if t >= t_max:
                break
            k = int(t * fps)
            if k >= n_out:
                break
            out.append((t, k, (a, b), (t - ta) / (tb - ta)))
    return out, span_of


def measure(clip, cond, t_max):
    key, _, _ = M.find(clip, cond)
    fps = EXACT[cond]
    o = np.load(M.CACHE / f"scan_{key}.npz")
    og, n_out = o["grays"], int(o["n"])
    with lib.gpu_use("shindan"):
        s = smooth.scan(clip)
    sg = s["grays"]

    smp, span_of = samples(clip, fps, n_out, t_max)
    need_gap = sorted({ab for _, _, ab, _ in smp})
    need_pair = sorted({(ab[0], k) for _, k, ab, _ in smp})

    with cf.ThreadPoolExecutor(max_workers=os.cpu_count()) as ex:
        gf = dict(zip(need_gap, ex.map(
            lambda ab: smooth._flow(sg[ab[0]], sg[ab[1]]), need_gap)))
        of = dict(zip(need_pair, ex.map(
            lambda ak: smooth._flow(sg[ak[0]], og[ak[1]]), need_pair)))

    runs_set = set(int(x) for x in lib.drawing_runs(clip))
    lags = np.empty(len(smp), np.float32)
    is_copy = np.zeros(len(smp), bool)
    ref = np.empty(len(smp), np.float32)
    for i, (t, k, ab, tau) in enumerate(smp):
        d = of[(ab[0], k)] - tau * gf[ab]
        lags[i] = float(np.percentile(
            np.sqrt(d[..., 0] ** 2 + d[..., 1] ** 2), smooth.PIX_P)) * smooth.SCALE
        is_copy[i] = shows_true_drawing(cond, k, ab[0], ab[1], runs_set)
        ref[i] = span_of[ab]
    np.savez(M.CACHE / f"fair_{clip}_{cond}_{GRID_HZ:g}.npz",
             lags=lags, is_copy=is_copy, ref=ref,
             t=np.array([x[0] for x in smp], np.float64))
    return dict(clip=clip, cond=cond, fps=round(fps, 3), grid_hz=GRID_HZ,
                samples=len(smp),
                lag_time_px=round(float(lags.mean()), 2),
                lag_gen_px=round(float(lags[~is_copy].mean()), 2)
                if (~is_copy).any() else None,
                lag_copy_px=round(float(lags[is_copy].mean()), 2)
                if is_copy.any() else None,
                copy_pct=round(float(is_copy.mean()) * 100, 1),
                lag_rel=round(float(lags.sum() / ref.sum()), 3)), lags, is_copy, smp


def run(clip, conds=CONDS):
    t_max = min(int(np.load(M.CACHE / f"scan_{M.find(clip, c)[0]}.npz")["n"])
                / EXACT[c] for c in conds)
    t_max = min(t_max, len(lib.load(clip)) / lib.FPS)
    lib.log(f"{clip}: 評価時刻 0〜{t_max:.2f}s、{GRID_HZ:g}Hz")
    res, keep = [], {}
    for c in conds:
        r, lags, is_copy, smp = measure(clip, c, t_max)
        keep[c] = (lags, is_copy, smp)
        res.append(r)
        lib.record("fair", r)
        print(r, flush=True)

    # 両方が生成 frame を出している時刻だけで比べる(最も厳しい対照)
    for a, b in (("x2絵", "60絵"), ("60絵", "120絵"), ("x2素直", "x2絵"),
                 ("60絵", "72絵"), ("120絵", "120整絵"), ("72絵", "120整絵")):
        if a not in keep or b not in keep:
            continue
        la, ca, sa = keep[a]
        lb, cb, sb = keep[b]
        assert [x[0] for x in sa] == [x[0] for x in sb], "評価時刻がずれています"
        m = (~ca) & (~cb)
        if not m.any():
            continue
        r = dict(clip=clip, pair=f"{a} 対 {b}", samples=int(m.sum()),
                 both_gen_pct=round(float(m.mean()) * 100, 1),
                 lag_a=round(float(la[m].mean()), 2),
                 lag_b=round(float(lb[m].mean()), 2))
        lib.record("fair_pair", r)
        print(r, flush=True)
        res.append(r)
    return res


if __name__ == "__main__":
    for c in (sys.argv[1:] or list(lib.CLIPS)):
        run(c)
