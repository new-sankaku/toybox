"""どの RIFE ONNX が batch>1 で engine になるかを調べる。

v4.6 は bs2 の build が落ちた。Reshape の目標 shape に 2 が焼かれていて、
[N,4,H,W] を [2,2,H,W] へ潰す graph になっている(batch=1 前提の export)。
新設計は batch が要なので、どの版が batch を通すかを先に確定させる。

判定は 128x128 の小さい engine を実際に build して行う。build が通れば
1080p でも通る(落ちるのは shape の整合であって容量ではない)。
"""
import sys
import tempfile
from pathlib import Path

import lib
import rifelib as R
import vfilib as V


def probe(name, bs=2, w=128, h=128):
    src = R.onnx_path(name)
    if not src.exists():
        return "onnx なし"
    tmp = Path(tempfile.gettempdir()) / f"_probe_{name}_{bs}"
    onnx16 = tmp.with_suffix(".onnx")
    eng = tmp.with_suffix(".engine")
    try:
        R.to_fp16(src, onnx16)
        R._build(onnx16, eng, w, h, bs)
        return "OK"
    except Exception as exc:
        return str(exc)[:160]
    finally:
        onnx16.unlink(missing_ok=True)
        eng.unlink(missing_ok=True)


if __name__ == "__main__":
    names = sys.argv[1:] or [n for n in R.available() if "ensemble" not in n]
    for n in names:
        r = probe(n)
        lib.record("batch_probe", dict(model=n, bs=2, result=r))
        lib.log(f"  {n:16s} {r}")
