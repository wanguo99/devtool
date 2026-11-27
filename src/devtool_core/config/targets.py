"""Validate SSH and existing-container target declarations."""
from __future__ import annotations

from ..model import DevtoolError, Target, identifier, text
from .schema import fields, mapping


def parse_targets(data):
    targets = {}
    for key, value in mapping(data.get("targets", {}), "targets").items():
        identifier(key, "target name")
        if key == "local":
            raise DevtoolError("local is a reserved target name")
        spec = fields(value, {"kind", "workdir", "host", "port", "identity", "container", "engine"}, f"target {key}")
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
            engine = text(spec["engine"], f"{key}.engine") if "engine" in spec else ""
            targets[key] = Target(key, kind, workdir, host, port, identity, engine=engine)
        else:
            if any(name in spec for name in ("host", "port", "identity", "engine")):
                raise DevtoolError(f"Docker target {key} cannot specify SSH settings")
            targets[key] = Target(key, kind, workdir, container=text(spec.get("container"), f"{key}.container"))
    return targets
