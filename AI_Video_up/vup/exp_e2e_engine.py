"""推奨する最終形を実際に作って測る。

vup.py の FusedSR は「前処理 + model + nv12化」を1つの torch.compile graph に
畳んでいる。TensorRT へ移すとき model だけ差し替えると、前後処理が別kernelに
戻ってしまう。そこで前後処理ごと ONNX へ入れて engine を1つにする。

入力: pinned uint8 (bs,H,W,3) BGR
出力: uint8 (bs, H*scale*3/2, W*scale) NV12
これで engine 1回呼ぶだけで pipe へ流せる形になる。
"""
import sys
import time
from pathlib import Path

import torch
import torch.nn.functional as F

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, r"C:\Users\sanka\AppData\Local\Temp\claude"
                   r"\C--01-work-00-Git-toybox-AI-Video-up"
                   r"\a69516b7-fb23-4024-ad85-73e2610bad30\scratchpad")
from gpulock import gpu_lock  # noqa: E402
from srlib import FLOP_PER_FRAME, H, W, grab_frames, psnr  # noqa: E402
from models_registry import load_model, resolve  # noqa: E402
from exp_trt import TrtRunner, build_engine, OUT  # noqa: E402


class FullSR(torch.nn.Module):
    """uint8 BGR HWC -> NV12 uint8。vup.py の FusedSR.graph と同じ計算。"""

    def __init__(self, model):
        super().__init__()
        self.model = model

    def forward(self, u8):                      # (bs,H,W,3) uint8
        # TRT の ONNX parser は uint8 の Transpose を受け付けないので先に cast する
        x = u8.half().permute(0, 3, 1, 2).div(255.0)
        y = self.model(x).clamp(0, 1)
        b, g, r = y[:, 0:1], y[:, 1:2], y[:, 2:3]
        luma = 0.299 * r + 0.587 * g + 0.114 * b
        u = (b - luma) * (0.5 / (1 - 0.114))
        v = (r - luma) * (0.5 / (1 - 0.299))
        luma = (luma * 219.0 + 16.0)[:, 0]
        u = F.avg_pool2d(u, 2) * 224.0 + 128.0
        v = F.avg_pool2d(v, 2) * 224.0 + 128.0
        uv = torch.stack((u, v), dim=-1)
        uv = uv.reshape(uv.shape[0], uv.shape[2], -1)
        # uint8 化は最後の1回だけ。TRT は uint8 の中間tensorを受け付けない
        nv12 = torch.cat((luma, uv), dim=1)
        return nv12.clamp(0, 255).round().to(torch.uint8)


def export(bs):
    p = OUT / f"sd_full_b{bs}.onnx"
    if p.exists():
        return p
    model, scale, _ = load_model(resolve("sd"), device="cuda", half=True)
    net = FullSR(model.to(memory_format=torch.channels_last)).eval().cuda()
    u8 = torch.randint(0, 255, (bs, H, W, 3), dtype=torch.uint8, device="cuda")
    with torch.no_grad():
        torch.onnx.export(net, (u8,), str(p), input_names=["u8"],
                          output_names=["nv12"], opset_version=17, dynamo=False)
    del net, model
    torch.cuda.empty_cache()
    return p


def main():
    print("前後処理込み engine (uint8 BGR -> NV12)")
    for bs in (1, 2, 4):
        try:
            eng = build_engine(export(bs), "full", bs)
            r = TrtRunner(eng)
            best, med = r.bench(bursts=25, iters=20)
            print(f"  TRT 前後処理込み bs={bs:<2d} best {best:7.1f} fps  "
                  f"med {med:7.1f} fps  engine {eng.stat().st_size/2**20:.0f} MB")
            del r
            torch.cuda.empty_cache()
        except Exception as exc:
            print(f"  bs={bs}: 失敗 {type(exc).__name__}: {str(exc)[:200]}")


if __name__ == "__main__":
    with gpu_lock("gpu-inference", "前後処理込みTRT engine"):
        main()
