"""Explicit, trusted project-local providers that return configuration fragments."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.util
from pathlib import Path
import sys

from ..model import DevtoolError


@dataclass(frozen=True)
class ProviderContext:
    root: Path
    config: Path
    project: str


def extend_config(data: dict, config: Path, allow: bool, project_name: str):
    providers = data.pop("providers", [])
    if not isinstance(providers,list) or any(not isinstance(value,str) or not value for value in providers):
        raise DevtoolError("providers must be a list of project-relative Python files")
    if providers and not allow:
        raise DevtoolError("this project declares Python providers; review them and pass --allow-providers to enable")
    root = config.parent
    context = ProviderContext(root,config,project_name)
    allowed = {"tasks","parameters","targets","aliases"}
    for relative in providers:
        item=Path(relative)
        source=(root/item).resolve()
        if item.is_absolute() or not source.is_relative_to(root) or source.suffix != ".py" or not source.is_file():
            raise DevtoolError(f"invalid provider path: {relative}")
        module_name = "_devtool_provider_" + hashlib.sha256(str(source).encode()).hexdigest()[:16]
        spec=importlib.util.spec_from_file_location(module_name,source)
        if spec is None or spec.loader is None:
            raise DevtoolError(f"cannot load provider: {relative}")
        module=importlib.util.module_from_spec(spec)
        sys.modules[module_name]=module
        try:
            # Providers are executable project code, not untrusted data. The
            # contract is to return data and not start tools or deploy services.
            exec(compile(source.read_bytes(), str(source), "exec"), module.__dict__)
            function=getattr(module,"provide",None)
            if not callable(function):
                raise DevtoolError("provider must define provide(context)")
            fragment=function(context)
        except Exception as error:
            raise DevtoolError(f"provider {relative} failed: {error}") from error
        finally:
            sys.modules.pop(module_name,None)
        if not isinstance(fragment,dict) or set(fragment)-allowed:
            raise DevtoolError(f"provider {relative} must return task/parameter/target/alias tables")
        for key, value in fragment.items():
            if not isinstance(value,dict) or not isinstance(data.setdefault(key,{}),dict):
                raise DevtoolError(f"invalid provider table {relative}:{key}")
            duplicates=set(data[key]) & set(value)
            if duplicates:
                raise DevtoolError(f"provider {relative} duplicates {key}: {', '.join(sorted(duplicates))}")
            data[key].update(value)
    return data
