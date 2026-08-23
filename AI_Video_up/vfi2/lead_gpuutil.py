"""処理中の GPU 使用率を実際に測る。

これまでの記録は lock の前後で1点ずつ拾っただけで、`util_after` が 1% から 95% まで
振れていた(処理の終わった後を拾う事がある)。処理中を通しで測っていなかった。

`nvidia-smi dmon` は sm / mem / enc / dec を別々に出す。VFI は
  推論(sm) + NVDEC(dec) + NVENC(enc)
の3つを同時に使うので、sm だけ見ても足りない。

注意: dmon の sm は「kernel が走っていた時間の割合」で、SM が埋まっている割合では
ない。別件の実測で sm 41% なのに CUDA event で測った自分の stream 占有が 82% と
食い違った事がある。**CUDA event の会計と併記しないと読み違える。**
"""
import argparse
import subprocess
import sys
import threading
import time

import numpy as np

import lib

FIELDS = ["sm", "mem", "enc", "dec", "pwr", "vram"]


class Sampler(threading.Thread):
    """NVML を 100ms 間隔で読む。

    `nvidia-smi dmon` は最短でも 1秒間隔なので、7秒の処理では7点しか取れない。
    NVML を直接読む。
    """

    def __init__(self, interval_s=0.1):
        super().__init__(daemon=True)
        self.interval_s = interval_s
        self.rows = []
        self.stop = threading.Event()

    def run(self):
        from pynvml import (nvmlInit, nvmlShutdown, nvmlDeviceGetHandleByIndex,
                            nvmlDeviceGetUtilizationRates,
                            nvmlDeviceGetEncoderUtilization,
                            nvmlDeviceGetDecoderUtilization,
                            nvmlDeviceGetPowerUsage, nvmlDeviceGetMemoryInfo)
        nvmlInit()
        h = nvmlDeviceGetHandleByIndex(0)
        try:
            while not self.stop.wait(self.interval_s):
                u = nvmlDeviceGetUtilizationRates(h)
                self.rows.append(dict(
                    t=time.time(), sm=float(u.gpu), mem=float(u.memory),
                    enc=float(nvmlDeviceGetEncoderUtilization(h)[0]),
                    dec=float(nvmlDeviceGetDecoderUtilization(h)[0]),
                    pwr=nvmlDeviceGetPowerUsage(h) / 1000.0,
                    vram=nvmlDeviceGetMemoryInfo(h).used / 2 ** 20))
        finally:
            nvmlShutdown()

    def close(self):
        self.stop.set()


def summarize(rows, t0, t1):
    """処理中の区間だけ抜いて集計する。前後の idle を混ぜない。"""
    inside = [r for r in rows if t0 <= r["t"] <= t1]
    if not inside:
        return None
    out = dict(samples=len(inside))
    for k in FIELDS:
        v = np.array([r[k] for r in inside])
        out[k] = dict(mean=round(float(v.mean()), 1),
                      p50=round(float(np.percentile(v, 50)), 1),
                      p90=round(float(np.percentile(v, 90)), 1),
                      max=round(float(v.max()), 1))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default="B_talk")
    ap.add_argument("--fps", default="x2")
    ap.add_argument("--plan", default="retime")
    ap.add_argument("--decode", default="nvdec")
    ap.add_argument("--model", default="v4.6")
    a = ap.parse_args()

    import s8_e2e

    out_fps = 2 * lib.FPS if a.fps == "x2" else float(a.fps)
    mon = Sampler()
    mon.start()
    time.sleep(2.0)                      # idle の基準を取る
    t_idle_end = time.time()

    t0 = time.time()
    rec = s8_e2e.run(a.clip, out_fps, model=a.model, plan=a.plan,
                     decode=a.decode, keep=False)
    t1 = time.time()
    time.sleep(1.5)
    mon.close()
    mon.join(timeout=5)

    idle = summarize(mon.rows, t0 - 2.0, t_idle_end)
    busy = summarize(mon.rows, t0, t1)
    info = dict(clip=a.clip, out_fps=round(out_fps, 3), plan=a.plan,
                decode=a.decode, model=a.model,
                sec=round(t1 - t0, 2), idle=idle, busy=busy,
                e2e_sec=rec.get("sec"), calls=rec.get("calls"))
    lib.record("gpuutil", info)

    print(f"\n{a.clip} {out_fps:.3f}fps {a.plan}/{a.decode}  {t1-t0:.1f}秒")
    print(f"{'':6s}{'平均':>8}{'p50':>8}{'p90':>8}{'最大':>8}   (待機時の平均)")
    label = dict(sm="計算", mem="帯域", enc="NVENC", dec="NVDEC", pwr="電力W", vram="VRAM")
    for k in FIELDS:
        b, i = busy[k], idle[k]
        print(f"{label[k]:6s}{b['mean']:>8.1f}{b['p50']:>8.1f}"
              f"{b['p90']:>8.1f}{b['max']:>8.1f}   {i['mean']:>8.1f}")
    print(f"標本 {busy['samples']}件")


if __name__ == "__main__":
    main()
