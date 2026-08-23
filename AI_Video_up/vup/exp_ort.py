"""ONNX Runtime (CUDA EP / TensorRT EP) を同じ ONNX で測る。

比較相手は torch.compile+CUDA Graph と native TensorRT。
IOBinding でGPU常駐にし、CPU往復を測らないようにする。
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np
import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, r"C:\Users\sanka\AppData\Local\Temp\claude"
                   r"\C--01-work-00-Git-toybox-AI-Video-up"
                   r"\a69516b7-fb23-4024-ad85-73e2610bad30\scratchpad")
from gpulock import gpu_lock  # noqa: E402
from exp_trt import export_onnx, OUT  # noqa: E402

W, H = 720, 480


def bench(ep, onnx_path, bs, bursts=20, iters=20):
    import onnxruntime as ort
    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    opts = {}
    if ep == "TensorrtExecutionProvider":
        cache = OUT / "ort_trt_cache"
        cache.mkdir(exist_ok=True)
        opts = {"trt_fp16_enable": True, "trt_engine_cache_enable": True,
                "trt_engine_cache_path": str(cache)}
    sess = ort.InferenceSession(str(onnx_path), so, providers=[(ep, opts)])
    iname = sess.get_inputs()[0].name
    oname = sess.get_outputs()[0].name
    x = torch.rand((bs, 3, H, W), dtype=torch.half, device="cuda").contiguous()
    y = torch.empty((bs, 3, H * 2, W * 2), dtype=torch.half, device="cuda")
    io = sess.io_binding()
    io.bind_input(iname, "cuda", 0, np.float16, tuple(x.shape), x.data_ptr())
    io.bind_output(oname, "cuda", 0, np.float16, tuple(y.shape), y.data_ptr())
    for _ in range(20):
        sess.run_with_iobinding(io)
    torch.cuda.synchronize()
    times = []
    for _ in range(bursts):
        t0 = time.perf_counter()
        for _ in range(iters):
            sess.run_with_iobinding(io)
        torch.cuda.synchronize()
        times.append((time.perf_counter() - t0) / iters)
    times.sort()
    return bs / times[0], bs / times[len(times) // 2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="sd")
    ap.add_argument("--batches", default="1,4")
    ap.add_argument("--eps", default="CUDAExecutionProvider,TensorrtExecutionProvider")
    args = ap.parse_args()
    for bs in (int(b) for b in args.batches.split(",")):
        onnx = export_onnx(args.model, bs, half=True)
        for ep in args.eps.split(","):
            try:
                best, med = bench(ep, onnx, bs)
                print(f"ORT {ep.replace('ExecutionProvider',''):9s} bs={bs:<2d} "
                      f"best {best:7.1f} fps  med {med:7.1f} fps")
            except Exception as exc:
                print(f"ORT {ep:28s} bs={bs}: 失敗 {type(exc).__name__}: {str(exc)[:160]}")


if __name__ == "__main__":
    with gpu_lock("gpu-inference", "ONNX Runtime CUDA/TRT EP 比較"):
        main()
