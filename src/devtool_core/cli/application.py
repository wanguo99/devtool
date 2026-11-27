"""Command line interface for project-defined tasks."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
import sys
import tomllib

from ..config import CONFIG, ConfigNotFound, find_config, read_project, read_identity, project_name
from ..model import DevtoolError, Project, Plan, Step, identifier, ID
from ..planning.planner import action_task, make_plan
from ..execution.runner import execute
from ..execution.preflight import inspect_plan
from ..execution.state import StateStore, state_directory
from ..execution.secrets import secret_values
from .arguments import ACTIONS, CORE_COMMANDS, command_index, selected_action, parser, overrides, backend_arguments


def init_project(path: str | None, name: str | None):
    directory = Path(path or Path.cwd()).expanduser().resolve()
    if not directory.is_dir():
        raise DevtoolError("init requires an existing directory")
    name = identifier(name or project_name(directory), "project name (use --name to override)")
    destination = directory / CONFIG
    content = f'''schema = 1

[project]
name = "{name}"

[commands]
# Replace this example with your project commands.
test = ["python3", "-c", "print('devtool ready')"]
# build = "make"
# deploy = "./scripts/deploy.sh"
# status = "docker compose ps"
'''
    with destination.open("x", encoding="utf-8") as stream:
        stream.write(content)
    print(destination)


def project_context(args, allow_adhoc=False):
    try:
        config = find_config(args.project)
        return read_identity(config) if allow_adhoc else read_project(config, allow_providers=args.allow_providers)
    except ConfigNotFound:
        if not allow_adhoc:
            raise
        directory = Path(args.project or Path.cwd()).expanduser().resolve()
        if not directory.is_dir():
            raise
        return Project("adhoc", directory, {}, {}, {})


def direct_plan(project, args):
    argv = list(args.argv)
    if argv and argv[0] == "--":
        argv.pop(0)
    if not argv or not argv[0] or any("\0" in item for item in argv):
        raise DevtoolError("exec requires -- COMMAND [ARG ...]")
    if args.timeout is not None and args.timeout < 1:
        raise DevtoolError("exec timeout must be positive")
    step = Step("exec", 1, tuple(argv), project.root, timeout=args.timeout)
    return Plan(project.name, project.root, "exec", ("exec",), (step,), {}, ("project",))


def finish_plan(plan, *, display=False, check=False, json_output=False):
    if display or check:
        data = plan.public()
        status = 0
        if check:
            checks = inspect_plan(plan)
            data["preflight"] = checks
            missing_paths = [str(path) for mapping in (plan.required_paths, plan.verify_manifests) for paths in mapping.values() for path in paths if not path.exists()]
            data["missing_required_paths"] = missing_paths
            missing_tools = [tool for tools in plan.required_tools.values() for tool in tools if not shutil.which(tool)]
            data["missing_required_tools"] = missing_tools
            status = 0 if not missing_paths and not missing_tools and all(item["cwd_exists"] and item["command_available"] and not item["missing_secret_references"] and not item["missing_tools"] for item in checks) else 1
        print(json.dumps(secret_values(plan).data(data), indent=2, ensure_ascii=False))
        return status
    return execute(plan, json_output=json_output)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    index=command_index(argv)
    if index<len(argv) and argv[index]=="artifact":
        from .artifact import main as artifact_main
        global_parser=argparse.ArgumentParser(add_help=False)
        global_parser.add_argument("--project")
        global_parser.add_argument("--allow-providers",action="store_true")
        prefix=global_parser.parse_args(argv[:index])
        arguments=argv[index+1:]
        if prefix.project and not any(a=="--root" or a.startswith("--root=") for a in arguments):
            project=Path(prefix.project).expanduser().resolve()
            arguments += ["--root",str(project if project.is_dir() else project.parent)]
        return artifact_main(arguments)
    if argv and argv[0] == "_internal":
        from .internal import internal_main
        return internal_main(argv[1:])
    action = selected_action(argv)
    extra = (action,) if ID.fullmatch(action) and action not in (*ACTIONS, *CORE_COMMANDS) else ()
    forwarded = ()
    if action != "exec" and "--" in argv:
        split = argv.index("--")
        forwarded = tuple(argv[split+1:])
        argv = argv[:split]
    try:
        preloaded=None
        # Project-specific flags are an optional configuration extension. Load
        # the project once before parsing them; never load providers for help.
        if ID.fullmatch(action) and (action not in CORE_COMMANDS or action == "task"):
            prefix_parser=argparse.ArgumentParser(add_help=False)
            prefix_parser.add_argument("--project")
            prefix_parser.add_argument("--allow-providers",action="store_true")
            prefix=prefix_parser.parse_args(argv[:command_index(argv)])
            if "--help" not in argv and "-h" not in argv:
                preloaded=project_context(prefix)
            elif action != "task":
                # Ordinary help must work without a project or provider execution.
                # A configured backend owns its own action-specific help.
                try:
                    config = find_config(prefix.project)
                    with config.open("rb") as stream:
                        raw = tomllib.load(stream)
                    backend = raw.get("backend", {})
                    actions = backend.get("actions", []) if isinstance(backend, dict) else []
                    if isinstance(actions, list) and action in actions and not raw.get("providers"):
                        preloaded = read_project(config)
                except (ConfigNotFound, tomllib.TOMLDecodeError):
                    pass
        if preloaded and action in preloaded.backend_actions:
            outer_index = command_index(argv)
            planned = argv[outer_index] == "plan"
            controls, backend = backend_arguments(argv[outer_index + 1 + int(planned):])
            plan = make_plan(preloaded, action, overrides(controls.overrides),
                             forwarded=(*backend, *forwarded))
            return finish_plan(plan, display=planned or controls.dry_run,
                               check=controls.check, json_output=controls.json)
        args=parser(extra,preloaded.options if preloaded else {}).parse_args(argv)
        if forwarded and action in {"init", "list", "validate", "history", "show"}:
            raise DevtoolError("arguments after -- are only for project tasks or exec")
        if args.command == "init":
            init_project(args.project, args.name)
            return 0
        action = args.planned if args.command == "plan" else args.command
        project = preloaded or project_context(args, allow_adhoc=action in ("exec","history","show"))
        if args.command in ("history", "show"):
            store = StateStore(state_directory(project.name, project.root))
            data = store.history(args.limit) if args.command == "history" else store.read(args.operation)
            print(json.dumps(data, indent=2, ensure_ascii=False))
            return 0
        if args.command in ("list","validate"):
            if args.command == "validate" or args.json:
                print(json.dumps({"schema":1,"project":project.name,"root":str(project.root),
                                  "tasks":[{"name":name,"description":task.description,"dependencies":list(task.dependencies)} for name,task in sorted(project.tasks.items())],
                                  "aliases":project.aliases,
                                  "options":{name:{"parameter":option.parameter,"value":option.value} for name,option in project.options.items()}},ensure_ascii=False,indent=2))
                return 0
            for key, task in sorted(project.tasks.items()):
                print(f"{key}\t{task.description}")
            for key, target in sorted(project.aliases.items()):
                print(f"{key}\t(alias for {target})")
            return 0
        if action == "exec":
            plan = direct_plan(project,args)
        else:
            requested = args.name if action == "task" else action_task(project, action, args.module)
            supplied=list(args.overrides)
            for flag,option in project.options.items():
                for value in getattr(args,"project_option_"+flag.replace("-","_"),None) or []:
                    supplied.append(f"{option.parameter}={value}")
            plan = make_plan(project, requested, overrides(supplied), forwarded=forwarded)
        return finish_plan(plan, display=args.command == "plan" or args.dry_run,
                           check=args.check, json_output=args.json)
    except KeyboardInterrupt:
        print("devtool: interrupted", file=sys.stderr)
        return 130
    except (DevtoolError, OSError, tomllib.TOMLDecodeError, json.JSONDecodeError) as exc:
        print(f"devtool: {exc}", file=sys.stderr)
        return 2
