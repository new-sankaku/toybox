"""数字だけで決めないための絵。model ごとの出力を同じ組で並べる。

metric は平坦部が支配するので、線画が溶けているかどうかは目でしか判らない。
`results/look_<clip>_<tag>.png` に出す。
"""
import sys

import cv2
import numpy as np
import torch

import rifelib as R
import vfilib as V

MODELS = ["v4.15_lite", "v4.25_lite", "v4.6", "v4.26", "v4.26_heavy"]
CROP = 420          # 切り出す正方形の一辺(原寸のまま切る。縮小すると崩れが消える)


def worst_indices(clip, model, k=3, tier=None):
    """その model が一番落としている組。"""
    arr = np.load(V.RESULTS / f"q_{model}_{clip}.npy")
    if tier is not None:
        arr = arr[arr["tier"] == tier]
    return [int(x) for x in arr["r1"][np.argsort(arr["lpips"])[-k:]]]


def pick_crop(gt, y):
    """一番差の大きい所を切る。"""
    d = cv2.absdiff(gt, y).max(axis=2)
    d = cv2.boxFilter(d.astype(np.float32), -1, (81, 81))
    _, _, _, mx = cv2.minMaxLoc(d)
    x = int(np.clip(mx[0] - CROP // 2, 0, V.W - CROP))
    y0 = int(np.clip(mx[1] - CROP // 2, 0, V.H - CROP))
    return x, y0


def label(img, text):
    img = img.copy()
    cv2.rectangle(img, (0, 0), (CROP, 26), (0, 0, 0), -1)
    cv2.putText(img, text, (6, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                (0, 255, 255), 1, cv2.LINE_AA)
    return img


def run(clip, tag, indices, models=MODELS):
    a = V.load(clip)
    ts = np.load(V.RESULTS / f"testset_{clip}.npy")
    by_r1 = {int(r["r1"]): r for r in ts}
    engines = {}
    rows = []
    for r1 in indices:
        rec = by_r1[r1]
        r0, r2, tau = int(rec["r0"]), int(rec["r2"]), float(rec["tau"])
        gt = a[r1]
        outs = [("GT D1", gt), ("hold D0", a[r0]),
                ("blend", (a[r0].astype(np.float32) * (1 - tau)
                           + a[r2].astype(np.float32) * tau).astype(np.uint8))]
        for name in models:
            if name not in engines:
                engines[name] = R.Rife(name, V.W, V.H, fp16=True)
            m = engines[name]
            R.pack(R.to_gpu(a[r0]), R.to_gpu(a[r2]), tau, m.dtype, out=m.dev_in)
            outs.append((name, R.unpack(m.infer()).cpu().numpy()))
        x, y0 = pick_crop(gt, outs[-1][1])
        tiles = [label(img[y0:y0 + CROP, x:x + CROP],
                       f"{nm}" + ("" if nm.startswith("GT") else
                                  f"  PSNR {V.psnr(img, gt):.1f}"))
                 for nm, img in outs]
        rows.append(np.hstack(tiles))
    sheet = np.vstack(rows)
    p = V.RESULTS / f"look_{clip}_{tag}.png"
    cv2.imwrite(str(p), sheet)
    V.log(f"  {p.name}  ({len(indices)}組 x {len(outs)}列)")
    for m in engines.values():
        del m
    torch.cuda.empty_cache()


if __name__ == "__main__":
    clip = sys.argv[1] if len(sys.argv) > 1 else "B_talk"
    ref = sys.argv[2] if len(sys.argv) > 2 else "v4.25_lite"
    run(clip, "worst", worst_indices(clip, ref, 3))
    run(clip, "typical", worst_indices(clip, ref, 3, tier=1)[:1]
        + worst_indices(clip, ref, 3, tier=0)[:1]
        + worst_indices(clip, ref, 3, tier=2)[:1])
