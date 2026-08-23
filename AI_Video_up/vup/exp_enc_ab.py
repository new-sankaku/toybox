"""exp_enc_ab - encode option の速度を drift に強い形で比べる。

同じ機体で別の計測が走っていると GPU clock と memory 帯域が動き、
条件を順番に並べて測ると後の条件ほど不利になる。条件を round robin で
回し、条件ごとの中央値を採る。各 round の GPU 使用率も記録して、
汚染がどれだけあったかを表に出す。
"""
import statistics
import subprocess
import sys
import time

FW, FH = 1440, 960
SZ = FW * FH * 3 // 2      # nv12
N = 600
ROUNDS = 5

CONFIGS = [
    ("現行 p7 + -pix_fmt yuv420p", ["-preset", "p7", "-cq", "24",
                                    "-pix_fmt", "yuv420p"]),
    ("p7 (pix_fmt 指定なし)", ["-preset", "p7", "-cq", "24"]),
    ("p7 + split3", ["-preset", "p7", "-cq", "24",
                     "-split_encode_mode", "3"]),
    ("p5", ["-preset", "p5", "-cq", "24"]),
    ("p5 + split3", ["-preset", "p5", "-cq", "24",
                     "-split_encode_mode", "3"]),
    ("p6 + split3", ["-preset", "p6", "-cq", "24",
                     "-split_encode_mode", "3"]),
    ("p5 + split3 + bf0 + lookahead0",
     ["-preset", "p5", "-cq", "24", "-split_encode_mode", "3",
      "-bf", "0", "-rc-lookahead", "0"]),
]


def gpu_util():
    try:
        o = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,"
                            "clocks.sm", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=5).stdout
        a, b = o.strip().splitlines()[0].split(",")
        return int(a), int(b)
    except Exception:
        return -1, -1


def one(frame, eargs, n=N):
    cmd = (["ffmpeg", "-v", "error", "-y", "-f", "rawvideo",
            "-pix_fmt", "nv12", "-s", f"{FW}x{FH}", "-r", "30", "-i", "-",
            "-c:v", "hevc_nvenc"] + eargs + ["-f", "null", "-"])
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         bufsize=SZ * 4)
    t0 = time.perf_counter()
    try:
        for _ in range(n):
            p.stdin.write(frame)
        p.stdin.close()
    except Exception:
        pass
    p.wait()
    el = time.perf_counter() - t0
    return n / el if p.returncode == 0 else 0.0


def main():
    import cv2
    import numpy as np
    rng = np.random.default_rng(0)
    bgr = cv2.GaussianBlur(rng.integers(0, 255, (FH, FW, 3), dtype=np.uint8),
                           (0, 0), 3)
    i420 = cv2.cvtColor(bgr, cv2.COLOR_BGR2YUV_I420)
    y = i420[:FH]
    u = i420[FH:FH + FH // 4].reshape(FH // 2, FW // 2)
    v = i420[FH + FH // 4:].reshape(FH // 2, FW // 2)
    uv = np.empty((FH // 2, FW), dtype=np.uint8)
    uv[:, 0::2], uv[:, 1::2] = u, v
    frame = np.concatenate([y.reshape(-1), uv.reshape(-1)]).tobytes()

    one(frame, ["-preset", "p5"])          # warm up
    res = {c[0]: [] for c in CONFIGS}
    for r in range(ROUNDS):
        g, clk = gpu_util()
        print(f"-- round {r + 1}/{ROUNDS}  GPU {g}% {clk}MHz")
        for label, eargs in CONFIGS:
            res[label].append(one(frame, eargs))
    print(f"\n=== nv12 {FW}x{FH} を pipe 投入 -> hevc_nvenc "
          f"({N}f x {ROUNDS} round の中央値) ===")
    base = statistics.median(res[CONFIGS[0][0]])
    for label, _ in CONFIGS:
        vs = sorted(res[label])
        med = statistics.median(vs)
        print(f"{label:34s} {med:7.1f} fps  (最小{vs[0]:6.1f} 最大{vs[-1]:6.1f})"
              f"  現行比 {med / base:4.2f}x")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        ROUNDS = int(sys.argv[1])
    main()
