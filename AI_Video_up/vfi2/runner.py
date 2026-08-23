"""新設計「絵の列 → 任意時刻 tau」のための推論 runner。

呼び出し側は「絵 i0 と 絵 i1 の間の時刻 tau を、出力 slot へ」と予約するだけ。
実行は flush() でまとめて行う。

## batch について(実測にもとづく既定)

「1組の絵から複数の tau を作れるので batch が効く」という読みは、
**1080p では成り立たない** (doc/高速化.md 2章)。

  bs=1  10.561 ms/枚
  bs=2  11.793 ms/枚 (0.90倍)
  bs=4  11.753 ms/枚 (0.90倍)
  bs=8  11.910 ms/枚 (0.89倍)   ※ v4.25_lite fp16 1920x1080

1080p の1枚で既に SM が埋まっているので、batch は VRAM を線形に食うだけ。
加えて vs-mlrt の RIFE v2実装 ONNX 17本のうち bs>1 の engine が build できるのは
v4.25_lite だけだった(他は Reshape に batch=1 が焼かれている)。

そのため `engine_batch` の既定は 1。`batch` は「まとめて予約する数」であって
engine の batch ではない。まとめることの利は別にある:

  - pack(次) と infer(今) と nv12+D2H(前) が同じ stream の上で連なり、
    CPU が1枚ごとに GPU を待たなくなる
  - 出力の順序が予約の順序で確定する

engine_batch>1 を明示的に指定した場合はその通りに動かす(黙って 1 に戻さない)。
"""
import torch

import lib
import rifelib as R

EPS = 1e-6


class BatchRunner:
    """絵の組と tau を予約し、まとめて推論する。

    frames : get(絵番号) -> cuda uint8 BGR HWC を返す物 (fastio.DrawingSource)
    sink   : sink(out_slot, cuda uint8 BGR HWC) を予約の順に呼ぶ

    exact_ends=True のとき tau が 0/1 ちょうどの予約は model を呼ばず絵を写す。
    RIFE は tau=0 でも img0 と完全一致しないので、これは近似ではなく **厳密**。
    """

    def __init__(self, model_name, w, h, batch=4, frames=None, sink=None,
                 engine_batch=1, exact_ends=True, impl="v2", scale=1.0,
                 fp16=True):
        if frames is None or sink is None:
            raise ValueError("frames と sink は必須です")
        if impl == "v1":
            if engine_batch != 1:
                raise ValueError("v1実装は batch を持てません (engine_batch=1)")
            import rifev1
            self.m = rifev1.RifeV1(model_name, w, h, scale=scale, fp16=fp16)
        elif impl == "v2":
            if scale != 1.0:
                raise ValueError("v2実装は flow の scale を掛けられません。"
                                 "scale を使うなら impl='v1' にしてください")
            self.m = R.Rife(model_name, w, h, bs=engine_batch, fp16=fp16)
        else:
            raise ValueError(f"impl は v1 か v2 です: {impl}")
        self.impl = impl
        self.w, self.h = w, h
        self.batch = max(1, int(batch))
        self.engine_batch = engine_batch
        self.frames = frames
        self.sink = sink
        self.exact_ends = exact_ends
        self.pending = []
        self.stat = dict(submitted=0, calls=0, exact=0, flushes=0)

    # -------------------------------------------------------------- 予約

    def submit(self, i0, i1, tau, out_slot):
        """絵 i0 と 絵 i1 の間の時刻 tau を out_slot へ。実行はしない。"""
        self.pending.append((int(i0), int(i1), float(tau), out_slot))
        self.stat["submitted"] += 1
        if len(self.pending) >= self.batch:
            self.flush()

    # -------------------------------------------------------------- 実行

    def _pack_into(self, row, i0, i1, tau):
        f0 = self.frames.get(i0)
        f1 = self.frames.get(i1)
        if self.impl == "v1":
            self.m.pack(f0, f1, tau)
        else:
            d = self.m.dev_in
            d[row, 0:3] = f0.permute(2, 0, 1).flip(0).to(self.m.dtype).div_(255.0)
            d[row, 3:6] = f1.permute(2, 0, 1).flip(0).to(self.m.dtype).div_(255.0)
            d[row, 6] = tau

    def _unpack_row(self, y, row):
        # permute してから float 化すると 25MB の fp32 中間を strided に書く
        # ことになり 1080p で 5.7ms 掛かる。CHW のまま uint8 まで落とす。
        x = y[row].float().clamp_(0, 1).mul_(255.0).round_().to(torch.uint8)
        return x.flip(0).permute(1, 2, 0).contiguous()

    def flush(self):
        """溜まった予約を、予約した順に実行して sink へ渡す。"""
        if not self.pending:
            return
        self.stat["flushes"] += 1
        chunk = []                       # model を呼ぶ物だけ溜める
        for item in self.pending:
            i0, i1, tau, slot = item
            if self.exact_ends and tau <= EPS:
                self._run_chunk(chunk)
                chunk = []
                self.sink(slot, self.frames.get(i0))
                self.stat["exact"] += 1
                continue
            if self.exact_ends and tau >= 1.0 - EPS:
                self._run_chunk(chunk)
                chunk = []
                self.sink(slot, self.frames.get(i1))
                self.stat["exact"] += 1
                continue
            chunk.append(item)
            if len(chunk) == self.engine_batch:
                self._run_chunk(chunk)
                chunk = []
        self._run_chunk(chunk)
        self.pending = []

    def _run_chunk(self, chunk):
        if not chunk:
            return
        for row, (i0, i1, tau, _slot) in enumerate(chunk):
            self._pack_into(row, i0, i1, tau)
        if len(chunk) < self.engine_batch:
            # 端数。engine の shape は固定なので余った行はそのまま流す
            for row in range(len(chunk), self.engine_batch):
                self.m.dev_in[row] = self.m.dev_in[len(chunk) - 1]
        y = self.m.infer()
        self.stat["calls"] += len(chunk)
        for row, (_i0, _i1, _tau, slot) in enumerate(chunk):
            self.sink(slot, self._unpack_row(y, row))

    def close(self):
        self.flush()
        return dict(self.stat)


# ------------------------------------------------------------ 時刻の割り付け
#
# 「絵の列」から目標 fps の出力時刻を作る所は semantics 側(別 Agent)の担当。
# ここに置くのは、runner を単体で動かして速度を測るための素朴な版だけ。


def plan_uniform(starts, n_src, src_fps, out_fps):
    """絵の開始時刻を等間隔と見なさず、source の時刻そのままで張り直す素朴版。

    出力 frame j の時刻 t = j / out_fps を、絵の開始時刻の列で挟んで
    (絵d, 絵d+1, tau) にする。速度計測用。品質の設計はここではしない。
    """
    starts = [int(x) for x in starts]
    times = [s / src_fps for s in starts]
    dur = n_src / src_fps
    out = []
    j = 0
    d = 0
    while True:
        t = j / out_fps
        if t >= dur:
            break
        while d + 1 < len(times) and times[d + 1] <= t:
            d += 1
        if d + 1 >= len(times):
            out.append((d, d, 0.0, j))
        else:
            span = times[d + 1] - times[d]
            tau = 0.0 if span <= 0 else (t - times[d]) / span
            out.append((d, d + 1, min(max(tau, 0.0), 1.0), j))
        j += 1
    return out
