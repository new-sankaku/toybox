"""仮説「中間絵の位置誤差 ≒ |進行率 - tau| × 跨ぐ変位」を検証する。

7章で「anime の動きは等速でない」事が判りました。model は tau の位置を作り、
真の絵は別の位置に居ます。**その差が px でどれだけになるか**が品質を決める、
という仮説です。決めるなら次が同時に説明されます。

  - A_op の 8-16px は半分が非等速なのに model が勝つ … ずれ×変位 が小さい
  - A_op の 128px超は破綻する                        … ずれ×変位 が大きい
  - B_talk は 32-64px でも model が良い              … 非等速が少ない
  - flow の解像度を下げても効かない                   … 追跡精度は timing を直さない

## 測り方

試験集合の組ごとに、v4.6 で tau の中間絵を作り、真の D1 との LPIPS を測ります。
比較用に blend と hold も測ります。そのうえで

    X1 = 跨ぐ変位(span)            … 大きさだけ
    X2 = |進行率 - tau|            … timing のずれだけ
    X3 = X2 × X1                   … 仮説の量(位置誤差 px)

と LPIPS の **Spearman(順位)相関**を取り、**X3 が X1・X2 の単独より強いか**を見ます。

**帯の中だけの相関も出します。**試験集合は変位で層別に抜いてあるので、
全体の相関は「変位が大きい組を多めに含む標本」の上の値です。帯を固定すれば
変位はほぼ一定になるので、そこで X2 が効いていれば **変位とは独立に
timing が効いている**事になります。

GPU を使います(model と LPIPS)。時間は測らないので共有で確保します。
"""
import sys

import numpy as np
from scipy import stats

import lib
import d14_bigspan as D

MODEL = "v4.6"


def per_pair(clip):
    """組ごとに (span, tau, 進行率, LPIPS の model / blend / hold)。"""
    import r_model
    a = lib.load(clip)
    rows = [r for r in D.analyze(clip) if r["adv"] is not None]
    m = r_model.Model(MODEL)
    out = []
    for r in rows:
        r0, r1, r2, tau = r["r0"], r["r1"], r["r2"], r["tau"]
        D0, D1, D2 = (np.array(a[i]) for i in (r0, r1, r2))
        f0, f2 = m.to_gpu(D0), m.to_gpu(D2)
        mid = m.infer(f0, f2, tau).clone()
        bl = (D0.astype(np.float32) * (1 - tau)
              + D2.astype(np.float32) * tau).round().astype(np.uint8)
        out.append(dict(
            clip=clip, r0=r0, r1=r1, r2=r2, tau=tau, span=r["span"],
            bin=r["bin"], adv=r["adv"], dev=abs(r["adv"] - tau),
            prod=abs(r["adv"] - tau) * r["span"],
            lp_model=float(lib.lpips_score(mid, m.to_gpu(D1))),
            lp_blend=float(lib.lpips_score(bl, D1)),
            lp_hold=float(lib.lpips_score(D0, D1))))
        del f0, f2, mid
    return out


def spear(x, y):
    if len(x) < 6:
        return None, None
    r, p = stats.spearmanr(x, y)
    return (None, None) if np.isnan(r) else (round(float(r), 3), round(float(p), 4))


def correlate(rows, label):
    x1 = np.array([r["span"] for r in rows])
    x2 = np.array([r["dev"] for r in rows])
    x3 = np.array([r["prod"] for r in rows])
    ym = np.array([r["lp_model"] for r in rows])
    yd = ym - np.array([r["lp_blend"] for r in rows])
    o = dict(label=label, n=len(rows))
    for nm, x in (("span", x1), ("dev", x2), ("prod", x3)):
        o[f"model_{nm}"], o[f"model_{nm}_p"] = spear(x, ym)
        o[f"vsblend_{nm}"], o[f"vsblend_{nm}_p"] = spear(x, yd)
    return o


def run(clip):
    with lib.gpu_use("shindan"):
        rows = per_pair(clip)
    np.save(lib.RESULTS / f"easing_{clip}.npy",
            np.array([(r["r0"], r["r1"], r["r2"], r["tau"], r["span"], r["bin"],
                       r["adv"], r["dev"], r["prod"], r["lp_model"], r["lp_blend"],
                       r["lp_hold"]) for r in rows],
                     dtype=[("r0", "i4"), ("r1", "i4"), ("r2", "i4"), ("tau", "f4"),
                            ("span", "f4"), ("bin", "i1"), ("adv", "f4"),
                            ("dev", "f4"), ("prod", "f4"), ("lp_model", "f8"),
                            ("lp_blend", "f8"), ("lp_hold", "f8")]))
    res = [correlate(rows, f"{clip}/全帯")]
    for b in range(len(D.BIN_LABELS)):
        s = [r for r in rows if r["bin"] == b]
        if len(s) >= 8:
            res.append(correlate(s, f"{clip}/{D.BIN_LABELS[b]}"))
    for r in res:
        lib.record("easing_corr", r)
        print(r, flush=True)
    return rows, res


if __name__ == "__main__":
    allrows = []
    for c in (sys.argv[1:] or ["B_talk", "C_act", "A_op"]):
        rows, _ = run(c)
        allrows += rows
    if len(allrows) > 100:
        r = correlate(allrows, "3本まとめ")
        lib.record("easing_corr", r)
        print(r, flush=True)
