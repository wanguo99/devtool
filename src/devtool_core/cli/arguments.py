"""Common CLI grammar, project flags and explicit parameter overrides."""
from __future__ import annotations

import argparse

from .. import __version__
from ..model import DevtoolError


ACTIONS = ("clone", "update", "doctor", "build", "test", "deploy", "start", "run", "stop",
           "status", "logs", "rollback", "export", "import")


def task_arguments(parser, options=()):
    parser.add_argument("--set", dest="overrides", action="append", default=[], metavar="NAME=VALUE",
                        help="override a declared non-secret project parameter")
    parser.add_argument("--dry-run", action="store_true", help="print the plan without executing")
    parser.add_argument("--check", action="store_true", help="read-only local input/command preflight")
    parser.add_argument("--json", action="store_true", help="print operation JSON; stream command output to stderr")
    for flag,option in dict(options).items():
        dest="project_option_"+flag.replace("-","_")
        if option.value is None:
            parser.add_argument("--"+flag,dest=dest,action="append",help=f"set project parameter {option.parameter}")
        else:
            value=str(option.value).lower() if isinstance(option.value,bool) else str(option.value)
            parser.add_argument("--"+flag,dest=dest,action="append_const",const=value,help=f"set {option.parameter}={value}")


def action_parsers(subparsers, extra_actions=(), options=()):
    for action in (*ACTIONS, *extra_actions):
        item = subparsers.add_parser(action, help=f"run the project's {action} task")
        item.add_argument("module", nargs="?", help="project module (default from configuration)")
        task_arguments(item,options)
    task = subparsers.add_parser("task", help="execute a named project task")
    task.add_argument("name")
    task_arguments(task,options)
    direct = subparsers.add_parser("exec", help="run an explicit local command using the recorded executor")
    direct.add_argument("--timeout", type=int)
    direct.add_argument("--dry-run", action="store_true")
    direct.add_argument("--check", action="store_true")
    direct.add_argument("--json", action="store_true")
    direct.add_argument("argv", nargs=argparse.REMAINDER, help="-- COMMAND [ARG ...]")


CORE_COMMANDS = {"init", "list", "validate", "plan", "history", "show", "task", "exec", "artifact"}


def command_index(argv):
    """Locate the outer action without loading project code."""
    index = 0
    while index < len(argv):
        value = argv[index]
        if value == "--project":
            index += 2
        elif value.startswith("--project=") or value == "--allow-providers":
            index += 1
        else:
            break
    return index


def selected_action(argv):
    index=command_index(argv)
    if index < len(argv) and argv[index] == "plan":
        index += 1
    return argv[index] if index < len(argv) else ""


def parser(extra_actions=(), options=()):
    root = argparse.ArgumentParser(prog="devtool", description="Project-defined engineering command runner",
                                   epilog="Any configured command can be invoked by name; use devtool list. Arguments after -- are passed to a single-command task.",
                                   allow_abbrev=False)
    root.add_argument("--version", action="version", version=__version__)
    root.add_argument("--project", metavar="PATH", help="project directory or TOML file (default: search upward)")
    root.add_argument("--allow-providers", action="store_true", help="enable reviewed project-local Python providers")
    sub = root.add_subparsers(dest="command", required=True)
    action_parsers(sub, extra_actions,options)
    plan = sub.add_parser("plan", help="print a read-only execution plan")
    action_parsers(plan.add_subparsers(dest="planned", required=True), extra_actions,options)
    listing = sub.add_parser("list", help="list available tasks and aliases")
    listing.add_argument("--json", action="store_true")
    sub.add_parser("validate", help="validate configuration without executing tasks")
    sub.add_parser("artifact", help="create, verify or prepare artifact manifests")
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
