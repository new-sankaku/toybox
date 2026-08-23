"""
vup_exp - 実験版。vup.py に2点だけ変えたもの
  1. decode に -fps_mode passthrough (VFR の CFR 複製展開を止める)
  2. dedup に box4 判定 (box12 / box16 / box20) を追加


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
    """video streamの全frameのPTS(秒)。VFR素材の時刻軸を正確に扱うため必須。

    packet走査で引く。frame走査はvideoを全decodeするため16分の素材で16.6秒掛かるが、
    packet走査は0.25秒で、B-frame素材でもsort後の値は完全一致する(実測)。
    """
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "packet=pts_time",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True).stdout
    pts = []
    for line in out.splitlines():
        tok = line.split(",")[0].strip()
        if not tok or tok == "N/A":
            continue
        pts.append(float(tok))
    pts.sort()
    pts = np.asarray(pts, dtype=np.float64)
    # mp4 の edit list で切り落とされる前置きを外す。
    # packet の pts は media 時刻なので edit list を反映しないが、
    # decoder が吐く frame は反映済みで、そのままだと表示時刻がずれる。
    # (`-ss ... -c copy` で切った file は必ずこれになる)
    n0 = len(pts)
    pts = pts[pts >= -1e-9]
    if len(pts) != n0:
        log(f"  edit list により先頭 {n0 - len(pts)} 枚は表示されません")
    if len(pts):
        pts = pts - pts[0]
    return pts


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
        self.raw_model = self.model
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
        self.nv12 = False

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

    def _to_nv12(self, bgr01):
        """BGR float[0,1] (1,3,H,W) -> NV12 uint8 (H*3/2, W)。

        出力pipeの帯域が bgr24 の半分になり、nvenc は nv12 が native なので
        ffmpeg側の変換も消える。係数は BT.601 limited range。
        ffmpeg swscale の bgr24->yuv420p と Y/UV とも最大誤差1で一致する
        (fp16の丸め 1/255 より小さい)ことを実測で確認済み。
        """
        torch = self.torch
        b, g, r = bgr01[:, 0:1], bgr01[:, 1:2], bgr01[:, 2:3]
        y = 0.299 * r + 0.587 * g + 0.114 * b
        u = (b - y) * (0.5 / (1 - 0.114))
        v = (r - y) * (0.5 / (1 - 0.299))
        y = y.mul_(219.0).add_(16.0)
        u = F.avg_pool2d(u, 2).mul_(224.0).add_(128.0)
        v = F.avg_pool2d(v, 2).mul_(224.0).add_(128.0)
        y = y.clamp_(0, 255).round_().to(torch.uint8)[0, 0]
        uv = torch.stack((u, v), dim=-1).clamp_(0, 255).round_().to(torch.uint8)
        uv = uv.reshape(uv.shape[2], -1)
        return torch.cat((y, uv), dim=0)

    def run_into(self, src_pin, dst_pin):
        """pinned入力 -> pinned出力。CPU側のmemcpyを挟まず、完了はeventで返す。"""
        torch = self.torch
        with torch.no_grad():
            x = src_pin.to(self.device, non_blocking=True)
            x = x.permute(2, 0, 1).unsqueeze(0).to(self.dtype).div_(255.0)
            x = x.contiguous(memory_format=torch.channels_last)
            y = self.model(x).clamp_(0, 1)
            if self.down > 1:
                y = F.avg_pool2d(y, self.down)
            elif self.ratio != 1.0:
                y = F.interpolate(y.float(), scale_factor=self.ratio,
                                  mode="bicubic", align_corners=False,
                                  antialias=self.ratio < 1.0).clamp_(0, 1)
            if self.nv12:
                y = self._to_nv12(y.float())
            else:
                y = y.mul_(255.0).round_().to(torch.uint8)
                y = y.squeeze(0).permute(1, 2, 0).contiguous()
            dst_pin.copy_(y, non_blocking=True)
            ev = torch.cuda.Event()
            ev.record()
            return ev


class FusedSR:
    """H2D後のuint8から出力画素形式までを1つの graph へ畳む。

    分けて書くと、前処理(permute+half+div+channels_last化)と後処理(nv12変換)が
    別々のkernelになり、1440x960の中間tensorを何度も往復する。実測で前処理0.87ms /
    nv12変換0.45msあり、model本体10.0msの13%を占めていた。
    torch.compileに丸ごと渡すとelementwiseが融合され、この分が縮む。
    """

    def __init__(self, base):
        torch = base.torch
        self.torch = torch
        self.base = base
        self.scale = base.scale
        self.out_scale = base.out_scale
        self.nv12 = base.nv12
        self.name = base.name + "+前後処理fuse"
        self.compiled = base.compiled

        def graph(u8):
            x = u8.permute(2, 0, 1).unsqueeze(0).to(base.dtype).div_(255.0)
            x = x.contiguous(memory_format=torch.channels_last)
            y = base.raw_model(x).clamp_(0, 1)
            if base.down > 1:
                y = F.avg_pool2d(y, base.down)
            elif base.ratio != 1.0:
                y = F.interpolate(y.float(), scale_factor=base.ratio,
                                  mode="bicubic", align_corners=False,
                                  antialias=base.ratio < 1.0).clamp_(0, 1)
            if self.nv12:
                return base._to_nv12(y.float())
            y = y.mul_(255.0).round_().to(torch.uint8)
            return y.squeeze(0).permute(1, 2, 0).contiguous()

        self.graph = torch.compile(graph) if base.compiled else graph

    def run_into(self, src_pin, dst_pin):
        torch = self.torch
        with torch.no_grad():
            y = self.graph(src_pin.to(self.base.device, non_blocking=True))
            dst_pin.copy_(y, non_blocking=True)
            ev = torch.cuda.Event()
            ev.record()
            return ev


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

    def run_into(self, src_pin, dst_pin):
        """SR threadはこの形式で呼ぶ。tile差分はtile単位で判定と入出力を組むため
        pinned直結にはできず、numpyを経由する。"""
        import torch
        dst_pin.numpy()[:] = self.runner(src_pin.numpy())
        ev = torch.cuda.Event()
        ev.record()
        return ev


# torch.compile は約4.5秒掛かり、1 frameあたり約4ms速くなる(実測)。
# 短い素材では元が取れないので、SR回数の見積りで自動判定する。
COMPILE_SETUP_SEC = 4.5
COMPILE_GAIN_MS = 4.0


def make_backend(args, out_scale=None, est_calls=None):
    from models_registry import resolve
    weights = resolve(args.model)
    mode = "off" if args.no_compile else args.compile
    want = mode != "off" and not args.tile_diff
    if want and est_calls is not None and mode == "auto":
        if est_calls * COMPILE_GAIN_MS / 1000.0 < COMPILE_SETUP_SEC:
            log(f"  torch.compileは使いません (SR見積り{est_calls}回では"
                f"compile時間{COMPILE_SETUP_SEC:.1f}秒の元が取れません)")
            want = False
    # tile差分はtileごとに入力形状が変わり、torch.compileが毎回再compileする
    base = TorchSR(weights, half=not args.fp32, out_scale=out_scale,
                   compile_model=want)
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
             "aggressive": (12, 0.012),
             "box12": (-4, 12.0),
             "box16": (-4, 16.0),
             "box20": (-4, 20.0)}

    def __init__(self, mode):
        self.thresh, self.ratio = self.MODES[mode]
        self.ref = None
        self.limit = None
        self.small = None

    def same(self, frame):
        if self.ref is None:
            return False
        if self.thresh < 0:
            # blk x blk の平均|d| の最大。encode noise は面で薄く乗るので
            # 平均で潰れ、瞬きや口のような局所的で濃い変化だけが残る。
            blk = -self.thresh
            if self.small is None:
                self.small = (frame.shape[1] // blk, frame.shape[0] // blk)
            d = cv2.absdiff(frame, self.ref)
            return int(cv2.resize(d, self.small,
                                  interpolation=cv2.INTER_AREA).max()) < self.ratio
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
    phase = {}
    v, a, fmt = probe(src)
    w, h = int(v["width"]), int(v["height"])
    duration = float(fmt.get("duration") or v.get("duration") or 0)

    log(f"入力: {src.name}  {w}x{h}  {fmt_time(duration)}")
    log("PTS読み取り中...")
    _t = time.time()
    pts = read_pts(src)
    phase["PTS読み"] = time.time() - _t
    if len(pts) == 0:
        raise RuntimeError("video frameのPTSを取得できませんでした")
    duration = max(duration, float(pts[-1]))
    nb = v.get("nb_frames")
    if nb and nb != "N/A" and abs(int(nb) - len(pts)) > 1:
        log(f"警告: packet数{len(pts)}とframe数{nb}が食い違います。"
            f"時刻軸がずれる恐れがあります")
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
    _t = time.time()
    # dedupで実際に減る分は素材依存なので、見積りは控えめに使用frame数そのままとする
    backend = make_backend(args, out_scale=probe_backend_scale, est_calls=n_used)
    phase["model読込"] = time.time() - _t
    scale = backend.out_scale
    fw, fh = w * scale, h * scale
    tail = "" if scale == backend.scale else f" (model x{backend.scale}をGPUで縮小)"
    dec = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(src), "-fps_mode", "passthrough",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
        stdout=subprocess.PIPE, bufsize=w * h * 3 * 8)

    out_path = src.with_name(src.stem + args.suffix + ".mp4")
    # 出力pipeの画素形式。nv12は bgr24 の半分の帯域で、nvencのnative形式なので
    # ffmpeg側の色変換も消える。GPU側の変換はswscaleと最大誤差1で一致する。
    use_nv12 = args.out_pix == "nv12"
    if use_nv12:
        if not hasattr(backend, "nv12"):
            raise SystemExit("--out-pix nv12 は tile差分と併用できません。"
                             "--out-pix bgr24 を付けてください")
        backend.nv12 = True
        out_shape = (fh * 3 // 2, fw)
    else:
        out_shape = (fh, fw, 3)
    if args.fuse and isinstance(backend, TorchSR):
        backend = FusedSR(backend)
    compiled = getattr(backend, "compiled", getattr(backend.base, "compiled", False)
                       if hasattr(backend, "base") else False)
    log(f"backend: {backend.name}{'+compile' if compiled else ''}"
        f"  出力: {fw}x{fh}{tail}  pipe: {args.out_pix}")

    enc_cmd = ["ffmpeg", "-v", "error", "-y",
               "-f", "rawvideo", "-pix_fmt", args.out_pix, "-s", f"{fw}x{fh}",
               "-r", f"{num}/{den}", "-i", "-"]
    if a is not None:
        enc_cmd += ["-i", str(src), "-map", "0:v", "-map", "1:a:0",
                    "-c:a", "aac", "-b:a", "192k", "-shortest"]
    enc_cmd += ["-c:v", args.encoder] + args.encoder_args.split()
    enc_cmd += ["-pix_fmt", "yuv420p", str(out_path)]
    enc = subprocess.Popen(enc_cmd, stdin=subprocess.PIPE)

    import torch as _torch
    # decodeの読み取りもthreadへ回す。逐次readだとSRの間pipeが空回りする
    # 入力はpinned memoryへ受ける。SR threadでのH2Dが非同期になる
    readq = queue.Queue(maxsize=8)
    NPOOL = 40

    def reader():
        pool = [_torch.empty((h, w, 3), dtype=_torch.uint8, pin_memory=True)
                for _ in range(NPOOL)]
        views = [q.numpy() for q in pool]
        k = 0
        while True:
            j = k % NPOOL
            k += 1
            got = dec.stdout.readinto(memoryview(views[j].reshape(-1)))
            if not got or got < w * h * 3:
                break
            readq.put((pool[j], views[j]))
        readq.put(None)

    rt = threading.Thread(target=reader, daemon=True)
    rt.start()

    # 出力pinned bufferをpoolで回す。numpy().copy() の 4.1MB memcpy を消す
    NOUT = 6
    freeq = queue.Queue()
    for _ in range(NOUT):
        _b = _torch.empty(out_shape, dtype=_torch.uint8, pin_memory=True)
        freeq.put((_b, _b.numpy()))

    writeq = queue.Queue(maxsize=NOUT)
    write_err = []
    w_stat = {"t_get": 0.0, "t_write": 0.0, "frames": 0, "bytes": 0}

    def writer():
        try:
            while True:
                _t = time.time()
                item = writeq.get()
                w_stat["t_get"] += time.time() - _t
                if item is None:
                    break
                buf, arr, n = item
                _t = time.time()
                for _ in range(n):
                    enc.stdin.write(arr)
                w_stat["t_write"] += time.time() - _t
                w_stat["frames"] += n
                w_stat["bytes"] += n * arr.nbytes
                freeq.put((buf, arr))
        except Exception as exc:  # encoderが落ちた場合
            write_err.append(exc)

    wt = threading.Thread(target=writer, daemon=True)
    wt.start()

    # SRを専用threadへ。判定・読取・書込putがGPU時間と重なる。
    # さらにeventで深さ2の投入しっぱなしにし、kernel投入待ちをGPU時間へ隠す。
    srq = queue.Queue(maxsize=4)
    sr_stat = {"calls": 0, "t_sr": 0.0, "t_wait": 0.0, "t_free": 0.0}
    sr_err = []

    gpu_prof = [] if args.gpu_prof else None

    def sr_worker():
        inflight = []   # [buf, arr, rep, event] 投入順
        DEPTH = 2

        def flush(keep):
            while len(inflight) > keep:
                buf, arr, rp, ev = inflight.pop(0)
                ev.synchronize()
                writeq.put((buf, arr, rp))

        try:
            while True:
                _t = time.time()
                item = srq.get()
                sr_stat["t_wait"] += time.time() - _t
                if item is None:
                    break
                src_pin, rp, is_new = item
                if not is_new:
                    # 使い回しは投入中の直近SR結果の枚数を足すだけ。順序は保たれる
                    inflight[-1][2] += rp
                    continue
                flush(DEPTH - 1)
                _t = time.time()
                buf, arr = freeq.get()
                sr_stat["t_free"] += time.time() - _t
                t0 = time.time()
                if gpu_prof is not None:
                    e0 = _torch.cuda.Event(enable_timing=True)
                    e0.record()
                ev = backend.run_into(src_pin, buf)
                if gpu_prof is not None:
                    e1 = _torch.cuda.Event(enable_timing=True)
                    e1.record()
                    gpu_prof.append((e0, e1))
                sr_stat["t_sr"] += time.time() - t0
                sr_stat["calls"] += 1
                inflight.append([buf, arr, rp, ev])
            flush(0)
        except Exception as exc:
            sr_err.append(exc)
        writeq.put(None)

    st = threading.Thread(target=sr_worker, daemon=True)
    st.start()

    _t = time.time()
    _warm_src = _torch.empty((h, w, 3), dtype=_torch.uint8, pin_memory=True)
    _warm_dst = _torch.empty(out_shape, dtype=_torch.uint8, pin_memory=True)
    for _ in range(3):
        backend.run_into(_warm_src, _warm_dst)
    _torch.cuda.synchronize()
    del _warm_src, _warm_dst
    phase["compile/warmup"] = time.time() - _t

    if args.gpu_prof:
        # 同一process・同一時刻でのSR単体性能。pipeline構造の損失を切り分ける
        _sp = _torch.empty((h, w, 3), dtype=_torch.uint8, pin_memory=True)
        _dp = _torch.empty(out_shape, dtype=_torch.uint8, pin_memory=True)
        for _ in range(10):
            backend.run_into(_sp, _dp)
        _torch.cuda.synchronize()
        _t = time.time()
        for _ in range(60):
            backend.run_into(_sp, _dp)
        _torch.cuda.synchronize()
        _ms = (time.time() - _t) / 60 * 1000
        log(f"  SR単体(同一process): {_ms:.2f}ms → {1000/_ms:.1f} fps")
        del _sp, _dp

    nbytes = w * h * 3
    t_ready = time.time()
    dedup = Dedup(args.dedup)
    sr_calls = 0
    written = 0
    t_sr = 0.0
    t_read = t_dedup = t_put = 0.0
    last_report = time.time()

    try:
        for i in range(n_src):
            _t = time.time()
            got = readq.get()
            t_read += time.time() - _t
            if got is None:
                log(f"警告: decodeが{i}frameで終了しました (想定{n_src})")
                break
            src_pin, frame = got
            rep = int(counts[i])
            if rep == 0:
                continue
            _t = time.time()
            _same = dedup.same(frame)
            t_dedup += time.time() - _t
            if not _same:
                dedup.mark(frame)
                sr_calls += 1
            _t = time.time()
            srq.put((src_pin, rep, not _same))
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
        srq.put(None)
        st.join()
        t_sr = sr_stat["t_sr"]
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
        if sr_err:
            raise sr_err[0]
        if write_err:
            raise write_err[0]

    el = time.time() - t_start
    el_proc = time.time() - t_ready
    log("")
    log(f"完了: {out_path.name}")
    log(f"  SR実行 {sr_calls}回 / source {n_src}枚"
        f" → 計算量 {n_src / max(sr_calls, 1):.2f}倍削減")
    log(f"  総時間 {fmt_time(el)}  実効 {n_out / max(el, 1e-6):.1f} fps(出力frame)")
    _ph = "  ".join(f"{k} {v:.1f}s" for k, v in phase.items())
    log(f"  内 起動 {el - el_proc:.1f}s ({_ph}  他 "
        f"{el - el_proc - sum(phase.values()):.1f}s)"
        f"  処理 {el_proc:.1f}s = {n_out / max(el_proc, 1e-6):.1f} fps"
        f"  SR {sr_calls / max(el_proc, 1e-6):.1f} fps")
    log(f"  SR thread: 入力待ち {sr_stat['t_wait']:.2f}s"
        f"  空buffer待ち {sr_stat['t_free']:.2f}s")
    if gpu_prof:
        _torch.cuda.synchronize()
        g = sum(a.elapsed_time(b) for a, b in gpu_prof) / 1000.0
        log(f"  GPU占有(SR実処理) {g:.2f}s / 処理{el_proc:.1f}s = {g/max(el_proc,1e-9)*100:.0f}%"
            f"  1回{g/max(len(gpu_prof),1)*1000:.2f}ms → 単体{len(gpu_prof)/max(g,1e-9):.1f} fps")
    log(f"  writer thread: 入力待ち {w_stat['t_get']:.2f}s"
        f"  pipe書込 {w_stat['t_write']:.2f}s"
        f"  ({w_stat['bytes'] / 1e9:.2f}GB / "
        f"{w_stat['bytes'] / 1e6 / max(w_stat['t_write'], 1e-9):.0f} MB/s)")
    # SRは別threadで非同期に投入するため、main側の時間は「投入」の時間でしかない。
    # 実効速度は総時間で見る。
    log(f"  main thread/source frame: 読取待ち {t_read/n_src*1000:.2f}ms"
        f"  使い回し判定 {t_dedup/n_src*1000:.2f}ms  SR投入 {t_sr/n_src*1000:.2f}ms"
        f"  書込put {t_put/n_src*1000:.2f}ms")
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
    ap.add_argument("--out-pix", default="nv12", choices=["nv12", "bgr24"],
                    help="出力pipeの画素形式。nv12は帯域半分でnvencのnative形式")
    ap.add_argument("--encoder-args", default="-preset p7 -cq 24")
    ap.add_argument("--suffix", default="_up")
    ap.add_argument("--fp32", action="store_true")
    ap.add_argument("--no-compile", action="store_true",
                    help="torch.compileを使わない")
    ap.add_argument("--compile", default="auto", choices=["auto", "on", "off"],
                    help="torch.compileの使用。autoは素材の長さで判断する")
    ap.add_argument("--dedup", default="balanced",
                    choices=["strict", "balanced", "aggressive",
                             "box12", "box16", "box20"],
                    help="frameの使い回し判定。strictは厳密一致のみ")
    ap.add_argument("--tile-diff", action="store_true",
                    help="変化した領域だけSRする(素材によっては全画面より遅い)")
    ap.add_argument("--tile-core", type=int, default=120)
    ap.add_argument("--tile-halo", type=int, default=0,
                    help="受容野分の余白。0なら起動時に実測して自動設定")
    ap.add_argument("--tile-thresh", type=int, default=6)
    ap.add_argument("--no-fuse", dest="fuse", action="store_false",
                    help="前後処理をcompile graphへ畳まない")
    ap.add_argument("--gpu-prof", action="store_true",
                    help="SRのGPU占有時間をCUDA eventで測る(検証用)")
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
