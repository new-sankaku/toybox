"""64px を超える組は「そもそも何なのか」。

speed 担当が flow の推定解像度を 1/4 まで落としても 64-128px 帯の品質が
まったく動かない事を示した(0.2427 → 0.2444)。「受容野が足りない」という
説明は棄却された。残る可能性は3つ:

  (a) model の性能不足        … 将来の model で直る
  (b) 素材に中間が存在しない  … どんな model でも当てられない
  (c) 絵の区切り方の誤り      … こちらの実装の問題

判定に要るのは「D1 が D0 と D2 の間に居るか」です。居るなら (a)、
居ないなら (b) か (c)。

## 測り方

D0→D1 の変位と D0→D2 の変位を比べます。被写体が t_0→t_2 を等速で動いたなら

    |flow(D0→D1)| / |flow(D0→D2)| ≒ tau

になるはずです。この比を **進行率** と呼びます。

  進行率 ≒ tau      … 中間として素直。model が当てられなければ (a)
  進行率 ≒ 0        … D1 は D0 のまま。変化は D1→D2 に在る
  進行率 ≒ 1        … D1 は既に D2。変化は D0→D1 に在る
  進行率 が tau と大きく違う … 等速でない(溜め・衝撃 frame・smear)

進行率は p95 の大きさの比ではなく、**D0→D2 の向きへの射影**で取ります。
大きさだけだと、別方向へ動いた場合も「進んだ」と読んでしまいます。

GPU は使いません(Farneback は CPU)。画像を作る側(sheet)だけ model を呼びます。
"""
import concurrent.futures as cf
import os
import sys

import cv2
import numpy as np

import lib
import smooth

BIN_LABELS = ["0-4", "4-8", "8-16", "16-32", "32-64", "64-128", "128-"]


def _g(a, i):
    return cv2.cvtColor(
        cv2.resize(np.array(a[i]), smooth.SMALL, interpolation=cv2.INTER_AREA),
        cv2.COLOR_BGR2GRAY)


def advance(g0, g1, g2):
    """進行率と、その信頼できる度合い。

    f02 = flow(D0→D2) の向きを軸に、f01 = flow(D0→D1) を射影する。
    大きく動いた画素ほど重みを持たせる(動いていない背景は分母が 0 になる)。
    """
    f01 = smooth._flow(g0, g1)
    f02 = smooth._flow(g0, g2)
    m02 = np.sqrt(f02[..., 0] ** 2 + f02[..., 1] ** 2)
    thr = np.percentile(m02, 90)
    sel = m02 >= max(thr, 1e-3)
    if not sel.any():
        return None, None, 0.0
    proj = (f01[..., 0] * f02[..., 0] + f01[..., 1] * f02[..., 1]) / (m02 ** 2 + 1e-9)
    r = float(np.median(proj[sel]))
    # D1→D2 側も同じ軸で見る。r + s ≒ 1 なら「D0→D1→D2 が一直線」
    f12 = smooth._flow(g1, g2)
    s = float(np.median(((f12[..., 0] * f02[..., 0] + f12[..., 1] * f02[..., 1])
                         / (m02 ** 2 + 1e-9))[sel]))
    return r, s, float(sel.mean())


def box4_max(a, b):
    d = np.abs(a.astype(np.float32) - b.astype(np.float32))
    h, w = d.shape[:2]
    d = d[:h // 4 * 4, :w // 4 * 4]
    d = d.reshape(h // 4, 4, w // 4, 4, -1) if d.ndim == 3 else \
        d.reshape(h // 4, 4, w // 4, 4, 1)
    return float(d.mean(axis=(1, 3)).round().max())


def analyze(clip):
    a = lib.load(clip)
    sel = np.load(lib.RESULTS / f"testset_{clip}.npy")
    gs = {}
    for r in sel:
        for i in (int(r["r0"]), int(r["r1"]), int(r["r2"])):
            if i not in gs:
                gs[i] = _g(a, i)

    def one(r):
        r0, r1, r2 = int(r["r0"]), int(r["r1"]), int(r["r2"])
        adv, back, cov = advance(gs[r0], gs[r1], gs[r2])
        return dict(clip=clip, r0=r0, r1=r1, r2=r2, tau=float(r["tau"]),
                    span=float(r["span"]), bin=int(r["bin"]),
                    adv=adv, back=back,
                    b01=box4_max(gs[r0], gs[r1]), b12=box4_max(gs[r1], gs[r2]),
                    b02=box4_max(gs[r0], gs[r2]))

    with cf.ThreadPoolExecutor(max_workers=os.cpu_count()) as ex:
        rows = list(ex.map(one, sel))
    return rows


def summarize(rows):
    out = []
    for b in range(len(BIN_LABELS)):
        r = [x for x in rows if x["bin"] == b and x["adv"] is not None]
        if not r:
            continue
        adv = np.array([x["adv"] for x in r])
        tau = np.array([x["tau"] for x in r])
        back = np.array([x["back"] for x in r])
        out.append(dict(
            clip=r[0]["clip"], bin=BIN_LABELS[b], n=len(r),
            tau_p50=round(float(np.median(tau)), 2),
            adv_p50=round(float(np.median(adv)), 3),
            adv_over_tau=round(float(np.median(adv / tau)), 2),
            straight_p50=round(float(np.median(adv + back)), 2),
            adv_lt_25pct=round(float((adv / tau < 0.25).mean()) * 100, 1),
            b01_p50=round(float(np.median([x["b01"] for x in r])), 0),
            b12_p50=round(float(np.median([x["b12"] for x in r])), 0)))
    return out


if __name__ == "__main__":
    for c in (sys.argv[1:] or ["A_op", "C_act", "B_talk"]):
        rows = analyze(c)
        for s in summarize(rows):
            lib.record("bigspan", s)
            print(s, flush=True)


# ---------------------------------------------------------------- 目で見る

TILE = (384, 216)


def sheet(clip, rows, dst, title, tile=TILE):
    """D0(=hold) / 真の D1 / model / blend / D2 を横に並べる。model は GPU。"""
    import torch
    import r_model

    a = lib.load(clip)
    m = r_model.Model()
    out = []
    for r in rows:
        r0, r1, r2, tau = r["r0"], r["r1"], r["r2"], r["tau"]
        D0, D1, D2 = (np.array(a[i]) for i in (r0, r1, r2))
        f0, f2 = m.to_gpu(D0), m.to_gpu(D2)
        mid = m.infer(f0, f2, tau).clone().cpu().numpy()
        bl = (D0.astype(np.float32) * (1 - tau)
              + D2.astype(np.float32) * tau).round().astype(np.uint8)
        cells = [(f"D0 = hold (f{r0})", D0), (f"TRUE D1 (f{r1})", D1),
                 (f"model tau={tau:.2f}", mid), ("blend", bl),
                 (f"D2 (f{r2})", D2)]
        row = []
        for name, img in cells:
            t = cv2.resize(img, tile, interpolation=cv2.INTER_AREA)
            cv2.rectangle(t, (0, 0), (tile[0] - 1, tile[1] - 1), (90, 200, 90), 2)
            for c, th in (((0, 0, 0), 4), ((255, 255, 255), 1)):
                cv2.putText(t, name, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, c, th)
            row.append(t)
        row = np.concatenate(row, axis=1)
        bar = np.zeros((26, row.shape[1], 3), np.uint8)
        cv2.putText(bar, f"span {r['span']:.0f}px  tau {tau:.2f}  advance "
                         f"{r['adv']:.3f} (expect {tau:.2f})  box4 D0-D1 {r['b01']:.0f} "
                         f"/ D1-D2 {r['b12']:.0f}",
                    (6, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (80, 220, 255), 1)
        out.append(np.concatenate([bar, row], axis=0))
        del f0, f2
    sheetimg = np.concatenate(
        [x for r in out for x in (r, np.zeros((6, out[0].shape[1], 3), np.uint8))][:-1],
        axis=0)
    top = np.zeros((30, sheetimg.shape[1], 3), np.uint8)
    cv2.putText(top, title, (6, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
    sheetimg = np.concatenate([top, sheetimg], axis=0)
    ok, enc = cv2.imencode(".png", sheetimg)
    if not ok:
        raise RuntimeError("png へ encode できません")
    dst.write_bytes(enc.tobytes())
    torch.cuda.empty_cache()
    return dst


def looks(clip, n=6):
    rows = [r for r in analyze(clip) if r["adv"] is not None]
    with lib.gpu_use("shindan"):
        for lo, hi, tag in ((128, 1e9, "128px超"), (64, 128, "64-128px")):
            sel = sorted([r for r in rows if lo <= r["span"] < hi],
                         key=lambda x: -x["span"])[:n]
            if not sel:
                continue
            p = lib.RESULTS / f"目視_{clip}_大変位_{tag}.png"
            sheet(clip, sel, p, f"{clip}  span {tag}  (advance = how far TRUE D1 "
                                f"moved toward D2, 0=stayed at D0, 1=already at D2)")
            lib.record("bigspan_look", dict(clip=clip, band=tag, out=str(p),
                                            pairs=[(r["r0"], r["r1"], r["r2"],
                                                    round(r["span"], 1),
                                                    round(r["adv"], 3)) for r in sel]))
            lib.log(f"  {p}")


def fb_consistency(g0, g2):
    """順方向と逆方向の flow が互いの逆になっているか(forward-backward check)。

    対応が存在しない場所(粒子・effect・cut)では、順逆が一致しない。
    「変位が大きい」のか「そもそも対応が無い」のかを分ける。
    戻り: (順方向の p95 変位px, fb 誤差の中央値px, fb 誤差/変位)
    """
    f = smooth._flow(g0, g2)
    b = smooth._flow(g2, g0)
    h, w = f.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    mx = np.clip(xx + f[..., 0], 0, w - 1)
    my = np.clip(yy + f[..., 1], 0, h - 1)
    bx = cv2.remap(b[..., 0], mx, my, cv2.INTER_LINEAR)
    by = cv2.remap(b[..., 1], mx, my, cv2.INTER_LINEAR)
    err = np.sqrt((f[..., 0] + bx) ** 2 + (f[..., 1] + by) ** 2)
    mag = np.sqrt(f[..., 0] ** 2 + f[..., 1] ** 2)
    thr = np.percentile(mag, 90)
    sel = mag >= max(thr, 1e-3)
    S = smooth.SCALE
    return (float(np.percentile(mag, 95)) * S,
            float(np.median(err[sel])) * S,
            float(np.median(err[sel] / (mag[sel] + 1e-6))))


# ------------------------------------------------- 非等速は「溜め」か「張り付き」か

def adv_series(clip, max_span=12):
    """cut を跨がない絵の3つ組を全部使って進行率を出す(標本抽出しない)。

    試験集合は層別に抜いてあるので、分布の形を見るには全数が要る。
    """
    a = lib.load(clip)
    runs = [int(x) for x in lib.drawing_runs(clip)]
    cuts = set(int(c) for c in lib.cut_frames(clip))
    gs, out = {}, []
    tri = []
    for k in range(len(runs) - 2):
        r0, r1, r2 = runs[k], runs[k + 1], runs[k + 2]
        if r2 - r0 > max_span or r1 in cuts or r2 in cuts:
            continue
        tri.append((k, r0, r1, r2))
        for i in (r0, r1, r2):
            if i not in gs:
                gs[i] = _g(a, i)

    def one(t):
        k, r0, r1, r2 = t
        adv, back, cov = advance(gs[r0], gs[r1], gs[r2])
        return dict(k=k, r0=r0, r1=r1, r2=r2,
                    tau=(r1 - r0) / (r2 - r0), adv=adv,
                    b01=box4_max(gs[r0], gs[r1]), b12=box4_max(gs[r1], gs[r2]))

    with cf.ThreadPoolExecutor(max_workers=os.cpu_count()) as ex:
        out = [r for r in ex.map(one, tri) if r["adv"] is not None]
    return out


def adv_shape(clip, rows=None):
    """進行率の分布の形と、隣り合う組との相関。

    溜め・詰め(ease)なら進行率は 0〜1 に散らばり、**隣の組と似る**はず
    (同じ動きの中なので)。端に張り付いているだけなら 0 と 1 の二極になり、
    隣とは無相関になる。**予測できるかどうかがここで決まる。**
    """
    rows = rows or adv_series(clip)
    adv = np.array([r["adv"] for r in rows])
    tau = np.array([r["tau"] for r in rows])
    d = adv - tau
    # 隣り合う3つ組(絵 index が1つ違い)の相関
    idx = {r["k"]: i for i, r in enumerate(rows)}
    pa, pb = [], []
    for r in rows:
        j = idx.get(r["k"] + 1)
        if j is not None:
            pa.append(d[idx[r["k"]]])
            pb.append(d[j])
    corr = float(np.corrcoef(pa, pb)[0, 1]) if len(pa) > 8 else None
    return dict(clip=clip, n=len(rows),
                adv_p50=round(float(np.median(adv)), 3),
                near0_pct=round(float((adv < 0.15).mean()) * 100, 1),
                near1_pct=round(float((adv > 0.85).mean()) * 100, 1),
                middle_pct=round(float(((adv >= 0.15) & (adv <= 0.85)).mean()) * 100, 1),
                dev_p50=round(float(np.median(np.abs(d))), 3),
                neighbor_corr=None if corr is None else round(corr, 3),
                neighbor_pairs=len(pa))


def adv_shape_trusted(clip, rows=None, fb_max=0.10):
    """flow が信用できる組だけで分布の形を見る。

    進行率が 0 や 1 に寄るのが「素材の timing」なのか「flow の失敗」なのかを
    分ける。fb 誤差が変位の fb_max 未満の組だけ残す。
    """
    a = lib.load(clip)
    rows = rows or adv_series(clip)
    gs = {}
    for r in rows:
        for i in (r["r0"], r["r2"]):
            if i not in gs:
                gs[i] = _g(a, i)
    with cf.ThreadPoolExecutor(max_workers=os.cpu_count()) as ex:
        fb = list(ex.map(lambda r: fb_consistency(gs[r["r0"]], gs[r["r2"]]), rows))
    keep = [r for r, f in zip(rows, fb) if f[2] < fb_max]
    out = adv_shape(clip, keep)
    out["fb_max"] = fb_max
    out["kept_pct"] = round(len(keep) / len(rows) * 100, 1)
    return out


def summarize_shape(rows):
    """帯ごとに進行率の**分布の形**を出す。

    中央値だけでは足りない。進行率は 0 と 1 の二極になる事があり、
    その場合の中央値は標本の入れ替わりで大きく動く(A_op の全数で 0.364、
    flow が信用できる組だけで 0.492)。**端に何%居るか**で見る。
    """
    out = []
    for b in range(len(BIN_LABELS)):
        r = [x for x in rows if x["bin"] == b and x["adv"] is not None]
        if not r:
            continue
        adv = np.array([x["adv"] for x in r])
        tau = np.array([x["tau"] for x in r])
        out.append(dict(
            clip=r[0]["clip"], bin=BIN_LABELS[b], n=len(r),
            adv_p50=round(float(np.median(adv)), 3),
            near0_pct=round(float((adv < 0.15).mean()) * 100, 1),
            near1_pct=round(float((adv > 0.85).mean()) * 100, 1),
            middle_pct=round(float(((adv >= 0.15) & (adv <= 0.85)).mean()) * 100, 1),
            dev_p50=round(float(np.median(np.abs(adv - tau))), 3)))
    return out


def classify(clip, bands=((0, 64, "64px以下"), (64, 128, "64-128px"), (128, 1e9, "128px超"))):
    """大変位の組を cut / 偽の分割 / 非等速 / 素直 に分ける。

    cut は `lib.cut_frames`(規約を揃えた後)をそのまま使う。
    """
    rows = [r for r in analyze(clip) if r["adv"] is not None]
    cuts = set(int(c) for c in lib.cut_frames(clip))
    out = []
    for lo, hi, tag in bands:
        s = [r for r in rows if lo <= r["span"] < hi]
        if not s:
            continue
        cut = [r for r in s if any(r["r0"] < c <= r["r2"] for c in cuts)]
        rest = [r for r in s if r not in cut]
        split = [r for r in rest if r["b01"] < 32 and r["b12"] > 3 * r["b01"]]
        rest2 = [r for r in rest if r not in split]
        bad = [r for r in rest2 if abs(r["adv"] - r["tau"]) > 0.25]
        ok = [r for r in rest2 if r not in bad]
        out.append(dict(clip=clip, band=tag, n=len(s), cut=len(cut), split=len(split),
                        nonlinear=len(bad), clean=len(ok),
                        clean_pct=round(len(ok) / len(s) * 100, 1)))
    return out
