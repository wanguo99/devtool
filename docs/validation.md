# Real-project validation (2026-11-27)

This acceptance run used the packaged Linux executable and the three [compatibility configurations](../examples/projects/README.md) in their existing project roots. The old root launchers were not replaced. Application backends and their pinned dependencies remain project responsibilities.

## Local project checks

| Project | Plans / backend help | Executed workflows and result |
| --- | ---: | --- |
| Smart Alarm | 69 / 69 | `test all`: all 31 tasks succeeded, including 654 BFF tests, 405 frontend tests, ThingsBoard Maven validation, the locked Air780EGG toolchain build, Lua and host checks. Built the Web bundle as part of the test. |
| ZipPOS | 60 / 58 | `test all`: 227 frontend tests; 32 + 437 Java tests with successful Maven packaging; 220 tooling tests and 7 validation tests. Separate tool and validation tests also passed. `build web`: all three Web portals built. |
| NTN workspace | 27 / 23 | `test all`: 731 unit tests and the source/bootstrap regression passed, including recursive source pins and repeated offline clone/fetch behavior. Existing remote workspace status and bounded logs also worked. |

The initial Smart Alarm run lacked the pinned pnpm version and host JDK/Maven. Temporary matching tools resolved these prerequisites. Five pinned Debian package URLs returned HTTP 404 while building the Air780EGG toolchain; the exact archives were recovered from the Debian historical snapshot, matched against the existing SHA-256 lock and seeded in the local build cache. No application lock or source file was changed.

## Actual ARM64 target

An x86_64 controller (Docker 29.7.2) deployed to an independent ARM64 host (Docker 29.9.2) over authenticated SSH. Both architecture-specific executables worked, including version 0.10.1 after correcting literal command-template handling. All test resources had unique names; no service ports, production volumes, or production credentials were used.

| Workflow | Actual target-side check |
| --- | --- |
| Smart Alarm | Transferred the real built Web bundle using manifest-verified rsync, started an isolated ARM64 HTTP container and retrieved its entry page. An incremental 44-byte marker file was transferred and retrievable after restart. |
| ZipPOS | Built two ARM64 test images containing the actual three-portal Web build; transferred via OCI delta, verified image IDs, served all three entry pages from the new image. |
| NTN workspace | Exported, transferred and imported a small ARM64 offline image bundle, verified its image identity and executed its marker command. Separately invoked the existing project's actual `status` and bounded `logs` commands against its existing ARM64 deployment, without changing existing services. |

For all three isolated containers, exercised deploy, start, status, logs, verification and stop through the common executable. The escaped Docker Go-template status command was verified on ARM64 using the fixed executable.

Observed rsync sender-byte counts for these specific small fixtures, excluding SSH protocol overhead:

| Transfer | First send | Subsequent send |
| --- | ---: | ---: |
| Smart Alarm Web files | 1,056,736 B | 13,813 B (44-byte added file) |
| ZipPOS OCI layers | 4,327,144 B | 2,573 B (small version-marker layer changed) |
| Offline bundle | 1,900,599 B | Not measured |

These measurements are not predictions for full application releases. The new containers were isolated smoke-test workloads, not complete production service replacements. Production database migrations, payment/OTA workflows, physical devices, full RFsim/5G radio service bring-up and live release rollback were not executed.

After the test, deleted only the three owned, stopped containers, three owned image tags and the temporary test directory. Compared the original and final inventory: all 11 original containers (including IDs, image IDs, start times and restart counts), 33 image entries, 8 networks, 4 volumes and 16 top-level home entries matched exactly. The original applications' tracked working-tree status was preserved.

## Repeat the safe compatibility checks

With the three existing checkouts and a built executable, run from this repository:

```sh
python3 tests/integration/verify_project_configs.py --full \
  --binary dist/linux-x86_64/devtool \
  --smart-alarm /path/to/smart-alarm \
  --zippos /path/to/zippos \
  --ntn-workspace /path/to/workspace
```

This checks all 156 task/alias plans and 150 backend help invocations against the project implementations; it uses a temporary view, never runs actual deploy or update commands and never replaces the original launcher. For real application testing and deployment use a project configuration in the actual checkout and explicitly selected test targets, respecting that project's release and isolation policy.
