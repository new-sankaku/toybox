"""GMFSS_Fortuna(base)を動かす。RIFE 以外の対照。

RIFE と違って TensorRT には載せていない(torch fp16)。GMFlow(transformer)を
含み、ONNX へ出すのに手が要るためで、**速度は torch のままの値**です。
RIFE 側の torch 値と比べたい場合は `--torch` で測り直せます。

構成: GMFlow で双方向 flow → MetricNet で信頼度 → FeatureNet の特徴を
softsplat(forward warp)で t へ運び → GridNet で合成。
flow は pair につき1回で、時刻ごとに変わるのは合成だけです
(`reuse()` と `inference()` が分かれています)。

重み: huggingface `NexusAex/GMFSS_Fortuna` の GMFSS/train_log/
code: github `98mxr/GMFSS_Fortuna`(CuPy無しの softsplat_torch へ落ちます)
"""
import sys
from pathlib import Path

import torch
import torch.nn.functional as F

import vfilib as V

HERE = Path(__file__).resolve().parent / "gmfss"


class Gmfss:
    name = "GMFSS_Fortuna_b"

    def __init__(self, w, h, fp16=True, scale=1.0, log=V.log):
        if str(HERE) not in sys.path:
            sys.path.insert(0, str(HERE))
        from model.GMFSS_infer_b import Model
        self.w, self.h, self.scale = w, h, scale
        self.dtype = torch.float32
        tmp = max(64, int(64 / scale))
        self.ph = ((h - 1) // tmp + 1) * tmp
        self.pw = ((w - 1) // tmp + 1) * tmp
        m = Model()
        m.load_model(str(HERE / "train_log"), -1)
        m.eval()
        m.device()
        # 手で .half() すると、position embedding や正規化定数が fp32 のまま
        # 残って「input Float / weight Half」で落ちる箇所が次々に出る。
        # autocast なら conv/linear だけ fp16 で走り、型の格上げは torch が畳む。
        self.fp16 = fp16
        self.m = m
        self._reuse = None
        self._key = None
        log(f"  {self.name}: 読み込み完了 (pad {self.pw}x{self.ph} "
            f"{'fp16' if fp16 else 'fp32'} scale={scale})")

    def _prep(self, f):
        x = f.permute(2, 0, 1).flip(0).to(self.dtype).div_(255.0).unsqueeze(0)
        return F.pad(x, (0, self.pw - self.w, 0, self.ph - self.h))

    @torch.no_grad()
    def predict(self, f0, f1, tau, key=None):
        """uint8 BGR HWC(cuda) 2枚 -> uint8 BGR HWC。

        同じ pair で tau だけ変える場合は key を渡すと flow を使い回します。
        """
        i0, i1 = self._prep(f0), self._prep(f1)
        with torch.autocast("cuda", dtype=torch.float16, enabled=self.fp16):
            if key is None or key != self._key:
                self._reuse = self.m.reuse(i0, i1, self.scale)
                self._key = key
            out = self.m.inference(i0, i1, self._reuse, tau)
        out = out.float()[:, :, :self.h, :self.w]
        return (out[0].flip(0).permute(1, 2, 0).float().clamp(0, 1)
                .mul(255.0).round().to(torch.uint8))
