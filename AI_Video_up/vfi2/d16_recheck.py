"""cut 位置の修正(lib._scd_convention_shift)を受けて C_act を作り直す。

C_act の絵の列が 263 → 257 枚に変わったので、**絵の列に依存する cache と
出力を全部捨てて作り直す**必要があります。A_op と B_talk は規約がそのままで
画素検証も通っているので触りません。

捨てる物(絵の列 or cut に依存):
  results/smooth/span_C_act.npz        絵と絵の区間と、その変位
  results/smooth/lag_*C_act*.npz       区間ごとの位置ずれ
  results/smooth/fair_C_act_*.npz      時間格子の標本
  results/retime_pairs_C_act.npy       r1 の pair 表
  results/same_C_act.npy               r1 の「同じ絵」判定
  results/spanmv2_C_act.npy            r3 の跨ぐ変位
  results/testset_C_act.npy            試験集合
  out/C_act_<条件>.mp4                 schedule が変わるので出力も作り直す

捨てない物:
  results/smooth/scan_*.npz            frame から作る物で絵の列に依らない
  results/q2_* / recon_* / anchor_*    model 担当・retime 担当の資産(主担当が手配)

退避先は results/_stale_C_act/。消さずに残します。
"""
import shutil
import sys
from pathlib import Path

import lib
import smooth

STALE = lib.RESULTS / "_stale_C_act"
CLIP = "C_act"
CONDS = ["元", "x2素直", "x2絵", "60絵", "60均し", "120絵", "72絵", "120整絵"]


def stale_files():
    out = []
    out += list(smooth.CACHE.glob(f"span_{CLIP}.npz"))
    out += [p for p in smooth.CACHE.glob("lag_*.npz") if CLIP in p.name]
    out += [p for p in smooth.CACHE.glob("fair_*.npz") if CLIP in p.name]
    for n in (f"retime_pairs_{CLIP}.npy", f"same_{CLIP}.npy",
              f"spanmv2_{CLIP}.npy", f"testset_{CLIP}.npy"):
        p = lib.RESULTS / n
        if p.exists():
            out.append(p)
    return out


def invalidate():
    STALE.mkdir(exist_ok=True)
    n = 0
    for p in stale_files():
        shutil.move(str(p), str(STALE / p.name))
        n += 1
    lib.log(f"{CLIP}: 古い cache を {n} 件 {STALE} へ退避しました")
    return n


def rebuild_inputs():
    import r1_cadence as R1
    import m1_testset as M1
    with lib.gpu_use("shindan"):
        R1.report(CLIP)                    # retime_pairs / same / retime_cadence
        M1.build(CLIP)                     # testset
        smooth.gap_spans(CLIP)             # span cache を先に作っておく


def rerender():
    import r5_render as R5
    import d15_intfps                      # noqa: F401  (72絵 / 120整絵 を CONDS へ足す)
    for name in CONDS:
        dst = lib.OUT / f"{CLIP}_{name}.mp4"
        if name != "元" and dst.exists():
            dst.unlink()                   # schedule が変わるので作り直す
        with lib.gpu_use("shindan"):
            if not dst.exists():
                r = R5.render(CLIP, name, dst)
                r["note"] = "cut 修正後の作り直し。速度は共有 GPU なので当てにしない"
                lib.record("render", r)
                lib.log(f"  {name}: {r.get('out_frames')} frame / calls={r.get('calls')} "
                        f"hold={r.get('hold')} copy={r.get('copy')}")
            m = smooth.measure(dst, CLIP, tag=f"retime/{CLIP}/{name}")
        lib.log(f"  {name}: lag={m['lag_px']} 絵/秒={m['drawing_rate']} "
                f"hold p50={m['hold_ms_p50']}ms")


if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else "all"
    if step in ("all", "invalidate"):
        invalidate()
    if step in ("all", "inputs"):
        rebuild_inputs()
    if step in ("all", "render"):
        rerender()
