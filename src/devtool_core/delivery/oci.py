"""Send or load verified OCI image candidates without activating services."""
from __future__ import annotations

import json
from pathlib import Path
import shlex
import tempfile

from ..model import DevtoolError
from ..runtime import run_checked
from ..runtime.docker import docker_identity, image_ref
from ..runtime.targets import remote_child, ssh_base
from .oci_layout import identity_digest, reconstruct, stage_archive
from .rsync import rsync_options
from .ssh import remote_helper


def load_candidate(cache, digest):
    with tempfile.TemporaryDirectory(prefix="devtool-oci-") as directory:
        archive = Path(directory) / "image.tar"
        manifest = reconstruct(cache, archive, digest)
        current = docker_identity(manifest["image"], missing_ok=True)
        if current and current != manifest["identity"]:
            raise DevtoolError("target image tag already refers to another image; use a unique candidate tag")
        if not current:
            run_checked(["docker","image","load","--input",str(archive)])
        if docker_identity(manifest["image"]) != manifest["identity"]:
            raise DevtoolError("loaded image identity differs from candidate")
    print(json.dumps({"transport":"oci-delta", "image":manifest["image"], "identity":manifest["identity"]}),flush=True)


def send_candidate(target, image, destination):
    image_ref(image)
    identity = docker_identity(image)
    current = docker_identity(image, target, missing_ok=True)
    if current == identity:
        print(json.dumps({"transport":"oci-delta", "image":image, "identity":identity,"already_present":True}),flush=True)
        return
    if current:
        raise DevtoolError("target candidate tag already refers to another image")
    full = remote_child(target.workdir,destination)
    with tempfile.TemporaryDirectory(prefix="devtool-oci-") as directory:
        path=Path(directory)
        archive=path/"image.tar"
        run_checked(["docker","image","save","--output",str(archive),image])
        staged=path/"staged"
        manifest=stage_archive(archive,staged,image,identity)
        if docker_identity(image)!=identity:
            raise DevtoolError("candidate image tag changed during export")
        digest=identity_digest(manifest)
        remote_helper(target,["prepare-tree","--root",target.workdir,"--destination",destination])
        run_checked([*rsync_options(),"-e",shlex.join(ssh_base(target)),"--",str(staged)+"/",target.host+":"+full+"/"])
        remote_helper(target,["load-oci","--path",full,"--sha256",digest])
        if docker_identity(image,target)!=identity:
            raise DevtoolError("target candidate identity mismatch")
        print(json.dumps({"transport":"oci-delta","image":image,"identity":identity,
                          "archive_bytes":archive.stat().st_size,"payload_bytes":sum(e["size"] for e in manifest["entries"])}),flush=True)
