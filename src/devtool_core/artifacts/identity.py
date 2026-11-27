"""Content identities for declared file and directory outputs."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import re
from ..model import DevtoolError


HEX = re.compile(r"[0-9a-f]{64}\Z")


def digest_file(path: Path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def describe(path: Path, root: Path):
    # Resolve again: task execution may have created or replaced a symlink.
    root = root.resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(root) or resolved == root:
        raise DevtoolError(f"artifact outside project: {path}")
    if not path.exists():
        raise DevtoolError(f"missing declared artifact: {path}")
    if path.is_file():
        return {"path": str(path), "type": "file", "bytes": path.stat().st_size, "sha256": digest_file(path)}
    if not path.is_dir():
        raise DevtoolError(f"unsupported artifact type: {path}")
    members = []
    size = 0
    for item in sorted(path.rglob("*"), key=lambda p: p.relative_to(path).as_posix()):
        name = item.relative_to(path).as_posix()
        mode = stat.S_IMODE(item.lstat().st_mode)
        if item.is_symlink():
            if not item.resolve().is_relative_to(root):
                raise DevtoolError(f"artifact contains an external symlink: {item}")
            members.append([name, "symlink", mode, os.readlink(item)])
        elif item.is_file():
            length = item.stat().st_size
            size += length
            members.append([name, "file", mode, length, digest_file(item)])
        elif item.is_dir():
            members.append([name, "directory", mode])
        else:
            raise DevtoolError(f"artifact contains a special file: {item}")
    identity = hashlib.sha256(json.dumps(members, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()
    return {"path": str(path), "type": "directory", "bytes": size, "sha256": identity, "entries": len(members)}
