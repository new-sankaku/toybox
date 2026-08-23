"""使える model の一覧と、重みの自動download

重みは models/ に置く。無ければ URL から取得する。
読み込みは spandrel に任せる（52 arch対応）ので、arch実装を足さずに model を増やせる。
"""
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODELS_DIR = HERE / "models"

SIROSKY = "https://github.com/Sirosky/Upscale-Hub/releases/download"
XINNTAO = "https://github.com/xinntao/Real-ESRGAN/releases/download"

# 名前: (file名, URL, 説明)
REGISTRY = {
    # --- SD anime (720x480 の DVD 品質) 向け。倍率は native x2 ---
    # sd-janai は ONNX でしか配布されていないため onnx_to_pth.py で変換した物。
    # 中身は realesr-animevideov3 と同一構成(64feat/16conv)の x2 版。
    "sd-janai": (
        "2x_AnimeJaNai_SD_V1beta34_Compact.pth",
        None,
        "AnimeJaNai SD V1beta34 Compact 0.60M。SD anime専用に訓練された唯一のAnimeJaNai",
    ),
    "sd-fast": (
        "2x_Ani4Kv2_G6i2_UltraCompact_105K.pth",
        f"{SIROSKY}/Ani4K-v2/2x_Ani4Kv2_G6i2_UltraCompact_105K.pth",
        "UltraCompact 0.30M。最速",
    ),
    "sd": (
        "2x_AniSD_AC_G6i2a_Compact_72500.pth",
        f"{SIROSKY}/AniSD/2x_AniSD_AC_G6i2a_Compact_72500.pth",
        "Compact 0.60M。SD anime専用に訓練",
    ),
    "sd-span": (
        "2x_AniSD_G6i1_SPAN_215K.pth",
        f"{SIROSKY}/AniSD/2x_AniSD_G6i1_SPAN_215K.pth",
        "SPAN 2.22M。Compactより高品質",
    ),
    "sd-hq": (
        "2x_AniSD_RealPLKSR_140K.pth",
        f"{SIROSKY}/AniSD-RealPLKSR/2x_AniSD_RealPLKSR_140K.pth",
        "RealPLKSR 7.37M。SD anime向けで最高品質の実用枠",
    ),
    "sd-max": (
        "2x_AniSD_DC_DAT2_97500.pth",
        f"{SIROSKY}/AniSD/2x_AniSD_DC_DAT2_97500.pth",
        "DAT2 11.06M。極めて遅い",
    ),
    "toon": (
        "2x_AniToon_RPLKSRS_242500.pth",
        f"{SIROSKY}/AniToon/2x_AniToon_RPLKSRS_242500.pth",
        "RealPLKSR small 2.35M。2025年の新しい方。western toon寄り",
    ),
    # --- 汎用 (Real-ESRGAN 系、x4) ---
    "anime": (
        "realesr-animevideov3.pth",
        f"{XINNTAO}/v0.2.5.0/realesr-animevideov3.pth",
        "Real-ESRGAN anime動画向け x4 (2022年)",
    ),
    "anime-hq": (
        "RealESRGAN_x4plus_anime_6B.pth",
        f"{XINNTAO}/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth",
        "Real-ESRGAN anime x4 の重い方 (2021年)",
    ),
    "photo": (
        "realesr-general-x4v3.pth",
        f"{XINNTAO}/v0.2.5.0/realesr-general-x4v3.pth",
        "実写向け x4 の軽い方",
    ),
    "photo-hq": (
        "RealESRGAN_x4plus.pth",
        f"{XINNTAO}/v0.1.0/RealESRGAN_x4plus.pth",
        "実写向け x4 の重い方",
    ),
}


def resolve(name_or_path):
    """model名またはfile pathを重みのpathに解決する。無ければdownloadする。"""
    if name_or_path in REGISTRY:
        fname, url, _ = REGISTRY[name_or_path]
        path = MODELS_DIR / fname
        if not path.exists() and url is None:
            raise SystemExit(
                f"{name_or_path} の重みがありません: {path}\n"
                f"ONNXからの変換が必要です。onnx_to_pth.py を使ってください。")
        if not path.exists():
            MODELS_DIR.mkdir(parents=True, exist_ok=True)
            print(f"model を download します: {url}", flush=True)
            urllib.request.urlretrieve(url, path)
            print(f"  保存しました: {path}", flush=True)
        return path
    path = Path(name_or_path)
    if not path.exists():
        raise SystemExit(f"model が見つかりません: {name_or_path}\n"
                         f"使える名前: {', '.join(REGISTRY)}")
    return path


def fix_span_reparam(model):
    """SPAN の Conv3XC が推論のたびに重みを再融合するのを止める。

    spandrel の Conv3XC.forward は eval 時にも毎回 update_params() を呼び、
    3本のconvを1本へ畳んで eval_conv へ書き戻している。重みは変わらないので
    起動時1回で済む処理を frame ごとにやり直している。この model には
    Conv3XC が20個ある。

    実害は2つ。(1) 毎frame 20回分の重み融合が乗る。(2) weightへの .data 代入と
    permute/flip のせいで torch.compile が graph を作れず落ちる。

    起動時に1回だけ融合し、以後は eval_conv を使うだけにすると、実測で
    eager 29.8 -> 71.9 fps、compile は落ちる -> 99.8 fps になる。
    出力は実frame 8枚すべてで最大画素差0、完全に一致する。
    """
    import torch.nn.functional as F
    targets = [m for m in model.modules() if type(m).__name__ == "Conv3XC"]
    if not targets:
        return 0
    for m in targets:
        m.update_params()

    def forward(self, x):
        out = self.eval_conv(x)
        if self.has_relu:
            out = F.leaky_relu(out, negative_slope=0.05)
        return out

    type(targets[0]).forward = forward
    return len(targets)


def _fast_load_compact(path, device, half):
    """SRVGGNetCompact だけ spandrel を通さずに読む。

    `import spandrel` は52 arch全部を読み込むため単体で3.7秒掛かる。
    起動が10秒のうち3.7秒である以上、既定modelの経路からは外す。
    形が少しでも一致しなければ None を返して spandrel へ落とす。
    """
    import torch
    from srvgg import SRVGGNetCompact
    try:
        sd = torch.load(path, map_location="cpu", weights_only=True)
    except Exception:
        return None
    if isinstance(sd, dict):
        # 順序は spandrel の canonicalize_state_dict と完全に同じにする。
        # basicsr形式は params と params_ema の両方を持つ事があり、採るのはEMA側。
        # 順序を間違えると重みが最大0.022ズレ、出力が0.18ズレる(実測)。
        for k in ("model_state_dict", "state_dict", "params_ema", "params-ema",
                  "params", "model", "net"):
            if k in sd and isinstance(sd[k], dict):
                sd = sd[k]
                break
    if not isinstance(sd, dict) or not sd:
        return None
    if not all(k.startswith("body.") for k in sd):
        return None
    idx = sorted({int(k.split(".")[1]) for k in sd})
    conv = [i for i in idx if sd.get(f"body.{i}.weight") is not None
            and sd[f"body.{i}.weight"].dim() == 4]
    prelu = [i for i in idx if i not in conv]
    # conv は偶数番、PReLU は奇数番で交互、最後は conv で終わる
    if conv != list(range(0, max(idx) + 1, 2)) or prelu != list(range(1, max(idx), 2)):
        return None
    w0 = sd["body.0.weight"]
    wl = sd[f"body.{conv[-1]}.weight"]
    num_feat, num_in_ch = w0.shape[0], w0.shape[1]
    out_total = wl.shape[0]
    if out_total % num_in_ch != 0:
        return None
    up2 = out_total // num_in_ch
    up = int(round(up2 ** 0.5))
    if up * up != up2 or up < 1:
        return None
    model = SRVGGNetCompact(num_in_ch=num_in_ch, num_out_ch=num_in_ch,
                            num_feat=num_feat, num_conv=len(conv) - 2, upscale=up)
    try:
        model.load_state_dict(sd, strict=True)
    except Exception:
        return None
    model = model.eval().to(device)
    if half:
        model.half()
    return model, up, "RealESRGAN Compact"


def load_model(path, device="cuda", half=True):
    """arch は重みの形から自動判定する。

    SRVGGNetCompact だけは自前実装で読む(spandrelのimportが3.7秒掛かるため)。
    それ以外は spandrel に任せる(52 arch対応)。

    戻り値は (model, scale, arch名)。
    """
    fast = _fast_load_compact(path, device, half)
    if fast is not None:
        return fast

    import spandrel
    try:
        import spandrel_extra_arches
        # 2回目以降のinstall()は重複でraiseするので無視する
        spandrel_extra_arches.install(ignore_duplicates=True)
    except ImportError:
        pass
    desc = spandrel.ModelLoader().load_from_file(str(path))
    model = desc.model.eval().to(device)
    if half:
        model.half()
    n = fix_span_reparam(model)
    name = desc.architecture.name
    if n:
        name += f"(Conv3XC {n}個の再融合を起動時1回へ)"
    return model, desc.scale, name


def describe():
    lines = []
    for name, (fname, _, note) in REGISTRY.items():
        mark = "有" if (MODELS_DIR / fname).exists() else "未取得"
        lines.append(f"  {name:10s} [{mark:6s}] {note}")
    return "\n".join(lines)
