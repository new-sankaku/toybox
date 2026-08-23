"""dedup 判定の実 cost を測る。

SR が TensorRT bs=2 で 221.9 fps (4.5ms/回) になると、source frame あたりの
予算は 4.5ms / 削減率 しかない。判定が main thread の単一 thread で回る以上、
「判定は SR に隠れるので只」は成り立たなくなる可能性がある。

判定だけを取り出して、cache 深さごとの実測 ms/frame を出す。
"""
import subprocess
import sys
import time

import cv2
import numpy as np

SRC = r"C:\01_work\00_Git\toybox\AI_Video_up\サンプル.mp4"
W, H = 720, 480
PX3 = H * W * 3
THR = 20
SIG = (45, 30)


def main():
    limit = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0
    p = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", SRC, "-t", str(limit),
         "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
        stdout=subprocess.PIPE, bufsize=PX3 * 8)
    frames = []
    buf = bytearray(PX3)
    mv = memoryview(buf)
    while True:
        got = p.stdout.readinto(mv)
        if not got or got < PX3:
            break
        frames.append(np.frombuffer(buf, np.uint8).reshape(H, W, 3).copy())
    p.stdout.close()
    p.wait()
    print(f"評価 {len(frames)} frame")

    print(f"\n{'構成':28s} {'SR回数':>7s} {'削減':>7s} {'判定ms/frame':>13s} "
          f"{'box4回数/frame':>14s}")
    for depth, prefilter in ((1, False), (4, True), (8, True), (16, True),
                             (16, False)):
        cache, sigs = [], []
        calls = 0
        nbox = 0
        t = 0.0
        for fr in frames:
            t0 = time.perf_counter()
            if not cache:
                cache.append(fr)
                sigs.append(cv2.resize(fr, SIG, interpolation=cv2.INTER_AREA)
                            .astype(np.int16))
                calls += 1
                t += time.perf_counter() - t0
                continue
            if prefilter:
                s = cv2.resize(fr, SIG, interpolation=cv2.INTER_AREA).astype(np.int16)
                order = [j for j in np.argsort([int(np.abs(s - q).max())
                                                for q in sigs])
                         if int(np.abs(s - sigs[j]).max()) <= 48]
            else:
                s = None
                order = range(len(cache) - 1, -1, -1)
            hit = -1
            for j in order:
                nbox += 1
                d = cv2.absdiff(fr, cache[j])
                if int(cv2.resize(d, (W // 4, H // 4),
                                  interpolation=cv2.INTER_AREA).max()) < THR:
                    hit = int(j)
                    break
            if hit >= 0:
                cache.append(cache.pop(hit))
                if prefilter:
                    sigs.append(sigs.pop(hit))
            else:
                calls += 1
                cache.append(fr)
                if prefilter:
                    sigs.append(s)
                if len(cache) > depth:
                    cache.pop(0)
                    if prefilter:
                        sigs.pop(0)
            t += time.perf_counter() - t0
        n = len(frames)
        tag = f"cache{depth}" + ("+指紋" if prefilter else "（総当たり）")
        print(f"{tag:28s} {calls:7d} {n / calls:6.2f}倍 {t / n * 1000:12.2f} "
              f"{nbox / n:13.2f}")

    print("\n参考: SR 1回の cost")
    for name, fps in (("torch.compile bs=1", 100.6), ("TensorRT bs=2", 221.9)):
        print(f"  {name:22s} {1000 / fps:.2f} ms/回")


if __name__ == "__main__":
    main()
