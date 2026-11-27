"""Public command-line entry point."""


def main(argv=None):
    from .application import main as entry
    return entry(argv)


__all__ = ["main"]
