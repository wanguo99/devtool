"""Command line interface for project-defined tasks."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tomllib

from . import __version__
from .config import CONFIG, ConfigNotFound, find_config, read_project, read_identity, project_name
from .model import DevtoolError, Project, Plan, Step, identifier, ID
from .planner import action_task, make_plan
from .runner import execute, inspect_plan
from .state import StateStore, state_directory
from .secrets import secret_values

ACTIONS = ("clone", "update", "doctor", "build", "test", "deploy", "start", "run", "stop",
           "status", "logs", "rollback", "export", "import")


def task_arguments(parser):
    parser.add_argument("--set", dest="overrides", action="append", default=[], metavar="NAME=VALUE",
                        help="override a declared non-secret project parameter")
    parser.add_argument("--dry-run", action="store_true", help="print the plan without executing")
    parser.add_argument("--check", action="store_true", help="read-only local input/command preflight")
    parser.add_argument("--json", action="store_true", help="print operation JSON; stream command output to stderr")


def action_parsers(subparsers, extra_actions=()):
    for action in (*ACTIONS, *extra_actions):
        item = subparsers.add_parser(action, help=f"run the project's {action} task")
        item.add_argument("module", nargs="?", help="project module (default from configuration)")
        task_arguments(item)
    task = subparsers.add_parser("task", help="execute a named project task")
    task.add_argument("name")
    task_arguments(task)
    direct = subparsers.add_parser("exec", help="run an explicit local command using the recorded executor")
    direct.add_argument("--timeout", type=int)
    direct.add_argument("--dry-run", action="store_true")
    direct.add_argument("--check", action="store_true")
    direct.add_argument("--json", action="store_true")
    direct.add_argument("argv", nargs=argparse.REMAINDER, help="-- COMMAND [ARG ...]")


CORE_COMMANDS = {"init", "list", "validate", "plan", "history", "show", "task", "exec"}


def selected_action(argv):
    """Locate the action without loading project code or parsing forwarded arguments."""
    index = 0
    while index < len(argv):
        value = argv[index]
        if value == "--project":
            index += 2
        elif value.startswith("--project=") or value == "--allow-providers":
            index += 1
        else:
            break
    if index < len(argv) and argv[index] == "plan":
        index += 1
    return argv[index] if index < len(argv) else ""


def parser(extra_actions=()):
    root = argparse.ArgumentParser(prog="devtool", description="Project-defined engineering command runner",
                                   epilog="Any configured command can be invoked by name; use devtool list. Arguments after -- are passed to a single-command task.",
                                   allow_abbrev=False)
    root.add_argument("--version", action="version", version=__version__)
    root.add_argument("--project", metavar="PATH", help="project directory or TOML file (default: search upward)")
    root.add_argument("--allow-providers", action="store_true", help="enable reviewed project-local Python providers")
    sub = root.add_subparsers(dest="command", required=True)
    action_parsers(sub, extra_actions)
    plan = sub.add_parser("plan", help="print a read-only execution plan")
    action_parsers(plan.add_subparsers(dest="planned", required=True), extra_actions)
    listing = sub.add_parser("list", help="list available tasks and aliases")
    listing.add_argument("--json", action="store_true")
    sub.add_parser("validate", help="validate configuration without executing tasks")
    history = sub.add_parser("history", help="show operation records for this project")
    history.add_argument("--limit", type=int, default=20)
    show = sub.add_parser("show", help="show a single operation record")
    show.add_argument("operation")
    init = sub.add_parser("init", help="create a minimal devtool.toml without overwriting existing files")
    init.add_argument("--name", default=None)
    return root


def overrides(items: list[str]):
    values = {}
    for item in items:
        key, separator, value = item.partition("=")
        if not separator or key in values:
            raise DevtoolError("--set requires unique NAME=VALUE assignments")
        values[key] = value
    return values


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


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "_internal":
        from .runtime import internal_main
        return internal_main(argv[1:])
    action = selected_action(argv)
    extra = (action,) if ID.fullmatch(action) and action not in (*ACTIONS, *CORE_COMMANDS) else ()
    forwarded = ()
    if action != "exec" and "--" in argv:
        split = argv.index("--")
        forwarded = tuple(argv[split+1:])
        argv = argv[:split]
    args = parser(extra).parse_args(argv)
    try:
        if forwarded and action in {"init", "list", "validate", "history", "show"}:
            raise DevtoolError("arguments after -- are only for project tasks or exec")
        if args.command == "init":
            init_project(args.project, args.name)
            return 0
        action = args.planned if args.command == "plan" else args.command
        project = project_context(args, allow_adhoc=action in ("exec","history","show"))
        if args.command in ("history", "show"):
            store = StateStore(state_directory(project.name, project.root))
            data = store.history(args.limit) if args.command == "history" else store.read(args.operation)
            print(json.dumps(data, indent=2, ensure_ascii=False))
            return 0
        if args.command in ("list","validate"):
            if args.command == "validate" or args.json:
                print(json.dumps({"schema":1,"project":project.name,"root":str(project.root),
                                  "tasks":[{"name":name,"description":task.description,"dependencies":list(task.dependencies)} for name,task in sorted(project.tasks.items())],
                                  "aliases":project.aliases},ensure_ascii=False,indent=2))
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
            plan = make_plan(project, requested, overrides(args.overrides), forwarded=forwarded)
        if args.command == "plan" or args.dry_run or args.check:
            data = plan.public()
            status = 0
            if args.check:
                checks = inspect_plan(plan)
                data["preflight"] = checks
                status = 0 if all(check["cwd_exists"] and check["command_available"] and not check["missing_secret_references"] and not check["missing_tools"] for check in checks) else 1
            print(json.dumps(secret_values(plan).data(data), indent=2, ensure_ascii=False))
            return status
        return execute(plan, json_output=args.json)
    except KeyboardInterrupt:
        print("devtool: interrupted", file=sys.stderr)
        return 130
    except (DevtoolError, OSError, tomllib.TOMLDecodeError, json.JSONDecodeError) as exc:
        print(f"devtool: {exc}", file=sys.stderr)
        return 2
