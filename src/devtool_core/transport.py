"""Compatibility entry point for source-mode transport helpers."""
from .cli.transport import main

if __name__ == "__main__":
    raise SystemExit(main())
