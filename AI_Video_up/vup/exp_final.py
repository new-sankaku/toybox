"""結論用の clean 測定。team の GPU lock を取って、他の計測と重ならない状態で測る。

比較するのは全部「model forward だけ」(前後処理は含めない):
  torch eager / torch.compile / +CUDA Graph / TensorRT fp16 を batch 別に。
A と B を交互に測り、各々の最速burstを採る。
"""
import sys
import time
from pathlib import Path

import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, r"C:\Users\sanka\AppData\Local\Temp\claude"
                   r"\C--01-work-00-Git-toybox-AI-Video-up"
                   r"\a69516b7-fb23-4024-ad85-73e2610bad30\scratchpad")
from gpulock import gpu_lock  # noqa: E402
from srlib import FLOP_PER_FRAME, H, W  # noqa: E402
from models_registry import load_model, resolve  # noqa: E402
from exp_trt import TrtRunner, build_engine, export_onnx  # noqa: E402

BURSTS, ITERS = 25, 20


def torch_runner(bs, mode="default", graph=True):
    torch.backends.cudnn.benchmark = True
    model, _, _ = load_model(resolve("sd"), device="cuda", half=True)
    model = model.to(memory_format=torch.channels_last)
    if mode != "none":
        model = torch.compile(model) if mode == "default" else \
            torch.compile(model, mode=mode)
    x = torch.rand((bs, 3, H, W), dtype=torch.half, device="cuda").contiguous(
        memory_format=torch.channels_last)
    with torch.no_grad():
        for _ in range(25):
            model(x)
        torch.cuda.synchronize()
        if not graph:
            return lambda: model(x)
        s = torch.cuda.Stream()
        s.wait_stream(torch.cuda.current_stream())
        with torch.cuda.stream(s):
            for _ in range(5):
                model(x)
        torch.cuda.current_stream().wait_stream(s)
        g = torch.cuda.CUDAGraph()
        with torch.cuda.graph(g):
            model(x)
        return g.replay


def burst(fn, n=ITERS):
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    for _ in range(n):
        fn()
    torch.cuda.synchronize()
    return (time.perf_counter() - t0) / n


def report(tag, times, bs):
    times.sort()
    best, med = bs / times[0], bs / times[len(times) // 2]
    print(f"  {tag:26s} bs={bs:<2d} best {best:7.1f} fps  med {med:7.1f} fps"
          f"  {best*FLOP_PER_FRAME/1e12:5.1f} TFLOPS", flush=True)
    return best


def main():
    print(f"torch={torch.__version__}  {W}x{H}  RTX 4070 Ti")
    base = None
    for bs in (1, 2, 4):
        with torch.no_grad():
            trt = TrtRunner(build_engine(export_onnx("sd", bs, half=True),
                                         "fp16", bs))
            trun = torch_runner(bs)
            s = trt.stream.cuda_stream

            def trt_run():
                trt.ctx.execute_async_v3(s)

            for _ in range(10):
                trun(); trt_run()
            ta, tb = [], []
            for _ in range(BURSTS):
                ta.append(burst(trun))
                tb.append(burst(trt_run))
            a = report("torch.compile+CUDAGraph", ta, bs)
            b = report("TensorRT fp16", tb, bs)
            if base is None:
                base = a
            print(f"    TRT/torch(同bs) {b/a:.2f}x   "
                  f"現行(torch bs=1)比 {b/base:.2f}x", flush=True)
            del trt, trun
            torch.cuda.empty_cache()


if __name__ == "__main__":
    with gpu_lock("gpu-inference", "TRT vs torch.compile 最終測定"):
        main()
