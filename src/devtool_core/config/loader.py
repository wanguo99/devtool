"""Assemble a validated project and its complete task graph."""
from __future__ import annotations

import tomllib
from pathlib import Path
from dataclasses import replace

from ..model import DevtoolError, Project, Task, identifier, strings
from ..planning.graph import TaskGraph
from .identity import configuration_name
from .schema import fields, mapping, parse_command
from .parameters import parse_parameters, parse_options
from .targets import parse_targets
from .tasks import parse_tasks
from .providers import extend_config


def read_project(config: Path, *, allow_providers=False) -> Project:
    config = config.resolve()
    with config.open("rb") as stream:
        data = tomllib.load(stream)
    fields(data, {"schema", "project", "defaults", "parameters", "aliases", "tasks", "targets", "providers", "commands", "sources", "options", "backend"}, "configuration")
    name = configuration_name(data, config)
    defaults = fields(data.get("defaults", {}), {"module", "env"}, "defaults")
    module = identifier(defaults.get("module", "all"), "default module")
    data = extend_config(data, config, allow_providers, name)
    parameters = parse_parameters(data)
    options = parse_options(data, parameters)
    targets = parse_targets(data)
    tasks, global_env = parse_tasks(data, defaults, parameters, targets)
    backend_actions = ()
    if "backend" in data:
        backend = fields(data["backend"], {"command", "actions"}, "backend")
        command = parse_command(backend.get("command"), "backend.command")
        backend_actions = strings(backend.get("actions"), "backend.actions")
        if not backend_actions or len(set(backend_actions)) != len(backend_actions):
            raise DevtoolError("backend.actions must contain unique action names")
        for action in backend_actions:
            identifier(action, "backend action")
            if action in {"init", "list", "validate", "plan", "history", "show", "task", "exec", "artifact"}:
                raise DevtoolError(f"backend action {action!r} is reserved by Devtool")
            if any(other != action and other.startswith(action + ".") for other in backend_actions):
                raise DevtoolError(f"backend action {action!r} overlaps another backend action")
            if any(key == action or key.startswith(action + ".") for key in tasks):
                raise DevtoolError(f"backend action {action!r} conflicts with an explicit task")
            tasks[action] = Task(action, f"delegate {action} to the project backend",
                                 commands=((*command, action),), env=dict(global_env))
    if "sources" in data:
        from ..sources.groups import source_tasks
        generated = source_tasks(data["sources"], config.parent,
                                 actions=tuple(a for a in ("clone", "update") if a not in backend_actions))
        duplicates = set(tasks) & set(generated)
        if duplicates:
            raise DevtoolError("source-generated tasks conflict with explicit tasks: " + ", ".join(sorted(duplicates)))
        tasks.update({key:replace(task,env={**global_env,**task.env}) for key,task in generated.items()})
    if not tasks:
        raise DevtoolError("project defines no tasks")
    TaskGraph(tasks)
    aliases = mapping(data.get("aliases", {}), "aliases")
    for key, target in aliases.items():
        identifier(key, "alias")
        if (key in tasks or any(key.startswith(a + ".") for a in backend_actions)
                or not isinstance(target, str) or target not in tasks):
            raise DevtoolError(f"alias {key!r} conflicts with a task or points to an unknown task")
    return Project(name, config.parent, tasks, parameters, dict(aliases), module, targets, options, backend_actions)
