"""ONNX export -> TensorRT engine build -> 速度と画質の実測 (vup.py は触らない)

precision: fp16 / fp8 / int8 (best) を切り替えて engine を作り、
同じ入力での torch fp16 出力との画素差も出す。
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np
import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from models_registry import load_model, resolve  # noqa: E402

W, H = 720, 480
OUT = HERE / "trt_work"


def export_onnx(name, bs, opset=17, half=False):
    OUT.mkdir(exist_ok=True)
    p = OUT / f"{name}_b{bs}_{'fp16' if half else 'fp32'}.onnx"
    if p.exists():
        return p
    model, scale, arch = load_model(resolve(name), device="cuda", half=half)
    x = torch.randn(bs, 3, H, W, device="cuda",
                    dtype=torch.half if half else torch.float32)
    torch.onnx.export(model, (x,), str(p), input_names=["x"],
                      output_names=["y"], opset_version=opset, dynamo=False)
    print(f"  export: {p.name}  arch={arch} x{scale}")
    del model
    torch.cuda.empty_cache()
    return p


def build_engine(onnx_path, precision, bs, calib_data=None):
    """TensorRT 11 は strongly typed network のみ。BuilderFlag.FP16/INT8/FP8 は廃止で、
    精度は ONNX 側の dtype と Q/DQ node が決める。fp16 は fp16 で export した ONNX を渡す。
    """
    import tensorrt as trt
    eng_path = onnx_path.with_name(onnx_path.stem + f"_{precision}.engine")
    if eng_path.exists():
        return eng_path
    logger = trt.Logger(trt.Logger.WARNING)
    builder = trt.Builder(logger)
    network = builder.create_network(
        1 << int(trt.NetworkDefinitionCreationFlag.STRONGLY_TYPED))
    parser = trt.OnnxParser(network, logger)
    with open(onnx_path, "rb") as f:
        if not parser.parse(f.read()):
            for i in range(parser.num_errors):
                print("  parse error:", parser.get_error(i))
            raise SystemExit("ONNX parse失敗")
    cfg = builder.create_builder_config()
    cfg.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, 4 << 30)
    t0 = time.time()
    plan = builder.build_serialized_network(network, cfg)
    if plan is None:
        raise SystemExit(f"engine build失敗 ({precision})")
    eng_path.write_bytes(plan)
    print(f"  build {precision}: {time.time()-t0:.0f}s  {eng_path.name}")
    return eng_path


class TrtRunner:
    def __init__(self, eng_path):
        import tensorrt as trt
        self.trt = trt
        logger = trt.Logger(trt.Logger.WARNING)
        rt = trt.Runtime(logger)
        self.engine = rt.deserialize_cuda_engine(eng_path.read_bytes())
        self.ctx = self.engine.create_execution_context()
        self.names = [self.engine.get_tensor_name(i)
                      for i in range(self.engine.num_io_tensors)]
        self.inp = [n for n in self.names
                    if self.engine.get_tensor_mode(n) == trt.TensorIOMode.INPUT]
        self.out = [n for n in self.names
                    if self.engine.get_tensor_mode(n) == trt.TensorIOMode.OUTPUT]
        self.dtypes = {n: trt.nptype(self.engine.get_tensor_dtype(n))
                       for n in self.names}
        self.shapes = {n: tuple(self.ctx.get_tensor_shape(n)) for n in self.names}
        self.buf = {}
        for n in self.names:
            dt = torch.from_numpy(np.zeros(1, dtype=self.dtypes[n])).dtype
            self.buf[n] = torch.empty(self.shapes[n], dtype=dt, device="cuda")
            self.ctx.set_tensor_address(n, self.buf[n].data_ptr())
        # copy と execute は必ず同じ stream に載せる。別streamにすると
        # copy 完了前に engine が入力を読む競合になる (PSNR 31dB まで落ちた)。
        # default stream は TRT が余計な同期を入れるので専用streamを使う。
        self.stream = torch.cuda.Stream()

    def __call__(self, x):
        with torch.cuda.stream(self.stream):
            self.buf[self.inp[0]].copy_(x)
            self.ctx.execute_async_v3(self.stream.cuda_stream)
        self.stream.synchronize()
        return self.buf[self.out[0]]

    def bench(self, bursts=15, iters=20, warmup=30):
        """他processがGPUを間欠使用するので、短いburstの最速を採る。"""
        n = self.shapes[self.inp[0]][0]
        s = self.stream.cuda_stream
        for _ in range(warmup):
            self.ctx.execute_async_v3(s)
        self.stream.synchronize()
        times = []
        for _ in range(bursts):
            t0 = time.perf_counter()
            for _ in range(iters):
                self.ctx.execute_async_v3(s)
            self.stream.synchronize()
            times.append((time.perf_counter() - t0) / iters)
        times.sort()
        return n / times[0], n / times[len(times) // 2]


def quality(name, runner, n=4):
    """torch fp32 を基準に、torch fp16 と TRT の画素差を uint8 換算で比べる"""
    model32, scale, _ = load_model(resolve(name), device="cuda", half=False)
    torch.manual_seed(0)
    bs = runner.shapes[runner.inp[0]][0]
    stats = []
    for _ in range(n):
        x = torch.rand(bs, 3, H, W, device="cuda")
        with torch.no_grad():
            ref = model32(x).clamp(0, 1).mul(255).round()
        y = runner(x.to(runner.buf[runner.inp[0]].dtype))
        y = y.float().clamp(0, 1).mul(255).round()
        d = (y - ref).abs()
        stats.append((d.max().item(), d.mean().item()))
    del model32
    torch.cuda.empty_cache()
    return max(s[0] for s in stats), sum(s[1] for s in stats) / len(stats)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="sd")
    ap.add_argument("--batches", default="1,2,4")
    ap.add_argument("--precisions", default="fp16")
    ap.add_argument("--quality", action="store_true")
    args = ap.parse_args()

    print(f"model={args.model}  {W}x{H}")
    for bs in (int(b) for b in args.batches.split(",")):
        for prec in args.precisions.split(","):
            onnx = export_onnx(args.model, bs, half=(prec == "fp16"))
            try:
                eng = build_engine(onnx, prec, bs)
                r = TrtRunner(eng)
                fps, med = r.bench()
                line = f"TRT {prec:5s} bs={bs} : best {fps:7.1f} fps  med {med:7.1f} fps"
                if args.quality:
                    mx, mean = quality(args.model, r)
                    line += f"   画素差 max {mx:.1f}/255  mean {mean:.4f}"
                print(line)
                del r
                torch.cuda.empty_cache()
            except Exception as exc:
                print(f"TRT {prec:5s} bs={bs} : 失敗 {type(exc).__name__}: {str(exc)[:200]}")


if __name__ == "__main__":
    main()
