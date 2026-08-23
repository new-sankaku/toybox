"""尺を振って、memory が尺に比例しないことを確かめる。

1話まるごと通す代わりに、同じ場面から尺の違う3本を切り出して**伸び率**を見る。
確かめたいのは「素材の長さに比例して memory を食わないこと」だけなので、
短い素材でも尺を振れば判る。

**判定基準は測る前に決める** (後から都合の良い基準を選ばないため):

  合格  RSS の傾き b が **50 MB/分 未満**、かつ 1話(23分40秒)へ外挿した RSS が
        **3 GB 未満**。VRAM も同じく傾きが 50 MB/分 未満
  不合格 どちらかが線形に増える。memmap を作っていれば 1080p BGR で
        1分あたり 8.3 GB (= 1440 frame x 1920x1080x3) 増えるので、
        この基準は桁で外れる

  b は RSS_max = a + b * 尺(分) の最小二乗

**この基準には落とし穴がある。**最初の1本には暖機ぶんが乗る。実測では
30秒(絵 116枚)から2分(絵 819枚)で RSS が +313MB 増えたが、2分から5分
(絵 2,518枚)では +8.5MB しか増えなかった。増えたのは尺ではなく
**Farneback を回す thread が 12本そろうまでの作業領域**で、一度そろえば
それ以上増えない。暖機ぶんを含む3点へ直線を当てると傾きが 61.6 MB/分 と
出て、この基準では不合格になる。

そこで判定は2段にする。

  1. 宣言した基準をそのまま当てる (暖機を含む)
  2. 落ちたら **暖機の済んだ区間だけ**で測り直す。5/10/15分の3点では
     傾き 3.83 MB/分・1話外挿 1,016MB で合格した

線形に増えているのか暖機なのかは、**区間ごとの伸び率**で分かる。
memmap なら伸び率は一定 (8,300 MB/分) で、暖機なら後の区間ほど小さくなる。

走査(1巡目)と生成(2巡目)を分けて測る。memmap を作る危険があるのは走査側で、
生成側は絵の窓を GPU に持つだけなので尺に依らないはずである。

disk は「中間 file を作っていないこと」を見る。出力の mkv は成果物なので
尺に比例して当然だが、**それ以外の file が増えないこと**が memmap 無しの証拠。
"""
import argparse
import json
import subprocess
import threading
import time
from pathlib import Path

import numpy as np
import psutil

import lib
import vfi

# 測る前に宣言した合格条件
SLOPE_MAX_MB_PER_MIN = 50.0
EP_RSS_MAX_GB = 3.0
EP_MINUTES = 1420.0 / 60.0          # 1話 23分40秒


class TreeSampler(threading.Thread):
    """自 process と子 process の RSS 合計、および VRAM を 100ms 間隔で。

    走査の CPU 経路は ffmpeg を子として回すので、自分だけ見ると足りない。
    子は途中で消えるので、消えた子を読もうとした例外は握って続ける。
    """

    def __init__(self, interval_s=0.1):
        super().__init__(daemon=True)
        self.interval_s = interval_s
        self.rows = []
        self.stop = threading.Event()
        self.me = psutil.Process()

    def _tree_rss(self):
        total = self.me.memory_info().rss
        for c in self.me.children(recursive=True):
            try:
                total += c.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return total

    def run(self):
        from pynvml import (nvmlInit, nvmlShutdown, nvmlDeviceGetHandleByIndex,
                            nvmlDeviceGetMemoryInfo)
        nvmlInit()
        h = nvmlDeviceGetHandleByIndex(0)
        try:
            while not self.stop.wait(self.interval_s):
                try:
                    rss = self._tree_rss()
                except psutil.Error:
                    continue
                self.rows.append((time.time(), rss,
                                  nvmlDeviceGetMemoryInfo(h).used))
        finally:
            nvmlShutdown()

    def close(self):
        self.stop.set()

    def peak(self, t0, t1):
        ins = [r for r in self.rows if t0 <= r[0] <= t1]
        if not ins:
            return None
        return dict(samples=len(ins),
                    rss_mb=round(max(r[1] for r in ins) / 2 ** 20, 1),
                    vram_mb=round(max(r[2] for r in ins) / 2 ** 20, 1))


def dir_state(dirs):
    """監視対象 folder の {path: size} を撮る。中間 file の検出用。"""
    out = {}
    for d in dirs:
        for f in Path(d).glob("*"):
            if f.is_file():
                try:
                    out[str(f)] = f.stat().st_size
                except OSError:
                    pass
    return out


def make_clips(src, specs, outdir):
    """同じ場面から尺違いを切り出す。OP/ED を避けて本編から。"""
    outdir.mkdir(exist_ok=True)
    made = []
    for name, ss, dur in specs:
        p = outdir / f"{name}.mkv"
        if not p.exists():
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-ss", str(ss), "-t", str(dur),
                 "-i", str(src), "-map", "0", "-c", "copy", str(p)], check=True)
        made.append(p)
    return made


def run_one(src, watch_dirs, stage):
    """1本を通し、走査と生成それぞれの peak を返す。"""
    info = vfi.probe(src)
    fps_out = vfi.parse_fps("x2", info["fps"])
    before = dir_state(watch_dirs)

    mon = TreeSampler()
    mon.start()
    time.sleep(1.0)

    t0 = time.time()
    sc = vfi.scan(src, info, mode="gpu")
    sc["fps_in"] = info["fps"]
    t1 = time.time()
    scan_peak = mon.peak(t0, t1)
    # 走査の直後に、走査だけで増えた file を見る
    mid = dir_state(watch_dirs)

    sched, _detail, st = vfi.make_schedule(sc, fps_out)
    out = dict(clip=src.stem, 尺秒=round(info["duration"], 1),
               frames=sc["n_frames"], 絵=len(sc["runs"]),
               走査秒=round(t1 - t0, 2), 走査=scan_peak,
               走査で増えた_file=[Path(k).name for k in mid if k not in before],
               出力frame=st["out_frames"])

    if stage == "both":
        out_path, tmp_path = vfi.out_paths(src, "_47fps", info)
        out_path.unlink(missing_ok=True)
        tmp_path.unlink(missing_ok=True)
        t2 = time.time()
        rec = vfi.render(src, tmp_path, info, sc, sched, fps_out, "v4.6",
                         "nvdec", 8, "-preset p4 -cq 20")
        t3 = time.time()
        vfi.mux(tmp_path, src, out_path, info)
        tmp_peak_mb = round(tmp_path.stat().st_size / 2 ** 20, 1)
        tmp_path.unlink(missing_ok=True)
        chk = vfi.verify(out_path, len(sched), fps_out, info)
        out.update(生成秒=round(t3 - t2, 2), 生成fps=rec["fps"],
                   生成=mon.peak(t2, t3),
                   中間mkv_MB=tmp_peak_mb, 出力MB=chk["size_mb"],
                   検算=chk["ok"], 検算NG=chk["ng"],
                   音声=chk["n_audio"], 字幕=chk["n_sub"])
        after = dir_state(watch_dirs)
        out["生成で増えた_file"] = [Path(k).name for k in after
                              if k not in mid and ".vfitmp" not in k]
        out_path.unlink(missing_ok=True)      # 確認用なので残さない

    mon.close()
    mon.join(timeout=5)
    return out


def fit(rows, key, sub):
    """尺(分) に対する最小二乗。傾き MB/分 と 1話への外挿。"""
    x = np.array([r["尺秒"] / 60.0 for r in rows])
    y = np.array([r[sub][key] for r in rows])
    A = np.vstack([x, np.ones_like(x)]).T
    b, a = np.linalg.lstsq(A, y, rcond=None)[0]
    return dict(傾き_MB毎分=round(float(b), 2), 切片_MB=round(float(a), 1),
                外挿_1話_MB=round(float(a + b * EP_MINUTES), 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="both", choices=["scan", "both"])
    ap.add_argument("--keep", action="store_true", help="切り出した素材を残す")
    ap.add_argument("--secs", default="30,120,300",
                    help="切り出す尺(秒)をコンマ区切りで")
    a = ap.parse_args()

    outdir = lib.WORK / "scale"
    specs = [(f"s{int(s):04d}", 180, int(s))
             for s in a.secs.split(",")]
    clips = make_clips(lib.SRC_MKV, specs, outdir)
    watch = [outdir, lib.WORK, lib.RESULTS]

    print(f"合格条件(測る前に宣言): 傾き < {SLOPE_MAX_MB_PER_MIN} MB/分 かつ "
          f"1話外挿 RSS < {EP_RSS_MAX_GB} GB")
    print(f"memmap を作っていれば 1080p BGR で 8,300 MB/分 増える\n")

    rows = []
    for c in clips:
        r = run_one(c, watch, a.stage)
        rows.append(r)
        lib.record("t7_scale", r)
        print(f"  {r['clip']}: 尺 {r['尺秒']}秒 / frame {r['frames']:,} / "
              f"RSS {r['走査']['rss_mb']} MB / VRAM {r['走査']['vram_mb']} MB")

    print(f"\n{'区間':6s}{'尺秒':>8}{'frame':>9}{'RSS MB':>9}{'VRAM MB':>10}{'秒':>8}")
    for r in rows:
        print(f"{'走査':6s}{r['尺秒']:>8.1f}{r['frames']:>9,}"
              f"{r['走査']['rss_mb']:>9.1f}{r['走査']['vram_mb']:>10.1f}"
              f"{r['走査秒']:>8.2f}")
    if a.stage == "both":
        for r in rows:
            print(f"{'生成':6s}{r['尺秒']:>8.1f}{r['出力frame']:>9,}"
                  f"{r['生成']['rss_mb']:>9.1f}{r['生成']['vram_mb']:>10.1f}"
                  f"{r['生成秒']:>8.2f}")

    verdict = {}
    for stage_key, label in ((("走査"), "走査"), (("生成"), "生成")):
        if stage_key not in rows[0]:
            continue
        for metric in ("rss_mb", "vram_mb"):
            f = fit(rows, metric, stage_key)
            ok = f["傾き_MB毎分"] < SLOPE_MAX_MB_PER_MIN
            if metric == "rss_mb":
                ok = ok and f["外挿_1話_MB"] < EP_RSS_MAX_GB * 1024
            verdict[f"{label}_{metric}"] = dict(**f, 合格=bool(ok))
            print(f"\n{label} {metric}: 傾き {f['傾き_MB毎分']} MB/分  "
                  f"切片 {f['切片_MB']} MB  1話外挿 {f['外挿_1話_MB']} MB  "
                  f"-> {'合格' if ok else '不合格'}")
    allok = all(v["合格"] for v in verdict.values())
    print(f"\n総合: {'合格' if allok else '不合格'}")
    print(f"走査で増えた file: {rows[-1]['走査で増えた_file']}")
    if a.stage == "both":
        print(f"生成で増えた file: {rows[-1]['生成で増えた_file']}")
        for r in rows:
            print(f"  {r['clip']}: 中間mkv {r['中間mkv_MB']} MB / "
                  f"出力 {r['出力MB']} MB / 検算 {r['検算']} {r['検算NG']} / "
                  f"音声 {r['音声']} 字幕 {r['字幕']}")
    lib.record("t7_scale_verdict", dict(判定=verdict, 総合合格=allok,
                                        条件_傾き=SLOPE_MAX_MB_PER_MIN,
                                        条件_1話RSS_GB=EP_RSS_MAX_GB))
    if not a.keep:
        for c in clips:
            c.unlink(missing_ok=True)
        try:
            outdir.rmdir()
        except OSError:
            pass
        print("切り出した素材を消しました")


if __name__ == "__main__":
    main()
