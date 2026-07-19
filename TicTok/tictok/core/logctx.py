"""Correlation context for logging.

Every diagnostic question about this app starts with "which streamer / which
session / which recording", so those three ids are carried out-of-band in
ContextVars and injected into every LogRecord rather than being repeated by hand
at each call site. HTTP/WS requests carry an independent request id.

Kept separate from logging_setup so that collector/recorder modules can set
correlation without importing the handler machinery.

ContextVar semantics that this design depends on: asyncio.create_task() copies
the context at creation time, so a value set before task creation is visible
inside the task, and a value set inside the task never leaks back to the parent.
asyncio.to_thread() copies the context too, so worker threads inherit it. A
long-lived thread started at import time (the storage batch writer, the gzip
compressor) inherits nothing and must attach correlation explicitly via
extra={"ctx": {...}}.
"""

from contextlib import contextmanager
from contextvars import ContextVar

ctx_unique_id: ContextVar = ContextVar("tictok_unique_id", default=None)
ctx_session_id: ContextVar = ContextVar("tictok_session_id", default=None)
ctx_recording_id: ContextVar = ContextVar("tictok_recording_id", default=None)
ctx_request_id: ContextVar = ContextVar("tictok_request_id", default=None)
# Long-running post-processing jobs (burn-in, upscale, transcription) run across
# sub-processes and worker threads. Binding one id for the job's duration is what
# joins its Layer1 log lines to the ops_events row recording the transition.
ctx_job_id: ContextVar = ContextVar("tictok_job_id", default=None)

_VARS = {
    "unique_id": ctx_unique_id,
    "session_id": ctx_session_id,
    "recording_id": ctx_recording_id,
    "request_id": ctx_request_id,
    "job_id": ctx_job_id,
}


@contextmanager
def log_context(**values):
    """Bind correlation ids for the duration of the block, restoring the previous
    values on exit. Resetting matters: a collector task runs many sessions in a
    loop, and a leaked session_id would misattribute the next session's logs.

    Passing a key explicitly as None binds None (i.e. clears it for the block);
    keys not passed are left untouched.
    """
    unknown = set(values) - set(_VARS)
    if unknown:
        raise ValueError(f"unknown correlation keys: {sorted(unknown)}")
    tokens = [(_VARS[key], _VARS[key].set(value)) for key, value in values.items()]
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


def current_context() -> dict:
    """Snapshot of the bound ids, omitting unset ones. Used when handing work to a
    thread that will not inherit the context, so it can re-attach correlation."""
    return {name: var.get() for name, var in _VARS.items() if var.get() is not None}
