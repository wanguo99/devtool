# Adopting Devtool in an existing project

The shared package is an orchestration layer. Preserve existing build scripts, configuration, product tests and deployment safeguards. Avoid replacing a working release path merely to move code into this library.

## 1. Wrap existing commands first

Install Devtool in an isolated environment, or use the absolute path to this checkout's `devtool`. In a project with a pre-existing local `./devtool`, **keep that entry point initially** and invoke the new command by its installed or absolute path. This avoids recursive dispatch.

With a `devtool.toml` in the existing project root:

```toml
[commands]
test = ["./devtool", "test", "all"]
build = ["./devtool", "build", "all"]

[tasks."check-build"]
dependencies = ["test", "build"]
```

Run the common tool, not the legacy repository-local launcher:

```sh
/path/to/common/devtool --project . plan build
/path/to/common/devtool --project . test
/path/to/common/devtool --project . check-build
```

For a platform-dependent old CLI, simply pass through options, for example `/path/to/common/devtool --project . build -- --platform arm64`. If the project needs defaults and validation for common flags, it can declare parameters instead. Keep each project's actual semantics: fetching source (`update` in some projects) and updating running services (`update` in others) are not interchangeable. If desired, map the old action name to a canonical task through `[aliases]`.

## 2. Choose task/transport boundaries

| Project style | Common Devtool owns | Existing project owns |
| --- | --- | --- |
| Multi-component IoT or embedded product | Task graph, execution, file/bundle identity, logs | Firmware toolchain, release/OTA procedures, device permissions, product contracts |
| Multi-module web/Java service | Build/test task graph, immutable candidate staging, SSH/OCI transfer | Database migration, release compatibility, traffic switch, backup and rollback |
| Native and cross-compiled C/C++ service | Parameters, build orchestration, manifest verification and rsync staging | Target architecture detection, sysroot/toolchain selection, debug stripping, offline image assembly |

Keep an explicit candidate selection and project-specific validation. Separate upload/staging from activation. Use version-specific project-managed rollout locking and rollback checks; common local history is not a substitute for production state. A general-purpose task runner cannot infer application invariants.

## 3. Move only reusable logic

Replace repeated simple command definitions with TOML. Use a reviewed Python provider when task generation depends on project structure. Implement complex build or deployment algorithms as project scripts or libraries called by tasks. The generic orchestration core should not import business code.

After plans, local tests and appropriate target acceptance are equivalent to the legacy path, the project may switch its root launcher to the shared executable. A typical thin launcher is:

```sh
#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
exec /path/to/common/devtool --project "$root" "$@"
```

Before switching, replace any task that calls `./devtool` with the retained legacy package/script or concrete build command. Keep the original CLI/flag contracts where useful. Pin the shared tool to a tested version in the project or CI environment; update independently from product releases.

## Read-only bridge example

This repository contains `examples/bridge/devtool.toml` for checking an existing CLI without changing its source tree:

```sh
./devtool --project examples/bridge doctor compat --set project_dir=/absolute/project
./devtool --project examples/bridge task preview-build --set project_dir=/absolute/project
./devtool --project examples/bridge task preview-cross-build \
    --set project_dir=/absolute/project --set platform=arm64
```

The second and third commands require the legacy tool to support its own read-only `plan` action and the chosen platform argument. They run no build/deployment commands. This repository's implementation has been validated against three existing local CLI entry points and two existing CLI plan implementations; the platform-sensitive plan requires an explicit supported platform. Their tracked and untracked checkout status was unchanged. No legacy application code or private host configuration is included here, and operational migration/production deployment remains a separate project acceptance activity.
