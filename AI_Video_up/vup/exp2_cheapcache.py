"""cache に生frameを持たずに済むか。

判定は box4max(|a - b|)、つまり **絶対値を取ってから** 4x4 平均する。
cache に box4(frame) だけを持つと判定は |box4(a) - box4(b)| になり、
block 内で符号が打ち消し合う変化(半分が+30、半分が-30)を見落とす。
別の判定になるので、削減率と安全性を測って比べる。

  A  box4(|a-b|)      cache は生frame 1.04MB/枚。判定は 1MB の absdiff
  B  |box4(a)-box4(b)| cache は box4 0.065MB/枚。判定は 65KB の absdiff

安全指標は両方とも独立な「欠落画素(|d|>48 の画素数)」で測る。
"""
import subprocess
import sys
import time

import cv2
import numpy as np

SRC = r"C:\01_work\00_Git\toybox\AI_Video_up\サンプル.mp4"
W, H = 720, 480
PX3 = H * W * 3
SW, SH = W // 4, H // 4


class Way:
    def __init__(self, name, kind, thr, depth):
        self.name, self.kind, self.thr, self.depth = name, kind, thr, depth
        self.cache = []          # kind=A: 生frame / kind=B: box4
        self.calls = 0
        self.miss_total = 0
        self.miss_max = 0
        self.miss_frames = 0
        self.t = 0.0

    def step(self, fr, small):
        t0 = time.perf_counter()
        item = fr if self.kind == "A" else small
        if not self.cache:
            self.cache.append(item.copy())
            self.calls += 1
            self.t += time.perf_counter() - t0
            return None
        hit = -1
        for j in range(len(self.cache) - 1, -1, -1):
            if self.kind == "A":
                d = cv2.absdiff(fr, self.cache[j])
                ok = int(cv2.resize(d, (SW, SH),
                                    interpolation=cv2.INTER_AREA).max()) < self.thr
            else:
                ok = int(cv2.absdiff(small, self.cache[j]).max()) < self.thr
            if ok:
                hit = j
                break
        if hit >= 0:
            self.cache.append(self.cache.pop(hit))
        else:
            self.calls += 1
            self.cache.append(item.copy())
            if len(self.cache) > self.depth:
                self.cache.pop(0)
        self.t += time.perf_counter() - t0
        return hit


def main():
    limit = float(sys.argv[1]) if len(sys.argv) > 1 else 0.0
    ways = ([Way(f"A 生frame  thr{t}", "A", t, 16) for t in (16, 20, 24)] +
            [Way(f"B box4のみ thr{t}", "B", t, 16)
             for t in (4, 6, 8, 10, 12, 16, 20)])
    # 安全指標のために、hit したときの本来の frame を持っておく必要がある。
    # A/B とも「使い回した相手の生frame」を別に保持して欠落画素を測る。
    truth = {id(w): [] for w in ways}

    cmd = ["ffmpeg", "-v", "error", "-i", SRC]
    if limit:
        cmd += ["-t", str(limit)]
    cmd += ["-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=PX3 * 8)
    buf = bytearray(PX3)
    mv = memoryview(buf)
    n = 0
    t0 = time.time()
    while True:
        got = p.stdout.readinto(mv)
        if not got or got < PX3:
            break
        n += 1
        fr = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
        small = cv2.resize(fr, (SW, SH), interpolation=cv2.INTER_AREA)
        for w in ways:
            tr = truth[id(w)]
            hit = w.step(fr, small)
            if not tr:
                tr.append(fr.copy())
                continue
            if hit is None:
                continue
            if hit >= 0:
                d = cv2.absdiff(fr, tr[hit])
                m = cv2.countNonZero(
                    cv2.threshold(d.reshape(H, -1), 48, 255,
                                  cv2.THRESH_BINARY)[1])
                w.miss_total += m
                w.miss_max = max(w.miss_max, m)
                w.miss_frames += m > 100
                tr.append(tr.pop(hit))
            else:
                tr.append(fr.copy())
                if len(tr) > w.depth:
                    tr.pop(0)
        if n % 6000 == 0:
            print(f"  {n}  {time.time() - t0:.0f}s", flush=True)
    p.stdout.close()
    p.wait()

    print(f"\n評価 {n} frame  cache 深さ16")
    print(f"{'構成':22s} {'SR回数':>7s} {'削減':>7s} {'欠落合計':>10s} "
          f"{'欠落最大':>8s} {'>100':>6s} {'判定ms/frame':>12s}")
    for w in ways:
        print(f"{w.name:22s} {w.calls:7d} {n / w.calls:6.2f}倍 "
              f"{w.miss_total:10d} {w.miss_max:8d} {w.miss_frames:6d} "
              f"{w.t / n * 1000:11.2f}")


if __name__ == "__main__":
    main()
