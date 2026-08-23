"""dedup 判定の掃引 その2。

exp2_dedup.py は「block平均|d|」を判定にも評価にも使っていて循環していた。
ここでは判定基準とは独立な安全指標で並べ直す。

安全指標(いずれも使い回した frame と本来の frame の差):
  欠落画素   max|d|>48 の画素数。線画が動けば必ず出る。「絵として何画素間違えたか」
  欠落最大   1 frame あたりの欠落画素数の最大
  欠落合計   区間全体の欠落画素数の合計 (取りこぼしの総量)
  PSNR最小   全体誤差の最悪値

判定は全て cv2 の実装で、1 frame あたりの実測時間も出す。
"""
import time

import cv2
import numpy as np

from exp2_lib import H, W, all_segments

PX3 = H * W * 3


# ------------------------------------------------------------ 判定基準
def c_exact():
    def f(cur, ref, d):
        return not d.any()
    return f


def c_global(thr, ratio):
    """現行実装。|d|>thr の channel 値が全体の ratio 未満なら同一とみなす。"""
    lim = ratio * PX3

    def f(cur, ref, d):
        nz = cv2.countNonZero(
            cv2.threshold(d.reshape(H, -1), thr, 255, cv2.THRESH_BINARY)[1])
        return nz <= lim
    return f


def c_blockmean(blk, thr):
    """|d| を blk x blk の box 平均へ畳んでから最大を見る。

    encode noise は面に薄く広がるので平均で潰れ、局所的で濃い変化だけが残る。
    実装は absdiff の結果を INTER_AREA で 1/blk に縮めるだけ (box 平均そのもの)。
    """
    dw, dh = W // blk, H // blk

    def f(cur, ref, d):
        s = cv2.resize(d, (dw, dh), interpolation=cv2.INTER_AREA)
        return int(s.max()) < thr
    return f


def c_blockmean_cnt(blk, thr, k):
    """box 平均が thr 以上の block が k 個以下なら同一とみなす(1 block だけの
    孤立した反応を許す)。"""
    dw, dh = W // blk, H // blk

    def f(cur, ref, d):
        s = cv2.resize(d, (dw, dh), interpolation=cv2.INTER_AREA)
        return cv2.countNonZero(
            cv2.threshold(s.reshape(dh, -1), thr - 1, 255,
                          cv2.THRESH_BINARY)[1]) <= k
    return f


def c_strong(thr, k):
    """|d|>thr の画素が k 個以下。安全指標と同族だが判定閾値は変える。"""
    def f(cur, ref, d):
        return cv2.countNonZero(
            cv2.threshold(d.reshape(H, -1), thr, 255,
                          cv2.THRESH_BINARY)[1]) <= k
    return f


CRITS = [("厳密一致", c_exact())]
CRITS += [("現行 balanced", c_global(4, 0.0015)),
          ("現行 aggressive", c_global(12, 0.012))]
CRITS += [(f"box{b} 平均max<{t}", c_blockmean(b, t))
          for b in (8, 16, 32) for t in (2, 3, 4, 6, 8, 12, 16)]
CRITS += [(f"box16 平均>={t} が{k}block以下", c_blockmean_cnt(16, t, k))
          for t in (4, 6, 8) for k in (1, 2, 4)]
CRITS += [(f"|d|>32 が{k}画素以下", c_strong(32, k))
          for k in (0, 32, 128, 512, 2048)]


def main():
    segs = list(all_segments())
    rows = []
    for name, fn in CRITS:
        reused = total = 0
        miss, psnrs = [], []
        t_judge = 0.0
        for _, f, _, _ in segs:
            ref = None
            for i in range(len(f)):
                total += 1
                if ref is None:
                    ref = f[i]
                    continue
                t0 = time.perf_counter()
                d = cv2.absdiff(f[i], ref)
                same = fn(f[i], ref, d)
                t_judge += time.perf_counter() - t0
                if same:
                    reused += 1
                    m = cv2.countNonZero(
                        cv2.threshold(d.reshape(H, -1), 48, 255,
                                      cv2.THRESH_BINARY)[1])
                    miss.append(m)
                    mse = float(np.mean(d.astype(np.float32) ** 2))
                    psnrs.append(99.0 if mse == 0 else
                                 10 * np.log10(255.0 ** 2 / mse))
                else:
                    ref = f[i]
        rate = reused / total
        miss = np.asarray(miss) if miss else np.zeros(1)
        rows.append((name, 1 / max(1 - rate, 1e-9),
                     int(miss.max()), int(miss.sum()),
                     min(psnrs) if psnrs else 99.0,
                     t_judge / total * 1000))
    rows.sort(key=lambda r: r[1])
    print(f"{'判定基準':28s} {'SR削減':>7s} {'欠落最大':>8s} {'欠落合計':>9s} "
          f"{'PSNR最小':>8s} {'判定ms':>7s}")
    for r in rows:
        print(f"{r[0]:28s} {r[1]:6.2f}倍 {r[2]:8d} {r[3]:9d} {r[4]:8.1f} {r[5]:7.2f}")


if __name__ == "__main__":
    main()
