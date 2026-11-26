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


def make_plan(project: Project, requested: str, overrides: dict[str, str] | None = None) -> Plan:
    requested = project.aliases.get(requested, requested)
    ordered = TaskGraph(project.tasks).order((requested,))
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
    for task in ordered:
        folder = Path(render(task.cwd))
        if folder.is_absolute():
            raise DevtoolError(f"task {task.name} cwd must be relative to the project")
        cwd = (project.root / folder).resolve()
        if not cwd.is_relative_to(project.root):
            raise DevtoolError(f"task {task.name} cwd escapes the project")
        env = {key: render(value) for key, value in task.env.items()}
        resources.update(task.resources)
        for n, argv in enumerate(task.commands, 1):
            args = tuple(render(arg) for arg in argv)
            if not args[0]:
                raise DevtoolError(f"empty executable in {task.name}")
            steps.append(Step(task.name, n, args, cwd, env, task.secret_env, task.timeout))
        if task.artifacts:
            paths = []
            for artifact in task.artifacts:
                relative = Path(render(artifact))
                dest = (project.root / relative).resolve()
                if relative.is_absolute() or not dest.is_relative_to(project.root) or dest == project.root:
                    raise DevtoolError(f"artifact path escapes project or points to its root: {artifact}")
                paths.append(project.root / relative)
            artifacts[task.name] = tuple(paths)
    unused = set(overrides) - set(used)
    if unused:
        raise DevtoolError("unused parameters for this task: " + ", ".join(sorted(unused)))
    return Plan(project.name, project.root, requested, tuple(t.name for t in ordered), tuple(steps), used, tuple(sorted(resources)), artifacts)
