"""tile差分の実効計算量を tile size × 判定閾値 で掃引する(GPU不要)

指標: 実効計算量比 = Σ(modelへ通す入力画素) / (frame数 × W × H)
      1.0未満でなければtile差分に意味がない。halo=20px固定。
"""
import subprocess
import numpy as np
import cv2

SRC = r"C:\01_work\00_Git\toybox\AI_Video_up\サンプル.mp4"
W, H = 720, 480
HALO = 20
CORES = [60, 96, 120, 160, 180, 240, 360]
THRESHOLDS = [2, 4, 6, 8, 12, 16]
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


def tile_px(changed, core):
    """このframeでmodelへ通す入力画素数(halo込み)。全画面より高ければ全画面。"""
    total = 0
    for y in range(0, H, core):
        for x in range(0, W, core):
            y1, x1 = min(y + core, H), min(x + core, W)
            ys0, ys1 = max(0, y - HALO), min(H, y1 + HALO)
            xs0, xs1 = max(0, x - HALO), min(W, x1 + HALO)
            if changed[ys0:ys1, xs0:xs1].any():
                total += (ys1 - ys0) * (xs1 - xs0)
    return min(total, H * W)


results = {}
frame_dedup = {t: 0 for t in THRESHOLDS}
n_frames = 0

for (ss, sec) in SEGMENTS:
    prev = None
    for f in frames(ss, sec):
        if prev is None:
            prev = f.copy()
            continue
        n_frames += 1
        d = cv2.absdiff(f, prev).max(axis=2)
        for t in THRESHOLDS:
            changed = d > t
            if not changed.any():
                frame_dedup[t] += 1
                for core in CORES:
                    results.setdefault((core, t), 0)
                continue
            for core in CORES:
                results[(core, t)] = results.get((core, t), 0) + tile_px(changed, core)
        prev = f.copy()

px_total = n_frames * H * W
print(f"評価frame数: {n_frames}  (区間 {SEGMENTS})")
print()
print("frame丸ごと同一と判定される割合 (= frame単位dedupの削減)")
for t in THRESHOLDS:
    r = frame_dedup[t] / n_frames
    print(f"  閾値 max|diff|>{t:2d}: {r*100:5.1f}%  → SR回数 {1/(1-r):.2f}倍削減")
print()
print("実効計算量比 (1.00 = 全画面SRと同じ。小さいほど良い)")
hdr = "  core\\閾値 " + "".join(f"{t:>8d}" for t in THRESHOLDS)
print(hdr)
for core in CORES:
    row = f"  {core:5d}    "
    for t in THRESHOLDS:
        row += f"{results[(core, t)] / px_total:8.3f}"
    print(row)
