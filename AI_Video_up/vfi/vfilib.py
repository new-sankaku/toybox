"""VFI計測の共通基盤。素材の読み込み・記録・metric。

記録は results/results.jsonl への追記のみで行う。実験scriptが途中で落ちても
それまでの計測値は残り、同じ計測を二度やらずに済む。
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "work"
RESULTS = ROOT / "results"
MODELS = ROOT / "models"
ONNX = ROOT / "onnx"
ENGINES = ROOT / "engines"
for _d in (WORK, RESULTS, MODELS, ONNX, ENGINES):
    _d.mkdir(exist_ok=True)

# 素材。A=OP(cut/effectが多い)、B=本編の会話場面(限定animation)
CLIPS = {
    "A_op": WORK / "A_op.mkv",
    "B_talk": WORK / "B_talk.mkv",
}
W, H = 1920, 1080
FPS_NUM, FPS_DEN = 24000, 1001


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------- 素材

def memmap_path(clip):
    return WORK / f"{clip}.bgr24.npy"


def decode_to_memmap(clip):
    """clipの全frameをBGR24のmemmapへ落とす。

    lossless再encodeしたsampleを更にlosslessに読むので、以降の実験は
    すべて同じ画素の上で走る。decodeを実験のたびに繰り返さない。
    """
    dst = memmap_path(clip)
    if dst.exists():
        return np.load(dst, mmap_mode="r")
    src = CLIPS[clip]
    n = int(subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
         "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(src)],
        capture_output=True, text=True).stdout.strip())
    log(f"{clip}: {n} frame を memmap へ展開します")
    arr = np.lib.format.open_memmap(dst, mode="w+", dtype=np.uint8,
                                    shape=(n, H, W, 3))
    p = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(src), "-fps_mode", "passthrough",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
        # bufsize は渡さない。1枚より大きい値を渡すと BufferedReader が
        # 内部bufferを経由して 1080p で 7倍遅くなる(exp_pipe.py)
        stdout=subprocess.PIPE)
    for i in range(n):
        got = p.stdout.readinto(memoryview(arr[i].reshape(-1)))
        if got < W * H * 3:
            raise RuntimeError(f"{clip}: frame {i} で decode が尽きました")
    if p.stdout.read(1):
        raise RuntimeError(f"{clip}: decoder に frame が余っています")
    p.wait()
    arr.flush()
    return np.load(dst, mmap_mode="r")


def load(clip):
    return decode_to_memmap(clip)


# ---------------------------------------------------------------- 記録

def record(kind, payload):
    """1件の計測結果を jsonl へ追記する。"""
    rec = {"kind": kind, "at": time.strftime("%Y-%m-%d %H:%M:%S"), **payload}
    with open(RESULTS / "results.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def read_records(kind=None):
    p = RESULTS / "results.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if kind is None or r["kind"] == kind:
            out.append(r)
    return out


def done_keys(kind, keyfields):
    """既に測ってある物の key 集合。実験の再開に使う。"""
    return {tuple(r.get(k) for k in keyfields) for r in read_records(kind)}


# ---------------------------------------------------------------- metric
#
# 実体は GPU 版(gpumetric.py)へ回す。1920x1080 の1枚あたり
#   psnr 80.2ms / bad_pixels 73.4ms / gmsd 61.0ms / box4 3.6ms  (CPU, 合計218ms)
#   psnr 0.84ms / bad_pixels 0.62ms / gmsd 1.45ms / box4 0.55ms (GPU, 合計3.4ms)
# で 63倍違い、model の 5.7ms より metric の方が重いという状態だった。
# 値が一致することは検算済み(box4 と bad_pixels は完全一致、psnr 1e-7、gmsd 3e-4)。
# *_cpu は検算用に残してある。


def psnr_cpu(a, b):
    """uint8 の2枚。完全一致は inf ではなく 100 を返す(集計しやすくする)。"""
    d = a.astype(np.float64) - b.astype(np.float64)
    mse = float((d * d).mean())
    if mse <= 0:
        return 100.0
    return float(10.0 * np.log10(255.0 * 255.0 / mse))


def box4_max_cpu(a, b):
    """vup の Dedup と同じ判定量。|diff| を4x4 box平均へ畳んでから最大。"""
    import cv2
    d = cv2.absdiff(a, b)
    small = (b.shape[1] // 4, b.shape[0] // 4)
    return int(cv2.resize(d, small, interpolation=cv2.INTER_AREA).max())


def bad_pixels_cpu(a, b, thresh=48):
    """|d|>thresh の画素数(3chのどれか)。判定基準と独立な取りこぼし指標。"""
    import cv2
    d = cv2.absdiff(a, b)
    return int((d.max(axis=2) > thresh).sum())


def gmsd_cpu(a, b):
    """Gradient Magnitude Similarity Deviation。線画の崩れに感度がある。"""
    import cv2
    ga = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gb = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY).astype(np.float32)
    kx = np.array([[1, 0, -1], [1, 0, -1], [1, 0, -1]], np.float32) / 3.0
    ky = kx.T

    def grad(g):
        return np.sqrt(cv2.filter2D(g, -1, kx) ** 2 + cv2.filter2D(g, -1, ky) ** 2)

    ma, mb = grad(ga), grad(gb)
    c = 170.0
    gms = (2 * ma * mb + c) / (ma ** 2 + mb ** 2 + c)
    return float(gms.std())


def _gm():
    import gpumetric
    return gpumetric


def psnr(a, b):
    return _gm().psnr(a, b)


def box4_max(a, b):
    return int(round(_gm().box4_max(a, b)))


def bad_pixels(a, b, thresh=48):
    return _gm().bad_pixels(a, b, thresh)


def gmsd(a, b):
    return _gm().gmsd(a, b)


_lpips_net = None


def lpips_score(a, b, device="cuda"):
    """LPIPS(AlexNet)。uint8 BGR の numpy か cuda tensor を渡す。低いほど良い。"""
    global _lpips_net
    import torch
    import lpips as _l
    if _lpips_net is None:
        _lpips_net = _l.LPIPS(net="alex").to(device).eval()

    def prep(x):
        if torch.is_tensor(x):
            t = x.flip(-1)                      # BGR -> RGB
        else:
            t = torch.from_numpy(np.ascontiguousarray(x[:, :, ::-1])).to(device)
        t = t.permute(2, 0, 1).float().div_(127.5).sub_(1.0)
        return t.unsqueeze(0)

    with torch.no_grad():
        return float(_lpips_net(prep(a), prep(b)).item())


def gmsd(a, b):
    """Gradient Magnitude Similarity Deviation。線画の崩れに感度がある。

    低いほど良い。PSNRは平坦部が支配するので、animeの輪郭評価には別軸が要る。
    """
    import cv2
    ga = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gb = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY).astype(np.float32)
    kx = np.array([[1, 0, -1], [1, 0, -1], [1, 0, -1]], np.float32) / 3.0
    ky = kx.T
    def grad(g):
        return np.sqrt(cv2.filter2D(g, -1, kx) ** 2 + cv2.filter2D(g, -1, ky) ** 2)
    ma, mb = grad(ga), grad(gb)
    c = 170.0
    gms = (2 * ma * mb + c) / (ma ** 2 + mb ** 2 + c)
    return float(gms.std())
