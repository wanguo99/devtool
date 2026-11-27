"""Validate explicit image references and read Docker image identities."""
from __future__ import annotations

import re
import subprocess

from ..model import DevtoolError
from . import run_checked
from .targets import remote

IMAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]*:[A-Za-z0-9_][A-Za-z0-9_.-]*\Z")


def image_ref(value):
    if not IMAGE.fullmatch(value):
        raise DevtoolError("image transfer requires an explicit tagged image reference")
    return value


def docker_identity(image, target=None, *, missing_ok=False):
    argv = ["docker", "image", "inspect", "--format", "{{.Id}} {{.Os}}/{{.Architecture}}", image]
    try:
        result = (remote(target, argv, capture_output=True, text=True) if target else run_checked(argv, capture_output=True, text=True))
    except subprocess.CalledProcessError as exc:
        if missing_ok and any(mark in (exc.stderr or "").lower() for mark in ("no such image", "no such object")):
            return None
        raise
    value = result.stdout.strip()
    if not re.fullmatch(r"sha256:[0-9a-f]{64} [A-Za-z0-9_/-]+", value):
        raise DevtoolError("invalid or ambiguous Docker image identity")
    return value


def normalized_tag(value):
    if not isinstance(value,str):
        return ""
    if "/" not in value:
        return "docker.io/library/" + value
    first = value.split("/",1)[0]
    if first == "docker.io" and value.count("/") == 1:
        return "docker.io/library/" + value.split("/",1)[1]
    if "." not in first and ":" not in first and first != "localhost":
        return "docker.io/" + value
    return value
