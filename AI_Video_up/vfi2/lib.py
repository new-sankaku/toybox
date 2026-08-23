"""vfi2 の共通基盤。

vfi/ の資産(model 実装・TensorRT engine・GPU metric)をそのまま使う。
違うのは素材が3本になったことと、「絵の列」を最初から一級の概念として
持つことの2点。

素材:
  A_op    OP (1:30-2:00)   1コマ打ち・cut と effect が多い。最も辛い
  B_talk  会話 (4:00-4:30) 限定animation。1枚が5.45 frame 保持される
  C_act   戦闘 (13:00-13:30) 本編の action。cut と effect と保持が混ざる
"""
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
VFI1 = ROOT.parent / "vfi"
sys.path.insert(0, str(VFI1))

WORK = ROOT / "work"
RESULTS = ROOT / "results"
OUT = ROOT / "out"
for _d in (WORK, RESULTS, OUT):
    _d.mkdir(exist_ok=True)

SRC_MKV = ROOT.parent / "[SubsPlease] Arknights - Enshin Shomei - 24 (1080p) [C62475EB].mkv"

CLIPS = {
    "A_op": dict(path=WORK / "A_op.mkv", ss=90, label="OP(1コマ打ち・大変位)"),
    "B_talk": dict(path=WORK / "B_talk.mkv", ss=240, label="会話(限定animation)"),
    "C_act": dict(path=WORK / "C_act.mkv", ss=780, label="戦闘(本編action)"),
}
W, H = 1920, 1080
FPS_NUM, FPS_DEN = 24000, 1001
FPS = FPS_NUM / FPS_DEN

MOVE_MIN = 16     # box4 がこれ未満なら同じ絵(vup の dedup balanced と同値)
SCD_CUT = 10.0    # ffmpeg scdet の score。これ以上を cut とみなす


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------- 素材

def memmap_path(clip):
    """A_op / B_talk は vfi/work に既に 4.5GB の展開がある。作り直さない。"""
    old = VFI1 / "work" / f"{clip}.bgr24.npy"
    if old.exists():
        return old
    return WORK / f"{clip}.bgr24.npy"


def decode_to_memmap(clip):
    dst = memmap_path(clip)
    if dst.exists():
        return np.load(dst, mmap_mode="r")
    src = CLIPS[clip]["path"]
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
        # bufsize は渡さない(1080p で 7.1倍遅くなる)
        stdout=subprocess.PIPE)
    for i in range(n):
        if p.stdout.readinto(memoryview(arr[i].reshape(-1))) < W * H * 3:
            raise RuntimeError(f"{clip}: frame {i} で decode が尽きました")
    if p.stdout.read(1):
        raise RuntimeError(f"{clip}: decoder に frame が余っています")
    p.wait()
    arr.flush()
    return np.load(dst, mmap_mode="r")


def load(clip):
    return decode_to_memmap(clip)


# ---------------------------------------------------------------- cut

def scd_path(clip):
    old = VFI1 / "results" / f"scd_{clip}.npy"
    if old.exists():
        return old
    return RESULTS / f"scd_{clip}.npy"


def _scd_convention_shift(clip, raw):
    """scd の score が「新 shot の先頭」に付いているか「旧 shot の末尾」かを画素で判定する。

    ffmpeg の scdet は比較後の frame(= 新 shot の先頭)へ score を付けるが、
    vfi/ から継承した file は1つ手前へずらして保存されている。どちらの規約でも
    `cut_frames` が正しく動くよう、**画素を見て**「index i の score は i→i+1 の
    変わり目」という規約へ揃える。

    規約を仮定で決めない。実測した C_act で `+1` 固定が1 frame ずれ、
    試験集合の 128px 超の組の 4/7 が cut になっていた。
    """
    import vfilib as V
    a = load(clip)
    idx = np.where(raw >= SCD_CUT)[0]
    idx = idx[(idx > 0) & (idx < len(a) - 1)][:12]
    if len(idx) == 0:
        return raw
    at_i, at_next = 0, 0
    for i in idx:
        i = int(i)
        if V.box4_max_cpu(a[i - 1], a[i]) > V.box4_max_cpu(a[i], a[i + 1]):
            at_i += 1          # 変わり目は (i-1|i)。score は新 shot の先頭に在る
        else:
            at_next += 1       # 変わり目は (i|i+1)。既に目的の規約
    if at_i > at_next:
        log(f"{clip}: scd の規約を1 frame 手前へ揃えます ({at_i}/{len(idx)} 件で判定)")
        out = np.zeros_like(raw)
        out[:-1] = raw[1:]
        return out
    return raw


def scdet(clip):
    """ffmpeg scdet の score。index i は「frame i と i+1 の間が cut か」を表す。

    生の出力の規約は生成元で違うので、`_scd_convention_shift` で画素を見て揃える。
    """
    dst = RESULTS / f"scdn_{clip}.npy"          # 規約を揃えた後の物
    if dst.exists():
        return np.load(dst)
    raw_path = scd_path(clip)
    if raw_path.exists():
        raw = np.load(raw_path)
    else:
        txt = RESULTS / f"scene_{clip}.txt"
        # filter の引数に Windows の絶対path を書くと `\` と `:` で parse に落ちる。
        # results/ を cwd にして相対名で渡す。
        subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(CLIPS[clip]["path"]),
             "-vf", f"scdet=threshold=0,metadata=print:file={txt.name}",
             "-an", "-f", "null", "-"], check=True, cwd=str(RESULTS))
        n = len(load(clip))
        raw = np.zeros(n, dtype=np.float32)
        cur = None
        for line in txt.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("frame:"):
                cur = int(line.split()[0].split(":")[1])
            elif "lavfi.scd.score=" in line and cur is not None:
                raw[cur] = float(line.split("=")[1])
        np.save(raw_path, raw)
    out = _scd_convention_shift(clip, raw)
    np.save(dst, out)
    return out


# ---------------------------------------------------------------- 絵の列

def drawing_runs(clip, move_min=MOVE_MIN):
    """絵が切り替わる frame 番号の列。

    比較相手は run の先頭に固定する。直前の frame と比べると閾値未満の差が
    毎frame見逃されて累積し、判定が少しずつ緩くなる。
    """
    dst = RESULTS / f"runs_{clip}_{move_min}.npy"
    if dst.exists():
        return np.load(dst)
    import vfilib as V
    a = load(clip)
    scd = scdet(clip)
    starts = [0]
    ref = a[0]
    for i in range(1, len(a)):
        if scd[i - 1] >= SCD_CUT or V.box4_max(ref, a[i]) >= move_min:
            starts.append(i)
            ref = a[i]
    runs = np.array(starts, dtype=np.int32)
    np.save(dst, runs)
    return runs


def cut_frames(clip):
    """cut が入る frame 番号(その frame から新しい shot)。"""
    scd = scdet(clip)
    return np.where(scd[:-1] >= SCD_CUT)[0] + 1


# ---------------------------------------------------------------- 記録

def record(kind, payload):
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
        if kind is None or r.get("kind") == kind:
            out.append(r)
    return out


def done_keys(kind, keyfields):
    return {tuple(r.get(k) for k in keyfields) for r in read_records(kind)}


# ---------------------------------------------------------------- metric

def _v():
    import vfilib as V
    return V


def psnr(a, b):
    return _v().psnr(a, b)


def box4_max(a, b):
    return _v().box4_max(a, b)


def bad_pixels(a, b, thresh=48):
    return _v().bad_pixels(a, b, thresh)


def lpips_score(a, b, device="cuda"):
    return _v().lpips_score(a, b, device)


def gmsd(a, b):
    """GPU版。vfilib は CPU版の再定義で GPU版が隠れているのでこちらを使う。"""
    import gpumetric
    return gpumetric.gmsd(a, b)


# ---------------------------------------------------------------- GPU 排他
#
# GPU は1枚しかない。複数の Agent が同時に回すと、速度の実測値が互いに汚染される
# (実測: v4.6 fp16 bs=1 1080p が、GPU 空き時 5.32ms に対し他が81%使用中は 11.65ms)。
#
# ただし全員が排他 lock を握ると、品質の測定(何十分も掛かる)が直列化して終わらない。
# そこで 2段にする。
#
#   gpu_use(who)   共有。GPU を使うが時間は測らない処理(品質測定・engine build など)。
#                  同時に何本でも入れる。ただし排他の待ち手が居る間は新規に入らない。
#   gpu_lock(who)  排他。時間を測る処理。共有の使用者が全員抜けるまで待ってから入る。
#
# **GPU を触る処理は必ずどちらかで囲むこと。**囲まない処理は他人の実測値を壊す。

import atexit
import contextlib
import os
import threading

LOCKDIR = RESULTS / ".gpulock"
LOCKDIR.mkdir(exist_ok=True)
EXCL = LOCKDIR / "exclusive"
WANT = LOCKDIR / "want"
SHARE = LOCKDIR / "share"
for _d in (WANT, SHARE):
    _d.mkdir(exist_ok=True)

STALE = 120.0          # 秒。これより古い token は落ちた process の残骸とみなす
BEAT = 20.0            # 秒。token の mtime を更新する間隔


def _sweep():
    """落ちた process が残した token を掃除する。"""
    now = time.time()
    for f in list(SHARE.glob("*.tok")) + list(WANT.glob("*.tok")) + [EXCL]:
        try:
            if f.exists() and now - f.stat().st_mtime > STALE:
                log(f"gpu: {f.name} が {now - f.stat().st_mtime:.0f}秒古いので破棄します")
                f.unlink(missing_ok=True)
        except OSError:
            pass


class _Beat(threading.Thread):
    """token の mtime を更新し続ける。生存の証明。"""

    def __init__(self, path):
        super().__init__(daemon=True)
        self.path, self.stop = path, threading.Event()

    def run(self):
        while not self.stop.wait(BEAT):
            try:
                os.utime(self.path, None)
            except OSError:
                return


def _create(path, text, exclusive):
    """token を作る。exclusive なら既に在れば False を返す(O_EXCL)。"""
    flags = os.O_CREAT | os.O_WRONLY | (os.O_EXCL if exclusive else os.O_TRUNC)
    try:
        fd = os.open(str(path), flags)
    except FileExistsError:
        return False
    os.write(fd, text.encode())
    os.close(fd)
    return True


@contextlib.contextmanager
def _held(path, who):
    b = _Beat(path)
    b.start()
    fin = lambda: path.unlink(missing_ok=True)
    atexit.register(fin)
    try:
        yield
    finally:
        b.stop.set()
        atexit.unregister(fin)
        fin()


def _deadline(t0, timeout, who, what):
    if time.time() - t0 > timeout:
        raise TimeoutError(f"gpu({who}): {timeout}秒待っても {what} が空きません")


@contextlib.contextmanager
def gpu_use(who="?", timeout=7200.0):
    """共有。GPU を使うが時間は測らない処理を囲む。

    排他の待ち手が居る間は新規に入らない(書き手飢餓を防ぐ)。
    """
    tok = SHARE / f"{who}.{os.getpid()}.tok"
    t0 = time.time()
    said = False
    while True:
        if EXCL.exists() or any(WANT.glob("*.tok")):
            _sweep()
            if EXCL.exists() or any(WANT.glob("*.tok")):
                _deadline(t0, timeout, who, "GPU")
                if not said:
                    log(f"gpu({who}): 排他の使用者/待ち手が居るため待機します")
                    said = True
                time.sleep(2.0)
                continue
        _create(tok, f"{who} {os.getpid()} {time.time():.0f}", exclusive=False)
        # token を置いた後にもう一度見る。この順序が要る。先に確認してから
        # 置くと、確認と設置の間に排他が割り込んで両方が通る
        if EXCL.exists() or any(WANT.glob("*.tok")):
            tok.unlink(missing_ok=True)
            continue
        with _held(tok, who):
            yield
        return


@contextlib.contextmanager
def gpu_lock(who="?", timeout=7200.0):
    """排他。時間を測る処理を囲む。共有の使用者が全員抜けるまで待つ。

    排他同士も O_EXCL で直列化する。待ち手が複数居ても1つしか通らない。
    """
    want = WANT / f"{who}.{os.getpid()}.tok"
    _create(want, f"{who} {os.getpid()} {time.time():.0f}", exclusive=False)
    t0 = time.time()
    said = False
    try:
        with _held(want, who):
            while True:
                _sweep()
                if not any(SHARE.glob("*.tok")) and _create(
                        EXCL, f"{who} {os.getpid()} {time.time():.0f}", exclusive=True):
                    break
                _deadline(t0, timeout, who, "共有の使用者か他の排他")
                if not said:
                    log(f"gpu({who}): GPU が空くのを待機します")
                    said = True
                time.sleep(2.0)
            with _held(EXCL, who):
                want.unlink(missing_ok=True)
                yield
    finally:
        want.unlink(missing_ok=True)


def gpu_busy_pct():
    """今の GPU 使用率(%)。測定値へ併記して、汚染された値を後から捨てられるようにする。"""
    r = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used",
                        "--format=csv,noheader,nounits"],
                       capture_output=True, text=True)
    util, mem = r.stdout.strip().splitlines()[0].split(",")
    return int(util), int(mem)


if __name__ == "__main__":
    for c in sys.argv[1:] or list(CLIPS):
        a = load(c)
        runs = drawing_runs(c)
        cuts = cut_frames(c)
        log(f"{c}: frame {len(a)} / 絵 {len(runs)} "
            f"(1枚 {len(a)/len(runs):.2f} frame) / cut {len(cuts)}")
