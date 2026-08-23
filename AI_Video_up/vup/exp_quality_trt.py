"""採否の判定に使う画質検証。基準は torch fp32。

既に許容されている「torch fp16 の丸め」を物差しにして、
TensorRT fp16 / int8 / fp8 がそれを超えるかを見る。
frame数を増やし、最悪frameの値で判定する(平均は外れ値を隠すため)。
"""
import sys
from pathlib import Path

import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, r"C:\Users\sanka\AppData\Local\Temp\claude"
                   r"\C--01-work-00-Git-toybox-AI-Video-up"
                   r"\a69516b7-fb23-4024-ad85-73e2610bad30\scratchpad")
from gpulock import gpu_lock  # noqa: E402
from srlib import grab_frames, to_gpu, psnr  # noqa: E402
from models_registry import load_model, resolve  # noqa: E402
from exp_trt import TrtRunner, build_engine, export_onnx, OUT  # noqa: E402

VIDEOS = [HERE.parent / "サンプル.mp4", HERE.parent / "テスト60秒.mp4"]
N_PER = 24


def main():
    m32, _, _ = load_model(resolve("sd"), device="cuda", half=False)
    m16, _, _ = load_model(resolve("sd"), device="cuda", half=True)
    m16 = m16.to(memory_format=torch.channels_last)

    cands = [("torch fp16", None)]
    for tag, onnx in (("TRT fp16", export_onnx("sd", 1, half=True)),
                      ("TRT int8", OUT / "sd_b1_fp32.int8.onnx"),
                      ("TRT fp8", OUT / "sd_b1_fp32.fp8.onnx")):
        try:
            if onnx.exists():
                prec = tag.split()[1]
                cands.append((tag, TrtRunner(build_engine(onnx, prec, 1))))
        except Exception as exc:
            print(f"  {tag}: engine 読めず {type(exc).__name__}")

    acc = {t: [] for t, _ in cands}
    n = 0
    for v in VIDEOS:
        if not v.exists():
            continue
        fr = grab_frames(v, N_PER, step=61)
        x = to_gpu(fr)
        n += len(fr)
        for i in range(len(fr)):
            xi = x[i:i + 1]
            with torch.no_grad():
                ref = m32(xi).clamp(0, 1).mul(255).round()
            for tag, r in cands:
                if r is None:
                    with torch.no_grad():
                        y = m16(xi.half().contiguous(
                            memory_format=torch.channels_last)).float()
                    y = y.clamp(0, 1).mul(255).round()
                else:
                    y = r(xi.to(r.buf[r.inp[0]].dtype)).float()
                    y = y.clamp(0, 1).mul(255).round()
                d = (ref - y).abs()
                acc[tag].append((psnr(ref, y), d.max().item(), d.mean().item()))

    print(f"\n実frame {n}枚 ({len(VIDEOS)}本) / 基準 torch fp32")
    print(f"{'':14s} {'PSNR最悪':>9s} {'PSNR平均':>9s} {'画素差max':>9s} "
          f"{'画素差mean':>11s} {'>2/255の割合':>12s}")
    for tag, _ in cands:
        v = acc[tag]
        finite = [p for p, _, _ in v if p != float("inf")]
        over = sum(1 for _, m, _ in v if m > 2) / len(v) * 100
        print(f"{tag:14s} {min(finite):9.2f} "
              f"{sum(finite)/len(finite):9.2f} "
              f"{max(m for _, m, _ in v):9.1f} "
              f"{sum(m for _, _, m in v)/len(v):11.4f} {over:11.1f}%")
    print("\n判定: torch fp16 (許容済み) の行を超えなければ、目視で差は出ない水準")


if __name__ == "__main__":
    with gpu_lock("gpu-inference", "TRT 画質検証 48frame"):
        main()
