# Changelog

## 0.2.0 — Stage 2

- Add hashed plans, resource locks, private atomic operation records, bounded redacted logs, timeouts and process-group cancellation.
- Add explicit environment-secret references, read-only preflight, artifact identities, history and operation inspection.
- Unit/CLI tests: 19 passed, including real local commands, timeout and Ctrl-C.

## 0.1.0 — Stage 1

- Introduce a Python standard-library CLI and schema-1 TOML configuration, typed parameter overrides, aliases, validated task DAG and deterministic JSON plans.
- Execute local argument-vector commands in dependency order, with project-relative working directories and fail-fast exit codes.
- Include a source-tree entry point, installable package metadata, self-hosted tasks and example configuration.
