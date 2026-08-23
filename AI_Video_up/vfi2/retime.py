"""絵の列へ時刻を張り直した出力 schedule を組む。

frame の列ではなく「絵」の列を時間軸に置き、目標 fps の各出力時刻 T を
それを挟む2枚の絵 D_k, D_k+1 から作る。素直な x2 との違いはここだけで、
素直な x2 は「同じ絵と同じ絵の間」にも1枚作ってしまうため、出力 frame は
増えても1秒あたりの異なる絵の枚数が増えない。

この file は **model に依存しない純粋な計算**。`python retime.py` で自己検査。
"""
import numpy as np

COPY, MODEL, HOLD = 0, 1, 2
KIND_NAME = {COPY: "copy", MODEL: "model", HOLD: "hold"}

STEP = np.dtype([("t", "f8"), ("k", "i4"), ("tau", "f8"), ("kind", "i1")])

EPS = 1e-6


def lengths(runs, n_frames):
    """絵 D_k が保持される frame 数。"""
    runs = np.asarray(runs, dtype=np.int64)
    if runs[0] != 0:
        raise ValueError("runs は frame 0 から始まる必要があります")
    ends = np.append(runs[1:], n_frames)
    L = ends - runs
    if (L <= 0).any():
        raise ValueError("絵の保持長が 0 以下です")
    return L


def anchors(runs, n_frames, anchor="head"):
    """絵の代表時刻(frame 単位)。

    head   run の先頭。2コマ打ちを「等速の運動を2 frame ずつ表示した物」と
           みなす立場。撮影が絵の切り替わり時刻をそのまま表示時刻にしている
           ならこれが正しい
    center run の中央。保持区間の重心を代表とみなす立場。コマ打ちが一定なら
           head と完全に同じ tau になり、混在する所でだけ差が出る
    """
    runs = np.asarray(runs, dtype=np.int64)
    if anchor == "head":
        return runs.astype(np.float64)
    if anchor == "center":
        return runs + (lengths(runs, n_frames) - 1) / 2.0
    raise ValueError(f"anchor が不明です: {anchor}")


def shot_bounds(runs, cut_frames):
    """cut で区切った絵 index の区間 [s, e) の列。"""
    runs = np.asarray(runs, dtype=np.int64)
    cutset = set(int(c) for c in np.asarray(cut_frames, dtype=np.int64).ravel())
    b = [0] + [k for k in range(1, len(runs)) if int(runs[k]) in cutset] + [len(runs)]
    return list(zip(b[:-1], b[1:]))


def even_anchors(a, runs, cut_frames):
    """cut で区切った shot ごとに代表時刻を等間隔へ均す。

    shot の両端の時刻は動かさない。shot の尺と cut の位置は保たれるが、
    shot の中の「溜め」(長い保持)は潰れる。
    """
    a = np.asarray(a, dtype=np.float64).copy()
    for s, e in shot_bounds(runs, cut_frames):
        if e - s >= 3:
            a[s:e] = np.linspace(a[s], a[e - 1], e - s)
    return a


def loo_tau(runs, n_frames, anchor="head"):
    """絵 D_k を D_k-1 と D_k+1 から作り直す時の tau(1枚落として復元の試験)。

    代表時刻の置き方が実際に効くのはここ。コマ打ちが一定なら head も center も
    0.5 になり、混在する所でだけ両者が割れる。
    """
    a = anchors(runs, n_frames, anchor)
    return (a[1:-1] - a[:-2]) / (a[2:] - a[:-2])


def build(runs, n_frames, fps_in, fps_out, *, anchor="head", block=None,
          even=False, cut_frames=(), n_out=None):
    """出力時刻ごとに (絵 k, tau, 種別) を決める。

    block  長さ len(runs)-1 の bool。pair k -> k+1 を補間してはいけない所。
           cut・意図的な静止・大変位の判定は呼び出し側で作って渡す
           (この file を model にも素材にも依存させないため)
    even   コマ打ちを shot 内で等間隔へ均す
    """
    runs = np.asarray(runs, dtype=np.int64)
    K = len(runs)
    a = anchors(runs, n_frames, anchor)
    if even:
        a = even_anchors(a, runs, cut_frames)
    t = a / float(fps_in)

    if block is None:
        block = np.zeros(max(K - 1, 0), dtype=bool)
    block = np.asarray(block, dtype=bool)
    if len(block) != K - 1:
        raise ValueError(f"block の長さが違います: {len(block)} != {K-1}")

    if n_out is None:
        n_out = int(round(n_frames / float(fps_in) * float(fps_out)))
    T = np.arange(n_out, dtype=np.float64) / float(fps_out)

    idx = np.clip(np.searchsorted(t, T, side="right") - 1, 0, K - 1)

    out = np.zeros(n_out, dtype=STEP)
    for j in range(n_out):
        k = int(idx[j])
        if k >= K - 1:
            out[j] = (T[j], K - 1, 0.0, COPY)
            continue
        gap = t[k + 1] - t[k]
        tau = (T[j] - t[k]) / gap
        if tau <= EPS:
            out[j] = (T[j], k, 0.0, COPY)
        elif tau >= 1.0 - EPS:
            out[j] = (T[j], k + 1, 0.0, COPY)
        elif block[k]:
            out[j] = (T[j], k, tau, HOLD)
        else:
            out[j] = (T[j], k, tau, MODEL)
    return out


def naive_x2(n_frames, fps_in, same_pair=None):
    """比較対象の「素直な x2」を同じ schedule 表現で書いた物。

    絵ではなく frame の列に対して、隣り合う frame の間へ tau=0.5 を1枚。
    same_pair[i] が True(frame i と i+1 が同じ絵)なら model を呼ばず複製する。
    絵 index の代わりに frame index をそのまま k に入れる。
    """
    if same_pair is None:
        same_pair = np.zeros(n_frames - 1, dtype=bool)
    same_pair = np.asarray(same_pair, dtype=bool)
    n_out = 2 * n_frames - 1
    out = np.zeros(n_out, dtype=STEP)
    for i in range(n_frames):
        out[2 * i] = (2 * i / (2.0 * fps_in), i, 0.0, COPY)
        if i < n_frames - 1:
            kind = HOLD if same_pair[i] else MODEL
            out[2 * i + 1] = ((2 * i + 1) / (2.0 * fps_in), i, 0.5, kind)
    return out


# ---------------------------------------------------------------- 集計

def emitted_id(step, ident):
    """出力 frame の「絵としての身元」。複製の判定に使う。

    copy/hold は元の絵そのもの。model は tau ごとに別の絵になる。
    ident は k を「絵の身元」へ写す。素直な x2 の k は frame 番号なので、
    ここを通さないと同じ絵を保持しているだけの frame まで別物に数えてしまう。
    """
    k = ident(int(step["k"]))
    if step["kind"] == MODEL:
        return ("m", k, round(float(step["tau"]), 6))
    return ("s", k)


def stats(sched, duration_s, ident=None):
    """schedule だけから出る数値。画素を見ないので model 非依存。"""
    ident = ident or (lambda k: k)
    kinds = sched["kind"]
    ids = [emitted_id(s, ident) for s in sched]
    dup = sum(1 for i in range(1, len(ids)) if ids[i] == ids[i - 1])
    return dict(
        out_frames=int(len(sched)),
        calls=int((kinds == MODEL).sum()),
        copy=int((kinds == COPY).sum()),
        hold=int((kinds == HOLD).sum()),
        distinct=len(set(ids)),
        distinct_per_sec=round(len(set(ids)) / duration_s, 2),
        dup_frames=dup,
        dup_pct=round(dup / len(ids) * 100, 1),
    )


# ---------------------------------------------------------------- 自己検査

def _check():
    fps = 24000 / 1001

    # 1. 2コマ打ちを元の fps のまま張り直すと、絵と絵のちょうど中間が1枚入る
    runs = np.array([0, 2, 4, 6])
    s = build(runs, 8, fps, fps)
    assert len(s) == 8, len(s)
    got = [(KIND_NAME[int(x["kind"])], round(float(x["tau"]), 3)) for x in s[:6]]
    assert got == [("copy", 0.0), ("model", 0.5), ("copy", 0.0), ("model", 0.5),
                   ("copy", 0.0), ("model", 0.5)], got

    # 2. 1コマ打ちを x2 すると素直な x2 と一致する
    n = 10
    runs = np.arange(n)
    s = build(runs, n, fps, 2 * fps)
    nv = naive_x2(n, fps)
    assert len(s) == 2 * n, (len(s), 2 * n)
    for j in range(2 * n - 1):
        assert int(s[j]["kind"]) == int(nv[j]["kind"]), j
        assert abs(float(s[j]["tau"]) - float(nv[j]["tau"])) < 1e-9, j

    # 3. 尺が保たれる
    for fo in (2 * fps, 60.0, 120.0):
        s = build(np.arange(0, 100, 2), 100, fps, fo)
        assert abs(len(s) / fo - 100 / fps) < 1.0 / fo + 1e-9

    # 4. block した pair は hold になり model を呼ばない
    runs = np.array([0, 2, 4, 6])
    blk = np.array([False, True, False])
    s = build(runs, 8, fps, 4 * fps, block=blk)
    for x in s:
        if int(x["k"]) == 1 and float(x["tau"]) > 0:
            assert int(x["kind"]) == HOLD, x

    # 5. 均しても shot の両端と cut の位置は動かない
    runs = np.array([0, 1, 2, 10, 11, 12])
    a0 = anchors(runs, 13, "head")
    a1 = even_anchors(a0, runs, cut_frames=[10])
    assert a1[0] == a0[0] and a1[2] == a0[2]
    assert a1[3] == a0[3] and a1[5] == a0[5]
    assert abs(a1[1] - 1.0) < 1e-9          # 0,1,2 は元から等間隔
    runs = np.array([0, 1, 9, 10])
    a1 = even_anchors(anchors(runs, 11, "head"), runs, cut_frames=[])
    assert np.allclose(a1, [0, 10 / 3, 20 / 3, 10])

    # 6. 絵 index は単調に進む
    runs = np.array([0, 2, 5, 6, 11])
    s = build(runs, 14, fps, 60.0)
    assert (np.diff(s["k"]) >= 0).all()

    # 7. コマ打ちが一定なら head と center は同じ tau。混在すると割れる
    runs = np.arange(0, 20, 2)
    assert np.allclose(loo_tau(runs, 20, "head"), 0.5)
    assert np.allclose(loo_tau(runs, 20, "center"), 0.5)
    runs = np.array([0, 1, 3, 4, 5])          # 1,2,1,1 コマ打ち
    th = loo_tau(runs, 6, "head")
    tc = loo_tau(runs, 6, "center")
    assert abs(th[0] - 1 / 3) < 1e-12, th
    assert abs(tc[0] - 0.5) < 1e-12, tc       # 中央だと 0.5, 1.5, 3.0 で等間隔
    assert not np.allclose(th, tc)

    # 8. 集計
    runs = np.arange(0, 20, 5)
    s = build(runs, 20, fps, 60.0)
    st = stats(s, 20 / fps)
    assert st["out_frames"] == len(s)
    assert st["calls"] + st["copy"] + st["hold"] == len(s)
    print("retime 自己検査 OK")


if __name__ == "__main__":
    _check()
