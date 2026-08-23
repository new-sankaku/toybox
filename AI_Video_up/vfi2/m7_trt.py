"""品質で上位に来た model を TensorRT へ載せられるかを確かめる。

載る/載らないの判断は「ONNX へ出せるか」と「出た graph を TensorRT が parse
できるか」の2段。**落ちたら落ちたと記録します**(別の物へ黙って落とさない)。

    python m7_trt.py film        FILM(torchscript) を ONNX へ
    python m7_trt.py probe       各 model の TensorRT 可否を静的に調べる
"""
import sys
import time

import torch

import lib
import vfimodels

ONNX = lib.ROOT / "onnx"
ONNX.mkdir(exist_ok=True)


def export_film(h=1088, w=1920, opset=17):
    """FILM は conv と grid_sample だけの graph。TensorRT の守備範囲のはず。

    torchscript を直接 export すると Fusion の
    `F.interpolate(net, size=pyramid[i].shape[2:4])` が「shape 由来の scalar
    size」になって落ちる。repo の source から eager を組み直し、そこだけ
    `scale_factor=2.0` へ書き換えてから出す(出力は torchscript と bit 一致を確認済み)。
    """
    root = vfimodels.MODELS / "FILM"
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from interpolator import Interpolator
    jit = torch.jit.load(str(root / "film_net_fp32.pt"), map_location="cpu")
    net = Interpolator()
    net.load_state_dict(jit.state_dict())
    net.eval()
    i0 = torch.rand(1, 3, h, w)
    i1 = torch.rand(1, 3, h, w)
    dt = torch.full((1, 1), 0.5)
    dst = ONNX / f"film_{w}x{h}.onnx"
    t0 = time.time()
    try:
        torch.onnx.export(net, (i0, i1, dt), str(dst), opset_version=opset,
                          input_names=["img0", "img1", "dt"],
                          output_names=["out"], dynamo=False)
    except Exception as exc:
        lib.record("trt", dict(model="FILM", stage="onnx_export", ok=False,
                               opset=opset, error=f"{type(exc).__name__}: {str(exc)[:600]}"))
        lib.log(f"  FILM: ONNX 失敗 {type(exc).__name__}: {str(exc)[:200]}")
        return None
    lib.record("trt", dict(model="FILM", stage="onnx_export", ok=True, opset=opset,
                           path=str(dst), mb=round(dst.stat().st_size / 2 ** 20, 1),
                           sec=round(time.time() - t0, 1)))
    lib.log(f"  FILM: ONNX 成功 {dst.stat().st_size/2**20:.1f}MB "
            f"({time.time()-t0:.0f}秒)")
    return dst


def build_trt(onnx_path, name):
    import tensorrt as trt
    logger = trt.Logger(trt.Logger.WARNING)
    builder = trt.Builder(logger)
    net = builder.create_network(
        1 << int(trt.NetworkDefinitionCreationFlag.STRONGLY_TYPED))
    parser = trt.OnnxParser(net, logger)
    with open(onnx_path, "rb") as f:
        if not parser.parse(f.read()):
            errs = [parser.get_error(i).desc() for i in range(parser.num_errors)]
            lib.record("trt", dict(model=name, stage="parse", ok=False,
                                   error=" | ".join(errs)[:800]))
            lib.log(f"  {name}: parse 失敗 {errs[:2]}")
            return None
    cfg = builder.create_builder_config()
    cfg.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, 4 << 30)
    t0 = time.time()
    # engine build は時間を測らないので共有側(lib の指針どおり)
    with lib.gpu_use("models"):
        plan = builder.build_serialized_network(net, cfg)
    if plan is None:
        lib.record("trt", dict(model=name, stage="build", ok=False,
                               error="build_serialized_network が None を返しました"))
        return None
    dst = lib.ROOT / "engines"
    dst.mkdir(exist_ok=True)
    p = dst / f"{name}.engine"
    p.write_bytes(plan)
    lib.record("trt", dict(model=name, stage="build", ok=True,
                           mb=round(len(plan) / 2 ** 20, 1),
                           sec=round(time.time() - t0, 1)))
    lib.log(f"  {name}: engine 完成 {len(plan)/2**20:.1f}MB ({time.time()-t0:.0f}秒)")
    return p


def probe():
    """各 model が TensorRT に載らない理由を、code の実体で確かめる。"""
    import importlib.util
    facts = []

    def has(path, needle):
        try:
            return needle in path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return False

    gm = vfimodels.MODELS / "DRBA" / "models"
    facts.append(dict(model="GMFSS_union",
                      cupy_kernel=has(gm / "softsplat" / "softsplat.py", "RawModule"),
                      autograd_function=has(gm / "softsplat" / "softsplat.py",
                                            "torch.autograd.Function"),
                      transformer=has(gm / "gmflow" / "transformer.py", "einsum")))
    gi = (vfimodels.MODELS / "GIMMVFI" / "src" / "models" / "generalizable_INR")
    facts.append(dict(model="GIMM-VFI",
                      cupy_kernel=has(gi / "modules" / "softsplat.py", "RawModule"),
                      python_loop=has(gi / "raft" / "corr.py", "for "),
                      transformer=has(gi / "flowformer" / "core" / "position_encoding.py",
                                      "class")))
    for f in facts:
        lib.record("trt_probe", f)
        print(f)


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "film"
    if what == "film":
        p = export_film()
        if p:
            build_trt(p, "film_1920x1088")
    elif what == "probe":
        probe()
