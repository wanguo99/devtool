# Devtool

A small, project-defined engineering task runner for source preparation, building, testing, deployment and repeatable command automation. Devtool orchestrates existing project tools; it is not a replacement for a compiler, package manager or application deployment logic.

## Quick start

Python 3.11 or newer. No runtime Python dependencies.

From this repository:

```sh
./devtool list
./devtool plan test
./devtool test
./devtool --project examples list
./devtool --project examples plan task prepare
./devtool --project examples build web --set message=hello
```

Install the distribution to use `devtool` from another project, e.g. `pipx install .`, or invoke the repository's `devtool` launcher by absolute path. `--project PATH` selects a directory or a configuration file. Otherwise the tool searches upward from the current working directory for `devtool.toml`.

For a new project, run `devtool init` in its root (existing configuration is never overwritten). Define named tasks using TOML:

```toml
schema = 1

[project]
name = "example"

[parameters.profile]
type = "string"
default = "release"
choices = ["debug", "release"]

[tasks."test.all"]
commands = [["python3", "-m", "unittest", "discover"]]

[tasks."build.app"]
commands = [["cmake", "--build", "build", "--config", "{{profile}}"]]
cwd = "."

[tasks."build.all"]
dependencies = ["build.app"]

[tasks.check-build]
dependencies = ["test.all", "build.all"]
```

`devtool build app` resolves `build.app`; `devtool build` resolves `build.all` (or `build`), and `devtool task check-build` resolves a custom task. Dependencies execute once in deterministic order. Task names and aliases are listed by `devtool list`. `devtool plan build app --set profile=debug` (or `devtool build app --dry-run`) prints JSON without executing commands or writing state. Values are substituted into individual argument strings, never evaluated as shell syntax. Use a checked-in script when a task requires a pipeline or shell logic. Commands run relative to the selected project's root; task cwd cannot escape the project. `--set` applies only to declared, referenced non-secret parameters. Integer and boolean parameters are also supported.

Built-in action names are conventions: `clone`, `update`, `doctor`, `build`, `test`, `deploy`, `start`, `run`, `stop`, `status`, `logs`, `rollback`, `export`, `import`. Projects choose which ones to implement. `[aliases]` can map a previous action name such as `"update.all"` to an existing task. Deploy, source update and service start are separate operations unless a project explicitly declares dependencies. A failed command stops the operation and preserves its exit code. Only execute configurations from projects you trust.

## Development and roadmap

- Stage 1 (implemented): configuration, dependency graph, CLI, local plans and execution.
- Stage 2 (implemented): operation history, logs, resource locks, timeouts, artifacts and preflight.
- Stage 3 (implemented): explicit local/SSH/container execution, rsync and Registry staging.
- Stage 4: project providers, portable integration examples and automation interfaces.

Project-specific build, rollout, data migration and rollback policies stay with each project. The shared core has no product-specific paths, credentials or deployment assumptions.

## Operation records and execution controls

```toml
[tasks."build.app"]
commands = [["python3", "scripts/build.py"]]
resources = ["project", "compiler"]
timeout = 3600
artifacts = ["dist/app"]
env = { BUILD_MODE = "release" }

[tasks."deploy.app"]
commands = [["python3", "scripts/deploy.py"]]
secret_env = { APP_TOKEN = "MY_DEPLOY_TOKEN" }
resources = ["project", "deployment"]
```

- `timeout` is an optional per-command wall-clock limit in seconds. Omit it for an unbounded build. Ctrl-C stops the owned local subprocess group. An interrupted external operation may require project-specific reconciliation; Devtool does not automatically retry a deployment.
- `resources` declares locks held for the entire plan. The default is `["project"]`, scoped to the project checkout. Explicitly empty `resources = []` is useful for independent read-only tasks. Tasks using custom locks must share the relevant lock name to exclude one another.
- `artifacts` declares project-relative files or directories to verify after that task succeeds. Their SHA-256, type and size are recorded (directory identities include relative names, modes, content and links). This records observed outputs, not a promise that an unchanged artifact was newly built.
- `secret_env` maps child environment names to host environment references. Missing references stop the plan before any commands run; stored plans contain references, not resolved values. Non-secret `env`/parameters must not contain credentials. Known values are redacted from console output and stored logs, but projects should still avoid printing secrets or encoded derivatives. Child commands inherit the caller's environment.

Plans include a canonical SHA-256 digest. `devtool plan build --check` or `devtool build --check` reports current local executable/cwd availability and missing secret references without executing the plan. A dependency may legitimately generate a directory or executable later; execution checks each step when it runs.

The runner creates private per-operation records and bounded step logs under `${XDG_STATE_HOME:-$HOME/.local/state}/devtool/<project>-<checkout-id>/` (or `DEVTOOL_STATE_HOME` as an absolute base directory). These are not build outputs. Use `devtool history --limit 10` or `devtool show <operation-id>` to inspect the recorded result. A RUNNING record whose owner disappeared is presented as `INTERRUPTED_UNKNOWN`: inspect the actual target before retrying. Linux/POSIX is the initial supported execution platform; the core assumes process groups and advisory file locks.

## Execution targets and staged transfer

Commands are local by default. A task may explicitly choose a named SSH target or an existing Docker container. Target workdirs are absolute, task `cwd` is relative to that workdir. For example:

```toml
[parameters.host]
type = "string"
default = "dev@example.invalid"

[targets.lab]
kind = "ssh"
host = "{{host}}"
workdir = "/srv/demo"
port = 22

[targets.builder]
kind = "docker"
container = "demo-builder"
workdir = "/app"

[tasks."status.all"]
target = "lab"
commands = [["docker", "compose", "ps"]]
resources = []

[tasks."test.container"]
target = "builder"
commands = [["python3", "-m", "unittest", "discover"]]
```

`devtool status --set host=dev@lab.example` executes the configured remote command; `devtool plan status` makes no SSH connection. SSH uses batch authentication and known-host verification; optional `identity` selects an existing local SSH key file. Docker targets address existing containers, without pulling or creating them. Target environments accept non-secret `env` only; use the project's existing target-side credential configuration for secrets. The first version supports SSH `user@hostname` and `user@IPv4`.

Transfer tasks stage files or images before executing subsequent commands. They never activate a service by themselves:

```toml
[tasks."stage.files"]
transfers = [
    { kind = "rsync", target = "lab", source = "dist/app", destination = "staging/app" }
]

[tasks."stage.images"]
transfers = [
    { kind = "registry", target = "lab", image = "registry.example.invalid/demo:1.0" }
]

[tasks."deploy.all"]
dependencies = ["stage.files"]
target = "lab"
commands = [["./rollout.sh", "staging/app"]]
```

- `rsync` requires installed compatible Devtool on the destination, SSH and rsync on both ends, and an existing target workspace. It prepares a dedicated child staging directory, performs checksum-based compressed incremental copy with partial-file reuse, verifies the source did not change and verifies the entire received tree SHA-256. It does **not** delete destination files; if stale extra files remain, verification fails. Use a dedicated staging directory; never use a live data directory. Symlinks must be relative and contained in the tree; special files are rejected.
- `registry` reuses the caller's Docker authentication. It pushes the explicit tagged local image, pulls the requested reference at the SSH target, and checks image ID and platform. `remote_image` can specify a different accessible registry alias. A mismatch fails before any subsequent task command.
- Transfer steps run before the task's own commands; dependencies can prepare artifacts first. The project is responsible for remote application ownership checks, a deployment lock spanning the actual activation, database compatibility, health checks and rollback. Devtool's core lock is local to a checkout, not a distributed lock.

`--check` examines local commands and transfer prerequisites only, without contacting external hosts. The target's CLI/daemon/path prerequisites are checked when the transfer or command is actually executed.
