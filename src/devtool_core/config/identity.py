"""Find a configuration and read project identity without loading providers."""
from __future__ import annotations

import tomllib
import re
from pathlib import Path

from ..model import DevtoolError, Project, identifier
from .schema import fields

CONFIG = "devtool.toml"


class ConfigNotFound(DevtoolError):
    pass


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


def read_identity(config: Path) -> Project:
    """Read only the project identity; history and direct commands need no providers."""
    config = config.resolve()
    with config.open("rb") as stream:
        data = tomllib.load(stream)
    return Project(configuration_name(data, config), config.parent, {}, {}, {})
