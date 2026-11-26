"""Verified staging transfers. No service activation or database operations."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tarfile

from .artifacts import describe
from .executors import absolute_remote, ssh_base, ssh_command, remote_child
from .model import DevtoolError, Target

HEX = re.compile(r"[0-9a-f]{64}\Z")
IMAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]*:[A-Za-z0-9_][A-Za-z0-9_.-]*\Z")


def local_child(root: Path, value: str):
    path = Path(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise DevtoolError(f"transfer source must be project-relative: {value!r}")
    full = root / path
    if not full.resolve().is_relative_to(root.resolve()) or full.resolve() == root.resolve():
        raise DevtoolError(f"transfer source escapes project: {value!r}")
    return full


def image_ref(value):
    if not IMAGE.fullmatch(value):
        raise DevtoolError("image transfer requires an explicit tagged image reference")
    return value


def target_flags(target):
    args = ["--host", target.host, "--port", str(target.port), "--workdir", target.workdir]
    if target.identity:
        args += ["--identity", target.identity]
    return args


def transfer_command(transfer, target, render, root):
    kind = transfer["kind"]
    command = [sys.executable, "-m", "devtool_core.transport", kind]
    if target is not None:
        command += target_flags(target)
    if kind == "rsync":
        source = local_child(root, render(transfer["source"]))
        destination = render(transfer["destination"])
        remote_child(target.workdir, destination)
        command += ["--source", str(source), "--destination", destination]
    elif kind == "registry":
        image = image_ref(render(transfer["image"]))
        remote = image_ref(render(transfer.get("remote_image", transfer["image"])))
        command += ["--image", image, "--remote-image", remote]
    elif kind == "oci-delta":
        image = image_ref(render(transfer["image"]))
        destination = render(transfer["destination"])
        remote_child(target.workdir, destination)
        command += ["--image", image, "--destination", destination]
    elif kind in ("archive-pack", "archive-unpack"):
        command += ["--source", str(local_child(root,render(transfer["source"]))),
                    "--destination", str(local_child(root,render(transfer["destination"])))]
    else:
        raise DevtoolError(f"unsupported transfer: {kind}")
    return tuple(command)


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


def rsync_options():
    return ["rsync", "--archive", "--compress", "--checksum", "--partial", "--partial-dir=.devtool-partial",
            "--no-owner", "--no-group", "--safe-links", "--protect-args", "--stats"]


def run(argv, **kwargs):
    return subprocess.run(argv, check=True, **kwargs)


def remote(target, argv, **kwargs):
    return run(ssh_command(target, argv), **kwargs)


def rsync_tree(target, source: Path, destination: str):
    identity = tree_identity(source)
    full = remote_child(target.workdir, destination)
    remote(target, ["python3", "-m", "devtool_core.transport", "prepare-tree", "--root", target.workdir, "--destination", destination])
    run([*rsync_options(), "-e", shlex.join(ssh_base(target)), "--", str(source.resolve()) + "/", target.host + ":" + full + "/"])
    if tree_identity(source)["sha256"] != identity["sha256"]:
        raise DevtoolError("source tree changed during transfer")
    remote(target, ["python3", "-m", "devtool_core.transport", "verify-tree", "--path", full, "--sha256", identity["sha256"]])
    print(json.dumps({"transport": "rsync", "destination": full, "artifact": identity}), flush=True)


def docker_identity(image, target=None, *, missing_ok=False):
    argv = ["docker", "image", "inspect", "--format", "{{.Id}} {{.Os}}/{{.Architecture}}", image]
    try:
        result = (remote(target, argv, capture_output=True, text=True) if target else run(argv, capture_output=True, text=True))
    except subprocess.CalledProcessError as exc:
        if missing_ok and any(mark in (exc.stderr or "").lower() for mark in ("no such image", "no such object")):
            return None
        raise
    value = result.stdout.strip()
    if not re.fullmatch(r"sha256:[0-9a-f]{64} [A-Za-z0-9_/-]+", value):
        raise DevtoolError("invalid or ambiguous Docker image identity")
    return value


def registry(target, image, remote_image):
    identity = docker_identity(image_ref(image))
    image_ref(remote_image)
    remote(target, ["docker", "info", "--format", "{{.ServerVersion}}"])
    run(["docker", "push", image])
    remote(target, ["docker", "pull", remote_image])
    if docker_identity(remote_image, target) != identity:
        raise DevtoolError("remote image ID/platform does not match the local candidate")
    print(json.dumps({"transport": "registry", "image": remote_image, "identity": identity}), flush=True)


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="action", required=True)
    for action in ("rsync", "registry", "oci-delta"):
        p = sub.add_parser(action)
        p.add_argument("--host", required=True)
        p.add_argument("--port", type=int, default=22)
        p.add_argument("--workdir", required=True)
        p.add_argument("--identity", default="")
        if action == "rsync":
            p.add_argument("--source", required=True, type=Path)
            p.add_argument("--destination", required=True)
        elif action == "registry":
            p.add_argument("--image", required=True)
            p.add_argument("--remote-image", required=True)
        else:
            p.add_argument("--image", required=True)
            p.add_argument("--destination", required=True)
    for action in ("archive-pack", "archive-unpack"):
        p = sub.add_parser(action)
        p.add_argument("--source", type=Path, required=True)
        p.add_argument("--destination", type=Path, required=True)
    load = sub.add_parser("load-oci")
    load.add_argument("--path", type=Path, required=True)
    load.add_argument("--sha256", required=True)
    prepare = sub.add_parser("prepare-tree")
    prepare.add_argument("--root", required=True, type=Path)
    prepare.add_argument("--destination", required=True)
    verify = sub.add_parser("verify-tree")
    verify.add_argument("--path", type=Path, required=True)
    verify.add_argument("--sha256", required=True)
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.action == "prepare-tree":
            print(prepare_directory(args.root, args.destination))
        elif args.action == "verify-tree":
            if not HEX.fullmatch(args.sha256) or tree_identity(args.path)["sha256"] != args.sha256:
                raise DevtoolError("remote tree SHA-256 differs from source; no activation performed")
            print("tree identity verified")
        elif args.action in ("archive-pack", "archive-unpack"):
            from .archive import pack_directory, unpack_directory
            func = pack_directory if args.action == "archive-pack" else unpack_directory
            print(json.dumps(func(args.source,args.destination)),flush=True)
        elif args.action == "load-oci":
            from .oci import load_candidate
            load_candidate(args.path,args.sha256)
        else:
            target = Target("transfer", "ssh", absolute_remote(args.workdir), args.host, args.port, args.identity)
            ssh_base(target)
            if args.action == "rsync":
                rsync_tree(target, args.source, args.destination)
            elif args.action == "registry":
                registry(target, args.image, args.remote_image)
            else:
                from .oci import send_candidate
                send_candidate(target,args.image,args.destination)
        return 0
    except (ValueError, OSError, subprocess.SubprocessError, tarfile.TarError) as exc:
        print(f"devtool transport: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
