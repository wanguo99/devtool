"""Explicit image push/pull with identity verification."""
from __future__ import annotations

import json

from ..model import DevtoolError
from ..runtime import run_checked
from ..runtime.docker import docker_identity, image_ref
from ..runtime.targets import remote


def registry(target, image, remote_image):
    identity = docker_identity(image_ref(image))
    image_ref(remote_image)
    remote(target, ["docker", "info", "--format", "{{.ServerVersion}}"])
    run_checked(["docker", "push", image])
    remote(target, ["docker", "pull", remote_image])
    if docker_identity(remote_image, target) != identity:
        raise DevtoolError("remote image ID/platform does not match the local candidate")
    print(json.dumps({"transport": "registry", "image": remote_image, "identity": identity}), flush=True)
