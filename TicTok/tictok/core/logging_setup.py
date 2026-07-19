"""Central logging setup: rotating text log, machine-readable JSONL log, gzip
compression of rotated files, correlation-id injection, and duplicate storm
suppression.

Why this exists as a module rather than a basicConfig call in server.main():
logging must be live before tictok.server creates its module-level Storage, because
the single-instance lock failure, the journal recovery result and the schema
migration all happen at import time. Configured later, those lines never reach the
log file at all.

Two output streams are written from one logger tree:
  - text  : logs/<name>.log     human reading and grep
  - JSONL : logs/<name>.jsonl   one JSON object per line for machine analysis

Both are produced from the same LogRecord, so they never disagree. Structured
fields are attached with extra={"event": "<domain>.<subject>_<verb>", "ctx": {...}}
and land in the JSONL stream; the text stream stays readable prose.

Formatting and file writes happen on a QueueListener thread, so a log call on the
asyncio event loop costs a filter evaluation plus a queue put. Rotation and gzip
therefore never stall event ingestion or the recording watchdogs.
"""

import atexit
import gzip
import json
import logging
import os
import queue
import shutil
import threading
import time
import traceback
from datetime import datetime
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
from pathlib import Path

from tictok.core import config
from tictok.core.logctx import (
    ctx_job_id,
    ctx_recording_id,
    ctx_request_id,
    ctx_session_id,
    ctx_unique_id,
)

_configured = False
_listener = None
_dedup_filter = None
_lock = threading.Lock()


# ---------------------------------------------------------------- compression

class _CompressWorker:
    """Single daemon thread that gzips rotated files off the caller's thread.

    A single worker rather than a pool: compression order is preserved and CPU use
    stays bounded to one core during an error storm, when rotations come fast.
    Renaming stays synchronous in the caller (it must free the base path at once);
    only the gzip is deferred.
    """

    def __init__(self) -> None:
        self._queue: queue.SimpleQueue = queue.SimpleQueue()
        self._thread = None

    def _ensure_thread(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run, name="tictok-log-compress", daemon=True
        )
        self._thread.start()

    def submit(self, path: Path, level: int) -> None:
        self._ensure_thread()
        self._queue.put((path, level))

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            path, level = item
            try:
                self._compress(path, level)
            except Exception:
                # Never take the process down over a log-housekeeping failure, but
                # never hide it either: the uncompressed file stays on disk and the
                # reason is reported through the normal logger.
                logging.getLogger("tictok.logging").exception(
                    "log compression failed; leaving plain file (path=%s)", path
                )

    def _compress(self, path: Path, level: int) -> None:
        if not path.exists():
            return
        target = path.with_suffix(path.suffix + ".gz")
        with path.open("rb") as src, gzip.open(target, "wb", compresslevel=level) as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
        # Unlink only after the .gz is closed and present, so an interrupted run
        # loses nothing.
        if target.exists() and target.stat().st_size > 0:
            path.unlink()

    def drain(self, timeout: float) -> None:
        if self._thread is None or not self._thread.is_alive():
            return
        self._queue.put(None)
        self._thread.join(timeout=timeout)


_compressor = _CompressWorker()


def compress_async(path) -> None:
    """Queue a closed file for gzip compression on the shared worker.

    Public because the battle raw-event capture writes its own files and needs the
    same off-thread compression when a session closes.
    """
    if not config.get_log_compress():
        return
    _compressor.submit(Path(path), config.get_log_compress_level())


# ------------------------------------------------------------------- rotation

def _retry_replace(source: str, dest: str, attempts: int, delay: float) -> None:
    """Rename with retries for Windows, where a virus scanner or search indexer can
    hold a transient handle on the file just closed. Raises on the final attempt:
    a rename that never succeeds must surface, not be swallowed."""
    for attempt in range(attempts):
        try:
            os.replace(source, dest)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def _prune_old_logs(base: Path, days: int) -> None:
    """Delete rotated files older than `days`. 0 disables pruning entirely, which is
    the default: logs are diagnostic assets and deletion is irreversible."""
    if days <= 0:
        return
    cutoff = time.time() - days * 86400
    pattern = f"{base.stem}-*{base.suffix}*"
    for path in base.parent.glob(pattern):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            logging.getLogger("tictok.logging").exception(
                "failed to prune rotated log (path=%s)", path
            )


class GzipRotatingFileHandler(RotatingFileHandler):
    """Size-based rotation to timestamped names, with gzip applied off-thread.

    doRollover is replaced rather than only setting rotator/namer, because the
    stdlib implementation shifts .1 -> .2 -> .3 and prunes by that numbering. With
    timestamped names there is nothing to shift, so the inherited implementation
    would neither rotate nor prune correctly.

    The timestamp is the rotation moment, i.e. the time of the file's last record,
    which is what "when did the incident happen" searches by. The first record's
    time is the first line of the file itself.
    """

    def __init__(self, filename, *, max_bytes: int, retention_days: int,
                 compress: bool, compress_level: int, **kwargs) -> None:
        super().__init__(filename, maxBytes=max_bytes, backupCount=1, **kwargs)
        self._retention_days = retention_days
        self._compress = compress
        self._compress_level = compress_level
        self.namer = self._name_rotated
        self.rotator = self._rotate

    def _name_rotated(self, _default_name: str) -> str:
        base = Path(self.baseFilename)
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
        candidate = base.with_name(f"{base.stem}-{stamp}{base.suffix}")
        # Two rotations inside the same second (possible during a storm) must not
        # collide and silently overwrite the earlier one.
        counter = 1
        while candidate.exists() or candidate.with_suffix(candidate.suffix + ".gz").exists():
            candidate = base.with_name(f"{base.stem}-{stamp}.{counter}{base.suffix}")
            counter += 1
        return str(candidate)

    def _rotate(self, source: str, dest: str) -> None:
        _retry_replace(
            source, dest,
            config.get_log_rotate_retry_attempts(),
            config.get_log_rotate_retry_delay_seconds(),
        )
        if self._compress:
            _compressor.submit(Path(dest), self._compress_level)

    def doRollover(self) -> None:
        if self.stream:
            self.stream.close()
            self.stream = None
        self.rotate(self.baseFilename, self.rotation_filename(self.baseFilename))
        self.stream = self._open()
        _prune_old_logs(Path(self.baseFilename), self._retention_days)


# ------------------------------------------------------------------- filtering

class StructuredQueueHandler(QueueHandler):
    """QueueHandler that hands the record to the listener intact.

    The stdlib implementation formats the record in prepare(), then clears args,
    exc_info and exc_text so the result can cross a process boundary. That is fatal
    here: the JSONL formatter would lose every structured exception and every
    argument template, leaving the machine stream with no stack traces at all.

    The queue is in-process, so no pickling is required and the record can be
    passed through unchanged. The consequence is that formatting is deferred to the
    listener thread, so a mutable object passed as a log argument must not be
    mutated after the call.
    """

    def prepare(self, record: logging.LogRecord) -> logging.LogRecord:
        return record


class CorrelationFilter(logging.Filter):
    """Inject the bound correlation ids into every record.

    Must be attached on the producer side (the QueueHandler), not to the listener's
    handlers: the listener runs on its own thread and does not inherit the
    ContextVars, so ids resolved there would always be None.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.unique_id = ctx_unique_id.get()
        record.session_id = ctx_session_id.get()
        record.recording_id = ctx_recording_id.get()
        record.request_id = ctx_request_id.get()
        record.job_id = ctx_job_id.get()
        return True


class DuplicateSuppressFilter(logging.Filter):
    """Collapse a repeating identical record into one line plus a repeat count.

    A single failing row once produced 47,827 identical FK tracebacks in one hour,
    which pushed every other line out of the retained window. Suppression keeps the
    first occurrence and reports the count, so nothing is hidden - only repeated.

    The fingerprint includes correlation ids: the same error for two different
    streamers is two facts, and folding them together would make a single-streamer
    problem indistinguishable from a global one. It uses the exception type and
    line number rather than a formatted traceback, because this runs on the event
    loop thread and must stay O(1).
    """

    def __init__(self, window_seconds: int, max_tracked: int) -> None:
        super().__init__()
        self._window = window_seconds
        self._max_tracked = max_tracked
        self._state: dict = {}
        self._state_lock = threading.Lock()

    def _fingerprint(self, record: logging.LogRecord):
        exc_type = record.exc_info[0].__name__ if record.exc_info and record.exc_info[0] else None
        # The fully formatted message, not the template: "boom %d" called with 500
        # distinct values is 500 distinct facts, and folding them by template would
        # discard 499 of them. A real storm repeats the formatted text verbatim and
        # still collapses.
        return (
            record.name,
            record.levelno,
            record.getMessage(),
            record.lineno,
            exc_type,
            getattr(record, "unique_id", None),
            getattr(record, "session_id", None),
        )

    def filter(self, record: logging.LogRecord) -> bool:
        if self._window <= 0:
            return True
        # DEBUG is opt-in and exists to show the sequence of what happened. Folding
        # it by identical text would collapse a per-event trace to one line per
        # distinct message, which is the opposite of what turning DEBUG on is for.
        if record.levelno <= logging.DEBUG:
            return True
        # One decision per record, not per handler. Without this the text handler
        # registers the fingerprint and the JSONL and console handlers then see a
        # duplicate and drop the record, emptying both streams.
        decided = getattr(record, "_dedup_pass", None)
        if decided is not None:
            return decided
        key = self._fingerprint(record)
        now = time.monotonic()
        with self._state_lock:
            entry = self._state.get(key)
            if entry is None:
                if len(self._state) >= self._max_tracked:
                    self._evict_locked(now)
                self._state[key] = [now, 0]
                record._dedup_pass = True
                return True
            started, count = entry
            if now - started < self._window:
                entry[1] = count + 1
                record._dedup_pass = False
                return False
            self._state[key] = [now, 0]
        if count:
            record.repeated = count
            record.repeated_window_seconds = self._window
        record._dedup_pass = True
        return True

    def _evict_locked(self, now: float) -> None:
        """Drop entries whose window has closed. Bounds memory when the fingerprint
        space is large (many distinct streamers over a long run)."""
        expired = [k for k, v in self._state.items() if now - v[0] >= self._window]
        for key in expired:
            del self._state[key]
        if len(self._state) >= self._max_tracked:
            oldest = sorted(self._state.items(), key=lambda kv: kv[1][0])
            for key, _ in oldest[: len(oldest) // 2]:
                del self._state[key]

    def pending_summaries(self) -> list:
        """Records suppressed but never followed by a repeat, reported at shutdown so
        the counts are not lost when a storm ends with the process."""
        with self._state_lock:
            items = [(key, entry[1]) for key, entry in self._state.items() if entry[1]]
            self._state.clear()
        return items


# ------------------------------------------------------------------ formatting

_TEXT_FORMAT = "%(asctime)s %(levelname)s %(name)s%(correlation)s %(message)s"

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "asctime", "message", "correlation", "event", "ctx", "repeated",
    "repeated_window_seconds", "unique_id", "session_id", "recording_id", "request_id",
    "job_id", "_dedup_pass",
}


def _correlation_pairs(record: logging.LogRecord) -> list:
    pairs = []
    for label, attr in (("uid", "unique_id"), ("sid", "session_id"),
                        ("rid", "recording_id"), ("req", "request_id"),
                        ("job", "job_id")):
        value = getattr(record, attr, None)
        if value is not None:
            pairs.append((label, value))
    return pairs


class TextFormatter(logging.Formatter):
    """Human-readable line. Correlation ids appear as explicit key=value pairs and
    only when bound, so a line is never padded with placeholder dashes."""

    def format(self, record: logging.LogRecord) -> str:
        pairs = _correlation_pairs(record)
        record.correlation = (
            " [" + " ".join(f"{k}={v}" for k, v in pairs) + "]" if pairs else ""
        )
        line = super().format(record)
        repeated = getattr(record, "repeated", 0)
        if repeated:
            line += (
                f" (repeated {repeated} more times in the previous "
                f"{getattr(record, 'repeated_window_seconds', 0)}s)"
            )
        return line


class JsonlFormatter(logging.Formatter):
    """One JSON object per record.

    Field width is deliberately restrained: source location and process/thread ids
    are carried only for WARNING and above or when an exception is attached, since
    that is when they are needed and INFO volume dominates the file size.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": datetime.fromtimestamp(record.created).isoformat(timespec="milliseconds"),
            "ts": round(record.created, 3),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        event = getattr(record, "event", None)
        if event:
            payload["event"] = event
        for label, value in _correlation_pairs(record):
            payload[label] = value

        ctx = getattr(record, "ctx", None)
        if ctx:
            payload["ctx"] = ctx
        # Anything passed via extra= outside the documented keys still reaches the
        # machine stream rather than being silently dropped.
        stray = {k: v for k, v in record.__dict__.items() if k not in _RESERVED}
        if stray:
            payload.setdefault("ctx", {}).update(stray)

        if record.args:
            payload["tmpl"] = str(record.msg)
        repeated = getattr(record, "repeated", 0)
        if repeated:
            payload["repeated"] = repeated
            payload["repeated_window_seconds"] = getattr(record, "repeated_window_seconds", 0)

        detailed = record.levelno >= logging.WARNING or record.exc_info
        if detailed:
            payload["src"] = {
                "mod": record.module,
                "func": record.funcName,
                "line": record.lineno,
            }
            payload["pid"] = record.process
            payload["thread"] = record.threadName
        if record.exc_info and record.exc_info[0]:
            payload["exc"] = {
                "type": record.exc_info[0].__name__,
                "msg": str(record.exc_info[1]),
                "stack": "".join(traceback.format_exception(*record.exc_info)),
            }
        return json.dumps(payload, ensure_ascii=False, default=str)


# ----------------------------------------------------------------------- setup

def _resolve_level(explicit: str, fallback: str) -> int:
    name = (explicit or fallback or "INFO").upper()
    level = logging.getLevelName(name)
    if not isinstance(level, int):
        raise ValueError(f"invalid log level: {name}")
    return level


def _apply_quiet_loggers(root_level: int) -> None:
    """Raise the floor on chatty third-party loggers.

    Skipped entirely when running at DEBUG: asking for DEBUG means asking to see
    the HTTP client's own traffic, and silencing it there would make DEBUG less
    informative than INFO in exactly the cases it is turned on for.
    """
    if root_level <= logging.DEBUG:
        return
    for item in config.get_log_quiet_loggers().split(","):
        item = item.strip()
        if not item or "=" not in item:
            continue
        name, _, level_name = item.partition("=")
        logging.getLogger(name.strip()).setLevel(_resolve_level(level_name.strip(), "WARNING"))


def _build_file_handler(path: Path, formatter: logging.Formatter, level: int):
    handler = GzipRotatingFileHandler(
        str(path),
        max_bytes=config.get_log_max_bytes(),
        retention_days=config.get_log_retention_days(),
        compress=config.get_log_compress(),
        compress_level=config.get_log_compress_level(),
        encoding="utf-8",
        errors="backslashreplace",
    )
    handler.setFormatter(formatter)
    handler.setLevel(level)
    return handler


def setup_logging(*, profile: str = "server", name: str = "tictok",
                  console: bool = True, level: str = "") -> None:
    """Configure the root logger. Idempotent: a second call is a no-op, so a script
    that imports server modules does not stack duplicate handlers.

    profile "server" writes logs/<name>.log; profile "script" writes
    logs/scripts/<name>-<pid>.log. Maintenance scripts get their own files because
    two processes rotating the same file race on Windows, where renaming a file
    another process holds open fails.
    """
    global _configured, _listener, _dedup_filter
    with _lock:
        if _configured:
            return

        root_level = _resolve_level(level, config.get_log_level())
        log_dir = Path(config.get_log_dir())
        if profile == "script":
            log_dir = log_dir / "scripts"
            stem = f"{name}-{os.getpid()}"
        else:
            stem = name
        log_dir.mkdir(parents=True, exist_ok=True)

        handlers = [
            _build_file_handler(log_dir / f"{stem}.log", TextFormatter(_TEXT_FORMAT), root_level)
        ]
        if config.get_log_jsonl_enabled():
            jsonl_level = _resolve_level(config.get_log_jsonl_level(), config.get_log_level())
            handlers.append(
                _build_file_handler(log_dir / f"{stem}.jsonl", JsonlFormatter(), jsonl_level)
            )
        if console:
            stream = logging.StreamHandler()
            stream.setFormatter(TextFormatter(_TEXT_FORMAT))
            stream.setLevel(_resolve_level(config.get_log_console_level(), config.get_log_level()))
            handlers.append(stream)

        root = logging.getLogger()
        root.setLevel(root_level)
        for existing in list(root.handlers):
            root.removeHandler(existing)

        _dedup_filter = DuplicateSuppressFilter(
            config.get_log_dedup_window_seconds(),
            config.get_log_dedup_max_tracked(),
        )

        if config.get_log_queue_enabled():
            # Unbounded queue on purpose: a bounded queue drops records under load,
            # which is a silent hole in exactly the situation being diagnosed.
            record_queue: queue.SimpleQueue = queue.SimpleQueue()
            producer = StructuredQueueHandler(record_queue)
            producer.addFilter(CorrelationFilter())
            producer.addFilter(_dedup_filter)
            root.addHandler(producer)
            _listener = QueueListener(record_queue, *handlers, respect_handler_level=True)
            _listener.start()
        else:
            for handler in handlers:
                handler.addFilter(CorrelationFilter())
                handler.addFilter(_dedup_filter)
                root.addHandler(handler)

        _apply_quiet_loggers(root_level)
        _configured = True
        atexit.register(shutdown_logging)

    logging.getLogger("tictok.logging").info(
        "logging started",
        extra={
            "event": "logging.started",
            "ctx": {
                "profile": profile,
                "level": logging.getLevelName(root_level),
                "dir": str(log_dir),
                "jsonl": config.get_log_jsonl_enabled(),
                "queue": config.get_log_queue_enabled(),
                "compress": config.get_log_compress(),
                "max_bytes": config.get_log_max_bytes(),
                "retention_days": config.get_log_retention_days(),
            },
        },
    )


def shutdown_logging() -> None:
    """Stop the listener and drain the compressor.

    Without this the queued tail of records is lost on exit, and a gzip in flight
    leaves a partial file. Registered with atexit by setup_logging.
    """
    global _configured, _listener
    with _lock:
        if not _configured:
            return
        _configured = False
        listener, _listener = _listener, None

    logger = logging.getLogger("tictok.logging")
    if _dedup_filter is not None:
        for key, count in _dedup_filter.pending_summaries():
            logger.warning(
                "suppressed %d repeats of %s at exit (logger=%s line=%s)",
                count, key[2], key[0], key[3],
                extra={"event": "logging.suppressed_flushed",
                       "ctx": {"count": count, "logger": key[0], "line": key[3]}},
            )
    if listener is not None:
        listener.stop()
    _compressor.drain(config.get_log_shutdown_drain_seconds())


# ------------------------------------------------------------------- utilities

def is_debug_enabled() -> bool:
    return logging.getLogger().isEnabledFor(logging.DEBUG)


def progress_interval_seconds(configured: float) -> float:
    """Interval for periodic progress lines, collapsed to 0 (every tick) at DEBUG.

    Threshold- and interval-gated logs are otherwise invisible to the log level,
    which is why raising the level previously produced almost no extra detail.
    """
    return 0.0 if is_debug_enabled() else configured
