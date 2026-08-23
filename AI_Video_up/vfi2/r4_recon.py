"""schedule ごと正解と突き合わせる。設計の選択肢はここで決める。

## 正解の作り方

時刻を張り直した出力には正解が無い。そこで **絵を1枚おきに間引いた素材**を
作る。絵 D_0, D_2, D_4, ... だけを残し、落とした絵の frame は直前の絵で
埋める(実際の限定animationで起きている事と同じ形)。

間引いた素材の絵の列に対して、**元の frame 時刻**へ張り直す。
出力 frame は元の frame と1対1に対応するので、全部に正解がある。

  - 残した絵に当たる出力  → copy で一致するはず(検算になる)
  - 落とした絵に当たる出力 → model が作る。ここが本当の試験

跨ぐ間隔が本番の2倍になるので、**本番より辛い側**の数字になる。
anchor・gate の閾値・均しの有無を、この1つの試験で横並びに比べる。
"""
import itertools
import sys

import numpy as np
import torch

import lib
import r1_cadence as R1
import r3_gate as R3
import r_model
import retime

HOLD_MAX = 8         # 絵の保持がこれを超えたら意図的な静止とみなす(frame)
MV_GATES = (32.0, 64.0, 1e9)


def thinned(clip):
    """1枚おきに間引いた絵の列と、その pair ごとの実測値。"""
    runs = lib.drawing_runs(clip)
    n = len(lib.load(clip))
    scd = lib.scdet(clip)
    smv = R3.span_mv(clip)              # smv[i] = D_i -> D_i+2 の flow p95
    keep = np.arange(0, len(runs), 2)
    tr = runs[keep]
    K = len(tr)
    gap = np.diff(np.append(tr, n))[:K - 1]
    cut = np.array([bool((scd[int(tr[j]):int(tr[j + 1])] >= lib.SCD_CUT).any())
                    for j in range(K - 1)])
    mv = np.array([float(smv[int(keep[j])]) if int(keep[j]) < len(smv) else 0.0
                   for j in range(K - 1)], dtype=np.float32)
    return keep, tr, gap, cut, mv


def block_mask(gap, cut, mv, mv_gate, hold_max=HOLD_MAX):
    return cut | (gap > hold_max) | (mv > mv_gate)


def source_frame(runs, keep, j):
    """間引いた素材で絵 j を表す元 frame 番号。"""
    return int(runs[keep[j]])


def evaluate(clip, anchor, mv_gate, even, model_name=r_model.DEFAULT, M=None):
    key = (clip, model_name, anchor, mv_gate, even)
    done = lib.done_keys("recon", ("clip", "model", "anchor", "mv_gate", "even"))
    if key in done:
        return None
    a = lib.load(clip)
    n = len(a)
    runs = lib.drawing_runs(clip)
    keep, tr, gap, cut, mv = thinned(clip)
    blk = block_mask(gap, cut, mv, mv_gate)
    sch = retime.build(tr, n, lib.FPS, lib.FPS, anchor=anchor, block=blk,
                       even=even, cut_frames=lib.cut_frames(clip), n_out=n)

    own = r_model.Model(model_name) if M is None else M
    rows = []
    for j, st in enumerate(sch):
        k = int(st["k"])
        kind = int(st["kind"])
        gt = own.to_gpu(np.array(a[j]))
        if kind == retime.MODEL:
            f0 = own.to_gpu(np.array(a[source_frame(runs, keep, k)]))
            f1 = own.to_gpu(np.array(a[source_frame(runs, keep, k + 1)]))
            y = own.infer(f0, f1, float(st["tau"]))
        else:
            y = own.to_gpu(np.array(a[source_frame(runs, keep, k)]))
        rows.append((j, kind, lib.lpips_score(y, gt), lib.gmsd(y, gt)))
        del gt, y

    arr = np.array(rows, dtype=[("j", "i4"), ("kind", "i1"),
                                ("lpips", "f8"), ("gmsd", "f8")])
    np.save(lib.RESULTS /
            f"recon_{clip}_{anchor}_{int(min(mv_gate,999))}_{int(even)}.npy", arr)

    # 落とした絵に当たる出力(本当の試験)。残した絵の出力は copy で 0 になる
    survive = set()
    for j in range(len(keep)):
        s = source_frame(runs, keep, j)
        e = int(runs[keep[j] + 1]) if keep[j] + 1 < len(runs) else n
        survive.update(range(s, e))
    dropped = np.array([j not in survive for j in arr["j"]])

    st = retime.stats(sch, n / lib.FPS)
    info = dict(clip=clip, model=model_name, anchor=anchor,
                mv_gate=(None if mv_gate > 1e8 else mv_gate), even=bool(even),
                hold_max=HOLD_MAX,
                n_out=len(arr), n_dropped=int(dropped.sum()),
                calls=st["calls"], hold=st["hold"], copy=st["copy"],
                block_pairs=int(blk.sum()), n_pairs=len(blk),
                block_pct=round(float(blk.mean()) * 100, 1),
                lpips_all=round(float(arr["lpips"].mean()), 5),
                gmsd_all=round(float(arr["gmsd"].mean()), 5),
                lpips_dropped=round(float(arr["lpips"][dropped].mean()), 5),
                gmsd_dropped=round(float(arr["gmsd"][dropped].mean()), 5),
                lpips_p95=round(float(np.percentile(arr["lpips"], 95)), 5),
                lpips_kept=round(float(arr["lpips"][~dropped].mean()), 6))
    lib.record("recon", info)
    if M is None:
        del own
        torch.cuda.empty_cache()
    return info


def baseline(clip, model_name=r_model.DEFAULT):
    """間引いた素材を何もせず流した時(= 補間なし)の同じ数字。"""
    if (clip, "none") in lib.done_keys("recon_base", ("clip", "kind2")):
        return
    a = lib.load(clip)
    n = len(a)
    runs = lib.drawing_runs(clip)
    keep, tr, gap, cut, mv = thinned(clip)
    sch = retime.build(tr, n, lib.FPS, lib.FPS, anchor="head",
                       block=np.ones(len(gap), bool), n_out=n)
    rows = []
    for j, st in enumerate(sch):
        gt = np.array(a[j])
        y = np.array(a[source_frame(runs, keep, int(st["k"]))])
        rows.append((lib.lpips_score(y, gt), lib.gmsd(y, gt)))
    arr = np.array(rows)
    survive = set()
    for jj in range(len(keep)):
        s = source_frame(runs, keep, jj)
        e = int(runs[keep[jj] + 1]) if keep[jj] + 1 < len(runs) else n
        survive.update(range(s, e))
    dropped = np.array([j not in survive for j in range(n)])
    lib.record("recon_base", dict(
        clip=clip, kind2="none", n_out=n, n_dropped=int(dropped.sum()),
        lpips_all=round(float(arr[:, 0].mean()), 5),
        gmsd_all=round(float(arr[:, 1].mean()), 5),
        lpips_dropped=round(float(arr[dropped, 0].mean()), 5),
        gmsd_dropped=round(float(arr[dropped, 1].mean()), 5)))


def run(clip, model_name=r_model.DEFAULT):
    baseline(clip, model_name)
    M = r_model.Model(model_name)
    for anchor, mv_gate, even in itertools.product(
            ("head", "center"), MV_GATES, (False, True)):
        info = evaluate(clip, anchor, mv_gate, even, model_name, M)
        if info is None:
            continue
        lib.log(f"  {clip} anchor={anchor} mv_gate={mv_gate:g} even={int(even)}: "
                f"落とした絵 LPIPS {info['lpips_dropped']:.5f} / "
                f"全体 {info['lpips_all']:.5f} / "
                f"呼び出し {info['calls']} / 封じた pair {info['block_pct']}%")
    del M
    torch.cuda.empty_cache()


if __name__ == "__main__":
    for c in (sys.argv[1:] or list(lib.CLIPS)):
        lib.log(f"=== 復元試験 {c}")
        run(c)
