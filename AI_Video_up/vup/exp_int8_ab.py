"""fp16 engine と int8 engine を同一process内で交互に測り、画質も比べる。"""
import sys
import time
from pathlib import Path

import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from models_registry import load_model, resolve  # noqa: E402
from exp_trt import TrtRunner, build_engine, export_onnx, OUT  # noqa: E402
from srlib import grab_frames, to_gpu, psnr  # noqa: E402

fp16 = TrtRunner(build_engine(export_onnx("sd", 1, half=True), "fp16", 1))
int8 = TrtRunner(build_engine(OUT / "sd_b1_fp32.int8.onnx", "int8", 1))


def burst(r, n=20):
    s = r.stream.cuda_stream
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    for _ in range(n):
        r.ctx.execute_async_v3(s)
    r.stream.synchronize()
    return (time.perf_counter() - t0) / n


for _ in range(30):
    burst(fp16, 5); burst(int8, 5)
a, b = [], []
for _ in range(30):
    a.append(burst(fp16)); b.append(burst(int8))
a.sort(); b.sort()
print(f"TRT fp16 bs=1: best {1/a[0]:7.1f} fps  med {1/a[len(a)//2]:7.1f} fps")
print(f"TRT int8 bs=1: best {1/b[0]:7.1f} fps  med {1/b[len(b)//2]:7.1f} fps")
print(f"  int8/fp16 = {a[0]/b[0]:.2f}x")

fr = grab_frames(HERE.parent / "サンプル.mp4", 12)
x = to_gpu(fr)
m32, _, _ = load_model(resolve("sd"), device="cuda", half=False)
res = {"fp16": [], "int8": []}
for i in range(len(fr)):
    xi = x[i:i + 1]
    with torch.no_grad():
        ref = m32(xi).clamp(0, 1).mul(255).round()
    for tag, r in (("fp16", fp16), ("int8", int8)):
        dt = r.buf[r.inp[0]].dtype
        y = r(xi.to(dt)).float().clamp(0, 1).mul(255).round()
        res[tag].append((psnr(ref, y), (ref - y).abs().max().item()))
for tag in ("fp16", "int8"):
    v = res[tag]
    print(f"  TRT {tag}: PSNR最小 {min(p for p,_ in v):6.2f} dB  "
          f"平均 {sum(p for p,_ in v)/len(v):6.2f} dB  "
          f"画素差max {max(m for _,m in v):5.1f}/255")
