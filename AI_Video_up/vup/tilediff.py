"""tile差分SR

前frameから変化した領域だけをmodelに通し、変わっていない領域は前frameのSR結果を
そのまま使う。halo(受容野分の余白)を付けて切るので、変化していない領域の出力は
全画面SRと一致する(実測: realesr-animevideov3で halo=20px のとき誤差0.00/255)。

halo分だけ余分に計算するため、変化tileが多い frame では全画面SRより高くつく。
そこで毎frameで見積りを取り、高くつくなら全画面SRへ落とす。
"""
import cv2
import numpy as np
import torch
import torch.nn.functional as F


def measure_receptive_field(model, scale, dtype=torch.half, device="cuda",
                            size=256, thresh=1.0 / 510):
    """入力の1画素を変えたとき出力に影響が出る範囲(入力換算の半径)を実測する。

    tileを切るときのhaloはこの半径以上でなければ、変えていない領域の出力まで
    ずれて継ぎ目になる。理論値(conv段数から出る値)ではなく実測を使うのは、
    段数が多いmodelでは寄与が減衰して実際の影響範囲がずっと狭いため。
    閾値は uint8 に丸めたとき差が出ない水準(0.5/255)に取る。
    """
    with torch.no_grad():
        base = torch.rand(1, 3, size, size, device=device, dtype=dtype)
        base = base.contiguous(memory_format=torch.channels_last)
        mod = base.clone()
        c = size // 2
        mod[0, :, c, c] = 1.0 - mod[0, :, c, c]
        a = model(base).float()
        b = model(mod).float()
        d = (a - b).abs().amax(dim=1)[0]
        ys, xs = torch.nonzero(d > thresh, as_tuple=True)
        if len(ys) == 0:
            return 0
        r = max(abs(ys.max().item() / scale - c), abs(ys.min().item() / scale - c),
                abs(xs.max().item() / scale - c), abs(xs.min().item() / scale - c))
        return int(r) + 1


class TileDiff:
    def __init__(self, model, scale, core=180, halo=None, thresh=2,
                 out_scale=None, device="cuda", dtype=torch.half):
        self.model = model
        if halo is None:
            halo = measure_receptive_field(model, scale, dtype=dtype,
                                           device=device) + 4
        self.scale = scale
        self.core = core
        self.halo = halo
        self.thresh = thresh
        self.device = device
        self.dtype = dtype
        self.out_scale = out_scale or scale
        self.ratio = self.out_scale / scale
        self.prev_in = None
        self.prev_sr = None          # (1,3,H*s,W*s) 出力空間のSR結果
        self.stat_tiles = 0          # 実行したtile枚数(面積換算)
        self.stat_px = 0.0           # modelに通した入力画素数の合計
        self.stat_full = 0           # 全画面SRへ落ちた回数
        self.stat_frames = 0
        self._pin = None

    # ------------------------------------------------------------ helpers
    def _to_t(self, bgr):
        x = torch.from_numpy(np.ascontiguousarray(bgr)).to(self.device)
        x = x.permute(2, 0, 1).unsqueeze(0).to(self.dtype).div_(255.0)
        return x.contiguous(memory_format=torch.channels_last)

    def _full(self, bgr):
        with torch.no_grad():
            return self.model(self._to_t(bgr)).clamp_(0, 1)

    def _emit(self, sr):
        with torch.no_grad():
            y = sr
            if self.ratio != 1.0:
                y = F.interpolate(y.float(), scale_factor=self.ratio,
                                  mode="bicubic", align_corners=False,
                                  antialias=self.ratio < 1.0)
            y = y.clamp(0, 1).mul_(255.0).round_().to(torch.uint8)
            y = y.squeeze(0).permute(1, 2, 0).contiguous()
            if self._pin is None or self._pin.shape != y.shape:
                self._pin = torch.empty(y.shape, dtype=torch.uint8,
                                        device="cpu", pin_memory=True)
            self._pin.copy_(y)
            # writer threadが書き出す間に次frameで上書きされないよう複製する
            return self._pin.numpy().copy()

    # ------------------------------------------------------------ main
    def __call__(self, bgr):
        h, w = bgr.shape[:2]
        s = self.scale
        c, ha = self.core, self.halo
        self.stat_frames += 1

        if self.prev_in is None:
            self.prev_sr = self._full(bgr)
            self.prev_in = bgr.copy()
            self.stat_full += 1
            self.stat_px += h * w
            return self._emit(self.prev_sr)

        d = cv2.absdiff(bgr, self.prev_in).max(axis=2)
        changed = d > self.thresh
        if not changed.any():
            return self._emit(self.prev_sr)

        ys = list(range(0, h, c))
        xs = list(range(0, w, c))
        need = []
        for y in ys:
            for x in xs:
                y1, x1 = min(y + c, h), min(x + c, w)
                if changed[max(0, y - ha):min(h, y1 + ha),
                           max(0, x - ha):min(w, x1 + ha)].any():
                    need.append((y, x, y1, x1))

        # 見積り: tile方式でmodelに通す入力画素数 vs 全画面
        tile_px = sum((min(y1 + ha, h) - max(0, y - ha)) *
                      (min(x1 + ha, w) - max(0, x - ha))
                      for (y, x, y1, x1) in need)
        if tile_px >= h * w * 0.85:
            self.prev_sr = self._full(bgr)
            self.prev_in = bgr.copy()
            self.stat_full += 1
            self.stat_px += h * w
            return self._emit(self.prev_sr)

        pad = np.pad(bgr, ((ha, ha), (ha, ha), (0, 0)), mode="edge")
        batch = []
        meta = []
        for (y, x, y1, x1) in need:
            py, px = y, x                       # padded座標では +ha されるが
            sub = pad[py:py + (y1 - y) + 2 * ha,
                      px:px + (x1 - x) + 2 * ha]
            batch.append(sub)
            meta.append((y, x, y1, x1, sub.shape[0], sub.shape[1]))

        # 同一形状ごとにまとめてbatch実行
        groups = {}
        for i, m in enumerate(meta):
            groups.setdefault((m[4], m[5]), []).append(i)
        with torch.no_grad():
            for shape, idxs in groups.items():
                arr = np.stack([batch[i] for i in idxs])
                t = torch.from_numpy(np.ascontiguousarray(arr)).to(self.device)
                t = t.permute(0, 3, 1, 2).to(self.dtype).div_(255.0)
                t = t.contiguous(memory_format=torch.channels_last)
                o = self.model(t).clamp_(0, 1)
                for k, i in enumerate(idxs):
                    y, x, y1, x1 = meta[i][:4]
                    self.prev_sr[0, :, y * s:y1 * s, x * s:x1 * s] = \
                        o[k, :, ha * s:ha * s + (y1 - y) * s,
                          ha * s:ha * s + (x1 - x) * s]
        # 参照frameは「SRをやり直した領域だけ」更新する。
        # 全面更新すると、閾値未満の変化が毎frame取りこぼされて累積し、
        # 前frameの結果を使い続ける領域が徐々にずれていく。
        for (y, x, y1, x1) in need:
            self.prev_in[y:y1, x:x1] = bgr[y:y1, x:x1]
        self.stat_tiles += len(need)
        self.stat_px += tile_px
        return self._emit(self.prev_sr)

    def report(self):
        if not self.stat_frames:
            return ""
        return (f"tile差分: frame {self.stat_frames}  全画面SRへfallback {self.stat_full}回"
                f"  model入力画素 {self.stat_px / self.stat_frames:.0f}/frame")
