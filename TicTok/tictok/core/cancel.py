"""Cooperative cancellation for the long-running media jobs.

A burn-in or an Up出力 runs for hours across an asyncio task, worker threads and several
ffmpeg sub-processes. ``Task.cancel()`` alone reaches none of that: the thread keeps
looping, and an ffmpeg awaited through ``proc.wait()`` is orphaned rather than stopped.
A token is therefore carried alongside the job and consulted at the two places that
actually spend the time — the per-frame loops — while every sub-process the job spawns
registers itself so the token can kill it directly.

``JobCancelled`` derives from ``BaseException`` on purpose, for the same reason
``asyncio.CancelledError`` does: the render paths wrap their frame loops in broad
``except Exception`` handlers that degrade to a lesser output (the burn-in falls back to
the ASS layer that way). A cancellation caught there would silently become a *worse
render* instead of a stop, which is the one outcome an operator pressing cancel must
never get.

The active token lives in a ContextVar, so it reaches ``asyncio.to_thread`` workers and
tasks created inside the job exactly like the GPU slot marker does (see core.gpu), and
code outside any job simply sees ``None`` and does nothing.
"""

import contextvars
import logging
import threading
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger("tictok.cancel")


class JobCancelled(BaseException):
    """Raised inside a job whose token was cancelled."""

    def __init__(self, job_id: str) -> None:
        super().__init__(f"job {job_id} cancelled")
        self.job_id = job_id


class CancelToken:
    """One job's cancel switch, plus the sub-processes to kill when it is thrown."""

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        self._cancelled = False
        self._lock = threading.Lock()
        self._processes: list = []

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        with self._lock:
            if self._cancelled:
                return
            self._cancelled = True
            processes = list(self._processes)
        logger.info(
            "job %s の取り消しを受け付けました（停止するprocess %d 件）",
            self.job_id, len(processes),
            extra={"event": "job.cancel_requested",
                   "ctx": {"job_id": self.job_id, "processes": len(processes)}},
        )
        for process in processes:
            _kill(process, self.job_id)

    def register_process(self, process) -> None:
        """Attach a running sub-process. Registering after the cancel already fired kills
        it right away — otherwise a process spawned in that window would run to
        completion with nobody left to stop it."""
        with self._lock:
            if self._cancelled:
                fire = True
            else:
                self._processes.append(process)
                fire = False
        if fire:
            _kill(process, self.job_id)

    def forget_process(self, process) -> None:
        with self._lock:
            if process in self._processes:
                self._processes.remove(process)

    def check(self) -> None:
        if self._cancelled:
            raise JobCancelled(self.job_id)


def _kill(process, job_id: str) -> None:
    """Kill (not terminate) a registered sub-process: ffmpeg exits on SIGTERM only after
    flushing, and on Windows there is no SIGTERM at all, so the partial output would
    outlive the cancel. Every caller unlinks its own partial file when the process
    reports a non-zero exit, which is what a kill produces."""
    try:
        if process.returncode is None:
            process.kill()
    except (OSError, ValueError, ProcessLookupError):
        logger.debug(
            "job %s の子processを終了できませんでした", job_id, exc_info=True,
            extra={"event": "job.cancel_kill_failed", "ctx": {"job_id": job_id}},
        )


_current: contextvars.ContextVar[Optional[CancelToken]] = contextvars.ContextVar(
    "tictok_cancel_token", default=None,
)


@contextmanager
def token_scope(token: CancelToken):
    """Make ``token`` the active one for the duration of the block."""
    reset = _current.set(token)
    try:
        yield token
    finally:
        _current.reset(reset)


def current_token() -> Optional[CancelToken]:
    return _current.get()


def check_cancelled() -> None:
    """Raise if the job running here was cancelled. A no-op outside a job."""
    token = _current.get()
    if token is not None:
        token.check()


def is_cancelled() -> bool:
    """Whether this job was already cancelled, without raising.

    A killed sub-process reports a non-zero exit exactly like a genuine ffmpeg failure
    does, so every ``returncode`` check has to ask this first: otherwise the operator's
    own cancel lands as an ffmpeg error (wrong state, wrong message, an error-severity
    ops_event). Callers unlink their partial output and then raise via
    ``check_cancelled()``. False outside a job."""
    token = _current.get()
    return token is not None and token.cancelled


def register_process(process) -> None:
    """Let the active job's cancel kill this sub-process. A no-op outside a job."""
    token = _current.get()
    if token is not None:
        token.register_process(process)


def forget_process(process) -> None:
    token = _current.get()
    if token is not None:
        token.forget_process(process)
