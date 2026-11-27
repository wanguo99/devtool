"""Prepare stripped runtime ELF trees while preserving loaded bytes and originals."""
from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

from ..model import DevtoolError
from ..runtime import external_environment
from .tree import tree_identity


def loaded_identity(path: Path):
    with path.open("rb") as stream:
        header=stream.read(64)
        if header[:4]!=b"\x7fELF":
            return None
        if len(header)<52 or header[4] not in (1,2) or header[5] not in (1,2):
            raise DevtoolError(f"unsupported ELF header: {path}")
        wide=header[4]==2; order="<" if header[5]==1 else ">"
        layout=order+("HHIQQQIHHHHHH" if wide else "HHIIIIIHHHHHH")
        try:
            kind,machine,_,entry,phoff,_,flags,ehsize,phentsize,phnum,_,_,_=struct.unpack_from(layout,header,16)
        except struct.error as exc:
            raise DevtoolError(f"invalid ELF header: {path}") from exc
        if kind not in (2,3):  # Only runtime executables/shared objects.
            return None
        pformat=order+("IIQQQQQQ" if wide else "IIIIIIII")
        length=path.stat().st_size
        if not phnum or phnum==65535 or phentsize<struct.calcsize(pformat) or phoff+phentsize*phnum>length:
            raise DevtoolError(f"invalid ELF program header table: {path}")
        segments=[]
        # Strip may change ELF section-table metadata in the first mapped page.
        ignored=((40,48),(58,64)) if wide else ((32,36),(46,52))
        for i in range(phnum):
            stream.seek(phoff+i*phentsize);values=struct.unpack(pformat,stream.read(struct.calcsize(pformat)))
            if values[0]!=1: continue
            if wide: _,pflags,offset,vaddr,paddr,filesz,memsz,align=values
            else: _,offset,vaddr,paddr,filesz,memsz,pflags,align=values
            if offset+filesz>length or filesz>memsz:
                raise DevtoolError(f"invalid ELF load segment: {path}")
            digest=hashlib.sha256();remaining=filesz;position=offset;stream.seek(offset)
            while remaining:
                chunk=bytearray(stream.read(min(remaining,1024*1024)))
                if not chunk: raise DevtoolError(f"truncated ELF segment: {path}")
                for a,b in ignored:
                    start,end=max(a,position),min(b,position+len(chunk))
                    if start<end: chunk[start-position:end-position]=b"\0"*(end-start)
                digest.update(chunk);position+=len(chunk);remaining-=len(chunk)
            segments.append((offset,vaddr,paddr,filesz,memsz,pflags,align,digest.hexdigest()))
        if not segments:
            raise DevtoolError(f"ELF executable has no loadable segments: {path}")
        return (header[4],header[5],kind,machine,entry,flags,tuple(segments))


def strip_tree(source: Path, destination: Path, program="strip"):
    source=source.absolute();destination=destination.absolute()
    original_tree=tree_identity(source)["sha256"]
    if destination.exists() or destination.is_symlink() or destination.resolve().is_relative_to(source.resolve()):
        raise DevtoolError("strip destination must be a new directory outside the source tree")
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".strip-",dir=destination.parent) as staging:
        tree=Path(staging)/"payload";shutil.copytree(source,tree,symlinks=True)
        stripped=[]
        for file in sorted(tree.rglob("*")):
            if file.is_symlink() or not file.is_file(): continue
            identity=loaded_identity(file)
            if identity is None: continue
            original=file.stat().st_size
            subprocess.run([program,"--strip-debug",str(file)],check=True,env=external_environment(executable=program))
            if loaded_identity(file)!=identity:
                raise DevtoolError(f"strip changed loaded ELF content: {file.relative_to(tree)}")
            stripped.append({"path":file.relative_to(tree).as_posix(),"before":original,"after":file.stat().st_size})
        if tree_identity(source)["sha256"]!=original_tree:
            raise DevtoolError("strip source changed while preparing the release tree")
        if destination.exists() or destination.is_symlink():
            raise DevtoolError("strip destination appeared during processing")
        tree.rename(destination)
    return {"source":str(source),"destination":str(destination),"elf":stripped}
