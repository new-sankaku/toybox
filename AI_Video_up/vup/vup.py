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
import shutil
import threading
import time
import traceback
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import torch.nn.functional as F  # noqa: E402  (torchはvenvに常駐)

HERE = Path(__file__).resolve().parent
VIDEO_EXT = {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".flv", ".webm", ".m4v",
             ".mpg", ".mpeg", ".ts", ".m2ts"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
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


def _probe_units(path, entry):
    """`-show_entries <section>=<field>` を整数listで返す。欠測数も返す。"""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", entry, "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True).stdout
    units, missing = [], 0
    for line in out.splitlines():
        tok = line.split(",")[0].strip()
        if not tok or tok == "N/A":
            missing += 1
            continue
        units.append(int(tok))
    return units, missing


def _probe_frame_pts(path):
    """frame走査でPTSを引く。時刻が無いframeはdurationから復元する。

    AVIのMPEG-4 packed bitstreamは末尾のframeがpacketに紐付かず、
    best_effort_timestamp が N/A で出る(実測: 5813 frame中の最後の1枚)。
    このframeもdecoderは出すので、捨てるとi番目に別の時刻が付く。
    durationは容器が全frameに書いているので直前の時刻へ足して埋める。
    """
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "frame=best_effort_timestamp,duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True).stdout
    units, missing = [], 0
    prev_ts = prev_dur = None
    for line in out.splitlines():
        cols = [c.strip() for c in line.split(",")]
        ts = cols[0] if cols else ""
        dur = cols[1] if len(cols) > 1 else ""
        if ts and ts != "N/A":
            cur = int(ts)
        elif prev_ts is not None and prev_dur is not None:
            cur = prev_ts + prev_dur
        else:
            missing += 1
            continue
        units.append(cur)
        prev_ts = cur
        if dur and dur != "N/A":
            prev_dur = int(dur)
    return units, missing


def read_pts(path, time_base, start_pts=None):
    """decoderが実際に出すframeのPTS(秒)を、出る順に返す。

    packet走査で引く。frame走査はvideoを全decodeするため16分の素材で16.6秒掛かるが、
    packet走査は0.25秒で、B-frame素材でもsort後の値は完全一致する(実測)。

    ただしpacketのPTSは容器が書いた値で、書いていない容器がある。MPEG-PSの実素材で
    3169 packet中169がN/Aだった。捨てるとdecoderが出す169枚に別の時刻を割り当てるので、
    1つでも欠けていたらframe走査へ切り替える。frame走査は best_effort_timestamp を読む
    -- decoderが補ったPTSで、同素材で欠測0・間隔29.97一定になる(packet走査は
    169箇所が14.99の穴だった)。

    stream の開始より前のpacketは decoder が捨てるので、ここでも捨てる。
    `ffmpeg -ss ... -c copy` で切ったfileは先頭GOPの前置きが負のPTSで残っており、
    実測でこのclipは packet 1567 に対し decoder が出すframeは 1462 だった
    (差の105枚がすべて負のPTS)。捨てないと i 番目のframeに別の時刻を割り当てる。

    この境目は `start_time` (秒) ではなく `start_pts` (time_base単位の整数) で切る。
    `start_time` も小数6桁の丸めで、MPEG-PSの実素材は start_pts 30607 / time_base
    1/90000 に対し start_time が 0.340078 と報告された。実値 0.34007777... より
    2.2e-9 大きく、先頭frameが自分の開始時刻より前だと判定されて捨てられていた
    (decoderは出すので、以降の全frameが1枚ずつずれる)。

    ffprobe の `pts_time` は小数6桁に丸めた値で使えない。30fpsなら 1/30 に対し
    0.033333 が返り、出力時刻との差 3.3e-7 で build_schedule が1つ前のframeを選ぶ
    (実写.mp4 で出力の96%が1 frame遅れていた)。time_base単位の整数 pts を読んで
    こちらで秒へ直す。
    """
    tb_num, tb_den = (int(x) for x in time_base.split("/"))
    units, missing = _probe_units(path, "packet=pts")
    if missing:
        log(f"packetのPTSが{missing}個欠けています。frame走査へ切り替えます")
        units, missing = _probe_frame_pts(path)
        if missing:
            raise RuntimeError(
                f"frameのPTSが{missing}個取得できませんでした: {path.name}")
    units.sort()
    if start_pts is not None:
        units = [u for u in units if u >= start_pts]
    return np.asarray(units, dtype=np.float64) * tb_num / tb_den


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


# 出力時刻とsource PTSは別々の有理数から作るので、同じ瞬間でも最後の1桁が食い違う。
# 素の大小比較だと1つ前のframeを選んでしまうため、この幅だけ余裕を持たせる。
# 240fpsのframe間隔(4.2e-3)より桁違いに小さく、絵を取り違える幅ではない。
PTS_EPS = 1e-6


def build_schedule(pts, fps_num, fps_den, duration):
    """出力frame k (時刻 k*den/num) に表示すべきsource frame indexの配列。"""
    n_out = int(np.floor(duration * fps_num / fps_den + 1e-6))
    t = np.arange(n_out, dtype=np.float64) * fps_den / fps_num
    idx = np.searchsorted(pts, t + PTS_EPS, side="right") - 1
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


class GpuPace:
    """GPUの稼働率の上限。実績が上限を超えた分だけ間を置く。

    録画のような別のGPU仕事と同居させる時に使う。1回ごとに固定で休むと、
    CPU側のdecode/encodeで既に空いている間を数えないため休み過ぎる。
    実績(SRに使った累計時間 / 経過時間)で見て、超えた時だけ待つ。

    白黒とcolorのように backend が2つ在っても上限は1つなので、
    meterはここに1個持って両方で分け合う。
    """

    def __init__(self, share):
        self.share = share
        self.busy = 0.0
        self.t0 = None

    def start(self):
        if self.t0 is None:
            self.t0 = time.time()
        return time.time()

    def done(self, t):
        self.busy += time.time() - t
        rest = self.busy * 100.0 / self.share - (time.time() - self.t0)
        if rest > 0:
            time.sleep(rest)

    def rate(self):
        if not self.t0:
            return 0.0
        return self.busy * 100.0 / max(time.time() - self.t0, 1e-9)


class PacedBackend:
    """GpuPace を通して呼ぶだけの薄い包み。"""

    def __init__(self, base, pace):
        self.base = base
        self.pace = pace
        self.name = f"{base.name} [GPU {pace.share}%まで]"

    def __getattr__(self, k):
        return getattr(self.base, k)

    def __call__(self, x):
        t = self.pace.start()
        out = self.base(x)
        self.pace.done(t)
        return out


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


# torch.compile は約4.5秒掛かり、1 SR回あたり約3.2ms速くなる(静穏環境での実測。
# 60秒の素材で処理 14.4秒 → 11.5秒、SR単体 78.0 → 114.3 fps)。
# 短い素材では元が取れないので、SR回数の見積りで自動判定する。
COMPILE_SETUP_SEC = 4.5
COMPILE_GAIN_MS = 3.2
# dedupで実際にSRが減る倍率の見積り。実測はbalancedで1.75倍だが、
# 素材によって変わるので控えめな値を使う(見積り過大でcompileを空振りさせない)。
DEDUP_EST = {"strict": 1.2, "balanced": 1.5, "aggressive": 1.8}
# COMPILE_GAIN_MS を測った時の1回あたりの画素数。得は融合できるelementwiseの量、
# つまり画素数に比例するので、これと比べて見積りを換算する。
COMPILE_REF_PX = 720 * 480


def make_backend(args, out_scale=None, est_calls=None, dedup_est=None):
    from models_registry import resolve
    weights = resolve(args.model)
    mode = "off" if args.no_compile else args.compile
    want = mode != "off" and not args.tile_diff
    if want and est_calls is not None and mode == "auto":
        est = est_calls / (DEDUP_EST[args.dedup] if dedup_est is None else dedup_est)
        if est * COMPILE_GAIN_MS / 1000.0 < COMPILE_SETUP_SEC:
            log(f"  torch.compileは使いません (SR見積り{est:.0f}回では"
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

    判定は |diff| を 4x4 の box平均へ畳んでから最大を取る。h264のencode noiseは
    面に薄く広がるので平均で潰れ、瞬きや口のような局所的で濃い変化だけが残る。
    畳まずに画素ごとの閾値と比率で見る旧方式より、削減率と取りこぼしの両方で上回る。

    全長16分34秒(出力に使う23103枚)の実測。欠落画素は使い回したframeと本来の
    frameで |d|>48 の画素数で、判定基準とは独立な指標:

      判定基準            SR回数  削減    欠落合計   欠落最大  >100画素のframe
      厳密一致            22818  1.01倍         0         0        0
      旧balanced          19134  1.21倍    43,884       494      138
      旧aggressive        15336  1.51倍 4,555,428     9,371    2,638
      box4<16(現balanced) 18559  1.24倍       146        13        0
      box4<20(現aggress.) 18070  1.28倍     3,353        70        0

    実際に動いているframeの |d|>48 画素数は p5=268・p10=680・中央9,206なので、
    box4<20 の最悪70画素は本物の動きの最小規模の1/4以下に収まる。
    旧aggressiveは瞬きや口の動きを取りこぼしていた(最悪9,371画素)。

    閾値は素材のh264 noise水準に対して選んだ値なので、別素材では
    --dedup-thresh で較正できるようにしてある。
    """

    MODES = {"strict": ("exact", 0),
             "balanced": ("box4", 16),
             "aggressive": ("box4", 20)}

    def __init__(self, mode, thresh=None):
        self.kind, self.thresh = self.MODES[mode]
        if thresh is not None:
            self.thresh = thresh
            if self.kind == "exact":
                self.kind = "box4"
        self.ref = None
        self.small = None

    def same(self, frame):
        if self.ref is None:
            return False
        if self.kind == "exact":
            return np.array_equal(self.ref, frame)
        if self.small is None:
            self.small = (frame.shape[1] // 4, frame.shape[0] // 4)
        d = cv2.absdiff(frame, self.ref)
        # INTER_AREA は整数分の1の縮小では box平均そのもの
        return int(cv2.resize(d, self.small,
                              interpolation=cv2.INTER_AREA).max()) < self.thresh

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
    _sp = v.get("start_pts")
    pts = read_pts(src, v["time_base"],
                   int(_sp) if _sp not in (None, "N/A") else None)
    phase["PTS読み"] = time.time() - _t
    if len(pts) == 0:
        raise RuntimeError("video frameのPTSを取得できませんでした")
    duration = max(duration, float(pts[-1]))
    nb = v.get("nb_frames")
    if nb and nb != "N/A" and len(pts) - int(nb) > 1:
        log(f"警告: PTS数{len(pts)}がframe数{nb}を超えています。"
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
    # -fps_mode passthrough が無いと、rawvideo muxerにtimestampが無いため
    # ffmpegが既定のcfrでVFR入力をCFRへ複製展開する(実測: 24279 packetの素材が
    # 29819 frame になる)。vup.pyは自前のscheduleで複製を掛けるので二重になり、
    # 先頭から順に読むだけの本loopでは映像が徐々に遅れ、末尾が丸ごと欠ける。
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
        slot_shape = (fh * 3 // 2, fw)
    else:
        slot_shape = (fh, fw, 3)
    # TensorRT の batch 推論では出力bufferを batch 枚ぶん持つ
    BS = args.trt_batch if args.trt else 1
    out_shape = slot_shape if BS == 1 else (BS,) + slot_shape
    if args.trt and args.tile_diff:
        raise SystemExit("--tile-diff は TensorRT と併用できません。"
                         "--no-trt を付けてください")
    if args.trt:
        from trt_backend import TrtSR
        from models_registry import resolve
        backend = TrtSR(resolve(args.model), w, h, out_scale=probe_backend_scale,
                        bs=args.trt_batch, nv12=use_nv12, log=log,
                        dynamic=args.trt_dynamic)
    elif args.fuse and isinstance(backend, TorchSR):
        backend = FusedSR(backend)
    compiled = getattr(backend, "compiled", getattr(backend.base, "compiled", False)
                       if hasattr(backend, "base") else False)
    log(f"backend: {backend.name}{'+compile' if compiled else ''}"
        f"  出力: {fw}x{fh}{tail}  pipe: {args.out_pix}")

    # 画素の縦横比(SAR)を引き継ぐ。rawvideoで渡すと失われ、anamorphic素材
    # (サンプル.mp4は SAR 853:720 / DAR 853:480)が 3:2 に潰れて出る。
    # 縦横とも同じ倍率で拡大するのでSARは変わらず、DARも原本と同じ。
    aspect = []
    sar = v.get("sample_aspect_ratio")
    if sar and sar not in ("N/A", "0:1", "1:1"):
        sn, sd = (int(x) for x in sar.split(":"))
        if sn > 0 and sd > 0:
            from math import gcd
            dn, dd = fw * sn, fh * sd
            g = gcd(dn, dd)
            aspect = ["-aspect", f"{dn // g}:{dd // g}"]

    enc_cmd = ["ffmpeg", "-v", "error", "-y",
               "-f", "rawvideo", "-pix_fmt", args.out_pix, "-s", f"{fw}x{fh}",
               "-r", f"{num}/{den}", "-i", "-"]
    if a is not None:
        enc_cmd += ["-i", str(src), "-map", "0:v", "-map", "1:a:0",
                    "-c:a", "aac", "-b:a", "192k", "-shortest"]
    enc_cmd += ["-c:v", args.encoder] + args.encoder_args.split() + aspect
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
                buf, arr, reps = item
                _t = time.time()
                if BS == 1:
                    for _ in range(reps[0]):
                        enc.stdin.write(arr)
                    n, nb = reps[0], reps[0] * arr.nbytes
                else:
                    n = nb = 0
                    for i, rp in enumerate(reps):
                        for _ in range(rp):
                            enc.stdin.write(arr[i])
                        n += rp
                        nb += rp * arr[i].nbytes
                w_stat["t_write"] += time.time() - _t
                w_stat["frames"] += n
                w_stat["bytes"] += nb
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
        """SRを投入し、完了したものから writer へ渡す。

        BS>=2 では batch が埋まるまで pending へ溜める。使い回しの枚数は
        「直近のbatch」ではなく「直近のslot」へ足す。ここを間違えると
        frameの順序が狂う。入力が尽きたら端数batchもflushする。
        """
        inflight = []   # [buf, arr, [rep,...], event] 投入順
        pending = []    # [(src_pin, rep), ...] 未投入のbatch
        DEPTH = 2

        def flush(keep):
            while len(inflight) > keep:
                buf, arr, rps, ev = inflight.pop(0)
                ev.synchronize()
                writeq.put((buf, arr, rps))

        def submit():
            flush(DEPTH - 1)
            _t = time.time()
            buf, arr = freeq.get()
            sr_stat["t_free"] += time.time() - _t
            t0 = time.time()
            if gpu_prof is not None:
                e0 = _torch.cuda.Event(enable_timing=True)
                e0.record()
            if BS == 1:
                ev = backend.run_into(pending[0][0], buf)
            else:
                ev = backend.run_batch_into([q[0] for q in pending], buf)
            if gpu_prof is not None:
                e1 = _torch.cuda.Event(enable_timing=True)
                e1.record()
                gpu_prof.append((e0, e1))
            sr_stat["t_sr"] += time.time() - t0
            sr_stat["calls"] += 1
            inflight.append([buf, arr, [q[1] for q in pending], ev])
            pending.clear()

        try:
            while True:
                _t = time.time()
                item = srq.get()
                sr_stat["t_wait"] += time.time() - _t
                if item is None:
                    break
                src_pin, rp, is_new = item
                if not is_new:
                    # 使い回しは直近のslotの枚数を足すだけ。順序は保たれる
                    if pending:
                        pending[-1] = (pending[-1][0], pending[-1][1] + rp)
                    else:
                        inflight[-1][2][-1] += rp
                    continue
                pending.append((src_pin, rp))
                if len(pending) >= BS:
                    submit()
            if pending:
                submit()
            flush(0)
        except Exception as exc:
            sr_err.append(exc)
        writeq.put(None)

    st = threading.Thread(target=sr_worker, daemon=True)
    st.start()

    def bench_sr(warm, it):
        """自前のbufferでSRを空回しする。戻り値は1 frameあたりのms。

        buffer をこの関数の中に閉じ込めるのは、pinned memory を呼び出し後に
        確実に手放すため。
        """
        src = [_torch.empty((h, w, 3), dtype=_torch.uint8, pin_memory=True)
               for _ in range(BS)]
        dst = _torch.empty(out_shape, dtype=_torch.uint8, pin_memory=True)

        def one():
            if BS == 1:
                return backend.run_into(src[0], dst)
            return backend.run_batch_into(src, dst)

        for _ in range(warm):
            one()
        _torch.cuda.synchronize()
        if it <= 0:
            return 0.0
        t0 = time.time()
        for _ in range(it):
            one()
        _torch.cuda.synchronize()
        return (time.time() - t0) / it / BS * 1000

    _t = time.time()
    bench_sr(3, 0)
    phase["compile/warmup"] = time.time() - _t

    if args.gpu_prof:
        # 同一process・同一時刻でのSR単体性能。pipeline構造の損失を切り分ける
        _ms = bench_sr(10, 60)
        log(f"  SR単体(同一process): {_ms:.2f}ms/frame → {1000 / _ms:.1f} fps")

    t_ready = time.time()
    dedup = Dedup(args.dedup, args.dedup_thresh)
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
        else:
            # n_src(=PTS数)がdecoderの出すframe数より少ないと、頭からn_src枚だけを
            # 全長へ引き延ばした別物が出る。しかも各frameは時刻を持っているので
            # 尺もfpsも正しく見え、再生するまで気付けない。実測でAVIのMPEG-4が
            # packet PTS 1056個/frame 5813枚となり、17.6秒ぶんが97秒へ伸びていた。
            # decoderに余りが残っていないかは、その場で確実に判る唯一の証拠。
            if not args.limit and readq.get() is not None:
                raise RuntimeError(
                    f"PTS数({n_src})よりdecoderが出すframeが多く、"
                    f"出力は先頭{n_src}枚を全長へ引き延ばした別物になります"
                    f" (frame数の報告値 {v.get('nb_frames')})")
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


def expand_inputs(paths, suffix):
    """dropされたpathを (処理対象, 表示名) の並びへ開く。

    directoryは下位directoryまで辿り、path順に採る。
    自分が出した物(suffix付き)を二度掛けしないよう除く。
    同じfileを2回渡されても1回だけ処理する。
    """
    targets, seen = [], set()

    def add(path, label, root=None):
        key = path.resolve()
        if key in seen:
            return
        seen.add(key)
        targets.append((path, label, root))

    for raw in paths:
        src = Path(raw)
        if not src.exists():
            log(f"エラー: 見つかりません {src}")
            sys.exit(1)
        if src.is_dir():
            found = sorted(f for f in src.rglob("*")
                           if f.is_file()
                           and f.suffix.lower() in (VIDEO_EXT | IMAGE_EXT))
            keep = [f for f in found if not f.stem.endswith(suffix)]
            nested = sum(1 for f in keep if f.parent != src)
            skipped = len(found) - len(keep)
            log(f"{src.name}: 処理対象 {len(keep)}本"
                + (f"(下位folderの{nested}本を含む)" if nested else "")
                + (f"  出力済みの{skipped}本は除外" if skipped else ""))
            for f in keep:
                add(f, str(f.relative_to(src)), src)
        elif src.stem.endswith(suffix):
            log(f"飛ばします(出力済み): {src.name}")
        elif src.suffix.lower() in (VIDEO_EXT | IMAGE_EXT):
            add(src, src.name)
        else:
            log(f"対象外: {src.name}")
    return targets


def _is_gray(bgr):
    """中身がgrayscaleか。pix_fmtでは判らない(色のまま保存されたgray頁が在る)ので画素で見る。"""
    d = np.abs(bgr.astype(np.int16) - bgr.mean(axis=2, keepdims=True)).max(axis=2)
    return float((d > 8).mean()) < 0.001


def _save_image(out_path, arr, gray, args, dpi):
    from PIL import Image
    if gray:
        # BT.601 luma。modelは3ch出力なので、そのまま出すと線に色が乗る
        y = (arr[:, :, 2] * 0.299 + arr[:, :, 1] * 0.587
             + arr[:, :, 0] * 0.114).round().clip(0, 255).astype(np.uint8)
        im = Image.fromarray(y, "L")
    else:
        im = Image.fromarray(arr[:, :, ::-1], "RGB")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    kw = {}
    if dpi:
        kw["dpi"] = dpi                      # 拡大したぶん解像度も上がる
    fmt = args.img_format.upper()
    if fmt == "WEBP":
        im.save(out_path, "WEBP", quality=args.img_quality, method=4, **kw)
    elif fmt == "JPEG":
        im.save(out_path, "JPEG", quality=args.img_quality, optimize=True, **kw)
    else:
        im.save(out_path, "PNG", compress_level=1, **kw)


def _image_out_path(src, root, args):
    """folderを落とした時は <folder>_up/ へ木構造ごと。fileなら元の隣。"""
    ext = "." + {"webp": "webp", "jpeg": "jpg", "png": "png"}[args.img_format]
    if root is None:
        return src.with_name(src.stem + args.suffix + ext)
    return root.with_name(root.name + args.suffix) / src.relative_to(root).with_suffix(ext)


def _img_est_calls(todo):
    """compile判定用のSR回数見積り。基準(720x480)何回ぶんかで返す。

    1回あたりの得は画素数に比例するので、枚数だけでは判断できない。
    先頭1枚の寸法で代表させる(Image.openはheaderしか読まない)。
    """
    from PIL import Image
    with Image.open(todo[0][0]) as im:
        px = im.size[0] * im.size[1]
    return len(todo) * px / COMPILE_REF_PX


def process_images(items, args):
    """画像はまとめて1 jobで回す。1枚ごとにbackendを作り直すと起動費用で潰れる。"""
    from concurrent.futures import ThreadPoolExecutor
    from PIL import Image
    t0 = time.time()
    todo = []
    for src, label, root in items:
        out = _image_out_path(src, root, args)
        if out.exists():
            continue
        todo.append((src, label, out))
    skipped = len(items) - len(todo)
    if skipped:
        log(f"  出力済みの{skipped}枚は飛ばします")
    if not todo:
        log("  処理する画像がありません")
        return []

    # 静止画にdedupは効かない(1枚ずつ別の絵)ので1.0を渡す。
    # 640x1280を324枚でも見積りは2.5秒で、compile時間4.5秒の元が取れない
    # (実測: 60枚が compileなし12秒 / compileあり20秒)。
    est = _img_est_calls(todo)
    pace = GpuPace(args.gpu_share) if args.gpu_share < 100 else None
    backend = make_backend(args, out_scale=args.scale, est_calls=est, dedup_est=1.0)
    if pace:
        backend = PacedBackend(backend, pace)
    log(f"backend: {backend.name}  画像 {len(todo)}枚")
    color_backend = None
    if args.img_color_model:
        import copy
        cargs = copy.copy(args)
        cargs.model = args.img_color_model
        color_backend = make_backend(cargs, out_scale=args.scale,
                                     est_calls=est, dedup_est=1.0)
        if pace:
            color_backend = PacedBackend(color_backend, pace)
        log(f"color頁用: {color_backend.name}")

    def read(job):
        src, label, out = job
        im = Image.open(src)
        dpi = im.info.get("dpi")
        arr = np.asarray(im.convert("RGB"))[:, :, ::-1].copy()   # BGRへ
        if dpi:
            sc = args.scale or backend.out_scale
            dpi = (dpi[0] * sc, dpi[1] * sc)
        return job, arr, dpi

    ng, done, n_color = [], 0, [0]
    with ThreadPoolExecutor(4) as dec, ThreadPoolExecutor(5) as enc:
        pending, writes = [], []
        it = iter(todo)
        for _ in range(6):
            job = next(it, None)
            if job is None:
                break
            pending.append(dec.submit(read, job))
        while pending:
            fut = pending.pop(0)
            job = next(it, None)
            if job is not None:
                pending.append(dec.submit(read, job))
            try:
                (src, label, out), arr, dpi = fut.result()
                gray = args.img_gray == "on" or (args.img_gray == "auto" and _is_gray(arr))
                if gray:
                    sr = backend(arr)
                elif color_backend is not None:
                    sr = color_backend(arr)
                elif not args.img_mono_model:
                    sr = backend(arr)
                else:
                    # B&W専用modelはcolor頁の色を捨てる(実測: 彩度53.3→0.6)。
                    # 黙って白黒にするより、原本をそのまま置いて気付けるようにする。
                    n_color[0] += 1
                    log(f"  color頁なので原本をそのまま置きます: {label}"
                        f" (--img-color-model で別modelを指定できます)")
                    out.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, out.with_suffix(src.suffix))
                    done += 1
                    continue
                writes.append((label, enc.submit(_save_image, out, sr, gray, args, dpi)))
            except Exception:
                lb = label if "label" in dir() else "?"
                ng.append(lb)
                log(f"  失敗: {lb}")
                log(traceback.format_exc())
            done += 1
            if done % 25 == 0 or done == len(todo):
                log(f"  {done}/{len(todo)}枚  {time.time() - t0:.0f}秒")
        for label, w in writes:
            try:
                w.result()
            except Exception:
                ng.append(label)
                log(f"  書き出し失敗: {label}")
                log(traceback.format_exc())
    if n_color[0]:
        log(f"  ※ color頁 {n_color[0]}枚は原本のまま置きました")
    tail = f"  GPU稼働率 {pace.rate():.0f}%" if pace else ""
    log(f"画像 {len(todo)}枚中 {len(todo) - len(ng)}枚 完了  "
        f"{fmt_time(time.time() - t0)}{tail}")
    return ng


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", nargs="*",
                    help="動画fileまたはdirectory。複数可")
    ap.add_argument("--model", default="sd-fast",
                    help="model名または .pth path。--list で一覧")
    ap.add_argument("--scale", type=int, default=None,
                    help="最終倍率(model倍率と違えば縮小)")
    ap.add_argument("--fps", default=None, help="出力fps (例 24000/1001)")
    ap.add_argument("--fps-mode", default="max", choices=["max", "dominant"],
                    help="VFR素材の出力fps決定則。max=frameを落とさない")
    ap.add_argument("--encoder", default="hevc_nvenc")
    ap.add_argument("--out-pix", default="nv12", choices=["nv12", "bgr24"],
                    help="出力pipeの画素形式。nv12は帯域半分でnvencのnative形式")
    # p7 は nvenc が別processのCUDA contextとしてSR kernelと時分割し、SRを待たせる。
    # SR側を何も変えずに、x2で 12.8→12.0秒、x4で 27.4→15.5秒 になる(実測)。
    # cq 24 は品質目標型なので、速いpresetは同じ品質をやや大きいfileで達成する
    # (実測 +3.5%)。
    ap.add_argument("--encoder-args", default="-preset p4 -cq 24")
    ap.add_argument("--suffix", default="_up")
    ap.add_argument("--img-format", default="webp", choices=["webp", "jpeg", "png"],
                    help="静止画の出力形式。webpは同品質でjpegの58%の容量")
    ap.add_argument("--img-quality", type=int, default=92)
    ap.add_argument("--img-gray", default="auto", choices=["auto", "on", "off"],
                    help="中身がgrayの画像を1chで書き出す(線に色が乗るのを防ぐ)")
    ap.add_argument("--gpu-share", type=int, default=100,
                    help="GPUの稼働率の上限(%%)。他の仕事(録画など)と同居させる時に"
                         "下げる。静止画のみ対応")
    ap.add_argument("--img-mono-model", action="store_true",
                    help="--model が白黒専用(漫画)である事を明示する。"
                         "color頁は色を捨てずに原本のまま置く")
    ap.add_argument("--img-color-model", default=None,
                    help="color頁だけ別modelで処理する。B&W専用modelは色を捨てるため")
    ap.add_argument("--fp32", action="store_true")
    ap.add_argument("--no-compile", action="store_true",
                    help="torch.compileを使わない")
    ap.add_argument("--compile", default="auto", choices=["auto", "on", "off"],
                    help="torch.compileの使用。autoは素材の長さで判断する")
    ap.add_argument("--dedup", default="balanced",
                    choices=["strict", "balanced", "aggressive"],
                    help="frameの使い回し判定。strictは厳密一致のみ")
    ap.add_argument("--dedup-thresh", type=int, default=None,
                    help="使い回し判定の閾値を直接指定する(素材ごとの較正用)")
    ap.add_argument("--tile-diff", action="store_true",
                    help="変化した領域だけSRする(素材によっては全画面より遅い)")
    ap.add_argument("--tile-core", type=int, default=120)
    ap.add_argument("--tile-halo", type=int, default=0,
                    help="受容野分の余白。0なら起動時に実測して自動設定")
    ap.add_argument("--tile-thresh", type=int, default=6)
    ap.add_argument("--no-trt", dest="trt", action="store_false",
                    help="TensorRTを使わず torch で推論する")
    ap.add_argument("--trt-dynamic", action="store_true",
                    help="解像度可変のengineを1本だけ作る(解像度ごとに作り直さない)")
    ap.add_argument("--trt-batch", type=int, default=2,
                    help="TensorRTのbatch数。2でSRが1.8倍になる(4以上は伸びない)")
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

    targets = expand_inputs(args.input, args.suffix)
    if not targets:
        log("処理対象がありません")
        sys.exit(1)

    videos = [t for t in targets if t[0].suffix.lower() in VIDEO_EXT]
    images = [t for t in targets if t[0].suffix.lower() in IMAGE_EXT]
    # 動画は run_into の非同期経路で回るため、この上限は掛からない。
    # 黙って無視すると効いたと誤認するので断る。
    if videos and args.gpu_share < 100:
        raise SystemExit("--gpu-share は静止画にしか効きません。"
                         f"動画が{len(videos)}本あります")
    if videos and images:
        log(f"動画 {len(videos)}本 / 画像 {len(images)}枚")
    many = len(videos) > 1
    t_all = time.time()
    ng = []
    for i, (src, label, _root) in enumerate(videos, 1):
        if many:
            log("")
            log("=" * 60)
            log(f"【{i}/{len(videos)}】{label}")
        try:
            process(src, args)
        except Exception:
            ng.append(label)
            log(f"失敗: {label}")
            log(traceback.format_exc())
    if many:
        log("")
        log(f"{len(videos)}本中 {len(videos) - len(ng)}本 完了"
            f"  合計 {fmt_time(time.time() - t_all)}")
    if images:
        log("")
        log("=" * 60)
        ng += process_images(images, args)
    for label in ng:
        log(f"  失敗: {label}")
    if ng:
        sys.exit(1)


if __name__ == "__main__":
    main()
