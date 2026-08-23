"""engine が実際に何をしているかを見る。layer別の時間と、選ばれた format/precision。"""
import json
import sys
from pathlib import Path

import tensorrt as trt
import torch

HERE = Path(__file__).resolve().parent
eng_path = Path(sys.argv[1])

logger = trt.Logger(trt.Logger.WARNING)
rt = trt.Runtime(logger)
engine = rt.deserialize_cuda_engine(eng_path.read_bytes())
ctx = engine.create_execution_context()

insp = engine.create_engine_inspector()
insp.execution_context = ctx
info = json.loads(insp.get_engine_information(trt.LayerInformationFormat.JSON))
layers = info.get("Layers", info)
print(f"layer数 {len(layers)}")
for L in layers[:8] + (layers[-3:] if len(layers) > 11 else []):
    if isinstance(L, dict):
        print(f"  {L.get('Name','?')[:60]:62s} "
              f"tactic={str(L.get('TacticValue',''))[:18]:20s}")
        print(f"      in ={L.get('Inputs')}")
        print(f"      out={L.get('Outputs')}")
    else:
        print("  ", str(L)[:150])


class P(trt.IProfiler):
    def __init__(self):
        super().__init__()
        self.d = {}

    def report_layer_time(self, name, ms):
        self.d[name] = self.d.get(name, 0.0) + ms


names = [engine.get_tensor_name(i) for i in range(engine.num_io_tensors)]
bufs = {}
for n in names:
    dt = trt.nptype(engine.get_tensor_dtype(n))
    t = torch.zeros(tuple(ctx.get_tensor_shape(n)),
                    dtype=torch.from_numpy(__import__("numpy").zeros(1, dtype=dt)).dtype,
                    device="cuda")
    bufs[n] = t
    ctx.set_tensor_address(n, t.data_ptr())

s = torch.cuda.Stream()
for _ in range(20):
    ctx.execute_async_v3(s.cuda_stream)
s.synchronize()
prof = P()
ctx.profiler = prof
N = 20
for _ in range(N):
    ctx.execute_async_v3(s.cuda_stream)
s.synchronize()
tot = sum(prof.d.values()) / N
print(f"\n合計 {tot:.3f} ms/iter = {1000/tot:.1f} fps")
for k, v in sorted(prof.d.items(), key=lambda kv: -kv[1])[:12]:
    print(f"  {v/N:7.3f} ms  {k[:90]}")
