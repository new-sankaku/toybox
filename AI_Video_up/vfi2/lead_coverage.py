"""話数全体で「補間が実際に掛かる割合」を測る。

3本の30秒 clip で決めた関門(cut / 保持9 frame以上 / 絵間変位64px超)を
23分の本編すべてへ当て、pair 数と尺の両方で通過率を出す。

関門は場面単位ではなく絵の pair 単位なので、戦闘場面でも変位の小さい pair は
通る。「戦闘には掛けない」という粗い言い方が正しいかどうかを、ここで確かめる。
"""
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

import lib

W, H = 480, 270            # 判定用の低解像度。原寸へ戻す倍率は 1920/480 = 4
SCALE = 1920 / W
FPS = lib.FPS
SAME_TH = 6                # |diff|max がこれ未満なら同じ絵(B_talk で box4>=16 と一致)
HOLD_MAX = 8               # これを超える保持は意図的な静止として封じる
SPAN_LIMIT = 64.0          # 絵間変位(原寸px)。これを超えたら封じる
SCD_CUT = 10.0

RES = lib.RESULTS


def scdet_episode(src):
    """話数全体の cut。scdet の score を frame ごとに返す。"""
    dst = RES / "ep_scd.npy"
    if dst.exists():
        return np.load(dst)
    txt = RES / "ep_scene.txt"
    lib.log("scdet を話数全体へ掛けます")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(src),
         "-vf", f"scdet=threshold=0,metadata=print:file={txt.name}",
         "-an", "-f", "null", "-"], check=True, cwd=str(RES))
    cur, vals = None, {}
    for line in txt.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line.startswith("frame:"):
            cur = int(line.split()[0].split(":")[1])
        elif "lavfi.scd.score=" in line and cur is not None:
            vals[cur] = float(line.split("=")[1])
    n = max(vals) + 1
    out = np.zeros(n, dtype=np.float32)
    for k, v in vals.items():
        out[k] = v
    np.save(dst, out)
    return out


def drawings(src, scd):
    """絵の切り替わり frame と、各絵の代表画像(低解像度)を返す。

    保持している絵だけを覚える。全 frame を持つと 4.4GB になる。
    """
    dst = RES / "ep_runs.npy"
    img_dst = RES / "ep_run_imgs.npy"
    if dst.exists() and img_dst.exists():
        return np.load(dst), np.load(img_dst, mmap_mode="r")
    p = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(src), "-fps_mode", "passthrough",
         "-vf", f"scale={W}:{H}:flags=area,format=gray", "-f", "rawvideo",
         "-pix_fmt", "gray", "-"], stdout=subprocess.PIPE)
    buf = bytearray(W * H)
    mv = memoryview(buf)
    starts, imgs = [], []
    ref = None
    i = 0
    while p.stdout.readinto(mv) == W * H:
        f = np.frombuffer(bytes(buf), np.uint8).reshape(H, W)
        cut = i > 0 and scd[i - 1] >= SCD_CUT
        if ref is None or cut or int(np.abs(f.astype(np.int16) - ref).max()) >= SAME_TH:
            starts.append(i)
            imgs.append(f.copy())
            ref = f.astype(np.int16)
        i += 1
    p.wait()
    lib.log(f"話数全体: frame {i} / 絵 {len(starts)}")
    runs = np.array(starts, dtype=np.int32)
    arr = np.stack(imgs)
    np.save(dst, runs)
    np.save(img_dst, arr)
    return runs, np.load(img_dst, mmap_mode="r")


def spans(imgs):
    """隣り合う絵の間の変位(原寸px の p95)。"""
    dst = RES / "ep_span.npy"
    if dst.exists():
        return np.load(dst)
    out = np.zeros(len(imgs) - 1, dtype=np.float32)
    for k in range(len(imgs) - 1):
        fl = cv2.calcOpticalFlowFarneback(
            imgs[k], imgs[k + 1], None, 0.5, 3, 21, 3, 5, 1.2, 0)
        mag = np.sqrt(fl[..., 0] ** 2 + fl[..., 1] ** 2)
        out[k] = float(np.percentile(mag, 95)) * SCALE
        if k % 2000 == 0:
            lib.log(f"  変位 {k}/{len(imgs)-1}")
    np.save(dst, out)
    return out


def main():
    src = lib.SRC_MKV
    scd = scdet_episode(src)
    runs, imgs = drawings(src, scd)
    span = spans(imgs)

    n_frames = int(runs[-1]) + 1
    hold = np.diff(np.append(runs, n_frames))          # 各絵の保持 frame 数
    # pair k は 絵k と 絵k+1 の間。封じる条件を3つ立てる
    is_cut = np.array([bool((scd[runs[k]:runs[k + 1]] >= SCD_CUT).any())
                       for k in range(len(runs) - 1)])
    is_still = hold[:-1] > HOLD_MAX
    is_far = span > SPAN_LIMIT
    blocked = is_cut | is_still | is_far
    passed = ~blocked

    # 尺。pair k が占める時間は 絵k の保持長
    dur = hold[:-1] / FPS
    total = float(dur.sum())

    rows = []
    for name, mask in [("cut", is_cut), ("意図的な静止", is_still),
                       ("大変位64px超", is_far), ("封じた計", blocked),
                       ("通した", passed)]:
        rows.append(dict(条件=name, pair=int(mask.sum()),
                         pair_pct=round(float(mask.mean()) * 100, 1),
                         尺秒=round(float(dur[mask].sum()), 1),
                         尺_pct=round(float(dur[mask].sum()) / total * 100, 1)))

    # 保持長ごとの内訳。「どのコマ打ちが通ったか」
    bands = [(1, 1), (2, 2), (3, 3), (4, 8), (9, 10 ** 9)]
    band_rows = []
    for lo, hi in bands:
        m = (hold[:-1] >= lo) & (hold[:-1] <= hi)
        if not m.any():
            continue
        band_rows.append(dict(
            保持=f"{lo}" if lo == hi else (f"{lo}-{hi}" if hi < 10 ** 9 else f"{lo}以上"),
            pair=int(m.sum()),
            尺秒=round(float(dur[m].sum()), 1),
            尺_pct=round(float(dur[m].sum()) / total * 100, 1),
            通過pair=int((m & passed).sum()),
            通過率=round(float((m & passed).sum()) / int(m.sum()) * 100, 1),
            変位p50=round(float(np.median(span[m])), 1)))

    info = dict(frames=n_frames, 尺秒=round(total, 1), 絵=len(runs),
                frames_per_drawing=round(n_frames / len(runs), 2),
                絵毎秒=round(len(runs) / total, 2),
                hold_max=HOLD_MAX, span_limit=SPAN_LIMIT, same_th=SAME_TH,
                関門=rows, 保持長別=band_rows)
    lib.record("ep_coverage", info)
    print(json.dumps(info, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
