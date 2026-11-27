"""Verified incremental directory staging over SSH."""
from __future__ import annotations

import json
from pathlib import Path
import shlex

from ..artifacts.tree import tree_identity
from ..runtime.targets import remote_child, ssh_base
from ..model import DevtoolError
from ..runtime import run_checked
from .ssh import remote_helper


def rsync_options():
    return ["rsync", "--archive", "--compress", "--checksum", "--partial", "--partial-dir=.devtool-partial",
            "--no-owner", "--no-group", "--safe-links", "--protect-args", "--stats"]


def rsync_tree(target, source: Path, destination: str):
    identity = tree_identity(source)
    full = remote_child(target.workdir, destination)
    remote_helper(target, ["prepare-tree", "--root", target.workdir, "--destination", destination])
    run_checked([*rsync_options(), "-e", shlex.join(ssh_base(target)), "--", str(source.resolve()) + "/", target.host + ":" + full + "/"])
    if tree_identity(source)["sha256"] != identity["sha256"]:
        raise DevtoolError("source tree changed during transfer")
    remote_helper(target, ["verify-tree", "--path", full, "--sha256", identity["sha256"]])
    print(json.dumps({"transport": "rsync", "destination": full, "artifact": identity}), flush=True)
