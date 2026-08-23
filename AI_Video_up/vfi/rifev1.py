"""RIFE の v1実装 ONNX。flow を低解像度で推定する `scale` を使うために要る。

v2実装(rifelib.py)は pad を graph の中でやってくれる代わり、`scale` を
掛けられない。**大変位で破綻するのを緩める唯一の手**が scale なので、
v1実装も用意する。

## v1 の入力 [1, 11, H, W]

  0-2  img0 RGB 0〜1
  3-5  img1 RGB 0〜1
  6    時刻 t
  7    横の正規化座標  2*x/(W-1) - 1
  8    縦の正規化座標  2*y/(H-1) - 1
  9    2/(W-1) を敷き詰めた面
  10   2/(H-1) を敷き詰めた面

H, W は **padした後**の大きさ。9/10 が flow(画素単位)を正規化座標へ直す係数で、
ここが padした大きさと食い違うと sampling 位置がずれる。
tau=0 で img0 と一致するかで検算する(exp_v1probe)。

## scale

vsmlrt と同じ graph 手術。Resize の倍率定数を 3個ごとに 2番目だけ 1/scale、
他を scale 倍し、Mul の定数を交互に 1/scale と scale 倍する。
flow の推定だけが低解像度になり、合成は原寸のまま。
pad の倍数は 32/scale になる(scale=0.5 なら 64)。
"""
import hashlib
from pathlib import Path

import torch
import torch.nn.functional as F

import rifelib as R
import vfilib as V

ENGINE_FORMAT = 1


def onnx_path(name):
    return V.ONNX / "rife" / f"rife_{name}.onnx"


def _apply_scale(model, scale):
    """vsmlrt.RIFEMerge と同じ定数書き換え。"""
    from onnx.numpy_helper import from_array, to_array
    rc = mc = 0
    for node in model.graph.node:
        if len(node.output) != 1 or node.op_type != "Constant":
            continue
        if node.output[0].startswith("onnx::Resize"):
            rc += 1
            t = node.attribute[0].t
            arr = to_array(t).copy()
            if rc % 3 == 2:
                arr[2:4] /= scale
            else:
                arr[2:4] *= scale
            # raw_data だけ差し替えると float_data が残って型が食い違い、
            # 後段の fp16 変換で「4 bytes を 2 bytes へ」と言われて parse が落ちる
            t.CopyFrom(from_array(arr, t.name))
        elif node.output[0].startswith("onnx::Mul"):
            mc += 1
            t = node.attribute[0].t
            arr = to_array(t).copy()
            arr = arr / scale if mc % 2 == 1 else arr * scale
            t.CopyFrom(from_array(arr.astype(to_array(t).dtype), t.name))
    if rc != 11 or mc != 7:
        raise RuntimeError(f"想定した定数の数と違います (Resize {rc}, Mul {mc})。"
                           "この重みは scale を掛けられません")
    return model


def multiple_of(name, scale):
    major_minor = name.split("_")[0].lstrip("v")
    mj, mn = (int(x) for x in major_minor.split("."))
    if (mj, mn) >= (4, 26):
        base = 64
    elif name in ("v4.25_lite",):
        base = 128
    elif name in ("v4.25_heavy", "v4.26_heavy"):
        base = 64
    else:
        base = 32
    m = base / scale
    if m != int(m):
        raise ValueError(f"{base}/scale が整数になりません")
    return int(m)


class RifeV1:
    def __init__(self, name, w, h, scale=1.0, fp16=True, log=V.log):
        import tensorrt as trt
        self.name, self.w, self.h, self.scale = name, w, h, scale
        self.dtype = torch.float16 if fp16 else torch.float32
        mult = multiple_of(name, scale)
        self.pw = (w + mult - 1) // mult * mult
        self.ph = (h + mult - 1) // mult * mult

        dev = torch.cuda.get_device_name(0).replace(" ", "")
        sig = (f"v1|{name}|{self.pw}x{self.ph}|s{scale}|"
               f"{'fp16' if fp16 else 'fp32'}|trt{trt.__version__}|{dev}|"
               f"v{ENGINE_FORMAT}")
        key = hashlib.sha1(sig.encode()).hexdigest()[:16]
        eng = V.ENGINES / f"{key}.engine"
        if not eng.exists():
            import onnx
            src = onnx_path(name)
            if not src.exists():
                raise FileNotFoundError(src)
            m = onnx.load(str(src))
            if scale != 1.0:
                m = _apply_scale(m, scale)
            work = V.ENGINES / f"{key}.onnx"
            onnx.save(m, str(work))
            if fp16:
                R.to_fp16(work, work)
            log(f"  {name} v1 scale={scale}: engine build "
                f"({self.pw}x{self.ph} {'fp16' if fp16 else 'fp32'})")
            import time
            t0 = time.time()
            _build(work, eng, self.pw, self.ph)
            log(f"  build {time.time()-t0:.0f}秒 "
                f"({eng.stat().st_size/2**20:.0f} MB)")
            work.unlink(missing_ok=True)

        self.engine = trt.Runtime(trt.Logger(trt.Logger.ERROR)) \
            .deserialize_cuda_engine(eng.read_bytes())
        self.ctx = self.engine.create_execution_context()
        names = [self.engine.get_tensor_name(i)
                 for i in range(self.engine.num_io_tensors)]
        self.i_name = next(n for n in names if self.engine.get_tensor_mode(n)
                           == trt.TensorIOMode.INPUT)
        self.o_name = next(n for n in names if self.engine.get_tensor_mode(n)
                           == trt.TensorIOMode.OUTPUT)
        self.ctx.set_input_shape(self.i_name, (1, 11, self.ph, self.pw))
        self.dev_in = torch.empty((1, 11, self.ph, self.pw), dtype=self.dtype,
                                  device="cuda")
        self.dev_out = torch.empty(tuple(self.ctx.get_tensor_shape(self.o_name)),
                                   dtype=self.dtype, device="cuda")
        self.ctx.set_tensor_address(self.i_name, self.dev_in.data_ptr())
        self.ctx.set_tensor_address(self.o_name, self.dev_out.data_ptr())
        self.out_shape = tuple(self.dev_out.shape)

        # 座標の面は毎回同じなので一度だけ作る
        xs = torch.arange(self.pw, device="cuda", dtype=torch.float32)
        ys = torch.arange(self.ph, device="cuda", dtype=torch.float32)
        self.dev_in[0, 7] = (2 * xs / (self.pw - 1) - 1).view(1, -1)
        self.dev_in[0, 8] = (2 * ys / (self.ph - 1) - 1).view(-1, 1)
        self.dev_in[0, 9] = 2.0 / (self.pw - 1)
        self.dev_in[0, 10] = 2.0 / (self.ph - 1)

    def pack(self, f0, f1, tau):
        """uint8 BGR HWC(cuda) 2枚。pad は端の複製で埋める。"""
        def put(dst, f):
            x = f.permute(2, 0, 1).flip(0).to(self.dtype).div_(255.0)
            if (self.ph, self.pw) != (self.h, self.w):
                x = F.pad(x.unsqueeze(0).float(),
                          (0, self.pw - self.w, 0, self.ph - self.h),
                          mode="replicate")[0].to(self.dtype)
            dst.copy_(x)
        put(self.dev_in[0, 0:3], f0)
        put(self.dev_in[0, 3:6], f1)
        self.dev_in[0, 6] = tau

    def infer(self):
        self.ctx.execute_async_v3(torch.cuda.current_stream().cuda_stream)
        return self.dev_out[:, :, :self.h, :self.w]


def _build(onnx_file, engine_file, w, h):
    import tensorrt as trt
    logger = trt.Logger(trt.Logger.ERROR)
    builder = trt.Builder(logger)
    net = builder.create_network(
        1 << int(trt.NetworkDefinitionCreationFlag.STRONGLY_TYPED))
    parser = trt.OnnxParser(net, logger)
    if not parser.parse(Path(onnx_file).read_bytes()):
        msg = "; ".join(str(parser.get_error(i)) for i in range(parser.num_errors))
        raise RuntimeError(f"ONNX parse失敗: {msg[:600]}")
    cfg = builder.create_builder_config()
    prof = builder.create_optimization_profile()
    prof.set_shape(net.get_input(0).name, (1, 11, h, w), (1, 11, h, w),
                   (1, 11, h, w))
    cfg.add_optimization_profile(prof)
    free, _ = torch.cuda.mem_get_info()
    cfg.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE,
                              min(6 << 30, max(2 << 30, free // 2)))
    plan = builder.build_serialized_network(net, cfg)
    if plan is None:
        raise RuntimeError("engine build 失敗")
    Path(engine_file).write_bytes(plan)
