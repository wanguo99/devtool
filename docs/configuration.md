# Configuration reference

Devtool reads `devtool.toml` from the current directory or an ancestor, or from the path supplied to `--project`. Relative task paths use the configuration directory as the project root.

Copy [the reusable configuration template](../templates/devtool.toml) into a new project as `devtool.toml`. All declarations are commented, with actual optional settings' defaults or clearly labelled project-specific examples. Uncomment a table header and the desired entries; for instance, enable `[commands]` and `doctor = ["uname", "-m"]`. At least one task is required for an operational configuration; omitting every declaration does not implicitly select any project action. Enable optional capability blocks only when needed. Run `devtool validate` and `devtool plan` for the intended action before executing it.

## Minimal commands

```toml
[commands]
build = "make -j8"
deploy = ["./scripts/deploy.sh"]
status = "docker compose ps"
check = [["make", "check"], ["make", "test"]]
```

Every key is a task name. Quoted keys with dots support modules (`"build.web"`). Values may be:

- A single shell-like command string, parsed using shell quoting rules into words.
- A flat array of strings representing one argument vector.
- An array of argument arrays for multiple commands to execute sequentially.

There is no implicit shell, glob expansion, variable expansion, pipeline or redirection. For shell syntax use a checked-in script or an explicit argument array such as `["sh", "-c", "check && build"]`. The latter is deliberately executable shell code, so keep it in reviewed, trusted project configuration. Use literal argv for parameters that must remain single arguments.

## Delegate an existing project backend

Projects that already expose their own CLI can avoid duplicate argument schemas:

```toml
[backend]
command = ["python3", "-m", "my_project"]
actions = ["clone", "update", "build", "deploy"]

[sources]
component = { url = "https://example.invalid/component.git", branch = "main" }
```

`command` is one command string or argv array, and `actions` is a nonempty list of unique action names. Each creates a single recorded task. `devtool build api --jobs 8` passes `build api --jobs 8` to the backend; modules, values, unknown options and `--help` belong to the backend, not a duplicate Devtool mapping. The engine reserves `--dry-run`, `--check`, `--json` and `--set NAME=VALUE`; any argument after an explicit `--` is passed literally to the backend, including otherwise reserved flags. `devtool plan build api --jobs 8` is read-only and shows the exact outer invocation. `--check` checks that invocation's local prerequisites, not arbitrary backend internals. Use a backend-specific plan when one is needed. The command still receives the ordinary default environment and is executed in the project root, under the normal project lock, with the same logs and exit status handling.

Do not define an explicit task or alias under a delegated action's name (including dotted modules). Engine-owned commands remain reserved. Nondelegated commands/tasks and typed parameters continue to work unchanged. When `clone` or `update` is delegated, its native generated source tasks are suppressed; the existing backend may read the same `[sources]` declarations and implement its own layout, submodules or dependencies. The source catalog remains validated. When neither is delegated, native source tasks work as before.

## Project metadata and modules

```toml
schema = 1                    # optional; schema 1 is the default
[project]
name = "my-project"           # optional; otherwise derived from directory name
[defaults]
module = "all"                # optional
env = { BUILD_ENV = "release" } # optional defaults for ordinary tasks

[commands]
"build.web" = "pnpm build"
"build.server" = "./mvnw package"
[tasks."build.all"]
dependencies = ["build.web", "build.server"]
```

`devtool build web` resolves `build.web`. If no module is supplied, `devtool build` looks for `build.all` (or the configured default module) and then `build`. `devtool task NAME` selects the exact task or alias; `devtool NAME` is the usual shorthand for arbitrary custom operations. Tool-owned commands `init`, `list`, `validate`, `plan`, `task`, `exec`, `history`, `show` and `artifact` take precedence; use `devtool task NAME` if a configured name overlaps one of them.

## Full task settings

Use `[tasks.NAME]` only when a shorthand command is insufficient. Do not define the same name in both `[tasks]` and `[commands]`.

```toml
[commands]
prepare = "./scripts/prepare.sh"

[tasks.build]
description = "Build the service"
dependencies = ["prepare"]
cwd = "backend"
commands = ["./mvnw verify", ["./mvnw", "package"]]
env = { BUILD_MODE = "release" }
timeout = 1800
resources = ["project", "builder"]
artifacts = ["backend/target/app.jar"]
```

`commands` on a full task can be a single string or a sequence of command strings/argv arrays. Dependencies are task names (including shorthand commands), run once in order; cycles and missing names are rejected. `cwd` is project-relative, `artifacts` is always relative to the project root, and `timeout` is per command. `resources` defaults to `["project"]`; use an explicit empty array for independent read-only operations. Use `secret_env = { CHILD_KEY = "HOST_KEY" }` to reference an existing host environment value without storing its value. The runner records verified outputs, not necessarily newly produced files. See [advanced reference](advanced.md) for logging, secret handling and optional target/transfer/provider fields.

## Parameters and argument forwarding

For existing scripts, prefer forwarding options without changing the config:

```toml
[commands]
build = "./scripts/build.sh"
```

```sh
devtool build -- --platform arm64 --jobs 8
```

Arguments following `--` are appended verbatim only to the selected task's sole command. A multi-command task or dependency-only group cannot receive forwarded arguments. No arguments are added to dependency tasks. `devtool plan build -- --platform arm64` shows exactly what will execute. Do not send secrets as argv.

For reusable defaults and validated choices, declare non-secret typed parameters:

```toml
[parameters.mode]
type = "string"
default = "release"
choices = ["release", "debug"]
[parameters.jobs]
type = "integer"
default = 4
[commands]
build = ["make", "MODE={{mode}}", "-j{{jobs}}"]
```

Use `devtool build --set mode=debug --set jobs=8`. Supported types are `string`, `integer`, `boolean` (default type is string). A referenced parameter without a default is required. Each placeholder is substituted within an individual argument without a second round of parsing. Unknown and unused overrides fail, so misspelled flags do not silently change behavior. Parameters may also be used in declared task paths, non-secret environment fields and optional target/transfer settings.

Write `{{{{` and `}}}}` to produce literal double braces in configured strings. For example, Docker's Go template can be passed as `["docker", "inspect", "--format", "{{{{.State.Status}}}}", "{{container}}"]`. After planning, Docker receives `{{.State.Status}}` and the resolved container name as separate arguments. Values supplied by parameters or forwarded after `--` remain literal data; they are not parsed as Devtool placeholders.

## Aliases and checks

```toml
[commands]
"source.fetch" = "git fetch origin"
[aliases]
update = "source.fetch"
```

Aliases map to existing task names. `update` is not assigned a built-in behavior: each project defines the meaning it intends. Use `devtool validate` to validate the schema and dependency graph, `devtool list` to discover tasks, and `devtool plan COMMAND` before operations whose effects should be reviewed. `--check` reports local preflight status without execution, and `--json` emits a structured operation result for automation. All commands return a nonzero exit status on failure.

## Optional source and artifact declarations

A `[sources]` catalog generates grouped clone/update tasks. Full tasks may declare `tools`, `requires`, `images`, `manifest` and `verify_manifests` for local input and immutable build-output checks. See [source groups and artifact contracts](sources-artifacts.md).

## Advanced workflows

Projects can define native CLI option names via `[options]`, computed defaults via `derive`, conditional tasks/steps via `when`, independent step tables and explicit failure/cleanup commands. See [workflow reference](workflows.md).
