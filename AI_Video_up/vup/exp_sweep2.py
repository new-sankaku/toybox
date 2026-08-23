"""変化判定の基準を変えて実効計算量を測り直す

(a) max|diff| > t                     ... 1画素でも動けば再計算(h264 noiseに弱い)
(b) |diff|>t の画素数が tile面積のk%超 ... noiseに強いが小さな動きを見落とす
(c) 2x2平均で潰してから max|diff| > t  ... noiseだけ落として動きは残す狙い
"""
import subprocess
import numpy as np
import cv2

SRC = r"C:\01_work\00_Git\toybox\AI_Video_up\サンプル.mp4"
W, H = 720, 480
HALO = 20
CORE = 120
SEGMENTS = [(30, 15), (120, 15), (210, 15), (270, 15)]  # 先頭5分から計60秒


def frames(ss, sec):
    p = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-ss", str(ss), "-i", SRC, "-t", str(sec),
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
        stdout=subprocess.PIPE, bufsize=W * H * 3 * 8)
    n = W * H * 3
    while True:
        b = p.stdout.read(n)
        if len(b) < n:
            break
        yield np.frombuffer(b, np.uint8).reshape(H, W, 3)
    p.stdout.close()
    p.wait()


def cost(mask_fn, d, dsmall):
    total = 0
    for y in range(0, H, CORE):
        for x in range(0, W, CORE):
            y1, x1 = min(y + CORE, H), min(x + CORE, W)
            ys0, ys1 = max(0, y - HALO), min(H, y1 + HALO)
            xs0, xs1 = max(0, x - HALO), min(W, x1 + HALO)
            if mask_fn(d, dsmall, ys0, ys1, xs0, xs1):
                total += (ys1 - ys0) * (xs1 - xs0)
    return min(total, H * W)


CRITERIA = []
for t in (2, 6, 12):
    CRITERIA.append((f"(a) max>{t}",
                     lambda d, ds, a, b, c, e, t=t: d[a:b, c:e].max() > t))
for t, k in ((2, 0.002), (2, 0.01), (2, 0.03), (6, 0.01), (6, 0.03)):
    CRITERIA.append((f"(b) >{t} が{k*100:g}%超",
                     lambda d, ds, a, b, c, e, t=t, k=k:
                     (d[a:b, c:e] > t).sum() > k * (b - a) * (e - c)))
for t in (2, 4, 6, 8):
    CRITERIA.append((f"(c) 2x2平均 max>{t}",
                     lambda d, ds, a, b, c, e, t=t:
                     ds[a // 2:(b + 1) // 2, c // 2:(e + 1) // 2].max() > t))

acc = {name: 0 for name, _ in CRITERIA}
skip = {name: 0 for name, _ in CRITERIA}
n = 0
for (ss, sec) in SEGMENTS:
    prev = None
    for f in frames(ss, sec):
        if prev is None:
            prev = f.copy()
            continue
        n += 1
        d = cv2.absdiff(f, prev).max(axis=2)
        small_a = cv2.resize(f, (W // 2, H // 2), interpolation=cv2.INTER_AREA)
        small_b = cv2.resize(prev, (W // 2, H // 2), interpolation=cv2.INTER_AREA)
        ds = cv2.absdiff(small_a, small_b).max(axis=2)
        for name, fn in CRITERIA:
            c = cost(fn, d, ds)
            acc[name] += c
            if c == 0:
                skip[name] += 1
        prev = f.copy()

print(f"評価frame数 {n}  core={CORE} halo={HALO}")
print(f"{'判定基準':24s} {'実効計算量比':>12s} {'全skip率':>9s}")
for name, _ in CRITERIA:
    print(f"{name:24s} {acc[name] / (n * H * W):12.3f} {skip[name] / n * 100:8.1f}%")
