"""Immutable command descriptions and serializable execution plans."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import re


class DevtoolError(ValueError):
    """Invalid project configuration, input or execution plan."""


ID = re.compile(r"[A-Za-z][A-Za-z0-9_.-]*\Z")
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
PLACEHOLDER = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")


def identifier(value: str, label: str) -> str:
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise DevtoolError(f"invalid {label}: {value!r}")
    return value


def text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or "\0" in value:
        raise DevtoolError(f"{label} must be a non-empty string")
    return value


def strings(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise DevtoolError(f"{label} must be an array of strings")
    return tuple(text(item, label) for item in value)


@dataclass(frozen=True)
class Parameter:
    kind: str = "string"
    default: str | int | bool | None = None
    choices: tuple[str | int | bool, ...] = ()
    description: str = ""

    def parse(self, value: Any, name: str):
        if self.kind == "string":
            result = value if isinstance(value, str) and "\0" not in value else None
        elif self.kind == "integer":
            result = value if type(value) is int else None
            if isinstance(value, str) and re.fullmatch(r"-?[0-9]+", value):
                result = int(value)
        elif self.kind == "boolean":
            result = value if type(value) is bool else None
            if value in ("true", "false"):
                result = value == "true"
        else:
            raise DevtoolError(f"unsupported parameter type {self.kind!r}")
        if result is None or self.choices and result not in self.choices:
            raise DevtoolError(f"invalid value for parameter {name!r} (type={self.kind}, choices={self.choices})")
        return result


@dataclass(frozen=True)
class Task:
    name: str
    description: str = ""
    dependencies: tuple[str, ...] = ()
    commands: tuple[tuple[str, ...], ...] = ()
    cwd: str = "."
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Project:
    name: str
    root: Path
    tasks: dict[str, Task]
    parameters: dict[str, Parameter]
    aliases: dict[str, str]
    default_module: str = "all"


@dataclass(frozen=True)
class Step:
    task: str
    index: int
    argv: tuple[str, ...]
    cwd: Path
    env: dict[str, str] = field(default_factory=dict)

    def public(self):
        return {"task": self.task, "index": self.index, "argv": list(self.argv),
                "cwd": str(self.cwd), "env": self.env}


@dataclass(frozen=True)
class Plan:
    project: str
    root: Path
    requested: str
    tasks: tuple[str, ...]
    steps: tuple[Step, ...]
    parameters: dict[str, str | int | bool]

    def public(self):
        return {"schema": 1, "project": self.project, "root": str(self.root),
                "requested": self.requested, "tasks": list(self.tasks),
                "parameters": self.parameters, "steps": [step.public() for step in self.steps]}
