"""Process-wide admission control for the GPU-bound media jobs.

STT decode, Up出力 (video super-resolution), the avatar super-resolution used by the
burn-in, and the burn-in's own NVENC encode all run on the same device and share one
CUDA context. Each of them already serialises *itself* with a private lock, but nothing
capped the total, so two burn-ins plus an Up出力 could sit on the GPU at once and only
slow each other down (or OOM). This module is that missing global cap.

The per-key locks elsewhere stay: they answer a different question ("is this exact output
already being rendered?") and this semaphore does not replace them.

Re-entrancy matters because the stages nest: the burn-in holds a slot for a whole variant
render, and the comment-layer thread inside it super-resolves avatars, which is another
GPU stage. A nested acquire would deadlock at the default limit of 1, so the holder is
tracked in a ContextVar and nested acquires within the same job are no-ops. The ContextVar
propagates into ``asyncio.to_thread`` workers and tasks created inside the held section,
which is exactly the boundary a single job crosses; a thread started outside the job gets
a fresh context and correctly queues for its own slot.
"""

import asyncio
import contextvars
import logging
import threading
import time
from contextlib import asynccontextmanager, contextmanager

from tictok.core import config

logger = logging.getLogger("tictok.gpu")

# Depth of the slot held by the current job. >0 means an enclosing stage of the same job
# already owns the slot, so this stage runs inside it instead of queueing behind itself.
_held = contextvars.ContextVar("tictok_gpu_slot_depth", default=0)

_semaphore: threading.Semaphore | None = None
_limit = 0
_init_lock = threading.Lock()
# Labels of the stages currently holding a slot, for the status endpoint / logs. Guarded
# by _state_lock; a counter of waiters rides along so a queued job is visible as queued
# rather than as "nothing happening".
_state_lock = threading.Lock()
_active: dict[int, str] = {}
_waiting = 0
_seq = 0


def _ensure_semaphore() -> threading.Semaphore:
    """Resolve the limit once per process. It is not re-read afterwards: changing the
    bound while slots are held cannot be done coherently, and the value is deployment
    configuration (env), not a per-run choice."""
    global _semaphore, _limit
    if _semaphore is not None:
        return _semaphore
    with _init_lock:
        if _semaphore is None:
            _limit = max(1, config.get_gpu_concurrency())
            _semaphore = threading.Semaphore(_limit)
            logger.info(
                "gpu admission control: %d concurrent job(s)", _limit,
                extra={"event": "gpu.limit_resolved", "ctx": {"limit": _limit}},
            )
    return _semaphore


def _acquire(label: str) -> int:
    """Block until a slot is free and return its handle. Returns 0 when the current job
    already holds one (nested stage), in which case no slot was taken."""
    global _waiting, _seq
    depth = _held.get()
    if depth > 0:
        _held.set(depth + 1)
        return 0
    sem = _ensure_semaphore()
    timeout = config.get_gpu_wait_timeout_seconds()
    waited = time.monotonic()
    with _state_lock:
        _waiting += 1
    try:
        acquired = sem.acquire(timeout=timeout) if timeout > 0 else sem.acquire()
    finally:
        with _state_lock:
            _waiting -= 1
    if not acquired:
        raise TimeoutError(
            f"GPU処理の順番待ちが上限({timeout:.0f}秒)を超えました: {label}"
        )
    waited = time.monotonic() - waited
    with _state_lock:
        _seq += 1
        handle = _seq
        _active[handle] = label
    _held.set(1)
    if waited >= 1.0:
        logger.info(
            "gpu slot acquired by %s after waiting %.1fs", label, waited,
            extra={"event": "gpu.slot_waited",
                   "ctx": {"label": label, "waited_seconds": round(waited, 1),
                           "limit": _limit}},
        )
    return handle


def _release(handle: int) -> None:
    if handle == 0:
        _held.set(max(0, _held.get() - 1))
        return
    with _state_lock:
        _active.pop(handle, None)
    _held.set(0)
    assert _semaphore is not None
    _semaphore.release()


@contextmanager
def gpu_slot(label: str):
    """Hold a GPU slot for the duration of the block (blocking; for worker threads)."""
    handle = _acquire(label)
    try:
        yield
    finally:
        _release(handle)


@asynccontextmanager
async def gpu_slot_async(label: str):
    """Hold a GPU slot without blocking the event loop. The wait itself happens on a
    worker thread; ``to_thread`` copies the context, so the depth marker set there would
    not reach the caller — the marker is therefore set here, on the caller's context."""
    depth = _held.get()
    if depth > 0:
        _held.set(depth + 1)
        try:
            yield
        finally:
            _held.set(max(0, _held.get() - 1))
        return
    handle = await asyncio.to_thread(_acquire_blocking_outer, label)
    _held.set(1)
    try:
        yield
    finally:
        _held.set(0)
        with _state_lock:
            _active.pop(handle, None)
        assert _semaphore is not None
        _semaphore.release()


def _acquire_blocking_outer(label: str) -> int:
    """``_acquire`` for the async wrapper: the worker thread starts from a copy of the
    caller's context, so its own ``_held.set`` is discarded when the thread ends. The
    caller sets the marker itself; this only does the blocking wait and bookkeeping."""
    return _acquire(label)


def gpu_status() -> dict:
    """Current admission state, for diagnostics: the configured cap, what is running and
    how many stages are queued behind it."""
    _ensure_semaphore()
    with _state_lock:
        return {
            "limit": _limit,
            "active": sorted(_active.values()),
            "waiting": _waiting,
        }
