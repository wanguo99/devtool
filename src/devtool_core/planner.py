"""Resolve actions and render explicit argument vectors in dependency order."""
from __future__ import annotations

from pathlib import Path
from .graph import TaskGraph
from .model import DevtoolError, PLACEHOLDER, Project, Plan, Step, identifier


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


def make_plan(project: Project, requested: str, overrides: dict[str, str] | None = None, *, forwarded: tuple[str, ...] = ()) -> Plan:
    requested = project.aliases.get(requested, requested)
    ordered = TaskGraph(project.tasks).order((requested,))
    if forwarded and (len(project.tasks[requested].commands) != 1 or any(not isinstance(arg, str) or "\0" in arg for arg in forwarded)):
        raise DevtoolError("arguments after -- require a requested task with exactly one command")
    overrides = overrides or {}
    unknown = set(overrides) - set(project.parameters)
    if unknown:
        raise DevtoolError("unknown parameters: " + ", ".join(sorted(unknown)))
    values = {name: spec.parse(overrides[name], name) if name in overrides else spec.default
              for name, spec in project.parameters.items()}
    used = {}

    def render(value: str):
        def substitute(match):
            key = match.group(1)
            if key not in values or values[key] is None:
                raise DevtoolError(f"missing parameter {key!r}; specify --set {key}=VALUE")
            result = values[key]
            used[key] = result
            return str(result).lower() if isinstance(result, bool) else str(result)
        result = PLACEHOLDER.sub(substitute, value)
        if "{{" in result or "}}" in result:
            raise DevtoolError(f"invalid unresolved parameter in {value!r}")
        return result

    steps: list[Step] = []
    resources = set()
    artifacts = {}
    required_paths, verify_manifests, manifest_outputs, images, required_tools = {}, {}, {}, {}, {}

    def local_output(value):
        relative = Path(render(value))
        dest = (project.root / relative).resolve()
        if relative.is_absolute() or ".." in relative.parts or not dest.is_relative_to(project.root) or dest == project.root:
            raise DevtoolError(f"path escapes project or points to its root: {value}")
        return project.root / relative

    for task in ordered:
        folder = render(task.cwd)
        target = None
        if task.target != "local":
            from .executors import resolve_target
            target = resolve_target(project.targets[task.target], render, project.root)
        cwd = project.root
        if target is None:
            relative = Path(folder)
            if relative.is_absolute():
                raise DevtoolError(f"task {task.name} cwd must be relative to the project")
            cwd = (project.root / relative).resolve()
            if not cwd.is_relative_to(project.root):
                raise DevtoolError(f"task {task.name} cwd escapes the project")
        env = {key: render(value) for key, value in task.env.items()}
        resources.update(task.resources)
        index = 0
        for transfer in task.transfers:
            from .executors import resolve_target
            from .transport import transfer_command
            index += 1
            remote_target = resolve_target(project.targets[transfer["target"]], render, project.root) if "target" in transfer else None
            args = transfer_command(transfer, remote_target, render, project.root)
            tools = {"rsync": ("ssh", "rsync"), "registry": ("ssh", "docker"),
                     "oci-delta": ("ssh", "rsync", "docker")}.get(transfer["kind"], ())
            steps.append(Step(task.name, index, args, project.root, {}, {}, task.timeout,
                              remote_target.name if remote_target else "local", "transfer", tuple(dict.fromkeys((*tools,*task.tools)))))
        for argv in task.commands:
            index += 1
            args = tuple(render(arg) for arg in argv)
            if task.name == requested:
                args += tuple(forwarded)
            if not args[0]:
                raise DevtoolError(f"empty executable in {task.name}")
            if target is not None:
                from .executors import target_command
                args = target_command(target, args, folder, env)
                steps.append(Step(task.name, index, args, cwd, {}, {}, task.timeout, target.name, target.kind, task.tools))
            else:
                steps.append(Step(task.name, index, args, cwd, env, task.secret_env, task.timeout, tools=task.tools))
        if task.tools:
            required_tools[task.name] = task.tools
        if task.artifacts:
            artifacts[task.name] = tuple(local_output(value) for value in task.artifacts)
        if task.requires:
            required_paths[task.name] = tuple(local_output(value) for value in task.requires)
        if task.verify_manifests:
            verify_manifests[task.name] = tuple(local_output(value) for value in task.verify_manifests)
        if task.manifest:
            manifest_outputs[task.name] = local_output(task.manifest)
        if task.images:
            from .transport import image_ref
            images[task.name] = tuple(image_ref(render(value)) for value in task.images)
    unused = set(overrides) - set(used)
    if unused:
        raise DevtoolError("unused parameters for this task: " + ", ".join(sorted(unused)))
    return Plan(project.name, project.root, requested, tuple(t.name for t in ordered), tuple(steps), used, tuple(sorted(resources)), artifacts, required_paths=required_paths, verify_manifests=verify_manifests,
                manifest_outputs=manifest_outputs, images=images, required_tools=required_tools)
