# Coverage of existing engineering tools

The shared executable consolidates reusable engineering mechanisms; individual product algorithms and infrastructure policy are not compiled into the shared engine. This preserves the configuration-first boundary and avoids bundling private project source or credentials.

| Existing capability | Implemented in shared executable | Project-specific input |
| --- | --- | --- |
| Task registration, dependency ordering, module build/test, parameter validation | `[commands]`, `[tasks]`, `[options]`, conditions, derived defaults, steps | Concrete compiler, package manager and script argv |
| Logs, operation state, cancellation, locks, timeouts, recovery | Common runner, history, phases, explicit cleanup | Application recovery/ownership behavior |
| Git repository preparation and update | `[sources]`, grouped clone/fetch, optional fixed revision and missing submodules | Repository URLs, fixed revisions and any specialized submodule mirror policy |
| Build inputs and toolchain package caches | Required tools/paths, SHA-256-pinned fetch and immutable manifests | Toolchain versions, sysroot, architecture flags, existing build scripts |
| Runtime debug strip | `artifact strip`, verified ELF load bytes | Selected host or cross `strip` tool and runtime package location |
| Local containers, SSH, deployment plans | Configured target execution, explicit remote workdirs | Project Compose files, service names, runtime policy |
| Registry, rsync, OCI incremental images | Native transfer adapters, verified staging | Candidate images/payload, target and dedicated cache |
| Full offline environment | Image bundles, generic directory archive and file/tree checks | Project's non-secret config and required image set |
| Deployment prerequisites and candidate selection | `manifest`, `verify_manifests`, explicit flags, conditional tasks | Database compatibility, service health and release selection rules |
| Service status/logs/start/stop/diagnostics | Configured commands and target adapters | Actual service management scripts |
| OTA, payment, notifications, device tooling, business acceptance | Command/task engine and explicit compatibility mappings | Existing specialized business backend and credentials |

## Existing-project configurations

[Three complete public-command mapping files](../examples/projects/README.md) are provided. These cover the previously exposed action/module combinations without invoking the previous root `./devtool` launcher. Straightforward independent tests are defined directly in the common engine. For specialized actions the templates call the existing project backend modules (which must remain in the project). This is a compatibility migration, not evidence that the old project-specific implementation can already be deleted.

This repository's own tests prove the common runtime independently, including the no-Python executable, local Git, ELF strip, directory/image archives and real local OCI/rsync/Docker identity verification. The templates are checked against the existing CLI surfaces and read-only plan/help paths using the packaged executable and an isolated project view. The optional integration script is `tests/integration/verify_project_configs.py`. No full application build, deployment, OTA, payment, business data migration, radio check or live service operation has been performed for this migration. Each project's direct recipes should replace the compatibility backend progressively as the project-specific acceptance verifies parity. The only **new** files required to start using the compatibility configuration in an existing checkout are the binary and its configuration; existing scripts and operational inputs remain prerequisites.
