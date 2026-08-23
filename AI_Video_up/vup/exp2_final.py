"""最終確認。全長16分34秒で判定基準を比べ、動きのある区間での取りこぼしを見る。

GPU を使わない。SR 実行回数は判定だけで決まるので、他の計測と競合しない。

安全性は3つの角度で見る:
  欠落画素   使い回した frame と本来の frame で |d|>48 の画素数
  取りこぼし frame  欠落画素が100を超えた frame の数(見て分かる大きさ)
  動作中の使い回し率  「明らかに動いている区間」で使い回してしまった率
動作中かどうかは、判定基準とは独立に「直前 frame との box4 最大が40以上」で決める。
"""
import subprocess
import sys
import time

import cv2
import numpy as np

SRC = r"C:\01_work\00_Git\toybox\AI_Video_up\サンプル.mp4"
W, H = 720, 480
PX3 = H * W * 3
MOVING = 40          # 「明らかに動いている」の閾値(直前frameとの box4 最大)


def read_pts():
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "packet=pts_time", "-of", "csv=p=0", SRC],
        capture_output=True, text=True, check=True).stdout
    pts = np.sort(np.asarray([float(x.split(",")[0]) for x in out.splitlines()
                              if x.strip() and x.split(",")[0] != "N/A"]))
    pts = pts[pts >= -1e-9]
    return pts - pts[0] if len(pts) else pts


def counts_for(pts, num, den):
    dur = float(pts[-1])
    n_out = int(np.floor(dur * num / den + 1e-6))
    t = np.arange(n_out, dtype=np.float64) * den / num
    idx = np.searchsorted(pts, t, side="right") - 1
    np.clip(idx, 0, len(pts) - 1, out=idx)
    return np.bincount(idx, minlength=len(pts)), n_out


def box4(d):
    return int(cv2.resize(d, (W // 4, H // 4),
                          interpolation=cv2.INTER_AREA).max())


class Crit:
    """1つの判定基準の状態。cache_k>1 なら過去k枚のSR結果から探す。"""

    def __init__(self, name, kind, a, b=0.0, cache_k=1):
        self.name, self.kind, self.a, self.b, self.k = name, kind, a, b, cache_k
        self.cache = []
        self.calls = 0
        self.miss_total = 0
        self.miss_max = 0
        self.miss_frames = 0
        self.moving_reuse = 0
        self.moving_n = 0
        self.worst = None

    def _same(self, fr, ref):
        d = cv2.absdiff(fr, ref)
        if self.kind == "box":
            return box4(d) < self.a, d
        nz = cv2.countNonZero(
            cv2.threshold(d.reshape(H, -1), self.a, 255, cv2.THRESH_BINARY)[1])
        return nz <= self.b * PX3, d

    def step(self, fr, moving, t):
        if not self.cache:
            self.cache.append(fr.copy())
            self.calls += 1
            return
        if moving:
            self.moving_n += 1
        hit = -1
        dd = None
        for j in range(len(self.cache) - 1, -1, -1):
            same, d = self._same(fr, self.cache[j])
            if same:
                hit, dd = j, d
                break
        if hit >= 0:
            m = cv2.countNonZero(
                cv2.threshold(dd.reshape(H, -1), 48, 255, cv2.THRESH_BINARY)[1])
            self.miss_total += m
            if m > self.miss_max:
                self.miss_max, self.worst = m, t
            if m > 100:
                self.miss_frames += 1
            if moving:
                self.moving_reuse += 1
            self.cache.append(self.cache.pop(hit))
        else:
            self.calls += 1
            self.cache.append(fr.copy())
            if len(self.cache) > self.k:
                self.cache.pop(0)


def run_stream(pts, counts, crits, limit=0.0):
    """decode して各 Crit を進める。出力に使った source frame 数を返す。"""
    n_src = len(pts)
    cmd = ["ffmpeg", "-v", "error", "-i", SRC]
    if limit:
        cmd += ["-t", str(limit)]
    cmd += ["-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=PX3 * 8)
    buf = bytearray(PX3)
    mv = memoryview(buf)
    seen = used = 0
    t0 = time.time()
    while True:
        got = p.stdout.readinto(mv)
        if not got or got < PX3:
            break
        i = seen
        seen += 1
        if i >= n_src or counts[i] == 0:
            continue
        used += 1
        fr = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
        for c in crits:
            c.step(fr, False, float(pts[i]))
        if seen % 6000 == 0:
            print(f"  {seen}/{n_src}  {time.time() - t0:.0f}s", flush=True)
    p.stdout.close()
    p.wait()
    return used


def main():
    limit = float(sys.argv[1]) if len(sys.argv) > 1 else 0.0
    pts = read_pts()
    counts, n_out = counts_for(pts, 30000, 1001)
    n_src = len(pts)

    crits = [Crit("現行 balanced", "glob", 4, 0.0015),
             Crit("現行 aggressive", "glob", 12, 0.012),
             Crit("box4<16", "box", 16),
             Crit("box4<20", "box", 20),
             Crit("box4<24", "box", 24),
             Crit("box4<28", "box", 28),
             Crit("box4<20 + cache8", "box", 20, cache_k=8),
             Crit("box4<20 + cache16", "box", 20, cache_k=16)]

    cmd = ["ffmpeg", "-v", "error", "-i", SRC]
    if limit:
        cmd += ["-t", str(limit)]
    cmd += ["-fps_mode", "passthrough", "-f", "rawvideo",
            "-pix_fmt", "bgr24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=PX3 * 8)
    buf = bytearray(PX3)
    mv = memoryview(buf)
    prev = None
    seen = used = n_moving = 0
    t0 = time.time()
    while True:
        got = p.stdout.readinto(mv)
        if not got or got < PX3:
            break
        i = seen
        seen += 1
        if i >= n_src or counts[i] == 0:
            continue
        used += 1
        fr = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
        moving = False
        if prev is not None:
            moving = box4(cv2.absdiff(fr, prev)) >= MOVING
        n_moving += moving
        prev = fr.copy()
        for c in crits:
            c.step(fr, moving, float(pts[i]))
        if seen % 6000 == 0:
            print(f"  {seen}/{n_src}  {time.time() - t0:.0f}s", flush=True)
    p.stdout.close()
    p.wait()

    print(f"\nsource frame {seen}  出力に使う {used}  "
          f"明らかに動いている frame {n_moving} ({n_moving / used * 100:.1f}%)")
    print(f"{'判定基準':20s} {'SR回数':>7s} {'削減':>7s} {'欠落合計':>10s} "
          f"{'欠落最大':>8s} {'>100の frame':>12s} {'動作中の使回率':>13s}")
    for c in crits:
        print(f"{c.name:20s} {c.calls:7d} {used / c.calls:6.2f}倍 "
              f"{c.miss_total:10d} {c.miss_max:8d} {c.miss_frames:12d} "
              f"{c.moving_reuse / max(c.moving_n, 1) * 100:12.2f}%")
    print("\n最悪の使い回しが起きた時刻:")
    for c in crits:
        print(f"  {c.name:20s} t={c.worst if c.worst else 0:.2f}s  "
              f"欠落{c.miss_max}画素")


if __name__ == "__main__":
    main()
