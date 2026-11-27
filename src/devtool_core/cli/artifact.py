"""Immutable build output manifests and verification before release operations."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

from ..artifacts.manifest import project_path, create_manifest, verify_manifest


def main(argv=None):
    parser=argparse.ArgumentParser(prog="devtool artifact",description=__doc__)
    actions=parser.add_subparsers(dest="action",required=True)
    create=actions.add_parser("create")
    create.add_argument("--root",type=Path,default=Path.cwd())
    create.add_argument("--output",required=True)
    create.add_argument("--file",action="append",default=[])
    create.add_argument("--image",action="append",default=[])
    verify=actions.add_parser("verify")
    verify.add_argument("--root",type=Path,default=Path.cwd())
    verify.add_argument("--manifest",required=True)
    strip=actions.add_parser("strip",help="copy and strip debug sections from runtime ELF files")
    strip.add_argument("--root",type=Path,default=Path.cwd())
    strip.add_argument("--source",required=True)
    strip.add_argument("--destination",required=True)
    strip.add_argument("--strip-command",default="strip")
    export=actions.add_parser("export-images",help="create a verified full offline Docker image bundle")
    export.add_argument("--root",type=Path,default=Path.cwd())
    export.add_argument("--output",required=True)
    export.add_argument("--image",action="append",required=True)
    load=actions.add_parser("import-images",help="verify and load a full offline Docker image bundle")
    load.add_argument("--root",type=Path,default=Path.cwd())
    load.add_argument("--input",required=True)
    fetch=actions.add_parser("fetch",help="download or repair a SHA-256-pinned cache file")
    fetch.add_argument("--root",type=Path,default=Path.cwd())
    fetch.add_argument("--url",required=True)
    fetch.add_argument("--output",required=True)
    fetch.add_argument("--sha256",required=True)
    fetch.add_argument("--size",type=int)
    try:
        args=parser.parse_args(argv)
        if args.action == "create":
            result=create_manifest(args.root,args.output,args.file,args.image)
        elif args.action == "verify":
            result=verify_manifest(args.root,args.manifest)
        elif args.action == "strip":
            from ..artifacts.elf import strip_tree
            result=strip_tree(project_path(args.root,args.source),project_path(args.root,args.destination),args.strip_command)
        elif args.action == "export-images":
            from ..delivery.bundles import export_images
            result=export_images(project_path(args.root,args.output),args.image)
        elif args.action == "import-images":
            from ..delivery.bundles import import_images
            result=import_images(project_path(args.root,args.input))
        else:
            from ..artifacts.fetch import fetch_file
            result=fetch_file(args.url,project_path(args.root,args.output),args.sha256,args.size)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (ValueError,OSError,subprocess.SubprocessError) as exc:
        print(f"devtool artifact: {exc}",file=sys.stderr);return 1
