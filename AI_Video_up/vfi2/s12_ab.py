"""旧実装と新実装を **交互に** 測る。

同じ条件を測り直すと 6.89秒 対 12.13秒 (1.76倍) までばらついた。canary は
両方 5.4ms で clean なので、干渉は推論の GPU 時間ではなく CPU・NVENC・disk
側にある。別々の時間帯に測った旧と新を並べても比較にならない。

そこで 1組 (旧 → 新pipe → 新NVDEC) を続けて回し、それを1巡とする。巡ごとに
比を出し、複数巡の **最小の秒** を代表値にする (干渉は遅くする向きにしか
働かないので、最小が一番汚染の少ない値)。
"""
import argparse

import lib
import s8_e2e
import s11_oldbase

CONDS = {"x2絵": 2 * lib.FPS, "60絵": 60.0}


def one(clip, cond, rounds=1):
    for r in range(rounds):
        fps = CONDS[cond]
        old = s11_oldbase.run(clip, cond)
        pipe = s8_e2e.run(clip, fps, plan="retime", decode="pipe", keep=False)
        nvdec = s8_e2e.run(clip, fps, plan="retime", decode="nvdec", keep=False)
        rec = dict(round=r, clip=clip, cond=cond, out_fps=fps,
                   calls=old["calls"], old_sec=old["sec"],
                   pipe_sec=pipe["sec"], nvdec_sec=nvdec["sec"],
                   pipe_vs_old=round(old["sec"] / pipe["sec"], 3),
                   nvdec_vs_old=round(old["sec"] / nvdec["sec"], 3),
                   nvdec_vs_pipe=round(pipe["sec"] / nvdec["sec"], 3),
                   verify_ok=bool(old["verify_ok"] and pipe["verify_ok"]
                                  and nvdec["verify_ok"]),
                   others=[old.get("others_before"), pipe.get("others_before"),
                           nvdec.get("others_before")])
        lib.record("ab", rec)
        lib.log(f"=== {clip} {cond} 第{r+1}巡: 旧 {old['sec']}秒 / "
                f"新pipe {pipe['sec']}秒 ({rec['pipe_vs_old']}倍) / "
                f"新NVDEC {nvdec['sec']}秒 ({rec['nvdec_vs_old']}倍)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="*")
    ap.add_argument("--conds", default=",".join(CONDS))
    ap.add_argument("--rounds", type=int, default=2)
    args = ap.parse_args()
    for r in range(args.rounds):
        for c in (args.clips or list(lib.CLIPS)):
            for name in args.conds.split(","):
                one(c, name, rounds=1)
