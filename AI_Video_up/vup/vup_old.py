"""
vup - 動画AI高画質化 (計算量削減版)

現行方式との違い:
  - 中間JPEGを作らない (decode -> GPU -> encode を pipe で直結)
  - frame重複を検出し、同一frameはSRを1回だけ実行して結果を再利用
  - 出力に使われないsource frameはSR自体を行わない
  - 出力fpsをsourceのPTSから正しく決める (現行はr_frame_rateを誤用してVFR素材で破綻)
"""
import argparse
import json
import queue
import subprocess
import sys
import threading
import time
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import torch.nn.functional as F  # noqa: E402  (torchはvenvに常駐)

HERE = Path(__file__).resolve().parent
STD_FPS = [(24000, 1001), (24, 1), (25, 1), (30000, 1001), (30, 1),
           (50, 1), (60000, 1001), (60, 1)]


def log(msg):
    print(msg, flush=True)


def fmt_time(sec):
    sec = int(sec)
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    if h:
        return f"{h}時間{m}分{s}秒"
    if m:
        return f"{m}分{s}秒"
    return f"{s}秒"


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_streams", "-show_format", str(path)],
        capture_output=True, text=True, encoding="utf-8", check=True).stdout
    data = json.loads(out)
    v = next(s for s in data["streams"] if s["codec_type"] == "video")
    a = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    return v, a, data["format"]


def read_pts(path):
    """video streamの全frameのPTS(秒)。VFR素材の時刻軸を正確に扱うため必須。"""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "frame=best_effort_timestamp_time",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True).stdout
    pts = []
    for line in out.splitlines():
        tok = line.split(",")[0].strip()
        if not tok or tok == "N/A":
            continue
        pts.append(float(tok))
    pts.sort()
    return np.asarray(pts, dtype=np.float64)


def pick_output_fps(pts, mode):
    """source PTSの実測間隔から出力CFRを決める。"""
    d = np.diff(pts)
    d = d[d > 0]
    if len(d) == 0:
        return 30000, 1001
    rates = Counter(round(1.0 / x, 2) for x in d)
    target = rates.most_common(1)[0][0] if mode == "dominant" else max(rates)
    best = min(STD_FPS, key=lambda nd: abs(nd[0] / nd[1] - target))
    if abs(best[0] / best[1] - target) / target > 0.02:
        return int(round(target * 1000)), 1000
    return best


def build_schedule(pts, fps_num, fps_den, duration):
    """出力frame k (時刻 k*den/num) に表示すべきsource frame indexの配列。"""
    n_out = int(np.floor(duration * fps_num / fps_den + 1e-6))
    t = np.arange(n_out, dtype=np.float64) * fps_den / fps_num
    idx = np.searchsorted(pts, t, side="right") - 1
    np.clip(idx, 0, len(pts) - 1, out=idx)
    return idx


class TorchSR:
    """model を fp16 + channels_last で動かす。

    出力倍率がmodel倍率と違う場合の縮小もGPU側で行う。CPUへ戻す画素数が減り、
    かつ上流のncnn実装(x2/x3はx4netの後段Interp)と同じ構造になる。
    """

    def __init__(self, weights, device="cuda", half=True, out_scale=None,
                 compile_model=True):
        import torch
        sys.path.insert(0, str(HERE))
        from models_registry import load_model
        torch.backends.cudnn.benchmark = True
        self.torch = torch
        self.model, self.scale, self.arch = load_model(weights, device=device,
                                                       half=half)
        self.name = f"{self.arch} x{self.scale}"
        self.model = self.model.to(memory_format=torch.channels_last)
        self.compiled = False
        if compile_model:
            try:
                import triton  # noqa: F401  (torch.compileのGPU backend)
                self.model = torch.compile(self.model)
                self.compiled = True
            except Exception as exc:
                log(f"  torch.compileは使いません ({type(exc).__name__})")
        self.device = device
        self.dtype = torch.half if half else torch.float32
        self.out_scale = out_scale or self.scale
        self.ratio = self.out_scale / self.scale
        # 整数分の1の縮小はavg_pool2dで済む(box filter)。実測でbicubicの1/6の時間
        exact_down = (self.out_scale < self.scale
                      and self.scale % self.out_scale == 0)
        self.down = self.scale // self.out_scale if exact_down else 1
        self._pin = None

    def __call__(self, bgr):
        torch = self.torch
        with torch.no_grad():
            x = torch.from_numpy(bgr).to(self.device, non_blocking=True)
            x = x.permute(2, 0, 1).unsqueeze(0).to(self.dtype).div_(255.0)
            x = x.contiguous(memory_format=torch.channels_last)
            y = self.model(x).clamp_(0, 1)
            if self.down > 1:
                y = F.avg_pool2d(y, self.down)
            elif self.ratio != 1.0:
                y = F.interpolate(y.float(), scale_factor=self.ratio,
                                  mode="bicubic", align_corners=False,
                                  antialias=self.ratio < 1.0).clamp_(0, 1)
            y = y.mul_(255.0).round_().to(torch.uint8)
            y = y.squeeze(0).permute(1, 2, 0).contiguous()
            if self._pin is None or self._pin.shape != y.shape:
                self._pin = torch.empty(y.shape, dtype=torch.uint8,
                                        device="cpu", pin_memory=True)
            self._pin.copy_(y, non_blocking=False)
            return self._pin.numpy().copy()


class TileDiffBackend:
    """SRを、前frameから変化した領域だけに絞る。

    この素材では実測で全画面SRより遅くなったため既定OFF。詳細はREADME。
    """

    def __init__(self, base, core, halo, thresh):
        from tilediff import TileDiff
        self.base = base
        self.scale = base.scale
        self.out_scale = base.out_scale
        self.runner = TileDiff(base.model, base.scale, core=core,
                               halo=(halo if halo > 0 else None),
                               thresh=thresh, out_scale=base.out_scale,
                               dtype=base.dtype)
        self.name = f"{base.name}+tile差分(halo {self.runner.halo}px)"
        if self.runner.halo * 2 >= core:
            raise SystemExit(
                f"このmodelは受容野が広く(半径{self.runner.halo - 4}px)、"
                f"core {core}px のtile差分は成立しません。"
                f"--tile-core を大きくするか --tile-diff を外してください。")

    def __call__(self, bgr):
        return self.runner(bgr)


def make_backend(args, out_scale=None):
    from models_registry import resolve
    weights = resolve(args.model)
    # tile差分はtileごとに入力形状が変わり、torch.compileが毎回再compileする
    base = TorchSR(weights, half=not args.fp32, out_scale=out_scale,
                   compile_model=not args.no_compile and not args.tile_diff)
    if args.tile_diff:
        return TileDiffBackend(base, args.tile_core, args.tile_halo, args.tile_thresh)
    return base


class Dedup:
    """前回SRしたframeと十分近ければ、SRを省いて前回の結果を使い回す。

    比較相手は「直前のframe」ではなく「最後に実際にSRしたframe」に固定する。
    直前と比べると、閾値未満の差が毎frame見逃されて累積し、使い回した絵が
    元の絵から少しずつ離れていく。

    判定は 3ch absdiff -> threshold -> countNonZero (実測1.0ms/frame)。
    max(axis=2)で画素単位に畳むと12.5ms/frame掛かり、削っただけのSRより高くつく。
    数えるのは画素ではなくchannel値なので、同じ動きでも最大3倍の数になる。

    実測(先頭5分から60秒・1800 frame)の削減率とPSNR最小値:
      strict     厳密一致                       1.25倍  PSNR∞
      balanced   |diff|>4 のchannel値が0.15%未満  1.50倍  PSNR 52.1dB
      aggressive |diff|>12 のchannel値が1.2%未満  2.10倍  PSNR 29.7dB (動きの取りこぼしあり)
    """

    MODES = {"strict": (0, 0.0),
             "balanced": (4, 0.0015),
             "aggressive": (12, 0.012)}

    def __init__(self, mode):
        self.thresh, self.ratio = self.MODES[mode]
        self.ref = None
        self.limit = None

    def same(self, frame):
        if self.ref is None:
            return False
        if self.thresh == 0:
            return np.array_equal(self.ref, frame)
        if self.limit is None:
            self.limit = self.ratio * frame.shape[0] * frame.shape[1] * 3
        d = cv2.absdiff(frame, self.ref)
        nz = cv2.countNonZero(
            cv2.threshold(d.reshape(frame.shape[0], -1), self.thresh,
                          255, cv2.THRESH_BINARY)[1])
        return nz <= self.limit

    def mark(self, frame):
        self.ref = frame.copy()


def process(src, args):
    import cv2  # noqa: F401  (Dedupが使う)
    t_start = time.time()
    v, a, fmt = probe(src)
    w, h = int(v["width"]), int(v["height"])
    duration = float(fmt.get("duration") or v.get("duration") or 0)

    log(f"入力: {src.name}  {w}x{h}  {fmt_time(duration)}")
    log("PTS読み取り中...")
    pts = read_pts(src)
    if len(pts) == 0:
        raise RuntimeError("video frameのPTSを取得できませんでした")
    duration = max(duration, float(pts[-1]))
    if args.limit:
        keep = pts <= args.limit
        pts = pts[keep]
        duration = min(duration, args.limit)

    if args.fps:
        if "/" in args.fps:
            num, den = (int(x) for x in args.fps.split("/"))
        else:
            num, den = int(round(float(args.fps) * 1000)), 1000
    else:
        num, den = pick_output_fps(pts, args.fps_mode)
    sched = build_schedule(pts, num, den, duration)
    counts = np.bincount(sched, minlength=len(pts))

    n_src, n_out = len(pts), len(sched)
    n_used = int((counts > 0).sum())
    log(f"source frame: {n_src}  出力fps: {num}/{den} ({num/den:.3f})  出力frame: {n_out}")
    log(f"  出力に使うsource frame: {n_used} ({n_used / n_src * 100:.1f}%)"
        f"  → {n_src - n_used}枚はSR不要")

    probe_backend_scale = args.scale
    backend = make_backend(args, out_scale=probe_backend_scale)
    scale = backend.out_scale
    fw, fh = w * scale, h * scale
    tail = "" if scale == backend.scale else f" (model x{backend.scale}をGPUで縮小)"
    compiled = getattr(backend, "compiled", getattr(backend.base, "compiled", False)
                       if hasattr(backend, "base") else False)
    log(f"backend: {backend.name}{'+compile' if compiled else ''}"
        f"  出力: {fw}x{fh}{tail}")

    dec = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(src), "-f", "rawvideo",
         "-pix_fmt", "bgr24", "-"],
        stdout=subprocess.PIPE, bufsize=w * h * 3 * 8)

    out_path = src.with_name(src.stem + args.suffix + ".mp4")
    enc_cmd = ["ffmpeg", "-v", "error", "-y",
               "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{fw}x{fh}",
               "-r", f"{num}/{den}", "-i", "-"]
    if a is not None:
        enc_cmd += ["-i", str(src), "-map", "0:v", "-map", "1:a:0",
                    "-c:a", "aac", "-b:a", "192k", "-shortest"]
    enc_cmd += ["-c:v", args.encoder] + args.encoder_args.split()
    enc_cmd += ["-pix_fmt", "yuv420p", str(out_path)]
    enc = subprocess.Popen(enc_cmd, stdin=subprocess.PIPE)

    # decodeの読み取りもthreadへ回す。逐次readだとSRの間pipeが空回りする
    readq = queue.Queue(maxsize=8)

    def reader():
        pool = [np.empty((h, w, 3), np.uint8) for _ in range(12)]
        k = 0
        while True:
            frame = pool[k % len(pool)]
            k += 1
            got = dec.stdout.readinto(memoryview(frame.reshape(-1)))
            if not got or got < w * h * 3:
                break
            readq.put(frame)
        readq.put(None)

    rt = threading.Thread(target=reader, daemon=True)
    rt.start()

    writeq = queue.Queue(maxsize=8)
    write_err = []

    def writer():
        try:
            while True:
                item = writeq.get()
                if item is None:
                    break
                arr, n = item
                for _ in range(n):
                    enc.stdin.write(arr)
        except Exception as exc:  # encoderが落ちた場合
            write_err.append(exc)

    wt = threading.Thread(target=writer, daemon=True)
    wt.start()

    nbytes = w * h * 3
    dedup = Dedup(args.dedup)
    prev_out = None
    sr_calls = 0
    written = 0
    t_sr = 0.0
    t_read = t_dedup = t_put = 0.0
    last_report = time.time()

    try:
        for i in range(n_src):
            _t = time.time()
            frame = readq.get()
            t_read += time.time() - _t
            if frame is None:
                log(f"警告: decodeが{i}frameで終了しました (想定{n_src})")
                break
            rep = int(counts[i])
            if rep == 0:
                continue
            _t = time.time()
            _same = dedup.same(frame)
            t_dedup += time.time() - _t
            if not _same:
                t0 = time.time()
                prev_out = backend(frame)
                t_sr += time.time() - t0
                sr_calls += 1
                dedup.mark(frame)
            _t = time.time()
            writeq.put((prev_out, rep))
            t_put += time.time() - _t
            written += rep

            if time.time() - last_report > 5.0:
                el = time.time() - t_start
                pct = written / n_out * 100
                eta = el / max(pct, 1e-6) * (100 - pct)
                log(f"  {pct:5.1f}%  出力{written}/{n_out}  SR実行{sr_calls}回"
                    f" (削減{(i + 1) / max(sr_calls, 1):.2f}倍)"
                    f"  経過{fmt_time(el)} 残り{fmt_time(eta)}")
                last_report = time.time()
    finally:
        try:
            dec.terminate()
        except Exception:
            pass
        while True:
            try:
                if readq.get_nowait() is None:
                    break
            except queue.Empty:
                break
        writeq.put(None)
        wt.join()
        try:
            enc.stdin.close()
        except Exception:
            pass
        enc.wait()
        try:
            dec.terminate()
        except Exception:
            pass
        dec.stdout.close()
        dec.wait()
        if write_err:
            raise write_err[0]

    el = time.time() - t_start
    log("")
    log(f"完了: {out_path.name}")
    log(f"  SR実行 {sr_calls}回 / source {n_src}枚"
        f" → 計算量 {n_src / max(sr_calls, 1):.2f}倍削減")
    log(f"  SR実時間 {fmt_time(t_sr)} ({sr_calls / max(t_sr, 1e-6):.1f} fps)"
        f"  総時間 {fmt_time(el)}")
    log(f"  内訳/source frame: 読取 {t_read/n_src*1000:.2f}ms  判定 {t_dedup/n_src*1000:.2f}ms"
        f"  SR {t_sr/n_src*1000:.2f}ms  書込待ち {t_put/n_src*1000:.2f}ms")
    if hasattr(backend, "runner"):
        r = backend.runner
        log(f"  {r.report()}"
            f"  実効計算量比 {r.stat_px / max(r.stat_frames, 1) / (w * h):.3f}")
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", nargs="?")
    ap.add_argument("--model", default="sd",
                    help="model名または .pth path。--list で一覧")
    ap.add_argument("--scale", type=int, default=None,
                    help="最終倍率(model倍率と違えば縮小)")
    ap.add_argument("--fps", default=None, help="出力fps (例 24000/1001)")
    ap.add_argument("--fps-mode", default="max", choices=["max", "dominant"],
                    help="VFR素材の出力fps決定則。max=frameを落とさない")
    ap.add_argument("--encoder", default="hevc_nvenc")
    ap.add_argument("--encoder-args", default="-preset p5 -cq 24")
    ap.add_argument("--suffix", default="_up")
    ap.add_argument("--fp32", action="store_true")
    ap.add_argument("--no-compile", action="store_true",
                    help="torch.compileを使わない(初回に約10秒掛かる代わりに1.6倍速い)")
    ap.add_argument("--dedup", default="balanced",
                    choices=["strict", "balanced", "aggressive"],
                    help="frameの使い回し判定。strictは厳密一致のみ")
    ap.add_argument("--tile-diff", action="store_true",
                    help="変化した領域だけSRする(素材によっては全画面より遅い)")
    ap.add_argument("--tile-core", type=int, default=120)
    ap.add_argument("--tile-halo", type=int, default=0,
                    help="受容野分の余白。0なら起動時に実測して自動設定")
    ap.add_argument("--tile-thresh", type=int, default=6)
    ap.add_argument("--limit", type=float, default=0,
                    help="先頭N秒だけ処理(検証用)")
    ap.add_argument("--list", action="store_true", help="使えるmodelを一覧表示")
    args = ap.parse_args()
    if args.list or not args.input:
        from models_registry import describe
        log("使える model:")
        log(describe())
        return

    src = Path(args.input)
    if not src.exists():
        log(f"エラー: 見つかりません {src}")
        sys.exit(1)
    process(src, args)


if __name__ == "__main__":
    main()
