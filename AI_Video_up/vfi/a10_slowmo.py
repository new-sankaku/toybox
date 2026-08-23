"""差が見える形で出す。x2 の会話場面では差が出ないことが実測で判ったので、
**倍率を上げて、連続して動いている shot で**並べる。

x2 の会話場面は、補間位置 718枚のうち目に見える差があるのが 31枚(4.3%)しか
ありません。1枚 1/48秒なので、30秒の素材で 0.65秒ぶんです。
**見て判らないのは当然で、実際にほとんど変わっていません。**

差が出るのは「連続して動いている shot」で、そこを倍率を上げて出します。
比較相手は frame の複製(=補間しない場合)で、容器の fps は揃えます。
違うのは中身の滑らかさだけになります。

作る物:
  <clip>_slowmo_x<N>.mp4    左=複製 / 右=補間。どちらも同じ fps、同じ遅さ
  <clip>_diffmap.mp4        x2 が複製とどこで違うのかを光らせたもの
"""
import argparse
import subprocess

import numpy as np
import torch

import rifelib as R
import vfilib as V

OUT = V.ROOT / "out"
OUT.mkdir(exist_ok=True)
FONT = ("fontfile=/Windows/Fonts/arial.ttf:fontsize=30:fontcolor=white"
        ":box=1:boxcolor=black@0.65:boxborderw=8")


def write(frames_iter, w, h, fps, dst, label):
    enc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
         "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
         "-vf", f"drawtext=text='{label}':{FONT}:x=16:y=16",
         "-c:v", "hevc_nvenc", "-preset", "p4", "-cq", "20",
         "-pix_fmt", "yuv420p", str(dst)], stdin=subprocess.PIPE)
    n = 0
    for f in frames_iter:
        enc.stdin.write(np.ascontiguousarray(f).tobytes())
        n += 1
    enc.stdin.close()
    enc.wait()
    return n


def slowmo(clip, start, count, mult, model, slow):
    """連続する count 枚を mult 倍に補間し、複製版と並べる。"""
    a = V.load(clip)
    m = R.Rife(model, V.W, V.H, fp16=True)

    def gen(interp):
        for i in range(start, start + count - 1):
            g0, g1 = R.to_gpu(a[i]), R.to_gpu(a[i + 1])
            yield a[i]
            for k in range(1, mult):
                if not interp:
                    yield a[i]
                else:
                    R.pack(g0, g1, k / mult, m.dtype, out=m.dev_in)
                    yield R.unpack(m.infer()).cpu().numpy()
        yield a[start + count - 1]

    fps = f"{V.FPS_NUM * mult}/{V.FPS_DEN}"
    p_dup = OUT / f"_dup.mp4"
    p_int = OUT / f"_int.mp4"
    n1 = write(gen(False), V.W, V.H, fps, p_dup, f"fukusei (hokan nashi) x{mult}")
    n2 = write(gen(True), V.W, V.H, fps, p_int, f"hokan {model} x{mult}")
    dst = OUT / f"{clip}_slowmo_x{mult}_{slow}分の1速.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(p_dup), "-i", str(p_int),
         "-filter_complex",
         f"[0:v]setpts={slow}*PTS[l];[1:v]setpts={slow}*PTS[r];"
         f"[l][r]hstack=inputs=2,scale=1920:-2[v]",
         "-map", "[v]", "-r", fps, "-c:v", "hevc_nvenc", "-preset", "p4", "-cq", "22", "-pix_fmt", "yuv420p", str(dst)], check=True)
    p_dup.unlink()
    p_int.unlink()
    del m
    torch.cuda.empty_cache()
    V.log(f"  {dst.name}  {n1}枚 x2列  ({dst.stat().st_size/1e6:.1f} MB)")
    return dst


def diffmap(clip, start, count, model):
    """x2 が複製とどこで違うのかを光らせる。左=x2 / 右=差(8倍に強調)。"""
    import cv2
    a = V.load(clip)
    m = R.Rife(model, V.W, V.H, fp16=True)
    rows = []

    def gen():
        for i in range(start, start + count - 1):
            yield np.hstack([a[i], np.zeros_like(a[i])])
            R.pack(R.to_gpu(a[i]), R.to_gpu(a[i + 1]), 0.5, m.dtype, out=m.dev_in)
            y = R.unpack(m.infer()).cpu().numpy()
            d = cv2.absdiff(y, a[i])                    # 複製との差
            d = np.clip(d.astype(np.int32) * 8, 0, 255).astype(np.uint8)
            rows.append(int(V.bad_pixels(y, a[i], 48)))
            yield np.hstack([y, d])

    dst = OUT / f"{clip}_差分map.mp4"
    write(gen(), V.W * 2, V.H, f"{V.FPS_NUM*2}/{V.FPS_DEN}", OUT / "_dm.mp4",
          "hidari = x2 shutsuryoku / migi = fukusei tono sa (8bai)")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(OUT / "_dm.mp4"),
                    "-vf", "setpts=4*PTS,scale=1920:-2", "-r",
                    f"{V.FPS_NUM*2}/{V.FPS_DEN}", "-c:v", "hevc_nvenc", "-preset", "p4", "-cq", "24", "-pix_fmt", "yuv420p", str(dst)],
                   check=True)
    (OUT / "_dm.mp4").unlink()
    del m
    torch.cuda.empty_cache()
    V.log(f"  {dst.name}  補間frameの |d|>48 画素数 中央{int(np.median(rows))} "
          f"最大{max(rows)}  ({dst.stat().st_size/1e6:.1f} MB)")
    return dst


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default="B_talk")
    ap.add_argument("--start", type=int, default=340)
    ap.add_argument("--count", type=int, default=48)
    ap.add_argument("--mult", type=int, default=4)
    ap.add_argument("--slow", type=int, default=4)
    ap.add_argument("--model", default="v4.6")
    args = ap.parse_args()
    V.log(f"=== {args.clip} frame {args.start} から {args.count}枚 x{args.mult}")
    slowmo(args.clip, args.start, args.count, args.mult, args.model, args.slow)
    diffmap(args.clip, args.start, args.count, args.model)
