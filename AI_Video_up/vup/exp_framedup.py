"""frame単位のdedup判定を、削減率と安全性の両面で評価する

「前frameのSR結果を使い回してよいか」の判定基準を複数用意し、
  - 削減率(何倍SR回数が減るか)
  - 使い回した場合に生じる誤差(source同士のPSNR。高いほど安全)
を測る。encode noiseだけの差なら使い回して問題ないが、
小さな動き(瞬き・口)を取りこぼすと、その部分だけ1 frame止まって見える。
"""
import subprocess
import numpy as np
import cv2

SRC = r"C:\01_work\00_Git\toybox\AI_Video_up\サンプル.mp4"
W, H = 720, 480
SEGMENTS = [(30, 15), (120, 15), (210, 15), (270, 15)]  # 先頭5分から計60秒
PX = H * W


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


# 実装で使う高速版(3ch absdiff + threshold + countNonZero, 1.0ms/frame)に合わせる。
# 数えるのは「画素」ではなく「channel値」なので、同じ動きでも最大3倍の数になる。
CRITERIA = [("厳密一致", 0, 0.0)] + [
    (f"|diff|>{t} のchannel値が{r*100:g}%未満", t, r)
    for t in (4, 8, 12)
    for r in (0.0005, 0.0015, 0.003, 0.006, 0.012)
]

hit = {n: [] for n, _, _ in CRITERIA}
total = 0
ref = {n: None for n, _, _ in CRITERIA}

for (ss, sec) in SEGMENTS:
    for n, _, _ in CRITERIA:
        ref[n] = None
    for f in frames(ss, sec):
        total += 1
        for name, thr, ratio in CRITERIA:
            r = ref[name]
            if r is None:
                ref[name] = f.copy()
                continue
            if thr == 0:
                same = np.array_equal(f, r)
            else:
                d = cv2.absdiff(f, r)
                nz = cv2.countNonZero(
                    cv2.threshold(d.reshape(H, -1), thr, 255, cv2.THRESH_BINARY)[1])
                same = nz <= ratio * PX * 3
            if same:
                mse = float(np.mean((f.astype(np.float32) - r.astype(np.float32)) ** 2))
                psnr = 99.0 if mse == 0 else 10 * np.log10(255.0 ** 2 / mse)
                hit[name].append(psnr)
            else:
                ref[name] = f.copy()

print(f"評価frame数 {total}")
print(f"{'判定基準':34s} {'使い回し率':>9s} {'SR削減':>7s} {'PSNR最小':>9s} {'PSNR中央':>9s}")
for name, _, _ in CRITERIA:
    v = hit[name]
    rate = len(v) / total
    red = 1 / (1 - rate) if rate < 1 else 99
    lo = min(v) if v else 99.0
    md = float(np.median(v)) if v else 99.0
    print(f"{name:34s} {rate*100:8.1f}% {red:6.2f}倍 {lo:9.1f} {md:9.1f}")
