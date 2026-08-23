"""端から端まで。新設計 (絵の列 → 任意時刻 tau → 目標 fps) の実効速度。

出力が正しいか(frame 数・尺・fps)を ffprobe で必ず検算する。

比較は2段にする。

  --plan retime   r5_render.py と **同じ schedule** を流す。model の呼び出し
                  回数まで一致するので、差は入出力と runner の作りだけになる。
                  旧実装 (results.jsonl の kind="render" cond="60絵" 等) との
                  直接比較はこちら。
  --plan uniform  絵の列を素直に張り直しただけの schedule。保持も gate も
                  しないので、ほぼ全ての出力 frame が model 呼び出しになる。
                  「上限まで補間した時にどこまで出るか」を見る。

  --decode pipe   ffmpeg rawvideo -> pipe -> pinned -> H2D (既定)
  --decode nvdec  NVDEC で GPU へ直 decode (fastio.NvdecDrawingSource)
"""
import argparse
import json
import subprocess
import time
from fractions import Fraction

import torch

import fastio
import lib
import runner as RN
import sgpu


def others_on_gpu():
    """自分以外で GPU に居る process の数。

    canary は推論の GPU 時間しか見ないので、他 Agent の ffmpeg (NVENC/NVDEC)
    や CPU 側の食い合いを捕まえられない。同じ条件を測り直すと 6.89秒 対
    12.13秒 と 1.76倍ばらついたのに canary は両方 5.4ms だった。誰が居たかを
    残しておかないと、後から汚染を判別できない。
    """
    import os
    r = subprocess.run(["nvidia-smi", "--query-compute-apps=pid",
                        "--format=csv,noheader"], capture_output=True, text=True)
    pids = [x.strip() for x in r.stdout.splitlines() if x.strip()]
    return len([p for p in pids if p != str(os.getpid())])


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
         "-show_entries", "stream=nb_read_frames,r_frame_rate,width,height,duration",
         "-of", "json", str(path)], capture_output=True, text=True).stdout
    s = json.loads(out)["streams"][0]
    return dict(frames=int(s["nb_read_frames"]), fps=s["r_frame_rate"],
                w=s["width"], h=s["height"],
                sec=round(float(s.get("duration", 0)), 3))


def build_plan(clip, out_fps, plan, even=False):
    """(予約の列, 絵の列) を返す。予約は (絵d0, 絵d1, tau, 出力slot)。"""
    n_src = len(lib.load(clip))
    starts = lib.drawing_runs(clip)
    if plan == "uniform":
        return RN.plan_uniform(starts, n_src, lib.FPS, out_fps), starts
    if plan != "retime":
        raise ValueError(f"plan は uniform か retime です: {plan}")
    import retime
    import r5_render as R5
    with lib.gpu_use("speed"):        # r3_gate が GPU を使う
        sch, _frame_of, _fps = R5.schedule_for(
            clip, dict(mode="draw", fps_out=float(out_fps), even=even))
    out = []
    for j, s in enumerate(sch):
        k = int(s["k"])
        if int(s["kind"]) == retime.MODEL:
            out.append((k, k + 1, float(s["tau"]), j))
        else:
            out.append((k, k, 0.0, j))
    return out, starts


def open_source(decode, src, starts, window):
    if decode == "pipe":
        return fastio.DrawingSource(src, lib.W, lib.H, starts, window=window)
    if decode == "nvdec":
        return fastio.NvdecDrawingSource(src, lib.W, lib.H, starts, window=window)
    raise ValueError(f"decode は pipe か nvdec です: {decode}")


def run(clip, out_fps, model="v4.6", impl="v2", scale=1.0, batch=8,
        engine_batch=1, enc_args="-preset p4 -cq 24", tag=None, keep=True,
        plan="uniform", decode="pipe", even=False):
    src = lib.CLIPS[clip]["path"]
    n_src = len(lib.load(clip))
    sched, starts = build_plan(clip, out_fps, plan, even)
    tag = tag or f"{plan}_{decode}_{model}_{impl}s{scale}"
    out_path = lib.OUT / f"e2e_{clip}_{out_fps}_{tag}.mp4"

    # engine の build は lock の外で済ませる
    with lib.gpu_use("speed"):
        warm = RN.BatchRunner(model, lib.W, lib.H, batch=1, frames=_Dummy(),
                              sink=lambda *a: None, engine_batch=engine_batch,
                              impl=impl, scale=scale)
        del warm
        torch.cuda.synchronize()

    window = max(8, batch + 4)
    with sgpu.measuring("speed") as env:
        t_open = time.time()
        srcimg = open_source(decode, src, starts, window)
        fr = Fraction(out_fps).limit_denominator(100000)   # 47.952… -> 48000/1001
        wr = fastio.NvencWriter(out_path, lib.W, lib.H,
                                fr.numerator, fr.denominator, args=enc_args)
        r = RN.BatchRunner(model, lib.W, lib.H, batch=batch, frames=srcimg,
                           sink=wr.sink, engine_batch=engine_batch,
                           impl=impl, scale=scale)
        others0 = others_on_gpu()
        t0 = time.time()
        for (d0, d1, tau, j) in sched:
            r.submit(d0, d1, tau, j)
            # 予約はまとめて後で実行されるので、flush が起きた時にだけ捨てる。
            # 予約したそばから捨てると、まだ実行していない予約の絵を消してしまう
            if not r.pending and d0 >= 1:
                srcimg.release_before(d0 - 1)
        stat = r.close()
        n_out = wr.close()
        t1 = time.time()
        others1 = others_on_gpu()
        srcimg.close()
        del r
        torch.cuda.empty_cache()
    dt = t1 - t0

    info = probe(out_path)
    rec = dict(clip=clip, out_fps=out_fps, plan=plan, decode=decode,
               model=model, impl=impl, scale=scale, batch=batch,
               engine_batch=engine_batch, encoder=enc_args,
               src_frames=n_src, drawings=len(starts), planned=len(sched),
               sunk=n_out, sec=round(dt, 2), sec_with_open=round(t1 - t_open, 2),
               out_fps_eff=round(n_out / dt, 1),
               realtime_x=round((n_out / out_fps) / dt, 2),
               calls=stat["calls"], exact=stat["exact"],
               ms_per_call=round(dt * 1000.0 / max(stat["calls"], 1), 3),
               others_before=others0, others_after=others1,
               out_path=str(out_path), probe=info, **env)
    ok = (info["frames"] == n_out == len(sched)
          and abs(info["sec"] - n_out / out_fps) < 0.05
          and info["w"] == lib.W and info["h"] == lib.H)
    rec["verify_ok"] = bool(ok)
    lib.record("e2e2", rec)
    lib.log(f"  {clip} {out_fps}fps {tag}: {n_out} frame / {dt:.2f}秒 = "
            f"{n_out/dt:.1f} fps  実時間の {rec['realtime_x']}倍速  "
            f"model {stat['calls']}回 / 写し {stat['exact']}回  検算 "
            f"{'OK' if ok else 'NG'} {info}")
    if not keep:
        out_path.unlink(missing_ok=True)
    return rec


def check_decode(clip, n=12):
    """NVDEC 経路の画素と順序を、ffmpeg bgr24 の展開と突き合わせる。

    順序が狂えば PSNR は桁で落ちる。色変換の差だけなら 40dB 前後に収まる。
    """
    import numpy as np
    a = lib.load(clip)
    starts = lib.drawing_runs(clip)
    with lib.gpu_use("speed"):
        s = fastio.NvdecDrawingSource(lib.CLIPS[clip]["path"], lib.W, lib.H,
                                      starts, window=max(8, n + 4))
        vals = []
        for d in range(min(n, len(starts))):
            g = s.get(d).cpu().numpy()
            vals.append(float(lib.psnr(np.ascontiguousarray(a[starts[d]]), g)))
        s.close()
    rec = dict(clip=clip, n=len(vals), psnr_min=round(min(vals), 2),
               psnr_mean=round(float(np.mean(vals)), 2),
               psnr_max=round(max(vals), 2))
    lib.record("nvdec_check", rec)
    lib.log(f"  {clip}: NVDEC 対 ffmpeg bgr24 PSNR "
            f"min {rec['psnr_min']} / 平均 {rec['psnr_mean']} dB ({len(vals)}枚)")
    return rec


class _Dummy:
    def get(self, d):
        raise AssertionError("build 用の空 runner です")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="*")
    # "x2" は source fps のちょうど2倍。丸めた 47.952 を渡すと出力時刻が絵の
    # 時刻と一致しなくなり、只で写せた frame まで model 呼び出しになる
    ap.add_argument("--fps", default="60")
    ap.add_argument("--model", default="v4.6")
    ap.add_argument("--impl", default="v2")
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--engine-batch", type=int, default=1)
    ap.add_argument("--enc", default="-preset p4 -cq 24")
    ap.add_argument("--plan", default="uniform")
    ap.add_argument("--decode", default="pipe")
    ap.add_argument("--even", action="store_true")
    ap.add_argument("--tag", default=None)
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--check-decode", action="store_true")
    args = ap.parse_args()
    clips = args.clips or list(lib.CLIPS)
    if args.check_decode:
        for c in clips:
            check_decode(c)
    else:
        for c in clips:
            for tok in str(args.fps).split(","):
                f = (lib.FPS * float(tok[1:]) if tok.startswith("x")
                     else float(tok))
                for pl in args.plan.split(","):
                    for de in args.decode.split(","):
                        run(c, f, args.model, args.impl, args.scale, args.batch,
                            args.engine_batch, args.enc, args.tag,
                            keep=args.keep, plan=pl, decode=de, even=args.even)
