"""出力側の天井を測る。model より先にここが詰まる可能性が高い。

x2 にすると出力frame数が倍になる。vup の実測で「出力側が律速に回った」と
書いた状態から更に倍なので、**encoder が何fps書けるか**が全体の上限を決める。

3つ測る:
  1. encoder 単体   … rawvideo を pipe へ流し込むだけ。SR も VFI もしない
  2. pipe の帯域    … 同じ物を NUL へ捨てて、pipe 側の限界を分離する
  3. preset の効き  … vup で x4 出力が p7->p4 で1.77倍になった件の1080p版
"""
import subprocess
import sys
import time

import numpy as np

import vfilib as V

W, H = V.W, V.H
FRAMES = 600


def bench(encoder, args, pix="nv12", w=W, h=H, frames=FRAMES, dst=None):
    nbytes = w * h * (3 if pix == "bgr24" else 3 // 2 if False else 0)
    nbytes = w * h * 3 if pix == "bgr24" else w * h * 3 // 2
    buf = np.random.randint(0, 255, nbytes, dtype=np.uint8).tobytes()
    out = ["-f", "null", "-"] if dst is None else [str(dst)]
    cmd = (["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", pix,
            "-s", f"{w}x{h}", "-r", "48000/1001", "-i", "-"]
           + (["-c:v", encoder] + args.split() if encoder else ["-c:v", "rawvideo"])
           + ["-pix_fmt", "yuv420p"] + out)
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    t0 = time.time()
    try:
        for _ in range(frames):
            p.stdin.write(buf)
        p.stdin.close()
    except BrokenPipeError:
        pass
    err = p.stderr.read().decode("utf-8", "replace")
    p.wait()
    dt = time.time() - t0
    if p.returncode != 0:
        return None, err[:300]
    return frames / dt, ""


def pipe_only(w=W, h=H, frames=FRAMES, pix="nv12"):
    """encoder を挟まず、同じ量を捨てるだけ。pipe 側の限界。"""
    nbytes = w * h * 3 if pix == "bgr24" else w * h * 3 // 2
    buf = np.random.randint(0, 255, nbytes, dtype=np.uint8).tobytes()
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo",
                          "-pix_fmt", pix, "-s", f"{w}x{h}", "-i", "-",
                          "-f", "null", "-c:v", "rawvideo", "-"],
                         stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    t0 = time.time()
    for _ in range(frames):
        p.stdin.write(buf)
    p.stdin.close()
    p.wait()
    return frames / (time.time() - t0)


CASES = [
    ("hevc_nvenc", "-preset p1 -cq 24"),
    ("hevc_nvenc", "-preset p4 -cq 24"),
    ("hevc_nvenc", "-preset p7 -cq 24"),
    ("h264_nvenc", "-preset p4 -cq 24"),
    ("hevc_nvenc", "-preset p4 -cq 24 -split_encode_mode 3"),
]


def run():
    fps = pipe_only()
    V.record("encoder", dict(case="pipe_only", pix="nv12", w=W, h=H,
                             fps=round(fps, 1)))
    print(f"  pipeだけ(encodeなし) nv12 1920x1080: {fps:.1f} fps")
    fps = pipe_only(pix="bgr24")
    V.record("encoder", dict(case="pipe_only", pix="bgr24", w=W, h=H,
                             fps=round(fps, 1)))
    print(f"  pipeだけ(encodeなし) bgr24 1920x1080: {fps:.1f} fps")

    for enc, args in CASES:
        fps, err = bench(enc, args)
        if fps is None:
            V.record("encoder", dict(case=f"{enc} {args}", error=err))
            print(f"  {enc} {args}: 失敗 {err[:120]}")
            continue
        V.record("encoder", dict(case=f"{enc} {args}", pix="nv12", w=W, h=H,
                                 fps=round(fps, 1), frames=FRAMES))
        print(f"  {enc} {args}: {fps:.1f} fps")

    # 4K(x2 SR を掛けた場合の出力)も見ておく
    for enc, args in (("hevc_nvenc", "-preset p1 -cq 24"),
                      ("hevc_nvenc", "-preset p4 -cq 24"),
                      ("hevc_nvenc", "-preset p7 -cq 24")):
        fps, err = bench(enc, args, w=3840, h=2160, frames=200)
        if fps is None:
            continue
        V.record("encoder", dict(case=f"{enc} {args}", pix="nv12",
                                 w=3840, h=2160, fps=round(fps, 1)))
        print(f"  3840x2160 {enc} {args}: {fps:.1f} fps")


if __name__ == "__main__":
    V.log("=== 出力側の天井")
    run()
