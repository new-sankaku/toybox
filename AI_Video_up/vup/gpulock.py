"""GPU実測の排他lock。5つのprocessが同じGPUで測ると値が壊れるため。

使い方:
    import sys; sys.path.insert(0, r"<このfileのdirectory>")
    from gpulock import gpu_lock
    with gpu_lock("model-arch", "bench_models 20件"):
        ...ここで測る...

- 取得できるまで待つ(既定 最大30分)。待っている間は何もしない。
- lockは 25分でstaleとみなして奪う(process落ちの取り残し対策)。
- 測定以外(download / code書き / 解析)ではlockを取らない事。
"""
import os
import time
from pathlib import Path

LOCK = Path(__file__).resolve().parent / "GPU_LOCK"
STALE = 25 * 60


class gpu_lock:
    def __init__(self, owner, note="", timeout=1800, poll=3.0):
        self.owner, self.note, self.timeout, self.poll = owner, note, timeout, poll

    def __enter__(self):
        t0 = time.time()
        waited = False
        while True:
            try:
                fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, f"{self.owner}\t{os.getpid()}\t{time.time()}\t{self.note}\n"
                         .encode("utf-8"))
                os.close(fd)
                if waited:
                    print(f"[gpu_lock] 取得しました ({time.time()-t0:.0f}秒待ち)", flush=True)
                return self
            except FileExistsError:
                try:
                    txt = LOCK.read_text(encoding="utf-8").strip().split("\t")
                    age = time.time() - float(txt[2])
                    holder = txt[0]
                except Exception:
                    # 読めないlock(手書きのlock file等)を「古い」と誤判定して奪うと、
                    # 実際に測定中のprocessを巻き込む。file の mtime で測る。
                    try:
                        age = time.time() - LOCK.stat().st_mtime
                    except OSError:
                        continue
                    holder = "書式不明"
                if age > STALE:
                    print(f"[gpu_lock] {holder} のlockが{age:.0f}秒古いので奪います", flush=True)
                    try:
                        LOCK.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                if not waited:
                    print(f"[gpu_lock] {holder} が使用中。待ちます", flush=True)
                    waited = True
                if time.time() - t0 > self.timeout:
                    raise TimeoutError(f"GPU lockを{self.timeout}秒待っても取れませんでした")
                time.sleep(self.poll)

    def __exit__(self, *exc):
        try:
            LOCK.unlink()
        except FileNotFoundError:
            pass
        return False
