"""出力 fps を素材 fps の整数倍にすると、古い絵を出す時間は消えるか。

3.8 で判ったのは「23.976fps を 60fps へ載せると、絵の切り替わりが出力 frame の
内側に落ち、A_op では尺の 17.4% で前の絵が出たままになる」という事です。
出力 fps が素材 fps の整数倍なら境界が重なるので、これは 0 になるはずです。

  47.952 = 23.976 x 2   (既に測ってある。stale 0.0%)
  71.928 = 23.976 x 3   ← 追加
  119.88 = 23.976 x 5   ← 追加。120Hz の画面とほぼ一致する

60 / 120 と横に並べます。schedule は r5_render の物をそのまま使うので
(CONDS に足すだけ)、既存の 60絵 / 120絵 と同じ関門・同じ実装です。

速度は測りません(GPU は共有で確保します)。
"""
import sys

import lib
import smooth
import r5_render as R5

NEW = {
    "72絵":    dict(mode="draw", fps_out=lib.FPS * 3),    # 71.928
    "120整絵": dict(mode="draw", fps_out=lib.FPS * 5),    # 119.88
}
R5.CONDS.update(NEW)


def render(clip, cond):
    dst = lib.OUT / f"{clip}_{cond}.mp4"
    if not dst.exists():
        lib.log(f"{clip}/{cond}: 出力します -> {dst}")
        with lib.gpu_use("shindan"):
            r = R5.render(clip, cond, dst)
        r["note"] = "速度は共有 GPU で測ったので当てにしない"
        lib.record("render", r)
        print(r, flush=True)
    with lib.gpu_use("shindan"):
        m = smooth.measure(dst, clip, tag=f"retime/{clip}/{cond}")
    print(m, flush=True)
    return dst


if __name__ == "__main__":
    for c in (sys.argv[1:] or list(lib.CLIPS)):
        for k in NEW:
            render(c, k)
