"""int8 PTQ を実素材で calibration して TensorRT engine を作り、速度と画質を測る。

TensorRT 11 は strongly typed network しか作れず、BuilderFlag.INT8 は廃止された。
精度は ONNX 側の Q/DQ node で決まるので、modelopt で Q/DQ を挿した ONNX を作る。
calibration data は実frame (乱数だと分布が違い、scaleが外れる)。
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from models_registry import load_model, resolve  # noqa: E402
from exp_trt import TrtRunner, build_engine, export_onnx, OUT  # noqa: E402
from srlib import grab_frames, to_gpu, psnr  # noqa: E402

W, H = 720, 480


def quantize_onnx(src_onnx, calib, quant_mode="int8"):
    """modelopt.onnx.quantization で Q/DQ を挿す。"""
    from modelopt.onnx.quantization import quantize
    dst = src_onnx.with_name(src_onnx.stem + f".{quant_mode}.onnx")
    if dst.exists():
        return dst
    quantize(
        onnx_path=str(src_onnx),
        quantize_mode=quant_mode,
        calibration_data={"x": calib},
        calibration_method="max" if quant_mode == "fp8" else "entropy",
        calibration_eps=["cuda:0"],
        output_path=str(dst),
    )
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="sd")
    ap.add_argument("--bs", type=int, default=4)
    ap.add_argument("--mode", default="int8", choices=["int8", "fp8"])
    ap.add_argument("--calib-frames", type=int, default=16)
    args = ap.parse_args()

    video = HERE.parent / "サンプル.mp4"
    fr = grab_frames(video, args.calib_frames, step=211)
    calib = (fr.astype(np.float32) / 255.0).transpose(0, 3, 1, 2)
    print(f"calibration frame {len(calib)}枚")

    src = export_onnx(args.model, args.bs, half=False)
    dst = quantize_onnx(src, calib, args.mode)
    print("quantized:", dst.name)
    eng = build_engine(dst, args.mode, args.bs)
    r = TrtRunner(eng)
    best, med = r.bench()
    print(f"TRT {args.mode} bs={args.bs}: best {best:.1f} fps  med {med:.1f} fps")


if __name__ == "__main__":
    sys.path.insert(0, r"C:\Users\sanka\AppData\Local\Temp\claude"
                       r"\C--01-work-00-Git-toybox-AI-Video-up"
                       r"\a69516b7-fb23-4024-ad85-73e2610bad30\scratchpad")
    from gpulock import gpu_lock
    with gpu_lock("gpu-inference", "fp8/int8 PTQ 測定"):
        main()
