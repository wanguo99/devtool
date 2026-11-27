"""Immutable command descriptions and serializable execution plans."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import re
import hashlib
import json


class DevtoolError(ValueError):
    """Invalid project configuration, input or execution plan."""


ID = re.compile(r"[A-Za-z][A-Za-z0-9_.-]*\Z")
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
SENSITIVE = re.compile(r"password|passwd|secret|token|credential|private.?key|authorization|api.?key", re.I)
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
    derive: str = ""

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
class CommandStep:
    argv: tuple[str, ...]
    cwd: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    secret_env: dict[str, str] = field(default_factory=dict)
    timeout: int | None = None
    target: str | None = None
    when: dict[str, tuple[str | int | bool, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class Option:
    parameter: str
    value: str | int | bool | None = None


@dataclass(frozen=True)
class Task:
    name: str
    description: str = ""
    dependencies: tuple[str, ...] = ()
    commands: tuple[tuple[str, ...], ...] = ()
    cwd: str = "."
    env: dict[str, str] = field(default_factory=dict)
    secret_env: dict[str, str] = field(default_factory=dict)
    resources: tuple[str, ...] = ("project",)
    timeout: int | None = None
    artifacts: tuple[str, ...] = ()
    target: str = "local"
    transfers: tuple[dict[str, str], ...] = ()
    requires: tuple[str, ...] = ()
    verify_manifests: tuple[str, ...] = ()
    manifest: str = ""
    images: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    steps: tuple[CommandStep, ...] = ()
    when: dict[str, tuple[str | int | bool, ...]] = field(default_factory=dict)
    on_failure: tuple[tuple[str, ...], ...] = ()
    cleanup: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class Target:
    name: str
    kind: str
    workdir: str
    host: str = ""
    port: int = 22
    identity: str = ""
    container: str = ""
    engine: str = ""


@dataclass(frozen=True)
class Project:
    name: str
    root: Path
    tasks: dict[str, Task]
    parameters: dict[str, Parameter]
    aliases: dict[str, str]
    default_module: str = "all"
    targets: dict[str, Target] = field(default_factory=dict)
    options: dict[str, Option] = field(default_factory=dict)
    backend_actions: tuple[str, ...] = ()


@dataclass(frozen=True)
class Step:
    task: str
    index: int
    argv: tuple[str, ...]
    cwd: Path
    env: dict[str, str] = field(default_factory=dict)
    secret_env: dict[str, str] = field(default_factory=dict)
    timeout: int | None = None
    target: str = "local"
    target_kind: str = "local"
    tools: tuple[str, ...] = ()

    def public(self):
        return {"task": self.task, "index": self.index, "argv": list(self.argv),
                "cwd": str(self.cwd), "env": self.env, "secret_env": self.secret_env,
                "timeout": self.timeout, "target": self.target, "target_kind": self.target_kind, "tools": list(self.tools)}


@dataclass(frozen=True)
class Plan:
    project: str
    root: Path
    requested: str
    tasks: tuple[str, ...]
    steps: tuple[Step, ...]
    parameters: dict[str, str | int | bool]
    resources: tuple[str, ...] = ()
    artifacts: dict[str, tuple[Path, ...]] = field(default_factory=dict)
    required_paths: dict[str, tuple[Path, ...]] = field(default_factory=dict)
    verify_manifests: dict[str, tuple[Path, ...]] = field(default_factory=dict)
    manifest_outputs: dict[str, Path] = field(default_factory=dict)
    images: dict[str, tuple[str, ...]] = field(default_factory=dict)
    required_tools: dict[str, tuple[str, ...]] = field(default_factory=dict)
    recovery_steps: dict[str, tuple[Step, ...]] = field(default_factory=dict)
    cleanup_steps: dict[str, tuple[Step, ...]] = field(default_factory=dict)

    def all_steps(self):
        return (*self.steps, *(step for steps in self.recovery_steps.values() for step in steps),
                *(step for steps in self.cleanup_steps.values() for step in steps))

    def public(self):
        value = {"schema": 1, "project": self.project, "root": str(self.root),
                "requested": self.requested, "tasks": list(self.tasks),
                "parameters": self.parameters, "steps": [step.public() for step in self.steps],
                "resources": list(self.resources),
                "artifacts": {task: [str(p) for p in paths] for task, paths in self.artifacts.items()},
                "required_paths": {task: [str(p) for p in paths] for task, paths in self.required_paths.items()},
                "verify_manifests": {task: [str(p) for p in paths] for task, paths in self.verify_manifests.items()},
                "manifest_outputs": {task: str(path) for task, path in self.manifest_outputs.items()},
                "images": {task: list(images) for task, images in self.images.items()},
                "required_tools": {task: list(tools) for task,tools in self.required_tools.items()},
                "on_failure": {task: [step.public() for step in steps] for task,steps in self.recovery_steps.items()},
                "cleanup": {task: [step.public() for step in steps] for task,steps in self.cleanup_steps.items()}}
        value["digest"] = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return value
