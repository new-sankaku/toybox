"""TensorRT engine を vup.py の backend として使うための最小の接続。

前処理(uint8 BGR HWC -> fp16 NCHW /255) と 後処理(nv12化 or uint8 BGR HWC) まで
engine に入れる。model だけ差し替えると FusedSR が畳んでいた前後処理が
別kernelに戻ってしまうため。実測で前後処理を入れてもcostは 2.5% (221.9->216.4 fps)。

vup.py 側の改修は3行:

    # make_backend() の戻り値を差し替える
    from trt_backend import TrtSR, want_trt
    if args.trt:
        backend = TrtSR(weights, w, h, out_scale=out_scale, bs=args.trt_batch,
                        nv12=(args.out_pix == "nv12"))
    # 以降 backend.run_into(src_pin, dst_pin) は今のまま

  ap.add_argument("--trt", action="store_true", help="TensorRT engineで推論する")
  ap.add_argument("--trt-batch", type=int, default=1)

bs=1 なら sr_worker は今のまま動く(drop-in)。bs>=2 にするには sr_worker を
batch対応させる必要がある(下の「batch化について」参照)。

engine は (重みfile, 入力解像度, out_scale, batch, nv12) ごとに1つ必要で、
初回だけ 20〜45秒掛かる。以降は CACHE_DIR から読む(load 0.75秒)。
TensorRT/driver/GPU を変えたら作り直しになるので、cache key に版を入れてある。

--- 実測 (RTX 4070 Ti, 720x480 -> 1440x960, sd=Compact 0.60M) ---
  現行 FusedSR (torch.compile)          113.8 fps
  TrtSR bs=1                            127.2 fps  (1.12倍)
  TrtSR bs=2                            204.9 fps  (1.80倍)
  ※ いずれも pinned H2D 0.090ms + D2H 0.170ms を含めた値

--- batch化について ---
bs>=2 では sr_worker (vup.py 496-539行) の改修が要る:
  1. inflight の要素を batch 単位にし、枚数を slot ごとに持つ
     ([buf, arr, rep, ev] -> [buf, arr, [rep,...], ev])。
     使い回しの `inflight[-1][2] += rp` の加算先は「直近のbatch」ではなく
     「直近のslot」にする。ここを間違えると frame 順が狂う。
  2. 入力が途切れたときに端数batchをflushする経路を足す。
     無いと末尾のframeが出ないまま止まる。
"""
import hashlib
from pathlib import Path

import torch
import torch.nn.functional as F

HERE = Path(__file__).resolve().parent
CACHE_DIR = HERE / "trt_engines"
ENGINE_FORMAT = 2   # このfileの生成規則を変えたら +1 する


class _Wrapped(torch.nn.Module):
    """uint8 BGR HWC -> (nv12 uint8 | uint8 BGR HWC)。FusedSR.graph と同じ計算。"""

    def __init__(self, model, down, ratio, nv12):
        super().__init__()
        self.model = model
        self.down, self.ratio, self.nv12 = down, ratio, nv12

    def forward(self, u8):                       # (bs,H,W,3) uint8
        # TRT の ONNX parser は uint8 の Transpose を通さないので先に cast する
        x = u8.half().permute(0, 3, 1, 2).div(255.0)
        y = self.model(x).clamp(0, 1)
        if self.down > 1:
            y = F.avg_pool2d(y, self.down)
        elif self.ratio != 1.0:
            y = F.interpolate(y.float(), scale_factor=self.ratio, mode="bicubic",
                              align_corners=False,
                              antialias=self.ratio < 1.0).clamp(0, 1).half()
        if not self.nv12:
            # uint8 化は最後の1回だけ。TRT は uint8 の中間tensorを受け付けない
            y = y.mul(255.0).permute(0, 2, 3, 1)
            return y.clamp(0, 255).round().to(torch.uint8)
        b, g, r = y[:, 0:1], y[:, 1:2], y[:, 2:3]
        luma = 0.299 * r + 0.587 * g + 0.114 * b
        u = (b - luma) * (0.5 / (1 - 0.114))
        v = (r - luma) * (0.5 / (1 - 0.299))
        luma = (luma * 219.0 + 16.0)[:, 0]
        u = F.avg_pool2d(u, 2) * 224.0 + 128.0
        v = F.avg_pool2d(v, 2) * 224.0 + 128.0
        uv = torch.stack((u, v), dim=-1)
        uv = uv.reshape(uv.shape[0], uv.shape[2], -1)
        nv12 = torch.cat((luma, uv), dim=1)
        return nv12.clamp(0, 255).round().to(torch.uint8)


# dynamic shape engine が受け持つ入力の範囲。opt に指定した解像度が最も速く、
# 外れるほど落ちる。nv12出力は縦横とも偶数が要る。
DYN_MIN = (256, 144)
DYN_OPT = (1280, 720)
DYN_MAX = (1920, 1088)


def _cache_key(weights, w, h, bs, out_scale, nv12, dynamic=False):
    import tensorrt as trt
    dev = torch.cuda.get_device_name(0).replace(" ", "")
    shape = (f"dyn{DYN_MIN[0]}x{DYN_MIN[1]}-{DYN_OPT[0]}x{DYN_OPT[1]}"
             f"-{DYN_MAX[0]}x{DYN_MAX[1]}") if dynamic else f"{w}x{h}"
    sig = f"{Path(weights).name}|{shape}|bs{bs}|s{out_scale}|nv12={nv12}|" \
          f"trt{trt.__version__}|{dev}|v{ENGINE_FORMAT}"
    return hashlib.sha1(sig.encode()).hexdigest()[:16]


def _export_onnx(weights, w, h, bs, out_scale, nv12, path, dynamic=False):
    from models_registry import load_model
    model, scale, arch = load_model(weights, device="cuda", half=True)
    model = model.to(memory_format=torch.channels_last)
    out_scale = out_scale or scale
    exact = out_scale < scale and scale % out_scale == 0
    net = _Wrapped(model, scale // out_scale if exact else 1,
                   out_scale / scale, nv12).eval().cuda()
    if dynamic:                      # 見本は opt の解像度で出す
        w, h = DYN_OPT
    u8 = torch.zeros((bs, h, w, 3), dtype=torch.uint8, device="cuda")
    axes = {"u8": {1: "h", 2: "w"}, "out": {1: "oh", 2: "ow"}} if dynamic else None
    with torch.no_grad():
        torch.onnx.export(net, (u8,), str(path), input_names=["u8"],
                          output_names=["out"], opset_version=17, dynamo=False,
                          dynamic_axes=axes)
    del net, model
    torch.cuda.empty_cache()
    return scale, out_scale, arch


def _collect_logger():
    """buildが失敗したときに理由を出せるよう、TensorRTのlogを溜めるlogger。

    trt.Builder は trt.ILogger の派生しか受け付けないので、import後に組む。
    """
    import tensorrt as trt

    class _CollectLogger(trt.ILogger):
        def __init__(self):
            trt.ILogger.__init__(self)
            self.lines = []

        def log(self, severity, msg):
            if severity <= trt.ILogger.Severity.WARNING:
                self.lines.append(str(msg))
                print(f"    [TRT] {msg}", flush=True)

    return _CollectLogger()


def _build(onnx_path, engine_path, profile_bs=None):
    """TensorRT 11 は strongly typed network のみ。BuilderFlag.FP16 は廃止で、
    精度は ONNX 側の dtype が決める(fp16 で export してあるので fp16 engine)。"""
    import tensorrt as trt
    logger = _collect_logger()
    builder = trt.Builder(logger)
    network = builder.create_network(
        1 << int(trt.NetworkDefinitionCreationFlag.STRONGLY_TYPED))
    parser = trt.OnnxParser(network, logger)
    if not parser.parse(onnx_path.read_bytes()):
        msg = "; ".join(str(parser.get_error(i)) for i in range(parser.num_errors))
        raise RuntimeError(f"ONNX parse失敗: {msg[:400]}")
    cfg = builder.create_builder_config()
    if profile_bs is not None:
        prof = builder.create_optimization_profile()
        prof.set_shape(network.get_input(0).name,
                       (profile_bs, DYN_MIN[1], DYN_MIN[0], 3),
                       (profile_bs, DYN_OPT[1], DYN_OPT[0], 3),
                       (profile_bs, DYN_MAX[1], DYN_MAX[0], 3))
        cfg.add_optimization_profile(prof)
    # 2GBだと DAT2 のような重いarchが「insufficient memory」でtacticを全部
    # 捨ててbuildに失敗する。空きVRAMの半分か6GBの小さい方を上限にする。
    free, _total = torch.cuda.mem_get_info()
    cfg.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE,
                              min(6 << 30, max(2 << 30, free // 2)))
    plan = builder.build_serialized_network(network, cfg)
    if plan is None:
        detail = "\n      ".join(logger.lines[-4:]) or "(TensorRTからの詳細なし)"
        raise SystemExit(
            "TensorRT engine の build に失敗しました。\n"
            f"      {detail}\n"
            "  このmodelはTensorRTに載りません。"
            "--no-trt を付けてtorchで実行してください。")
    engine_path.write_bytes(plan)


class TrtSR:
    """vup.py の backend 互換。run_into(src_pin, dst_pin) -> cuda Event。"""

    def __init__(self, weights, w, h, out_scale=None, bs=1, nv12=True,
                 log=print, dynamic=False):
        import tensorrt as trt
        CACHE_DIR.mkdir(exist_ok=True)
        if dynamic and not (DYN_MIN[0] <= w <= DYN_MAX[0]
                            and DYN_MIN[1] <= h <= DYN_MAX[1]):
            raise SystemExit(
                f"--trt-dynamic が受け持つ範囲({DYN_MIN[0]}x{DYN_MIN[1]}〜"
                f"{DYN_MAX[0]}x{DYN_MAX[1]})の外です: {w}x{h}")
        key = _cache_key(weights, w, h, bs, out_scale, nv12, dynamic)
        onnx_path = CACHE_DIR / f"{key}.onnx"
        engine_path = CACHE_DIR / f"{key}.engine"
        meta = CACHE_DIR / f"{key}.txt"

        if not engine_path.exists():
            what = (f"{DYN_MIN[0]}x{DYN_MIN[1]}〜{DYN_MAX[0]}x{DYN_MAX[1]}可変"
                    if dynamic else f"{w}x{h}")
            log(f"  TensorRT engine を作ります ({what} bs={bs})。初回のみ20〜45秒")
            scale, out_scale, arch = _export_onnx(weights, w, h, bs, out_scale,
                                                  nv12, onnx_path, dynamic)
            _build(onnx_path, engine_path, bs if dynamic else None)
            # ONNX は engine を作るためだけの中間file。engineができたら消す
            onnx_path.unlink(missing_ok=True)
            for extra in CACHE_DIR.glob(onnx_path.name + ".*"):
                extra.unlink(missing_ok=True)
            meta.write_text(f"{scale}\t{out_scale}\t{arch}", encoding="utf-8")
            log(f"  保存しました: {engine_path.name} "
                f"({engine_path.stat().st_size / 2**20:.0f} MB)")
        s, o, arch = meta.read_text(encoding="utf-8").split("\t")
        self.scale, self.out_scale, self.arch = int(s), int(o), arch

        logger = trt.Logger(trt.Logger.ERROR)
        self.engine = trt.Runtime(logger).deserialize_cuda_engine(
            engine_path.read_bytes())
        self.ctx = self.engine.create_execution_context()
        names = [self.engine.get_tensor_name(i)
                 for i in range(self.engine.num_io_tensors)]
        self.i_name = next(n for n in names
                           if self.engine.get_tensor_mode(n) ==
                           trt.TensorIOMode.INPUT)
        self.o_name = next(n for n in names
                           if self.engine.get_tensor_mode(n) ==
                           trt.TensorIOMode.OUTPUT)
        if dynamic:      # 形状を決めてからでないと buffer の大きさが判らない
            self.ctx.set_input_shape(self.i_name, (bs, h, w, 3))
        self.dev_in = torch.empty(tuple(self.ctx.get_tensor_shape(self.i_name)),
                                  dtype=torch.uint8, device="cuda")
        self.dev_out = torch.empty(tuple(self.ctx.get_tensor_shape(self.o_name)),
                                   dtype=torch.uint8, device="cuda")
        self.ctx.set_tensor_address(self.i_name, self.dev_in.data_ptr())
        self.ctx.set_tensor_address(self.o_name, self.dev_out.data_ptr())
        # copy と execute は必ず同じ stream に載せる。別streamにすると
        # copy 完了前に engine が入力を読み、出力が壊れる(実測 PSNR 31dB)。
        # default stream は TRT が余計な同期を入れるので専用streamにする。
        self.stream = torch.cuda.Stream()
        self.bs = bs
        self.nv12 = nv12
        self.compiled = True
        self.name = (f"{arch} x{self.scale} TensorRT fp16 (bs={bs}"
                     + ("、可変形状)" if dynamic else ")"))

    def run_into(self, src_pin, dst_pin):
        """bs=1 用。vup.py の sr_worker から今のまま呼べる。"""
        with torch.cuda.stream(self.stream):
            self.dev_in.copy_(src_pin.reshape(self.dev_in.shape),
                              non_blocking=True)
            self.ctx.execute_async_v3(self.stream.cuda_stream)
            dst_pin.copy_(self.dev_out.reshape(dst_pin.shape), non_blocking=True)
            ev = torch.cuda.Event()
            ev.record(self.stream)
        return ev

    def run_batch_into(self, src_pins, dst_pin):
        """bs>=2 用。src_pins は bs 枚の pinned frame。dst_pin は bs 枚ぶん。"""
        with torch.cuda.stream(self.stream):
            for i, s in enumerate(src_pins):
                self.dev_in[i].copy_(s.reshape(self.dev_in.shape[1:]),
                                     non_blocking=True)
            self.ctx.execute_async_v3(self.stream.cuda_stream)
            dst_pin.copy_(self.dev_out.reshape(dst_pin.shape), non_blocking=True)
            ev = torch.cuda.Event()
            ev.record(self.stream)
        return ev
