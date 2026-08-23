"""「滑らかさ」を測る。チーム共通の判定軸。

## 何を滑らかさとみなすか

anime の絵は等間隔には並んでいない。1枚の絵が k frame 保持され、次の絵へ
飛ぶ。人が「カクつく」と言うのは、**絵が動くべき時刻に動いていない**状態で、
これは frame 数ではなく「時間あたりの位置のずれ」で測るのが正しい。

作画された絵 D_a(時刻 t_a)と D_b(時刻 t_b)の間では、被写体は t_a→t_b を
かけて連続に動いた、と読む(この読みは本project全体の前提でもある)。
すると時刻 t に画面へ出ているべき絵は tau=(t-t_a)/(t_b-t_a) の中間絵であり、
実際に出ている絵との差が **そのまま位置の誤差(px)** になる。

  lag_px  … 出力 frame ごとに
              || flow(D_a -> 出力frame) - tau * flow(D_a -> D_b) || の画素p95
            を測り、全出力frameで平均した値。**主指標。0 が完璧**
  step_px … 隣接する出力 frame 間の変位 p95。1枚あたりの跳び幅。
            lag が同じでも step が大きいと 24fps 特有のストロボ感が出る。**副指標**

tau は frame の**表示区間の中央**で採る(PHASE)。先頭で採ると、標本の少ない
低 fps ほど誤差が過小に出て、24fps 1コマ打ちの素材が lag=0 になってしまう。

検算(d8_selftest.py): 実際の絵を 4〜64px 平行移動させると、span はどの
percentile でもその値ちょうどを返す。保持の lag は r*span に厳密に一致する。
ただし**正しい位置に置いても lag は span の 16% までしか下がらない**
(Farneback の局所誤差)。これがこの指標の下限で、これ以下の差は読めない。

lag_px は保持(絵が動かない時間)に比例し、**frame rate を上げただけでは減らない**。
step_px は frame rate に反比例して減る。素直な x2 が効かないのはこの非対称が
理由で、2つを分けて出さないと「効いた/効かない」が判定できない。

hold_ms / new_rate / disp_cv は診断用の補助。cut を跨ぐ区間は全指標から外す
(cut は補間しないので、含めると「絵が変わった」だけで指標が動いてしまう)。

## 使い方

    import smooth
    r = smooth.measure("out/B_talk_x2.mkv", "B_talk")   # 出力を測る
    r = smooth.measure("B_talk", "B_talk")              # 素材そのものを測る
    print(r["lag_px"], r["step_px"])

    gaps, spans = smooth.gap_spans("B_talk")   # 隣接する絵の間の変位(px)

戻り値は dict。key は measure() の docstring を参照。
"""
import concurrent.futures as cf
import hashlib
import json
import os
import subprocess
import threading
from pathlib import Path

import cv2
import numpy as np

import lib

SMALL = (480, 270)          # 変位はここで測る(1920/480 = 4 の整数分の1縮小)
SCALE = lib.W / SMALL[0]    # 測った変位を原寸 px へ戻す倍率
PIX_P = 95                  # 画素方向の集約。動く部分は画面の一部なので上側を見る
PHASE = 0.5                 # 誤差を測る時刻。frame は表示区間を持つので中央で測る
                            # (先頭で測ると、標本の少ない低fpsほど誤差が過小に出る。
                            #  24fps 1コマ打ちの素材が lag=0 になってしまった)

CACHE = lib.RESULTS / "smooth"
CACHE.mkdir(exist_ok=True)


class _TL(threading.local):
    @property
    def flow(self):
        f = getattr(self, "_f", None)
        if f is None:
            f = cv2.FarnebackOpticalFlow_create(
                numLevels=5, pyrScale=0.5, winSize=25, numIters=3,
                polyN=5, polySigma=1.2)
            self._f = f
        return f


_TLS = _TL()


# ---------------------------------------------------------------- 入力

def probe(path):
    o = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,r_frame_rate", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True).stdout.strip().split(",")
    num, den = (int(x) for x in o[2].split("/"))
    return int(o[0]), int(o[1]), num / den


def _decode(path, w, h):
    """全frameを BGR24 で流す。yield する配列は使い回すので、受け側で写すこと。"""
    p = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(path), "-fps_mode", "passthrough",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
        # bufsize は渡さない(1080p の pipe 読みが 7.1倍遅くなる)
        stdout=subprocess.PIPE)
    buf = np.empty((h, w, 3), np.uint8)
    mv = memoryview(buf.reshape(-1))
    while True:
        got = p.stdout.readinto(mv)
        if not got or got < w * h * 3:
            break
        yield buf
    p.stdout.close()
    p.wait()


def _sig(path):
    st = Path(path).stat()
    return hashlib.sha1(f"{path}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()[:16]


def scan(video, move_min=lib.MOVE_MIN):
    """1回の走査で「縮小gray列」と「絵の切り替わり位置」を得る。

    video は file path か、lib.CLIPS の clip 名(素材そのものを測る場合)。
    戻り: dict(grays=(n,270,480) uint8, starts=絵の開始frame番号, n, w, h, fps)
    """
    if isinstance(video, dict):
        return video
    if str(video) in lib.CLIPS:
        clip = str(video)
        src = lib.load(clip)                     # memmap のまま1枚ずつ渡す
        return scan_frames((src[i] for i in range(len(src))),
                           f"clip_{clip}_{move_min}", lib.W, lib.H, lib.FPS,
                           move_min)
    w, h, fps = probe(video)
    return scan_frames(_decode(video, w, h),
                       f"{Path(video).stem}_{_sig(video)}_{move_min}",
                       w, h, fps, move_min)


def scan_frames(frames, key, w, h, fps, move_min=lib.MOVE_MIN):
    """frame の列(BGR24 uint8)を走査する。生成した frame をその場で測る用。

    key は cache 名。中身が変わったら key も変えること。
    """
    import torch
    import torch.nn.functional as F
    import gpumetric as GM

    cp = CACHE / f"scan_{key}.npz"
    if cp.exists():
        z = np.load(cp)
        return dict(grays=z["grays"], starts=z["starts"], n=int(z["n"]),
                    w=int(z["w"]), h=int(z["h"]), fps=float(z["fps"]), key=key)

    k = w // SMALL[0]
    if w % SMALL[0] or h % SMALL[1] or k != h // SMALL[1]:
        raise ValueError(f"{key}: {w}x{h} は {SMALL} の整数倍ではありません")
    wt = torch.tensor([0.114, 0.587, 0.299], device="cuda").view(1, 3, 1, 1)
    grays, starts = [], []
    ref = None
    for i, f in enumerate(frames):
        t = GM.to_gpu(f).permute(2, 0, 1).unsqueeze(0).float()
        g = F.avg_pool2d(t, k).round_()          # cv2 の INTER_AREA と同値
        g = (g * wt).sum(1).round_().clamp_(0, 255).to(torch.uint8)
        grays.append(g[0].cpu().numpy())
        cur = t[0].permute(1, 2, 0).to(torch.uint8)
        if ref is None or GM.box4_max(ref, cur) >= move_min:
            starts.append(i)
            ref = cur.clone()
    grays = np.stack(grays)
    starts = np.array(starts, dtype=np.int32)
    n = len(grays)
    np.savez(cp, grays=grays, starts=starts, n=n, w=w, h=h, fps=fps)
    return dict(grays=grays, starts=starts, n=n, w=w, h=h, fps=fps, key=key)


# ---------------------------------------------------------------- 変位

def _flow(g0, g1):
    return _TLS.flow.calc(g0, g1, None)


def _mag_p95(f):
    return float(np.percentile(np.sqrt(f[..., 0] ** 2 + f[..., 1] ** 2), PIX_P)) * SCALE


def displacements(grays, pairs=None):
    """隣接(または指定した組)の変位 p95 を px で返す。"""
    if pairs is None:
        pairs = [(i, i + 1) for i in range(len(grays) - 1)]
    with cf.ThreadPoolExecutor(max_workers=os.cpu_count()) as ex:
        return np.array(list(ex.map(
            lambda ij: _mag_p95(_flow(grays[ij[0]], grays[ij[1]])), pairs)),
            dtype=np.float32)


def gaps_of(clip):
    """cut を跨がない「絵と絵の組」。(a, b) は素材の frame 番号。"""
    runs = lib.drawing_runs(clip)
    cuts = set(int(c) for c in lib.cut_frames(clip))
    return [(int(runs[i]), int(runs[i + 1])) for i in range(len(runs) - 1)
            if int(runs[i + 1]) not in cuts]


def gap_spans(clip):
    """隣接する絵の間の変位(px)。model が実際に跨ぐ量そのもの。"""
    cp = CACHE / f"span_{clip}.npz"
    if cp.exists():
        z = np.load(cp)
        return [tuple(x) for x in z["gaps"]], z["spans"]
    g = scan(clip)
    gaps = gaps_of(clip)
    spans = displacements(g["grays"], gaps)
    np.savez(cp, gaps=np.array(gaps, dtype=np.int32), spans=spans)
    return gaps, spans


# ---------------------------------------------------------------- 主指標

def _lag_one(g0, gx, gap_flow, r):
    """出力1枚ぶんの位置ずれ(px)。gx が g0 と同一なら flow は 0。"""
    if gx is None:
        f = np.zeros_like(gap_flow)
    else:
        f = _flow(g0, gx)
    d = f - r * gap_flow
    return float(np.percentile(np.sqrt(d[..., 0] ** 2 + d[..., 1] ** 2), PIX_P)) * SCALE


def measure(video, src_clip, fps_out=None, move_min=lib.MOVE_MIN, tag=None,
            record=True):
    """滑らかさを測る。

    video    出力 file、lib.CLIPS の clip 名(素材そのものを測る)、または
             scan_frames() が返した dict(生成した frame をその場で測る)
    src_clip 元素材の clip 名。絵の切り替わり時刻と cut の位置をここから採る
    fps_out  出力の frame rate。省略時は file から読む(clip 名なら素材のfps)

    戻り値(すべて lower is better ではない物には単位を付けてある):
      lag_px      位置ずれの平均(px)。**主指標**
      lag_p95_px  同 p95
      lag_rel     lag_px / 区間の変位。0.5 が「まったく動いていない」目安
      step_px     隣接出力frame間の変位の中央値(px)
      step_p95_px 同 p95
      step_cv     step のばらつき(変動係数)。保持->跳躍の型ほど大きい
      drawings    出力に現れた異なる絵の枚数 / drawing_rate 毎秒
      hold_ms_p50 / hold_ms_p95   1枚が画面に留まる時間
      new_pct     直前と異なる絵である出力frameの割合(%)
      frames / fps / dur_s / covered  (covered = 指標に使えた出力frame数)
    """
    o = scan(video, move_min)
    s = scan(src_clip, move_min)
    fps = fps_out or o["fps"]
    gaps, spans = gap_spans(src_clip)

    lp = CACHE / f"lag_{o['key']}_{src_clip}_{fps:.3f}_ph{PHASE:g}.npz"
    if lp.exists():
        z = np.load(lp)
        lags, ref_span, steps = z["lags"], z["ref_span"], z["steps"]
        n_cov = len(lags)
    else:
        lags, ref_span, steps = _lag_step(o, s, src_clip, gaps, spans, fps)
        np.savez(lp, lags=lags, ref_span=ref_span, steps=steps)
        n_cov = len(lags)

    starts = o["starts"]
    holds = np.diff(np.append(starts, o["n"])) / fps * 1000.0
    dur = o["n"] / fps
    r = dict(
        video="(frames)" if isinstance(video, dict) else str(video),
        src=src_clip, tag=tag or ("(frames)" if isinstance(video, dict) else str(video)),
        frames=o["n"], fps=round(fps, 3), dur_s=round(dur, 2),
        covered=n_cov,
        lag_px=round(float(lags.mean()), 2),
        lag_p95_px=round(float(np.percentile(lags, 95)), 2),
        lag_rel=round(float(lags.sum() / max(ref_span.sum(), 1e-6)), 3),
        step_px=round(float(np.median(steps)), 2),
        step_p95_px=round(float(np.percentile(steps, 95)), 2),
        step_cv=round(float(steps.std() / max(steps.mean(), 1e-6)), 2),
        drawings=int(len(starts)),
        drawing_rate=round(len(starts) / dur, 1),
        hold_ms_p50=round(float(np.percentile(holds, 50)), 1),
        hold_ms_p95=round(float(np.percentile(holds, 95)), 1),
        new_pct=round(len(starts) / o["n"] * 100, 1),
    )
    if record:
        lib.record("smooth", r)
    return r


def _lag_step(o, s, src_clip, gaps, spans, fps):
    # 出力 frame の時刻を素材の「絵と絵の区間」へ割り当てる
    gap_flow = {}
    with cf.ThreadPoolExecutor(max_workers=os.cpu_count()) as ex:
        for (a, b), f in zip(gaps, ex.map(
                lambda ab: _flow(s["grays"][ab[0]], s["grays"][ab[1]]), gaps)):
            gap_flow[(a, b)] = f

    jobs = []
    for k in range(o["n"]):
        t = (k + PHASE) / fps          # その frame が映っている区間の中央
        for (a, b) in gaps:
            ta, tb = a / lib.FPS, b / lib.FPS
            if ta <= t < tb:
                jobs.append((k, (a, b), (t - ta) / (tb - ta)))
                break

    def lag_job(j):
        k, ab, r = j
        gx = o["grays"][k]
        g0 = s["grays"][ab[0]]
        same = np.array_equal(gx, g0)
        return _lag_one(g0, None if same else gx, gap_flow[ab], r)

    with cf.ThreadPoolExecutor(max_workers=os.cpu_count()) as ex:
        lags = np.array(list(ex.map(lag_job, jobs)), dtype=np.float32)
    span_of = {ab: sp for ab, sp in zip(gaps, spans)}
    ref_span = np.array([span_of[j[1]] for j in jobs], dtype=np.float32)

    # step は cut を跨ぐ組を外す。cut は素材の frame 番号なので時刻で写す
    cut_t = [c / lib.FPS for c in lib.cut_frames(src_clip)]
    pairs = [(k, k + 1) for k in range(o["n"] - 1)
             if not any(k / fps < ct <= (k + 1) / fps for ct in cut_t)]
    steps = displacements(o["grays"], pairs)
    return lags, ref_span, steps

if __name__ == "__main__":
    import sys
    for c in (sys.argv[1:] or list(lib.CLIPS)):
        r = measure(c, c)
        print(json.dumps(r, ensure_ascii=False, indent=1))
