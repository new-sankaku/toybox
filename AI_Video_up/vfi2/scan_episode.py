"""話数全体を低解像度で走査し、コマ打ち・動き量・cut密度を秒ごとに出す。"""
import subprocess, sys, json
import numpy as np
from pathlib import Path

SRC = Path(sys.argv[1])
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(exist_ok=True)
W, H = 320, 180
FPS = 24000 / 1001

p = subprocess.Popen(
    ["ffmpeg", "-v", "error", "-i", str(SRC), "-fps_mode", "passthrough",
     "-vf", f"scale={W}:{H}:flags=bilinear,format=gray", "-f", "rawvideo",
     "-pix_fmt", "gray", "-"], stdout=subprocess.PIPE)
buf = bytearray(W * H)
mv = memoryview(buf)
prev = None
mad, mx = [], []
n = 0
while True:
    got = p.stdout.readinto(mv)
    if not got or got < W * H:
        break
    f = np.frombuffer(bytes(buf), dtype=np.uint8).reshape(H, W).astype(np.int16)
    if prev is not None:
        d = np.abs(f - prev)
        mad.append(float(d.mean()))
        mx.append(float(np.percentile(d, 99.5)))
    prev = f
    n += 1
p.wait()
mad = np.array(mad, dtype=np.float32)
mx = np.array(mx, dtype=np.float32)
np.save(OUT / "ep_mad.npy", mad)
np.save(OUT / "ep_mx.npy", mx)
print("frames", n)

CUT = 12.0        # cut 判定(低解像度MAD)
SAME = 0.35       # 同じ絵とみなす閾値
is_cut = mad > CUT
is_same = mad < SAME
sec = int(FPS)
rows = []
for s in range(0, (n - 1) // sec):
    a, b = s * sec, min((s + 1) * sec, n - 1)
    seg = slice(a, b)
    rows.append(dict(sec=s, mad=float(mad[seg].mean()),
                     same_pct=float(is_same[seg].mean() * 100),
                     cuts=int(is_cut[seg].sum())))
json.dump(rows, open(OUT / "ep_seconds.json", "w"), ensure_ascii=False)
print("秒ごとの記録:", OUT / "ep_seconds.json")
