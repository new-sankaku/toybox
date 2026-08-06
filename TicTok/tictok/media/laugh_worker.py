"""笑い声検出をGPUで走らせるための**別process**境界。

親(server) ... ``run_build`` が子processを起こし、確率列を受け取る。
子         ... ``python -m tictok.media.laugh_worker <入力path>`` が実際に解析する。

CPU実行(``TICTOK_LAUGH_AUDIO_DEVICE=cpu``、既定)はこの経路を通らない。process内で
``laugh_audio._build`` を直接呼ぶ。ここが要るのはcudaのときだけである。

== なぜ同じprocessで走らせてはいけないか ==

``doc/STT_PROCESS_ISOLATION.md`` と同じ理由である。WindowsはDLLを名前1つにつき1個しか
processへ載せない。このprojectのvenvには ``cudnn64_9.dll`` が**3つ**入っている:

    venv/Lib/site-packages/ctranslate2/cudnn64_9.dll      (faster-whisper 同梱 9.10.2)
    venv/Lib/site-packages/torch/lib/cudnn64_9.dll        (torch 2.6+cu124 同梱 9.1.0)
    venv/Lib/site-packages/nvidia/cudnn/bin/cudnn64_9.dll (nvidia wheel)

onnxruntime-gpu はここへ4つ目の要求(cuDNN 9.*)を持ち込む。版の食い違った組で呼ばれた
cuDNNは整合性checkに失敗して ``0xc0000409`` でprocessごと即死し、例外にならないので
try/exceptでは拾えず、logも1行も残らない(STTで実測3回)。**同居させないことが唯一の
対処**で、``gpu_slot`` のような直列化では解けない — DLLの常駐は解かれないため。

副次的に、子の死は親が終了codeとstderrで必ず観測でき、解析ごとにVRAMが必ず解放される。

== 親子の約束 ==

子の**標準出力はJSONLの制御channel専用**で、1行1 message:

    {"t": "progress", "seconds": 復号済み秒}
    {"t": "result", "profile": {...}}      最後に1回だけ
    {"t": "error",  "message": "..."}

logは標準errorへ出す(親が読み取ってserverのlogへ流す)。stdoutへlogを混ぜてはならない
— 制御channelが壊れて結果を読めなくなる。確率列は3時間の録画でも1万点強・JSONで
100KB程度なので、1行で渡して差し支えない。
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path
from typing import Optional

from tictok.core.gpu import gpu_slot
from tictok.paths import PROJECT_ROOT

logger = logging.getLogger("tictok.laugh")

# 失敗時のerror本文に載せる子のlog行数。全部載せると原因が埋もれる(stt_workerと同値)。
STDERR_TAIL_LINES = 40

# 実行中の子。Windowsは親が終わっても子を道連れにしないので、server停止時にここから
# 明示的に落とす(落とさないとGPUを掴んだままの孤児が残る)。
_children_lock = threading.Lock()
_children: set = set()


def terminate_all() -> int:
    """実行中の子をすべて落とす。落とした数を返す(server停止時に呼ぶ)。"""
    with _children_lock:
        targets = list(_children)
    for proc in targets:
        if proc.poll() is None:
            proc.kill()
    if targets:
        logger.info(
            "笑い声検出のworker: 子process %d 件を終了させました", len(targets),
            extra={"event": "laugh.worker_terminated", "ctx": {"children": len(targets)}},
        )
    return len(targets)


def register_cuda_dll_dirs() -> list:
    """CUDA runtimeのDLLをloaderへ登録する。登録したdirectoryを返す。

    **子process側でだけ呼ぶこと。** 親(server)で呼ぶと、この後にCUDA EPが載る道を開いて
    しまい、module docstringの同居問題そのものになる。

    ``nvidia-*-cu12`` wheel群(cublas / cudnn / cuda_runtime / cuda_nvrtc)に加えて
    **torchが同梱するlib directoryも足す**。onnxruntime-gpuのCUDA EPは cuFFT にも依存
    するが、``nvidia-cufft-cu12`` はこのvenvに入っておらず(実測: cufft64_11.dll が
    missing でCUDA EPの読み込みが失敗した)、同じDLLがtorchの同梱物として既に在るため。
    cuFFTのためだけに274MBのwheelを増やす必要はない。

    ``add_dll_directory`` だけでは足りず**PATHにも積む**。onnxruntimeはprovider DLLを
    loaderのPATH検索で解決するので、片方だけではDLLを見つけられない
    (transcription._register_cuda_dll_dirs が同じ理由で同じことをしている)。
    """
    if not sys.platform.startswith("win"):
        # LinuxではwheelがRPATHでlibを指すので登録は要らない。
        return []
    bin_dirs: list = []
    try:
        import nvidia
    except ImportError:
        nvidia = None
    if nvidia is not None:
        for base in getattr(nvidia, "__path__", []):
            try:
                subs = os.listdir(base)
            except OSError:
                continue
            for sub in subs:
                bin_dir = os.path.join(base, sub, "bin")
                if os.path.isdir(bin_dir):
                    bin_dirs.append(bin_dir)
    try:
        import torch  # noqa: F401  (DLLの置き場を知るためだけにimportする)
        torch_lib = os.path.join(os.path.dirname(torch.__file__), "lib")
    except ImportError:
        torch_lib = None
    if torch_lib and os.path.isdir(torch_lib):
        bin_dirs.append(torch_lib)

    for bin_dir in bin_dirs:
        try:
            os.add_dll_directory(bin_dir)
        except OSError:
            logger.warning(
                "CUDAのDLL dir %s を登録できません", bin_dir,
                extra={"event": "laugh.cuda_dll_dir_rejected", "ctx": {"path": bin_dir}},
                exc_info=True,
            )
    if bin_dirs:
        existing = os.environ.get("PATH", "")
        new = [d for d in bin_dirs if d not in existing]
        if new:
            os.environ["PATH"] = os.pathsep.join(new) + os.pathsep + existing
    return bin_dirs


def _drain_stderr(stream, tail: deque) -> None:
    """子のlogを読み続け、そのままserverのlogへ流す。

    読み続けること自体が必須である。stderrはpipe(既定64KB)で、親が読まないまま埋まると
    子は書き込みでblockし、解析が無言で止まる。"""
    for raw in stream:
        line = raw.rstrip("\r\n")
        if not line:
            continue
        tail.append(line)
        logger.info("[laugh] %s", line)


def run_build(src, window: float, hop: float, on_progress=None) -> dict:
    """``src`` の笑い確率列を子processで作り、profile dictを返す。同期(threadから呼ぶ)。

    GPU枠はここで押さえる。``gpu_slot`` はprocess内のsemaphoreなので、子で取っても他の
    jobとは噛み合わない — 枠を持つのは常に親側である(stt_workerと同じ)。

    ``on_progress(復号済み秒)`` は子が送る進捗をそのまま中継する。"""
    from tictok.media.laugh_audio import LaughAudioError

    args = [sys.executable, "-u", "-m", "tictok.media.laugh_worker", str(src),
            "--window", repr(float(window)), "--hop", repr(float(hop))]
    tail: deque = deque(maxlen=STDERR_TAIL_LINES)
    with gpu_slot("laugh"):
        proc = subprocess.Popen(
            args, cwd=str(PROJECT_ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", env=dict(os.environ),
        )
        with _children_lock:
            _children.add(proc)
        reader = threading.Thread(target=_drain_stderr, args=(proc.stderr, tail),
                                  daemon=True, name="laugh-worker-log")
        reader.start()
        profile: Optional[dict] = None
        failure: Optional[dict] = None
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except ValueError:
                    # 制御channelに素のtextが出てきた = 約束が破れている。捨てずにlogへ
                    # 残す(黙って読み飛ばすと結果が来ない理由が分からなくなる)。
                    logger.warning(
                        "笑い声検出のworkerがJSON以外の行をstdoutへ出力しました: %.200s",
                        line,
                        extra={"event": "laugh.worker_protocol_violation",
                               "ctx": {"line": line[:200]}},
                    )
                    continue
                kind = message.get("t")
                if kind == "progress":
                    if on_progress is not None:
                        on_progress(message.get("seconds") or 0.0)
                elif kind == "result":
                    profile = message.get("profile")
                elif kind == "error":
                    failure = message
            code = proc.wait()
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            with _children_lock:
                _children.discard(proc)
            reader.join(timeout=5)

    if failure is not None:
        raise LaughAudioError(failure.get("message") or "笑い声検出に失敗しました。")
    if code != 0 or profile is None:
        # 子が異常終了した。native crash(0xc0000409等)はpythonの例外にならないので、
        # ここが唯一の観測点になる。終了codeと直前のlogを必ず本文へ残すこと。
        detail = "\n".join(tail) or "(子processのlogはありません)"
        raise LaughAudioError(
            "笑い声検出のprocessが異常終了しました(exit=%s)。直前のlog:\n%s" % (code, detail))
    return profile


# ===== 子process側 =====


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main(argv: list) -> int:
    if len(argv) < 2:
        print("usage: python -m tictok.media.laugh_worker <path> [--window S] [--hop S]",
              file=sys.stderr)
        return 2
    # logは標準errorへ。親が読んでserverのlogへ流す(stdoutは制御channel専用)。
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(name)s %(message)s")
    src = Path(argv[1])
    window = hop = None
    for i, arg in enumerate(argv):
        if arg == "--window" and i + 1 < len(argv):
            window = float(argv[i + 1])
        elif arg == "--hop" and i + 1 < len(argv):
            hop = float(argv[i + 1])

    dirs = register_cuda_dll_dirs()
    logging.getLogger("tictok.laugh").info("CUDAのDLL dirを %d 件登録しました", len(dirs))

    from tictok.core.config import (get_laugh_audio_hop_seconds,
                                    get_laugh_audio_window_seconds)
    from tictok.media.laugh_audio import LaughAudioError, _build

    if window is None:
        window = get_laugh_audio_window_seconds()
    if hop is None:
        hop = get_laugh_audio_hop_seconds()

    from tictok.core.config import get_job_progress_min_interval_seconds
    from tictok.core.progress import IntervalGate

    # 復号は1 chunkごとに進むので、そのまま送ると1本で数万行になる。親が使うのは表示用の
    # 位置だけなので、時間で間引いて送る。
    gate = IntervalGate(get_job_progress_min_interval_seconds())

    def on_progress(seconds: float) -> None:
        if gate.ready():
            _emit({"t": "progress", "seconds": seconds})

    try:
        profile = _build(src, window, hop, on_progress)
    except LaughAudioError as exc:
        _emit({"t": "error", "message": str(exc)})
        return 3
    except Exception as exc:  # noqa: BLE001 - 親へ理由を渡してから落ちる
        logging.getLogger("tictok.laugh").exception("笑い声検出がworkerで失敗しました")
        _emit({"t": "error", "message": "笑い声検出に失敗しました: %s" % exc})
        return 4
    _emit({"t": "result", "profile": profile})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
