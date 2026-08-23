"""目で見るための比較動画。指標が本当に見た目と対応するかを確かめる。

左から [素材(24fpsを複製で48へ) | 素直なx2 | 時刻張り直し] を横に並べ、
48fps の1本にする。数字だけで結論を出さないための工程。

区間は「cut が少なく、絵と絵の変位の合計が最大」の窓を自動で選ぶ。
"""
import argparse
import subprocess
import sys

import cv2
import numpy as np
import torch
import torch.nn.functional as F

import lib
import smooth
import d2_x2
import d4_retime

sys.path.insert(0, str(lib.VFI1))
import gpumetric as GM       # noqa: E402

TILE = (960, 540)
SEG_S = 8.0
MAX_CUTS = 2


def pick_window(clip, seg_s=SEG_S):
    gaps, spans = smooth.gap_spans(clip)
    n = len(lib.load(clip))
    cuts = [int(c) for c in lib.cut_frames(clip)]
    wf = int(seg_s * lib.FPS)
    best, best_score = 0, -1.0
    for a in range(0, n - wf, 6):
        b = a + wf
        nc = sum(1 for c in cuts if a <= c < b)
        if nc > MAX_CUTS:
            continue
        sc = sum(float(s) for (g0, _), s in zip(gaps, spans) if a <= g0 < b)
        if sc > best_score:
            best, best_score = a, sc
    return best, best + wf, best_score


def tiles(gen, k0, k1):
    """出力 frame k0..k1 だけを 960x540 の uint8 で取り出す。"""
    out = []
    for k, f in enumerate(gen):
        if k >= k1:
            break
        if k < k0:
            continue
        t = GM.to_gpu(f).permute(2, 0, 1).unsqueeze(0).float()
        t = F.interpolate(t, size=(TILE[1], TILE[0]), mode="area")
        out.append(t[0].permute(1, 2, 0).round_().clamp_(0, 255)
                   .to(torch.uint8).cpu().numpy())
    return out


def src_doubled(clip):
    a = lib.load(clip)
    for i in range(len(a)):
        f = np.array(a[i])
        yield f
        yield f


def build(clip, fps_out=lib.FPS * 2, span_limit=32.0):
    f0, f1, score = pick_window(clip)
    k0, k1 = int(f0 / lib.FPS * fps_out), int(f1 / lib.FPS * fps_out)
    lib.log(f"{clip}: 素材 frame {f0}-{f1} (変位合計 {score:.0f}px) を切り出します")

    with lib.gpu_use("shindan"):
        cols = [
            ("source 24fps", tiles(src_doubled(clip), k0, k1)),
            ("naive x2", tiles(d2_x2.x2_frames(clip, stat=dict(
                calls=0, skip_static=0, skip_cut=0)), k0, k1)),
            (f"retimed {fps_out:.0f}fps",
             tiles(d4_retime.retime_frames(clip, fps_out, span_limit), k0, k1)),
        ]
    n = min(len(c[1]) for c in cols)
    w = TILE[0] * len(cols)
    dst = lib.OUT / f"比較_{clip}_{fps_out:.0f}fps.mp4"
    enc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
         "-s", f"{w}x{TILE[1]}", "-r", f"{fps_out:.3f}", "-i", "-",
         "-c:v", "libx264", "-preset", "slow", "-crf", "16",
         "-pix_fmt", "yuv420p", str(dst)], stdin=subprocess.PIPE)
    for k in range(n):
        row = np.concatenate([c[1][k] for c in cols], axis=1)
        for j, (name, _) in enumerate(cols):
            cv2.putText(row, name, (j * TILE[0] + 16, 34),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 4)
            cv2.putText(row, name, (j * TILE[0] + 16, 34),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 1)
        enc.stdin.write(row.tobytes())
    enc.stdin.close()
    enc.wait()
    lib.record("look", dict(clip=clip, fps_out=fps_out, span_limit=span_limit,
                            src_from=f0, src_to=f1, frames=n, out=str(dst)))
    lib.log(f"  {dst}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="*", default=None)
    ap.add_argument("--fps", type=float, default=lib.FPS * 2)
    ap.add_argument("--span-limit", type=float, default=32.0)
    args = ap.parse_args()
    for c in (args.clips or list(lib.CLIPS)):
        build(c, args.fps, args.span_limit)
