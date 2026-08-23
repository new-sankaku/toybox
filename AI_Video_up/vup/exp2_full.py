"""全長16分34秒で、判定基準ごとの SR 実行回数を数える。

SR 回数は判定だけで決まり GPU を使わないので、他の計測と競合せず、
機体の状態にも左右されない。時間はこの回数に SR 単価を掛ければ出る。

decode は `-fps_mode passthrough`。既定のままだと rawvideo muxer が
VFR を CFR へ複製展開してしまい、source frame ではないものを数えることになる。
"""
import subprocess
import sys
import time

import cv2
import numpy as np

SRC = r"C:\01_work\00_Git\toybox\AI_Video_up\サンプル.mp4"
W, H = 720, 480
PX3 = H * W * 3


def read_pts():
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "packet=pts_time", "-of", "csv=p=0", SRC],
        capture_output=True, text=True, check=True).stdout
    return np.sort(np.asarray([float(x.split(",")[0]) for x in out.splitlines()
                               if x.strip() and x.split(",")[0] != "N/A"]))


def schedule(pts, num, den):
    dur = float(pts[-1])
    n_out = int(np.floor(dur * num / den + 1e-6))
    t = np.arange(n_out, dtype=np.float64) * den / num
    idx = np.searchsorted(pts, t, side="right") - 1
    np.clip(idx, 0, len(pts) - 1, out=idx)
    return np.bincount(idx, minlength=len(pts)), n_out


def c_global(thr, ratio):
    lim = ratio * PX3

    def f(d):
        return cv2.countNonZero(
            cv2.threshold(d.reshape(H, -1), thr, 255,
                          cv2.THRESH_BINARY)[1]) <= lim
    return f


def c_box(blk, thr):
    dw, dh = W // blk, H // blk

    def f(d):
        return int(cv2.resize(d, (dw, dh),
                              interpolation=cv2.INTER_AREA).max()) < thr
    return f


CRITS = [("厳密一致", lambda d: not d.any()),
         ("現行 balanced (|d|>4 が0.15%未満)", c_global(4, 0.0015)),
         ("現行 aggressive (|d|>12 が1.2%未満)", c_global(12, 0.012)),
         ("box4 max<10", c_box(4, 10)),
         ("box4 max<12", c_box(4, 12)),
         ("box4 max<14", c_box(4, 14)),
         ("box4 max<16", c_box(4, 16)),
         ("box4 max<20", c_box(4, 20)),
         ("box8 max<8", c_box(8, 8))]


def main():
    limit = float(sys.argv[1]) if len(sys.argv) > 1 else 0.0
    pts = read_pts()
    counts, n_out = schedule(pts, 30000, 1001)
    n_src = len(pts)
    print(f"source frame {n_src}  出力frame {n_out} (30000/1001)  "
          f"出力に使う source {int((counts > 0).sum())}")

    refs = [None] * len(CRITS)
    calls = [0] * len(CRITS)
    miss = [0] * len(CRITS)
    seen = 0
    cmd = ["ffmpeg", "-v", "error", "-i", SRC]
    if limit:
        cmd += ["-t", str(limit)]
    cmd += ["-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=PX3 * 8)
    buf = bytearray(PX3)
    mv = memoryview(buf)
    t0 = time.time()
    while True:
        got = p.stdout.readinto(mv)
        if not got or got < PX3:
            break
        i = seen
        seen += 1
        if i >= n_src or counts[i] == 0:
            continue
        fr = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
        for k, (_, fn) in enumerate(CRITS):
            r = refs[k]
            if r is None:
                refs[k] = fr.copy()
                calls[k] += 1
                continue
            d = cv2.absdiff(fr, r)
            if fn(d):
                miss[k] += cv2.countNonZero(
                    cv2.threshold(d.reshape(H, -1), 48, 255,
                                  cv2.THRESH_BINARY)[1])
            else:
                refs[k] = fr.copy()
                calls[k] += 1
        if seen % 4000 == 0:
            print(f"  {seen}/{n_src}  {time.time() - t0:.0f}s", flush=True)
    p.stdout.close()
    p.wait()
    used = int((counts[:seen] > 0).sum())
    print(f"\n読んだ source frame {seen}  うち出力に使う {used}")
    print(f"{'判定基準':34s} {'SR回数':>8s} {'削減':>7s} {'欠落合計':>10s}")
    for k, (name, _) in enumerate(CRITS):
        print(f"{name:34s} {calls[k]:8d} {used / calls[k]:6.2f}倍 {miss[k]:10d}")


if __name__ == "__main__":
    main()
