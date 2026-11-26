"""Fetch an explicitly identified file into a verified project cache."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit
from urllib.request import urlopen

from .artifacts import digest_file
from .model import DevtoolError
from .transport import HEX


def fetch_file(url:str,destination:Path,sha256:str,size:int|None=None):
    parsed=urlsplit(url)
    if parsed.scheme not in ("https","http","file") or parsed.username or parsed.password:
        raise DevtoolError("fetch URL must be HTTP(S) or file without embedded credentials")
    if not HEX.fullmatch(sha256) or size is not None and size<0:raise DevtoolError("fetch requires valid SHA-256 and optional size")
    if destination.is_symlink() or destination.exists() and not destination.is_file():raise DevtoolError("fetch destination must be a regular file")
    if destination.is_file() and (size is None or destination.stat().st_size==size) and digest_file(destination)==sha256:
        return {"path":str(destination),"sha256":sha256,"cached":True}
    destination.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix=".download-",dir=destination.parent);temporary=Path(name)
    digest=hashlib.sha256();total=0
    try:
        with os.fdopen(fd,"wb") as stream,urlopen(url,timeout=60) as response:
            while chunk:=response.read(1024*1024):
                total+=len(chunk)
                if size is not None and total>size:raise DevtoolError("download exceeds expected size")
                digest.update(chunk);stream.write(chunk)
            stream.flush();os.fsync(stream.fileno())
        if digest.hexdigest()!=sha256 or size is not None and total!=size:raise DevtoolError("download does not match expected content identity")
        if destination.is_symlink():raise DevtoolError("fetch destination changed to symlink")
        os.replace(temporary,destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {"path":str(destination),"sha256":sha256,"bytes":total,"cached":False}
