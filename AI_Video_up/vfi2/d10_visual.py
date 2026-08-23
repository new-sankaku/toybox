"""目で見る。数字(保持 20.9ms 対 104.3ms の二極)と見た目が合うかを確かめる。

(1) 並べた比較動画を 1/4 速で作る(人が見る用)
    左 = x2素直(47.952fps)、右 = 60絵(60fps)。どちらも 1/4 速へ伸ばしてから
    共通の 60fps へ載せる。frame を間引かないので、1枚が画面に留まる時間の
    比は元のまま保たれる。

(2) 連続 frame を並べた1枚の画像(こちらは診断担当が読む用)
    動いている区間を切り出し、出力 frame を横に並べる。x2素直 では
    「同じ絵が5枚 → 中間が1枚 → 同じ絵が5枚」が並ぶはず。
"""
import argparse
import subprocess

import cv2
import numpy as np

import lib

X2 = lib.OUT / "B_talk_x2素直.mp4"
R60 = lib.OUT / "B_talk_60絵.mp4"
FPS_X2 = lib.FPS * 2
FPS_60 = 60.0
SLOW = 4                      # 1/4 速
SEG = (13.0, 17.0)            # 素材の時刻(秒)。3コマ打ちで実際に動いている区間


TILE = (960, 540)
OUT_FPS = 60.0


def _seg(path, w=TILE[0], h=TILE[1]):
    """SEG の区間を 960x540 で読み込む。ffmpeg の drawtext は fontconfig が
    無くて落ちるので、文字は cv2 で入れる。"""
    p = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-ss", str(SEG[0]), "-t", str(SEG[1] - SEG[0]),
         "-i", str(path), "-fps_mode", "passthrough",
         "-vf", f"scale={w}:{h}:flags=area", "-f", "rawvideo",
         "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE)
    buf = bytearray(w * h * 3)
    mv = memoryview(buf)
    out = []
    while p.stdout.readinto(mv) == w * h * 3:
        out.append(np.frombuffer(bytes(buf), np.uint8).reshape(h, w, 3).copy())
    p.stdout.close()
    p.wait()
    return out


def compare_video(dst):
    """左右を 1/4 速へ伸ばして共通の 60fps へ載せる。frame は間引かないので、
    1枚が画面に留まる時間の比(20.9ms 対 16.7ms)は元のまま保たれる。"""
    L, R = _seg(X2), _seg(R60)
    n = int((SEG[1] - SEG[0]) * SLOW * OUT_FPS)
    enc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
         "-s", f"{TILE[0] * 2}x{TILE[1]}", "-r", f"{OUT_FPS:g}", "-i", "-",
         "-c:v", "libx264", "-preset", "slow", "-crf", "16",
         "-pix_fmt", "yuv420p", str(dst)], stdin=subprocess.PIPE)
    for j in range(n):
        t = j / OUT_FPS / SLOW                    # 素材側の経過時刻(秒)
        l = L[min(int(t * FPS_X2), len(L) - 1)]
        r = R[min(int(t * FPS_60), len(R) - 1)]
        row = np.concatenate([l, r], axis=1).copy()
        for i, name in enumerate(("x2 naive 47.952fps", "retimed 60fps")):
            for c, th in (((0, 0, 0), 4), ((255, 255, 255), 1)):
                cv2.putText(row, name, (i * TILE[0] + 16, 34),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, c, th)
        enc.stdin.write(row.tobytes())
    enc.stdin.close()
    enc.wait()
    return dst


# ---------------------------------------------------------------- 多列の 1/4 速

def read_range(path, k0, k1, w, h):
    """出力 frame k0..k1-1 を w x h で取り出す。file は毎回頭から読む
    (30秒の 1080p なら数秒。segment ごとに読み捨てて memory を空ける)。"""
    p = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(path), "-fps_mode", "passthrough",
         "-vf", f"scale={w}:{h}:flags=area", "-f", "rawvideo",
         "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE)
    buf = bytearray(w * h * 3)
    mv = memoryview(buf)
    out = []
    for k in range(k1):
        if p.stdout.readinto(mv) < w * h * 3:
            break
        if k >= k0:
            out.append(np.frombuffer(bytes(buf), np.uint8).reshape(h, w, 3).copy())
    p.stdout.close()
    p.kill()
    if not out:
        raise RuntimeError(f"{path}: frame {k0}..{k1} を取り出せません")
    return out


def slow_grid(cols, segments, dst, tile=(640, 360), slow=SLOW):
    """cols = [(path, fps, 表示名), ...] を横に並べ、1/4 速で1本にする。

    segments = [(t0, t1, 見出し), ...]。素材側の時刻(秒)。
    frame は間引かず、共通の 60fps へ載せる。1枚が画面に留まる時間の比は
    元のまま保たれる(実速の4倍の長さで画面に出る)。
    """
    w, h = tile
    enc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
         "-s", f"{w * len(cols)}x{h}", "-r", f"{OUT_FPS:g}", "-i", "-",
         "-c:v", "libx264", "-preset", "slow", "-crf", "18",
         "-pix_fmt", "yuv420p", str(dst)], stdin=subprocess.PIPE)
    for (t0, t1, cap) in segments:
        got = []
        for path, fps, _ in cols:
            k0 = int(t0 * fps)
            k1 = int(np.ceil(t1 * fps)) + 1
            got.append((k0, read_range(path, k0, k1, w, h)))
        n = int((t1 - t0) * slow * OUT_FPS)
        for j in range(n):
            t = j / OUT_FPS / slow                    # 素材側の経過時刻(秒)
            row = []
            for (path, fps, _), (k0, fr) in zip(cols, got):
                i = min(max(int((t0 + t) * fps) - k0, 0), len(fr) - 1)
                row.append(fr[i])
            row = np.concatenate(row, axis=1).copy()
            for i, (_, _, name) in enumerate(cols):
                for c, th in (((0, 0, 0), 4), ((255, 255, 255), 1)):
                    cv2.putText(row, name, (i * w + 10, 24),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.55, c, th)
            for c, th in (((0, 0, 0), 4), ((80, 220, 255), 1)):
                cv2.putText(row, cap, (10, h - 12),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, c, th)
            enc.stdin.write(row.tobytes())
        del got
    enc.stdin.close()
    enc.wait()
    return dst


def cols_of(clip, conds=("元", "x2素直", "60絵")):
    fps = {"元": lib.FPS, "x2素直": lib.FPS * 2, "x2絵": lib.FPS * 2,
           "60絵": 60.0, "60均し": 60.0, "120絵": 120.0}
    name = {"元": "source 23.976fps", "x2素直": "x2 naive 47.952fps",
            "x2絵": "retimed 47.952fps", "60絵": "retimed 60fps",
            "60均し": "retimed 60fps (evened)", "120絵": "retimed 120fps"}
    return [(lib.OUT / f"{clip}_{c}.mp4", fps[c], name[c]) for c in conds]


def busy_window(clip, dur=2.5, max_cuts=1):
    """cut が少なく、絵と絵の変位の合計が最大の窓(素材の秒)。"""
    import smooth
    gaps, spans = smooth.gap_spans(clip)
    n = len(lib.load(clip))
    cuts = [int(c) for c in lib.cut_frames(clip)]
    wf = int(dur * lib.FPS)
    best, best_score = 0, -1.0
    for a in range(0, n - wf, 3):
        b = a + wf
        if sum(1 for c in cuts if a <= c < b) > max_cuts:
            continue
        sc = sum(float(s) for (g0, _), s in zip(gaps, spans) if a <= g0 < b)
        if sc > best_score:
            best, best_score = a, sc
    return best / lib.FPS, (best + wf) / lib.FPS, best_score


def grab(path, k0, n, w=1920, h=1080):
    """出力 frame k0 から n 枚を BGR で取り出す。"""
    p = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(path), "-fps_mode", "passthrough",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE)
    buf = bytearray(w * h * 3)
    mv = memoryview(buf)
    out = []
    for k in range(k0 + n):
        if p.stdout.readinto(mv) < w * h * 3:
            raise RuntimeError(f"{path}: frame {k} で decode が尽きました")
        if k >= k0:
            out.append(np.frombuffer(bytes(buf), np.uint8).reshape(h, w, 3).copy())
    p.stdout.close()
    p.kill()
    return out


def motion_box(frames, side=384):
    """一番動いている所を正方形で囲む。"""
    d = np.zeros(frames[0].shape[:2], np.float32)
    for i in range(len(frames) - 1):
        d += np.abs(frames[i + 1].astype(np.float32)
                    - frames[i].astype(np.float32)).mean(2)
    ys, xs = np.nonzero(d > max(d.max() * 0.25, 4.0))
    if len(xs) == 0:
        raise ValueError("動いている画素が在りません")
    cx, cy = int(np.median(xs)), int(np.median(ys))
    h, w = d.shape
    x0 = int(np.clip(cx - side // 2, 0, w - side))
    y0 = int(np.clip(cy - side // 2, 0, h - side))
    return x0, y0, side


def box4_max(a, b):
    """4x4 平均した差の最大値。lib.MOVE_MIN と同じ物差し(こちらは CPU)。
    出力は H.264 なので厳密一致では判定できない(encode 雑音で必ず違う)。"""
    d = np.abs(a.astype(np.float32) - b.astype(np.float32))
    h, w = d.shape[:2]
    d = d[:h // 4 * 4, :w // 4 * 4].reshape(h // 4, 4, w // 4, 4, 3)
    return float(d.mean(axis=(1, 3)).round().max())


def strip(frames, box, tile=192, label=""):
    x0, y0, s = box
    cells = []
    prev = None
    for i, f in enumerate(frames):
        c = cv2.resize(f[y0:y0 + s, x0:x0 + s], (tile, tile),
                       interpolation=cv2.INTER_AREA)
        same = prev is not None and box4_max(f, prev) < lib.MOVE_MIN
        txt = f"{i}" + ("=" if same else "*")
        col = (120, 120, 255) if same else (120, 255, 120)
        cv2.rectangle(c, (0, 0), (tile - 1, tile - 1), col, 2)
        cv2.putText(c, txt, (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 4)
        cv2.putText(c, txt, (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 1)
        cells.append(c)
        prev = f
    row = np.concatenate(cells, axis=1)
    bar = np.zeros((28, row.shape[1], 3), np.uint8)
    cv2.putText(bar, label, (5, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                (255, 255, 255), 1)
    return np.concatenate([bar, row], axis=0)


def contact(dst, t0=14.31, dur=0.25):
    n_x2 = int(round(dur * FPS_X2))
    n_60 = int(round(dur * FPS_60))
    fx = grab(X2, int(round(t0 * FPS_X2)), n_x2)
    f6 = grab(R60, int(round(t0 * FPS_60)), n_60)
    box = motion_box(f6)
    a = strip(fx, box, label=f"x2 naive 47.952fps  ({n_x2} frames = {dur*1000:.0f}ms)"
                             "   * = new drawing  |  = = duplicate of previous")
    b = strip(f6, box, label=f"retimed 60fps  ({n_60} frames = {dur*1000:.0f}ms)")
    w = max(a.shape[1], b.shape[1])
    pad = lambda x: np.pad(x, ((0, 0), (0, w - x.shape[1]), (0, 0)))
    sheet = np.concatenate([pad(a), np.zeros((8, w, 3), np.uint8), pad(b)], axis=0)
    # cv2.imwrite は非ASCII の path を書けない(黙って False を返す)
    ok, enc = cv2.imencode(".png", sheet)
    if not ok:
        raise RuntimeError("png へ encode できません")
    dst.write_bytes(enc.tobytes())
    return dst, box


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--t0", type=float, default=14.31)
    args = ap.parse_args()
    v = compare_video(lib.OUT / "目視_B_talk_x2素直と60絵_4分の1速.mp4")
    lib.log(f"比較動画: {v}")
    p, box = contact(lib.RESULTS / "目視_B_talk_連続frame.png", args.t0)
    lib.log(f"連続frame: {p}  切り出し {box}")
    lib.record("visual", dict(clip="B_talk", video=str(v), sheet=str(p),
                             seg_s=SEG, slow=SLOW, t0=args.t0, box=list(box)))
