"""Portable directory bundles with explicit member validation and atomic import."""
from __future__ import annotations

import gzip
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tarfile
import tempfile

from .model import DevtoolError
from .transport import tree_identity, HEX

MAX_MEMBERS = 200_000
MAX_METADATA = 16 * 1024 * 1024


def member_name(value):
    if not isinstance(value, str):
        raise DevtoolError("archive member path must be a string")
    name = PurePosixPath(value)
    if (not value or name.is_absolute() or not name.parts or ".." in name.parts or
            "\\" in value or "\0" in value or str(name) != value.rstrip("/")):
        raise DevtoolError(f"unsafe archive path: {value!r}")
    return str(name)


def read_members(archive):
    members = {}
    for item in archive:
        name = member_name(item.name)
        if name in members or len(members) >= MAX_MEMBERS:
            raise DevtoolError("duplicate archive path or member limit exceeded")
        if not (item.isfile() or item.isdir() or item.issym()):
            raise DevtoolError(f"unsupported archive member type: {name}")
        if item.mode & 0o7000:
            raise DevtoolError(f"special permission bits are not portable: {name}")
        members[name] = item
    return members


def json_member(archive, item):
    if not item.isfile() or item.size > MAX_METADATA:
        raise DevtoolError("invalid archive metadata member")
    with archive.extractfile(item) as stream:
        return json.load(stream)


def file_info(name, mode, size=0, kind=tarfile.REGTYPE, link=""):
    info = tarfile.TarInfo(name)
    info.type = kind
    info.mode = mode
    info.size = size
    info.linkname = link
    info.mtime = 0
    return info


def write_file(archive, name, source):
    mode = stat.S_IMODE(source.lstat().st_mode)
    if mode & 0o7000:
        raise DevtoolError(f"special permission bits are not portable: {source}")
    if source.is_symlink():
        archive.addfile(file_info(name, mode, kind=tarfile.SYMTYPE, link=os.readlink(source)))
    elif source.is_dir():
        archive.addfile(file_info(name, mode, kind=tarfile.DIRTYPE))
    elif source.is_file():
        with source.open("rb") as stream:
            archive.addfile(file_info(name, mode, source.stat().st_size), stream)
    else:
        raise DevtoolError(f"special file is not portable: {source}")


def pack_directory(source: Path, output: Path):
    source = source.absolute()
    output = output.absolute()
    if output.resolve().is_relative_to(source.resolve()):
        raise DevtoolError("bundle output must be outside its source tree")
    if output.exists() or output.is_symlink():
        raise DevtoolError(f"bundle output already exists: {output}")
    identity = tree_identity(source)
    manifest = {"schema": 1, "kind": "devtool-directory", "sha256": identity["sha256"],
                "bytes": identity["bytes"], "entries": identity["entries"]}
    metadata = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(prefix=".bundle-", dir=output.parent)
    temporary = Path(filename)
    try:
        with os.fdopen(fd, "wb") as stream, gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as compressed, \
                tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
            archive.addfile(file_info("manifest.json", 0o644, len(metadata)), io.BytesIO(metadata))
            write_file(archive, "payload", source)
            for path in sorted(source.rglob("*")):
                name = member_name("payload/" + path.relative_to(source).as_posix())
                write_file(archive, name, path)
        if tree_identity(source)["sha256"] != identity["sha256"]:
            raise DevtoolError("bundle source changed during export")
        # Hard-link publication is atomic and refuses an existing output path.
        os.link(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return manifest


def validate_payload(members):
    if "manifest.json" not in members or "payload" not in members or not members["payload"].isdir():
        raise DevtoolError("missing directory bundle manifest or payload")
    for name, item in members.items():
        if name in ("manifest.json", "payload"):
            continue
        if not name.startswith("payload/"):
            raise DevtoolError(f"unexpected bundle member: {name}")
        parent = str(PurePosixPath(name).parent)
        if parent not in members or not members[parent].isdir():
            raise DevtoolError(f"archive member has non-directory parent: {name}")
        if item.issym():
            link = PurePosixPath(item.linkname)
            if link.is_absolute() or not link.parts:
                raise DevtoolError(f"unsafe symbolic link: {name}")
            stack = list(PurePosixPath(name).parent.parts)
            for part in link.parts:
                if part == "..":
                    if len(stack) <= 1:
                        raise DevtoolError(f"symbolic link escapes bundle: {name}")
                    stack.pop()
                else:
                    stack.append(part)


def unpack_directory(source: Path, destination: Path):
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise DevtoolError(f"bundle destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".bundle-", dir=destination.parent) as temp:
        root = Path(temp)
        with tarfile.open(source, mode="r:*") as archive:
            members = read_members(archive)
            validate_payload(members)
            manifest = json_member(archive, members["manifest.json"])
            if (not isinstance(manifest, dict) or manifest.get("schema") != 1 or
                    manifest.get("kind") != "devtool-directory" or
                    not isinstance(manifest.get("sha256"), str) or not HEX.fullmatch(manifest["sha256"])):
                raise DevtoolError("invalid bundle manifest")
            directories = []
            for name in sorted(members, key=lambda n: (len(PurePosixPath(n).parts), n)):
                if name == "manifest.json":
                    continue
                item = members[name]
                path = root / name
                if item.isdir():
                    path.mkdir(mode=0o700)
                    directories.append((path, item.mode))
                elif item.issym():
                    path.symlink_to(item.linkname)
                else:
                    with archive.extractfile(item) as stream, path.open("xb") as out:
                        shutil.copyfileobj(stream, out)
                    path.chmod(item.mode)
            for path, mode in reversed(directories):
                path.chmod(mode)
        identity = tree_identity(root / "payload")
        if any(manifest.get(key) != identity[key] for key in ("sha256", "bytes", "entries")):
            raise DevtoolError("bundle content does not match its manifest")
        if destination.exists() or destination.is_symlink():
            raise DevtoolError("bundle destination appeared during import")
        (root / "payload").rename(destination)
    return manifest
