"""Validate, stage and reconstruct content-addressed OCI archive layouts."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
import shutil
import tarfile

from ..artifacts.archive import read_members, member_name, MAX_METADATA, file_info
from ..artifacts.identity import HEX, digest_file
from ..model import DevtoolError
from ..runtime.docker import image_ref, normalized_tag


MANIFEST = "archive.json"


def identity_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def exact_file(root, name):
    name = member_name(name)
    if root.is_symlink():
        raise DevtoolError("OCI cache root is a symlink")
    path = root
    for part in Path(name).parts:
        path = path / part
        if path.is_symlink():
            raise DevtoolError(f"unexpected symlink in OCI cache: {name}")
    if not path.is_file():
        raise DevtoolError(f"missing OCI cache member: {name}")
    return path


def read_json(root, name):
    path = exact_file(root,name)
    if path.stat().st_size > MAX_METADATA:
        raise DevtoolError("OCI metadata too large")
    return json.loads(path.read_text())


def descriptor_path(descriptor, paths):
    if not isinstance(descriptor,dict) or not isinstance(descriptor.get("digest"),str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", descriptor["digest"]):
        raise DevtoolError("invalid OCI descriptor")
    path = "blobs/sha256/" + descriptor["digest"].split(":",1)[1]
    if path not in paths:
        raise DevtoolError("OCI descriptor references a missing blob")
    return path


def verify_docker_manifest(root: Path, paths, image, identity):
    if not {"manifest.json", "index.json", "oci-layout"}.issubset(paths):
        raise DevtoolError("Docker save archive lacks OCI layout; use registry or a full export instead")
    if any(path not in {"manifest.json","index.json","oci-layout","repositories"} and not re.fullmatch(r"blobs/sha256/[0-9a-f]{64}",path) for path in paths):
        raise DevtoolError("unexpected member in Docker OCI archive")
    if not isinstance(identity,str) or not re.fullmatch(r"sha256:[0-9a-f]{64} [A-Za-z0-9_/-]+",identity):
        raise DevtoolError("invalid candidate image identity")
    layout = read_json(root,"oci-layout")
    if not isinstance(layout,dict) or layout.get("imageLayoutVersion") != "1.0.0":
        raise DevtoolError("unsupported OCI layout version")
    manifest = read_json(root,"manifest.json")
    if not isinstance(manifest,list) or len(manifest) != 1 or not isinstance(manifest[0],dict):
        raise DevtoolError("OCI archive must contain exactly one requested image")
    tags = manifest[0].get("RepoTags")
    if not isinstance(tags,list) or len(tags)!=1 or normalized_tag(tags[0]) != normalized_tag(image):
        raise DevtoolError("OCI archive contains unexpected image tags")
    config = manifest[0].get("Config")
    layers = manifest[0].get("Layers")
    if not isinstance(config,str) or config not in paths or not config.startswith("blobs/sha256/") or not isinstance(layers,list):
        raise DevtoolError("invalid Docker manifest config")
    if any(not isinstance(layer,str) or not layer.startswith("blobs/sha256/") or layer not in paths for layer in layers):
        raise DevtoolError("OCI manifest references missing layers")
    index = read_json(root,"index.json")
    descriptors = index.get("manifests") if isinstance(index,dict) else None
    if not isinstance(descriptors,list) or len(descriptors) != 1:
        raise DevtoolError("only single-image OCI indexes are supported")
    descriptor = descriptors[0]
    first = descriptor_path(descriptor,paths)
    annotations = descriptor.get("annotations",{})
    if not isinstance(annotations,dict) or normalized_tag(annotations.get("io.containerd.image.name") or annotations.get("org.opencontainers.image.ref.name")) != normalized_tag(image):
        raise DevtoolError("OCI index tag differs from requested image")
    entry = read_json(root,first)
    # Some image stores export a one-platform nested index. Reject multiple
    # platforms/attestations rather than guessing which image will be loaded.
    visited = {first}
    while isinstance(entry,dict) and "manifests" in entry:
        children = entry["manifests"]
        if not isinstance(children,list) or len(children)!=1 or len(visited)>8:
            raise DevtoolError("multi-platform OCI archives are not supported by this adapter")
        child = descriptor_path(children[0],paths)
        if child in visited:
            raise DevtoolError("OCI manifest cycle")
        visited.add(child)
        entry = read_json(root,child)
    if not isinstance(entry,dict) or descriptor_path(entry.get("config"),paths) != config:
        raise DevtoolError("OCI config differs from Docker manifest")
    descriptor_layers = entry.get("layers")
    if not isinstance(descriptor_layers,list) or [descriptor_path(item,paths) for item in descriptor_layers] != layers:
        raise DevtoolError("OCI layers differ from Docker manifest")
    # Classic and containerd-backed Docker stores report different ID forms.
    expected = identity.split()[0].removeprefix("sha256:")
    if expected not in {config.rsplit("/",1)[1], *[path.rsplit("/",1)[1] for path in visited]}:
        raise DevtoolError("OCI descriptor/config does not match candidate ID")
    if "repositories" in paths:
        repositories = read_json(root,"repositories")
        if not isinstance(repositories,dict) or any(not isinstance(value,dict) for value in repositories.values()):
            raise DevtoolError("invalid legacy repositories metadata")
        actual = {normalized_tag(f"{repo}:{tag}") for repo, tags in repositories.items() for tag in tags}
        if actual and actual != {normalized_tag(image)}:
            raise DevtoolError("legacy repositories metadata contains unexpected tags")


def stage_archive(source: Path, destination: Path, image: str, identity: str):
    image_ref(image)
    destination.mkdir()
    payload = destination / "payload"
    payload.mkdir()
    entries = []
    with tarfile.open(source, mode="r:*") as archive:
        members = read_members(archive)
        for name, item in sorted(members.items()):
            if item.isdir():
                continue
            if not item.isfile() or ".devtool-partial" in Path(name).parts:
                raise DevtoolError("OCI archive must use regular files and directories")
            path = payload / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(item) as stream, path.open("xb") as out:
                shutil.copyfileobj(stream, out)
            digest = digest_file(path)
            if name.startswith("blobs/") and name != "blobs/sha256/"+digest:
                raise DevtoolError(f"OCI blob path does not match SHA-256: {name}")
            entries.append({"path": name, "size": item.size, "sha256": digest})
    paths = {entry["path"] for entry in entries}
    verify_docker_manifest(payload, paths, image, identity)
    manifest = {"schema": 1, "kind": "docker-oci-save", "image": image, "identity": identity, "entries": entries}
    data = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    if len(data.encode()) > MAX_METADATA:
        raise DevtoolError("OCI inventory too large")
    (destination / MANIFEST).write_text(data)
    return manifest


class DigestReader:
    def __init__(self, stream):
        self.stream = stream
        self.digest = hashlib.sha256()

    def read(self, amount=-1):
        data = self.stream.read(amount)
        self.digest.update(data)
        return data


def reconstruct(cache: Path, output: Path, expected: str):
    manifest_file = exact_file(cache, MANIFEST)
    if manifest_file.stat().st_size > MAX_METADATA:
        raise DevtoolError("OCI inventory too large")
    manifest = json.loads(manifest_file.read_text())
    if (not isinstance(manifest,dict) or manifest.get("schema") != 1 or manifest.get("kind") != "docker-oci-save" or
            not HEX.fullmatch(expected) or identity_digest(manifest) != expected):
        raise DevtoolError("OCI inventory digest mismatch")
    entries = manifest.get("entries")
    if not isinstance(entries,list) or not isinstance(manifest.get("image"),str) or not isinstance(manifest.get("identity"),str):
        raise DevtoolError("invalid OCI inventory")
    image_ref(manifest["image"])
    paths = set()
    if len(entries) > 200_000:
        raise DevtoolError("OCI inventory member limit exceeded")
    for entry in entries:
        if not isinstance(entry,dict) or set(entry) != {"path","size","sha256"}:
            raise DevtoolError("invalid OCI inventory entry")
        name = member_name(entry["path"])
        if (name in paths or type(entry["size"]) is not int or entry["size"] < 0 or
                not isinstance(entry["sha256"],str) or not HEX.fullmatch(entry["sha256"])):
            raise DevtoolError("invalid or duplicate OCI inventory entry")
        if name.startswith("blobs/") and name != "blobs/sha256/" + entry["sha256"]:
            raise DevtoolError("invalid content-addressed blob path")
        paths.add(name)
    payload = cache / "payload"
    if payload.is_symlink():
        raise DevtoolError("OCI payload cache is a symlink")
    verify_docker_manifest(payload, paths, manifest["image"], manifest["identity"])
    # Reconstruct exactly selected entries; stale blobs from earlier candidates are ignored.
    with output.open("xb") as out, tarfile.open(fileobj=out, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for entry in entries:
            path = exact_file(payload,entry["path"])
            if path.stat().st_size != entry["size"]:
                raise DevtoolError(f"OCI cache member size mismatch: {entry['path']}")
            with path.open("rb") as stream:
                reader = DigestReader(stream)
                archive.addfile(file_info(entry["path"],0o644,entry["size"]),reader)
                if reader.digest.hexdigest() != entry["sha256"] or stream.read(1):
                    raise DevtoolError(f"OCI cache member integrity mismatch: {entry['path']}")
    return manifest
