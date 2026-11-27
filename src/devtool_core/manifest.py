"""Compatibility entry point for source-mode artifact helpers."""
from .cli.artifact import main

if __name__ == "__main__":
    raise SystemExit(main())
