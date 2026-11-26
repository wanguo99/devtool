#!/bin/sh
# Native-architecture, glibc-baseline self-contained Linux executable.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
case "$(uname -m)" in
    x86_64|aarch64) arch=$(uname -m) ;;
    *) echo 'Unsupported binary architecture' >&2; exit 2 ;;
esac
output="$root/dist/linux-$arch"
mkdir -p "$output"
if [ "$#" -eq 1 ] && [ "$1" = "--native" ]; then
    # The caller provides PyInstaller in the selected build Python environment.
    PYTHONPATH="$root/src${PYTHONPATH:+:$PYTHONPATH}" python3 -m PyInstaller --noconfirm --clean --onefile --noupx \
        --name devtool --paths "$root/src" --collect-submodules devtool_core \
        --distpath "$output" --workpath "$root/build/pyinstaller-$arch" --specpath "$root/build" "$root/packaging/entry.py"
elif [ "$#" -eq 0 ]; then
    builder="devtool-binary-builder:py311-bullseye-$arch"
    context="$root/.cache/binary-builder-$arch"
    mkdir -p "$context/wheels"
    cp "$root/packaging/Dockerfile" "$root/packaging/requirements.txt" "$context/"
    python3 -m pip download --only-binary=:all: --python-version 311 \
        --implementation cp --abi cp311 --platform "manylinux2014_$arch" \
        --dest "$context/wheels" -r "$context/requirements.txt"
    docker build --network none --tag "$builder" "$context"
    docker run --rm --network none --user "$(id -u):$(id -g)" \
        -e HOME=/tmp -e PYTHONPATH=/src/src -e PYINSTALLER_CONFIG_DIR=/tmp/pyinstaller \
        --mount "type=bind,source=$root,target=/src,readonly" \
        --mount "type=bind,source=$output,target=/out" \
        "$builder" python -m PyInstaller --noconfirm --clean --onefile --noupx \
        --name devtool --paths /src/src --collect-submodules devtool_core \
        --distpath /out --workpath /tmp/work --specpath /tmp /src/packaging/entry.py
else
    echo 'Usage: build-binary.sh [--native]' >&2; exit 2
fi
(cd "$output" && sha256sum devtool > devtool.sha256)
"$output/devtool" --version
printf 'Binary: %s\n' "$output/devtool"
