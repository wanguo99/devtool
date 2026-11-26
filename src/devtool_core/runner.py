"""Run commands in plan order, stopping at the first failure."""
from __future__ import annotations

import os
import shlex
import subprocess
import sys

from .model import Plan, DevtoolError


def execute(plan: Plan) -> int:
    for step in plan.steps:
        if not step.cwd.is_dir():
            raise DevtoolError(f"working directory does not exist: {step.cwd}")
        print(f"[{step.task}:{step.index}] {shlex.join(step.argv)}", file=sys.stderr, flush=True)
        result = subprocess.run(step.argv, cwd=step.cwd, env={**os.environ, **step.env}, check=False)
        if result.returncode:
            return result.returncode if result.returncode > 0 else 128 - result.returncode
    return 0
