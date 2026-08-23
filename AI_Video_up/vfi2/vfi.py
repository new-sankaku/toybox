"""動画の frame 補完。絵の列へ時刻を張り直して出力 fps を上げる。

設計の根拠は doc/時刻張り直し.md。要点だけ:

  素直な x2 (frame と frame の間に1枚) は、限定 animation では中間 frame の
  8割が「同じ絵と同じ絵の間」でただの複製になる。frame ではなく **絵の列**を
  時間軸に置き、目標 fps の各出力時刻を挟む2枚の絵から作る。

関門(補間してはいけない所)も実測で決まっている:

  cut を跨ぐ pair          model が hold の 1.3〜1.6倍悪い
  保持 9 frame 以上の pair 意図的な静止。溶かすと元に無い動きを作る
  絵間変位 64px 超の pair  model が単純平均に負ける

検証 script (s8_e2e.py 等) との最大の違いは **素材を memmap へ展開しない**こと。
30秒の 1080p で 4.5GB、1話なら 197GB になり成立しない。1巡目は低解像度の
Y を stream で読み、絵の切り替わりと cut だけを覚える。

  1巡目(走査)  絵の列・cut・絵間変位を作る。持つのは絵1枚ぶんの縮小 Y だけ
  2巡目(生成)  NVDEC/pipe -> RIFE(TensorRT fp16) -> NVENC。映像だけ書く
  3巡目(mux)   元 file から音声・字幕・添付(字幕用の書体)を copy で入れる

1巡目は GPU 経路(既定)と CPU 経路のどちらでも同じ答えを出せるように書いてある。

  GPU  NVDEC -> Y 平面から 480幅へ面積平均 / 絵の差分 / scdet の式
  CPU  ffmpeg 1本で scdet と縮小 Y を同時に出す

両者が一致することは t4_scangpu.py と t5_scdgpu.py で実測してある
(NVDEC の Y は libavcodec と bit 一致、scdet の score は metadata の丸め
0.0005 以内、cut の集合は完全一致)。**残る CPU は絵間変位の Farneback だけ**で、
これは OpenCV に CUDA 版が無く、別の flow へ替えると 64px の関門を測り直しに
なるので CPU に残してある (doc/使い方.md 参照)。
"""
import argparse
import collections
import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys
import threading
import time
import traceback
from fractions import Fraction
from pathlib import Path

import cv2
import numpy as np
import psutil
import torch
import torch.nn.functional as F

import fastio
import lib
import retime
import runner as RN

VIDEO_EXT = {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".flv", ".webm", ".m4v",
             ".mpg", ".mpeg", ".ts", ".m2ts"}

# 走査の判定値。doc/時刻張り直し.md 3章と lead_coverage.py で実測して決めた物。
# 解像度にも fps にも依存しない (幅 480 の Y に対する画素差と、原寸へ戻した px)
SCAN_W = 480          # 判定値用の幅。変位はここから原寸へ戻す
# 縮小 Y の max|差| がこれ未満なら同じ絵。原寸の box4>=16 と最も合う値を3本の
# clip で選び直した (t2_thresh.py)。選ぶ基準は recall/prec ではなく **関門が
# 占める尺**。出力の見た目を決めるのはそちらだから。
#   C_act  10 で 静止尺 +0.2 / 封じた尺 +0.0、12 では +2.4 / +2.2
#   A_op   10 と 12 で差が無い (封じた尺 -1.2)
#   B_talk 6〜18 のどれでも原寸と完全一致
# 判定用の画素を full range の gray から limited の Y へ変えたので、以前の 12 が
# ここでは 10 になる (12 * 219/255 = 10.3)。閾値の意味は変わっていない
SAME_TH = 10
HOLD_MAX = 8          # 保持がこれを超える pair は意図的な静止として封じる
SPAN_LIMIT = 64.0     # 絵間変位(原寸px)。これを超えたら封じる
SCD_CUT = lib.SCD_CUT # ffmpeg scdet の score。これ以上を cut の候補とする

FLOW_QUEUE = 256      # 変位計算の未処理数の上限。超えたら decode を待たせる


def fmt_time(sec):
    sec = int(sec)
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    if h:
        return f"{h}時間{m}分{s}秒"
    if m:
        return f"{m}分{s}秒"
    return f"{s}秒"


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------- 素材を調べる

def probe(src):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_streams", "-show_format", str(src)],
        capture_output=True, text=True, encoding="utf-8", check=True).stdout
    d = json.loads(out)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), None)
    if v is None:
        raise RuntimeError(f"映像 stream がありません: {src.name}")

    r = Fraction(v["r_frame_rate"])
    avg = Fraction(v["avg_frame_rate"]) if v.get("avg_frame_rate") not in (
        None, "0/0") else r
    if r <= 0:
        raise RuntimeError(f"fps を読めません: {v['r_frame_rate']}")
    if avg > 0 and abs(float(avg) - float(r)) / float(r) > 0.005:
        raise RuntimeError(
            f"VFR らしき素材です (r_frame_rate {r} 対 avg_frame_rate {avg})。"
            "絵の列は frame 番号を時刻へ写して作るので、この tool は CFR 前提です")

    sar = v.get("sample_aspect_ratio")
    if sar in (None, "N/A", "0:1"):
        sar = "1:1"
    return dict(
        w=int(v["width"]), h=int(v["height"]),
        fps=r, pix_fmt=v.get("pix_fmt", ""),
        color_space=v.get("color_space", ""),
        color_range=v.get("color_range", ""),
        sar=sar,
        duration=float(d["format"].get("duration") or v.get("duration") or 0),
        n_audio=sum(1 for s in d["streams"] if s["codec_type"] == "audio"),
        n_sub=sum(1 for s in d["streams"] if s["codec_type"] == "subtitle"),
        n_att=sum(1 for s in d["streams"] if s["codec_type"] == "attachment"),
    )


def pick_decode(info, want):
    """decode 経路を決める。auto は理由を必ず名乗る(黙って落とさない)。"""
    if want != "auto":
        return want, "指定"
    if info["pix_fmt"] not in ("yuv420p", "yuvj420p"):
        return "pipe", f"{info['pix_fmt']} は NVDEC の NV12 経路では扱えません"
    if info["color_space"] not in ("bt709", "", "unknown"):
        return "pipe", f"色空間が {info['color_space']} です (NVDEC 経路は bt709 前提)"
    return "nvdec", "8bit 4:2:0 / bt709"


def out_paths(src, suffix, info):
    """出力の path。字幕を落とさない容器を選ぶ。

    .mp4/.mov は字幕(ass)と添付(書体)を copy で入れられないので、字幕が
    在る素材と、そもそも hevc を入れられない容器は .mkv にする。
    """
    ext = src.suffix.lower()
    if ext in (".mp4", ".mov") and info["n_sub"] == 0:
        out_ext = ext
    else:
        out_ext = ".mkv"
    out = src.with_name(src.stem + suffix + out_ext)
    tmp = src.with_name(src.stem + suffix + ".vfitmp" + out_ext)
    return out, tmp


# ---------------------------------------------------------------- 1巡目: 走査

class _Flow(threading.local):
    """Farneback は thread ごとに持つ。r1_cadence.py と同じ設定にする

    (関門の 64px は、この設定で測った変位に対して決めた値)。
    """

    @property
    def calc(self):
        f = getattr(self, "_f", None)
        if f is None:
            f = cv2.FarnebackOpticalFlow_create(
                numLevels=5, pyrScale=0.5, winSize=25, numIters=3,
                polyN=5, polySigma=1.2)
            self._f = f
        return f


_FLOW = _Flow()


def _span_px(a, b, to_full):
    f = _FLOW.calc.calc(a, b, None)
    mag = np.sqrt(f[..., 0] ** 2 + f[..., 1] ** 2)
    return float(np.percentile(mag, 95)) * to_full


class _Runs:
    """絵の列と絵間変位を積む。CPU 経路と GPU 経路で共有する。

    「同じ絵か」の判定そのものは呼び出し側が行う (numpy と torch で別)。
    ここに集めるのは、その判定より後の帳簿だけ — 絵の先頭 frame・1つ前との
    差・Farneback の予約。**両経路で同じ帳簿を通す**ので、結果が食い違ったら
    原因は判定に使う gray の画素だけに絞れる。
    """

    def __init__(self, to_full, n_est, workers=None):
        self.to_full = to_full
        self.n_est = n_est
        self.starts, self.dprev, self.mv = [], [], []
        self.head = None                # 今の絵の先頭 (CPU 上の gray)
        self.ex = cf.ThreadPoolExecutor(
            max_workers=max(1, workers or (os.cpu_count() or 4)))
        self.futs = collections.deque()
        self.t0 = self.last = time.time()

    def drain(self, limit):
        while len(self.futs) > limit:
            self.mv.append(self.futs.popleft().result())

    def push(self, i, d_prev, gray_cpu):
        """frame i を積む。gray_cpu が None でなければ新しい絵の先頭。"""
        self.dprev.append(int(d_prev))
        if gray_cpu is not None:
            if self.head is not None:
                self.futs.append(
                    self.ex.submit(_span_px, self.head, gray_cpu, self.to_full))
                self.drain(FLOW_QUEUE)
            self.head = gray_cpu
            self.starts.append(i)

    def tick(self, i):
        now = time.time()
        if now - self.last > 2.0:
            self.last = now
            pct = min(100.0, i / self.n_est * 100)
            log(f"  走査 {i:,}/{self.n_est:,} frame ({pct:.0f}%)  "
                f"絵 {len(self.starts):,}  経過 {fmt_time(now - self.t0)}")

    def close(self):
        self.ex.shutdown(wait=True)

    def finish(self, n, src, raw):
        if n == 0:
            raise RuntimeError(f"frame を1枚も読めませんでした: {src.name}")
        cuts, vote = _cut_starts(raw, np.array(self.dprev, dtype=np.int32))
        log(f"  走査おわり: frame {n:,} / 絵 {len(self.starts):,} "
            f"(1枚 {n/len(self.starts):.2f} frame) / cut {len(cuts)}  "
            f"{fmt_time(time.time() - self.t0)}")
        if vote[1]:
            log(f"    cut の位置: score の frame が新 shot の先頭 {vote[0]}件 / "
                f"1つ後ろ {vote[1]}件")
        return dict(n_frames=n, runs=np.array(self.starts, dtype=np.int64),
                    cuts=cuts, mv=np.array(self.mv, dtype=np.float32))


def apply_load_limit(cpu, lowload):
    """CPU の使い方を絞る。既定(どちらも未指定)は速度優先で何もしない。

    絞る先は3つ。**どれも出力を変えない**(絵の列も変位も同じ値になる)。

      変位の worker 数  ここが CPU のほぼ全部。t8_cpubreak.py の実測で、
                        走査の CPU の 99.2% が Farneback だった
                        (変位を計算しない走査は 0.12 core)
      OpenCV の内部 thread  worker ごとに更に並列化するので、絞る時は
                        こちらも絞らないと thread が溢れる
      process 優先度    低くすると、user の他の作業に順番を譲る。
                        Windows では子(ffmpeg)が優先度を継承するので、
                        ffmpeg を spawn する前に設定する

    戻り値の worker は ffmpeg の -threads にも使う。
    """
    ncpu = os.cpu_count() or 4
    if cpu is not None and cpu < 1:
        raise ValueError(f"--cpu は 1 以上です: {cpu}")
    workers = cpu if cpu else (max(1, ncpu // 4) if lowload else None)
    if workers:
        cv2.setNumThreads(workers)
        torch.set_num_threads(workers)
    if lowload:
        try:
            psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        except (AttributeError, psutil.Error) as exc:
            # Windows 以外や権限が無い時。優先度が下がらないだけで動く
            log(f"  優先度を下げられませんでした: {exc}")
    if workers is None:
        return None, f"速度優先 (worker {ncpu})"
    return workers, (f"低負荷 worker {workers}/{ncpu} + 優先度を下げる"
                     if lowload else f"worker {workers}/{ncpu}")


def scan_dims(info, scan_w):
    """判定用の縮小寸法。yuv420p を通すので幅も高さも偶数にする。"""
    w, h = info["w"], info["h"]
    sw = max(2, int(scan_w) // 2 * 2)
    sh = max(2, int(round(h * sw / w)) // 2 * 2)
    return sw, sh, w / sw


def scan_cpu(src, info, scan_w=SCAN_W, same_th=SAME_TH, workers=None,
             ff_threads=0):
    """CPU 経路。ffmpeg 1本で scdet と縮小 Y を同時に出す。

    scdet(原寸) の score は file へ、判定用の Y は pipe へ。
    Y は絵1枚ぶんしか保持しない。

    `format=gray` ではなく `format=yuv420p,extractplanes=y` を通す。gray は
    limited(16-235) を full(0-255) へ広げる format で、その拡張が swscale の
    実装依存の丸めを持ち込む。実測すると GPU 側で同じ拡張を式で書いても
    A_op で画素が最大 18 ずれた (縮小器そのものの差は最大 1 だった)。
    拡張は情報を増やさないので、両経路とも **limited のまま**の Y で判定する。
    """
    sw, sh, to_full = scan_dims(info, scan_w)
    n_est = max(1, int(round(info["duration"] * float(info["fps"]))))

    scene = lib.RESULTS / f"scene_{os.getpid()}.txt"
    scene.unlink(missing_ok=True)
    # filter の引数に Windows の絶対path を書くと `\` と `:` で parse に落ちる。
    # results/ を cwd にして相対名で渡す
    fc = (f"[0:v]split=2[a][b];"
          f"[a]scdet=threshold=0,metadata=print:file={scene.name}[s];"
          f"[b]scale={sw}:{sh}:flags=area,format=yuv420p,extractplanes=y[g]")
    thr = ["-threads", str(ff_threads)] if ff_threads else []
    p = subprocess.Popen(
        ["ffmpeg", "-v", "error"] + thr + ["-i", str(src),
         "-filter_complex", fc,
         "-map", "[g]", "-fps_mode", "passthrough", "-an",
         "-f", "rawvideo", "-pix_fmt", "gray", "-",
         "-map", "[s]", "-fps_mode", "passthrough", "-an", "-f", "null", "-"],
        stdout=subprocess.PIPE, cwd=str(lib.RESULTS))   # bufsize は渡さない

    ring = [np.empty((sh, sw), np.uint8) for _ in range(2)]
    R = _Runs(to_full, n_est, workers)
    i = 0
    try:
        while True:
            cur = ring[i & 1]
            if p.stdout.readinto(memoryview(cur.reshape(-1))) < sw * sh:
                break
            prev = ring[(i - 1) & 1]
            new = None
            if R.head is None or int(cv2.absdiff(R.head, cur).max()) >= same_th:
                new = cur.copy()
            R.push(i, 0 if i == 0 else int(cv2.absdiff(prev, cur).max()), new)
            i += 1
            R.tick(i)
        R.drain(0)
    finally:
        R.close()
        try:
            p.stdout.close()
        except OSError:
            pass
        p.wait()
    raw = _read_scdet(scene, i)
    scene.unlink(missing_ok=True)
    out = R.finish(i, src, raw)
    out.update(scan_w=sw, scan_h=sh, scan="cpu", scd=raw)
    return out


def gpu_scan_reason(info):
    """GPU 走査に載せられるか。載せられないなら理由を返す。

    pick_decode と違って色空間は見ない。走査は Y 平面しか使わず、色を
    作らないので bt709 かどうかが結果に関わらない。見るのは NV12 で
    受け取れる形式かどうかだけ。
    """
    if info["pix_fmt"] not in ("yuv420p", "yuvj420p"):
        return False, f"{info['pix_fmt']} は NVDEC の NV12 経路では扱えません"
    return True, "8bit 4:2:0"


def scan_gpu(src, info, scan_w=SCAN_W, same_th=SAME_TH, workers=None):
    """GPU 経路。NVDEC で decode し、縮小・差分・scdet を GPU で行う。

    CPU 経路との対応:

      ffmpeg decode      -> NVDEC。Y/U/V は libavcodec と **bit 一致** する
                            (t4_scangpu.py で実測。H.264/HEVC の復号は規格上
                            bit exact なので当然だが、確かめてある)
      scale=area         -> 面積平均。CPU 経路の縮小 Y と画素で最大 1 しか
                            違わない (t4_scangpu.py)
      scdet              -> 同じ式を Y 平面へ掛ける。
                            mafd = sad_Y*100/(w*h*256)
                            score = min(mafd, |mafd - 前の mafd|)
                            ffmpeg の出力と 0.0005 (metadata の丸め) 以内で
                            一致することを t5_scdgpu.py で実測した

    絵の切り替わり判定は前の絵の先頭と比べるので frame ごとに逐次で、GPU の
    結果を1つずつ CPU へ降ろす必要がある。3つの scalar を1つの tensor へ束ねて
    降ろし、同期は frame あたり1回に抑える。
    """
    import pathlib
    os.add_dll_directory(str(pathlib.Path(torch.__file__).parent / "lib"))
    import PyNvVideoCodec as nvc

    w, h = info["w"], info["h"]
    sw, sh, to_full = scan_dims(info, scan_w)
    n_est = max(1, int(round(info["duration"] * float(info["fps"]))))
    cnt = float(w * h) * 256.0 / 100.0        # mafd の分母

    dmx = nvc.CreateDemuxer(filename=str(src))
    dec = nvc.CreateDecoder(gpuid=0, codec=dmx.GetNvCodecId(), cudacontext=0,
                            cudastream=0, usedevicememory=True)
    R = _Runs(to_full, n_est, workers)
    prev_y = torch.empty((h, w), dtype=torch.int16, device="cuda")
    prev_g = torch.empty((sh, sw), dtype=torch.float32, device="cuda")
    head_g = torch.empty((sh, sw), dtype=torch.float32, device="cuda")
    scores = []
    prev_mafd = None
    i = 0
    try:
        for pkt in dmx:
            for f in dec.Decode(pkt):
                y = torch.from_dlpack(f)[:h].to(torch.int16)
                g = F.adaptive_avg_pool2d(
                    y.to(torch.float32)[None, None], (sh, sw))[0, 0]
                g = g.round_().clamp_(0.0, 255.0)
                if i == 0:
                    trio = torch.zeros(3, dtype=torch.float64, device="cuda")
                else:
                    trio = torch.stack((
                        (y - prev_y).abs_().sum(dtype=torch.float64),
                        (g - prev_g).abs().max().to(torch.float64),
                        (g - head_g).abs().max().to(torch.float64)))
                sad, d_prev, d_head = (float(x) for x in trio.cpu())

                if i:
                    mafd = sad / cnt
                    # ffmpeg は 1つ前が無い時 prev_mafd=0 から始めるので、
                    # min(mafd, |mafd - 0|) = mafd。上限 100 も同じく合わせる
                    scores.append(min(100.0, mafd if prev_mafd is None
                                      else min(mafd, abs(mafd - prev_mafd))))
                    prev_mafd = mafd
                new = None
                if i == 0 or d_head >= same_th:
                    head_g.copy_(g)
                    new = np.ascontiguousarray(
                        g.to(torch.uint8).cpu().numpy())
                R.push(i, d_prev, new)
                prev_y.copy_(y)
                prev_g.copy_(g)
                i += 1
                R.tick(i)
        R.drain(0)
    finally:
        R.close()
        dec = None
        dmx = None
    raw = np.array([0.0] + scores, dtype=np.float32)[:max(i, 1)]
    out = R.finish(i, src, raw)
    out.update(scan_w=sw, scan_h=sh, scan="gpu", scd=raw)
    return out


def scan(src, info, scan_w=SCAN_W, same_th=SAME_TH, mode="gpu",
         workers=None, ff_threads=0):
    """1巡目。mode は gpu / cpu / auto。auto は載らない理由を必ず名乗る。"""
    if mode == "auto":
        ok, why = gpu_scan_reason(info)
        mode = "gpu" if ok else "cpu"
        if not ok:
            log(f"  走査は CPU で行います: {why}")
    if mode == "gpu":
        ok, why = gpu_scan_reason(info)
        if not ok:
            raise RuntimeError(f"GPU 走査に載せられません: {why}")
        return scan_gpu(src, info, scan_w, same_th, workers)
    if mode == "cpu":
        return scan_cpu(src, info, scan_w, same_th, workers, ff_threads)
    raise ValueError(f"走査は gpu か cpu か auto です: {mode}")


def _read_scdet(path, n):
    if not path.exists():
        raise RuntimeError(f"scdet の出力がありません: {path}")
    out = np.zeros(n, dtype=np.float32)
    cur = None
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line.startswith("frame:"):
            cur = int(line.split()[0].split(":")[1])
        elif "lavfi.scd.score=" in line and cur is not None and cur < n:
            out[cur] = float(line.split("=")[1])
    return out


def _cut_starts(raw, dprev):
    """score が付いた frame から、新 shot の先頭 frame を決める。

    ffmpeg の scdet は比較後の frame(= 新 shot の先頭)へ score を付けるが、
    規約を仮定で決めない (doc の lib._scd_convention_shift と同じ立場)。
    候補ごとに、その前後どちらの変わり目が大きいかを **画素で** 見て決める。
    """
    n = len(raw)
    out, vote = [], [0, 0]
    for i in np.where(raw >= SCD_CUT)[0]:
        i = int(i)
        d_here = dprev[i] if i < n else 0
        d_next = dprev[i + 1] if i + 1 < n else 0
        if d_here >= d_next:
            out.append(i)
            vote[0] += 1
        else:
            out.append(i + 1)
            vote[1] += 1
    return np.array(sorted(set(out)), dtype=np.int64), vote


# ---------------------------------------------------------------- schedule

def build_block(sc, hold_max=HOLD_MAX, span_limit=SPAN_LIMIT):
    """pair k (絵k -> 絵k+1) を補間してはいけないか。"""
    runs, n = sc["runs"], sc["n_frames"]
    K = len(runs)
    ends = np.append(runs[1:], n)
    hold = ends - runs                       # 各絵が保持される frame 数
    is_still = hold[:-1] > hold_max
    is_far = sc["mv"] > span_limit
    # pair k は runs[k] < b <= runs[k+1] に新 shot の先頭 b が在れば cut を跨ぐ
    pos = np.searchsorted(sc["cuts"], runs[1:], side="right") \
        - np.searchsorted(sc["cuts"], runs[:-1], side="right")
    is_cut = pos > 0
    if len(is_far) != K - 1:
        raise RuntimeError(f"変位の数が合いません: {len(is_far)} != {K-1}")
    blocked = is_cut | is_still | is_far
    dur = hold[:-1] / float(sc["fps_in"])
    total = float(dur.sum()) or 1.0
    detail = {}
    for name, m in (("cut", is_cut), ("意図的な静止", is_still),
                    ("大変位", is_far), ("封じた計", blocked), ("通した", ~blocked)):
        detail[name] = dict(pair=int(m.sum()),
                            pair_pct=round(float(m.mean()) * 100, 1),
                            尺秒=round(float(dur[m].sum()), 1),
                            尺_pct=round(float(dur[m].sum()) / total * 100, 1))
    return blocked, detail


def make_schedule(sc, fps_out):
    blocked, detail = build_block(sc)
    sched = retime.build(sc["runs"], sc["n_frames"], float(sc["fps_in"]),
                         float(fps_out), anchor="head", block=blocked)
    st = retime.stats(sched, sc["n_frames"] / float(sc["fps_in"]))
    return sched, detail, st


# ---------------------------------------------------------------- 2巡目: 生成

def render(src, out_video, info, sc, sched, fps_out, model, decode,
           batch, enc_args):
    w, h = info["w"], info["h"]
    fr = Fraction(fps_out)
    window = max(8, batch + 4)
    n_total = len(sched)

    if decode == "nvdec":
        srcimg = fastio.NvdecDrawingSource(src, w, h, sc["runs"], window=window)
    elif decode == "pipe":
        srcimg = fastio.DrawingSource(src, w, h, sc["runs"], window=window)
    else:
        raise ValueError(f"decode は auto か nvdec か pipe です: {decode}")

    args = enc_args
    sn, sd = (int(x) for x in info["sar"].split(":"))
    if sn != sd:
        # rawvideo で渡すと SAR が失われる。anamorphic 素材が潰れて出るのを防ぐ
        from math import gcd
        dn, dd = w * sn, h * sd
        g = gcd(dn, dd)
        args = f"{args} -aspect {dn//g}:{dd//g}"

    wr = fastio.NvencWriter(out_video, w, h, fr.numerator, fr.denominator,
                            args=args)
    r = RN.BatchRunner(model, w, h, batch=batch, frames=srcimg, sink=wr.sink)
    t0 = last = time.time()
    try:
        for j, s in enumerate(sched):
            k = int(s["k"])
            if int(s["kind"]) == retime.MODEL:
                r.submit(k, k + 1, float(s["tau"]), j)
            else:
                r.submit(k, k, 0.0, j)
            # 予約はまとめて後で実行される。flush が起きた時にだけ捨てる
            if not r.pending and k >= 1:
                srcimg.release_before(k - 1)
            now = time.time()
            if now - last > 2.0:
                last = now
                done = wr.n
                el = now - t0
                eta = el / done * (n_total - done) if done else 0
                log(f"  生成 {done:,}/{n_total:,} frame "
                    f"({done/n_total*100:.0f}%)  {done/max(el,1e-9):.0f} fps  "
                    f"経過 {fmt_time(el)}  残り {fmt_time(eta)}")
        stat = r.close()
        n_out = wr.close()
    finally:
        srcimg.close()
        del r
        torch.cuda.empty_cache()
    dt = time.time() - t0
    if n_out != n_total:
        raise RuntimeError(f"出力 frame が足りません: {n_out} != {n_total}")
    return dict(sec=round(dt, 2), out_frames=n_out, calls=stat["calls"],
                exact=stat["exact"], fps=round(n_out / dt, 1))


def mux(out_video, src, out_path, info):
    """映像に、元 file の音声・字幕・添付(字幕用の書体)を copy で入れる。"""
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(out_video), "-i", str(src),
           "-map", "0:v:0"]
    if info["n_audio"]:
        cmd += ["-map", "1:a?"]
    if info["n_sub"]:
        cmd += ["-map", "1:s?"]
    if info["n_att"]:
        cmd += ["-map", "1:t?"]
    cmd += ["-c", "copy", str(out_path)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError(f"mux に失敗しました: {r.stderr.strip()}")


def _ffprobe_json(args, what):
    """ffprobe を JSON で読む。returncode を見てから parse する。

    見ないと、ffprobe が落ちた時に空文字を json.loads して
    「Expecting value: line 1 column 1」だけが出る。何が起きたか分からない。
    """
    r = subprocess.run(["ffprobe", "-v", "error", "-of", "json"] + args,
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError(
            f"{what} の ffprobe に失敗しました (rc={r.returncode}): "
            f"{r.stderr.strip() or '出力が空です'}")
    return json.loads(r.stdout)


def verify(out_path, n_expect, fps_out, info):
    # frame 数は -count_packets で数える。-count_frames は全部 decode するので、
    # 1話ぶん(68,094 frame)で生成そのものより時間が掛かった。packet と frame は
    # H.264/HEVC では1対1 (1 packet = 1 access unit = 1 frame) で、実測でも
    # 30秒2本と1話で -count_frames と同じ値になり、1話 374ms 対 18分以上だった
    v = _ffprobe_json(
        ["-count_packets", "-select_streams", "v:0", "-show_entries",
         "stream=nb_read_packets,r_frame_rate,width,height", str(out_path)],
        "出力の frame 数")["streams"][0]
    d = _ffprobe_json(["-show_streams", "-show_format", str(out_path)],
                      "出力の stream 構成")
    got = dict(frames=int(v["nb_read_packets"]), fps=v["r_frame_rate"],
               w=int(v["width"]), h=int(v["height"]),
               sec=round(float(d["format"].get("duration") or 0), 3),
               n_audio=sum(1 for s in d["streams"] if s["codec_type"] == "audio"),
               n_sub=sum(1 for s in d["streams"] if s["codec_type"] == "subtitle"),
               size_mb=round(Path(out_path).stat().st_size / 2 ** 20, 1))
    got["video_sec"] = round(n_expect / float(fps_out), 3)
    ng = []
    if got["frames"] != n_expect:
        ng.append(f"frame {got['frames']} != {n_expect}")
    # mkv は timestamp を 1ms 刻みで持つので 48000/1001 を正確に書けない。
    # ffprobe が読み戻す r_frame_rate は 7001/146 のような近い有理数になる
    if abs(float(Fraction(got["fps"])) / float(fps_out) - 1) > 0.002:
        ng.append(f"fps {got['fps']} != {Fraction(fps_out)}")
    if (got["w"], got["h"]) != (info["w"], info["h"]):
        ng.append(f"解像度 {got['w']}x{got['h']} != {info['w']}x{info['h']}")
    # 映像の時間軸は frame 数と fps で決まり切っているので、ここで見るのは
    # 「元と同じ長さの物が出たか」。音声が映像より長い素材が在るので容器の尺で比べる
    if abs(got["sec"] - info["duration"]) > 1.0:
        ng.append(f"尺 {got['sec']} != 元の {info['duration']:.3f}")
    if got["n_audio"] != info["n_audio"]:
        ng.append(f"音声 {got['n_audio']} != {info['n_audio']}")
    if got["n_sub"] != info["n_sub"]:
        ng.append(f"字幕 {got['n_sub']} != {info['n_sub']}")
    got["ok"] = not ng
    got["ng"] = ng
    return got


# ---------------------------------------------------------------- 1本ぶん

def process(src, args):
    info = probe(src)
    fps_out = parse_fps(args.fps, info["fps"])
    suffix = args.suffix or f"_{int(float(fps_out))}fps"
    out_path, tmp_path = out_paths(src, suffix, info)
    if out_path.exists():
        log(f"飛ばします(出力済み): {out_path.name}")
        return None
    decode, why = pick_decode(info, args.decode)

    log(f"入力: {src.name}")
    log(f"  {info['w']}x{info['h']}  {float(info['fps']):.3f} fps  "
        f"{fmt_time(info['duration'])}  音声 {info['n_audio']} / "
        f"字幕 {info['n_sub']} / 添付 {info['n_att']}")
    log(f"  出力: {out_path.name}  {float(fps_out):.3f} fps "
        f"({Fraction(fps_out)})  decode: {decode} ({why})")

    t_all = time.time()
    sc = scan(src, info, scan_w=args.scan_width, mode=args.scan,
              workers=args.workers, ff_threads=args.workers or 0)
    sc["fps_in"] = info["fps"]
    t_scan = time.time() - t_all

    sched, detail, st = make_schedule(sc, fps_out)
    log(f"  出力 {st['out_frames']:,} frame = 写し {st['copy']:,} + "
        f"補間 {st['calls']:,} + 保持 {st['hold']:,}  "
        f"異なる絵 {st['distinct_per_sec']}/秒")
    for name in ("cut", "意図的な静止", "大変位", "封じた計", "通した"):
        d = detail[name]
        log(f"    {name}: pair {d['pair']:,} ({d['pair_pct']}%)  "
            f"尺 {d['尺秒']}秒 ({d['尺_pct']}%)")
    if args.plan_only:
        lib.record("vfi_plan", dict(src=src.name, fps_out=str(Fraction(fps_out)),
                                    scan_sec=round(t_scan, 1),
                                    n_frames=sc["n_frames"],
                                    drawings=len(sc["runs"]), **st))
        return None

    tmp_path.unlink(missing_ok=True)
    try:
        with lib.gpu_use("tool") if not args.gpu_lock else lib.gpu_lock("tool"):
            busy = lib.gpu_busy_pct()
            rec = render(src, tmp_path, info, sc, sched, fps_out, args.model,
                         decode, args.batch, args.enc)
        mux(tmp_path, src, out_path, info)
        tmp_path.unlink(missing_ok=True)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        out_path.unlink(missing_ok=True)
        raise

    chk = verify(out_path, len(sched), fps_out, info)
    total = time.time() - t_all
    log(f"  生成 {rec['sec']}秒 ({rec['fps']} fps)  走査 {t_scan:.1f}秒  "
        f"合計 {fmt_time(total)}")
    log(f"  検算 {'OK' if chk['ok'] else 'NG ' + ' / '.join(chk['ng'])}: "
        f"{chk['frames']:,} frame / {chk['fps']} / 映像 {chk['video_sec']}秒 / "
        f"容器 {chk['sec']}秒 (元 {info['duration']:.3f}秒) / "
        f"音声 {chk['n_audio']} / 字幕 {chk['n_sub']} / {chk['size_mb']} MB")
    lib.record("vfi_run", dict(
        src=src.name, out=out_path.name, w=info["w"], h=info["h"],
        fps_in=str(info["fps"]), fps_out=str(Fraction(fps_out)),
        model=args.model, decode=decode, scan=sc["scan"], enc=args.enc,
        n_frames=sc["n_frames"], drawings=len(sc["runs"]),
        cuts=len(sc["cuts"]), scan_sec=round(t_scan, 1),
        gate=detail, sched=st, render=rec, total_sec=round(total, 1),
        gpu_busy_pct=busy[0], gpu_mem_mb=busy[1], verify=chk))
    if not chk["ok"]:
        # 壊れた出力を残すと、次に流した時に「出力済み」で飛ばしてしまう
        out_path.unlink(missing_ok=True)
        raise RuntimeError(f"出力の検算に失敗しました: {chk['ng']}")
    return chk


def parse_fps(spec, fps_in):
    """`x2` は源の fps の厳密な2倍。

    47.952 と丸めると出力時刻が絵の時刻と一致せず、只で写せた frame が
    全部補間対象へ落ちて 1.41倍遅くなる (doc/高速化.md 6-5)。
    """
    spec = str(spec).strip()
    if spec.startswith("x"):
        m = Fraction(spec[1:])
        return Fraction(fps_in) * m
    return Fraction(spec)


def is_own_output(stem, suffix_hint):
    """この tool が前に出した file か。既定の suffix は fps から作るので形で見る。"""
    if suffix_hint:
        return stem.endswith(suffix_hint)
    return re.search(r"_\d+fps$", stem) is not None


def expand(paths, suffix_hint):
    out, seen = [], set()
    for raw in paths:
        src = Path(raw)
        if not src.exists():
            raise SystemExit(f"エラー: 見つかりません {src}")
        found = (sorted(f for f in src.iterdir()
                        if f.is_file() and f.suffix.lower() in VIDEO_EXT)
                 if src.is_dir() else [src])
        for f in found:
            if f.suffix.lower() not in VIDEO_EXT:
                log(f"対象外: {f.name}")
                continue
            if ".vfitmp" in f.name or is_own_output(f.stem, suffix_hint):
                log(f"飛ばします(出力済み): {f.name}")
                continue
            # 走査の ffmpeg は results/ を cwd にして動く(filter の引数に
            # Windows の絶対path を書けないため)。相対path のままだと入力を見失う
            f = f.resolve()
            key = str(f).lower()
            if key not in seen:
                seen.add(key)
                out.append(f)
    return out


def main():
    ap = argparse.ArgumentParser(
        description="絵の列へ時刻を張り直して frame を補完します")
    ap.add_argument("input", nargs="*", help="動画 file か、動画の入った folder")
    ap.add_argument("--fps", default="x2",
                    help="出力 fps。x2 は源の厳密な2倍(既定)。60 や 60000/1001 も可")
    ap.add_argument("--model", default="v4.6", help="RIFE の model 名")
    ap.add_argument("--decode", default="auto", choices=["auto", "nvdec", "pipe"])
    ap.add_argument("--scan", default="auto", choices=["auto", "gpu", "cpu"],
                    help="1巡目の走査をどちらで行うか (既定は auto = 載るなら GPU)")
    ap.add_argument("--batch", type=int, default=8, help="まとめて予約する数")
    ap.add_argument("--enc", default="-preset p4 -cq 20", help="NVENC の option")
    ap.add_argument("--suffix", default=None,
                    help="出力名に付ける文字列 (既定は出力 fps から作る)")
    ap.add_argument("--scan-width", type=int, default=SCAN_W,
                    help="1巡目の判定に使う幅")
    ap.add_argument("--plan-only", action="store_true",
                    help="走査だけして、何 frame 生成するかを出す")
    ap.add_argument("--gpu-lock", action="store_true",
                    help="GPU を排他で使う (速度を測る時だけ)")
    ap.add_argument("--cpu", type=int, default=None,
                    help="使う core 数の上限 (既定は上限なし)")
    ap.add_argument("--低負荷", "--lowload", dest="lowload",
                    action="store_true",
                    help="CPU を絞り優先度を下げる。他の作業と同居する時に")
    args = ap.parse_args()
    if not args.input:
        ap.error("動画 file か folder を渡してください")

    try:
        args.workers, load_note = apply_load_limit(args.cpu, args.lowload)
    except ValueError as exc:
        ap.error(str(exc))
    if args.workers:
        log(f"負荷設定: {load_note}")

    files = expand(args.input, args.suffix)
    if not files:
        log("処理対象がありません")
        return 1
    many = len(files) > 1
    t0 = time.time()
    ng = []
    for i, f in enumerate(files, 1):
        if many:
            log("")
            log("=" * 60)
            log(f"【{i}/{len(files)}】{f.name}")
        try:
            process(f, args)
        except Exception:
            ng.append(f.name)
            log(f"失敗: {f.name}")
            log(traceback.format_exc())
    if many:
        log("")
        log(f"{len(files)}本中 {len(files) - len(ng)}本 完了  "
            f"合計 {fmt_time(time.time() - t0)}")
    for name in ng:
        log(f"  失敗: {name}")
    return 1 if ng else 0


if __name__ == "__main__":
    sys.exit(main())
