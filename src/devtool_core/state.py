"""Private operation records and non-blocking resource locks."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from uuid import uuid4

from .model import DevtoolError

OPERATION_ID = re.compile(r"[0-9a-f]{32}\Z")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def state_directory(project: str, root: Path) -> Path:
    base = Path(os.environ.get("DEVTOOL_STATE_HOME") or
                (Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "devtool")).expanduser()
    if not base.is_absolute():
        raise DevtoolError("DEVTOOL_STATE_HOME/XDG_STATE_HOME must be absolute")
    key = hashlib.sha256(os.fsencode(root.resolve())).hexdigest()[:16]
    return base / f"{project}-{key}"


def secure_directory(path: Path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir() or path.stat().st_uid != os.getuid():
        raise DevtoolError(f"unsafe operation state directory: {path}")
    path.chmod(0o700)


def atomic_json(path: Path, value):
    fd, filename = tempfile.mkstemp(prefix=".record-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(filename, path)
    finally:
        if os.path.exists(filename):
            os.unlink(filename)


def process_identity(pid: int):
    if type(pid) is not int or pid <= 0:
        return None
    try:
        fields = (Path("/proc") / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()
        return fields[19] if fields[0] != "Z" else None
    except (OSError, IndexError):
        return None


def running(record):
    pid = record.get("pid")
    if type(pid) is not int or pid <= 0:
        return False
    expected = record.get("process_identity")
    if expected:
        return process_identity(pid) == expected
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class StateStore:
    def __init__(self, root: Path):
        self.root = root
        self.operations = root / "operations"
        self.locks = root / "locks"

    def prepare(self):
        for directory in (self.root, self.operations, self.locks):
            secure_directory(directory)

    @contextmanager
    def acquire(self, resources):
        self.prepare()
        with ExitStack() as held:
            for resource in sorted(set(resources)):
                key = hashlib.sha256(resource.encode()).hexdigest()
                flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
                fd = os.open(self.locks / (key + ".lock"), flags, 0o600)
                stream = held.enter_context(os.fdopen(fd, "a+"))
                try:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise DevtoolError(f"resource already locked: {resource}") from exc
            yield

    def create(self, plan):
        operation = uuid4().hex
        directory = self.operations / operation
        directory.mkdir(mode=0o700)
        record = {"schema": 1, "id": operation, "pid": os.getpid(),
                  "process_identity": process_identity(os.getpid()), "created_at": now(),
                  "status": "RUNNING", "plan": plan, "steps": [], "artifacts": []}
        self.save(record)
        return directory, record

    def save(self, record):
        record["updated_at"] = now()
        atomic_json(self.operations / record["id"] / "operation.json", record)

    def read(self, operation: str):
        if not OPERATION_ID.fullmatch(operation):
            raise DevtoolError("invalid operation id")
        with (self.operations / operation / "operation.json").open(encoding="utf-8") as stream:
            result = json.load(stream)
        if result["status"] == "RUNNING" and not running(result):
            result["status"] = "INTERRUPTED_UNKNOWN"
        return result

    def history(self, limit=20):
        if limit < 1:
            raise DevtoolError("history limit must be positive")
        paths = sorted(self.operations.glob("*/operation.json"), key=lambda p: p.stat().st_mtime_ns, reverse=True)
        return [self.read(path.parent.name) for path in paths[:limit]]
