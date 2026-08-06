"""文字起こしを**別process**で実行するための境界。

親(server) ... ``run_transcribe`` が子processを起こし、進捗と結果を受け取る。
子         ... ``python -m tictok.record.stt_worker <入力path>`` が実際に復号する。

== なぜ同じprocessで走らせてはいけないか ==

文字起こし(faster-whisper = CTranslate2)と、焼き込み・Up出力(torch)は、**別versionの
cuDNNを同梱している**。WindowsはDLLを名前1つにつき1個しかprocessへ載せないため、先に
文字起こしが載せた ``cudnn64_9.dll``(ctranslate2同梱 9.10.2)を、後から来たtorchも掴む。
cuDNN 9のこのDLLは実体を持たない振り分け役で、実体はtorch側の 9.1.0 が解決される。
版の食い違った組で呼ばれたcuDNNは整合性checkに失敗し、``0xc0000409``(fail-fast)で
**processごと即死**する。実測3回、いずれも「upscale model ready」の1〜1.5秒後で、
例外にならないためtry/exceptでは拾えず、logも1行も残らなかった。

``gpu_slot`` は実行を直列化するが、DLLの常駐は解かない。一度でも文字起こしが走った
processには載ったままなので、順番を空けても衝突は消えない。**同居させないことが唯一の
対処**である。

副次的に3つ直る: 子の死は親が終了codeとstderrで必ず観測できる(今までは無言で消えた) /
復号中の取り消しがkillで効く / job毎にVRAMが必ず解放される。model loadは実測3.6秒で、
1件あたりの復号(数分〜十数分)に対して1%未満なので、常駐させる必要はない。

== 親子の約束 ==

子の**標準出力はJSONLの制御channel専用**で、1行1 message:

    {"t": "progress", "done": 秒, "total": 秒}
    {"t": "result",   "result": {...}}          最後に1回だけ
    {"t": "error",    "message": "...", "stt": true}

logは標準errorへ出す(親が読み取ってserverのlogへ流す)。stdoutへlogを混ぜてはならない
— 制御channelが壊れて結果を読めなくなる。
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
from typing import Callable, Optional

from tictok.core import cancel
from tictok.core.gpu import gpu_slot
from tictok.record.transcription import STTError

logger = logging.getLogger("tictok.stt")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# 失敗時のerror本文に載せる子のlog行数。全部載せると数万行になり、逆に原因が埋もれる。
STDERR_TAIL_LINES = 40

# 実行中の子。Windowsは親が終わっても子を道連れにしないので、serverの停止時にここから
# 明示的に落とす。同じprocessで復号していた頃はprocessの終了がそのまま復号の終了だったが、
# 別processにした以上、GPUを掴んだままの孤児が残り得る。
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
            "stt worker: 子process %d 件を終了させました", len(targets),
            extra={"event": "stt.worker_terminated", "ctx": {"children": len(targets)}},
        )
    return len(targets)


def _drain_stderr(stream, tail: deque) -> None:
    """子のlogを読み続け、そのままserverのlogへ流す。

    読み続けること自体が必須である。stderrはpipe(既定64KB)で、親が読まないまま埋まると
    子は書き込みでblockし、復号が無言で止まる。"""
    for raw in stream:
        line = raw.rstrip("\r\n")
        if not line:
            continue
        tail.append(line)
        logger.info("[stt] %s", line)


def run_transcribe(path: str, on_progress: Optional[Callable] = None) -> dict:
    """``path`` を子processで文字起こしし、結果dictを返す。同期(呼び出し側はthreadへ)。

    GPU枠はここで押さえる。``gpu_slot`` はprocess内のsemaphoreなので、子で取っても他の
    jobとは噛み合わない — 枠を持つのは常に親側である。

    取り消しは子processのkillで効かせる。他のmedia jobと同じく ``cancel.register_process``
    へ預けるだけでよい — 復号はCTranslate2の中で回っており、python側に取り消しを見に行く
    余地は無いので、殺す以外に止める手段が無い。**登録し忘れると取り消しが黙って効かない**:
    APIは受け付けて `cancelling` を返すのに子は最後まで走り切り、画面には「取消中」が
    残り続ける(実測: 6時間16分の入力を96%まで回し切った)。枠待ちの前後でも取り消しを見る
    — GPUが埋まっている間の待機は数時間になり得るので、そこで受けた取り消しが枠を取った
    後の復号開始まで無視されると、止めたはずのjobが改めて走り出す。"""
    args = [sys.executable, "-u", "-m", "tictok.record.stt_worker", str(path)]
    tail: deque = deque(maxlen=STDERR_TAIL_LINES)
    cancel.check_cancelled()
    with gpu_slot("stt"):
        cancel.check_cancelled()
        proc = subprocess.Popen(
            args, cwd=str(PROJECT_ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", env=dict(os.environ),
        )
        cancel.register_process(proc)
        with _children_lock:
            _children.add(proc)
        reader = threading.Thread(target=_drain_stderr, args=(proc.stderr, tail),
                                  daemon=True, name="stt-worker-log")
        reader.start()
        result = None
        failure = None
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except ValueError:
                    # 制御channelに素のtextが出てきた = 約束が破れている。捨てずにlogへ
                    # 残す(黙って読み飛ばすと、結果が来ない理由が分からなくなる)。
                    logger.warning(
                        "stt workerがJSON以外の行をstdoutへ出力しました: %.200s", line,
                        extra={"event": "stt.worker_protocol_violation",
                               "ctx": {"line": line[:200]}},
                    )
                    continue
                kind = message.get("t")
                if kind == "progress":
                    if on_progress:
                        on_progress(message.get("done") or 0.0, message.get("total") or 0.0)
                elif kind == "result":
                    result = message.get("result")
                elif kind == "error":
                    failure = message
            code = proc.wait()
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            cancel.forget_process(proc)
            with _children_lock:
                _children.discard(proc)
            reader.join(timeout=5)

    # 取り消しで殺した子は、本物のcrashと同じ非0で返ってくる。先に取り消しを名乗らないと、
    # operator自身の取り消しが「文字起こしのprocessが異常終了しました」というerrorになり、
    # jobの状態も重大度も嘘になる(core.cancelの is_cancelled が置かれている理由と同じ)。
    cancel.check_cancelled()
    if failure is not None:
        raise STTError(failure.get("message") or "文字起こしに失敗しました。")
    if code != 0 or result is None:
        # 子が異常終了した。native crash(0xc0000409等)はpythonの例外にならないので、
        # ここが唯一の観測点になる。終了codeと直前のlogを必ず本文へ残すこと。
        detail = "\n".join(tail) or "(子processのlogはありません)"
        raise STTError(
            "文字起こしのprocessが異常終了しました(exit=%s)。直前のlog:\n%s" % (code, detail))
    return result


# ===== 子process側 =====


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main(argv: list) -> int:
    if len(argv) < 2:
        print("usage: python -m tictok.record.stt_worker <path>", file=sys.stderr)
        return 2
    # logは標準errorへ。親が読んでserverのlogへ流す(stdoutは制御channel専用)。
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(name)s %(message)s")
    from tictok.record.transcription import transcribe

    from tictok.core.progress import IntervalGate
    from tictok.core.config import get_job_progress_min_interval_seconds

    last_pct = -1
    # %が動かない間も再生位置は進む。Job画面はその位置を出すので(4時間の録画は1%が
    # 2.4分で、%だけでは動いているか分からない)、%据え置きの間も間隔ぶんは送る。
    # segment毎に全部送ると長時間録画で数千行になるため、間引きは残す。
    gate = IntervalGate(get_job_progress_min_interval_seconds())

    def on_progress(done: float, total: float) -> None:
        nonlocal last_pct
        pct = int(done / total * 100) if total > 0 else 0
        if pct == last_pct and not gate.ready():
            return
        last_pct = pct
        _emit({"t": "progress", "done": done, "total": total})

    try:
        result = transcribe(argv[1], on_progress)
    except STTError as exc:
        _emit({"t": "error", "message": str(exc), "stt": True})
        return 3
    except Exception as exc:  # noqa: BLE001 - 親へ理由を渡してから落ちる
        logging.getLogger("tictok.stt").exception("transcribe failed in worker")
        _emit({"t": "error", "message": "文字起こしに失敗しました: %s" % exc})
        return 4
    _emit({"t": "result", "result": result})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
