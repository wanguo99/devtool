# Devtool

**One command execution engine, one configuration file per project.**

Devtool simplifies development and operations by running project-defined commands. It does not prescribe a programming language, build system, deployment strategy, container runtime, or directory layout. Use your existing scripts and tools; let Devtool handle task ordering, execution, exit codes, plans and operation records.

## 1. Build or download the executable

Use the architecture-appropriate Linux executable. Build it with `./scripts/build-binary.sh` (Docker), or `./devtool build binary` in this source checkout. The output is `dist/linux-$(uname -m)/devtool`; see [binary distribution](docs/binary.md). Copy this single file into any project. The executable contains its Python runtime; configured external commands still require their project tools.

For source development the repository launcher requires Python 3.11+; no runtime third-party Python dependencies are needed. The executable discovers `devtool.toml` in the current directory or an ancestor; `--project PATH` selects another project directory or configuration file explicitly.

## 2. Integrate Devtool into a project

For a new project, place the matching executable and the [configuration template](templates/devtool.toml) at its root:

```sh
DEVTOOL_REPO=/path/to/devtool
cd /path/to/my-project
cp -n "$DEVTOOL_REPO/dist/linux-$(uname -m)/devtool" ./devtool
cp -n "$DEVTOOL_REPO/templates/devtool.toml" ./devtool.toml
```

The template follows the style of `sshd_config`: **every configuration declaration is commented out by default**. Optional engine settings show their actual defaults; entries without a universal default (such as project commands, source URLs and target addresses) show illustrative values instead. Uncomment only the table headers and settings you intend to use, and replace the sample paths with the project's actual commands. No real target or credential is configured. The copy commands do not overwrite existing files; for an existing project, review its current launcher and configuration before replacing them.

For example, enable just these two lines in the copied file:

```toml
[commands]
doctor = ["uname", "-m"]
```

Then check the result without running a build or deployment:

```sh
./devtool validate
./devtool list
./devtool plan doctor
```

`validate` checks the configuration and dependency graph; for configured build or deploy tasks, `--check` also checks local prerequisites. A fully commented template contains no tasks and will not validate as an operational project until you enable at least one command or task. The sample script commands require the corresponding project scripts to exist. Alternatively, run `./devtool init` in a project without an existing config to generate a small active starter configuration.

## 3. Configure the project's existing commands

If writing **`devtool.toml`** from scratch, a typical web or service project could use:

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

If the project already has a command-line backend that parses its own actions and options, delegate those actions in two declarations instead of repeating every flag and module:

```toml
[backend]
command = ["python3", "-m", "my_project"]
actions = ["clone", "update", "build", "deploy", "test"]

[sources]
component = { url = "https://example.invalid/component.git", branch = "main" }
```

`devtool build server --jobs 8` invokes `python3 -m my_project build server --jobs 8`. Devtool still handles planning, local preflight, execution, locks and operation history. The backend owns its business arguments and can read `[sources]` from the same file. Use this only when an existing backend already implements those operations; otherwise ordinary `[commands]` and native `[sources]` are sufficient. See [backend delegation](docs/configuration.md#delegate-an-existing-project-backend).

## 4. Run the commands

```sh
./devtool build
./devtool test
./devtool deploy
./devtool status
./devtool logs
./devtool backup
```

Any configured name is a command, not just `build`, `test` or `deploy`. Devtool does not automatically build before deployment or start containers after building. Only the configuration decides what happens.

```sh
./devtool list                  # discover configured commands
./devtool plan deploy           # read-only plan, no execution
./devtool build --check         # check local executable and input availability
./devtool build --json          # machine-readable result; output on stderr
./devtool history               # inspect previous operations
```

A single command can receive additional arguments after `--`, without declaring every option in Devtool:

```sh
./devtool build -- --mode production
./devtool deploy -- --host user@example.invalid
```

Additional arguments go only to the requested single-command task, not to its dependency tasks. Complex argument workflows can instead use declared parameters. Commands are run from the project root by default.

## 5. Combine commands into workflows when needed

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
./devtool release
./devtool plan release
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

## 6. Core and optional extensions

| Core engine | Optional capabilities |
| --- | --- |
| Configuration, command arguments and task dependencies | Named SSH or Docker execution targets |
| Read-only execution plans and preflight checks | Registry, rsync, OCI and archive transfers |
| Process execution, output, timeout and exit codes | Python providers for dynamic task definitions |
| Logs, operation history, resource locks and artifact identities | Declarative Git source groups, verified candidate manifests and ELF strip preparation |

The core runs independently of the optional targets and transfers. Ordinary project configurations simply call their existing build/deploy scripts, including scripts that already use Docker or SSH. The tool does not own database migrations, release compatibility, application rollback or production policy. [Advanced features](docs/advanced.md) are available for projects that actually need them.

## Source structure

The implementation is divided by responsibility rather than by application:

| Directory in `src/devtool_core/` | Responsibility |
| --- | --- |
| `cli/` | Argument parsing, command dispatch, helper entry points |
| `config/` | Project discovery, TOML decoding, validation and providers |
| `planning/` | Dependency graph, parameters and read-only execution plans |
| `execution/` | Process execution, preflight, logs, locks and operation state |
| `runtime/` | System-command, SSH, Docker and packaged-runtime adapters |
| `artifacts/` | File/tree identities, manifests, archives, pinned downloads, ELF strip |
| `delivery/` | rsync, Registry, OCI and offline image delivery |
| `sources/` | Git source catalog and checkout operations |

`model.py` contains shared data contracts. Tests are separated into `tests/unit/` and opt-in `tests/integration/`; `templates/` contains the reusable configuration, while `examples/projects/` contains the three application-specific compatibility mappings. See [architecture and dependency boundaries](docs/architecture.md).

## Development

This repository also uses Devtool for its own checks:

```sh
./devtool test
./devtool --project examples/simple plan release
./devtool --project examples/simple release
./devtool --project examples/simple backup -- --dry-run
```

Run an explicitly supplied local command, even without a project config, with `devtool exec -- COMMAND [ARG...]`. CI and external schedulers can call any configured task and use its exit code or JSON result.

The fast suite checks that the reusable template is entirely commented and that selective activation and the optional extension blocks produce valid, read-only plans.

For changes affecting image delivery or the executable, run the corresponding opt-in checks:

```sh
./devtool test docker
./devtool build binary
./devtool test binary
./devtool build wheel
```

Use the [existing-project compatibility matrix](docs/validation.md) to check changes against Smart Alarm, ZipPOS and NTN workspace without replacing their launchers or contacting a deployment host.

- [Reusable configuration template](templates/devtool.toml)
- [Executable distribution and builds](docs/binary.md)
- [Source architecture and module boundaries](docs/architecture.md)
- [Existing project compatibility configs](examples/projects/README.md) and [migration coverage](docs/migration-coverage.md)
- [Real-project and ARM64 deployment validation](docs/validation.md)
- [Configuration reference](docs/configuration.md)
- [Conditional workflows, custom flags and recovery](docs/workflows.md)
- [Source groups, artifact manifests and strip](docs/sources-artifacts.md)
- [Advanced execution and delivery capabilities](docs/advanced.md)
- [Integration guide](docs/integration.md)
- [Simple example](examples/simple/devtool.toml)
- [Change history](CHANGELOG.md)

Only execute configurations from projects you trust. Logs and history are private per-checkout operation records, not build artifacts. Do not pass credentials as command arguments; use the project's existing secret mechanism.
