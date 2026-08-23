"""decode と encode。新設計「絵の列 → 任意時刻 tau」向けの入出力。

設計の根拠は doc/高速化.md の実測値。要点だけ:

  推論        5.24 ms/枚   ← ここが天井
  pack/unpack/nv12/D2H  計 1.03 ms/枚
  decode (pipe)  198 fps = 5.0 ms/枚 (別 thread)
  encode (nvenc p4 + D2H + pipe)  348 fps = 2.9 ms/枚 (別 thread)

decode も encode も推論より速く、しかも別 thread なので **入出力は天井ではない**。
それでも NVDEC (817 fps) へ替えると端から端までで 1.00〜1.39倍になる
(doc/高速化.md 3-3)。効くのは model 呼び出しが少ない素材ほど。

ただし NVDEC の出力は NV12 で、chroma の補間が ffmpeg の bgr24 出力と違う
(PSNR 47.5dB)。他の Agent の品質計測は lib.load() の画素を基準にしているので、
**品質を測る経路へ NvdecDrawingSource を混ぜない**。出力を作る時だけ使う。
既定は pipe 経路のままにし、NVDEC は明示的に選ばせる。

**bufsize を Popen へ渡してはいけない。** 1枚より大きい値を渡すと 1080p の
pipe 読みが 7.1倍遅くなる (vfi/exp_pipe.py: 223.7 fps -> 31.4 fps)。
"""
import queue
import subprocess
import threading

import torch
import torch.nn.functional as F

import lib


# ------------------------------------------------------------ decode

class PipeDecoder:
    """ffmpeg の rawvideo を pipe で読み、pinned buffer で順に渡す。

    読むのは thread、GPU へ上げるのは呼び出し側(main thread)。
    reader thread で H2D すると別 stream になり、同期の面倒が増えるわりに
    得が無い(H2D は 0.48ms/枚)。
    """

    def __init__(self, src, w, h, pool=24, qsize=8):
        self.w, self.h = w, h
        self.nbytes = w * h * 3
        self.p = subprocess.Popen(
            ["ffmpeg", "-v", "error", "-i", str(src), "-fps_mode", "passthrough",
             "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
            stdout=subprocess.PIPE)          # bufsize は渡さない
        self.pool = [torch.empty((h, w, 3), dtype=torch.uint8, pin_memory=True)
                     for _ in range(pool)]
        self.views = [b.numpy() for b in self.pool]
        self.npool = pool
        self.q = queue.Queue(maxsize=qsize)
        self.free = queue.Queue()
        for i in range(pool):
            self.free.put(i)
        self.t = threading.Thread(target=self._read, daemon=True)
        self.t.start()

    def _read(self):
        k = 0
        while True:
            i = self.free.get()
            if i is None:
                break
            got = self.p.stdout.readinto(memoryview(self.views[i].reshape(-1)))
            if not got or got < self.nbytes:
                self.free.put(i)
                break
            self.q.put((k, i))
            k += 1
        self.q.put(None)

    def __iter__(self):
        """(frame番号, pinned tensor, 解放用の callable) を順に返す。"""
        while True:
            item = self.q.get()
            if item is None:
                return
            k, i = item
            yield k, self.pool[i], (lambda i=i: self.free.put(i))

    def close(self):
        self.free.put(None)
        try:
            self.p.stdout.close()
        except OSError:
            pass
        self.p.kill()
        self.p.wait()


class DrawingSource:
    """「絵の番号 → GPU 上の tensor」。同じ絵を何度も decode し直さない。

    絵は複数の出力 frame から何度も参照される。GPU 上に窓で持ち、
    使い終わった古い絵だけ捨てる。窓の外を要求されたら **例外にする**
    (黙って decode し直すと、遅くなった事に誰も気付かない)。

    starts は「その絵が始まる source frame 番号」の昇順配列
    (lib.drawing_runs の戻り値)。
    """

    def __init__(self, src, w, h, starts, window=8):
        self.dec = PipeDecoder(src, w, h)
        self.it = iter(self.dec)
        self.starts = list(int(x) for x in starts)
        self.window = window
        self.ring = [torch.empty((h, w, 3), dtype=torch.uint8, device="cuda")
                     for _ in range(window)]
        self.have = {}                       # 絵番号 -> ring の位置
        self.next_d = 0                      # 次に取り込む絵の番号
        self.oldest = 0                      # まだ捨てていない一番古い絵
        self._exhausted = False

    def _advance(self):
        """次の絵を1枚 GPU へ載せる。"""
        if self.next_d >= len(self.starts):
            self._exhausted = True
            return False
        if self.next_d - self.oldest >= self.window:
            raise RuntimeError(
                f"絵の窓が足りません (窓 {self.window} 枚、"
                f"{self.oldest}〜{self.next_d} を同時に要求)。"
                "release_before を呼ぶか window を広げてください")
        target = self.starts[self.next_d]
        for k, pin, release in self.it:
            if k == target:
                slot = self.next_d % self.window
                self.ring[slot].copy_(pin, non_blocking=True)
                # copy が終わる前に pinned を再利用させない
                ev = torch.cuda.Event()
                ev.record()
                ev.synchronize()
                release()
                self.have[self.next_d] = slot
                self.next_d += 1
                return True
            release()
        self._exhausted = True
        return False

    def get(self, d):
        if d < self.oldest:
            raise RuntimeError(
                f"絵 {d} は窓({self.oldest}〜)から出ています。"
                "window を広げるか、参照の順序を昇順にしてください")
        while d >= self.next_d:
            if not self._advance():
                raise RuntimeError(f"絵 {d} まで decode できませんでした "
                                   f"({self.next_d} 枚で尽きました)")
        return self.ring[self.have[d]]

    def release_before(self, d):
        while self.oldest < d:
            self.have.pop(self.oldest, None)
            self.oldest += 1

    def close(self):
        self.dec.close()


# ------------------------------------------------------------ NVDEC 直 decode

# BT.709 limited range の逆変換。素材の色は tv/bt709 (ffprobe で確認済み)。
_K = dict(cr_r=1.5748, cr_g=0.4681, cb_g=0.1873, cb_b=1.8556)


def nv12_to_bgr(surf, w, h):
    """NVDEC の NV12 surface (h*3/2, w) uint8 -> BGR uint8 HWC。GPU 上で完結。

    chroma は nearest で 2倍にする。ffmpeg の bgr24 出力は双一次に近い補間を
    するので画素は完全一致しない (PSNR は s8_e2e が記録する)。
    """
    y = surf[:h].to(torch.float32)
    uv = surf[h:h + h // 2].reshape(h // 2, w // 2, 2).to(torch.float32)
    cb = uv[:, :, 0].sub_(128.0).mul_(255.0 / 224.0)
    cr = uv[:, :, 1].sub_(128.0).mul_(255.0 / 224.0)
    cb = cb.repeat_interleave(2, 0).repeat_interleave(2, 1)
    cr = cr.repeat_interleave(2, 0).repeat_interleave(2, 1)
    y = y.sub_(16.0).mul_(255.0 / 219.0)
    r = y + _K["cr_r"] * cr
    g = y - _K["cb_g"] * cb - _K["cr_g"] * cr
    b = y + _K["cb_b"] * cb
    return torch.stack((b, g, r), dim=-1).clamp_(0, 255).round_().to(torch.uint8)


class NvdecDrawingSource:
    """DrawingSource と同じ口で、decode を NVDEC (GPU 直) にした版。

    pipe も H2D も通らない。要る絵だけ BGR へ直し、要らない frame は
    decode するだけで捨てる (色変換の費用が乗らない)。

    NVDEC の surface は decoder が使い回すので、次の Decode を呼ぶ前に
    **自分の stream を同期して** 複製を確定させる必要がある。main の stream
    を同期すると推論待ちに巻き込まれるので、専用 stream を持つ。
    """

    def __init__(self, src, w, h, starts, window=8):
        import os
        import pathlib
        os.add_dll_directory(str(pathlib.Path(torch.__file__).parent / "lib"))
        import PyNvVideoCodec as nvc

        self.w, self.h = w, h
        self.starts = [int(x) for x in starts]
        self.window = window
        self.dmx = nvc.CreateDemuxer(filename=str(src))
        self.dec = nvc.CreateDecoder(gpuid=0, codec=self.dmx.GetNvCodecId(),
                                     cudacontext=0, cudastream=0,
                                     usedevicememory=True)
        self.ring = [torch.empty((h, w, 3), dtype=torch.uint8, device="cuda")
                     for _ in range(window)]
        self.stream = torch.cuda.Stream()
        self.free = threading.Semaphore(window)
        self.cv = threading.Condition()
        self.ready = -1                  # ここまでの絵は ring に載っている
        self.oldest = 0
        self.err = None
        self.n_decoded = 0
        self.t = threading.Thread(target=self._run, daemon=True)
        self.t.start()

    def _run(self):
        try:
            want, k = 0, 0
            for pkt in self.dmx:
                for f in self.dec.Decode(pkt):
                    if want < len(self.starts) and k == self.starts[want]:
                        if not self.free.acquire(timeout=300):
                            raise RuntimeError("絵の窓が空きません")
                        with torch.cuda.stream(self.stream):
                            self.ring[want % self.window].copy_(
                                nv12_to_bgr(torch.from_dlpack(f), self.w, self.h))
                        self.stream.synchronize()
                        with self.cv:
                            self.ready = want
                            self.cv.notify_all()
                        want += 1
                    k += 1
            self.n_decoded = k
        except Exception as exc:                      # thread の中で握り潰さない
            with self.cv:
                self.err = exc
                self.cv.notify_all()
        finally:
            with self.cv:
                self.cv.notify_all()

    def get(self, d):
        if d < self.oldest:
            raise RuntimeError(f"絵 {d} は窓({self.oldest}〜)から出ています")
        with self.cv:
            while self.ready < d and self.err is None and self.t.is_alive():
                self.cv.wait(1.0)
            if self.err is not None:
                raise self.err
            if self.ready < d:
                raise RuntimeError(f"絵 {d} まで decode できませんでした "
                                   f"({self.ready + 1} 枚で尽きました)")
        return self.ring[d % self.window]

    def release_before(self, d):
        while self.oldest < d:
            self.oldest += 1
            self.free.release()

    def close(self):
        self.dmx = None
        self.dec = None


# ------------------------------------------------------------ encode

def nv12(bgr_u8):
    """uint8 BGR HWC(cuda) -> nv12 uint8 (h*3/2, w)。vup/trt_backend.py と同式。"""
    x = bgr_u8.permute(2, 0, 1).float().div_(255.0).unsqueeze(0)
    b, g, r = x[:, 0:1], x[:, 1:2], x[:, 2:3]
    luma = 0.299 * r + 0.587 * g + 0.114 * b
    u = (b - luma) * (0.5 / (1 - 0.114))
    v = (r - luma) * (0.5 / (1 - 0.299))
    y = (luma * 219.0 + 16.0)[:, 0]
    u = F.avg_pool2d(u, 2) * 224.0 + 128.0
    v = F.avg_pool2d(v, 2) * 224.0 + 128.0
    uv = torch.stack((u, v), dim=-1)
    uv = uv.reshape(uv.shape[0], uv.shape[2], -1)
    return torch.cat((y, uv), dim=1).clamp_(0, 255).round_().to(torch.uint8)[0]


class NvencWriter:
    """GPU の BGR を nv12 化 -> pinned -> pipe -> hevc_nvenc。

    出力 frame ごとに torch.cuda.synchronize() を呼ぶと、補間しなくても
    58.8 fps で頭打ちになる(旧実装で実測)。event を writer thread へ渡し、
    main thread は待たない。
    """

    def __init__(self, out_path, w, h, fps_num, fps_den,
                 encoder="hevc_nvenc", args="-preset p4 -cq 24", nbuf=12):
        self.w, self.h = w, h
        self.p = subprocess.Popen(
            ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "nv12",
             "-s", f"{w}x{h}", "-r", f"{fps_num}/{fps_den}", "-i", "-",
             "-c:v", encoder] + args.split()
            + ["-pix_fmt", "yuv420p", str(out_path)], stdin=subprocess.PIPE)
        self.free = queue.Queue()
        for _ in range(nbuf):
            b = torch.empty((h * 3 // 2, w), dtype=torch.uint8, pin_memory=True)
            self.free.put((b, b.numpy(), torch.cuda.Event()))
        self.q = queue.Queue(maxsize=nbuf)
        self.n = 0
        self.t = threading.Thread(target=self._write, daemon=True)
        self.t.start()

    def _write(self):
        while True:
            item = self.q.get()
            if item is None:
                break
            buf, arr, ev = item
            ev.synchronize()
            self.p.stdin.write(arr)
            self.free.put((buf, arr, ev))

    def sink(self, out_slot, bgr_gpu):
        """BatchRunner から呼ばれる。out_slot は順番の目印で、値は使わない。"""
        buf, arr, ev = self.free.get()
        buf.copy_(nv12(bgr_gpu), non_blocking=True)
        ev.record()
        self.q.put((buf, arr, ev))
        self.n += 1

    def close(self):
        self.q.put(None)
        self.t.join()
        self.p.stdin.close()
        self.p.wait()
        return self.n
