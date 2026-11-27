"""SSH helper execution and remote staging directory preparation."""
from __future__ import annotations

from pathlib import Path

from ..runtime.targets import remote_child, remote
from ..model import DevtoolError
from ..runtime import frozen


def prepare_directory(root: Path, relative: str):
    if not root.is_dir():
        raise DevtoolError(f"target workspace does not exist: {root}")
    remote_child(str(root), relative)
    root = root.resolve()
    folder = root
    for part in Path(relative).parts:
        folder = folder / part
        if folder.is_symlink():
            raise DevtoolError(f"target directory contains a symlink: {folder}")
        folder.mkdir(exist_ok=True)
        if not folder.is_dir():
            raise DevtoolError(f"target path is not a directory: {folder}")
    return folder


def remote_helper(target, arguments):
    engine = target.engine or ("./devtool" if frozen() else "")
    prefix = [engine, "_internal", "transport"] if engine else ["python3", "-m", "devtool_core.transport"]
    return remote(target, [*prefix, *arguments])
