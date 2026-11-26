"""Command line interface for project-defined tasks."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tomllib

from . import __version__
from .config import CONFIG, find_config, read_project
from .model import DevtoolError, identifier
from .planner import action_task, make_plan
from .runner import execute

ACTIONS = ("clone", "update", "doctor", "build", "test", "deploy", "start", "run", "stop",
           "status", "logs", "rollback", "export", "import")


def task_arguments(parser):
    parser.add_argument("--set", dest="overrides", action="append", default=[], metavar="NAME=VALUE",
                        help="override a declared non-secret project parameter")
    parser.add_argument("--dry-run", action="store_true", help="print the plan without executing")


def action_parsers(subparsers):
    for action in ACTIONS:
        item = subparsers.add_parser(action, help=f"run the project's {action} task")
        item.add_argument("module", nargs="?", help="project module (default from configuration)")
        task_arguments(item)
    task = subparsers.add_parser("task", help="execute a named project task")
    task.add_argument("name")
    task_arguments(task)


def parser():
    root = argparse.ArgumentParser(prog="devtool", description="Project-defined engineering task runner")
    root.add_argument("--version", action="version", version=__version__)
    root.add_argument("--project", metavar="PATH", help="project directory or TOML file (default: search upward)")
    sub = root.add_subparsers(dest="command", required=True)
    action_parsers(sub)
    plan = sub.add_parser("plan", help="print a read-only execution plan")
    action_parsers(plan.add_subparsers(dest="planned", required=True))
    sub.add_parser("list", help="list available tasks and aliases")
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
    name = identifier(name or directory.name, "project name (use --name to override)")
    destination = directory / CONFIG
    content = f'''schema = 1

[project]
name = "{name}"

[tasks."test.all"]
description = "Replace this example with your project's checks"
commands = [["python3", "-c", "print('devtool ready')"]]
'''
    with destination.open("x", encoding="utf-8") as stream:
        stream.write(content)
    print(destination)


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "init":
            init_project(args.project, args.name)
            return 0
        project = read_project(find_config(args.project))
        if args.command == "list":
            for key, task in sorted(project.tasks.items()):
                print(f"{key}\t{task.description}")
            for key, target in sorted(project.aliases.items()):
                print(f"{key}\t(alias for {target})")
            return 0
        action = args.planned if args.command == "plan" else args.command
        requested = args.name if action == "task" else action_task(project, action, args.module)
        plan = make_plan(project, requested, overrides(args.overrides))
        if args.command == "plan" or args.dry_run:
            print(json.dumps(plan.public(), indent=2, ensure_ascii=False))
            return 0
        return execute(plan)
    except KeyboardInterrupt:
        print("devtool: interrupted", file=sys.stderr)
        return 130
    except (DevtoolError, OSError, tomllib.TOMLDecodeError) as exc:
        print(f"devtool: {exc}", file=sys.stderr)
        return 2
