"""出力fpsの決め方が SR 回数と encode 量にどう効くかを測る。

SR は入力解像度で計算するので出力倍率は効かないが、出力 fps は
「何枚の source frame を使うか」を通じて SR 回数に直接効く。
"""
from collections import Counter

import numpy as np

SRC = r"C:\01_work\00_Git\toybox\AI_Video_up\サンプル.mp4"
STD = [(24000, 1001), (24, 1), (25, 1), (30000, 1001), (30, 1),
       (50, 1), (60000, 1001), (60, 1), (120000, 1001)]


def main():
    import subprocess
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "packet=pts_time", "-of", "csv=p=0", SRC],
        capture_output=True, text=True, check=True).stdout
    pts = np.sort(np.asarray([float(x.split(",")[0]) for x in out.splitlines()
                              if x.strip() and x.split(",")[0] != "N/A"]))
    d = np.diff(pts)
    d = d[d > 0]
    print(f"source frame {len(pts)}  尺 {pts[-1]:.2f}s  "
          f"平均 {len(pts) / pts[-1]:.2f} fps")
    c = Counter(round(1.0 / x, 2) for x in d)
    print("frame間隔から出る瞬間fpsの分布:")
    for r, n in c.most_common(8):
        print(f"  {r:8.2f} fps  {n:6d} ({n / len(d) * 100:5.1f}%)")
    print(f"  現行 --fps-mode max が選ぶ値: {max(c)}  "
          f"(この値の出現 {c[max(c)]} 回)")

    dur = float(pts[-1])
    print(f"\n{'出力fps':>14s} {'出力frame':>9s} {'使うsource':>10s} "
          f"{'落とすsource':>11s} {'SR上限':>8s}")
    for num, den in STD:
        n_out = int(np.floor(dur * num / den + 1e-6))
        t = np.arange(n_out, dtype=np.float64) * den / num
        idx = np.searchsorted(pts, t, side="right") - 1
        np.clip(idx, 0, len(pts) - 1, out=idx)
        used = len(np.unique(idx))
        print(f"{num}/{den:>5} {n_out:9d} {used:10d} {len(pts) - used:11d} "
              f"{used / len(pts) * 100:7.1f}%")


if __name__ == "__main__":
    main()
