# Source groups and verified build outputs

These built-in operations are available in the same executable. They are optional; projects may continue to call their existing scripts through `[commands]`.

## Source preparation

```toml
[sources.frontend]
url = "https://example.invalid/frontend.git"
path = "source/frontend"
branch = "main"
groups = ["web"]

[sources.library]
url = "https://example.invalid/library.git"
path = "source/library"
revision = "0123456789012345678901234567890123456789"
groups = ["web", "backend"]
submodules = true

[sources.legacy]
url = "https://example.invalid/legacy.git"
default = false
groups = ["legacy"]
```

`devtool clone` clones missing default sources. `devtool clone web` selects a group, and `devtool clone legacy` explicitly selects the omitted component. Each source name is also a selection group. Existing repos must match their configured origin; clone skips them, update fetches origin without changing HEAD or merging. A new clone is prepared in a temporary sibling directory and published only after successful preparation. An explicitly pinned commit uses a detached checkout on the **new clone**; an existing checkout is never automatically moved to that revision. Submodule initialization is opt-in and fills only missing submodules; initialized submodule checkouts and edits are preserved. No implicit upstream remote, push, reset, or cleanup is performed. Paths must be fixed, non-overlapping project-relative locations; URLs may not embed HTTP credentials. Supply access through normal Git credential helpers or SSH configuration. Use project-specific scripts for unusual repository layouts or strict mirror remapping policies.

The catalog generates `clone.<group>`/`update.<group>` and per-source internal tasks, which participate in ordinary task dependencies and plans. Do not define competing task names for the same groups. Git is a project tool required to execute these tasks, not a dependency to run Devtool itself.

## Input and artifact contracts

```toml
[parameters.tag]
default = "candidate-001"

[tasks.build]
tools = ["make", "docker"]
requires = ["Makefile"]
commands = ["make", ["docker", "build", "--tag", "example.invalid/demo:{{tag}}", "."]]
artifacts = ["dist/app"]
images = ["example.invalid/demo:{{tag}}"]
manifest = "releases/{{tag}}.json"

[tasks.deploy]
verify_manifests = ["releases/{{tag}}.json"]
commands = [["./scripts/rollout.sh", "releases/{{tag}}.json"]]
```

Use `devtool build --set tag=candidate-002`, then `devtool deploy --set tag=candidate-002`. `tools` and `requires` are checked when a task begins; `--check` also reports missing local prerequisites without executing. `artifacts` are files or directories rooted in the project. `images` are explicit tagged local Docker images; identity includes image ID and OS/architecture. A configured `manifest` is emitted only after successful commands and artifact checks, and never replaces an existing manifest. `verify_manifests` checks each required file/tree and image identity before a task's commands run. The same controls can be used in dependency-only or verification-only tasks.

The manifest is an integrity record, not a signature or a replacement for the project's release compatibility or database checks. Paths and image references must match the environment that owns those outputs.

Standalone helper commands also work outside a task plan:

```sh
./devtool artifact create --output releases/demo.json --file dist/app --image example.invalid/demo:v1
./devtool artifact verify --manifest releases/demo.json
```

## Debug-symbol stripping

```sh
./devtool artifact strip --source build/runtime --destination dist/release
```

This copies a runtime directory, strips only debug sections from ELF executables and shared objects using the chosen `strip` tool, and validates that mapped load segments (excluding section-table metadata) remain identical. The input tree is not changed; the destination must not already exist. Pass a cross-toolchain executable with `--strip-command`. Use separate configured build tasks/parameters to choose debug or release artifacts and record the result with an artifact manifest. Project-specific cross compiler, sysroot and CMake/Meson settings remain in the project commands.
