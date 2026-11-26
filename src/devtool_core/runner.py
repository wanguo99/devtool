"""Bounded logging, process-group cancellation, artifact checks and history."""
from __future__ import annotations

import os
import json
from pathlib import Path
import selectors
import shlex
import shutil
import signal
import subprocess
import sys
import time

from .artifacts import describe
from .model import Plan, Step, DevtoolError
from .secrets import Redactor, resolve_environment, secret_values
from .state import StateStore, now, state_directory
from .runtime import external_environment

LOG_LIMIT = 8 * 1024 * 1024
LINE_LIMIT = 64 * 1024


class Timeout(DevtoolError):
    pass


class UnknownOutcome(DevtoolError):
    pass


class BoundedOutput:
    def __init__(self, stream, redactor: Redactor, limit=LOG_LIMIT, console=None):
        self.stream = stream
        self.redactor = redactor
        self.limit = limit
        self.console = sys.stdout if console is None else console
        self.written = 0
        self.truncated = False
        self.pending = bytearray()
        self.discard_line = False

    def line(self, value: str):
        safe = self.redactor.text(value)
        print(safe, end="", file=self.console, flush=True)
        raw = safe.encode("utf-8", errors="replace")
        remaining = self.limit - self.written
        if remaining > 0 and raw:
            # A truncated UTF-8 tail must remain a valid text log.
            data = raw[:remaining].decode("utf-8", errors="ignore")
            self.stream.write(data)
            self.written += len(data.encode())
            self.stream.flush()
        if len(raw) > remaining and not self.truncated:
            self.truncated = True
            print("[devtool] log limit reached; remaining output is not persisted", file=sys.stderr, flush=True)

    def feed(self, raw: bytes):
        # Whole bounded lines are redacted before any bytes are exposed. An
        # overlong line is suppressed rather than leaking a split secret.
        for i, piece in enumerate(raw.split(b"\n")):
            if i:
                if self.discard_line:
                    self.line("[devtool] overlong output line omitted\n")
                else:
                    self.line(self.pending.decode("utf-8", errors="replace") + "\n")
                self.pending.clear()
                self.discard_line = False
            if not self.discard_line:
                if len(self.pending) + len(piece) > LINE_LIMIT:
                    self.pending.clear()
                    self.discard_line = True
                else:
                    self.pending.extend(piece)

    def finish(self):
        if self.discard_line:
            self.line("[devtool] overlong output line omitted\n")
        elif self.pending:
            self.line(self.pending.decode("utf-8", errors="replace") + "\n")
        self.pending.clear()


def stop_process(process):
    # The child was started in a new process group. Never signal unrelated PIDs.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=3)
    # The leader may have exited while a child in the same group is still alive.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


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


def run_step(step: Step, stream, redactor, log_limit, console=None):
    env = resolve_environment(step)
    if not step.cwd.is_dir():
        raise DevtoolError(f"working directory does not exist: {step.cwd}")
    if not command_path(step, env):
        raise DevtoolError(f"command not available: {step.argv[0]}")
    missing_tools = [tool for tool in step.tools if not shutil.which(tool)]
    if missing_tools:
        raise DevtoolError("missing transport tools: " + ", ".join(missing_tools))
    process = subprocess.Popen(step.argv, cwd=step.cwd, env=external_environment(env, executable=step.argv[0]), stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, start_new_session=True)
    output = BoundedOutput(stream, redactor, log_limit, console)
    started = time.monotonic()
    exited = None
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map() or process.poll() is None:
                if step.timeout is not None and time.monotonic() - started >= step.timeout:
                    raise Timeout(f"step timed out after {step.timeout} seconds")
                if process.poll() is not None:
                    exited = exited or time.monotonic()
                    # A deliberately detached service may still hold the pipe.
                    if time.monotonic() - exited > 0.5:
                        break
                for key, _ in selector.select(0.1):
                    chunk = os.read(key.fd, 8192)
                    if chunk:
                        output.feed(chunk)
                    else:
                        selector.unregister(key.fileobj)
            code = process.wait()
    except BaseException:
        stop_process(process)
        raise
    finally:
        output.finish()
        process.stdout.close()
    return (code if code >= 0 else 128 - code), output.truncated


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
                    from .manifest import verify_manifest
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
                    from .transport import docker_identity
                    for image in plan.images[name]:
                        record["artifacts"].append(redactor.data({"task":name,"type":"image","image":image,"identity":docker_identity(image)}))
                if name in plan.manifest_outputs:
                    from .manifest import create_manifest
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
