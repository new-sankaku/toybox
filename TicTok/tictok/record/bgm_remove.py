"""出力からBGM・効果音・環境音を落とし、話し声だけを残す(BGM除去)。

親側の境界。実処理は :mod:`tictok.record.bgm_child` が**別venvのpython**で行う
(理由はそちらのdocstring)。ここが持つのは、成果物mp4の音声を差し替える手順である。

== 掛ける相手は「出来上がった成果物」であって原本ではない ==

原本(.ts)には掛けない。modelは**話し声以外を実測-22.2dB落とす**ので、消える対象は
BGMだけではない:

  - gift SE
  - battleの効果音・歓声
  - コラボ相手の声(マイクが遠ければ「話し声以外」の側に寄る)

battleのある録画に常時掛けるのは素材を壊す方向なので、**出力するときに選ぶ**形にする。
音量正規化(``clip_normalize_audio``)と同じ枠である。

== 切り出しの後で音声だけ差し替える ==

切り出しと同時に掛けない。stream copyの切り出しは要求より手前のkeyframeから始まるため、
「要求した窓」と「実際に出力された窓」が一致しない。別々に切った音声を後から重ねると、
その差だけ音がずれる。**出来上がったmp4そのものから音声を取り出して差し替える**なら、
窓は定義上ぴったり一致する。映像はstream copyのままなので、追加費用は音声だけである。

実測(RTX 4070 Ti, MossFormer2_SE_48K): 固定約5.5秒(process起動3秒 + model load 2.5秒)
＋ 尺÷18.8。60秒のclipで8.5〜9.9秒、10分で約45秒。VRAMは尺によらず0.25GB。

== 出力はmonoになる ==

modelがmonoしか受け取らないため。録画の左右chは実質同一(L-R差が本体より27.5dB下)で、
monoにしても落ちる情報は無い。
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
from collections import deque
from pathlib import Path
from typing import Optional

from tictok.core import cancel, config
from tictok.core.gpu import gpu_slot
from tictok.paths import PROJECT_ROOT
from tictok.record import audio_norm
from tictok.record.recorder import ffmpeg_ctx

logger = logging.getLogger("tictok.bgm")

CHILD_PATH = Path(__file__).resolve().parent / "bgm_child.py"
# modelが受け取る形。子側の検証と揃えること(片方だけ変えると子が入力を弾く)。
CHILD_RATE = 48000
STDERR_TAIL_LINES = 40

_children_lock = threading.Lock()
_children: set = set()


class BGMRemoveError(RuntimeError):
    """BGM除去の失敗。切り出し自体の失敗と区別するために別型にする。"""


def terminate_all() -> int:
    """実行中の子をすべて落とす。落とした数を返す(server停止時に呼ぶ)。"""
    with _children_lock:
        targets = list(_children)
    for proc in targets:
        if proc.poll() is None:
            proc.kill()
    if targets:
        logger.info(
            "BGM除去: 子process %d 件を終了させました", len(targets),
            extra={"event": "bgm.worker_terminated", "ctx": {"children": len(targets)}},
        )
    return len(targets)


def python_path() -> Optional[Path]:
    """BGM除去用venvのpython。未設定・不在ならNone(PROJECT_ROOT相対も受ける)。"""
    raw = config.get_bgm_remove_python()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path if path.is_file() else None


def unavailable_reason() -> Optional[str]:
    """使えない理由。使えるならNone。**投入時に確かめてから受け付けるために使う。**

    workerで初めて落とすと、押した人は待った末に理由を知ることになる。
    """
    if not config.get_bgm_remove_enabled():
        return ("BGM除去は無効です。.env の TICTOK_BGM_REMOVE_ENABLED=1 で有効にしてください。")
    if python_path() is None:
        return ("BGM除去用venvのpythonが見つかりません。"
                ".env の TICTOK_BGM_REMOVE_PYTHON に設定してください。")
    if not CHILD_PATH.is_file():
        return f"BGM除去の実行fileがありません: {CHILD_PATH}"
    return None


def describe(enabled: bool) -> dict:
    """logのctxへ入れる形。掛けていないことも明示的に残す。"""
    if not enabled:
        return {"bgm_removed": False}
    return {"bgm_removed": True, "bgm_model": config.get_bgm_remove_model(),
            "bgm_task": config.get_bgm_remove_task()}


def _drain_stderr(stream, tail: deque) -> None:
    """子のlogを読み続け、そのままserverのlogへ流す。

    読み続けること自体が必須である。stderrはpipe(既定64KB)で、親が読まないまま埋まると
    子は書き込みでblockし、処理が無言で止まる。"""
    for raw in stream:
        line = raw.rstrip("\r\n")
        if not line:
            continue
        tail.append(line)
        logger.info("[bgm] %s", line)


def _run_child(src: Path, dst: Path) -> dict:
    """子processでBGM除去を実行する。同期(呼び出し側はthreadへ)。

    GPU枠はここで押さえる。``gpu_slot`` はprocess内のsemaphoreなので、子で取っても他の
    jobとは噛み合わない — 枠を持つのは常に親側である。取り消しは子のkillで効かせるため、
    ``cancel.register_process`` へ必ず預ける(登録し忘れると取り消しが黙って効かない)。
    """
    interpreter = python_path()
    if interpreter is None:
        raise BGMRemoveError(unavailable_reason() or "BGM除去を実行できません。")
    args = [str(interpreter), "-u", str(CHILD_PATH), str(src), str(dst),
            "--model", config.get_bgm_remove_model(),
            "--task", config.get_bgm_remove_task(),
            "--device", config.get_bgm_remove_device()]
    tail: deque = deque(maxlen=STDERR_TAIL_LINES)
    cancel.check_cancelled()
    with gpu_slot("bgm"):
        cancel.check_cancelled()
        proc = subprocess.Popen(
            args, cwd=str(PROJECT_ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", env=dict(os.environ),
        )
        cancel.register_process(proc)
        with _children_lock:
            _children.add(proc)
        reader = threading.Thread(target=_drain_stderr, args=(proc.stderr, tail),
                                  daemon=True, name="bgm-worker-log")
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
                    logger.warning(
                        "BGM除去の子がJSON以外の行をstdoutへ出力しました: %.200s", line,
                        extra={"event": "bgm.worker_protocol_violation",
                               "ctx": {"line": line[:200]}},
                    )
                    continue
                if message.get("t") == "result":
                    result = message.get("result")
                elif message.get("t") == "error":
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

    # 取り消しで殺した子は本物のcrashと同じ非0で返る。先に取り消しを名乗らないと、
    # operator自身の取り消しが「異常終了」というerrorになり、重大度が嘘になる。
    cancel.check_cancelled()
    if failure is not None:
        raise BGMRemoveError(failure.get("message") or "BGM除去に失敗しました。")
    if code != 0 or result is None:
        detail = "\n".join(tail) or "(子processのlogはありません)"
        raise BGMRemoveError(
            "BGM除去のprocessが異常終了しました(exit=%s)。直前のlog:\n%s" % (code, detail))
    return result


def _run_ffmpeg(args: list, stage: str, media: Path) -> None:
    completed = subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if completed.returncode == 0:
        return
    stderr = completed.stderr.decode("utf-8", "replace")
    logger.error(
        "%s のBGM除去に失敗しました(%s)", media.name, stage,
        extra={"event": "bgm.ffmpeg_failed",
               "ctx": {"stage": stage, "path": str(media),
                       **ffmpeg_ctx(args, completed.returncode, stderr_text=stderr)}},
    )
    raise BGMRemoveError(f"BGM除去の{stage}に失敗しました: {stderr.strip()[:300]}")


def _apply(media: Path, normalize: Optional[dict]) -> dict:
    """``media`` の音声をBGM除去したものへ差し替える(同期)。

    映像はstream copyのまま触らない。音量正規化を併せて掛ける場合もここで1回だけ行う。
    先に切り出し側で正規化してからここで再encodeすると、AACを2世代重ねることになる。
    """
    reason = unavailable_reason()
    if reason:
        raise BGMRemoveError(reason)
    work = Path(tempfile.mkdtemp(prefix=".bgm_", dir=media.parent))
    try:
        raw = work / "in.wav"
        cleaned = work / "out.wav"
        replaced = work / f"out{media.suffix}"
        _run_ffmpeg(["ffmpeg", "-v", "error", "-y", "-i", str(media), "-vn",
                     "-ac", "1", "-ar", str(CHILD_RATE), "-c:a", "pcm_s16le", str(raw)],
                    "音声の取り出し", media)
        detail = _run_child(raw, cleaned)
        if normalize:
            audio_args = ["-c:a", "aac", "-b:a", f"{int(normalize['bitrate_kbps'])}k",
                          "-af", audio_norm.audio_filter(normalize["target_lufs"],
                                                         normalize["true_peak"]),
                          "-ar", str(CHILD_RATE)]
        else:
            audio_args = ["-c:a", "aac", "-ar", str(CHILD_RATE)]
        # 映像は0番の入力から名指しでcopyし、音声は1番の入力だけを採る。-shortestは付けない
        # (音声は入力と同じsample数に揃えてあり、短い方に合わせて映像を切る理由が無い)。
        _run_ffmpeg(["ffmpeg", "-v", "error", "-y", "-i", str(media), "-i", str(cleaned),
                     "-map", "0:v:0", "-c:v", "copy", "-map", "1:a:0", *audio_args,
                     "-movflags", "+faststart", str(replaced)],
                    "音声の差し替え", media)
        if not replaced.is_file() or replaced.stat().st_size <= 0:
            raise BGMRemoveError("BGM除去は成功しましたが出力fileがありません。")
        replaced.replace(media)
    finally:
        for leftover in work.glob("*"):
            leftover.unlink(missing_ok=True)
        work.rmdir()
    return detail


async def apply_to(media: Path, normalize: Optional[dict] = None) -> dict:
    """成果物mp4の音声をBGM除去したものへ差し替える。

    ``normalize`` を渡すと、差し替えと同じencodeで音量正規化も済ませる。
    """
    return await asyncio.to_thread(_apply, media, normalize)


if __name__ == "__main__":  # 手元確認用(server経由と同じ経路を通す)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(name)s %(message)s")
    if len(sys.argv) < 2:
        print("usage: python -m tictok.record.bgm_remove <mp4>", file=sys.stderr)
        raise SystemExit(2)
    print(json.dumps(_apply(Path(sys.argv[1]), None), ensure_ascii=False))
