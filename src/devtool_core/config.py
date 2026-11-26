"""Read a project-local TOML definition without executing project code."""
from __future__ import annotations

import tomllib
import re
import shlex
from pathlib import Path
from typing import Any

from .graph import TaskGraph
from .providers import extend_config
from .model import DevtoolError, NAME, SENSITIVE, Parameter, Project, Task, Target, identifier, strings, text

CONFIG = "devtool.toml"


class ConfigNotFound(DevtoolError):
    pass


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
            raise ConfigNotFound(f"no configuration at {candidate}")
        return candidate
    start = (cwd or Path.cwd()).resolve()
    for directory in (start, *start.parents):
        candidate = directory / CONFIG
        if candidate.is_file():
            return candidate
    raise ConfigNotFound(f"no {CONFIG} found; run devtool init or specify --project")


def project_name(directory: Path) -> str:
    """Derive a stable, filesystem-safe label when no project name is declared."""
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", directory.name).strip("._-")
    if not value:
        return "project"
    return value if value[0].isalpha() else "project-" + value


def configuration_name(data: dict, config: Path) -> str:
    schema = data.get("schema", 1)
    if type(schema) is not int or schema != 1:
        raise DevtoolError("unsupported configuration schema; expected 1")
    info = fields(data.get("project", {}), {"name"}, "project")
    return identifier(info.get("name", project_name(config.parent)), "project name")


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


def read_identity(config: Path) -> Project:
    """Read only the project identity; history and direct commands need no providers."""
    config = config.resolve()
    with config.open("rb") as stream:
        data = tomllib.load(stream)
    return Project(configuration_name(data, config), config.parent, {}, {}, {})


def read_project(config: Path, *, allow_providers=False) -> Project:
    config = config.resolve()
    with config.open("rb") as stream:
        data = tomllib.load(stream)
    fields(data, {"schema", "project", "defaults", "parameters", "aliases", "tasks", "targets", "providers", "commands"}, "configuration")
    name = configuration_name(data, config)
    defaults = fields(data.get("defaults", {}), {"module"}, "defaults")
    module = identifier(defaults.get("module", "all"), "default module")
    data = extend_config(data, config, allow_providers, name)
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
    for key, value in mapping(data.get("commands", {}), "commands").items():
        identifier(key, "command name")
        tasks[key] = Task(key, commands=parse_commands(value, f"commands.{key}", shortcut=True))
    for key, value in mapping(data.get("tasks", {}), "tasks").items():
        if key in tasks:
            raise DevtoolError(f"duplicate task {key!r} in commands and tasks")
        identifier(key, "task name")
        spec = fields(value, {"description", "dependencies", "commands", "cwd", "env", "secret_env", "resources", "timeout", "artifacts", "target", "transfers"}, f"task {key}")
        description = spec.get("description", "")
        if not isinstance(description, str):
            raise DevtoolError(f"description for {key} must be a string")
        deps = strings(spec.get("dependencies", []), f"{key}.dependencies")
        if len(set(deps)) != len(deps):
            raise DevtoolError(f"duplicate dependencies in {key}")
        commands = parse_commands(spec.get("commands", []), f"{key}.commands")
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
