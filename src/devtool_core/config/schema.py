"""Primitive TOML field and command validation."""
from __future__ import annotations

from typing import Any
import shlex

from ..model import DevtoolError


def fields(value: Any, allowed: set[str], label: str) -> dict:
    if not isinstance(value, dict):
        raise DevtoolError(f"{label} must be a table")
    unknown = set(value) - allowed
    if unknown:
        raise DevtoolError(f"unknown {label} fields: {', '.join(sorted(unknown))}")
    return value


def mapping(value: Any, label: str) -> dict:
    if not isinstance(value, dict):
        raise DevtoolError(f"{label} must be a table")
    return value


def parse_command(value, label: str) -> tuple[str, ...]:
    """Parse shell-like words or an explicit argv; never evaluate shell syntax."""
    if isinstance(value, str):
        try:
            lexer = shlex.shlex(value, posix=True, punctuation_chars="|&;<>")
            lexer.whitespace_split = True
            lexer.commenters = ""
            value = list(lexer)
        except ValueError as exc:
            raise DevtoolError(f"invalid command quoting in {label}: {exc}") from exc
        if any(word and all(ch in "|&;<>" for ch in word) for word in value):
            raise DevtoolError(f"shell control operators in {label}; use an explicit script or [\"sh\", \"-c\", SCRIPT]")
    if (not isinstance(value, list) or not value or not value[0] or
            any(not isinstance(arg, str) or "\0" in arg for arg in value)):
        raise DevtoolError(f"{label} must be a nonempty command string or argv array")
    return tuple(value)


def parse_commands(value, label: str, *, shortcut=False) -> tuple[tuple[str, ...], ...]:
    # A compact command is a string or flat argv. Multiple commands use nested
    # argv arrays; a full task's `commands` also accepts multiple command strings.
    if isinstance(value, str) or (shortcut and isinstance(value, list) and value and all(isinstance(arg, str) for arg in value)):
        return (parse_command(value, label),)
    if not isinstance(value, list):
        raise DevtoolError(f"{label} must be a command or a sequence of commands")
    if shortcut and not value:
        raise DevtoolError(f"empty command in {label}")
    return tuple(parse_command(item, label) for item in value)
