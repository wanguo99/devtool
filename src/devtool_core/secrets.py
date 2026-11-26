"""Resolve explicit environment references; redact known values from diagnostics."""
from __future__ import annotations

import os
import re
from .model import SENSITIVE, DevtoolError


class Redactor:
    def __init__(self, values=()):
        self.values = sorted({line for value in values if value for line in value.splitlines() if line},
                             key=len, reverse=True)

    def text(self, value: str):
        for secret in self.values:
            value = value.replace(secret, "[REDACTED]")
        return re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)\S+", r"\1[REDACTED]", value)

    def data(self, value):
        if isinstance(value, dict):
            return {key: self.data(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.data(item) for item in value]
        return self.text(value) if isinstance(value, str) else value


def secret_values(plan, environ=None):
    environ = os.environ if environ is None else environ
    known = [value for key, value in environ.items() if SENSITIVE.search(key) and len(value) >= 4]
    for step in plan.all_steps():
        for name in step.secret_env.values():
            if name in environ and environ[name]:
                known.append(environ[name])
    return Redactor(known)


def resolve_environment(step):
    env = {**os.environ, **step.env}
    for key, reference in step.secret_env.items():
        value = os.environ.get(reference)
        if not value:
            raise DevtoolError(f"required secret environment reference is not set: {reference}")
        env[key] = value
    return env
