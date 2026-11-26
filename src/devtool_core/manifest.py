"""Immutable build output manifests and verification before release operations."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from .artifacts import describe, digest_file
from .model import DevtoolError
from .transport import docker_identity, image_ref


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


def main(argv=None):
    parser=argparse.ArgumentParser(prog="devtool artifact",description=__doc__)
    actions=parser.add_subparsers(dest="action",required=True)
    create=actions.add_parser("create")
    create.add_argument("--root",type=Path,default=Path.cwd())
    create.add_argument("--output",required=True)
    create.add_argument("--file",action="append",default=[])
    create.add_argument("--image",action="append",default=[])
    verify=actions.add_parser("verify")
    verify.add_argument("--root",type=Path,default=Path.cwd())
    verify.add_argument("--manifest",required=True)
    strip=actions.add_parser("strip",help="copy and strip debug sections from runtime ELF files")
    strip.add_argument("--root",type=Path,default=Path.cwd())
    strip.add_argument("--source",required=True)
    strip.add_argument("--destination",required=True)
    strip.add_argument("--strip-command",default="strip")
    export=actions.add_parser("export-images",help="create a verified full offline Docker image bundle")
    export.add_argument("--root",type=Path,default=Path.cwd())
    export.add_argument("--output",required=True)
    export.add_argument("--image",action="append",required=True)
    load=actions.add_parser("import-images",help="verify and load a full offline Docker image bundle")
    load.add_argument("--root",type=Path,default=Path.cwd())
    load.add_argument("--input",required=True)
    fetch=actions.add_parser("fetch",help="download or repair a SHA-256-pinned cache file")
    fetch.add_argument("--root",type=Path,default=Path.cwd())
    fetch.add_argument("--url",required=True)
    fetch.add_argument("--output",required=True)
    fetch.add_argument("--sha256",required=True)
    fetch.add_argument("--size",type=int)
    try:
        args=parser.parse_args(argv)
        if args.action == "create":
            result=create_manifest(args.root,args.output,args.file,args.image)
        elif args.action == "verify":
            result=verify_manifest(args.root,args.manifest)
        elif args.action == "strip":
            from .strip_artifacts import strip_tree
            result=strip_tree(project_path(args.root,args.source),project_path(args.root,args.destination),args.strip_command)
        elif args.action == "export-images":
            from .image_bundle import export_images
            result=export_images(project_path(args.root,args.output),args.image)
        elif args.action == "import-images":
            from .image_bundle import import_images
            result=import_images(project_path(args.root,args.input))
        else:
            from .fetch import fetch_file
            result=fetch_file(args.url,project_path(args.root,args.output),args.sha256,args.size)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (ValueError,OSError,subprocess.SubprocessError) as exc:
        print(f"devtool artifact: {exc}",file=sys.stderr);return 1


if __name__ == "__main__":
    raise SystemExit(main())
