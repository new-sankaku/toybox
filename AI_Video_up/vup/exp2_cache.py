"""直前の1枚ではなく、過去K枚のSR結果から一致するものを探す。

anime の会話場面は「口だけ動く止め絵」が多く、frame i は i-1 とは違うが
i-2 とは同じ、という往復が起きる。直前1枚としか比べない現行方式は
これを全部取りこぼす。過去K枚を持てば拾えるはずで、
SR結果の保持は 1440x960x3 = 4.1MB/枚なので K=8 でも 33MB でしかない。

判定を K 倍やると CPU が持たないので、
  1. 全frameの小さな指紋(45x30 の平均画像)を作る
  2. 指紋が近い候補だけ box4 判定に掛ける
の2段にした場合の判定回数も数える。
"""
import subprocess
import sys
import time

import cv2
import numpy as np

SRC = r"C:\01_work\00_Git\toybox\AI_Video_up\サンプル.mp4"
W, H = 720, 480
PX3 = H * W * 3
THR = 16          # box4 平均|d| の閾値
SIG = (45, 30)    # 指紋の大きさ


def box4max(d):
    return int(cv2.resize(d, (W // 4, H // 4),
                          interpolation=cv2.INTER_AREA).max())


def sig_of(f):
    return cv2.resize(f, SIG, interpolation=cv2.INTER_AREA).astype(np.int16)


def main():
    limit = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0
    ks = [1, 2, 3, 4, 6, 8, 16]
    cmd = ["ffmpeg", "-v", "error", "-i", SRC, "-t", str(limit),
           "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=PX3 * 8)
    buf = bytearray(PX3)
    mv = memoryview(buf)

    state = {k: {"cache": [], "sigs": [], "calls": 0, "miss": 0,
                 "full": 0, "hit_age": []} for k in ks}
    n = 0
    t0 = time.time()
    while True:
        got = p.stdout.readinto(mv)
        if not got or got < PX3:
            break
        fr = np.frombuffer(buf, np.uint8).reshape(H, W, 3).copy()
        n += 1
        s = sig_of(fr)
        for k in ks:
            st = state[k]
            if not st["cache"]:
                st["cache"].append(fr)
                st["sigs"].append(s)
                st["calls"] += 1
                continue
            # 指紋の距離で候補を並べ、近い順に box4 判定
            ds = [int(np.abs(s - q).max()) for q in st["sigs"]]
            order = np.argsort(ds)
            hit = -1
            for j in order:
                if ds[j] > 48:            # 指紋が遠すぎるものは見るまでもない
                    break
                st["full"] += 1
                if box4max(cv2.absdiff(fr, st["cache"][j])) < THR:
                    hit = int(j)
                    break
            if hit >= 0:
                st["miss"] += 1
                st["hit_age"].append(len(st["cache"]) - hit)
                # 使ったものを最新へ寄せる(LRU)
                st["cache"].append(st["cache"].pop(hit))
                st["sigs"].append(st["sigs"].pop(hit))
            else:
                st["calls"] += 1
                st["cache"].append(fr)
                st["sigs"].append(s)
                if len(st["cache"]) > k:
                    st["cache"].pop(0)
                    st["sigs"].pop(0)
    p.stdout.close()
    p.wait()
    print(f"評価 {n} frame ({limit:.0f}秒)  {time.time() - t0:.0f}s")
    print(f"{'cache枚数':>9s} {'SR回数':>8s} {'削減':>7s} {'box4判定/frame':>14s} "
          f"{'一致の遡り 中央':>15s}")
    for k in ks:
        st = state[k]
        age = st["hit_age"]
        print(f"{k:9d} {st['calls']:8d} {n / st['calls']:6.2f}倍 "
              f"{st['full'] / n:13.2f} "
              f"{(np.median(age) if age else 0):14.0f}")


if __name__ == "__main__":
    main()
