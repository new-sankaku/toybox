"""exp_nv12 - SR 出力 (GPU上のRGB) -> NV12 変換を GPU で行うコスト。

pipe へ流す bytes を 3 -> 1.5 bytes/px に半減できるが、変換は SR と同じ
GPU を使う。SR が現状の bottleneck なので、変換が SR 時間に対して
無視できる大きさかどうかが採否を決める。
"""
import time

import torch
import torch.nn.functional as F

FW, FH = 1440, 960
N = 500

# BT.709 limited range (video range) の RGB -> YUV
M709 = torch.tensor([[0.18258588, 0.61423059, 0.06200706],
                     [-0.10064373, -0.33857195, 0.43921569],
                     [0.43921569, -0.39894216, -0.04027352]])
OFF = torch.tensor([16.0, 128.0, 128.0])


def bench(fn, label, warm=30, n=N):
    x = torch.rand((1, 3, FH, FW), device="cuda", dtype=torch.half)
    for _ in range(warm):
        fn(x)
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    for _ in range(n):
        fn(x)
    torch.cuda.synchronize()
    el = time.perf_counter() - t0
    print(f"{label:44s} {el/n*1000:7.3f} ms/frame  {n/el:8.1f} fps")
    return el / n * 1000


def make_naive(dtype):
    m = M709.to("cuda", dtype)
    off = OFF.to("cuda", dtype).view(1, 3, 1, 1)

    def f(x):
        x = x.to(dtype)
        yuv = torch.einsum("ij,bjhw->bihw", m, x) * 255.0 + off
        yuv = yuv.clamp_(0, 255)
        y = yuv[:, 0].to(torch.uint8)
        uvp = F.avg_pool2d(yuv[:, 1:], 2)
        uv = torch.stack([uvp[:, 0], uvp[:, 1]], -1).reshape(1, FH // 2, FW)
        return y.reshape(-1), uv.to(torch.uint8).reshape(-1)
    return f


def make_conv(dtype):
    """1x1 conv 一発で YUV を作り、UV は stride 2 の conv で同時に間引く。"""
    w = M709.to("cuda", dtype).view(3, 3, 1, 1)
    b = OFF.to("cuda", dtype) / 255.0

    def f(x):
        yuv = F.conv2d(x.to(dtype), w, b).mul_(255.0).clamp_(0, 255)
        y = yuv[:, :1]
        uv = F.avg_pool2d(yuv[:, 1:], 2)
        out = torch.empty(FH * FW * 3 // 2, dtype=torch.uint8, device="cuda")
        out[:FH * FW] = y.reshape(-1).to(torch.uint8)
        uvi = uv.to(torch.uint8).squeeze(0)          # (2, H/2, W/2)
        out[FH * FW:] = uvi.permute(1, 2, 0).reshape(-1)
        return out
    return f


def make_fused(dtype):
    """出力 buffer を使い回し、interleave を1回の permute で済ませる。"""
    w = M709.to("cuda", dtype).view(3, 3, 1, 1)
    b = OFF.to("cuda", dtype) / 255.0
    out = torch.empty(FH * FW * 3 // 2, dtype=torch.uint8, device="cuda")
    yv = out[:FH * FW].view(FH, FW)
    uvv = out[FH * FW:].view(FH // 2, FW // 2, 2)

    def f(x):
        yuv = F.conv2d(x.to(dtype), w, b).mul_(255.0).clamp_(0, 255)
        yv.copy_(yuv[0, 0])
        uvv.copy_(F.avg_pool2d(yuv[:, 1:], 2)[0].permute(1, 2, 0))
        return out
    return f


if __name__ == "__main__":
    print(f"=== {FW}x{FH} RGB(fp16, GPU) -> NV12(GPU) ===")
    bench(make_naive(torch.half), "naive einsum fp16")
    bench(make_conv(torch.half), "1x1 conv fp16 (毎回alloc)")
    f_fused = make_fused(torch.half)
    bench(f_fused, "1x1 conv fp16 + buffer使い回し")
    try:
        cf = torch.compile(make_fused(torch.half))
        bench(cf, "同上 + torch.compile", warm=60)
    except Exception as exc:
        print("torch.compile NG", type(exc).__name__, exc)

    print("\n=== 比較: 現行の RGB->uint8 整形 + D2H ===")
    x = torch.rand((1, 3, FH, FW), device="cuda", dtype=torch.half)
    pin3 = torch.empty((FH, FW, 3), dtype=torch.uint8, device="cpu",
                       pin_memory=True)
    pin15 = torch.empty(FH * FW * 3 // 2, dtype=torch.uint8, device="cpu",
                        pin_memory=True)

    def cur(x):
        y = x.mul(255.0).clamp_(0, 255).round_().to(torch.uint8)
        y = y.squeeze(0).permute(1, 2, 0).contiguous()
        pin3.copy_(y, non_blocking=False)
        return pin3
    bench(cur, "現行: bgr24 整形 + D2H 4.15MB")

    def nv(x):
        o = f_fused(x)
        pin15.copy_(o, non_blocking=False)
        return pin15
    bench(nv, "新: NV12 変換 + D2H 2.07MB")
