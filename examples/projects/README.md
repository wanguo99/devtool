# Existing-project compatibility configurations

Each subdirectory contains one configuration file for an existing project. Copy the matching `devtool.toml` and the common executable into that project's root. The new binary does **not** need the previous root launcher; these compatibility files explicitly call existing project backend modules or scripts, not `./devtool` (which would recurse after replacement).

| Configuration | Public operation surface |
| --- | --- |
| `smart-alarm/devtool.toml` | Product modules, environment start/update/stop/status/logs, offline images, doctor, verification and OTA |
| `zippos/devtool.toml` | Build/test, deploy/update/rollback, remote preparation, diagnostics, validation, payment, notifications and independent beta instance operations |
| `ntn-workspace/devtool.toml` | Clone/update, RAN/Core/UE build, platform-dependent deployment, validation and container lifecycle |

Use `./devtool list`, `./devtool plan build web` or `./devtool plan deploy` to see the common engine plan. Legacy options are passed after `--`, for example `./devtool build all -- --platform phytium`, `./devtool deploy -- --host user@example.invalid --manifest candidate.json` (use the options expected by that project). `legacy-plan` on the two tools that expose a detailed legacy plan delegates the read-only legacy plan, for example `./devtool legacy-plan -- build all --platform phytium`. `legacy-help` lists the old interface. The new engine records operations independently.

These are complete public-command **compatibility mappings**, not a claim that all domain-specific backend implementations have been rewritten. Existing Python project code, build scripts, toolchains, application configuration, credentials and release policies must remain available for their commands. The common executable itself needs no Python installation; configured Python backends may need their own project runtime. Smart Alarm's existing Docker control bootstrap remains an option via its environment or when Python is unavailable.

Use the [native configuration guide](../../docs/configuration.md), [source/artifact helpers](../../docs/sources-artifacts.md) and [workflow reference](../../docs/workflows.md) to replace a compatibility command with direct configured steps as the project validates that workflow. Never remove the older backend before validating its replacement, and never migrate a live service just to test a new wrapper. No target address, private profile, business source or credential is included in these files.

The repository includes `tests/integration/verify_project_configs.py` to verify a packaged binary with these configurations against local existing checkouts. Pass the executable path and the three project roots. It only exercises help and read-only build plans using a temporary directory and checks that the original checkout statuses do not change. Add `--full` to build every configured task's read-only plan and check each compatibility command's backend help.

See the [real-project validation report](../../docs/validation.md) for the tested application workflows, isolated ARM64 deployment and cleanup results.
