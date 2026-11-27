"""Source checkout path and revision rules."""
from __future__ import annotations

from pathlib import Path
import re

from ..model import DevtoolError

SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


def source_path(root: Path, path: str, *, check_layout=True):
    root = root.resolve()
    relative = Path(path)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts or ".git" in relative.parts:
        raise DevtoolError("source path must be a dedicated project-relative directory")
    destination = root / relative
    # A delegated source backend may use its own layout/compatibility links.
    # Only native Git tasks resolve and enforce the actual destination layout.
    if not check_layout:
        return destination
    if not destination.resolve().is_relative_to(root) or destination.resolve() == root:
        raise DevtoolError("source path escapes project")
    folder = root
    for part in relative.parts:
        folder = folder / part
        if folder.is_symlink():
            raise DevtoolError(f"source path goes through a symlink: {folder}")
    return destination
