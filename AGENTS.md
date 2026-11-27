# Devtool maintenance

This repository contains the reusable task runner, not any application's build or deployment policy. Work from the repository root and read README.md, CHANGELOG.md, and the relevant tests before making changes.

## Source ownership

| Location | Responsibility |
| --- | --- |
| `src/devtool_core/model.py` | Shared configuration and execution-plan data contracts |
| `cli/`, `config/`, `planning/` | Command interface, configuration decoding, read-only planning |
| `execution/`, `runtime/` | Task orchestration, logs/state, process and system-tool adapters |
| `artifacts/`, `delivery/`, `sources/` | Artifact preparation, transfer protocols, Git source operations |
| `templates/devtool.toml` | Reusable project onboarding configuration |
| `examples/projects/` | Existing application-specific compatibility configurations |
| `tests/unit/`, `tests/integration/` | Fast isolated tests and opt-in real-environment tests |

Package paths in the table are relative to `src/devtool_core/` unless a repository-relative path is shown. Follow [docs/architecture.md](docs/architecture.md) for the ownership and dependency boundaries.

## Implementation and integration principles

- Keep the source runtime dependency-free on Python 3.11+ and support the self-contained Linux executable. New internal helpers must work from both source and the packaged binary; do not assume `sys.executable` is Python. Verify binary-related changes with `./devtool test binary` on the local architecture. The primary interface is a minimal project-local `[commands]` table in `devtool.toml`; project-specific build/deploy and operations logic belongs in ordinary configured commands and existing scripts. Advanced task fields, providers, SSH and transfer adapters are optional and must not become a required integration step.
- Preserve schema compatibility; document new options and keep execution plans read-only. Shell-like command strings are tokenized into argument vectors, not implicitly executed by a shell. Any configured task can be invoked directly by name; explicitly forwarded arguments after `--` apply to a single requested command. Plans, logs and examples must not contain credentials or private project configuration.
- Keep build, transfer, deployment, and service lifecycle separate unless the project explicitly defines dependencies. Never infer production targets or operate external services when testing this library.
- Follow the package boundaries in [docs/architecture.md](docs/architecture.md). Keep the runtime adapters independent of the configuration/planning/execution layers; keep artifact validation independent of delivery protocols; keep optional adapters out of ordinary local-only plans. Preserve the source-mode helper module names and packaged internal dispatch protocol. Add fast regression tests in `tests/unit/` and opt-in real-environment tests in `tests/integration/`.
- Use synthetic repositories, controlled subprocesses and mocked transports for tests. Do not edit the application repositories when changing this shared tool. Real deployments require an explicit target and project-level acceptance checks.
- Keep `templates/devtool.toml` generic and copyable: all configuration declarations commented out in the style of sshd_config, actual engine defaults documented, and illustrative values clearly distinguished from defaults. No actual hosts, credentials or project-specific rollout policy. Keep the template, README, configuration reference and relevant examples synchronized when the schema or CLI changes. Test the fully commented file, selective activation and enabled optional blocks using read-only plans, not deployment.

## Development workflow

1. Check the repository status and locate the owning module before modifying code. Keep changes focused on the shared engine and preserve existing user changes.
2. Add or update fast tests for changed behavior, including configuration/plan compatibility where applicable. Run `./devtool test` and exercise the relevant CLI entry points or examples.
3. For template/configuration changes, test an activated temporary copy with `validate` and the relevant `plan` commands; the unmodified commented template is not an operational project configuration. For image delivery changes use `./devtool test docker`; for executable changes use `./devtool build binary` and `./devtool test binary`. Verify the existing-project compatibility matrix when modifying their integration surfaces. Documentation-only edits do not require rebuilding images or contacting a remote server.
4. Update README, architecture/configuration documentation and CHANGELOG as relevant. Review `git diff --check` and the final changed files.
5. Commit and push the requested branch when authorized. Check the resulting Git status and CI results; report any verification that could not be completed.
