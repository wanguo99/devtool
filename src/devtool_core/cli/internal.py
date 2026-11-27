"""Dispatch named helpers without loading adapters for ordinary commands."""
from __future__ import annotations

import sys


def internal_main(argv):
    if not argv:
        print("devtool: missing internal helper", file=sys.stderr)
        return 2
    name, *arguments = argv
    if name == "transport":
        from .transport import main
    elif name == "sources":
        from ..sources.cli import main
    elif name == "manifest":
        from .artifact import main
    else:
        print(f"devtool: unknown internal helper {name!r}", file=sys.stderr)
        return 2
    return main(arguments)
