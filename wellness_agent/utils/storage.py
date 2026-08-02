"""Thread-safe JSON persistence behind a swappable interface.

Implements GAP_ANALYSIS.md migration task M5 (StorageInterface):
atomic writes via temp-file + os.replace, cross-platform advisory file
locking, and a JSON document implementation. Engines keep importing the
module-level functions, which now delegate to a single interface-backed
instance, so the backend can be swapped (e.g. PostgreSQL in M15)
without touching any engine.
"""

import errno
import hashlib
import json
import os
import tempfile
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

try:
    import fcntl  # POSIX advisory locks
except ImportError:
    fcntl = None

try:
    import msvcrt  # Windows advisory locks
except ImportError:
    msvcrt = None


class StorageInterface(ABC):
    """Contract for persistence backends.

    Implementations must guarantee that a completed save() is fully
    durable and that load() never observes a partially written document.
    """

    @abstractmethod
    def load(self, path):
        """Return the JSON document at path, or {} if it does not exist."""

    @abstractmethod
    def save(self, path, data):
        """Atomically persist data as JSON; returns the destination path."""


class _FileLock:
    """Cross-platform advisory file lock on a hashed sidecar.

    The sidecar lives in the OS temp dir (never next to the data file, so
    it can't collide with data-directory globs), and the data file itself
    is never locked so atomic os.replace over it always succeeds (Windows
    refuses to replace a file held open by another handle). OS-level locks
    (flock / msvcrt) are released automatically if the owning process
    dies, so stale locks cannot wedge the app; a PID-file fallback with
    stale detection covers the rare platforms without either primitive.
    """

    def __init__(self, path):
        resolved = str(Path(path).resolve())
        digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:32]
        lock_dir = Path(tempfile.gettempdir()) / "opencode_locks"
        self._lock_path = lock_dir / (digest + ".lock")
        self._file = None

    def __enter__(self):
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        if fcntl is not None:
            f = open(self._lock_path, "a+b")
            self._file = f
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        elif msvcrt is not None:
            f = open(self._lock_path, "a+b")
            self._file = f
            if f.seek(0, os.SEEK_END) == 0:
                f.write(b"\0")
                f.flush()
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
        else:
            self._acquire_fallback()
        return self

    def _acquire_fallback(self):
        for _ in range(400):
            try:
                fd = os.open(self._lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(fd, str(os.getpid()).encode())
                finally:
                    os.close(fd)
                return
            except FileExistsError:
                try:
                    stale = time.time() - os.path.getmtime(self._lock_path) > 30
                except OSError:
                    stale = False
                if stale:
                    try:
                        os.remove(self._lock_path)
                    except OSError:
                        pass
                time.sleep(0.05)
        raise RuntimeError("could not acquire lock: %s" % self._lock_path)

    def __exit__(self, exc_type, exc, tb):
        f = self._file
        if f is not None:
            try:
                if fcntl is not None:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                else:
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            finally:
                f.close()
        elif fcntl is None and msvcrt is None:
            # fallback strategy: the lock file's existence IS the lock
            try:
                os.remove(self._lock_path)
            except OSError:
                pass
        return False


class JsonFileStorage(StorageInterface):
    """JSON documents on disk with atomic writes and file locking."""

    def __init__(self):
        self._thread_locks = {}
        self._guard = threading.Lock()

    def _thread_lock(self, path):
        key = str(Path(path).resolve())
        with self._guard:
            lock = self._thread_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._thread_locks[key] = lock
            return lock

    def load(self, path):
        path = Path(path)
        if not path.exists():
            return {}
        with self._thread_lock(path), _FileLock(path):
            if not path.exists():
                return {}
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)

    def save(self, path, data):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._thread_lock(path), _FileLock(path):
            fd, tmp_path = tempfile.mkstemp(
                dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                self._atomic_replace(tmp_path, path)
            except BaseException:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
                raise
        return path

    def _atomic_replace(self, tmp_path, path):
        """os.replace with bounded retries.

        On Windows, AV/Indexer services intermittently hold freshly
        written files open for a few milliseconds; the rename then fails
        with a sharing violation. Retrying briefly absorbs those
        transient locks without weakening atomicity (still a single
        rename on success).
        """
        for attempt in range(5):
            try:
                os.replace(tmp_path, str(path))
                return
            except OSError as exc:
                transient = exc.errno in (errno.EACCES, errno.EPERM, errno.EBUSY)
                if not transient or attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))


default_storage = JsonFileStorage()


def load_json(path):
    """Load a JSON document; returns {} for missing files.

    Delegates to the shared JsonFileStorage so every caller is protected
    by atomic writes and file locking.
    """
    return default_storage.load(path)


def save_json(path, data):
    """Atomically persist data as JSON; returns the destination path."""
    return default_storage.save(path, data)


def now_iso():
    return datetime.now().isoformat()


def days_since(date_str):
    from datetime import datetime
    then = datetime.fromisoformat(date_str)
    return (datetime.now() - then).days


def merge_dicts(base, update):
    merged = base.copy()
    for k, v in update.items():
        if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
            merged[k] = merge_dicts(merged[k], v)
        else:
            merged[k] = v
    return merged
