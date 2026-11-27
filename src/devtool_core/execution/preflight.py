"""Local executable resolution and non-mutating command checks."""
from __future__ import annotations

import os
from pathlib import Path
import shutil

from ..model import Plan, Step


def command_path(step: Step, env):
    command = step.argv[0]
    if os.sep in command:
        candidate = Path(command)
        path = candidate if candidate.is_absolute() else step.cwd / candidate
        return str(path) if path.is_file() and os.access(path, os.X_OK) else None
    # PATH may contain entries relative to the step's working directory.
    search = os.pathsep.join(str(Path(entry) if Path(entry).is_absolute() else step.cwd / entry)
                             for entry in env.get("PATH", os.defpath).split(os.pathsep))
    return shutil.which(command, path=search)


def inspect_plan(plan: Plan):
    """Read-only local preflight; missing generated paths are reported, not created."""
    result = []
    for step in plan.all_steps():
        env = {**os.environ, **step.env}
        missing = [name for name in step.secret_env.values() if not os.environ.get(name)]
        result.append({"task": step.task, "index": step.index,
                       "cwd_exists": step.cwd.is_dir(), "command_available": bool(command_path(step, env)),
                       "missing_secret_references": missing,
                       "missing_tools": [tool for tool in step.tools if not shutil.which(tool)]})
    return result
