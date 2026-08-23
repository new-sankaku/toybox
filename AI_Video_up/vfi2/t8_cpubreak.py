"""走査を GPU へ移しても CPU が空かない理由を、内訳で特定する。

実測は「1話の GPU 走査が 88.4秒で CPU core秒 830 = 9.4 core を専有」。
GPU へ移したのに空かないので、**どこが CPU を食っているか**を分ける。

測り方は system 全体の使用率(sampling)ではなく **process の CPU 時間の差**
にする。sampling は他の作業の CPU まで拾うので内訳の特定には粗すぎる。
`psutil.Process.cpu_times()` の user+system は process が実際に消費した
core 秒そのもので、thread 数に関わらず正しく積算される。

分ける軸は Farneback を回す worker 数。0 は `_span_px` を差し替えて
「変位を計算しない走査」にした物で、decode + GPU loop + Python の
per-frame 処理だけが残る。

  worker 0    NVDEC + GPU 縮小/差分/scdet + Python の per-frame loop
  worker 1..N 上に Farneback が N 並列で乗る

この差が Farneback のぶん。傾きが立てば「CPU を食っているのは Farneback」
で確定し、立たなければ decode か同期待ちを疑う。
"""
import argparse
import time

import numpy as np
import psutil

import lib
import vfi


def cpu_seconds(p):
    t = p.cpu_times()
    total = t.user + t.system
    for c in p.children(recursive=True):
        try:
            ct = c.cpu_times()
            total += ct.user + ct.system
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return total


def run(src, info, workers, mode, stub_flow):
    """1回走査して、消費した core 秒と実時間を返す。"""
    me = psutil.Process()
    orig = vfi._span_px
    if stub_flow:
        vfi._span_px = lambda a, b, to_full: 0.0
    try:
        c0, t0 = cpu_seconds(me), time.time()
        sc = vfi.scan(src, info, mode=mode, workers=workers)
        sec = time.time() - t0
        cpu = cpu_seconds(me) - c0
    finally:
        vfi._span_px = orig
    return dict(worker=0 if stub_flow else workers, mode=mode,
                秒=round(sec, 2), CPU_core秒=round(cpu, 1),
                占有core=round(cpu / sec, 2),
                fps=round(sc["n_frames"] / sec),
                frames=sc["n_frames"], 絵=len(sc["runs"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", nargs="?", default=str(lib.CLIPS["A_op"]["path"]))
    ap.add_argument("--workers", default="1,2,4,8,12")
    a = ap.parse_args()
    src = vfi.Path(a.input).resolve()
    info = vfi.probe(src)

    rows = [run(src, info, 1, "gpu", True)]
    for w in [int(x) for x in a.workers.split(",")]:
        rows.append(run(src, info, w, "gpu", False))
    rows.append(run(src, info, 0, "cpu", True))
    rows[-1]["mode"] = "cpu(変位なし)"
    rows.append(run(src, info, psutil.cpu_count(), "cpu", False))
    rows[-1]["mode"] = "cpu(全部)"

    base = rows[0]
    print(f"\n{src.name}  {base['frames']:,} frame / 絵 {base['絵']:,}  "
          f"論理core {psutil.cpu_count()}")
    print(f"\n{'経路':14s}{'変位worker':>11}{'秒':>8}{'fps':>7}"
          f"{'CPU core秒':>11}{'占有core':>9}{'Farneback分':>12}")
    for r in rows:
        extra = r["CPU_core秒"] - base["CPU_core秒"]
        lbl = "" if r is base else f"{extra:+.1f}"
        print(f"{r['mode']:14s}{r['worker']:>11}{r['秒']:>8.2f}{r['fps']:>7}"
              f"{r['CPU_core秒']:>11.1f}{r['占有core']:>9.2f}{lbl:>12}")
        lib.record("t8_cpubreak", dict(src=src.name, **r,
                                       farneback_core秒=round(extra, 1)))

    flow = [r for r in rows if r["mode"] == "gpu" and r["worker"] > 0]
    if flow:
        top = max(flow, key=lambda r: r["worker"])
        share = (top["CPU_core秒"] - base["CPU_core秒"]) / top["CPU_core秒"] * 100
        print(f"\n変位(Farneback)が占める割合: {share:.1f}%  "
              f"(worker {top['worker']} で core秒 {top['CPU_core秒']:.1f} のうち "
              f"{top['CPU_core秒'] - base['CPU_core秒']:.1f})")
        print(f"変位を計算しない走査の占有 core: {base['占有core']:.2f}  "
              f"({base['fps']} fps)")


if __name__ == "__main__":
    main()
