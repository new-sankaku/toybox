"""補間が何をしたのかを、frame ごとに数値で出す。

「差が分からない」に対する答えを推測でなく数値で出すための script。
出力 CSV: results/diff_<clip>.csv

各 補間位置 i（source frame i と i+1 の間）について:

  src_box4    元の2枚の差。**補間frameが元と違い得る上限**
  src_maxd    同、画素の最大差
  out_box4    補間frame と「複製(= frame i をそのまま)」の差
  out_bad48   同、|d|>48 の画素数
  psnr_f0     補間frame と frame i の PSNR
  psnr_f1     補間frame と frame i+1 の PSNR
  psnr_naive  補間frame と 複製 の PSNR（= psnr_f0 と同じ。並べて見るため）

src_box4 が 0 に近ければ、model が何を出しても複製と同じ絵にしかなりません。
**差が小さいのは model の問題ではなく、元が動いていないから**であることを
この2列を並べて確かめます。
"""
import sys

import numpy as np
import torch

import gpumetric as GM
import rifelib as R
import vfilib as V

MODEL = "v4.6"


def run(clip, model=MODEL):
    a = V.load(clip)
    scd = np.load(V.RESULTS / f"scd_{clip}.npy")
    m = R.Rife(model, V.W, V.H, fp16=True)
    n = len(a)
    rows = []
    prev = GM.to_gpu(np.array(a[0]))
    for i in range(n - 1):
        cur = GM.to_gpu(np.array(a[i + 1]))
        src_box4 = GM.box4_max(prev, cur)
        src_maxd = float((prev.float() - cur.float()).abs().amax())
        R.pack(prev, cur, 0.5, m.dtype, out=m.dev_in)
        y = R.unpack(m.infer())
        rows.append((i, float(scd[i]), src_box4, src_maxd,
                     GM.box4_max(y, prev), GM.bad_pixels(y, prev),
                     GM.psnr(y, prev), GM.psnr(y, cur)))
        prev = cur
        if i % 200 == 0:
            V.log(f"  {i}/{n-1}")
    arr = np.array(rows, dtype=[("i", "i4"), ("scd", "f4"), ("src_box4", "f4"),
                                ("src_maxd", "f4"), ("out_box4", "f4"),
                                ("out_bad48", "i8"), ("psnr_f0", "f8"),
                                ("psnr_f1", "f8")])
    np.save(V.RESULTS / f"diff_{clip}.npy", arr)
    with open(V.RESULTS / f"diff_{clip}.csv", "w", encoding="utf-8") as f:
        f.write("i,scd,src_box4,src_maxd,out_box4,out_bad48,psnr_f0,psnr_f1\n")
        for r in arr:
            f.write(f"{r['i']},{r['scd']:.2f},{r['src_box4']:.0f},"
                    f"{r['src_maxd']:.0f},{r['out_box4']:.0f},{r['out_bad48']},"
                    f"{r['psnr_f0']:.2f},{r['psnr_f1']:.2f}\n")

    # 元がどれだけ動いているかで層に分け、その層で補間が何をしたかを見る
    bins = [(0, 4), (4, 16), (16, 48), (48, 120), (120, 1e9)]
    lines = []
    for lo, hi in bins:
        s = arr[(arr["src_box4"] >= lo) & (arr["src_box4"] < hi)
                & (arr["scd"] < 10.0)]
        if not len(s):
            continue
        lines.append(dict(
            src_box4=f"{lo}〜{hi if hi < 1e8 else ''}",
            n=len(s), pct=round(len(s) / len(arr) * 100, 1),
            out_box4_med=round(float(np.median(s["out_box4"])), 1),
            out_bad_med=int(np.median(s["out_bad48"])),
            out_bad_p90=int(np.percentile(s["out_bad48"], 90)),
            visible=int((s["out_bad48"] > 10000).sum())))
    cut = arr[arr["scd"] >= 10.0]
    info = dict(clip=clip, model=model, pairs=len(arr), cuts=len(cut),
                rows=lines,
                visible_total=int((arr["out_bad48"] > 10000).sum()),
                visible_pct=round(float((arr["out_bad48"] > 10000).mean()) * 100, 1))
    V.record("diffreport", info)

    print(f"\n=== {clip}  補間位置 {len(arr)} 箇所 (cut {len(cut)}) ===")
    print(f"{'元の2枚の差 box4':>18s} {'箇所':>6s} {'割合':>7s} "
          f"{'補間と複製の差 box4 中央':>24s} {'|d|>48画素 中央':>16s} "
          f"{'同 p90':>10s} {'目に見える枚数':>14s}")
    for r in lines:
        print(f"{r['src_box4']:>18s} {r['n']:>6d} {r['pct']:>6.1f}% "
              f"{r['out_box4_med']:>24.1f} {r['out_bad_med']:>16d} "
              f"{r['out_bad_p90']:>10d} {r['visible']:>14d}")
    print(f"\n目に見える差(|d|>48 が1万画素超)がある補間frame: "
          f"{info['visible_total']} / {len(arr)} ({info['visible_pct']}%)")
    print(f"CSV: results/diff_{clip}.csv")
    del m
    torch.cuda.empty_cache()


if __name__ == "__main__":
    for c in (sys.argv[1:] or list(V.CLIPS)):
        run(c)
