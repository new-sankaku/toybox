"""schedule を実際に流して出力 file を作り、実効速度を測る。

素材を1回だけ順に decode し、schedule が要る「絵の先頭 frame」だけ GPU へ
残す。schedule の絵 index は単調に進むので、GPU に載せるのは常に2枚で足りる。

  decode(ffmpeg) --pipe--> reader thread --> GPU(補間) --> writer thread --> encode

条件は CONDS。「素直な x2」と「絵の列」の対比が主目的。
"""
import argparse
import queue
import subprocess
import threading
import time

import numpy as np
import torch

import lib
import r1_cadence as R1
import r3_gate as R3
import r_model
import retime

HOLD_MAX = 8          # 絵の保持がこれを超えたら意図的な静止(r4 と同じ)
MV_GATE = 64.0        # 跨ぐ変位がこれを超えたら補間しない
ENC = ["-c:v", "hevc_nvenc", "-preset", "p4", "-cq", "20", "-pix_fmt", "yuv420p"]

CONDS = {
    "元":       dict(mode="orig"),
    "x2素直":   dict(mode="naive"),
    "x2絵":     dict(mode="draw", fps_mul=2.0),
    "60絵":     dict(mode="draw", fps_out=60.0),
    "60均し":   dict(mode="draw", fps_out=60.0, even=True),
    "120絵":    dict(mode="draw", fps_out=120.0),
}


def nv12(bgr_u8):
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


# ---------------------------------------------------------------- schedule

def schedule_for(clip, cond):
    """条件から (schedule, 絵 index -> 素材 frame 番号, fps_out) を作る。"""
    n = len(lib.load(clip))
    runs = lib.drawing_runs(clip)
    if cond["mode"] == "naive":
        sm = R1.same_frames(clip)
        cuts = set(int(c) for c in lib.cut_frames(clip))
        blk = sm | np.array([(i + 1) in cuts for i in range(n - 1)])
        sch = retime.naive_x2(n, lib.FPS, same_pair=blk)
        return sch, np.arange(n), 2.0 * lib.FPS
    p = R1.pairs(clip)
    smv = R3.span_mv(clip)                 # smv[i] = D_i -> D_i+2
    gap = p["gap"].astype(np.int64)
    # 本番で跨ぐのは1つ隣の絵なので、pair ごとの変位をそのまま使う
    blk = p["cut"] | (gap > HOLD_MAX) | (p["mv"] > MV_GATE)
    fps_out = cond.get("fps_out") or cond["fps_mul"] * lib.FPS
    sch = retime.build(runs, n, lib.FPS, fps_out, anchor="head", block=blk,
                       even=cond.get("even", False),
                       cut_frames=lib.cut_frames(clip))
    return sch, runs.astype(np.int64), fps_out


def ident_for(clip, cond):
    """schedule の k を「絵の身元」へ写す。

    素直な x2 の k は frame 番号なので、そのまま数えると同じ絵を保持して
    いるだけの frame まで別の絵に数えてしまう(実測で 28.1 対 8.6 と3倍違った)。
    """
    if cond["mode"] != "naive":
        return lambda k: k
    runs = lib.drawing_runs(clip)
    return lambda i: int(np.searchsorted(runs, i, side="right") - 1)


# ---------------------------------------------------------------- 実行

def render(clip, name, out_path, model_name=r_model.DEFAULT, keep=True):
    cond = CONDS[name]
    src = str(lib.CLIPS[clip]["path"])
    w, h = lib.W, lib.H

    if cond["mode"] == "orig":
        t0 = time.time()
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src] + ENC
                       + [str(out_path)], check=True)
        return dict(clip=clip, cond=name, out_frames=len(lib.load(clip)),
                    fps_out=round(lib.FPS, 3), calls=0, hold=0,
                    copy=len(lib.load(clip)),
                    sec=round(time.time() - t0, 2), out_path=str(out_path))

    sch, frame_of, fps_out = schedule_for(clip, cond)
    need = sorted({int(frame_of[int(s["k"])]) for s in sch}
                  | {int(frame_of[min(int(s["k"]) + 1, len(frame_of) - 1)])
                     for s in sch})
    need_set = set(need)
    M = r_model.Model(model_name)

    dec = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", src, "-fps_mode", "passthrough",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
        stdout=subprocess.PIPE)      # bufsize は渡さない(1080p で 7.1倍遅くなる)
    num = int(round(fps_out * 1001))
    enc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "nv12",
         "-s", f"{w}x{h}", "-r", f"{num}/1001", "-i", "-"] + ENC
        + [str(out_path)], stdin=subprocess.PIPE)

    NPOOL, NOUT = 24, 8
    readq = queue.Queue(maxsize=8)

    def reader():
        pool = [torch.empty((h, w, 3), dtype=torch.uint8, pin_memory=True)
                for _ in range(NPOOL)]
        views = [p.numpy() for p in pool]
        k = 0
        while True:
            j = k % NPOOL
            got = dec.stdout.readinto(memoryview(views[j].reshape(-1)))
            if not got or got < w * h * 3:
                break
            readq.put((k, pool[j]))
            k += 1
        readq.put(None)

    writeq = queue.Queue(maxsize=8)
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
            ev.synchronize()
            enc.stdin.write(arr)
            freeq.put((buf, arr, ev))

    rt = threading.Thread(target=reader, daemon=True)
    wt = threading.Thread(target=writer, daemon=True)

    slots = {}
    state = dict(next_i=0, done=False)

    def pump_to(f):
        """素材 frame f まで decode を進め、要る frame を GPU に残す。"""
        while state["next_i"] <= f and not state["done"]:
            item = readq.get()
            if item is None:
                state["done"] = True
                break
            i, pin = item
            if i in need_set:
                g = torch.empty((h, w, 3), dtype=torch.uint8, device="cuda")
                g.copy_(pin, non_blocking=False)
                slots[i] = g
            state["next_i"] = i + 1

    def emit(bgr):
        buf, arr, ev = freeq.get()
        buf.copy_(nv12(bgr), non_blocking=True)
        ev.record()
        writeq.put((buf, arr, ev))

    stat = dict(calls=0, copy=0, hold=0)
    t0 = time.time()
    rt.start()
    wt.start()
    for s in sch:
        k = int(s["k"])
        kind = int(s["kind"])
        f0 = int(frame_of[k])
        if kind == retime.MODEL:
            f1 = int(frame_of[k + 1])
            pump_to(f1)
            emit(M.infer(slots[f0], slots[f1], float(s["tau"])))
            stat["calls"] += 1
        else:
            pump_to(f0)
            emit(slots[f0])
            stat["hold" if kind == retime.HOLD else "copy"] += 1
        for old in [x for x in slots if x < f0]:
            del slots[old]
    writeq.put(None)
    wt.join()
    enc.stdin.close()
    enc.wait()
    dec.stdout.close()
    dec.wait()
    dt = time.time() - t0

    st = retime.stats(sch, len(lib.load(clip)) / lib.FPS, ident_for(clip, cond))
    del M
    slots.clear()
    torch.cuda.empty_cache()
    return dict(clip=clip, cond=name, model=model_name,
                fps_out=round(fps_out, 3), out_frames=len(sch),
                calls=stat["calls"], hold=stat["hold"], copy=stat["copy"],
                sched_distinct=st["distinct"],
                sched_distinct_per_sec=st["distinct_per_sec"],
                sched_dup_pct=st["dup_pct"],
                sec=round(dt, 2), out_fps=round(len(sch) / dt, 1),
                realtime_x=round((len(sch) / fps_out) / dt, 2),
                out_path=str(out_path))


def run(clip, names, model_name=r_model.DEFAULT):
    done = lib.done_keys("render", ("clip", "cond", "model"))
    for name in names:
        out = lib.OUT / f"{clip}_{name}.mp4"
        if (clip, name, model_name if CONDS[name]["mode"] != "orig" else None) \
                in done and out.exists():
            lib.log(f"  {clip} {name}: 済み")
            continue
        with lib.gpu_lock("retime"):
            rec = render(clip, name, out, model_name)
        lib.record("render", rec)
        lib.log(f"  {clip} {name}: {rec['out_frames']} frame / {rec['sec']}秒 "
                f"= {rec.get('out_fps', 0)} fps  model呼び出し {rec['calls']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="*", default=None)
    ap.add_argument("--conds", default=",".join(CONDS))
    ap.add_argument("--model", default=r_model.DEFAULT)
    args = ap.parse_args()
    for c in (args.clips or list(lib.CLIPS)):
        lib.log(f"=== 出力 {c}")
        run(c, args.conds.split(","), args.model)
