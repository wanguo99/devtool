"""Read a project-local TOML definition without executing project code."""
from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from .graph import TaskGraph
from .model import DevtoolError, NAME, SENSITIVE, Parameter, Project, Task, Target, identifier, strings, text

CONFIG = "devtool.toml"


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


def find_config(project: str | Path | None = None, cwd: Path | None = None) -> Path:
    if project is not None:
        location = Path(project).expanduser().resolve()
        candidate = location / CONFIG if location.is_dir() else location
        if not candidate.is_file():
            raise DevtoolError(f"no configuration at {candidate}")
        return candidate
    start = (cwd or Path.cwd()).resolve()
    for directory in (start, *start.parents):
        candidate = directory / CONFIG
        if candidate.is_file():
            return candidate
    raise DevtoolError(f"no {CONFIG} found; run devtool init or specify --project")


def read_project(config: Path) -> Project:
    config = config.resolve()
    with config.open("rb") as stream:
        data = tomllib.load(stream)
    fields(data, {"schema", "project", "defaults", "parameters", "aliases", "tasks", "targets"}, "configuration")
    if type(data.get("schema")) is not int or data["schema"] != 1:
        raise DevtoolError("configuration requires schema = 1")
    info = fields(data.get("project", {}), {"name"}, "project")
    name = identifier(info.get("name"), "project name")
    defaults = fields(data.get("defaults", {}), {"module"}, "defaults")
    module = identifier(defaults.get("module", "all"), "default module")
    parameters = {}
    for key, value in mapping(data.get("parameters", {}), "parameters").items():
        if not NAME.fullmatch(key) or SENSITIVE.search(key):
            raise DevtoolError(f"invalid parameter name: {key}")
        spec = fields(value, {"type", "default", "choices", "description"}, f"parameter {key}")
        kind = spec.get("type", "string")
        if kind not in ("string", "integer", "boolean"):
            raise DevtoolError(f"unknown parameter type for {key}: {kind!r}")
        choices = spec.get("choices", [])
        if not isinstance(choices, list):
            raise DevtoolError(f"choices for {key} must be an array")
        description = spec.get("description", "")
        if not isinstance(description, str):
            raise DevtoolError(f"description for {key} must be a string")
        parser = Parameter(kind)
        parsed = tuple(parser.parse(choice, key) for choice in choices)
        param = Parameter(kind, None, parsed, description)
        default = param.parse(spec["default"], key) if "default" in spec else None
        parameters[key] = Parameter(kind, default, parsed, description)
    targets = {}
    for key, value in mapping(data.get("targets", {}), "targets").items():
        identifier(key, "target name")
        if key == "local":
            raise DevtoolError("local is a reserved target name")
        spec = fields(value, {"kind", "workdir", "host", "port", "identity", "container"}, f"target {key}")
        kind = spec.get("kind")
        if kind not in ("ssh", "docker"):
            raise DevtoolError(f"target {key} kind must be ssh or docker")
        workdir = text(spec.get("workdir"), f"{key}.workdir")
        if kind == "ssh":
            if "container" in spec:
                raise DevtoolError(f"SSH target {key} cannot specify a container")
            host = text(spec.get("host"), f"{key}.host")
            port = spec.get("port", 22)
            if type(port) is not int or not 1 <= port <= 65535:
                raise DevtoolError(f"invalid SSH port for {key}")
            identity = text(spec["identity"], f"{key}.identity") if "identity" in spec else ""
            targets[key] = Target(key, kind, workdir, host, port, identity)
        else:
            if any(name in spec for name in ("host", "port", "identity")):
                raise DevtoolError(f"Docker target {key} cannot specify SSH settings")
            targets[key] = Target(key, kind, workdir, container=text(spec.get("container"), f"{key}.container"))
    tasks: dict[str, Task] = {}
    for key, value in mapping(data.get("tasks", {}), "tasks").items():
        identifier(key, "task name")
        spec = fields(value, {"description", "dependencies", "commands", "cwd", "env", "secret_env", "resources", "timeout", "artifacts", "target", "transfers"}, f"task {key}")
        description = spec.get("description", "")
        if not isinstance(description, str):
            raise DevtoolError(f"description for {key} must be a string")
        deps = strings(spec.get("dependencies", []), f"{key}.dependencies")
        if len(set(deps)) != len(deps):
            raise DevtoolError(f"duplicate dependencies in {key}")
        raw_commands = spec.get("commands", [])
        if not isinstance(raw_commands, list):
            raise DevtoolError(f"{key}.commands must be an array of argv arrays")
        commands = []
        for command in raw_commands:
            if not isinstance(command, list) or not command or any(not isinstance(arg, str) or "\0" in arg for arg in command) or not command[0]:
                raise DevtoolError(f"{key}.commands requires nonempty argv arrays with a nonempty executable")
            commands.append(tuple(command))
        commands = tuple(commands)
        raw_transfers = spec.get("transfers", [])
        if not isinstance(raw_transfers, list):
            raise DevtoolError(f"{key}.transfers must be an array of tables")
        transfers = []
        for transfer in raw_transfers:
            if not isinstance(transfer, dict):
                raise DevtoolError(f"invalid transfer in {key}")
            kind = transfer.get("kind")
            if not isinstance(kind, str):
                raise DevtoolError(f"transfer kind must be a string in {key}")
            required = {"rsync": {"source", "destination", "target"},
                        "registry": {"image", "target"},
                        "oci-delta": {"image", "target", "destination"},
                        "archive-pack": {"source", "destination"},
                        "archive-unpack": {"source", "destination"}}.get(kind)
            if required is None:
                raise DevtoolError(f"unknown transfer kind in {key}: {kind!r}")
            optional = {"remote_image"} if kind == "registry" else set()
            fields(transfer, {"kind", *required, *optional}, f"{key}.transfer")
            if not required.issubset(transfer):
                raise DevtoolError(f"missing transfer fields in {key}: {', '.join(sorted(required - set(transfer)))}")
            for field, value in transfer.items():
                text(value, f"{key}.transfer.{field}")
            if "target" in required and (transfer["target"] not in targets or targets[transfer["target"]].kind != "ssh"):
                raise DevtoolError(f"transfer in {key} requires a named SSH target")
            transfers.append(dict(transfer))
        if not commands and not deps and not transfers:
            raise DevtoolError(f"task {key} has neither commands, transfers nor dependencies")
        cwd = text(spec.get("cwd", "."), f"{key}.cwd")
        env = mapping(spec.get("env", {}), f"{key}.env")
        for k, v in env.items():
            if not NAME.fullmatch(k) or SENSITIVE.search(k) or not isinstance(v, str) or "\0" in v:
                raise DevtoolError(f"invalid environment entry in {key}")
        secret_env = mapping(spec.get("secret_env", {}), f"{key}.secret_env")
        for k, v in secret_env.items():
            if not NAME.fullmatch(k) or not isinstance(v, str) or not NAME.fullmatch(v) or k in env:
                raise DevtoolError(f"invalid secret environment reference in {key}")
        resources = strings(spec.get("resources", ["project"]), f"{key}.resources")
        for resource in resources:
            identifier(resource, "resource")
        timeout = spec.get("timeout")
        if timeout is not None and (type(timeout) is not int or timeout < 1):
            raise DevtoolError(f"timeout for {key} must be a positive integer in seconds")
        artifacts = strings(spec.get("artifacts", []), f"{key}.artifacts")
        target = spec.get("target", "local")
        if target != "local" and (not isinstance(target, str) or target not in targets):
            raise DevtoolError(f"unknown target for {key}: {target!r}")
        if target != "local" and secret_env:
            raise DevtoolError(f"remote/container task {key} must use target-side secret configuration")
        if target != "local" and artifacts:
            raise DevtoolError(f"task {key} declares local artifacts but uses a non-local target")
        tasks[key] = Task(key, description, deps, commands, cwd, dict(env), dict(secret_env), resources, timeout, artifacts, target, tuple(transfers))
    if not tasks:
        raise DevtoolError("project defines no tasks")
    TaskGraph(tasks)
    aliases = mapping(data.get("aliases", {}), "aliases")
    for key, target in aliases.items():
        identifier(key, "alias")
        if key in tasks or not isinstance(target, str) or target not in tasks:
            raise DevtoolError(f"alias {key!r} conflicts with a task or points to an unknown task")
    return Project(name, config.parent, tasks, parameters, dict(aliases), module, targets)
