"""品質枠の VFI model を1つの interface へ揃える。

## signature

    m = vfimodels.build(name, w=1920, h=1080)
    y = m.predict(f0, f1, tau, key=None)

    f0, f1 : uint8 BGR HWC の cuda tensor (H,W,3)。numpy でも可(内部で載せる)
    tau    : 0<tau<1 の float。f0 を時刻0、f1 を時刻1 とした時の出力時刻
    key    : 同じ pair で tau だけ変える時に渡すと中間結果を使い回す model がある
             (GMFSS 系の flow)。省略可
    返り値 : uint8 BGR HWC の cuda tensor (H,W,3)

    m.name        model の表示名
    m.tau_aware   tau を実際に見るか(False の物は tau を無視する)
    m.impl        実装の一言(torch fp16 / TensorRT など)

## 1 process 1 model

各 repo が `models` `model` `config` という同名の package を自分の root から
import する。同じ process で2つ載せると sys.modules が衝突する。
**必ず model ごとに process を分けてください**(m2_bench.py がそうしています)。

## 収録

| name              | 素性 | 重み |
|---|---|---|
| gmfss_union       | GMFSS + RIFE 合流版。anime 向け | DRBA 同梱 |
| gmfss_fortuna_b   | GMFSS_Fortuna base | vfi/gmfss |
| rife426heavy_t    | RIFE v4.26 heavy の torch 実装 | DRBA 同梱 |
| gimmvfi_r_p       | GIMM-VFI RAFT版 LPIPS 学習 | GSean/GIMM-VFI |
| gimmvfi_f_p       | GIMM-VFI FlowFormer版 LPIPS 学習 | 同上 |
| emavfi_t          | EMA-VFI 任意時刻版 | xmanifold/emavfi |
| film              | FILM(Google)の torchscript 移植 | dajes release |
| ifrnet_gopro      | IFRNet GoPro | vfi/ifrnet |
"""
import os
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

# GIMM-VFI と DRBA の softsplat は cupy で kernel を JIT する。cupy は
# nvrtc64_120_0.dll を探すが、この環境の CUDA toolkit は v11.3 で持っていない。
# torch が bundle している 12.x の dll を探索 path へ足すと通る。
# CUDA_HOME を先に埋めるのは、softsplat が空なら v11.3 を入れてしまうため。
try:
    os.add_dll_directory(str(Path(torch.__file__).resolve().parent / "lib"))
except (OSError, AttributeError):
    pass
os.environ.setdefault("CUDA_HOME", str(Path(torch.__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent
MODELS = ROOT / "models"
VFI1 = ROOT.parent / "vfi"


def to_gpu(a):
    if torch.is_tensor(a):
        return a
    return torch.from_numpy(np.ascontiguousarray(a)).cuda()


def _bgr_to_rgb_f32(f, ph, pw, h, w):
    """uint8 BGR HWC(cuda) -> float32 RGB (1,3,ph,pw) 0..1。右下へ pad。"""
    x = to_gpu(f).permute(2, 0, 1).flip(0).float().div_(255.0).unsqueeze(0)
    return F.pad(x, (0, pw - w, 0, ph - h))


def _rgb_f32_to_bgr(x, h, w):
    x = x.float()[:, :, :h, :w]
    return (x[0].flip(0).permute(1, 2, 0).clamp_(0, 1)
            .mul_(255.0).round_().to(torch.uint8))


def _pad_to(v, m):
    return ((v - 1) // m + 1) * m


# ---------------------------------------------------------------- DRBA 系

class _DrbaBase:
    """DRBA repo(models/ 以下)を使う wrapper の共通部。"""
    root = MODELS / "DRBA"

    def _enter(self):
        if str(self.root) not in sys.path:
            sys.path.insert(0, str(self.root))


class GmfssUnion(_DrbaBase):
    """GMFSS_union: GMFlow + MetricNet + softsplat + GridNet に RIFE を合流。

    `inference(I0, I1, reuse, timestep0=t, timestep1=1-t, rife=...)` で任意時刻。
    timestep0/1 は per-pixel の map も取れる(DRBA が使う口)が、ここでは
    scalar を渡す。
    """
    name = "GMFSS_union"
    tau_aware = True
    impl = "torch fp16 autocast"

    def __init__(self, w, h, scale=1.0, log=print):
        self._enter()
        import os
        from models.model_gmfss_union.GMFSS import Model
        from models.rife_426_heavy.IFNet_HDv3 import IFNet
        from models.utils.tools import convert
        wdir = self.root / "weights" / "train_log_gmfss_union"
        self.w, self.h, self.scale = w, h, scale
        self.pw, self.ph = _pad_to(w, 128), _pad_to(h, 128)
        m = Model()
        m.load_model(str(wdir), -1)
        m.device(torch.device("cuda"))
        m.eval()
        self.m = m
        self.ifnet = IFNet().cuda().eval()
        self.ifnet.load_state_dict(
            convert(torch.load(os.path.join(str(wdir), "rife.pkl"), map_location="cpu")),
            strict=False)
        self.scale_list = [16 / scale, 8 / scale, 4 / scale, 2 / scale, 1 / scale]
        self._reuse = self._key = None
        log(f"  {self.name}: 読み込み完了 (pad {self.pw}x{self.ph} scale={scale})")

    @torch.inference_mode()
    def predict(self, f0, f1, tau, key=None):
        I0 = _bgr_to_rgb_f32(f0, self.ph, self.pw, self.h, self.w)
        I1 = _bgr_to_rgb_f32(f1, self.ph, self.pw, self.h, self.w)
        with torch.autocast("cuda", dtype=torch.float16):
            if key is None or key != self._key:
                self._reuse = self.m.reuse(I0, I1, self.scale)
                self._key = key
            I0s = F.interpolate(I0, scale_factor=0.5, mode="bilinear", align_corners=False)
            I1s = F.interpolate(I1, scale_factor=0.5, mode="bilinear", align_corners=False)
            rife = self.ifnet(torch.cat((I0s, I1s), 1), timestep=tau,
                              scale_list=self.scale_list)[0]
            out = self.m.inference(I0, I1, self._reuse, timestep0=tau,
                                   timestep1=1 - tau, rife=rife)
        return _rgb_f32_to_bgr(out, self.h, self.w)


class Rife426HeavyTorch(_DrbaBase):
    """RIFE v4.26 heavy の torch 実装。TensorRT 版との対照と DRBA の土台。"""
    name = "RIFE_v4.26_heavy_torch"
    tau_aware = True
    impl = "torch fp16 autocast"

    def __init__(self, w, h, scale=1.0, log=print):
        self._enter()
        import os
        from models.rife_426_heavy.IFNet_HDv3 import IFNet
        from models.utils.tools import convert
        wdir = self.root / "weights" / "train_log_rife_426_heavy"
        self.w, self.h = w, h
        self.pw, self.ph = _pad_to(w, 64), _pad_to(h, 64)
        self.ifnet = IFNet().cuda().eval()
        self.ifnet.load_state_dict(
            convert(torch.load(os.path.join(str(wdir), "flownet.pkl"), map_location="cpu")),
            strict=False)
        self.scale_list = [16 / scale, 8 / scale, 4 / scale, 2 / scale, 1 / scale]
        log(f"  {self.name}: 読み込み完了 (pad {self.pw}x{self.ph})")

    @torch.inference_mode()
    def predict(self, f0, f1, tau, key=None):
        I0 = _bgr_to_rgb_f32(f0, self.ph, self.pw, self.h, self.w)
        I1 = _bgr_to_rgb_f32(f1, self.ph, self.pw, self.h, self.w)
        with torch.autocast("cuda", dtype=torch.float16):
            out = self.ifnet(torch.cat((I0, I1), 1), timestep=tau,
                             scale_list=self.scale_list)[0]
        return _rgb_f32_to_bgr(out, self.h, self.w)


# ---------------------------------------------------------------- GIMM-VFI

class GimmVfi:
    """GIMM-VFI(NeurIPS 2024)。双方向 flow から時空間の motion latent を作り、
    座標入力の INR で **任意時刻の flow を直接吐く**。任意 tau が設計の中心。

    ds_factor は flow を測る解像度の倍率。相関 volume が (HW/64)^2 で効くので
    **1080p では 1.0 が 12GB に載らない**(3.97GB の 1発で OOM)。実測で載るのは
    0.5(peak 5.12GB / 827ms)。既定はそれ。
    """
    tau_aware = True
    impl = "torch fp32(autocast不可)"
    root = MODELS / "GIMMVFI"

    def __init__(self, w, h, variant="r", ds_factor=0.5, log=print):
        src = self.root / "src"
        for p in (str(src), str(self.root)):
            if p not in sys.path:
                sys.path.insert(0, p)
        import omegaconf
        from models import create_model
        self.name = f"GIMM-VFI-{variant.upper()}-P"
        self.w, self.h, self.ds_factor = w, h, ds_factor
        self.pw, self.ph = _pad_to(w, 32), _pad_to(h, 32)
        cfg_path = self.root / "configs" / "gimmvfi" / f"gimmvfi_{variant}_arb.yaml"
        ckpt = self.root / "pretrained_ckpt" / f"gimmvfi_{variant}_arb_lpips.pt"
        from utils.config import augment_arch_defaults
        config = omegaconf.OmegaConf.load(cfg_path)
        # yaml は差分だけ。既定値(fwarp_type など)は configs.py 側にある
        config.arch = augment_arch_defaults(config.arch)
        self._fix_paths(config)
        # RAFT/FlowFormer の重み path は config ではなく repo の中に
        # 'pretrained_ckpt/...' と直書きされている。cwd を移して読ませる
        cwd = os.getcwd()
        os.chdir(str(self.root))
        try:
            model, _ = create_model(config.arch)
        finally:
            os.chdir(cwd)
        sd = torch.load(ckpt, map_location="cpu")
        model.load_state_dict(sd["state_dict"], strict=True)
        self.m = model.cuda().eval()
        log(f"  {self.name}: 読み込み完了 (pad {self.pw}x{self.ph} ds={ds_factor})")

    def _fix_paths(self, node):
        import omegaconf
        if isinstance(node, omegaconf.DictConfig):
            for k in node:
                v = node[k]
                if isinstance(v, str) and v.startswith("pretrained_ckpt/"):
                    node[k] = str(self.root / v)
                else:
                    self._fix_paths(v)
        elif isinstance(node, omegaconf.ListConfig):
            for v in node:
                self._fix_paths(v)

    @torch.inference_mode()
    def predict(self, f0, f1, tau, key=None):
        I0 = _bgr_to_rgb_f32(f0, self.ph, self.pw, self.h, self.w)
        I1 = _bgr_to_rgb_f32(f1, self.ph, self.pw, self.h, self.w)
        xs = torch.cat((I0.unsqueeze(2), I1.unsqueeze(2)), dim=2)
        coord = [(self.m.sample_coord_input(1, xs.shape[-2:], [tau],
                                            device=xs.device,
                                            upsample_ratio=self.ds_factor), None)]
        t = [tau * torch.ones(1, device=xs.device, dtype=torch.float)]
        out = self.m(xs, coord, t=t, ds_factor=self.ds_factor)["imgt_pred"][0]
        return _rgb_f32_to_bgr(out, self.h, self.w)


# ---------------------------------------------------------------- EMA-VFI

class EmaVfi:
    """EMA-VFI(CVPR 2023)の任意時刻版 ours_t。frame 間 attention で
    motion と appearance を同時に取る hybrid CNN/Transformer。"""
    name = "EMA-VFI_t"
    tau_aware = True
    impl = "torch fp32 (TTA無し)"
    root = MODELS / "EMAVFI"

    def __init__(self, w, h, small=False, tta=False, log=print):
        if str(self.root) not in sys.path:
            sys.path.insert(0, str(self.root))
        import config as cfg
        from Trainer import Model
        if small:
            self.name = "EMA-VFI_small_t"
            cfg.MODEL_CONFIG["LOGNAME"] = "ours_small_t"
            cfg.MODEL_CONFIG["MODEL_ARCH"] = cfg.init_model_config(F=16, depth=[2, 2, 2, 2, 2])
        else:
            cfg.MODEL_CONFIG["LOGNAME"] = "ours_t"
            cfg.MODEL_CONFIG["MODEL_ARCH"] = cfg.init_model_config(F=32, depth=[2, 2, 2, 4, 4])
        import os
        cwd = os.getcwd()
        os.chdir(str(self.root))          # load_model が ckpt/ を相対で読む
        try:
            m = Model(-1)
            m.load_model()
        finally:
            os.chdir(cwd)
        m.eval()
        m.device()
        self.m, self.tta = m, tta
        self.w, self.h = w, h
        self.pw, self.ph = _pad_to(w, 32), _pad_to(h, 32)
        log(f"  {self.name}: 読み込み完了 (pad {self.pw}x{self.ph} TTA={tta})")

    @torch.inference_mode()
    def predict(self, f0, f1, tau, key=None):
        I0 = _bgr_to_rgb_f32(f0, self.ph, self.pw, self.h, self.w)
        I1 = _bgr_to_rgb_f32(f1, self.ph, self.pw, self.h, self.w)
        out = self.m.inference(I0, I1, TTA=self.tta, timestep=tau, fast_TTA=self.tta)
        return _rgb_f32_to_bgr(out, self.h, self.w)


# ---------------------------------------------------------------- FILM

class Film:
    """FILM(Google, ECCV2022)の torchscript 移植。大変位に強いのが売り。

    signature は `model(img0, img1, dt)` で dt を取るが、**元論文の学習は
    t=0.5 のみ**。任意 tau を本当に見るかは実測で確かめる(m4_tau.py)。
    """
    name = "FILM"
    tau_aware = None          # 実測で決める
    impl = "torchscript fp16"
    root = MODELS / "FILM"

    def __init__(self, w, h, half=True, log=print):
        self.w, self.h, self.half = w, h, half
        self.pw, self.ph = _pad_to(w, 64), _pad_to(h, 64)
        m = torch.jit.load(str(self.root / "film_net_fp32.pt"), map_location="cpu")
        m.eval()
        self.dtype = torch.float16 if half else torch.float32
        self.m = m.to(device="cuda", dtype=self.dtype)
        log(f"  {self.name}: 読み込み完了 (pad {self.pw}x{self.ph} "
            f"{'fp16' if half else 'fp32'})")

    @torch.inference_mode()
    def predict(self, f0, f1, tau, key=None):
        I0 = _bgr_to_rgb_f32(f0, self.ph, self.pw, self.h, self.w).to(self.dtype)
        I1 = _bgr_to_rgb_f32(f1, self.ph, self.pw, self.h, self.w).to(self.dtype)
        dt = I0.new_full((1, 1), float(tau))
        out = self.m(I0, I1, dt)
        return _rgb_f32_to_bgr(out, self.h, self.w)


# ---------------------------------------------------------------- vfi/ の資産

class GmfssFortunaB:
    name = "GMFSS_Fortuna_b"
    tau_aware = True
    impl = "torch fp16 autocast"

    def __init__(self, w, h, scale=1.0, log=print):
        if str(VFI1) not in sys.path:
            sys.path.insert(0, str(VFI1))
        import gmfsslib
        self.m = gmfsslib.Gmfss(w, h, fp16=True, scale=scale, log=log)

    def predict(self, f0, f1, tau, key=None):
        return self.m.predict(f0, f1, tau, key)


class IfrnetGoPro:
    name = "IFRNet_GoPro"
    tau_aware = True
    impl = "torch fp16 autocast"

    def __init__(self, w, h, log=print):
        if str(VFI1) not in sys.path:
            sys.path.insert(0, str(VFI1))
        import ifrnetlib
        self.m = ifrnetlib.Ifrnet(w, h, fp16=True, log=log)

    def predict(self, f0, f1, tau, key=None):
        return self.m.predict(f0, f1, tau, key)


class RifeTrt:
    """既存の TensorRT engine(vfi/rifelib)。速度枠の対照。"""
    tau_aware = True
    impl = "TensorRT fp16"

    def __init__(self, w, h, version="v4.26_heavy", log=print):
        if str(VFI1) not in sys.path:
            sys.path.insert(0, str(VFI1))
        import rifelib
        self.R = rifelib
        self.name = f"RIFE_{version}_trt"
        self.m = rifelib.Rife(version, w, h, fp16=True)

    def predict(self, f0, f1, tau, key=None):
        self.R.pack(to_gpu(f0), to_gpu(f1), float(tau), self.m.dtype, out=self.m.dev_in)
        return self.R.unpack(self.m.infer())


# ---------------------------------------------------------------- baseline

class Hold:
    name, tau_aware, impl = "hold", False, "-"

    def __init__(self, w, h, log=print):
        pass

    def predict(self, f0, f1, tau, key=None):
        return to_gpu(f0)


class Blend:
    name, tau_aware, impl = "blend", True, "-"

    def __init__(self, w, h, log=print):
        pass

    def predict(self, f0, f1, tau, key=None):
        return (to_gpu(f0).float() * (1 - tau) + to_gpu(f1).float() * tau
                ).round_().clamp_(0, 255).to(torch.uint8)


# ---------------------------------------------------------------- 生成

BUILDERS = {
    "hold": lambda w, h, log: Hold(w, h, log),
    "blend": lambda w, h, log: Blend(w, h, log),
    "gmfss_union": lambda w, h, log: GmfssUnion(w, h, log=log),
    "gmfss_fortuna_b": lambda w, h, log: GmfssFortunaB(w, h, log=log),
    "rife426heavy_t": lambda w, h, log: Rife426HeavyTorch(w, h, log=log),
    "rife426heavy_trt": lambda w, h, log: RifeTrt(w, h, "v4.26_heavy", log=log),
    "rife425lite_trt": lambda w, h, log: RifeTrt(w, h, "v4.25_lite", log=log),
    "rife426_trt": lambda w, h, log: RifeTrt(w, h, "v4.26", log=log),
    "rife46_trt": lambda w, h, log: RifeTrt(w, h, "v4.6", log=log),
    "gimmvfi_r_p": lambda w, h, log: GimmVfi(w, h, "r", log=log),
    "gimmvfi_f_p": lambda w, h, log: GimmVfi(w, h, "f", log=log),
    "emavfi_t": lambda w, h, log: EmaVfi(w, h, log=log),
    "emavfi_small_t": lambda w, h, log: EmaVfi(w, h, small=True, log=log),
    "film": lambda w, h, log: Film(w, h, log=log),
    "ifrnet_gopro": lambda w, h, log: IfrnetGoPro(w, h, log=log),
}


def build(name, w=1920, h=1080, log=print):
    if name not in BUILDERS:
        raise KeyError(f"未知の model: {name}. 使えるのは {sorted(BUILDERS)}")
    return BUILDERS[name](w, h, log)
