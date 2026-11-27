"""Strict directory identities shared by archive and file staging."""
from __future__ import annotations

import os
from pathlib import Path

from ..model import DevtoolError
from .identity import describe


def tree_identity(path: Path):
    if path.is_symlink() or not path.is_dir():
        raise DevtoolError(f"transfer source must be a real directory: {path}")
    path = path.resolve()
    for item in path.rglob("*"):
        if item.name == ".devtool-partial":
            raise DevtoolError("tree contains the reserved rsync partial directory name")
        if item.is_symlink():
            try:
                external = Path(os.readlink(item)).is_absolute() or not item.resolve().is_relative_to(path)
            except RuntimeError as exc:
                raise DevtoolError(f"transfer tree contains a symlink cycle: {item}") from exc
            if external:
                raise DevtoolError(f"transfer tree contains an external or absolute symlink: {item}")
    return describe(path, path.parent)
