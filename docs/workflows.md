# Configurable multi-step engineering workflows

The simple `[commands]` interface remains sufficient for most projects. More complex existing tools can be expressed using the same engine instead of adding hard-coded project argument parsers or Python providers.

## Project-specific switches and defaults

```toml
[parameters.platform]
default = "arm64"
[parameters.jobs]
type = "integer"
derive = "half_cpus"
[parameters.profile]
default = "release"
choices = ["debug", "release"]
[parameters.tag]
derive = "utc_tag"

[options]
platform = "platform"
jobs = "jobs"
tag = "tag"
debug = { parameter = "profile", value = "debug" }
release = { parameter = "profile", value = "release" }

[commands]
build = ["./scripts/build.sh", "--platform", "{{platform}}", "--jobs", "{{jobs}}", "--profile", "{{profile}}", "--tag", "{{tag}}"]
```

`devtool build --platform arm64 --debug` now uses project-configured option names. Repeating a parameter through different flags (for example `--debug --release`) is rejected. The project may still use `--set` or the single-command argument forwarding delimiter `--`. Reserved engine options such as `--check`, `--json`, and `--dry-run` keep their engine semantics; use explicit named tasks or forwarding for legacy options that conflict.

Derived defaults are `half_cpus` (integer, half the available CPU affinity count with minimum 1), `host_arch` (string, `amd64`/`arm64` where recognizable), `utc_tag` (string, UTC timestamp with microsecond precision), and `project_root` (string). A derived default is evaluated once per plan when referenced. Provide an explicit tag to select the same candidate in separate build/deploy operations.

## Conditional tasks and independently configured steps

```toml
[parameters.profile]
default = "release"
[parameters.host_arch]
derive = "host_arch"

[tasks."compile.native"]
when = { host_arch = "arm64" }
commands = ["./scripts/build-native.sh"]

[tasks."compile.cross"]
when = { host_arch = "amd64" }
commands = ["./scripts/build-cross.sh"]

[tasks.build]
dependencies = ["compile.native", "compile.cross"]

[[tasks.build.steps]]
command = "./devtool artifact strip --source out/debug --destination out/release"
when = { profile = "release" }

[[tasks.build.steps]]
command = "make check"
cwd = "tests"
env = { CHECK_MODE = "{{profile}}" }
```

Each `when` table requires all parameter conditions to match. A condition value can be one value or a list of accepted values (OR). Inactive dependency branches and their exclusive prerequisites are skipped. An explicitly requested disabled task is rejected. The static dependency graph must remain valid even when some tasks are conditional.

Full tasks can use either `commands` or `steps`. A step table provides one `command` (string or argv) and optional `cwd`, `env`, `secret_env`, `timeout`, `target` and `when`. Step environment values merge with task defaults; paths and targets follow the same validation rules. Transfer steps still precede the task's command steps, and task preflight/artifact checks cover the whole task. Extra forwarded arguments are accepted only if exactly one command step is active in the requested task.

## Recovery and cleanup

```toml
[tasks.deploy]
verify_manifests = ["releases/candidate.json"]
commands = ["./scripts/activate.sh"]
on_failure = ["./scripts/restore-previous.sh"]
cleanup = ["./scripts/close-release-session.sh"]
```

These are explicit project commands, not an engine-invented rollback strategy. `on_failure` runs when a normal task command returns a known nonzero exit. `cleanup` runs after known command completion (success or failure). Recovery or cleanup never erases the operation's original failure; a failed cleanup after a successful command also fails the operation. Each step is recorded with its phase. Missing prerequisites, timeouts, interruption and an ambiguous SSH connection failure do not trigger recovery automatically. An SSH exit 255 records `INTERRUPTED_UNKNOWN` for reconciliation. Project scripts should implement their own transaction/ownership and health checks; any database migration rollback must remain an explicit project decision.
