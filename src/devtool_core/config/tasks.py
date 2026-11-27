"""Validate command shorthand, task steps, transfer fields and task policy."""
from __future__ import annotations

from ..model import DevtoolError, NAME, SENSITIVE, Task, CommandStep, identifier, strings, text
from .schema import fields, mapping, parse_command, parse_commands


def conditions(value, label, parameters):
    result={}
    for key,expect in mapping(value,label).items():
        if key not in parameters: raise DevtoolError(f"unknown condition parameter {key}")
        choices=expect if isinstance(expect,list) else [expect]
        if not choices: raise DevtoolError(f"empty condition in {label}")
        result[key]=tuple(parameters[key].parse(item,key) for item in choices)
    return result


def environment(value,label,secret=False):
    result=mapping(value,label)
    for key,item in result.items():
        if not NAME.fullmatch(key) or not isinstance(item,str) or "\0" in item or (not secret and SENSITIVE.search(key)) or (secret and not NAME.fullmatch(item)):
            raise DevtoolError(f"invalid environment entry in {label}")
    return dict(result)


def parse_transfers(value, key, targets):
    raw_transfers = value
    if not isinstance(raw_transfers, list):
        raise DevtoolError(f"{key}.transfers must be an array of tables")
    transfers = []
    for transfer in raw_transfers:
        if not isinstance(transfer, dict):
            raise DevtoolError(f"invalid transfer in {key}")
        kind = transfer.get("kind")
        if not isinstance(kind, str):
            raise DevtoolError(f"transfer kind must be a string in {key}")
        required = {"rsync": {"source", "destination", "target"},
                    "registry": {"image", "target"},
                    "oci-delta": {"image", "target", "destination"},
                    "archive-pack": {"source", "destination"},
                    "archive-unpack": {"source", "destination"}}.get(kind)
        if required is None:
            raise DevtoolError(f"unknown transfer kind in {key}: {kind!r}")
        optional = {"remote_image"} if kind == "registry" else set()
        fields(transfer, {"kind", *required, *optional}, f"{key}.transfer")
        if not required.issubset(transfer):
            raise DevtoolError(f"missing transfer fields in {key}: {', '.join(sorted(required - set(transfer)))}")
        for field, value in transfer.items():
            text(value, f"{key}.transfer.{field}")
        if "target" in required and (transfer["target"] not in targets or targets[transfer["target"]].kind != "ssh"):
            raise DevtoolError(f"transfer in {key} requires a named SSH target")
        transfers.append(dict(transfer))
    return transfers


def parse_tasks(data, defaults, parameters, targets):
    global_env=environment(defaults.get("env",{}),"defaults.env")
    tasks: dict[str, Task] = {}
    for key, value in mapping(data.get("commands", {}), "commands").items():
        identifier(key, "command name")
        tasks[key] = Task(key, commands=parse_commands(value, f"commands.{key}", shortcut=True),env=dict(global_env))
    for key, value in mapping(data.get("tasks", {}), "tasks").items():
        if key in tasks:
            raise DevtoolError(f"duplicate task {key!r} in commands and tasks")
        identifier(key, "task name")
        spec = fields(value, {"description", "dependencies", "commands", "cwd", "env", "secret_env", "resources", "timeout", "artifacts", "target", "transfers", "requires", "verify_manifests", "manifest", "images", "tools", "steps", "when", "on_failure", "cleanup"}, f"task {key}")
        description = spec.get("description", "")
        if not isinstance(description, str):
            raise DevtoolError(f"description for {key} must be a string")
        deps = strings(spec.get("dependencies", []), f"{key}.dependencies")
        if len(set(deps)) != len(deps):
            raise DevtoolError(f"duplicate dependencies in {key}")
        commands = parse_commands(spec.get("commands", []), f"{key}.commands")
        raw_steps=spec.get("steps",[])
        if not isinstance(raw_steps,list) or (commands and raw_steps):
            raise DevtoolError(f"task {key} must choose command list or step tables")
        command_steps=[]
        for i, raw in enumerate(raw_steps,1):
            label=f"{key}.steps[{i}]"
            item=fields(raw,{"command","cwd","env","secret_env","timeout","target","when"},label)
            step_target=item.get("target")
            if step_target is not None and (not isinstance(step_target,str) or step_target not in {"local",*targets}):
                raise DevtoolError(f"invalid target in {label}")
            timeout=item.get("timeout")
            if timeout is not None and (type(timeout) is not int or timeout<1):
                raise DevtoolError(f"invalid timeout in {label}")
            command_steps.append(CommandStep(parse_command(item.get("command"),label),
                                             text(item["cwd"],label) if "cwd" in item else None,
                                             environment(item.get("env",{}),label),environment(item.get("secret_env",{}),label,True),
                                             timeout,step_target,conditions(item.get("when",{}),label,parameters)))
        recovery=parse_commands(spec.get("on_failure",[]),f"{key}.on_failure")
        cleanup=parse_commands(spec.get("cleanup",[]),f"{key}.cleanup")
        transfers = parse_transfers(spec.get("transfers", []), key, targets)
        if not commands and not command_steps and not deps and not transfers and not any(spec.get(field) for field in ("requires","verify_manifests","manifest","artifacts","images","tools")):
            raise DevtoolError(f"task {key} has no configured operation")
        cwd = text(spec.get("cwd", "."), f"{key}.cwd")
        env = {**global_env,**mapping(spec.get("env", {}), f"{key}.env")}
        for k, v in env.items():
            if not NAME.fullmatch(k) or SENSITIVE.search(k) or not isinstance(v, str) or "\0" in v:
                raise DevtoolError(f"invalid environment entry in {key}")
        secret_env = mapping(spec.get("secret_env", {}), f"{key}.secret_env")
        for k, v in secret_env.items():
            if not NAME.fullmatch(k) or not isinstance(v, str) or not NAME.fullmatch(v) or k in env:
                raise DevtoolError(f"invalid secret environment reference in {key}")
        resources = strings(spec.get("resources", ["project"]), f"{key}.resources")
        for resource in resources:
            identifier(resource, "resource")
        timeout = spec.get("timeout")
        if timeout is not None and (type(timeout) is not int or timeout < 1):
            raise DevtoolError(f"timeout for {key} must be a positive integer in seconds")
        artifacts = strings(spec.get("artifacts", []), f"{key}.artifacts")
        target = spec.get("target", "local")
        if target != "local" and (not isinstance(target, str) or target not in targets):
            raise DevtoolError(f"unknown target for {key}: {target!r}")
        if target != "local" and secret_env:
            raise DevtoolError(f"remote/container task {key} must use target-side secret configuration")
        requires = strings(spec.get("requires", []), f"{key}.requires")
        manifests = strings(spec.get("verify_manifests", []), f"{key}.verify_manifests")
        manifest = text(spec["manifest"], f"{key}.manifest") if "manifest" in spec else ""
        images = strings(spec.get("images", []), f"{key}.images")
        tools = strings(spec.get("tools", []), f"{key}.tools")
        if target != "local" and (artifacts or manifest or images):
            raise DevtoolError(f"task {key} declares local outputs but uses a non-local target")
        if manifest and not (artifacts or images):
            raise DevtoolError(f"task {key} manifest needs artifacts or images")
        tasks[key] = Task(name=key, description=description, dependencies=deps, commands=commands, cwd=cwd,
                          env=dict(env), secret_env=dict(secret_env), resources=resources, timeout=timeout,
                          artifacts=artifacts, target=target, transfers=tuple(transfers), requires=requires,
                          verify_manifests=manifests, manifest=manifest, images=images, tools=tools, steps=tuple(command_steps), when=conditions(spec.get("when",{}),key,parameters),
                          on_failure=recovery, cleanup=cleanup)
    return (tasks, global_env)
