"""前回の実行が残した捕捉ffmpegを、次の起動で始末する。

serverがきれいに終われば、捕捉ffmpegはrecorderの ``_terminate`` が止める。だがserverが
その後始末を通らずに死ぬ経路がある(hard kill・コンソールのCLOSE・native crash)。**Windowsは
親の終了で子を道連れにしない**ので、そのffmpegは生き残り、録画行の主が居なくなった
session dirへ書き続ける。

実測(2026-08-02): serverのコンソールにCTRLイベントが届いてprocess groupごと落ちた際、
捕捉ffmpegだけが同じdirへ書き続けた。過去ぶんを数えると直近60件中7件が同じ状態で、孤児が
書いた素材は 12.9 GB。録画00425は録画行が **12.0秒** で確定しているのに、dirには
**16,861.8秒** ぶんが積まれていた。

これは容量の話だけでは済まない。再生playlist(``files._finalized_playlist``)はdirの採用集合
から描き直すので、**playerが再生する尺と録画行の尺が別物になる**。転写・切り出し・軸の
一致判定はいずれも素材を読むため、録画の尺を信じている側が全部ずれる。

== なぜ起動時に始末するのか ==

孤児を作らせない方法は無い(強制終了は定義上、後始末を通らない)。作られた孤児を**次の起動が
必ず回収する**ことだけが確実な対処になる。回収は「中断した録画の復旧」より**先**に行う:
復旧は素材を見て録画を確定させるので、まだ書き続けている孤児が居ると、確定した尺が直後から
嘘になる。

== pidだけでは足りない ==

pidは再利用される。停止したffmpegのpidを別のprocessが引き継いだ後にkillすれば、無関係な
processを殺すことになる。そこでpidと**そのprocessの作成時刻**を対で記録し、両方一致した
ときだけ止める。作成時刻はWindows(GetProcessTimes)とLinux(/proc/<pid>/stat)で取れる。
取れない環境では**何もしない** — 身元を確かめられない相手をkillしないことのほうが、孤児を
1つ残すことより重要である。
"""
import json
import logging
import os
import signal
from pathlib import Path

from tictok.core import layout
from tictok.core.process_lock import _pid_alive

logger = logging.getLogger("tictok.orphan_capture")

# session dirへ置く捕捉processの身元。録画実体のglob(seg*.ts / pack*.ts)にも
# capture indexにも当たらない名前にする。
CAPTURE_MARK_NAME = "capture.pid"


def process_identity(pid: int):
    """``pid`` のprocessの作成時刻(識別用の文字列)。取れなければNone。

    pidの再利用を見破るためだけに使う。値そのものに意味は無く、記録時と一致するかだけを見る。"""
    if not pid or pid <= 0:
        return None
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return None
        try:
            created = wintypes.FILETIME()
            exited = wintypes.FILETIME()
            kernel = wintypes.FILETIME()
            user = wintypes.FILETIME()
            ok = kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                          ctypes.byref(kernel), ctypes.byref(user))
            if not ok:
                return None
            return "%d:%d" % (created.dwHighDateTime, created.dwLowDateTime)
        finally:
            kernel32.CloseHandle(handle)
    try:
        stat = Path("/proc/%d/stat" % pid).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    # comm は空白も括弧も含み得るので、最後の ')' より後ろだけを分割する。
    tail = stat.rpartition(")")[2].split()
    # starttime は stat の 22 番目のfield = ')' の後ろから数えて 20 番目(0起点で19)。
    if len(tail) < 20:
        return None
    return tail[19]


def mark(hls_dir, pid: int) -> None:
    """``hls_dir`` へ捕捉processの身元を書く。失敗しても録画は続ける。

    書けなかった場合に録画を止める理由は無い — 失うのは「次の起動が孤児を回収できる」と
    いう保険であって、録画そのものではない。"""
    identity = process_identity(pid)
    path = Path(hls_dir) / CAPTURE_MARK_NAME
    try:
        path.write_text(json.dumps({"pid": pid, "identity": identity}), encoding="utf-8")
    except OSError:
        logger.warning(
            "捕捉processの身元を %s へ書けませんでした（孤児の自動回収が効かなくなります）",
            path, exc_info=True,
            extra={"event": "capture.mark_failed", "ctx": {"path": str(path), "pid": pid}},
        )


def clear(hls_dir) -> None:
    """捕捉が止まったdirの身元を消す。止まった相手を次の起動が探しに行かないようにする。"""
    try:
        (Path(hls_dir) / CAPTURE_MARK_NAME).unlink(missing_ok=True)
    except OSError:
        logger.debug("捕捉processの身元を消せませんでした: %s", hls_dir, exc_info=True)


def _read_mark(path: Path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None
    if not isinstance(data, dict):
        return None, None
    pid = data.get("pid")
    return (pid if isinstance(pid, int) else None), data.get("identity")


def sweep(roots) -> dict:
    """record root群を走査し、前回の実行が残した捕捉ffmpegを止める。

    ``(見つけた数, 止めた数, 身元を確かめられず見送った数)`` を返す。**起動時に、中断録画の復旧より
    先に呼ぶこと。**

    止めるのは「pidが生きていて、記録した作成時刻と一致する」ものだけ。身元が確かめられない
    ものには触れず、目印だけ消す(消さないと毎起動で同じ判断を繰り返す)。"""
    found = killed = mismatched = 0
    for root in roots:
        for session in layout.iter_sessions(root):
            path = session / CAPTURE_MARK_NAME
            if not path.is_file():
                continue
            found += 1
            pid, identity = _read_mark(path)
            alive = _pid_alive(pid) if pid else False
            current = process_identity(pid) if alive else None
            if not alive or identity is None or current is None or current != identity:
                if alive:
                    mismatched += 1
                    logger.warning(
                        "%s の捕捉process pid=%s は身元を確かめられないため触れません"
                        "（記録=%s 現在=%s）", session.name, pid, identity, current,
                        extra={"event": "capture.orphan_identity_unverified",
                               "ctx": {"session": str(session), "pid": pid,
                                       "recorded": identity, "current": current}},
                    )
                clear(session)
                continue
            try:
                os.kill(pid, signal.SIGTERM if os.name == "nt" else signal.SIGKILL)
            except OSError:
                logger.warning(
                    "%s の孤児となった捕捉process pid=%s を止められませんでした",
                    session.name, pid, exc_info=True,
                    extra={"event": "capture.orphan_kill_failed",
                           "ctx": {"session": str(session), "pid": pid}},
                )
                clear(session)
                continue
            killed += 1
            logger.warning(
                "前回の実行が残した捕捉process pid=%s を止めました（%s）", pid, session.name,
                extra={"event": "capture.orphan_killed",
                       "ctx": {"session": str(session), "pid": pid}},
            )
            clear(session)
    if found:
        logger.info(
            "前回の捕捉processを回収しました: 見つけた %d 件 / 止めた %d 件 / 身元違い %d 件",
            found, killed, mismatched,
            extra={"event": "capture.orphan_sweep",
                   "ctx": {"found": found, "killed": killed, "mismatched": mismatched}},
        )
    return {"found": found, "killed": killed, "mismatched": mismatched}
