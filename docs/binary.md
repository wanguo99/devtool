# Portable executable distribution

Devtool can be distributed as a single ELF executable containing the Python runtime and Devtool modules. The receiving project needs only the architecture-appropriate executable and its `devtool.toml` (plus the actual project tools described by the configuration, such as Git, Docker, npm or a compiler).

## Build

From the Devtool source checkout:

```sh
./devtool build binary
# Equivalent direct packaging entry:
./scripts/build-binary.sh
```

The build host needs Docker and Python/pip to download the pinned build wheels. The default builder then uses Python 3.11 on Debian Bullseye inside Docker for a glibc 2.31 baseline. The output is `dist/linux-x86_64/devtool` on x86_64 or `dist/linux-aarch64/devtool` on AArch64, plus `devtool.sha256`. `./devtool build` uses the same packaging task; building a Python wheel remains available as `./devtool build wheel`. A native build (`./scripts/build-binary.sh --native`) requires PyInstaller in the build Python environment and targets the build host's system-library baseline.

The executable is self-contained with respect to Python, not a statically linked universal executable. Linux binaries remain architecture- and libc-dependent. Build and test on a suitable native architecture; packaging on one architecture does not create a binary for a different architecture. See [PyInstaller's Linux portability guidance](https://pyinstaller.org/en/stable/usage.html#making-gnu-linux-apps-forward-compatible).

GitHub Actions builds native x86_64 and AArch64 executable artifacts with the same builder definition. Download the matching architecture's artifact rather than copying the x86_64 executable onto an ARM64 target. The workflow uses [GitHub-hosted runner labels](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).

## Use in a project

Copy the generated file to the project's root with executable permissions and verify its checksum. Add the project's `devtool.toml`; no Python package installation is required to run the core itself:

```sh
./devtool list
./devtool plan build
./devtool build
./devtool deploy
```

Configured build scripts still require their own runtimes and tools. A Python build script needs Python; a Docker build needs Docker. The executable does not package every possible external project dependency.

The frozen engine runs its internal helpers via the same executable. For SSH file/OCI staging, the target needs a matching architecture's executable in its configured workspace (`./devtool` by default for frozen callers). An SSH target may set `engine = "/usr/local/bin/devtool"` when installed centrally. Source/Python-mode configurations without `engine` retain their previous Python-module helper invocation. Target helper versions should match the sender.

## Verify

```sh
./devtool test binary
# or ./scripts/test-binary.sh
```

This opt-in test copies the executable and a fixture config into an isolated Debian Bullseye container with no Python installed, executes ordinary commands and parameter forwarding, and completes an internal archive export/import. No real project deployment or external service is touched.
