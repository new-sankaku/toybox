"""出力 file の滑らかさを測る。判定軸は共通の smooth.py。

lag_px  時刻 t に出ているべき絵と実際に出ている絵の位置のずれ(px)。**主指標**
step_px 隣接する出力 frame 間の跳び幅(px)。副指標

素直な x2 が効かない理由がこの2つの非対称で出る。lag は保持の長さで決まり
frame rate を上げても減らないが、step は frame rate に反比例して減る。
"""
import sys

import lib
import r5_render
import smooth


def run(clip, names=None):
    names = names or list(r5_render.CONDS)
    rows = []
    for name in names:
        p = lib.OUT / f"{clip}_{name}.mp4"
        if not p.exists():
            lib.log(f"  {clip} {name}: 出力がありません")
            continue
        w, h, fps = smooth.probe(p)
        r = smooth.measure(p, clip, fps_out=fps, tag=f"retime/{clip}/{name}")
        r["cond"] = name
        rows.append(r)
        lib.log(f"  {clip} {name}: lag {r['lag_px']:.2f}px / step {r['step_px']:.2f}px "
                f"/ 異なる絵 {r['drawing_rate']}/秒 / 複製 {100-r['new_pct']:.1f}%")
    return rows


if __name__ == "__main__":
    for c in (sys.argv[1:] or list(lib.CLIPS)):
        lib.log(f"=== 滑らかさ {c}")
        run(c)
