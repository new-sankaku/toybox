"""Single-instance guard scoped to the database file.

Two TicTok server processes pointed at the same database collect the same rooms
concurrently, saving each physical battle twice (see doc/BUG_CHECKLIST.md). The
collection invariant is "one collector process per database", which a per-process
manager cannot enforce on its own. This lock makes a second process abort at
startup. It is an exclusive lock file holding the owner PID; a leftover lock from
a crashed process is reclaimed once its PID is found dead, so a hard kill does not
wedge the next start. Works on Windows and POSIX.
"""

import json
import logging
import os
import time

logger = logging.getLogger("tictok.lock")


class ProcessLockError(RuntimeError):
    """Raised when the lock is already held by another live process."""


def _pid_alive(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        ERROR_ACCESS_DENIED = 5
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            # Access denied means the PID exists under another user/integrity
            # level — a live holder, same as the POSIX PermissionError branch.
            return ctypes.get_last_error() == ERROR_ACCESS_DENIED
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                # Can't read the exit code, so assume the process is alive rather
                # than risk stealing a lock from a running instance.
                return True
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists but owned by another user — still a live holder.
        return True
    return True


class ProcessLock:
    """Exclusive, PID-stamped lock file with stale-owner reclamation."""

    def __init__(self, path: str) -> None:
        self.path = str(path)
        self._fd = None

    def acquire(self) -> "ProcessLock":
        # O_EXCL makes creation atomic, so exactly one process wins the race; the
        # losers fall through to inspect the existing holder.
        attempts = 0
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            except FileExistsError:
                holder = self._read_holder()
                if holder is None:
                    # Empty/garbage content is almost always the winner mid-write
                    # (create then write are two steps); retry briefly before
                    # concluding the file is an orphan from a crash-during-write.
                    attempts += 1
                    if attempts <= 20:
                        time.sleep(0.02)
                        continue
                    logger.warning("reclaiming unreadable lock file: %s", self.path)
                    self._unlink()
                    continue
                pid = holder.get("pid")
                if not _pid_alive(pid):
                    logger.warning("reclaiming stale lock from dead pid=%s: %s", pid, self.path)
                    self._unlink()
                    attempts = 0
                    continue
                raise ProcessLockError(
                    f"another TicTok instance (pid={pid}) is already running with this "
                    f"database. Stop it first, or remove the lock file if it is stale: {self.path}"
                )
            else:
                os.write(fd, json.dumps({"pid": os.getpid()}).encode("utf-8"))
                try:
                    os.fsync(fd)
                except OSError:
                    pass
                self._fd = fd
                logger.info("acquired instance lock: %s (pid=%d)", self.path, os.getpid())
                return self

    def release(self) -> None:
        # Unlink only on the first release while we still own the fd. A second
        # release (lifespan shutdown + atexit both call this) must be a no-op:
        # by then another instance may have acquired the lock, and unlinking
        # here would delete that live holder's file.
        if self._fd is None:
            return
        try:
            os.close(self._fd)
        except OSError:
            pass
        self._fd = None
        self._unlink()

    def _unlink(self) -> None:
        try:
            os.remove(self.path)
        except FileNotFoundError:
            pass
        except OSError:
            logger.exception("failed to remove lock file: %s", self.path)

    def _read_holder(self):
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = fh.read().strip()
        except (FileNotFoundError, OSError):
            return None
        if not data:
            return None
        try:
            parsed = json.loads(data)
        except (json.JSONDecodeError, ValueError):
            return None
        if not isinstance(parsed, dict) or "pid" not in parsed:
            return None
        return parsed

    def __enter__(self) -> "ProcessLock":
        return self.acquire()

    def __exit__(self, *exc) -> None:
        self.release()
