"""Declarative Git source groups: clone missing repositories, fetch without checkout."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile
import sys

from .model import DevtoolError, Task, identifier, strings, text
from .runtime import helper_command, external_environment

SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


def source_tasks(raw, root: Path):
    """Translate source declarations into ordinary engine tasks, not a second runner."""
    if not isinstance(raw, dict):
        raise DevtoolError("sources must be a table")
    generated = {}
    groups = {"all": []}
    paths = set()
    for name, item in raw.items():
        identifier(name, "source name")
        if not isinstance(item, dict) or set(item) - {"url", "path", "branch", "revision", "groups", "default", "submodules"}:
            raise DevtoolError(f"invalid source {name}")
        url = text(item.get("url"), f"sources.{name}.url")
        path = text(item.get("path", "source/" + name), f"sources.{name}.path")
        if "{{" in path:
            raise DevtoolError("source checkout paths must be fixed to prevent overlapping destinations")
        destination = source_path(root, path)
        if any(destination == previous or destination.is_relative_to(previous) or previous.is_relative_to(destination) for previous in paths):
            raise DevtoolError("source checkout paths overlap")
        paths.add(destination)
        if re.match(r"https?://[^/]+@",url,re.I):
            raise DevtoolError("do not embed credentials in source URLs")
        branch, revision = item.get("branch", ""), item.get("revision", "")
        if not isinstance(branch, str) or not isinstance(revision, str):
            raise DevtoolError(f"invalid branch/revision in source {name}")
        if branch and revision:
            raise DevtoolError(f"source {name} must choose branch or revision, not both")
        if revision and "{{" not in revision and not SHA.fullmatch(revision):
            raise DevtoolError(f"source {name} revision must be a full commit SHA")
        included, submodules = item.get("default", True), item.get("submodules", False)
        if type(included) is not bool or type(submodules) is not bool:
            raise DevtoolError(f"source {name} default/submodules must be boolean")
        members = strings(item.get("groups", []), f"sources.{name}.groups")
        for group in (*members, name):
            identifier(group, "source group")
            if group == "all":
                raise DevtoolError("source group 'all' is reserved for the default selection")
            if name not in groups.setdefault(group, []):
                groups[group].append(name)
        if included:
            groups["all"].append(name)
        for action in ("clone", "update"):
            command = [*helper_command("sources"), action, "--root", str(root), "--path", path, "--url", url]
            if branch:
                command += ["--branch", branch]
            if revision:
                command += ["--revision", revision]
            if submodules:
                command.append("--submodules")
            key = f"source.{action}.{name}"
            generated[key] = Task(key, f"{action} source {name}", commands=(tuple(command),),tools=("git",))
    for group, names in groups.items():
        if not names:
            continue
        for action in ("clone", "update"):
            key = f"{action}.{group}"
            generated[key] = Task(key, f"{action} source group {group}", dependencies=tuple(f"source.{action}.{name}" for name in names))
    return generated


def source_path(root: Path, path: str):
    root = root.resolve()
    relative = Path(path)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts or ".git" in relative.parts:
        raise DevtoolError("source path must be a dedicated project-relative directory")
    destination = root / relative
    if not destination.resolve().is_relative_to(root) or destination.resolve() == root:
        raise DevtoolError("source path escapes project")
    folder = root
    for part in relative.parts:
        folder = folder / part
        if folder.is_symlink():
            raise DevtoolError(f"source path goes through a symlink: {folder}")
    return destination


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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("clone","update"))
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--path",required=True)
    parser.add_argument("--url",required=True)
    parser.add_argument("--branch",default="")
    parser.add_argument("--revision",default="")
    parser.add_argument("--submodules",action="store_true")
    args=parser.parse_args(argv)
    try:
        prepare_source(args.action,args.root,args.path,args.url,args.branch,args.revision,args.submodules)
        return 0
    except (DevtoolError,OSError,subprocess.SubprocessError) as exc:
        print(f"devtool sources: {exc}",file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
