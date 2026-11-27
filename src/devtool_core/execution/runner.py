"""Orchestrate a plan, recording outcomes and artifacts."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

from ..artifacts.identity import describe
from ..model import Plan, DevtoolError
from .process import LOG_LIMIT, Timeout, run_step
from .secrets import resolve_environment, secret_values
from .state import StateStore, now, state_directory


class UnknownOutcome(DevtoolError):
    pass


def execute(plan: Plan, *, state_root: Path | None = None, log_limit=LOG_LIMIT, json_output=False) -> int:
    if log_limit < 0:
        raise DevtoolError("log limit must be nonnegative")
    store = StateStore(state_root or state_directory(plan.project, plan.root))
    redactor = secret_values(plan)
    # Resolve every explicit reference before any command can mutate the project.
    for step in plan.all_steps():
        resolve_environment(step)
    with store.acquire(plan.resources):
        directory, record = store.create(redactor.data(plan.public()))
        print(f"[devtool] operation {record['id']}", file=sys.stderr, flush=True)
        code = 0
        current = None
        steps_by_task = {}
        for step in plan.steps:
            steps_by_task.setdefault(step.task, []).append(step)
        def logged(step,phase="command"):
            nonlocal current
            label=f"{len(record['steps'])+1:03d}-{step.task}-{phase}-{step.index}.log"
            current={"task":step.task,"index":step.index,"phase":phase,"status":"RUNNING","started_at":now(),"log":label}
            record["steps"].append(current);store.save(record)
            print(redactor.text(f"[{step.task}:{phase}:{step.index}] {shlex.join(step.argv)}"),file=sys.stderr,flush=True)
            fd=os.open(directory/label,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,"w",encoding="utf-8") as stream:
                result,truncated=run_step(step,stream,redactor,log_limit,sys.stderr if json_output else None)
            current.update(status="SUCCEEDED" if result==0 else "FAILED",exit_code=result,finished_at=now(),log_truncated=truncated)
            store.save(record);current=None
            if step.target_kind=="ssh" and result==255:
                raise UnknownOutcome("SSH connection failed or was lost; inspect the target before retrying")
            return result

        try:
            for name in plan.tasks:
                missing = [tool for tool in plan.required_tools.get(name,()) if not shutil.which(tool)]
                if missing:
                    raise DevtoolError(f"missing tools for {name}: {', '.join(missing)}")
                for path in plan.required_paths.get(name, ()):
                    if not path.resolve().is_relative_to(plan.root.resolve()) or not path.exists():
                        raise DevtoolError(f"missing required input for {name}: {path}")
                if name in plan.verify_manifests:
                    from ..artifacts.manifest import verify_manifest
                    for path in plan.verify_manifests[name]:
                        verify_manifest(plan.root,path.relative_to(plan.root))
                if name in plan.manifest_outputs and plan.manifest_outputs[name].exists():
                    raise DevtoolError(f"immutable candidate manifest already exists: {plan.manifest_outputs[name]}")
                failure=0
                for step in steps_by_task.get(name, ()):
                    failure=logged(step)
                    if failure:
                        code=failure
                        record["failed_step"]={"task":name,"index":step.index,"exit_code":failure}
                        for recovery in plan.recovery_steps.get(name,()):
                            if logged(recovery,"on_failure"): break
                        break
                # Configured recovery/cleanup applies to known synchronous outcomes,
                # not cancellation or a timed-out/unknown remote operation.
                cleanup_failure=0
                for cleanup in plan.cleanup_steps.get(name,()):
                    result=logged(cleanup,"cleanup")
                    cleanup_failure=cleanup_failure or result
                code=failure or cleanup_failure
                if code: raise DevtoolError(f"task {name} exited with {code}")
                for path in plan.artifacts.get(name, ()):
                    record["artifacts"].append(redactor.data({"task": name, **describe(path, plan.root)}))
                if name in plan.images:
                    from ..runtime.docker import docker_identity
                    for image in plan.images[name]:
                        record["artifacts"].append(redactor.data({"task":name,"type":"image","image":image,"identity":docker_identity(image)}))
                if name in plan.manifest_outputs:
                    from ..artifacts.manifest import create_manifest
                    output=plan.manifest_outputs[name]
                    created=create_manifest(plan.root,output.relative_to(plan.root),
                                            [path.relative_to(plan.root).as_posix() for path in plan.artifacts.get(name,())],
                                            plan.images.get(name,()))
                    record["artifacts"].append(redactor.data({"task":name,"type":"manifest","path":str(output),"sha256":created["sha256"]}))
                store.save(record)
            record["status"] = "SUCCEEDED"
        except KeyboardInterrupt:
            code = 130
            record.update(status="CANCELLED", error="interrupted")
        except UnknownOutcome as exc:
            code = 255
            record.update(status="INTERRUPTED_UNKNOWN",error=redactor.text(str(exc)))
        except Timeout as exc:
            code = 124
            record.update(status="TIMED_OUT", error=redactor.text(str(exc)))
        except (OSError, DevtoolError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            code = code or 1
            record.update(status="FAILED", error=redactor.text(str(exc)))
        finally:
            if current and current["status"] == "RUNNING":
                current.update(status=record["status"], exit_code=code, finished_at=now())
            record.update(exit_code=code, finished_at=now())
            store.save(record)
        if code:
            print(f"[devtool] {record.get('error', record['status'])}", file=sys.stderr, flush=True)
        if json_output:
            print(json.dumps(record, ensure_ascii=False, indent=2))
        return code
