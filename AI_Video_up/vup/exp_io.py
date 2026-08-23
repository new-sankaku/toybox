"""exp_io - decode/pipe/encode 経路の基礎値を測る (vup.py は触らない)

  python exp_io.py dec        decode 経路の比較
  python exp_io.py enc        encode 経路の比較
  python exp_io.py pipe       pipe 単体の throughput
"""
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC60 = HERE.parent / "テスト60秒.mp4"
SRC = HERE.parent / "サンプル.mp4"
W, H = 720, 480


def drain(cmd, framebytes, label, limit_frames=None):
    """ffmpeg の stdout を rawvideo として読み捨て、frame/s と MB/s を返す。"""
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         bufsize=framebytes * 8)
    buf = bytearray(framebytes)
    mv = memoryview(buf)
    n = 0
    t0 = time.perf_counter()
    while True:
        got = 0
        while got < framebytes:
            r = p.stdout.readinto(mv[got:])
            if not r:
                break
            got += r
        if got < framebytes:
            break
        n += 1
        if limit_frames and n >= limit_frames:
            break
    el = time.perf_counter() - t0
    try:
        p.stdout.close()
        p.terminate()
    except Exception:
        pass
    err = p.stderr.read().decode("utf-8", "ignore")[-400:]
    p.wait()
    fps = n / el if el else 0
    mbs = n * framebytes / el / 1e6 if el else 0
    print(f"{label:52s} {n:6d}f {el:7.2f}s {fps:8.1f} fps {mbs:8.1f} MB/s")
    if err.strip() and "Error" in err:
        print(f"    stderr: {err.strip()[:300]}")
    return fps


def timed(cmd, label, nframes):
    t0 = time.perf_counter()
    r = subprocess.run(cmd, capture_output=True)
    el = time.perf_counter() - t0
    if r.returncode != 0:
        print(f"{label:52s} FAILED: "
              f"{r.stderr.decode('utf-8', 'ignore')[-300:]}")
        return 0
    print(f"{label:52s} {nframes:6d}f {el:7.2f}s {nframes/el:8.1f} fps")
    return nframes / el


def bench_dec(src, nframes):
    print(f"\n=== decode: {src.name} ({W}x{H}) ===")
    base = ["ffmpeg", "-v", "error", "-y"]
    px = {"bgr24": W * H * 3, "yuv420p": W * H * 3 // 2,
          "nv12": W * H * 3 // 2, "gray": W * H, "rgb24": W * H * 3}

    timed(base + ["-i", str(src), "-f", "null", "-"],
          "A decode only (-f null)", nframes)
    timed(base + ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
                  "-i", str(src), "-f", "null", "-"],
          "B NVDEC decode only (-f null)", nframes)
    timed(base + ["-c:v", "h264_cuvid", "-i", str(src), "-f", "null", "-"],
          "C h264_cuvid decode only (-f null)", nframes)

    for fmt in ("bgr24", "yuv420p", "nv12"):
        drain(base + ["-i", str(src), "-f", "rawvideo", "-pix_fmt", fmt, "-"],
              px[fmt], f"D CPU decode -> pipe {fmt}")

    for fmt in ("bgr24", "nv12"):
        drain(base + ["-hwaccel", "cuda", "-i", str(src),
                      "-f", "rawvideo", "-pix_fmt", fmt, "-"],
              px[fmt], f"E NVDEC(auto download) -> pipe {fmt}")

    drain(base + ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
                  "-i", str(src), "-vf", "hwdownload,format=nv12",
                  "-f", "rawvideo", "-pix_fmt", "nv12", "-"],
          px["nv12"], "F NVDEC+hwdownload -> pipe nv12")

    drain(base + ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
                  "-i", str(src), "-vf", "scale_cuda=format=bgr0,hwdownload,"
                  "format=bgr0,format=bgr24",
                  "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
          px["bgr24"], "G NVDEC+scale_cuda bgr0 -> pipe bgr24")

    for th in ("1", "2", "4", "8"):
        drain(base + ["-threads", th, "-i", str(src),
                      "-f", "rawvideo", "-pix_fmt", "yuv420p", "-"],
              px["yuv420p"], f"H CPU decode -threads {th} -> pipe yuv420p")

    drain(base + ["-i", str(src), "-f", "nut", "-pix_fmt", "yuv420p", "-"],
          px["yuv420p"], "I CPU decode -> nut yuv420p (frame数は概算)")


def bench_enc(nframes=600, fw=1440, fh=960):
    print(f"\n=== encode: {fw}x{fh} rawvideo 投入 -> null ===")
    import numpy as np
    sizes = {"bgr24": fw * fh * 3, "yuv420p": fw * fh * 3 // 2,
             "nv12": fw * fh * 3 // 2}
    frames = {}
    rng = np.random.default_rng(0)
    # 実素材に近い絵を作る (乱数はencodeの最悪値になる)
    base = rng.integers(0, 255, (fh, fw, 3), dtype=np.uint8)
    import cv2
    base = cv2.GaussianBlur(base, (0, 0), 3)
    for k, sz in sizes.items():
        if k == "bgr24":
            frames[k] = base.tobytes()
        else:
            yuv = cv2.cvtColor(base, cv2.COLOR_BGR2YUV_I420)
            frames[k] = yuv.tobytes()
    assert len(frames["yuv420p"]) == sizes["yuv420p"]

    def run(fmt, enc, eargs, label):
        cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo",
               "-pix_fmt", fmt, "-s", f"{fw}x{fh}", "-r", "30",
               "-i", "-", "-c:v", enc] + eargs + ["-f", "null", "-"]
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                             stderr=subprocess.PIPE,
                             bufsize=sizes[fmt] * 4)
        data = frames[fmt]
        t0 = time.perf_counter()
        try:
            for _ in range(nframes):
                p.stdin.write(data)
            p.stdin.close()
        except Exception as exc:
            print(f"{label:52s} write failed {exc}")
        p.wait()
        el = time.perf_counter() - t0
        err = p.stderr.read().decode("utf-8", "ignore")[-300:]
        mbs = nframes * sizes[fmt] / el / 1e6
        print(f"{label:52s} {nframes:6d}f {el:7.2f}s "
              f"{nframes/el:8.1f} fps {mbs:8.1f} MB/s")
        if p.returncode != 0:
            print(f"    rc={p.returncode} {err.strip()[:250]}")

    run("bgr24", "hevc_nvenc", ["-preset", "p7", "-cq", "24",
                                "-pix_fmt", "yuv420p"], "J bgr24 -> hevc_nvenc p7")
    run("bgr24", "hevc_nvenc", ["-preset", "p5", "-cq", "24",
                                "-pix_fmt", "yuv420p"], "K bgr24 -> hevc_nvenc p5")
    run("bgr24", "hevc_nvenc", ["-preset", "p1", "-cq", "24",
                                "-pix_fmt", "yuv420p"], "L bgr24 -> hevc_nvenc p1")
    run("yuv420p", "hevc_nvenc", ["-preset", "p7", "-cq", "24"],
        "M yuv420p -> hevc_nvenc p7")
    run("yuv420p", "hevc_nvenc", ["-preset", "p5", "-cq", "24"],
        "N yuv420p -> hevc_nvenc p5")
    run("nv12", "hevc_nvenc", ["-preset", "p7", "-cq", "24"],
        "O nv12 -> hevc_nvenc p7")
    run("nv12", "hevc_nvenc", ["-preset", "p5", "-cq", "24"],
        "P nv12 -> hevc_nvenc p5")
    run("bgr24", "rawvideo", ["-f", "null"][:0] or [], "Q bgr24 -> null encoder (pipe天井)")
    run("yuv420p", "rawvideo", [], "R yuv420p -> null encoder (pipe天井)")
    run("nv12", "rawvideo", [], "S nv12 -> null encoder (pipe天井)")


def bench_pipe(mb=2000):
    print(f"\n=== pipe throughput ({mb} MB) ===")
    chunks = [1 << 16, 1 << 18, 1 << 20, 1 << 22, 4147200]
    prod = (
        "import sys,os\n"
        "n=int(sys.argv[1]); c=int(sys.argv[2])\n"
        "b=b'x'*c\n"
        "w=sys.stdout.buffer\n"
        "tot=0\n"
        "while tot<n:\n"
        "    w.write(b); tot+=c\n"
        "w.flush()\n")
    for c in chunks:
        total = mb * 1_000_000
        p = subprocess.Popen([sys.executable, "-c", prod, str(total), str(c)],
                             stdout=subprocess.PIPE, bufsize=c)
        buf = bytearray(c)
        mv = memoryview(buf)
        got = 0
        t0 = time.perf_counter()
        while True:
            r = p.stdout.readinto(mv)
            if not r:
                break
            got += r
        el = time.perf_counter() - t0
        p.wait()
        print(f"  chunk {c:>9d} B: {got/1e6:8.1f} MB {el:6.2f}s "
              f"{got/el/1e6:8.1f} MB/s")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "dec"
    if what == "dec":
        bench_dec(SRC60, 1567)
    elif what == "dec_full":
        bench_dec(SRC, 24279)
    elif what == "enc":
        bench_enc()
    elif what == "pipe":
        bench_pipe()
