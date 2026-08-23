"""RIFE(vs-mlrt の ONNX)を TensorRT で動かす。

## ONNX の素性

vs-mlrt が配っている RIFE の ONNX は2種類ある。

  rife/     … v1実装。入力 [1,11,H,W]。H,W を 32/64/128 の倍数へ自分で padし、
              座標grid 4ch を自分で作って足す必要がある
  rife_v2/  … v2実装。入力 [batch,7,H,W]。padは graph の中でやる

本fileは **v2実装** を使う。7ch の内訳は [R0,G0,B0, R1,G1,B1, t] で、
t は 0〜1 の時刻(全画素同じ値)。**時刻が入力なので任意時刻の中間frameが作れる**。
素材がVFR、あるいは 24→60 のように割り切れない倍率でも、この1本で足りる。

## fp16 について

TensorRT 11 は strongly typed network しか作れず BuilderFlag.FP16 が無い。
精度は ONNX 側の dtype が決めるので、fp16 で回すには ONNX を fp16 へ変換する。

ここで理屈上の懸念がある。RIFE は推定した flow を GridSample の正規化座標
(-1〜1)へ直す所で 2/(W-1) 倍する。1920幅なら 1.04e-3 で、fp16 の 1.0 近傍の
分解能 9.8e-4 とほぼ同じ。座標計算まで fp16 にすると sampling 位置が1画素刻みに
量子化される恐れがある。

ただし **これは理屈であって実測ではない**。座標計算だけ fp32 で残す graph 手術は
Cast の入れ忘れで conv の入力と重みの型が食い違い、engine の build が通らない
(実測: /encode/cnn0/Conv で input=Float kernel=Half)。
まず全部 fp16 で作り、**fp32 engine を対照に同じ試験集合で差を測る**
(exp_prec.py)。差が出てから手術する。
"""
import hashlib
from pathlib import Path

import numpy as np
import torch

import vfilib as V

ENGINE_FORMAT = 1     # このfileの生成規則を変えたら +1

# flow を作る側。ここから先(入力側)は fp16 のままにする
_FLOW_PRODUCERS = {"Conv", "ConvTranspose", "Resize", "DepthToSpace",
                   "LeakyRelu", "Sigmoid"}


def onnx_path(name):
    return V.ONNX / "rife_v2" / f"rife_{name}.onnx"


def available():
    return sorted(p.stem.replace("rife_", "")
                  for p in (V.ONNX / "rife_v2").glob("rife_v4*.onnx"))


# ------------------------------------------------------------ fp16変換

def _grid_path_nodes(model):
    """GridSample の grid 入力から後ろ向きに辿った node 名の集合。

    flow を作っている conv 系に当たったら、その node は含めずに止める。
    """
    g = model.graph
    producer = {}
    for n in g.node:
        for o in n.output:
            producer[o] = n
    keep, stack = set(), []
    for n in g.node:
        if n.op_type == "GridSample":
            stack.append(n.input[1])
    while stack:
        t = stack.pop()
        n = producer.get(t)
        if n is None or n.name in keep or n.op_type in _FLOW_PRODUCERS:
            continue
        keep.add(n.name)
        stack.extend(n.input)
    return keep


def to_fp16(src, dst, keep_grid_fp32=False):
    """ONNX を fp16 へ。keep_grid_fp32 で座標計算の node だけ fp32 で残す。"""
    import onnx
    from onnxconverter_common import float16

    m = onnx.load(str(src))
    keep = sorted(_grid_path_nodes(m)) if keep_grid_fp32 else []
    m16 = float16.convert_float_to_float16(
        m, keep_io_types=False, node_block_list=keep,
        disable_shape_infer=True)
    _fix_float_attrs(m16, keep)
    onnx.save(m16, str(dst))
    return len(keep)


def _fix_float_attrs(model, keep):
    """convert_float_to_float16 が書き換えない「型を属性で持つ node」を直す。

    Cast(to=FLOAT) と ConstantOfShape(value=fp32) は attribute の中に型があり、
    tensor の走査では見つからない。残すと Reciprocal→Mul のように
    fp32 と fp16 が同じ演算に入り、TensorRT の parse がそこで落ちる
    (実測: /Mul: ElementWiseOperation PROD must have same input types)。
    """
    import onnx
    from onnx import helper, numpy_helper
    import numpy as _np
    keep = set(keep)
    for n in model.graph.node:
        if n.name in keep:
            continue
        if n.op_type == "Cast":
            for a in n.attribute:
                if a.name == "to" and a.i == onnx.TensorProto.FLOAT:
                    a.i = onnx.TensorProto.FLOAT16
        elif n.op_type == "ConstantOfShape":
            for a in n.attribute:
                if a.name == "value" and a.t.data_type == onnx.TensorProto.FLOAT:
                    v = numpy_helper.to_array(a.t).astype(_np.float16)
                    a.t.CopyFrom(numpy_helper.from_array(v, a.t.name))


# ------------------------------------------------------------ engine

def _key(name, w, h, bs, fp16):
    import tensorrt as trt
    dev = torch.cuda.get_device_name(0).replace(" ", "")
    sig = (f"{name}|{w}x{h}|bs{bs}|{'fp16' if fp16 else 'fp32'}|"
           f"trt{trt.__version__}|{dev}|v{ENGINE_FORMAT}")
    return hashlib.sha1(sig.encode()).hexdigest()[:16]


def _build(onnx_file, engine_file, w, h, bs):
    import tensorrt as trt

    class _Log(trt.ILogger):
        def __init__(self):
            trt.ILogger.__init__(self)
            self.lines = []

        def log(self, sev, msg):
            if sev <= trt.ILogger.Severity.WARNING:
                self.lines.append(str(msg))

    logger = _Log()
    builder = trt.Builder(logger)
    net = builder.create_network(
        1 << int(trt.NetworkDefinitionCreationFlag.STRONGLY_TYPED))
    parser = trt.OnnxParser(net, logger)
    if not parser.parse(Path(onnx_file).read_bytes()):
        msg = "; ".join(str(parser.get_error(i)) for i in range(parser.num_errors))
        raise RuntimeError(f"ONNX parse失敗: {msg[:600]}")
    cfg = builder.create_builder_config()
    prof = builder.create_optimization_profile()
    iname = net.get_input(0).name
    prof.set_shape(iname, (bs, 7, h, w), (bs, 7, h, w), (bs, 7, h, w))
    cfg.add_optimization_profile(prof)
    free, _ = torch.cuda.mem_get_info()
    cfg.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE,
                              min(6 << 30, max(2 << 30, free // 2)))
    plan = builder.build_serialized_network(net, cfg)
    if plan is None:
        detail = "\n  ".join(logger.lines[-6:]) or "(詳細なし)"
        raise RuntimeError(f"engine build 失敗:\n  {detail}")
    Path(engine_file).write_bytes(plan)


class Rife:
    """RIFE v2実装の TensorRT engine。

    infer(t7) は (bs,7,h,w) の cuda tensor を受け、(bs,3,h,w) を返す。
    dtype は engine に合わせる(fp16 engine なら half)。
    """

    def __init__(self, name, w, h, bs=1, fp16=True, log=V.log):
        import tensorrt as trt
        self.name, self.w, self.h, self.bs, self.fp16 = name, w, h, bs, fp16
        self.dtype = torch.float16 if fp16 else torch.float32
        key = _key(name, w, h, bs, fp16)
        eng = V.ENGINES / f"{key}.engine"
        if not eng.exists():
            src = onnx_path(name)
            if not src.exists():
                raise FileNotFoundError(src)
            work = V.ENGINES / f"{key}.onnx"
            if fp16:
                n = to_fp16(src, work)
                log(f"  {name}: fp16化" + (f" (座標計算 {n} node は fp32)" if n else ""))
            else:
                work = src
            log(f"  {name}: engine を build します ({w}x{h} bs={bs} "
                f"{'fp16' if fp16 else 'fp32'})")
            import time
            t0 = time.time()
            _build(work, eng, w, h, bs)
            log(f"  {name}: build {time.time()-t0:.0f}秒 "
                f"({eng.stat().st_size/2**20:.0f} MB)")
            if fp16:
                Path(work).unlink(missing_ok=True)
        self.engine = trt.Runtime(trt.Logger(trt.Logger.ERROR)) \
            .deserialize_cuda_engine(eng.read_bytes())
        self.ctx = self.engine.create_execution_context()
        names = [self.engine.get_tensor_name(i)
                 for i in range(self.engine.num_io_tensors)]
        self.i_name = next(n for n in names if self.engine.get_tensor_mode(n)
                           == trt.TensorIOMode.INPUT)
        self.o_name = next(n for n in names if self.engine.get_tensor_mode(n)
                           == trt.TensorIOMode.OUTPUT)
        self.ctx.set_input_shape(self.i_name, (bs, 7, h, w))
        self.dev_in = torch.empty((bs, 7, h, w), dtype=self.dtype, device="cuda")
        oshape = tuple(self.ctx.get_tensor_shape(self.o_name))
        self.dev_out = torch.empty(oshape, dtype=self.dtype, device="cuda")
        self.ctx.set_tensor_address(self.i_name, self.dev_in.data_ptr())
        self.ctx.set_tensor_address(self.o_name, self.dev_out.data_ptr())
        self.out_shape = oshape

    def infer(self, t7=None):
        """dev_in の中身で実行し、dev_out の view を返す(次のinferで上書き)。

        t7 を渡した場合は dev_in へ写してから実行する。copy も execute も
        **現在のstream** に載せる。別streamにすると、入力を組む kernel が
        終わる前に engine が dev_in を読み、前回の絵が返る(実測した)。
        """
        if t7 is not None:
            self.dev_in.copy_(t7)
        self.ctx.execute_async_v3(torch.cuda.current_stream().cuda_stream)
        return self.dev_out[:, :, :self.h, :self.w]


# ------------------------------------------------------------ 前後処理

def pack(f0, f1, tau, dtype=torch.float16, out=None):
    """uint8 BGR HWC の2枚(cuda tensor)と時刻tauから (1,7,H,W) を組む。

    RIFE は RGB 0〜1 を受ける。BGR->RGB は index の逆順で済ませる。
    """
    h, w = f0.shape[:2]
    if out is None:
        out = torch.empty((1, 7, h, w), dtype=dtype, device=f0.device)
    out[0, 0:3] = f0.permute(2, 0, 1).flip(0).to(dtype).div_(255.0)
    out[0, 3:6] = f1.permute(2, 0, 1).flip(0).to(dtype).div_(255.0)
    out[0, 6] = tau
    return out


def unpack(y):
    """(1,3,H,W) RGB 0〜1 -> uint8 BGR HWC の cuda tensor。"""
    # permute してから float 化すると、25MB の fp32 中間を strided access で
    # 書くことになり 1080p で 5.7ms 掛かる。CHW のまま uint8 まで落とし、
    # 最後に1回だけ転置する(実測 5.70ms -> 0.55ms)。
    # 掛け算は fp32 で行う。fp16 のまま 255 倍すると丸めが .5 の境目をまたぎ、
    # 画素が最大1ずれる(実測)。CHW のうちは連続なので fp32 でも安い。
    x = y[0].float().clamp_(0, 1).mul_(255.0).round_().to(torch.uint8)
    return x.flip(0).permute(1, 2, 0).contiguous()


def to_gpu(arr):
    return torch.from_numpy(np.ascontiguousarray(arr)).cuda()
