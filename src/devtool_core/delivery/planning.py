"""Translate validated staging declarations into helper argument vectors."""
from __future__ import annotations

from pathlib import Path

from ..runtime.targets import remote_child
from ..model import DevtoolError
from ..runtime import helper_command
from ..runtime.docker import image_ref


def local_child(root: Path, value: str):
    path = Path(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise DevtoolError(f"transfer source must be project-relative: {value!r}")
    full = root / path
    if not full.resolve().is_relative_to(root.resolve()) or full.resolve() == root.resolve():
        raise DevtoolError(f"transfer source escapes project: {value!r}")
    return full


def target_flags(target):
    args = ["--host", target.host, "--port", str(target.port), "--workdir", target.workdir]
    if target.identity:
        args += ["--identity", target.identity]
    if target.engine:
        args += ["--engine", target.engine]
    return args


def transfer_command(transfer, target, render, root):
    kind = transfer["kind"]
    command = [*helper_command("transport"), kind]
    if target is not None:
        command += target_flags(target)
    if kind == "rsync":
        source = local_child(root, render(transfer["source"]))
        destination = render(transfer["destination"])
        remote_child(target.workdir, destination)
        command += ["--source", str(source), "--destination", destination]
    elif kind == "registry":
        image = image_ref(render(transfer["image"]))
        remote = image_ref(render(transfer.get("remote_image", transfer["image"])))
        command += ["--image", image, "--remote-image", remote]
    elif kind == "oci-delta":
        image = image_ref(render(transfer["image"]))
        destination = render(transfer["destination"])
        remote_child(target.workdir, destination)
        command += ["--image", image, "--destination", destination]
    elif kind in ("archive-pack", "archive-unpack"):
        command += ["--source", str(local_child(root,render(transfer["source"]))),
                    "--destination", str(local_child(root,render(transfer["destination"])))]
    else:
        raise DevtoolError(f"unsupported transfer: {kind}")
    return tuple(command)
