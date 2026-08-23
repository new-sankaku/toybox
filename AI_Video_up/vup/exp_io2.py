"""exp_io2 - 出力側 (SR結果 -> encoder) の投入経路を比較する。

現行は 1440x960 bgr24 (4.15MB/frame) を pipe へ流している。
半分の bytes (yuv420p/nv12) で流す場合と、ffmpeg 側 option の効きを測る。
"""
import subprocess
import sys
import time

FW, FH = 1440, 960
N = 900


def make_frames():
    import cv2
    import numpy as np
    rng = np.random.default_rng(0)
    base = cv2.GaussianBlur(
        rng.integers(0, 255, (FH, FW, 3), dtype=np.uint8), (0, 0), 3)
    i420 = cv2.cvtColor(base, cv2.COLOR_BGR2YUV_I420)
    y = i420[:FH]
    u = i420[FH:FH + FH // 4].reshape(FH // 2, FW // 2)
    v = i420[FH + FH // 4:].reshape(FH // 2, FW // 2)
    uv = np.empty((FH // 2, FW), dtype=np.uint8)
    uv[:, 0::2] = u
    uv[:, 1::2] = v
    nv12 = np.concatenate([y.reshape(-1), uv.reshape(-1)])
    return {"bgr24": base.tobytes(), "yuv420p": i420.tobytes(),
            "nv12": nv12.tobytes()}


SZ = {"bgr24": FW * FH * 3, "yuv420p": FW * FH * 3 // 2,
      "nv12": FW * FH * 3 // 2}


def run(frames, fmt, label, pre=None, post=None, n=N):
    cmd = ["ffmpeg", "-v", "error", "-y"] + (pre or [])
    cmd += ["-f", "rawvideo", "-pix_fmt", fmt, "-s", f"{FW}x{FH}",
            "-r", "30", "-i", "-"] + (post or []) + ["-f", "null", "-"]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE,
                         bufsize=SZ[fmt] * 4)
    data = frames[fmt]
    t0 = time.perf_counter()
    try:
        for _ in range(n):
            p.stdin.write(data)
        p.stdin.close()
    except Exception as exc:
        print(f"{label:56s} write error {exc}")
    p.wait()
    el = time.perf_counter() - t0
    err = p.stderr.read().decode("utf-8", "ignore")[-250:]
    if p.returncode != 0:
        print(f"{label:56s} FAILED rc={p.returncode} {err.strip()[:200]}")
        return 0.0
    print(f"{label:56s} {n/el:8.1f} fps  {n*SZ[fmt]/el/1e6:7.1f} MB/s")
    return n / el


def best(frames, fmt, label, pre=None, post=None, reps=3):
    """CUDA/nvenc の初期化やGPU clockで1割以上振れるので最良値を採る。"""
    vals = [run(frames, fmt, label if i == reps - 1 else "  (warm)",
                pre, post) for i in range(reps)]
    return max(vals)


def main():
    f = make_frames()
    print(f"=== 出力投入 {FW}x{FH}  bgr24 {SZ['bgr24']/1e6:.2f}MB / "
          f"yuv420p {SZ['yuv420p']/1e6:.2f}MB per frame ===")
    print("(warm up)")
    run(f, "yuv420p", "  warmup", post=["-c:v", "hevc_nvenc", "-preset", "p5"])
    run(f, "bgr24", "  warmup", post=["-c:v", "hevc_nvenc", "-preset", "p5"])
    E7 = ["-c:v", "hevc_nvenc", "-preset", "p7", "-cq", "24"]
    E5 = ["-c:v", "hevc_nvenc", "-preset", "p5", "-cq", "24"]
    SPL = ["-split_encode_mode", "3"]

    print("-- 現行 --")
    best(f, "bgr24", "1 bgr24 + p7 (現行相当)", post=E7 + ["-pix_fmt", "yuv420p"])
    print("-- pixel format を減らす --")
    best(f, "yuv420p", "2 yuv420p + p7", post=E7)
    best(f, "nv12", "3 nv12 + p7", post=E7)
    best(f, "yuv420p", "4 yuv420p + p5", post=E5)
    best(f, "nv12", "5 nv12 + p5", post=E5)
    print("-- split_encode_mode --")
    best(f, "yuv420p", "6 yuv420p + p7 + split3", post=E7 + SPL)
    best(f, "yuv420p", "7 yuv420p + p5 + split3", post=E5 + SPL)
    best(f, "nv12", "8 nv12 + p5 + split3", post=E5 + SPL)
    best(f, "bgr24", "9 bgr24 + p5 + split3", post=E5 + SPL + ["-pix_fmt", "yuv420p"])
    print("-- 入力 block size / thread queue --")
    for bs in ("65536", "1048576", "4194304"):
        best(f, "yuv420p", f"10 yuv420p p7 -blocksize {bs}",
            pre=["-blocksize", bs], post=E7)
    best(f, "yuv420p", "11 yuv420p p7 -thread_queue_size 512",
        pre=["-thread_queue_size", "512"], post=E7)
    print("-- 天井 (encoder 無し) --")
    best(f, "bgr24", "12 bgr24 -> rawvideo null", post=["-c:v", "rawvideo"])
    best(f, "yuv420p", "13 yuv420p -> rawvideo null", post=["-c:v", "rawvideo"])
    best(f, "yuv420p", "14 yuv420p -> rawvideo null -blocksize 4M",
        pre=["-blocksize", "4194304"], post=["-c:v", "rawvideo"])
    print("-- GPU filter で色変換させる (bgr24投入のまま) --")
    best(f, "bgr24", "15 bgr24 + hwupload_cuda,scale_cuda + p7",
        post=["-vf", "format=bgr0,hwupload_cuda,scale_cuda=format=nv12"] + E7)




def main2():
    """現行 (nv12 pipe) を起点にした encoder option の比較。"""
    f = make_frames()
    print(f"=== nv12 pipe {FW}x{FH} を起点にした encode option ===")
    run(f, "nv12", "  warmup", post=["-c:v", "hevc_nvenc", "-preset", "p5"])
    Y = ["-pix_fmt", "yuv420p"]
    for label, post in [
        ("A 現行 nv12 + p7 + -pix_fmt yuv420p",
         ["-c:v", "hevc_nvenc", "-preset", "p7", "-cq", "24"] + Y),
        ("B nv12 + p7 (-pix_fmt 指定なし)",
         ["-c:v", "hevc_nvenc", "-preset", "p7", "-cq", "24"]),
        ("C nv12 + p7 + -pix_fmt nv12",
         ["-c:v", "hevc_nvenc", "-preset", "p7", "-cq", "24",
          "-pix_fmt", "nv12"]),
        ("D nv12 + p5 + -pix_fmt yuv420p",
         ["-c:v", "hevc_nvenc", "-preset", "p5", "-cq", "24"] + Y),
        ("E nv12 + p5 (指定なし)",
         ["-c:v", "hevc_nvenc", "-preset", "p5", "-cq", "24"]),
        ("F nv12 + p5 + split3 (指定なし)",
         ["-c:v", "hevc_nvenc", "-preset", "p5", "-cq", "24",
          "-split_encode_mode", "3"]),
        ("G nv12 + p6 + split3 (指定なし)",
         ["-c:v", "hevc_nvenc", "-preset", "p6", "-cq", "24",
          "-split_encode_mode", "3"]),
        ("H nv12 + p7 + split3 (指定なし)",
         ["-c:v", "hevc_nvenc", "-preset", "p7", "-cq", "24",
          "-split_encode_mode", "3"]),
        ("I nv12 + p4 + split3 (指定なし)",
         ["-c:v", "hevc_nvenc", "-preset", "p4", "-cq", "24",
          "-split_encode_mode", "3"]),
    ]:
        best(f, "nv12", label, post=post)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "n":
        N = int(sys.argv[2])
    (main2 if len(sys.argv)>1 and sys.argv[-1]=="2" else main)()
