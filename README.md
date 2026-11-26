# Devtool

**One command execution engine, one configuration file per project.**

Devtool simplifies development and operations by running project-defined commands. It does not prescribe a programming language, build system, deployment strategy, container runtime, or directory layout. Use your existing scripts and tools; let Devtool handle task ordering, execution, exit codes, plans and operation records.

## 1. Install once

Python 3.11+ on Linux/POSIX. No runtime Python dependencies.

Install in an isolated tool environment (for example, `pipx install .` from this checkout), or use the absolute path to this repository's executable `devtool`. The same executable can run every project. It discovers `devtool.toml` in the current directory or an ancestor; `--project PATH` selects another project directory or configuration file explicitly.

## 2. Configure the project's existing commands

Create **`devtool.toml`** in your project's root. For a typical web or service project:

```toml
[commands]
build = "pnpm build"
test = "pnpm test"
deploy = "./scripts/deploy.sh"
start = "docker compose up -d"
stop = "docker compose stop"
status = "docker compose ps"
logs = "docker compose logs --tail 100"
backup = "./scripts/backup.sh"
```

These are example commands; replace them with the commands your project already uses. No `[project]` table, plugin, backend, or additional file is required. `devtool init` can generate a starter config without overwriting an existing file.

## 3. Run the commands

```sh
devtool build
devtool test
devtool deploy
devtool status
devtool logs
devtool backup
```

Any configured name is a command, not just `build`, `test` or `deploy`. Devtool does not automatically build before deployment or start containers after building. Only the configuration decides what happens.

```sh
devtool list                  # discover configured commands
devtool plan deploy           # read-only plan, no execution
devtool build --check         # check local executable and input availability
devtool build --json          # machine-readable result; output on stderr
devtool history               # inspect previous operations
```

A single command can receive additional arguments after `--`, without declaring every option in Devtool:

```sh
devtool build -- --mode production
devtool deploy -- --host user@example.invalid
```

Additional arguments go only to the requested single-command task, not to its dependency tasks. Complex argument workflows can instead use declared parameters. Commands are run from the project root by default.

## 4. Combine commands into workflows when needed

A command may use a shell-like string, an explicit argument array, or multiple argument arrays. Strings are split into words, **not** evaluated by a shell. For pipelines or redirections, use a project script or explicitly specify `['sh', '-c', '...']` as an argument array.

```toml
[commands]
test = [["pnpm", "check"], ["pnpm", "test"]]
build = ["pnpm", "build"]
deploy = "./scripts/deploy.sh"

[tasks.release]
dependencies = ["test", "build", "deploy"]
```

```sh
devtool release
devtool plan release
```

Tasks execute once in dependency order and stop on the first failure. With more complex projects, add named modules, parameters, working directories or outputs only where required:

```toml
[commands]
"build.frontend" = "pnpm build"
"build.backend" = "./mvnw package"

[tasks."build.all"]
dependencies = ["build.frontend", "build.backend"]
```

Then use `devtool build frontend`, `devtool build backend`, or `devtool build`. See [configuration reference](docs/configuration.md) for the complete syntax and [integration guide](docs/integration.md) for migrating an existing project.

## 5. Core and optional extensions

| Core engine | Optional capabilities |
| --- | --- |
| Configuration, command arguments and task dependencies | Named SSH or Docker execution targets |
| Read-only execution plans and preflight checks | Registry, rsync, OCI and archive transfers |
| Process execution, output, timeout and exit codes | Python providers for dynamic task definitions |
| Logs, operation history, resource locks and artifact identities | Project-defined remote rollout and acceptance scripts |

The core runs independently of the optional targets and transfers. Ordinary project configurations simply call their existing build/deploy scripts, including scripts that already use Docker or SSH. The tool does not own database migrations, release compatibility, application rollback or production policy. [Advanced features](docs/advanced.md) are available for projects that actually need them.

## Development

This repository also uses Devtool for its own checks:

```sh
./devtool test
./devtool --project examples/simple plan release
./devtool --project examples/simple release
./devtool --project examples/simple backup -- --dry-run
```

Run an explicitly supplied local command, even without a project config, with `devtool exec -- COMMAND [ARG...]`. CI and external schedulers can call any configured task and use its exit code or JSON result.

- [Configuration reference](docs/configuration.md)
- [Advanced execution and delivery capabilities](docs/advanced.md)
- [Integration guide](docs/integration.md)
- [Simple example](examples/simple/devtool.toml)
- [Change history](CHANGELOG.md)

Only execute configurations from projects you trust. Logs and history are private per-checkout operation records, not build artifacts. Do not pass credentials as command arguments; use the project's existing secret mechanism.
