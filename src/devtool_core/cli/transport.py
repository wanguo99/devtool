"""Verified staging transfers. No service activation or database operations."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tarfile

from ..artifacts.identity import HEX
from ..artifacts.tree import tree_identity
from ..delivery.ssh import prepare_directory
from ..runtime.targets import absolute_remote, ssh_base
from ..model import DevtoolError, Target


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="action", required=True)
    for action in ("rsync", "registry", "oci-delta"):
        p = sub.add_parser(action)
        p.add_argument("--host", required=True)
        p.add_argument("--port", type=int, default=22)
        p.add_argument("--workdir", required=True)
        p.add_argument("--identity", default="")
        p.add_argument("--engine", default="")
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
            from ..artifacts.archive import pack_directory, unpack_directory
            func = pack_directory if args.action == "archive-pack" else unpack_directory
            print(json.dumps(func(args.source,args.destination)),flush=True)
        elif args.action == "load-oci":
            from ..delivery.oci import load_candidate
            load_candidate(args.path,args.sha256)
        else:
            target = Target("transfer", "ssh", absolute_remote(args.workdir), args.host, args.port, args.identity, engine=args.engine)
            ssh_base(target)
            if args.action == "rsync":
                from ..delivery.rsync import rsync_tree
                rsync_tree(target, args.source, args.destination)
            elif args.action == "registry":
                from ..delivery.registry import registry
                registry(target, args.image, args.remote_image)
            else:
                from ..delivery.oci import send_candidate
                send_candidate(target,args.image,args.destination)
        return 0
    except (ValueError, OSError, subprocess.SubprocessError, tarfile.TarError) as exc:
        print(f"devtool transport: {exc}", file=sys.stderr)
        return 1
