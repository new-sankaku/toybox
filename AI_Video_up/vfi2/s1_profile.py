"""現状の内訳を測る。stage を1つずつ切り離して天井を出す。

wall time で測ると、GPU の待ちが「その時 .item() を呼んだ場所」へ全部乗る
(旧 a8_e2e では gate と w_sync に model の待ちが吸われていた)。
GPU 側は CUDA event、CPU 側(pipe 読み書き)は wall time で測る。

各 stage を「1 frame あたり何 ms か」まで揃えると、clip ごとの呼び出し回数を
掛けるだけで内訳の表が作れる。
"""
import subprocess
import sys
import time

import numpy as np
import torch
import torch.nn.functional as F

import lib
import sgpu
import rifelib as R

W, H = lib.W, lib.H
NBYTES = W * H * 3


def gpu_ms(fn, iters=40, warm=10):
    """CUDA event で fn 1回あたりの ms。毎回 synchronize しない。"""
    for _ in range(warm):
        fn()
    torch.cuda.synchronize()
    e0 = [torch.cuda.Event(enable_timing=True) for _ in range(iters)]
    e1 = [torch.cuda.Event(enable_timing=True) for _ in range(iters)]
    for k in range(iters):
        e0[k].record()
        fn()
        e1[k].record()
    torch.cuda.synchronize()
    # 他 process の干渉は必ず「遅くする」向きにしか働かない。median だと
    # 干渉が値へ残るので min を採る。
    return float(min(a.elapsed_time(b) for a, b in zip(e0, e1)))


# ------------------------------------------------------------ 各 stage

def stage_decode(clip, limit=400):
    """ffmpeg rawvideo を pipe で pinned へ読む。bufsize は渡さない。"""
    src = str(lib.CLIPS[clip]["path"])
    p = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", src, "-fps_mode", "passthrough",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE)
    pool = [torch.empty((H, W, 3), dtype=torch.uint8, pin_memory=True)
            for _ in range(8)]
    views = [b.numpy() for b in pool]
    k = 0
    t0 = time.time()
    while k < limit:
        if p.stdout.readinto(memoryview(views[k % 8].reshape(-1))) < NBYTES:
            break
        k += 1
    dt = time.time() - t0
    p.kill()
    p.wait()
    return k / dt


def stage_h2d():
    pin = torch.empty((H, W, 3), dtype=torch.uint8, pin_memory=True)
    dev = torch.empty((H, W, 3), dtype=torch.uint8, device="cuda")
    return gpu_ms(lambda: dev.copy_(pin, non_blocking=True))


def stage_gate():
    """旧 a8_e2e の gate_metrics。box4 と平均絶対差。"""
    a = torch.randint(0, 255, (H, W, 3), dtype=torch.uint8, device="cuda")
    b = torch.randint(0, 255, (H, W, 3), dtype=torch.uint8, device="cuda")

    def f():
        d = (b.half() - a.half()).abs_()
        F.avg_pool2d(d.permute(2, 0, 1).unsqueeze(0), 4).amax()
        d.mean()

    return gpu_ms(f)


def stage_pack(m):
    a = torch.randint(0, 255, (H, W, 3), dtype=torch.uint8, device="cuda")
    b = torch.randint(0, 255, (H, W, 3), dtype=torch.uint8, device="cuda")
    return gpu_ms(lambda: R.pack(a, b, 0.5, m.dtype, out=m.dev_in))


def stage_infer(m):
    return gpu_ms(lambda: m.infer()) / m.bs


def nv12(bgr_u8):
    x = bgr_u8.permute(2, 0, 1).float().div_(255.0).unsqueeze(0)
    b, g, r = x[:, 0:1], x[:, 1:2], x[:, 2:3]
    luma = 0.299 * r + 0.587 * g + 0.114 * b
    u = (b - luma) * (0.5 / (1 - 0.114))
    v = (r - luma) * (0.5 / (1 - 0.299))
    y = (luma * 219.0 + 16.0)[:, 0]
    u = F.avg_pool2d(u, 2) * 224.0 + 128.0
    v = F.avg_pool2d(v, 2) * 224.0 + 128.0
    uv = torch.stack((u, v), dim=-1)
    uv = uv.reshape(uv.shape[0], uv.shape[2], -1)
    return torch.cat((y, uv), dim=1).clamp_(0, 255).round_().to(torch.uint8)[0]


def stage_unpack(m):
    y = torch.rand((1, 3, H, W), dtype=m.dtype, device="cuda")
    return gpu_ms(lambda: R.unpack(y))


def stage_nv12():
    x = torch.randint(0, 255, (H, W, 3), dtype=torch.uint8, device="cuda")
    return gpu_ms(lambda: nv12(x))


def stage_d2h():
    dev = torch.empty((H * 3 // 2, W), dtype=torch.uint8, device="cuda")
    pin = torch.empty((H * 3 // 2, W), dtype=torch.uint8, pin_memory=True)
    return gpu_ms(lambda: pin.copy_(dev, non_blocking=True))


def stage_encode(args="-preset p4 -cq 24", frames=400, encoder="hevc_nvenc"):
    buf = np.random.randint(0, 255, W * H * 3 // 2, dtype=np.uint8).tobytes()
    p = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "nv12",
         "-s", f"{W}x{H}", "-r", "48000/1001", "-i", "-", "-c:v", encoder]
        + args.split() + ["-pix_fmt", "yuv420p", "-f", "null", "-"],
        stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    t0 = time.time()
    for _ in range(frames):
        p.stdin.write(buf)
    p.stdin.close()
    p.wait()
    return frames / (time.time() - t0)


# ------------------------------------------------------------ 実行

def run(model="v4.6"):
    m = R.Rife(model, W, H, bs=1, fp16=True)          # build は lock の外
    torch.cuda.synchronize()

    with sgpu.measuring() as env:
        res = dict(
            decode_fps=round(stage_decode("B_talk"), 1),
            h2d_ms=round(stage_h2d(), 3),
            gate_ms=round(stage_gate(), 3),
            pack_ms=round(stage_pack(m), 3),
            infer_ms=round(stage_infer(m), 3),
            unpack_ms=round(stage_unpack(m), 3),
            nv12_ms=round(stage_nv12(), 3),
            d2h_ms=round(stage_d2h(), 3),
            encode_p4_fps=round(stage_encode(), 1),
            encode_p1_fps=round(stage_encode("-preset p1 -cq 24"), 1),
            encode_p4_split_fps=round(
                stage_encode("-preset p4 -cq 24 -split_encode_mode 3"), 1),
        )
    res.update(model=model, w=W, h=H, **env)
    lib.record("stage", res)
    for k, v in res.items():
        lib.log(f"  {k}: {v}")
    return res


if __name__ == "__main__":
    lib.log("=== stage ごとの天井")
    run(sys.argv[1] if len(sys.argv) > 1 else "v4.6")
