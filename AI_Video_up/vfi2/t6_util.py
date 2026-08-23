"""走査(1巡目)と生成(2巡目)それぞれで、CPU と GPU をどれだけ使うか実測する。

「GPU に載せたから速い」は仮定にすぎない。NVENC が CUDA の時間を奪う例
(doc/高速化.md) のように、載せ替えが遅くする事もある。**載せるたびに測る。**

測る物:
  GPU  NVML を 100ms 間隔で読む (lead_gpuutil.Sampler)。sm / NVDEC / NVENC を
       別々に見る。sm だけ見ると NVDEC が仕事をしていても 0% に見える
  CPU  2通りで取る
       使用率   psutil の system 全体。他の作業も混ざるので待機時を引く
       core秒   process 木の cpu_times() の差。**こちらが本命**。
                子(ffmpeg)は終了すると読めなくなるので、走行中に 100ms 間隔で
                pid ごとの最大値を覚えておいて最後に足す。これをやらないと
                CPU 経路の ffmpeg が丸ごと勘定から落ちる

尺の大半を占めるのは生成側なので(5分素材で 走査 20.8秒 対 生成 79.0秒)、
走査だけ測っても「CPU を食うのはどこか」の答えにならない。
"""
import argparse
import threading
import time
from pathlib import Path

import numpy as np
import psutil

import lead_gpuutil as GU
import lib
import vfi

NCPU = psutil.cpu_count(logical=True)


class CpuSampler(threading.Thread):
    """system 全体の使用率と、process 木の CPU 時間を 100ms 間隔で。"""

    def __init__(self, interval_s=0.1):
        super().__init__(daemon=True)
        self.interval_s = interval_s
        self.rows = []
        self.child = {}                   # pid -> 消費した core 秒(最大)
        self.stop = threading.Event()
        self.me = psutil.Process()

    def _own(self):
        t = self.me.cpu_times()
        return t.user + t.system

    def _scan_children(self):
        for c in self.me.children(recursive=True):
            try:
                t = c.cpu_times()
                self.child[c.pid] = max(self.child.get(c.pid, 0.0),
                                        t.user + t.system)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    def run(self):
        psutil.cpu_percent(None)
        while not self.stop.wait(self.interval_s):
            self.rows.append((time.time(), psutil.cpu_percent(None)))
            self._scan_children()

    def close(self):
        self._scan_children()
        self.stop.set()

    def child_total(self):
        return sum(self.child.values())


def pct(rows, t0, t1):
    v = np.array([p for t, p in rows if t0 <= t <= t1])
    if not len(v):
        return None
    return dict(mean=round(float(v.mean()), 1),
                p50=round(float(np.percentile(v, 50)), 1),
                p90=round(float(np.percentile(v, 90)), 1),
                max=round(float(v.max()), 1))


class Measured:
    """区間ごとに CPU/GPU を取る。stage を跨いで1本の sampler を使う。"""

    def __init__(self, warm=2.0):
        self.gpu, self.cpu = GU.Sampler(), CpuSampler()
        self.warm = warm

    def __enter__(self):
        self.gpu.start()
        self.cpu.start()
        time.sleep(self.warm)
        self.t_idle0 = time.time() - self.warm
        self.t_idle1 = time.time()
        return self

    def __exit__(self, *exc):
        time.sleep(1.0)
        self.gpu.close()
        self.cpu.close()
        self.gpu.join(timeout=5)
        self.cpu.join(timeout=5)

    def idle(self):
        return dict(CPU=pct(self.cpu.rows, self.t_idle0, self.t_idle1),
                    GPU=GU.summarize(self.gpu.rows, self.t_idle0, self.t_idle1))

    def section(self, fn):
        own0, ch0 = self.cpu._own(), self.cpu.child_total()
        t0 = time.time()
        out = fn()
        t1 = time.time()
        self.cpu._scan_children()
        core = (self.cpu._own() - own0) + (self.cpu.child_total() - ch0)
        sec = t1 - t0
        return out, dict(秒=round(sec, 2), CPU_core秒=round(core, 1),
                         占有core=round(core / max(sec, 1e-9), 2),
                         CPU使用率=pct(self.cpu.rows, t0, t1),
                         GPU=GU.summarize(self.gpu.rows, t0, t1))


def show(name, m):
    g = m["GPU"]
    print(f"{name:10s}{m['秒']:>8.2f}{m['CPU使用率']['mean']:>8.1f}"
          f"{m['CPU_core秒']:>11.1f}{m['占有core']:>9.2f}"
          f"{g['sm']['mean']:>8.1f}{g['mem']['mean']:>8.1f}"
          f"{g['dec']['mean']:>8.1f}{g['enc']['mean']:>8.1f}"
          f"{g['vram']['max']:>9.0f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--stage", default="both", choices=["scan", "render", "both"])
    ap.add_argument("--scan-mode", default="gpu", choices=["gpu", "cpu"])
    ap.add_argument("--cpu", type=int, default=None, help="変位の worker 上限")
    ap.add_argument("--lowload", action="store_true")
    a = ap.parse_args()

    src = Path(a.input).resolve()
    info = vfi.probe(src)
    fps_out = vfi.parse_fps("x2", info["fps"])
    workers, note = vfi.apply_load_limit(a.cpu, a.lowload)

    rows = {}
    with Measured() as M:
        sc, m = M.section(lambda: vfi.scan(src, info, mode=a.scan_mode,
                                           workers=workers,
                                           ff_threads=workers or 0))
        sc["fps_in"] = info["fps"]
        m["fps"] = round(sc["n_frames"] / m["秒"])
        rows[f"走査({a.scan_mode})"] = m
        if a.stage in ("render", "both"):
            sched, _d, st = vfi.make_schedule(sc, fps_out)
            out_path, tmp = vfi.out_paths(src, "_t6", info)
            tmp.unlink(missing_ok=True)
            out_path.unlink(missing_ok=True)
            _r, m2 = M.section(lambda: vfi.render(
                src, tmp, info, sc, sched, fps_out, "v4.6", "nvdec", 8,
                "-preset p4 -cq 20"))
            m2["fps"] = round(len(sched) / m2["秒"])
            rows["生成"] = m2
            tmp.unlink(missing_ok=True)
            out_path.unlink(missing_ok=True)
        idle = M.idle()

    print(f"\n{src.name}  {info['w']}x{info['h']}  "
          f"{sc['n_frames']:,} frame  論理core {NCPU}  負荷設定: {note}")
    print(f"\n{'区間':10s}{'秒':>8}{'CPU%':>8}{'core秒':>11}{'占有core':>9}"
          f"{'sm%':>8}{'帯域%':>8}{'DEC%':>8}{'ENC%':>8}{'VRAM MB':>9}")
    for k, m in rows.items():
        show(k, m)
        lib.record("t6_util", dict(src=src.name, 区間=k, 負荷=note,
                                   worker=workers, **m))
    ig = idle["GPU"]
    print(f"{'待機':10s}{'':>8}{idle['CPU']['mean']:>8.1f}{'':>11}{'':>9}"
          f"{ig['sm']['mean']:>8.1f}{ig['mem']['mean']:>8.1f}"
          f"{ig['dec']['mean']:>8.1f}{ig['enc']['mean']:>8.1f}"
          f"{ig['vram']['max']:>9.0f}")
    tot_sec = sum(m["秒"] for m in rows.values())
    tot_core = sum(m["CPU_core秒"] for m in rows.values())
    print(f"\n合計 {tot_sec:.1f}秒 / CPU {tot_core:.1f} core秒 "
          f"(平均 {tot_core/max(tot_sec,1e-9):.2f} core 専有)")


if __name__ == "__main__":
    main()
