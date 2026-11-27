"""Resolve configured operations and render argument vectors in dependency order."""
from __future__ import annotations

from pathlib import Path
from .graph import TaskGraph
from .parameters import ParameterResolver
from ..model import DevtoolError, Project, Plan, Step, CommandStep, identifier


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


def make_plan(project: Project, requested: str, overrides: dict[str,str] | None=None, *, forwarded: tuple[str,...]=()) -> Plan:
    requested=project.aliases.get(requested,requested)
    graph=TaskGraph(project.tasks)
    if requested not in project.tasks:
        raise DevtoolError(f"unknown task {requested!r}")
    parameters = ParameterResolver(project, overrides)
    render, condition = parameters.render, parameters.condition

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
            from ..runtime.targets import resolve_target,target_command
            target=resolve_target(project.targets[target_name],render,project.root)
            return Step(task.name,index,target_command(target,argv,folder,env),project.root,{}, {},timeout,target.name,target.kind,task.tools)
        relative=Path(folder);cwd=(project.root/relative).resolve()
        if relative.is_absolute() or not cwd.is_relative_to(project.root):
            raise DevtoolError(f"task {task.name} cwd escapes the project")
        return Step(task.name,index,argv,cwd,env,secrets,timeout,tools=task.tools)

    for task in ordered:
        resources.update(task.resources);index=0
        for transfer in task.transfers:
            from ..runtime.targets import resolve_target
            from ..delivery.planning import transfer_command
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
            from ..runtime.docker import image_ref
            images[task.name]=tuple(image_ref(render(item)) for item in task.images)
    parameters.check_unused()
    return Plan(project.name,project.root,requested,tuple(task.name for task in ordered),tuple(steps),parameters.used,
                tuple(sorted(resources)),artifacts,required_paths=required_paths,verify_manifests=verify_manifests,
                manifest_outputs=manifest_outputs,images=images,required_tools=required_tools,
                recovery_steps=recovery_steps,cleanup_steps=cleanup_steps)
