"""Clone, fetch and initialize missing Git submodules."""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import tempfile

from ..model import DevtoolError
from ..runtime import external_environment
from .paths import SHA, source_path


def git(*args, cwd=None, capture=False, raw=False):
    result = subprocess.run(["git", *map(str,args)], cwd=cwd, check=True,
                            env=external_environment(executable="git"),
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None, text=True)
    return (result.stdout.rstrip("\n") if raw else result.stdout.strip()) if capture else None


def checked_repository(path: Path, url: str):
    if not path.is_dir() or git("rev-parse", "--show-toplevel", cwd=path, capture=True) != str(path.resolve()):
        raise DevtoolError(f"existing path is not a repository root: {path}")
    actual = git("remote", "get-url", "origin", cwd=path, capture=True)
    if actual != url:
        raise DevtoolError(f"origin mismatch at {path}; existing repository left unchanged")


def initialize_missing_submodules(path: Path):
    """Initialize missing entries only; never update an already checked-out submodule."""
    if not (path / ".gitmodules").is_file():
        return
    output = git("submodule", "status", cwd=path, capture=True, raw=True)
    # --status output uses a fixed 40/64-character object ID, then path and optional description.
    for line in output.splitlines():
        match = re.fullmatch(r"([-+ U])([0-9a-f]{40}|[0-9a-f]{64}) (.+?)(?: \([^\n]*\))?", line)
        if not match:
            raise DevtoolError("unexpected git submodule status; refusing to modify the checkout")
        state, _, relative = match.groups()
        child = source_path(path, relative)
        if state == "-":
            git("submodule", "update", "--init", "--", relative, cwd=path)
        elif state == "U":
            raise DevtoolError(f"unmerged submodule: {child}")
        # An existing divergent submodule is deliberately left on its current SHA.
        initialize_missing_submodules(child)


def prepare_source(action, root: Path, path: str, url: str, branch="", revision="", submodules=False):
    if url.startswith("-") or any(ch in url for ch in ("\n", "\r", "\0")):
        raise DevtoolError("invalid source URL")
    # Commands are deliberately not allowed to carry embedded HTTP credentials.
    if re.match(r"https?://[^/]+@",url,re.I):
        raise DevtoolError("use Git credential helpers instead of credentials in source URLs")
    if branch and (branch.startswith("-") or not branch.strip() or any(ch.isspace() for ch in branch)):
        raise DevtoolError("invalid source branch")
    if revision and (branch or not SHA.fullmatch(revision)):
        raise DevtoolError("source revision must be a full commit SHA")
    destination = source_path(root,path)
    if destination.exists():
        checked_repository(destination,url)
        if action == "update":
            git("fetch","--no-tags","origin",cwd=destination)
        if submodules:
            initialize_missing_submodules(destination)
        print(json.dumps({"source":str(destination),"action":"fetched" if action=="update" else "existing"}),flush=True)
        return
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".devtool-clone-",dir=destination.parent) as stage:
        checkout=Path(stage)/"checkout"
        args=["clone","--no-tags"]
        if branch:
            args += ["--branch",branch]
        if revision:
            args += ["--no-checkout"]
        git(*args,"--",url,checkout)
        if revision:
            try:
                git("cat-file","-e",revision+"^{commit}",cwd=checkout,capture=True)
            except subprocess.CalledProcessError:
                git("fetch","--no-tags","origin",revision,cwd=checkout)
            git("checkout","--detach",revision,cwd=checkout)
        if submodules:
            initialize_missing_submodules(checkout)
        if destination.exists() or destination.is_symlink():
            raise DevtoolError("source destination appeared during clone")
        checkout.rename(destination)
    print(json.dumps({"source":str(destination),"action":"cloned"}),flush=True)
