"""Declarative Git source groups: clone missing repositories, fetch without checkout."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

from ..model import DevtoolError
from .git import prepare_source


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
