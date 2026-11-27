"""Validate typed parameters, derived defaults and CLI option mappings."""
from __future__ import annotations

import re

from ..model import DevtoolError, NAME, SENSITIVE, Parameter, Option
from .schema import fields, mapping


def parse_parameters(data):
    parameters = {}
    for key, value in mapping(data.get("parameters", {}), "parameters").items():
        if not NAME.fullmatch(key) or SENSITIVE.search(key):
            raise DevtoolError(f"invalid parameter name: {key}")
        spec = fields(value, {"type", "default", "choices", "description", "derive"}, f"parameter {key}")
        kind = spec.get("type", "string")
        if kind not in ("string", "integer", "boolean"):
            raise DevtoolError(f"unknown parameter type for {key}: {kind!r}")
        choices = spec.get("choices", [])
        if not isinstance(choices, list):
            raise DevtoolError(f"choices for {key} must be an array")
        description = spec.get("description", "")
        if not isinstance(description, str):
            raise DevtoolError(f"description for {key} must be a string")
        parser = Parameter(kind)
        parsed = tuple(parser.parse(choice, key) for choice in choices)
        param = Parameter(kind, None, parsed, description)
        default = param.parse(spec["default"], key) if "default" in spec else None
        derive = spec.get("derive", "")
        derivations = {"half_cpus":"integer", "host_arch":"string", "utc_tag":"string", "project_root":"string"}
        if not isinstance(derive,str) or (derive and (derivations.get(derive)!=kind or "default" in spec)):
            raise DevtoolError(f"invalid derived default for {key}")
        parameters[key] = Parameter(kind, default, parsed, description, derive)
    return parameters


def parse_options(data, parameters):
    options = {}
    reserved = {"help","project","allow-providers","version","set","dry-run","check","json","timeout"}
    for flag,value in mapping(data.get("options",{}),"options").items():
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]*",flag) or flag in reserved:
            raise DevtoolError(f"invalid or reserved project option {flag}")
        if isinstance(value,str):
            name, constant = value, None
        else:
            item=fields(value,{"parameter","value"},f"option {flag}")
            name,constant=item.get("parameter"),item.get("value")
            if "value" not in item: raise DevtoolError(f"option {flag} requires a constant value")
        if not isinstance(name,str) or name not in parameters:
            raise DevtoolError(f"option {flag} references unknown parameter")
        if constant is not None:
            constant=parameters[name].parse(constant,name)
        options[flag]=Option(name,constant)
    return options
