"""Immutable candidate manifests and content verification."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from .identity import describe, digest_file
from ..model import DevtoolError
from ..runtime.docker import docker_identity, image_ref


def project_path(root: Path, value: str | Path):
    root=root.resolve()
    relative=Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise DevtoolError(f"expected project-relative artifact path: {value}")
    path=root/relative
    if not path.resolve().is_relative_to(root) or path.resolve()==root:
        raise DevtoolError(f"artifact path escapes project: {value}")
    return path


def file_record(root,path):
    path=project_path(root,path)
    record=describe(path,root)
    record["path"]=path.relative_to(root.resolve()).as_posix()
    return record


def create_manifest(root: Path, output: str | Path, paths=(), images=()):
    root=root.resolve()
    destination=project_path(root,output)
    if destination.exists() or destination.is_symlink():
        raise DevtoolError("manifest output already exists; use a unique candidate name")
    paths=tuple(paths); images=tuple(images)
    if not paths and not images:
        raise DevtoolError("manifest needs at least one file/directory or image")
    if len(set(paths))!=len(paths) or len(set(images))!=len(images):
        raise DevtoolError("duplicate manifest artifacts")
    for path in paths:
        if destination.resolve().is_relative_to(project_path(root,path).resolve()):
            raise DevtoolError("manifest output cannot be included in its own artifact tree")
    records=[file_record(root,path) for path in paths]
    image_records=[{"image":image_ref(image),"identity":docker_identity(image)} for image in images]
    manifest={"schema":1,"kind":"devtool-artifact-manifest","files":records,"images":image_records}
    destination.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix=".manifest-",dir=destination.parent)
    temporary=Path(name)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as stream:
            json.dump(manifest,stream,ensure_ascii=False,indent=2,sort_keys=True)
            stream.write("\n")
            stream.flush();os.fsync(stream.fileno())
        os.link(temporary,destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {"path":str(destination),"sha256":digest_file(destination),**manifest}


def verify_manifest(root: Path, source: str | Path):
    root=root.resolve();path=project_path(root,source)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>16*1024*1024:
        raise DevtoolError("invalid artifact manifest file")
    manifest=json.loads(path.read_text())
    if (not isinstance(manifest,dict) or manifest.get("schema")!=1 or manifest.get("kind")!="devtool-artifact-manifest" or
            not isinstance(manifest.get("files"),list) or not isinstance(manifest.get("images"),list) or
            not (manifest["files"] or manifest["images"])):
        raise DevtoolError("invalid artifact manifest schema")
    seen_files=set();seen_images=set()
    for entry in manifest["files"]:
        if not isinstance(entry,dict) or not isinstance(entry.get("path"),str) or entry["path"] in seen_files:
            raise DevtoolError("invalid or duplicate manifest file entry")
        seen_files.add(entry["path"])
        if file_record(root,entry["path"])!=entry:
            raise DevtoolError(f"artifact differs from manifest: {entry['path']}")
    for entry in manifest["images"]:
        if (not isinstance(entry,dict) or set(entry)!={"image","identity"} or not isinstance(entry["image"],str) or
                not isinstance(entry["identity"],str) or entry["image"] in seen_images):
            raise DevtoolError("invalid or duplicate manifest image entry")
        seen_images.add(entry["image"])
        if docker_identity(image_ref(entry["image"]))!=entry["identity"]:
            raise DevtoolError(f"image differs from manifest: {entry['image']}")
    return {"path":str(path),"sha256":digest_file(path),**manifest}
