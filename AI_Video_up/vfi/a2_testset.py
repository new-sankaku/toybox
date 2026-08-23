"""品質を測るための試験集合を作る。全modelがまったく同じ組を見る。

## 何を測るか

生成した中間frameには正解が無い。唯一の実測法は **1枚落として復元** で、
両端から中を作り、本物と比べる。

## 「frame」ではなく「絵」で組む

最初の版は連続する3 frame (i-1, i, i+1) で組んだが、anime では成立しなかった。
B_talk(本編の会話場面)で3 frameとも別の絵になる組は **718組中わずか8組**しか
無い。1枚の絵が3〜5 frame 保持されるので、frameで3枚取ると必ず同じ絵が混ざり、
hold(前のframeをそのまま)が自動的に満点を取ってmodelの巧拙が消える。

そこで **絵の列** で組む。box4 が閾値未満なら同じ絵と見なして run へ畳み、
連続する3つの絵 D0, D1, D2 の真ん中を、両端と実際の時間比 tau から作る。

    tau = (r1 - r0) / (r2 - r0)      r* は各絵の最初のframe番号

これは x2 補間が実際にやること(隣り合う絵の間を作る)と同じ問題で、しかも
**間隔が1段広い**ぶん本番より辛い。辛い側なので判断に使える。
A_op(OP、全編1コマ打ち)では run 長が1なので frame単位の試験と一致する。

## 除く物

- cut を跨ぐ組。cut は補間せず hold するのが正解で、modelの優劣と無関係
- 絵の間隔が広すぎる組 (r2 - r0 > MAX_SPAN)。1秒近く止まった後の絵は
  補間の対象ではなく、間を作ってはいけない
- 動きの大小で3層に分ける。平均1つだと、大変位で破綻するmodelと
  小変位で線が甘いmodelの区別が付かない
"""
import sys

import numpy as np

import vfilib as V

N_PER_CLIP = 120
MOVE_MIN = 16       # box4 がこれ未満なら「同じ絵」(vup の dedup balanced と同値)
MAX_SPAN = 8        # D0 から D2 までの frame 数の上限


def drawing_runs(a, scd):
    """絵の切り替わり位置。比較相手は run の先頭に固定する(vup の Dedup と同じ)。

    直前のframeと比べると、閾値未満の差が毎frame見逃されて累積し、
    「同じ絵」の判定が少しずつ緩くなる。
    """
    starts = [0]
    ref = a[0]
    for i in range(1, len(a)):
        if scd[i - 1] >= 10.0 or V.box4_max(ref, a[i]) >= MOVE_MIN:
            starts.append(i)
            ref = a[i]
    return np.array(starts)


def build(clip, n=N_PER_CLIP, seed=0):
    a = V.load(clip)
    cad = np.load(V.RESULTS / f"cadence_{clip}.npy")
    scd = np.load(V.RESULTS / f"scd_{clip}.npy")
    runs = drawing_runs(a, scd)
    V.log(f"{clip}: 絵 {len(runs)}枚 / frame {len(a)}枚 "
          f"(1枚あたり {len(a)/len(runs):.2f} frame)")

    cand = []
    for k in range(len(runs) - 2):
        r0, r1, r2 = int(runs[k]), int(runs[k + 1]), int(runs[k + 2])
        if r2 - r0 > MAX_SPAN:
            continue
        if (scd[r0:r2] >= 10.0).any():      # 間に cut がある
            continue
        mv = float(cad["mv_p95"][r0:r2].max())
        cand.append((r0, r1, r2, (r1 - r0) / (r2 - r0),
                     V.box4_max(a[r0], a[r2]), mv))

    if len(cand) < 8:
        raise RuntimeError(f"{clip}: 試験に使える組が {len(cand)} しかありません")
    cand = np.array(cand, dtype=[("r0", "i4"), ("r1", "i4"), ("r2", "i4"),
                                 ("tau", "f4"), ("box4", "i4"), ("mv", "f4")])

    q = np.quantile(cand["mv"], [1 / 3, 2 / 3])
    tier = np.digitize(cand["mv"], q)
    rng = np.random.default_rng(seed)
    picked = []
    for t in (0, 1, 2):
        idx = np.where(tier == t)[0]
        picked.extend(rng.choice(idx, min(len(idx), int(np.ceil(n / 3))),
                                 replace=False).tolist())
    picked = sorted(picked)[:n]
    sel = cand[picked]

    out = np.zeros(len(sel), dtype=[("r0", "i4"), ("r1", "i4"), ("r2", "i4"),
                                    ("tau", "f4"), ("box4", "i4"),
                                    ("mv", "f4"), ("tier", "i1")])
    for f in ("r0", "r1", "r2", "tau", "box4", "mv"):
        out[f] = sel[f]
    out["tier"] = tier[picked]
    np.save(V.RESULTS / f"testset_{clip}.npy", out)

    # 静止側(model を呼ばずに済む組)。速度の話の根拠になる
    n_static = sum(1 for i in range(len(a) - 1)
                   if V.box4_max(a[i], a[i + 1]) < MOVE_MIN)

    info = dict(clip=clip, frames=len(a), drawings=len(runs),
                frames_per_drawing=round(len(a) / len(runs), 2),
                candidates=len(cand), picked=len(out),
                move_min=MOVE_MIN, max_span=MAX_SPAN,
                span_median=int(np.median(sel["r2"] - sel["r0"])),
                tau_median=round(float(np.median(sel["tau"])), 3),
                tier_edges=[round(float(x), 2) for x in q],
                tier_counts=[int((out["tier"] == t).sum()) for t in (0, 1, 2)],
                mv_median=round(float(np.median(sel["mv"])), 2),
                mv_max=round(float(sel["mv"].max()), 2),
                static_pairs=n_static,
                static_pct=round(n_static / (len(a) - 1) * 100, 1),
                cut_pairs=int((scd >= 10.0).sum()))
    V.record("testset", info)
    for k, v in info.items():
        print(f"  {k}: {v}")
    return out


if __name__ == "__main__":
    for c in (sys.argv[1:] or list(V.CLIPS)):
        V.log(f"=== {c}")
        build(c)
