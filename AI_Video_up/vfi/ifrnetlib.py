"""IFRNet(RIFE 以外の対照 2件目)。torch fp16。

code: github ltkong218/IFRNet の models/IFRNet.py
重み: huggingface pavlichenko/ifrnet_gopro の IFRNet_GoPro.pth

**Vimeo90K の重みは tau を無視します。** Vimeo90K の三つ組は常に真ん中なので、
学習中 t=0.5 しか見ておらず、embt が信号になっていません
(実測: tau=0 と tau=1 の出力の最大差 2.2e-6)。
任意時刻が要るので GoPro(8x学習)の重みを既定にします(同 0.54)。
H, W は 16 の倍数が要るので 32 の倍数へ pad します。
"""
import sys
from pathlib import Path

import torch
import torch.nn.functional as F

import vfilib as V

HERE = Path(__file__).resolve().parent / "ifrnet"


class Ifrnet:
    name = "IFRNet_Vimeo90K"

    def __init__(self, w, h, fp16=True, weights="IFRNet_GoPro.pth", log=V.log):
        if str(HERE) not in sys.path:
            sys.path.insert(0, str(HERE))
        from models.IFRNet import Model
        self.w, self.h, self.fp16 = w, h, fp16
        self.ph = ((h - 1) // 32 + 1) * 32
        self.pw = ((w - 1) // 32 + 1) * 32
        m = Model().cuda().eval()
        self.name = f"IFRNet_{Path(weights).stem.split('_')[-1]}"
        sd = torch.load(HERE / weights, map_location="cuda")
        m.load_state_dict(sd)
        self.m = m
        log(f"  {self.name}: 読み込み完了 (pad {self.pw}x{self.ph} "
            f"{'fp16' if fp16 else 'fp32'})")

    def _prep(self, f):
        x = f.permute(2, 0, 1).flip(0).float().div_(255.0).unsqueeze(0)
        return F.pad(x, (0, self.pw - self.w, 0, self.ph - self.h))

    @torch.no_grad()
    def predict(self, f0, f1, tau, key=None):
        i0, i1 = self._prep(f0), self._prep(f1)
        embt = torch.full((1, 1, 1, 1), float(tau), device="cuda")
        with torch.autocast("cuda", dtype=torch.float16, enabled=self.fp16):
            out = self.m.inference(i0, i1, embt)
        out = out.float()[:, :, :self.h, :self.w]
        return (out[0].flip(0).permute(1, 2, 0).clamp(0, 1)
                .mul(255.0).round().to(torch.uint8))
