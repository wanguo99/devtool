"""Expand declarative source groups into ordinary engine tasks."""
from __future__ import annotations

from pathlib import Path
import re

from ..model import DevtoolError, Task, identifier, strings, text
from ..runtime import helper_command
from .paths import SHA, source_path


def source_tasks(raw, root: Path, *, actions=("clone", "update")):
    """Translate source declarations into ordinary engine tasks, not a second runner."""
    if not isinstance(raw, dict):
        raise DevtoolError("sources must be a table")
    generated = {}
    groups = {"all": []}
    paths = set()
    for name, item in raw.items():
        identifier(name, "source name")
        if not isinstance(item, dict) or set(item) - {"url", "path", "branch", "revision", "groups", "default", "submodules"}:
            raise DevtoolError(f"invalid source {name}")
        url = text(item.get("url"), f"sources.{name}.url")
        path = text(item.get("path", "source/" + name), f"sources.{name}.path")
        if "{{" in path:
            raise DevtoolError("source checkout paths must be fixed to prevent overlapping destinations")
        destination = source_path(root, path, check_layout=bool(actions))
        if any(destination == previous or destination.is_relative_to(previous) or previous.is_relative_to(destination) for previous in paths):
            raise DevtoolError("source checkout paths overlap")
        paths.add(destination)
        if re.match(r"https?://[^/]+@",url,re.I):
            raise DevtoolError("do not embed credentials in source URLs")
        branch, revision = item.get("branch", ""), item.get("revision", "")
        if not isinstance(branch, str) or not isinstance(revision, str):
            raise DevtoolError(f"invalid branch/revision in source {name}")
        if branch and revision:
            raise DevtoolError(f"source {name} must choose branch or revision, not both")
        if revision and "{{" not in revision and not SHA.fullmatch(revision):
            raise DevtoolError(f"source {name} revision must be a full commit SHA")
        included, submodules = item.get("default", True), item.get("submodules", False)
        if type(included) is not bool or type(submodules) is not bool:
            raise DevtoolError(f"source {name} default/submodules must be boolean")
        members = strings(item.get("groups", []), f"sources.{name}.groups")
        for group in (*members, name):
            identifier(group, "source group")
            if group == "all":
                raise DevtoolError("source group 'all' is reserved for the default selection")
            if name not in groups.setdefault(group, []):
                groups[group].append(name)
        if included:
            groups["all"].append(name)
        for action in actions:
            command = [*helper_command("sources"), action, "--root", str(root), "--path", path, "--url", url]
            if branch:
                command += ["--branch", branch]
            if revision:
                command += ["--revision", revision]
            if submodules:
                command.append("--submodules")
            key = f"source.{action}.{name}"
            generated[key] = Task(key, f"{action} source {name}", commands=(tuple(command),),tools=("git",))
    for group, names in groups.items():
        if not names:
            continue
        for action in actions:
            key = f"{action}.{group}"
            generated[key] = Task(key, f"{action} source group {group}", dependencies=tuple(f"source.{action}.{name}" for name in names))
    return generated
