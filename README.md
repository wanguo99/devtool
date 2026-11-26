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

- Stage 1: configuration, dependency graph, CLI, local plans and execution.
- Stage 2: operation history, logs, resource locks, timeouts, artifacts and preflight.
- Stage 3: explicit local/remote/container execution and transfer adapters.
- Stage 4: project providers, portable integration examples and automation interfaces.

Project-specific build, rollout, data migration and rollback policies stay with each project. The shared core has no product-specific paths, credentials or deployment assumptions.
