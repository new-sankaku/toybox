"""目で見る物を作る。数値ではなくこれが user への答え。

  <clip>_比較_元と素直x2と60絵.mp4       全尺の3面比較(実時間は3面とも同じ)
  <clip>_1_4速_大変位_<秒>.mp4           破綻しやすい所を 1/4 速で
  <clip>_1_4速_cut直後_<秒>.mp4
  <clip>_1_4速_効果が出る所_<秒>.mp4     限定animationで効果が一番わかる所

file 名は日本語。中の label も日本語で焼く。
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

import lib
import r1_cadence as R1
import r5_render
import retime

# font と label は cwd へ置いて相対名で渡す。filter の引数に Windows の
# 絶対path を書くと `C:` の colon で option の切れ目と解釈されて parse に落ちる
FONT_SRC = Path("C:/Windows/Fonts/meiryo.ttc")
ENC = ["-c:v", "hevc_nvenc", "-preset", "p4", "-cq", "20", "-pix_fmt", "yuv420p"]


def _tile(i, label_file, fps, slow, size):
    f = [f"[{i}:v]scale={size[0]}:{size[1]}"]
    if slow != 1:
        f.append(f"setpts={slow}*PTS")
    f.append(f"fps={fps}")
    f.append(f"drawtext=fontfile=f.ttc:textfile={label_file}:fontsize=26:"
             f"fontcolor=white:box=1:boxcolor=black@0.65:boxborderw=8:x=14:y=14")
    return ",".join(f) + f"[v{i}]"


def compose(srcs, labels, out, size=(640, 360), fps=60, slow=1,
            ss=None, dur=None, stack="h"):
    tmp = Path(tempfile.mkdtemp(prefix="retime_"))
    try:
        shutil.copyfile(FONT_SRC, tmp / "f.ttc")
        for i, lb in enumerate(labels):
            (tmp / f"l{i}.txt").write_text(lb, encoding="utf-8")
        cmd = ["ffmpeg", "-v", "error", "-y"]
        for s in srcs:
            if ss is not None:
                cmd += ["-ss", f"{ss:.3f}"]
            if dur is not None:
                cmd += ["-t", f"{dur:.3f}"]
            cmd += ["-i", str(Path(s).resolve())]
        chains = [_tile(i, f"l{i}.txt", fps, slow, size)
                  for i in range(len(srcs))]
        ins = "".join(f"[v{i}]" for i in range(len(srcs)))
        chains.append(f"{ins}{stack}stack=inputs={len(srcs)}[out]")
        cmd += ["-filter_complex", ";".join(chains), "-map", "[out]"] + ENC
        cmd += [str(Path(out).resolve())]
        subprocess.run(cmd, check=True, cwd=str(tmp))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


# ---------------------------------------------------------------- 場所選び

def windows(clip, span=2.0):
    """見るべき区間を素材の実測から選ぶ。"""
    n = len(lib.load(clip))
    p = R1.pairs(clip)
    runs = lib.drawing_runs(clip)
    sch, frame_of, fps_out = r5_render.schedule_for(clip, r5_render.CONDS["60絵"])
    blk = p["cut"] | (p["gap"] > r5_render.HOLD_MAX) | (p["mv"] > r5_render.MV_GATE)
    live = ~blk
    out = {}

    if live.any():
        k = int(np.argmax(np.where(live, p["mv"], -1)))
        t = float(p["r0"][k]) / lib.FPS
        out["大変位"] = (max(0.0, t - span / 2), span, round(float(p["mv"][k]), 1))

    cuts = lib.cut_frames(clip)
    if len(cuts):
        # cut の直後に動きがある物を選ぶ
        best, bt = -1.0, None
        for c in cuts:
            k = int(np.searchsorted(runs, c))
            m = float(p["mv"][k]) if k < len(p) else 0.0
            if m > best:
                best, bt = m, float(c) / lib.FPS
        out["cut直後"] = (max(0.0, bt - 0.5), span, round(best, 1))

    # 効果が一番わかる所: span 秒の窓で model 呼び出しが最も多い所
    tt = sch["t"]
    is_model = sch["kind"] == retime.MODEL
    best, bt = -1, 0.0
    for st in np.arange(0, n / lib.FPS - span, 0.25):
        c = int(is_model[(tt >= st) & (tt < st + span)].sum())
        if c > best:
            best, bt = c, float(st)
    out["効果が出る所"] = (bt, span, best)
    return out


# ---------------------------------------------------------------- 実行

def run(clip):
    o = lib.OUT
    src = {k: o / f"{clip}_{k}.mp4" for k in r5_render.CONDS}
    miss = [k for k, v in src.items() if not v.exists()]
    if miss:
        raise FileNotFoundError(f"{clip}: 先に r5_render.py を回してください ({miss})")
    lb = lib.CLIPS[clip]["label"]

    made = []
    p = o / f"{clip}_比較_元と素直x2と60絵.mp4"
    compose([src["元"], src["x2素直"], src["60絵"]],
            [f"元 23.976fps\n{lb}", "素直な x2  47.952fps",
             "絵の列へ張り直し  60fps"], p)
    made.append(p)

    p = o / f"{clip}_比較_元と60絵_大画面.mp4"
    compose([src["元"], src["60絵"]],
            ["元 23.976fps", "絵の列へ張り直し 60fps"], p, size=(960, 540))
    made.append(p)

    for name, (ss, dur, val) in windows(clip).items():
        p = o / f"{clip}_1_4速_{name}_{ss:.1f}秒.mp4"
        compose([src["元"], src["x2素直"], src["60絵"]],
                [f"元 23.976fps  1/4速", "素直な x2  1/4速",
                 "絵の列 60fps  1/4速"], p, size=(640, 360), slow=4,
                ss=ss, dur=dur)
        made.append(p)
        lib.log(f"  {clip} {name}: {ss:.1f}秒から {dur}秒 (指標 {val})")

    p = o / f"{clip}_比較_60絵と60均し.mp4"
    compose([src["60絵"], src["60均し"]],
            ["絵の列 60fps(実測のコマ打ちのまま)", "絵の列 60fps(コマ打ちを均した)"],
            p, size=(960, 540))
    made.append(p)

    lib.record("look", dict(clip=clip, files=[x.name for x in made]))
    for x in made:
        lib.log(f"  作成: {x.name} ({x.stat().st_size/2**20:.1f} MB)")


if __name__ == "__main__":
    for c in (sys.argv[1:] or list(lib.CLIPS)):
        lib.log(f"=== 目で見る物 {c}")
        run(c)
