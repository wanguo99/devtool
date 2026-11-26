# Changelog

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
