"""flow の scale を下げた時の品質の代価。速度は s7 が測ってある。

scale は v1実装(rifev1.py)だけが掛けられる。同じ実装の scale=1.0 を基準に
0.5 / 0.25 を測るので、実装差は入らない。

試験集合は m1_testset.py が作った `results/testset_<clip>.npy`
(絵 D0,D2 から真ん中の絵 D1 を tau で作り、本物と比べる)。
metric は m3_bench.py と同じ GPU 版で、層別抽出の重みで平均し直す。

品質の計算は時間を測らないので `lib.gpu_use` で囲む(排他を握ると他 Agent の
実測が止まる)。engine の build はさらにその外で行う。
"""
import argparse
import sys

import numpy as np
import onnx
import onnx.numpy_helper
import torch

import lib
import m3_bench as MB

sys.path.insert(0, str(lib.VFI1))
import gpumetric as GM        # noqa: E402
import vfilib as V            # noqa: E402
import rifev1 as R1           # noqa: E402


# ---------------------------------------------------------------- scale の一般化
#
# rifev1._apply_scale は Constant の **出力名** (`onnx::Resize*` / `onnx::Mul*`)
# で定数を拾う。この命名は v4.0〜v4.6 の古い export のもので、v4.15_lite 以降
# (v4.18 / v4.25_lite / v4.26 / v4.26_heavy) は `/blockN/Constant_*` になるため
# 1個も拾えず「この重みは scale を掛けられません」で落ちる。
#
# 両者の graph は同型で、pyramid の各段が
#   down Resize (倍率<1) → conv → up Resize (倍率>1)
# と、flow の大きさを直す Mul の対 (段の倍率の逆数と、次の段の倍率) を持つ。
#
#   v4.6         Resize 0.125 / 8 / 0.25,0.25 / 4 / 0.5,0.5 / 2 / 1,1 / 1
#                Mul    8, 0.25, 4, 0.5, 2, 1, 1
#   v4.26_heavy  Resize 0.0625 / 16 / 0.125 / 8 / 0.25 / 4 / 0.5 / 2
#                Mul    16, 0.125, 8, 0.25, 4, 0.5, 2
#
# なので名前ではなく **倍率の値** で分類できる: 1未満は down で ×scale、
# 1より大きいものは up で ÷scale。v4.6 だけ最終段の倍率が 1.0 で値から
# 判別できないので、そこは出現順で分ける (down,down,up の順)。
#
# この関数が rifev1._apply_scale と **同じ ONNX を出すこと** を v4.6 で
# 検算してから使う (verify_against_v1)。合わなければ止める。

def _scale_constants(model):
    """(Resize の倍率定数, Mul の倍率定数) を出現順で返す。"""
    prod = {n.output[0]: n for n in model.graph.node}
    init = {i.name: i for i in model.graph.initializer}
    rz, ml = [], []
    for n in model.graph.node:
        if n.op_type == "Resize":
            for inp in n.input[1:]:
                if inp and inp in prod and prod[inp].op_type == "Constant":
                    t = prod[inp].attribute[0].t
                    if np.asarray(onnx.numpy_helper.to_array(t)).size >= 4:
                        rz.append(t)
                        break
        elif n.op_type == "Mul":
            for inp in n.input:
                t = None
                if inp in prod and prod[inp].op_type == "Constant":
                    t = prod[inp].attribute[0].t
                if t is not None and onnx.numpy_helper.to_array(t).size == 1:
                    ml.append(t)
                    break
    return rz, ml


def _val(t, idx):
    return float(onnx.numpy_helper.to_array(t).ravel()[idx])


def apply_scale_by_value(model, scale, strict=True):
    """倍率の値だけで down/up を分けて flow の scale を掛ける。

    倍率が 1.0 の定数は値から down/up を分けられない。新しい export
    (v4.26 系) には 1.0 が1つも無いので、strict=True で「1.0 が出たら止める」
    にしておけば取り違えは起きない。
    """
    from onnx.numpy_helper import from_array, to_array
    rz, ml = _scale_constants(model)
    if not rz or not ml:
        raise RuntimeError("倍率の定数が見つかりません")
    for t, i in [(t, 2) for t in rz] + [(t, 0) for t in ml]:
        if _val(t, i) == 1.0 and strict:
            raise RuntimeError("倍率 1.0 の定数があり down/up を判別できません")
    for t in rz:
        arr = to_array(t).copy()
        arr[2:4] = arr[2:4] / scale if float(arr[2]) > 1.0 else arr[2:4] * scale
        t.CopyFrom(from_array(arr, t.name))
    for t in ml:
        arr = to_array(t).copy()
        arr = arr / scale if float(arr.ravel()[0]) > 1.0 else arr * scale
        t.CopyFrom(from_array(arr.astype(to_array(t).dtype), t.name))
    return model


OLD_EXPORT = ("v4.0", "v4.2", "v4.3", "v4.4", "v4.5", "v4.6")


def verify_against_v1(names=OLD_EXPORT, scales=(0.5, 0.25)):
    """既存実装 (rifev1._apply_scale) と同じ操作であることを確かめる。

    既存実装が扱える古い export には倍率 1.0 の定数が混ざっており、値だけでは
    down/up を分けられない。そこで **1.0 以外の定数** について両者が同じ値に
    なることを確かめる。1.0 以外が全部一致すれば「値で分ける」が正しい意味を
    表していることになり、1.0 を持たない新しい export では判別が一意に決まる。

    合わなければ例外。ここを通らないまま v4.26_heavy へ適用しない。
    """
    from onnx.numpy_helper import to_array
    checked = 0
    for name in names:
        src = R1.onnx_path(name)
        for s in scales:
            base = _scale_constants(onnx.load(str(src)))
            a = _scale_constants(R1._apply_scale(onnx.load(str(src)), s))
            b = _scale_constants(apply_scale_by_value(
                onnx.load(str(src)), s, strict=False))
            for grp in (0, 1):
                idx = 2 if grp == 0 else 0
                for k, t0 in enumerate(base[grp]):
                    if _val(t0, idx) == 1.0:
                        continue          # 値では分けられない段。対象外
                    va, vb = _val(a[grp][k], idx), _val(b[grp][k], idx)
                    if abs(va - vb) > 1e-9:
                        raise RuntimeError(
                            f"{name} scale={s}: 既存実装と一致しません "
                            f"({'Resize' if grp == 0 else 'Mul'}[{k}] "
                            f"{_val(t0, idx)} -> {va} 対 {vb})")
                    checked += 1
    lib.log(f"  scale 書き換えの検算 OK ({len(names)} model × {len(scales)} scale / "
            f"定数 {checked} 個が既存実装と一致)")
    return True


def new_export_ok(name):
    """新しい export に倍率 1.0 の定数が無いこと (判別が一意) を確かめる。"""
    rz, ml = _scale_constants(onnx.load(str(R1.onnx_path(name))))
    ones = [t for t in rz if _val(t, 2) == 1.0] + [t for t in ml if _val(t, 0) == 1.0]
    if ones:
        raise RuntimeError(f"{name}: 倍率 1.0 の定数が {len(ones)} 個あります")
    lib.log(f"  {name}: 倍率 Resize {len(rz)}個 / Mul {len(ml)}個、"
            "1.0 は無し (down/up が一意に決まる)")
    return True


def enable_new_export_scale(name):
    """検算に通してから rifev1 の定数書き換えを値ベースへ差し替える。

    rifev1.py は他 Agent の資産なので書き換えない。engine の build と cache は
    RifeV1 の物をそのまま使いたいので、この関数だけ差し替える。
    """
    verify_against_v1()
    new_export_ok(name)
    R1._apply_scale = lambda m, s: apply_scale_by_value(m, s, strict=True)


def to_bgr_u8(y):
    """RifeV1.infer() の (1,3,h,w) fp16 RGB 0..1 -> uint8 BGR HWC。"""
    x = y[0].float().clamp_(0, 1).mul_(255.0).round_().to(torch.uint8)
    return x.flip(0).permute(1, 2, 0).contiguous()


def quality(m, clip):
    a = lib.load(clip)
    ts = np.load(lib.RESULTS / f"testset_{clip}.npy")
    rows = []
    for rec in ts:
        r0, r1, r2 = int(rec["r0"]), int(rec["r1"]), int(rec["r2"])
        tau = float(rec["tau"])
        gt = GM.to_gpu(np.array(a[r1]))
        m.pack(GM.to_gpu(np.array(a[r0])), GM.to_gpu(np.array(a[r2])), tau)
        y = to_bgr_u8(m.infer())
        rows.append((r1, int(rec["bin"]), float(rec["span"]), tau,
                     float(rec["weight"]), GM.psnr(y, gt), V.lpips_score(y, gt),
                     GM.gmsd(y, gt), GM.bad_pixels(y, gt)))
    return np.array(rows, dtype=MB.QDTYPE)


def run(model="v4.6", scales=(1.0, 0.5, 0.25), clips=None):
    clips = clips or list(lib.CLIPS)
    done = lib.done_keys("scalequal", ("model", "scale", "clip"))
    if model not in OLD_EXPORT:
        enable_new_export_scale(model)
    built = {}
    for s in scales:                                  # build は lock の外
        built[s] = R1.RifeV1(model, lib.W, lib.H, scale=s, fp16=True)
    for s in scales:
        for clip in clips:
            if (model, s, clip) in done:
                lib.log(f"  {clip} scale={s}: 済み")
                continue
            with lib.gpu_use("speed"):
                arr = quality(built[s], clip)
            np.save(lib.RESULTS / f"scaleq_{model}_{s}_{clip}.npy", arr)
            r = MB.summarise(arr)
            lib.record("scalequal", dict(model=model, impl="v1", scale=s,
                                         clip=clip, pad=f"{built[s].pw}x{built[s].ph}",
                                         **r))
            lib.log(f"  {clip} scale={s}: LPIPS {r['lpips']:.4f} / "
                    f"GMSD {r['gmsd']:.4f} / PSNR {r['psnr']:.2f} (n={r['n']})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="*")
    ap.add_argument("--model", default="v4.6")
    ap.add_argument("--scales", default="1.0,0.5,0.25")
    args = ap.parse_args()
    run(args.model, tuple(float(x) for x in args.scales.split(",")),
        args.clips or None)
