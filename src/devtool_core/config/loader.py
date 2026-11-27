"""Assemble a validated project and its complete task graph."""
from __future__ import annotations

import tomllib
from pathlib import Path
from dataclasses import replace

from ..model import DevtoolError, Project, identifier
from ..planning.graph import TaskGraph
from .identity import configuration_name
from .schema import fields, mapping
from .parameters import parse_parameters, parse_options
from .targets import parse_targets
from .tasks import parse_tasks
from .providers import extend_config


def read_project(config: Path, *, allow_providers=False) -> Project:
    config = config.resolve()
    with config.open("rb") as stream:
        data = tomllib.load(stream)
    fields(data, {"schema", "project", "defaults", "parameters", "aliases", "tasks", "targets", "providers", "commands", "sources", "options"}, "configuration")
    name = configuration_name(data, config)
    defaults = fields(data.get("defaults", {}), {"module", "env"}, "defaults")
    module = identifier(defaults.get("module", "all"), "default module")
    data = extend_config(data, config, allow_providers, name)
    parameters = parse_parameters(data)
    options = parse_options(data, parameters)
    targets = parse_targets(data)
    tasks, global_env = parse_tasks(data, defaults, parameters, targets)
    if "sources" in data:
        from ..sources.groups import source_tasks
        generated = source_tasks(data["sources"], config.parent)
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
        if key in tasks or not isinstance(target, str) or target not in tasks:
            raise DevtoolError(f"alias {key!r} conflicts with a task or points to an unknown task")
    return Project(name, config.parent, tasks, parameters, dict(aliases), module, targets, options)
