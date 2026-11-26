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
- Stage 3: explicit local/remote/container execution and transfer adapters.
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
