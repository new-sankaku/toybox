"""exp_pynv - PyNvVideoCodec で decode/encode を GPU 常駐にできるか確かめる。

確認したいこと:
  1. Windows で import できるか、API の形
  2. decode 結果を CPU を経由せず torch tensor にできるか (DLPack)
  3. torch の CUDA tensor をそのまま encode へ渡せるか
  4. その throughput が現行の pipe 経路より速いか
"""
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC60 = HERE.parent / "テスト60秒.mp4"

# PyNvVideoCodec は cudart64_12.dll 等を自力で見つけられない。
# CUDA Toolkit を入れずに済ませるため torch 同梱のものを使う。
import torch as _t  # noqa: E402
os.add_dll_directory(os.path.join(os.path.dirname(_t.__file__), "lib"))


def step1_api():
    import PyNvVideoCodec as nvc
    print("version:", getattr(nvc, "__version__", "?"))
    names = [n for n in dir(nvc) if not n.startswith("_")]
    print("公開名:", ", ".join(names))
    for n in ("CreateDecoder", "CreateEncoder", "SimpleDecoder",
              "PyNvDecoder", "PyNvEncoder", "PySimpleDecoder"):
        if hasattr(nvc, n):
            print(f"  {n}: あり")


def step2_decode():
    import torch
    import PyNvVideoCodec as nvc
    dec = nvc.SimpleDecoder(str(SRC60), gpu_id=0,
                            use_device_memory=True,
                            output_color_type=nvc.OutputColorType.RGBP)
    print("frame数:", len(dec))
    f0 = dec[0]
    t = torch.from_dlpack(f0)
    print("torch tensor:", t.shape, t.dtype, t.device, "contiguous",
          t.is_contiguous())
    n = 0
    t0 = time.perf_counter()
    for batch in dec:
        tt = torch.from_dlpack(batch)
        n += 1
        if n >= 1500:
            break
    torch.cuda.synchronize()
    el = time.perf_counter() - t0
    print(f"decode -> torch (GPU常駐): {n}f {el:.2f}s {n/el:.1f} fps")


def step2b_decode_iter():
    """ThreadedDecoder / batch API があればそちらも測る。"""
    import torch
    import PyNvVideoCodec as nvc
    if not hasattr(nvc, "ThreadedDecoder"):
        print("ThreadedDecoder なし")
        return
    dec = nvc.ThreadedDecoder(str(SRC60), buffer_size=10, cuda_context=0,
                              cuda_stream=0, use_device_memory=True,
                              output_color_type=nvc.OutputColorType.RGBP)
    n = 0
    t0 = time.perf_counter()
    while True:
        frames = dec.get_batch_frames(10)
        if not frames:
            break
        for fr in frames:
            torch.from_dlpack(fr)
            n += 1
    torch.cuda.synchronize()
    el = time.perf_counter() - t0
    print(f"ThreadedDecoder -> torch: {n}f {el:.2f}s {n/el:.1f} fps")


def step3_encode(fw=1440, fh=960, n=900):
    """torch CUDA tensor -> NVENC。CPU を一切経由しない encode。"""
    import torch
    import PyNvVideoCodec as nvc
    out = open(str(HERE / "_pynv_out.hevc"), "wb")
    enc = nvc.CreateEncoder(fw, fh, "NV12", False, codec="hevc",
                            preset="P5", gpu_id=0)
    # NV12 の CUDA tensor を作る (実際は SR 結果から作る)
    y = torch.randint(16, 235, (fh, fw), dtype=torch.uint8, device="cuda")
    uv = torch.randint(16, 235, (fh // 2, fw), dtype=torch.uint8,
                       device="cuda")
    nv12 = torch.cat([y.reshape(-1), uv.reshape(-1)]).contiguous()

    class DL:
        """PyNvVideoCodec は __dlpack__(stream) を位置引数で呼ぶが、
        torch の Tensor.__dlpack__ は stream をkeyword専用にしている。
        間に挟んで signature を合わせる。"""

        def __init__(self, t):
            self.t = t

        def __dlpack__(self, *a, **k):
            return self.t.__dlpack__()

        def __dlpack_device__(self):
            return self.t.__dlpack_device__()

    nv12 = DL(nv12)
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    nb = 0
    for _ in range(n):
        pkt = enc.Encode(nv12)
        if pkt:
            nb += len(bytearray(pkt))
            out.write(bytearray(pkt))
    pkt = enc.EndEncode()
    if pkt:
        out.write(bytearray(pkt))
    torch.cuda.synchronize()
    el = time.perf_counter() - t0
    out.close()
    print(f"torch CUDA tensor -> NVENC P5: {n}f {el:.2f}s {n/el:.1f} fps "
          f"({nb/1e6:.1f} MB)")


def step4_rgb_to_nv12(fw=1440, fh=960, n=900):
    """SR 出力 (RGB float/uint8 on GPU) -> NV12 変換の GPU コスト。"""
    import torch
    x = torch.rand((1, 3, fh, fw), device="cuda", dtype=torch.half)
    # BT.709 limited range
    m = torch.tensor([[0.1826, 0.6142, 0.0620],
                      [-0.1006, -0.3386, 0.4392],
                      [0.4392, -0.3989, -0.0403]], device="cuda",
                     dtype=torch.half)
    off = torch.tensor([16.0, 128.0, 128.0], device="cuda",
                       dtype=torch.half).view(1, 3, 1, 1)

    def conv(t):
        yuv = torch.einsum("ij,bjhw->bihw", m, t) * 255.0 + off
        yuv = yuv.clamp_(0, 255)
        yy = yuv[:, 0]
        uvp = torch.nn.functional.avg_pool2d(yuv[:, 1:], 2)
        uv = torch.stack([uvp[:, 0], uvp[:, 1]], dim=-1).reshape(
            1, fh // 2, fw)
        return (yy.to(torch.uint8).reshape(-1),
                uv.to(torch.uint8).reshape(-1))

    for _ in range(20):
        conv(x)
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    for _ in range(n):
        conv(x)
    torch.cuda.synchronize()
    el = time.perf_counter() - t0
    print(f"GPU RGB->NV12 変換のみ: {n}f {el:.2f}s {n/el:.1f} fps "
          f"({el/n*1000:.3f} ms/frame)")


def step5_d2h(fw=1440, fh=960, n=900):
    """D2H の帯域: bgr24 (4.15MB) vs nv12 (2.07MB)。"""
    import torch
    for name, nbytes in (("bgr24 4.15MB", fw * fh * 3),
                         ("nv12  2.07MB", fw * fh * 3 // 2)):
        g = torch.empty(nbytes, dtype=torch.uint8, device="cuda")
        c = torch.empty(nbytes, dtype=torch.uint8, device="cpu",
                        pin_memory=True)
        for _ in range(20):
            c.copy_(g, non_blocking=True)
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        for _ in range(n):
            c.copy_(g, non_blocking=True)
        torch.cuda.synchronize()
        el = time.perf_counter() - t0
        print(f"D2H {name}: {n/el:8.1f} fps  "
              f"{n*nbytes/el/1e9:.2f} GB/s  {el/n*1000:.3f} ms/frame")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    fns = {"api": step1_api, "dec": step2_decode, "dec2": step2b_decode_iter,
           "enc": step3_encode, "conv": step4_rgb_to_nv12, "d2h": step5_d2h}
    if what == "all":
        for k, fn in fns.items():
            print(f"\n--- {k} ---")
            try:
                fn()
            except Exception as exc:
                import traceback
                traceback.print_exc()
    else:
        fns[what]()
