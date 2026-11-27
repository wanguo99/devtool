"""Resolve typed defaults, render templates and track consumed parameters."""
from __future__ import annotations

from datetime import datetime, timezone
import os
import platform
import re

from ..model import DevtoolError, PLACEHOLDER, Project


def derived_default(kind, project):
    if kind == "half_cpus":
        try: count=len(os.sched_getaffinity(0))
        except (AttributeError,OSError): count=os.cpu_count() or 1
        return max(1,count//2)
    if kind == "host_arch":
        machine=platform.machine().lower()
        return {"x86_64":"amd64","aarch64":"arm64"}.get(machine,machine)
    if kind == "utc_tag":
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ").lower()
    if kind == "project_root": return str(project.root)
    raise DevtoolError(f"unsupported derived default {kind}")


TOKENS = re.compile(r"\{\{\{\{|\}\}\}\}|" + PLACEHOLDER.pattern + r"|\{\{|\}\}")


class ParameterResolver:
    """Per-plan parameter state; no mutation of shared project configuration."""

    def __init__(self, project: Project, overrides: dict[str, str] | None = None):
        self.project = project
        self.overrides = overrides or {}
        unknown = set(self.overrides) - set(project.parameters)
        if unknown:
            raise DevtoolError("unknown parameters: " + ", ".join(sorted(unknown)))
        self.values = {
            name: spec.parse(self.overrides[name], name) if name in self.overrides else spec.default
            for name, spec in project.parameters.items()
        }
        self.used = {}

    def value(self, key):
        if key not in self.values:
            raise DevtoolError(f"unknown parameter {key!r}")
        spec = self.project.parameters[key]
        if self.values[key] is None and spec.derive:
            self.values[key] = spec.parse(derived_default(spec.derive, self.project), key)
        if self.values[key] is None:
            raise DevtoolError(f"missing parameter {key!r}; specify --set {key}=VALUE")
        self.used[key] = self.values[key]
        return self.values[key]

    def render(self, text):
        # Escaped braces and substituted values are literal output.
        def substitute(match):
            token = match.group(0)
            if token in ("{{{{", "}}}}"):
                return token[:2]
            if match.group(1) is None:
                raise DevtoolError(f"invalid unresolved parameter in {text!r}")
            item = self.value(match.group(1))
            return str(item).lower() if isinstance(item, bool) else str(item)

        return TOKENS.sub(substitute, text)

    def condition(self, when):
        return all(self.value(key) in choices for key, choices in when.items())

    def check_unused(self):
        unused = set(self.overrides) - set(self.used)
        if unused:
            raise DevtoolError("unused parameters for this task: " + ", ".join(sorted(unused)))
