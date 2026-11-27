"""Construct explicit local, SSH and existing-container execution commands."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path, PurePosixPath
import re
import shlex

from ..model import DevtoolError, Target
from . import frozen, run_checked

SSH_HOST = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*@[A-Za-z0-9][A-Za-z0-9.-]*\Z")
CONTAINER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")


def absolute_remote(value):
    path = PurePosixPath(value)
    if not path.is_absolute() or len(path.parts) < 2 or value.startswith("//") or ".." in path.parts or any(c in value for c in ("\0", "\r", "\n")):
        raise DevtoolError(f"target workdir must be an absolute non-root path: {value!r}")
    return str(path)


def remote_child(root, value, *, allow_root=False):
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or any(c in value for c in ("\0", "\r", "\n")):
        raise DevtoolError(f"target path must stay below workdir: {value!r}")
    if relative == PurePosixPath(".") and not allow_root:
        raise DevtoolError("transfer needs a dedicated child directory")
    return str(PurePosixPath(root) / relative)


def resolve_target(target: Target, render, root: Path):
    target = replace(target, workdir=absolute_remote(render(target.workdir)), host=render(target.host),
                     identity=render(target.identity), container=render(target.container), engine=render(target.engine))
    if target.kind == "ssh":
        if not SSH_HOST.fullmatch(target.host):
            raise DevtoolError("SSH host must have the form user@hostname or user@IPv4")
        if not target.engine and frozen():
            target = replace(target, engine="./devtool")
        if target.engine and (target.engine.startswith("-") or any(ch in target.engine for ch in ("\0", "\r", "\n"))):
            raise DevtoolError("invalid remote devtool executable")
        if target.identity:
            path = Path(target.identity).expanduser()
            target = replace(target, identity=str((root / path).resolve()))
    elif not CONTAINER.fullmatch(target.container):
        raise DevtoolError("invalid Docker container name")
    return target


def ssh_base(target: Target):
    if target.kind != "ssh" or not SSH_HOST.fullmatch(target.host) or not 1 <= target.port <= 65535:
        raise DevtoolError("invalid SSH target")
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=10", "-p", str(target.port)]
    if target.identity:
        cmd += ["-i", target.identity]
    return cmd


def ssh_command(target: Target, argv, *, cwd=None, env=None):
    env = env or {}
    command = ["env", "--", *[f"{key}={value}" for key, value in sorted(env.items())], *argv]
    script = "cd " + shlex.quote(absolute_remote(cwd or target.workdir)) + " && exec " + shlex.join(command)
    return (*ssh_base(target), "--", target.host, script)


def target_command(target: Target, argv, cwd, env):
    folder = remote_child(target.workdir, cwd, allow_root=True)
    if target.kind == "ssh":
        return ssh_command(target, argv, cwd=folder, env=env)
    command = ["docker", "exec", "--workdir", folder]
    for key, value in sorted(env.items()):
        command += ["--env", f"{key}={value}"]
    return tuple([*command, "--", target.container, *argv])


def remote(target, argv, **kwargs):
    """Execute one command using the explicit SSH target."""
    return run_checked(ssh_command(target, argv), **kwargs)
