"""端から端まで通して、実際の出力fileと実効速度を出す。

数字だけで決めないため、**必ず file を作って目で見る**。
metric は平坦部が支配するので、崩れているかどうかは再生でしか判らない。

構成は vup.py と同じ形:
  decode(ffmpeg) --pipe--> reader thread --> GPU(補間) --> writer thread --pipe--> encode(ffmpeg)

x2 の出力 frame k は
  k が偶数 -> source frame k/2 をそのまま(model を呼ばない)
  k が奇数 -> source (k-1)/2 と (k+1)/2 の間 tau=0.5
判定で呼ばずに済む物は前の frame を写す。
"""
import argparse
import queue
import subprocess
import threading
import time

import torch
import torch.nn.functional as F

import rifelib as R
import vfilib as V


def nv12(bgr_u8):
    """uint8 BGR HWC(cuda) -> nv12 uint8。vup/trt_backend.py と同じ式。"""
    x = bgr_u8.permute(2, 0, 1).float().div_(255.0).unsqueeze(0)
    b, g, r = x[:, 0:1], x[:, 1:2], x[:, 2:3]
    luma = 0.299 * r + 0.587 * g + 0.114 * b
    u = (b - luma) * (0.5 / (1 - 0.114))
    v = (r - luma) * (0.5 / (1 - 0.299))
    y = (luma * 219.0 + 16.0)[:, 0]
    u = torch.nn.functional.avg_pool2d(u, 2) * 224.0 + 128.0
    v = torch.nn.functional.avg_pool2d(v, 2) * 224.0 + 128.0
    uv = torch.stack((u, v), dim=-1)
    uv = uv.reshape(uv.shape[0], uv.shape[2], -1)
    return torch.cat((y, uv), dim=1).clamp_(0, 255).round_().to(torch.uint8)[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--model", default="v4.25_lite")
    ap.add_argument("--gate", type=int, default=16,
                    help="box4 がこれ未満なら model を呼ばず前の frame を写す")
    ap.add_argument("--scd", type=float, default=10.0, help="cut 判定の閾値")
    ap.add_argument("--encoder", default="hevc_nvenc")
    ap.add_argument("--encoder-args", default="-preset p4 -cq 24")
    ap.add_argument("--out", default=None)
    ap.add_argument("--limit", type=int, default=0, help="先頭N frameだけ")
    ap.add_argument("--no-model", action="store_true",
                    help="補間せず前のframeを複製する(出力側の天井を測る)")
    args = ap.parse_args()

    from pathlib import Path
    src = Path(args.src)
    if not src.exists():
        src = V.WORK / (args.src if args.src.endswith(".mkv")
                        else args.src + ".mkv")
    src = str(src)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,r_frame_rate", "-of", "csv=p=0", src],
        capture_output=True, text=True).stdout.strip().split(",")
    w, h = int(probe[0]), int(probe[1])
    num, den = (int(x) for x in probe[2].split("/"))
    tag = "none" if args.no_model else args.model
    out_path = args.out or src.replace(".mkv", f"_x2_{tag}.mp4")
    V.log(f"入力 {w}x{h} {num/den:.3f}fps -> 出力 {num*2/den:.3f}fps  {out_path}")

    m = None if args.no_model else R.Rife(args.model, w, h, fp16=True)

    dec = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", src, "-fps_mode", "passthrough",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
        # bufsize を指定してはいけない。Python の BufferedReader は
        # 「要求 < buffer」だと内部bufferを経由するので、1枚ぶんより大きい
        # bufsize を渡すと pipe 読みが桁で遅くなる
        # (実測 1920x1080: 31.4 fps -> 223.7 fps、720x480: 943 -> 1851 fps)。
        # 既定(-1=8192)なら 6.2MB の readinto は raw read へ素通りする。
        stdout=subprocess.PIPE)
    enc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "nv12",
         "-s", f"{w}x{h}", "-r", f"{num*2}/{den}", "-i", "-",
         "-c:v", args.encoder] + args.encoder_args.split()
        + ["-pix_fmt", "yuv420p", out_path], stdin=subprocess.PIPE)

    ph = dict(wait_read=0.0, gate=0.0, model=0.0, wait_free=0.0,
              w_sync=0.0, w_write=0.0)
    readq = queue.Queue(maxsize=8)
    NPOOL = 24

    def reader():
        pool = [torch.empty((h, w, 3), dtype=torch.uint8, pin_memory=True)
                for _ in range(NPOOL)]
        views = [p.numpy() for p in pool]
        k = 0
        while not args.limit or k < args.limit:
            j = k % NPOOL
            k += 1
            got = dec.stdout.readinto(memoryview(views[j].reshape(-1)))
            if not got or got < w * h * 3:
                break
            readq.put((pool[j], views[j]))
        readq.put(None)

    writeq = queue.Queue(maxsize=8)
    NOUT = 8
    freeq = queue.Queue()
    for _ in range(NOUT):
        b = torch.empty((h * 3 // 2, w), dtype=torch.uint8, pin_memory=True)
        freeq.put((b, b.numpy(), torch.cuda.Event()))

    def writer():
        while True:
            item = writeq.get()
            if item is None:
                break
            buf, arr, ev = item
            _t = time.time()
            ev.synchronize()
            ph["w_sync"] += time.time() - _t
            _t = time.time()
            enc.stdin.write(arr)
            ph["w_write"] += time.time() - _t
            freeq.put((buf, arr, ev))

    rt = threading.Thread(target=reader, daemon=True)
    wt = threading.Thread(target=writer, daemon=True)
    rt.start()
    wt.start()

    def emit(bgr_gpu):
        """nv12 化して pinned へ落とし、完了 event を writer へ渡す。

        ここで torch.cuda.synchronize() を呼ぶと、1出力frameごとに main loop が
        GPU を待って何も投入できなくなる(実測: 補間を一切しなくても 58.8 fps で
        頭打ちになり、model の速さが見えなくなった)。event を writer へ渡す。
        """
        _t = time.time()
        buf, arr, ev = freeq.get()
        ph["wait_free"] += time.time() - _t
        buf.copy_(nv12(bgr_gpu), non_blocking=True)
        ev.record()
        writeq.put((buf, arr, ev))

    # 判定は GPU で行う。1920x1080x3 の absdiff と resize を CPU でやると
    # それだけで 10ms/frame 掛かり、model より重くなる
    def gate_metrics(p, c):
        d = (c.half() - p.half()).abs_()
        box4 = F.avg_pool2d(d.permute(2, 0, 1).unsqueeze(0), 4).amax()
        return box4.float(), d.mean().float()

    stat = dict(out=0, calls=0, skip_static=0, skip_cut=0)
    gpu_ring = [torch.empty((h, w, 3), dtype=torch.uint8, device="cuda")
                for _ in range(3)]
    t0 = time.time()
    prev_gpu = None
    k = 0
    while True:
        _t = time.time()
        item = readq.get()
        ph["wait_read"] += time.time() - _t
        if item is None:
            break
        pin, _view = item
        cur_gpu = gpu_ring[k % 3]
        k += 1
        cur_gpu.copy_(pin, non_blocking=True)

        if prev_gpu is not None:
            _t = time.time()
            box4_t, mad_t = gate_metrics(prev_gpu, cur_gpu)
            box4, mad = box4_t.item(), mad_t.item()      # ここで1回だけ待つ
            ph["gate"] += time.time() - _t
            if m is None or box4 < args.gate:
                stat["skip_static"] += box4 < args.gate
                emit(prev_gpu)
            elif mad > 18.0:                      # cut は補間しない
                stat["skip_cut"] += 1
                emit(prev_gpu)
            else:
                _t = time.time()
                R.pack(prev_gpu, cur_gpu, 0.5, m.dtype, out=m.dev_in)
                emit(R.unpack(m.infer()))
                ph["model"] += time.time() - _t
                stat["calls"] += 1
            stat["out"] += 1
        emit(cur_gpu)
        stat["out"] += 1
        prev_gpu = cur_gpu

    writeq.put(None)
    wt.join()
    enc.stdin.close()
    enc.wait()
    dec.wait()
    dt = time.time() - t0
    rec = dict(src=str(src), model=("none" if m is None else args.model),
               gate=args.gate, w=w, h=h, out_frames=stat["out"],
               calls=stat["calls"], skip_static=stat["skip_static"],
               skip_cut=stat["skip_cut"], sec=round(dt, 2),
               out_fps=round(stat["out"] / dt, 1),
               encoder=f"{args.encoder} {args.encoder_args}", out_path=out_path,
               phase={k: round(v, 2) for k, v in ph.items()})
    V.record("e2e", rec)
    V.log(f"出力 {stat['out']} frame / {dt:.1f}秒 = {stat['out']/dt:.1f} fps  "
          f"model呼び出し {stat['calls']}  静止で省略 {stat['skip_static']}  "
          f"cutで省略 {stat['skip_cut']}")
    V.log("  内訳(秒): " + "  ".join(f"{k} {v:.1f}" for k, v in ph.items()))


if __name__ == "__main__":
    main()
