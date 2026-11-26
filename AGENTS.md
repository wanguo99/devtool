# Devtool maintenance

This repository contains the reusable task runner, not any application's build or deployment policy. Work from the repository root and read README.md, CHANGELOG.md, and the relevant tests before making changes.

- Keep the runtime dependency-free on Python 3.11+. Project-specific commands belong in project configurations or explicitly registered providers, not the shared executor.
- Preserve schema compatibility; document new options and keep execution plans read-only. Command execution uses explicit argument vectors. Plans, logs and examples must not contain credentials or private project configuration.
- Keep build, transfer, deployment, and service lifecycle separate unless the project explicitly defines dependencies. Never infer production targets or operate external services when testing this library.
- Use synthetic repositories, controlled subprocesses and mocked transports for tests. Do not edit the application repositories when changing this shared tool. Real deployments require an explicit target and project-level acceptance checks.
- Each development stage: run `./devtool test`, exercise relevant CLI examples, review `git diff --check`, update the docs and changelog, then commit and push the requested branch when authorized.
