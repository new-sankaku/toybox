"""旧実装 (r5_render.py) を、新実装と同じ条件で測り直す。

results.jsonl の kind="render" は `lib.gpu_lock` だけで測ってあり、
GPU が実際に空いたか (sgpu.wait_idle) と canary は取っていない。
新旧を比べる表の基準にするには条件が揃わないので、同じ `sgpu.measuring`
の中で測り直して kind="render2" へ記録する。

r5_render.py には手を入れない。render() をそのまま呼ぶ。
"""
import argparse

import lib
import r5_render as R5
import s8_e2e
import sgpu

CONDS = ["x2絵", "60絵"]


def run(clip, cond, model="v4.6", keep=False):
    out_path = lib.OUT / f"old_{clip}_{cond}.mp4"
    with sgpu.measuring("speed") as env:
        others0 = s8_e2e.others_on_gpu()
        rec = R5.render(clip, cond, out_path, model)
        others1 = s8_e2e.others_on_gpu()
    info = s8_e2e.probe(out_path)
    fps_out = rec["fps_out"]
    ok = (info["frames"] == rec["out_frames"]
          and abs(info["sec"] - rec["out_frames"] / fps_out) < 0.05)
    rec.update(env)
    rec["probe"] = info
    rec["verify_ok"] = bool(ok)
    rec["others_before"], rec["others_after"] = others0, others1
    lib.record("render2", rec)
    lib.log(f"  旧 {clip} {cond}: {rec['out_frames']} frame / {rec['sec']}秒 = "
            f"{rec['out_fps']} fps  実時間の {rec['realtime_x']}倍速  "
            f"model {rec['calls']}回  検算 {'OK' if ok else 'NG'}")
    if not keep:
        out_path.unlink(missing_ok=True)
    return rec


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="*")
    ap.add_argument("--conds", default=",".join(CONDS))
    ap.add_argument("--model", default="v4.6")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()
    for c in (args.clips or list(lib.CLIPS)):
        for name in args.conds.split(","):
            run(c, name, args.model, args.keep)
