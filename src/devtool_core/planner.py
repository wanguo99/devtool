"""Resolve configured operations and render argument vectors in dependency order."""
from __future__ import annotations

from datetime import datetime, timezone
import os
import platform
import re
from pathlib import Path
from .graph import TaskGraph
from .model import DevtoolError, PLACEHOLDER, Project, Plan, Step, CommandStep, identifier


def action_task(project: Project, action: str, module: str | None = None) -> str:
    identifier(action, "action")
    if module is not None:
        identifier(module, "module")
    candidates = ([f"{action}.{module}"] if module is not None
                  else [f"{action}.{project.default_module}", action])
    for name in candidates:
        if name in project.tasks or name in project.aliases:
            return project.aliases.get(name, name)
    raise DevtoolError(f"no task for {action} {module or project.default_module}; use devtool list")


def derived_default(kind, project):
    if kind == "half_cpus":
        try: count=len(os.sched_getaffinity(0))
        except (AttributeError,OSError): count=os.cpu_count() or 1
        return max(1,count//2)
    if kind == "host_arch":
        machine=platform.machine().lower()
        return {"x86_64":"amd64","aarch64":"arm64"}.get(machine,machine)
    if kind == "utc_tag":
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ").lower()
    if kind == "project_root": return str(project.root)
    raise DevtoolError(f"unsupported derived default {kind}")


def make_plan(project: Project, requested: str, overrides: dict[str,str] | None=None, *, forwarded: tuple[str,...]=()) -> Plan:
    requested=project.aliases.get(requested,requested)
    graph=TaskGraph(project.tasks)
    if requested not in project.tasks:
        raise DevtoolError(f"unknown task {requested!r}")
    overrides=overrides or {}
    unknown=set(overrides)-set(project.parameters)
    if unknown: raise DevtoolError("unknown parameters: "+", ".join(sorted(unknown)))
    values={name:spec.parse(overrides[name],name) if name in overrides else spec.default for name,spec in project.parameters.items()}
    used={}

    def value(key):
        if key not in values: raise DevtoolError(f"unknown parameter {key!r}")
        if values[key] is None and project.parameters[key].derive:
            values[key]=project.parameters[key].parse(derived_default(project.parameters[key].derive,project),key)
        if values[key] is None: raise DevtoolError(f"missing parameter {key!r}; specify --set {key}=VALUE")
        used[key]=values[key]
        return values[key]

    def render(text):
        # Parse the original string once: escaped braces and parameter values
        # are literal output, not another round of template input.
        tokens = re.compile(r"\{\{\{\{|\}\}\}\}|" + PLACEHOLDER.pattern + r"|\{\{|\}\}")
        def substitute(match):
            token = match.group(0)
            if token in ("{{{{", "}}}}"):
                return token[:2]
            if match.group(1) is None:
                raise DevtoolError(f"invalid unresolved parameter in {text!r}")
            item=value(match.group(1))
            return str(item).lower() if isinstance(item,bool) else str(item)
        return tokens.sub(substitute,text)

    def condition(when):
        return all(value(key) in choices for key,choices in when.items())

    if not condition(project.tasks[requested].when):
        raise DevtoolError(f"requested task {requested!r} is disabled by its condition")
    ordered=graph.order((requested,),enabled=lambda task: condition(task.when))
    steps=[];resources=set();artifacts={};required_paths={};verify_manifests={};manifest_outputs={};images={};required_tools={};recovery_steps={};cleanup_steps={}

    def local_output(text):
        relative=Path(render(text));dest=(project.root/relative).resolve()
        if relative.is_absolute() or ".." in relative.parts or not dest.is_relative_to(project.root) or dest==project.root:
            raise DevtoolError(f"path escapes project or points to its root: {text}")
        return project.root/relative

    def command_step(task,spec,index,extra=()):
        folder=render(spec.cwd if spec.cwd is not None else task.cwd)
        target_name=spec.target or task.target
        env={key:render(item) for key,item in {**task.env,**spec.env}.items()}
        secrets={**task.secret_env,**spec.secret_env}
        if set(env)&set(secrets): raise DevtoolError(f"secret/non-secret environment conflict in {task.name}")
        timeout=spec.timeout or task.timeout
        argv=tuple(render(item) for item in spec.argv)+tuple(extra)
        if not argv[0]: raise DevtoolError(f"empty executable in {task.name}")
        if target_name!="local":
            if secrets: raise DevtoolError(f"remote step in {task.name} requires target-side credentials")
            from .executors import resolve_target,target_command
            target=resolve_target(project.targets[target_name],render,project.root)
            return Step(task.name,index,target_command(target,argv,folder,env),project.root,{}, {},timeout,target.name,target.kind,task.tools)
        relative=Path(folder);cwd=(project.root/relative).resolve()
        if relative.is_absolute() or not cwd.is_relative_to(project.root):
            raise DevtoolError(f"task {task.name} cwd escapes the project")
        return Step(task.name,index,argv,cwd,env,secrets,timeout,tools=task.tools)

    for task in ordered:
        resources.update(task.resources);index=0
        for transfer in task.transfers:
            from .executors import resolve_target
            from .transport import transfer_command
            index+=1
            remote_target=resolve_target(project.targets[transfer["target"]],render,project.root) if "target" in transfer else None
            args=transfer_command(transfer,remote_target,render,project.root)
            tools={"rsync":("ssh","rsync"),"registry":("ssh","docker"),"oci-delta":("ssh","rsync","docker")}.get(transfer["kind"],())
            steps.append(Step(task.name,index,args,project.root,{}, {},task.timeout,remote_target.name if remote_target else "local","transfer",tuple(dict.fromkeys((*tools,*task.tools)))))
        active=[spec for spec in (task.steps or tuple(CommandStep(argv) for argv in task.commands)) if condition(spec.when)]
        extra=forwarded if task.name==requested else ()
        if extra and (len(active)!=1 or any(not isinstance(item,str) or "\0" in item for item in extra)):
            raise DevtoolError("arguments after -- require a requested task with exactly one command")
        for spec in active:
            index+=1;steps.append(command_step(task,spec,index,extra))
        if task.on_failure: recovery_steps[task.name]=tuple(command_step(task,CommandStep(argv),i) for i,argv in enumerate(task.on_failure,1))
        if task.cleanup: cleanup_steps[task.name]=tuple(command_step(task,CommandStep(argv),i) for i,argv in enumerate(task.cleanup,1))
        if task.tools: required_tools[task.name]=task.tools
        if task.artifacts: artifacts[task.name]=tuple(local_output(item) for item in task.artifacts)
        if task.requires: required_paths[task.name]=tuple(local_output(item) for item in task.requires)
        if task.verify_manifests: verify_manifests[task.name]=tuple(local_output(item) for item in task.verify_manifests)
        if task.manifest: manifest_outputs[task.name]=local_output(task.manifest)
        if task.images:
            from .transport import image_ref
            images[task.name]=tuple(image_ref(render(item)) for item in task.images)
    unused=set(overrides)-set(used)
    if unused: raise DevtoolError("unused parameters for this task: "+", ".join(sorted(unused)))
    return Plan(project.name,project.root,requested,tuple(task.name for task in ordered),tuple(steps),used,
                tuple(sorted(resources)),artifacts,required_paths=required_paths,verify_manifests=verify_manifests,
                manifest_outputs=manifest_outputs,images=images,required_tools=required_tools,
                recovery_steps=recovery_steps,cleanup_steps=cleanup_steps)
