"""decode と encode を GPU 上で完結できるか。PCIe 転送と pipe が消えるか測る。

現状は decode: ffmpeg --pipe--> CPU --H2D--> GPU、encode: GPU --D2H--> CPU
--pipe--> nvenc。往復で 1 frame あたり H2D 0.48ms + D2H 0.24ms + pipe の
CPU 費用が乗る。

試す手は2つ:
  ffmpeg -hwaccel cuda -hwaccel_output_format cuda
      … pipe で受け取る以上どこかで hwdownload が要る。GPU 上に置いたまま
        渡す口が無いので「使えるか」だけ見る
  PyNvVideoCodec
      … NVDEC/NVENC を直接叩く。device memory の surface を CUDA array
        interface で受け取れるので torch tensor に出来る

PyNvVideoCodec は import に失敗する(DLL が見つからない)。torch が同梱する
CUDA の DLL を探索path へ足せば通る。pip install は要らない。
"""
import os
import pathlib
import subprocess
import sys
import time

import numpy as np
import torch

import lib
import sgpu

os.add_dll_directory(str(pathlib.Path(torch.__file__).parent / "lib"))
import PyNvVideoCodec as nvc          # noqa: E402

W, H = lib.W, lib.H


def ffmpeg_nvdec(clip="B_talk"):
    """ffmpeg 側の NVDEC が素材を受け付けるか。速度も見る。"""
    src = str(lib.CLIPS[clip]["path"])
    t0 = time.time()
    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-hwaccel", "cuda",
         "-hwaccel_output_format", "cuda", "-i", src, "-f", "null", "-"],
        capture_output=True, text=True)
    dt = time.time() - t0
    n = len(lib.load(clip))
    if p.returncode != 0 or p.stderr.strip():
        return None, p.stderr.strip()[:250]
    return n / dt, ""


def ffmpeg_cpu_null(clip="B_talk"):
    """対照。CPU decode だけ(pipe も画素の取り出しも無し)。"""
    src = str(lib.CLIPS[clip]["path"])
    t0 = time.time()
    subprocess.run(["ffmpeg", "-v", "error", "-i", src, "-f", "null", "-"],
                   capture_output=True)
    return len(lib.load(clip)) / (time.time() - t0)


def pynv_decode(clip="B_talk", limit=400):
    """NVDEC で GPU memory へ decode し、torch tensor として受け取る。"""
    src = str(lib.CLIPS[clip]["path"])
    dmx = nvc.CreateDemuxer(filename=src)
    dec = nvc.CreateDecoder(gpuid=0, codec=dmx.GetNvCodecId(),
                            cudacontext=0, cudastream=0, usedevicememory=True)
    k = 0
    shapes = set()
    t0 = time.time()
    for pkt in dmx:
        for f in dec.Decode(pkt):
            t = torch.from_dlpack(f)          # GPU 上のまま
            shapes.add(tuple(t.shape))
            k += 1
            if k >= limit:
                break
        if k >= limit:
            break
    dt = time.time() - t0
    return k / dt, k, sorted(shapes)


def pipe_decode(clip="B_talk", limit=400):
    """対照。現状の pipe 経由(CPU pinned まで)。"""
    src = str(lib.CLIPS[clip]["path"])
    p = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", src, "-fps_mode", "passthrough",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE)
    pool = [torch.empty((H, W, 3), dtype=torch.uint8, pin_memory=True)
            for _ in range(8)]
    views = [b.numpy() for b in pool]
    dev = torch.empty((H, W, 3), dtype=torch.uint8, device="cuda")
    k = 0
    t0 = time.time()
    while k < limit:
        if p.stdout.readinto(memoryview(views[k % 8].reshape(-1))) < W * H * 3:
            break
        dev.copy_(pool[k % 8], non_blocking=True)
        k += 1
    torch.cuda.synchronize()
    dt = time.time() - t0
    p.kill()
    p.wait()
    return k / dt


def pynv_encode(frames=400, preset="P4", codec="hevc"):
    """GPU 上の nv12 を NVENC へ直接渡す。D2H も pipe も通らない。"""
    enc = nvc.CreateEncoder(width=W, height=H, fmt="NV12", usecpuinputbuffer=False,
                            codec=codec, preset=preset)
    buf = torch.randint(0, 255, (H * 3 // 2, W), dtype=torch.uint8, device="cuda")
    nbytes = 0
    t0 = time.time()
    for _ in range(frames):
        bs = enc.Encode(buf)
        nbytes += len(bs)
    nbytes += len(enc.EndEncode())
    dt = time.time() - t0
    return frames / dt, nbytes


def pipe_encode(frames=400, args="-preset p4 -cq 24"):
    """対照。現状の GPU -> D2H -> pipe -> nvenc。"""
    dev = torch.randint(0, 255, (H * 3 // 2, W), dtype=torch.uint8, device="cuda")
    pin = torch.empty((H * 3 // 2, W), dtype=torch.uint8, pin_memory=True)
    arr = pin.numpy()
    p = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "nv12",
         "-s", f"{W}x{H}", "-r", "48000/1001", "-i", "-", "-c:v", "hevc_nvenc"]
        + args.split() + ["-pix_fmt", "yuv420p", "-f", "null", "-"],
        stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    t0 = time.time()
    for _ in range(frames):
        pin.copy_(dev)
        p.stdin.write(arr)
    p.stdin.close()
    p.wait()
    return frames / (time.time() - t0)


def run():
    r = {}
    with sgpu.measuring("speed") as env:
        try:
            fps, err = ffmpeg_nvdec()
            r["ffmpeg_nvdec_fps"] = None if fps is None else round(fps, 1)
            r["ffmpeg_nvdec_error"] = err or None
        except Exception as exc:
            r["ffmpeg_nvdec_error"] = str(exc)[:200]
        r["ffmpeg_cpu_null_fps"] = round(ffmpeg_cpu_null(), 1)
        try:
            fps, k, shapes = pynv_decode()
            r["pynv_decode_fps"] = round(fps, 1)
            r["pynv_decode_frames"] = k
            r["pynv_decode_shape"] = str(shapes)
        except Exception as exc:
            r["pynv_decode_error"] = str(exc)[:250]
        r["pipe_decode_h2d_fps"] = round(pipe_decode(), 1)
        try:
            fps, nbytes = pynv_encode()
            r["pynv_encode_fps"] = round(fps, 1)
            r["pynv_encode_bytes"] = nbytes
        except Exception as exc:
            r["pynv_encode_error"] = str(exc)[:250]
        r["pipe_encode_d2h_fps"] = round(pipe_encode(), 1)
    r.update(env)
    lib.record("gpuio", r)
    for k, v in r.items():
        lib.log(f"  {k}: {v}")


if __name__ == "__main__":
    run()
