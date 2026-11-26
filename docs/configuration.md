# Configuration reference

Devtool reads `devtool.toml` from the current directory or an ancestor, or from the path supplied to `--project`. Relative task paths use the configuration directory as the project root.

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

## Project metadata and modules

```toml
schema = 1                    # optional; schema 1 is the default
[project]
name = "my-project"           # optional; otherwise derived from directory name
[defaults]
module = "all"                # optional

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
