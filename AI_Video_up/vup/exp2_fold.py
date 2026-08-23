"""x4 model で x2 出力するとき、最終 conv に縮小を畳み込む。

現行は  model(x) -> pixel_shuffle(4) -> clamp -> avg_pool2d(2)  で、
2880x1920 の tensor を作ってから半分に捨てている。

SRVGGNetCompact の最終 conv は 64ch -> 3*4*4=48ch で、body の
64->64 conv 16本と比べても計算量の3割を占める。
avg_pool2d は線形なので pixel_shuffle の前に移せる:

  avg_pool2d(pixel_shuffle(conv(x,W), 4), 2) == pixel_shuffle(conv(x,W'), 2)
  W'[c*4 + p*2 + q] = mean_{u,v in {0,1}} W[c*16 + (2p+u)*4 + (2q+v)]

skip 接続の nearest 補間も avg_pool2d(nearest_x4(x), 2) == nearest_x2(x) で一致する。
つまり **出力は数学的に同一**のまま、最終 conv の出力 ch が 48 -> 12 に減り、
2880x1920 の中間 tensor が丸ごと消える。

clamp の位置だけが変わる(現行は平均の前、畳み込み後は平均の後)ので、
実際の差を画素で測る。
"""
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from models_registry import resolve  # noqa: E402
from srvgg import SRVGGNetCompact  # noqa: E402

W, H = 720, 480


def build(path, out_scale, device="cuda", half=True):
    sd = torch.load(path, map_location="cpu")
    sd = sd.get("params", sd)
    keys = [k for k in sd if k.startswith("body") and k.endswith(".weight")
            and sd[k].dim() == 4]
    last_w = max(keys, key=lambda k: int(k.split(".")[1]))
    last_b = last_w[:-6] + "bias"
    up = int((sd[last_w].shape[0] // 3) ** 0.5)
    n_conv = len(keys) - 2
    feat = sd["body.0.weight"].shape[0]

    plain = SRVGGNetCompact(num_feat=feat, num_conv=n_conv, upscale=up)
    plain.load_state_dict(sd, strict=True)

    fold = None
    if out_scale and out_scale < up and up % out_scale == 0:
        r = up // out_scale                      # 縮小率
        s = out_scale
        wv = sd[last_w].reshape(3, up, up, feat, 3, 3)
        bv = sd[last_b].reshape(3, up, up)
        # (a,b) を (p,q) x (u,v) へ分解して u,v で平均する
        wv = wv.reshape(3, s, r, s, r, feat, 3, 3).mean(dim=(2, 4))
        bv = bv.reshape(3, s, r, s, r).mean(dim=(2, 4))
        fold = SRVGGNetCompact(num_feat=feat, num_conv=n_conv, upscale=s)
        nsd = {k: v for k, v in sd.items() if k not in (last_w, last_b)}
        nsd[last_w] = wv.reshape(3 * s * s, feat, 3, 3).contiguous()
        nsd[last_b] = bv.reshape(3 * s * s).contiguous()
        fold.load_state_dict(nsd, strict=True)

    out = []
    for m in (plain, fold):
        if m is None:
            out.append(None)
            continue
        m.eval().to(device)
        if half:
            m.half()
        out.append(m.to(memory_format=torch.channels_last))
    return out[0], out[1], up


def run_plain(m, x, up, out_scale):
    y = m(x).clamp_(0, 1)
    if up != out_scale:
        y = F.avg_pool2d(y, up // out_scale)
    return y.mul_(255.0).round_().to(torch.uint8)


def run_fold(m, x):
    return m(x).clamp_(0, 1).mul_(255.0).round_().to(torch.uint8)


def bench(fn, n=30, warm=10):
    for _ in range(warm):
        fn()
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    for _ in range(n):
        fn()
    torch.cuda.synchronize()
    return n / (time.perf_counter() - t0)


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "anime"
    out_scale = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    use_compile = "--no-compile" not in sys.argv
    torch.backends.cudnn.benchmark = True
    plain, fold, up = build(resolve(name), out_scale)
    if fold is None:
        print(f"{name}: model x{up} -> 出力 x{out_scale} は畳み込めません")
        return
    print(f"{name}: model x{up} -> 出力 x{out_scale}  入力 {W}x{H}")

    torch.manual_seed(0)
    x = torch.rand(1, 3, H, W, device="cuda", dtype=torch.half)
    x = x.contiguous(memory_format=torch.channels_last)
    with torch.no_grad():
        a = run_plain(plain, x, up, out_scale).float()
        b = run_fold(fold, x).float()
        d = (a - b).abs()
        print(f"出力の差 (uint8): 最大 {d.max().item():.0f}  平均 {d.mean().item():.4f}"
              f"  差のある画素 {(d > 0).float().mean().item() * 100:.3f}%")

    if use_compile:
        try:
            import triton  # noqa: F401
            plain = torch.compile(plain)
            fold = torch.compile(fold)
            tag = "compile"
        except Exception:
            tag = "eager"
    else:
        tag = "eager"
    with torch.no_grad():
        f1 = bench(lambda: run_plain(plain, x, up, out_scale))
        f2 = bench(lambda: run_fold(fold, x))
    print(f"{tag}:  現行 {f1:.1f} fps  ->  畳み込み {f2:.1f} fps  "
          f"({f2 / f1:.2f}倍)")

    # FLOP の内訳(3x3 conv のみ、掛け算+足し算で2)
    px = W * H
    feat = plain._orig_mod.body[0].weight.shape[0] if hasattr(plain, "_orig_mod") \
        else plain.body[0].weight.shape[0]
    n_body = (len([m for m in (plain._orig_mod if hasattr(plain, "_orig_mod")
                               else plain).body
                   if isinstance(m, torch.nn.Conv2d)]) - 2)
    g_body = n_body * px * feat * feat * 9 * 2 / 1e9
    g_in = px * 3 * feat * 9 * 2 / 1e9
    g_last = px * feat * (3 * up * up) * 9 * 2 / 1e9
    g_last_f = px * feat * (3 * out_scale * out_scale) * 9 * 2 / 1e9
    print(f"FLOP: 入口 {g_in:.1f}G  body {g_body:.1f}G  "
          f"最終conv {g_last:.1f}G -> {g_last_f:.1f}G")
    print(f"      合計 {g_in + g_body + g_last:.1f}G -> "
          f"{g_in + g_body + g_last_f:.1f}G "
          f"({(g_in + g_body + g_last_f) / (g_in + g_body + g_last):.2f}倍)")


if __name__ == "__main__":
    main()
