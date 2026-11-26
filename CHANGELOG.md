# Changelog

## 0.8.0 — Reusable source and artifact preparation

- Add declarative Git source groups, optional legacy exclusions, pinned new checkouts and fetch-only updates. Missing submodules are initialized without resetting existing checkouts. Local Git fixtures verify dirty worktree and submodule preservation.
- Add required path/tool checks, artifact and Docker image manifests, manifest preflight before task execution, and standalone verified manifest helpers. Add private runtime ELF strip preparation with load-segment identity checks.
- 61 unit/CLI tests passed, including a real compiled ELF strip/execute test. Rebuild the binary and test the internal helpers without a target Python installation.

## 0.7.0 — Self-contained Linux executable

- Package the core and internal helpers as an architecture-specific one-file ELF with an embedded Python runtime. Preserve source-mode execution; use binary self-dispatch and clean system-command library environments when frozen.
- Add reproducible builder scripts using a Debian Bullseye/Python 3.11 baseline, pinned build wheels, SHA-256 output, and x86_64/AArch64 native CI packaging. The local x86_64 portable executable passed an isolated Debian Bullseye test without Python, including configured commands, forwarded arguments, operation history and nested archive helpers. ARM64 artifacts are built by the native-architecture CI job; no live ARM target was modified.
- 53 unit/CLI tests passed. The initial in-container dependency installation stalled; host wheel staging followed by offline installation resolved the build.

## 0.6.0 — Configuration-first command engine

- Make a single `[commands]` table sufficient to use Devtool. Optional project identity is derived from the configuration directory; schema 1 is implicit when omitted. Accept command strings, argv arrays and ordered command arrays.
- Invoke any configured command directly by name, and forward arguments after `--` to the selected single-command task. Existing full tasks, typed parameters, aliases, providers and optional delivery adapters remain compatible. Local command plans do not load the SSH or transfer modules.
- Simplify README and starter configuration; separate advanced capabilities into a reference guide. Add minimal example and 9 configuration-first CLI regression tests (51 total).

## 0.5.1 — Stage 6: real-engine acceptance and polish

- Add an explicit, isolated `test docker` integration task. Docker Server 29.7.2 built two scratch images, saved both as OCI archives, reused an unchanged blob with actual local rsync, and loaded the reconstructed candidate with the original image identity. The fixture tags were removed. No service ran or remote host was contacted.
- Correct the final unterminated log-line truncation record, validate stored record identities and reject nonportable bundle member names during export. The first real delta check treated a metadata-only rsync timestamp change as a retransmission; the corrected test distinguishes data-transfer itemization.
- Unit/CLI tests: 42 passed.

## 0.5.0 — Stage 5: project providers and automation

- Add explicitly enabled project-local providers, configuration validation, direct local `exec`, JSON operation results and migration/bridge examples.
- Add CI across Python 3.11–3.13 and verify the package wheel can be built, installed and used from a separate package path.
- Unit/CLI tests: 39 passed. Three existing project entry points and two read-only build-plan paths exercised without changing their checkout status. No live service deployment performed.

## 0.4.0 — Stage 4: portable and OCI artifacts

- Add deterministic directory bundle export/import, validation of archive paths and links, and manifest-verified atomic import without overwrite.
- Add OCI Docker-save blob staging, rsync reuse, exact inventory reconstruction, image identity verification and protection against unexpected image tags or replacement. Unsupported archive formats are rejected explicitly.
- Unit/CLI tests: 32 passed, including actual local archive round trips and rsync cache reuse. Docker loading and remote execution are tested with fixtures; live engine compatibility remains to be verified.

## 0.3.0 — Stage 3: execution targets and staged transfer

- Add explicit SSH and existing Docker container targets, safe argv rendering and read-only plans.
- Add typed rsync and Registry transfer steps with source/target identity verification, fail-fast staging and no implicit service activation. Local rsync is exercised with real temporary trees; remote protocols are tested using fixtures, not production hosts.
- Unit/CLI tests: 26 passed.

## 0.2.0 — Stage 2

- Add hashed plans, resource locks, private atomic operation records, bounded redacted logs, timeouts and process-group cancellation.
- Add explicit environment-secret references, read-only preflight, artifact identities, history and operation inspection.
- Unit/CLI tests: 19 passed, including real local commands, timeout and Ctrl-C.

## 0.1.0 — Stage 1

- Introduce a Python standard-library CLI and schema-1 TOML configuration, typed parameter overrides, aliases, validated task DAG and deterministic JSON plans.
- Execute local argument-vector commands in dependency order, with project-relative working directories and fail-fast exit codes.
- Include a source-tree entry point, installable package metadata, self-hosted tasks and example configuration.
