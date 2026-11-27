"""Verified full Docker image bundles for offline environments."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import tarfile
import tempfile

from ..artifacts.archive import pack_directory,unpack_directory,read_members,json_member
from ..artifacts.identity import digest_file
from ..model import DevtoolError
from ..runtime.docker import docker_identity, image_ref, normalized_tag
from ..runtime import run_checked


def archive_tags(archive_path: Path, images: dict[str,str]):
    expected={normalized_tag(tag):identity for tag,identity in images.items()}
    if len(expected)!=len(images): raise DevtoolError("duplicate equivalent image tags")
    with tarfile.open(archive_path,mode="r:*") as archive:
        members=read_members(archive)
        if "manifest.json" not in members: raise DevtoolError("Docker archive has no image manifest")
        manifest=json_member(archive,members["manifest.json"])
        if not isinstance(manifest,list): raise DevtoolError("invalid Docker archive manifest")
        configs={}
        for item in manifest:
            if not isinstance(item,dict) or not isinstance(item.get("RepoTags"),list) or not item["RepoTags"] or not isinstance(item.get("Config"),str):
                raise DevtoolError("invalid Docker image manifest entry")
            config=members.get(item["Config"])
            if config is None or not config.isfile() or config.size>16*1024*1024:
                raise DevtoolError("missing Docker image config")
            with archive.extractfile(config) as stream:
                config_digest=hashlib.file_digest(stream,"sha256").hexdigest()
            for tag in item["RepoTags"]:
                normalized=normalized_tag(tag)
                if normalized in configs or normalized not in expected:
                    raise DevtoolError("Docker archive has unexpected or duplicate image tags")
                configs[normalized]=config_digest
        if set(configs)!=set(expected): raise DevtoolError("Docker archive does not include all requested images")
        oci_ids={}
        if "index.json" in members:
            index=json_member(archive,members["index.json"])
            descriptors=index.get("manifests") if isinstance(index,dict) else None
            if not isinstance(descriptors,list): raise DevtoolError("invalid OCI image index")
            for descriptor in descriptors:
                if not isinstance(descriptor,dict):raise DevtoolError("invalid OCI descriptor")
                annotations=descriptor.get("annotations",{})
                tag=normalized_tag(annotations.get("io.containerd.image.name") or annotations.get("org.opencontainers.image.ref.name")) if isinstance(annotations,dict) else ""
                identity=descriptor.get("digest","")
                if tag in oci_ids or tag not in expected or not isinstance(identity,str) or not re.fullmatch(r"sha256:[0-9a-f]{64}",identity):
                    raise DevtoolError("unexpected OCI tag or image digest")
                member=members.get("blobs/sha256/"+identity.split(":",1)[1])
                if member is None or not member.isfile() or member.size>16*1024*1024:
                    raise DevtoolError("missing OCI descriptor blob")
                with archive.extractfile(member) as stream:
                    if hashlib.file_digest(stream,"sha256").hexdigest()!=identity.split(":",1)[1]:
                        raise DevtoolError("OCI descriptor digest mismatch")
                oci_ids[tag]=identity
            if set(oci_ids)!=set(expected): raise DevtoolError("OCI and Docker manifests contain different tags")
        for tag,identity in expected.items():
            if not isinstance(identity,str) or not re.fullmatch(r"sha256:[0-9a-f]{64} [A-Za-z0-9_/-]+",identity):
                raise DevtoolError("invalid expected image identity")
            digest=identity.split()[0]
            if digest not in {"sha256:"+configs[tag],oci_ids.get(tag)}:
                raise DevtoolError("Docker save image identity does not match the selected candidate")
        if "repositories" in members:
            repos=json_member(archive,members["repositories"])
            if not isinstance(repos,dict) or any(not isinstance(value,dict) for value in repos.values()):
                raise DevtoolError("invalid repositories metadata")
            actual={normalized_tag(f"{repo}:{tag}") for repo,tags in repos.items() for tag in tags}
            if actual-set(expected):raise DevtoolError("unexpected tag in repositories metadata")


def export_images(output:Path, images):
    images=tuple(image_ref(image) for image in images)
    if not images or len(set(images))!=len(images):raise DevtoolError("specify unique image tags to export")
    if output.exists() or output.is_symlink():raise DevtoolError("image bundle already exists")
    identities={image:docker_identity(image) for image in images}
    with tempfile.TemporaryDirectory(prefix="devtool-images-") as temp:
        tree=Path(temp)/"payload";tree.mkdir();saved=tree/"images.tar"
        run_checked(["docker","image","save","--output",str(saved),*images])
        archive_tags(saved,identities)
        if {image:docker_identity(image) for image in images}!=identities:
            raise DevtoolError("image tags changed while exporting")
        (tree/"images.json").write_text(json.dumps({"schema":1,"kind":"docker-images","images":identities,"archive_sha256":digest_file(saved)},sort_keys=True))
        pack_directory(tree,output)
    return {"bundle":str(output),"images":identities}


def import_images(source:Path):
    with tempfile.TemporaryDirectory(prefix="devtool-images-") as temp:
        tree=Path(temp)/"restored";unpack_directory(source,tree)
        metadata=tree/"images.json";saved=tree/"images.tar"
        if not metadata.is_file() or metadata.stat().st_size>16*1024*1024 or not saved.is_file():raise DevtoolError("invalid image bundle")
        record=json.loads(metadata.read_text())
        if not isinstance(record,dict) or record.get("schema")!=1 or record.get("kind")!="docker-images" or not isinstance(record.get("images"),dict) or not record["images"] or record.get("archive_sha256")!=digest_file(saved):
            raise DevtoolError("image bundle manifest mismatch")
        images=record["images"]
        for image in images:image_ref(image)
        archive_tags(saved,images)
        missing=[]
        for image,identity in images.items():
            current=docker_identity(image,missing_ok=True)
            if current is None:missing.append(image)
            elif current!=identity:raise DevtoolError(f"existing tag {image} points to a different image")
        if missing:run_checked(["docker","image","load","--input",str(saved)])
        if {image:docker_identity(image) for image in images}!=images:
            raise DevtoolError("loaded image identities differ from the bundle")
    return {"bundle":str(source),"images":images,"loaded":bool(missing)}
