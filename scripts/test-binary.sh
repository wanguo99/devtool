#!/bin/sh
# Prove that the portable executable needs no Python installation on its target.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
binary="$root/dist/linux-$(uname -m)/devtool"
test -x "$binary"
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT HUP INT TERM
cp "$binary" "$scratch/devtool"
mkdir "$scratch/data"
printf 'binary fixture\n' > "$scratch/data/text"
cat > "$scratch/devtool.toml" <<'TOML'
[parameters.mode]
default = "release"
[options]
debug = {parameter="mode",value="debug"}
[sources.fixture]
url = "https://example.invalid/fixture.git"
[commands]
inspect = ["sh", "-c", "printf '%s\\n' \"$1\"", "inspect", "{{mode}}"]
status = ["sh", "-c", "printf 'binary works\\n'"]
backup = ["sh", "-c", "printf '%s\\n' \"$1\"", "backup"]
[tasks.export]
transfers = [{kind="archive-pack",source="data",destination="bundle.tar.gz"}]
[tasks.import]
transfers = [{kind="archive-unpack",source="bundle.tar.gz",destination="restored"}]
TOML
cat > "$scratch/delegated.toml" <<'TOML'
[backend]
command = ["sh", "backend.sh"]
actions = ["clone", "update", "build"]
[sources.fixture]
url = "https://example.invalid/fixture.git"
branch = "main"
TOML
cat > "$scratch/backend.sh" <<'SH'
printf '%s\n' "$@" > received.txt
SH
docker run --rm --network none --user "$(id -u):$(id -g)" -e HOME=/tmp -e DEVTOOL_STATE_HOME=/tmp/state \
    --mount "type=bind,source=$scratch,target=/project" --workdir /project debian:bullseye-slim sh -eu -c '
    if command -v python3 >/dev/null; then echo "Test image unexpectedly contains Python" >&2; exit 1; fi
    ./devtool --version
    ./devtool status
    ./devtool inspect --debug
    ./devtool plan clone >/tmp/source-plan.json
    ./devtool _internal sources --help >/tmp/source-help.txt
    ./devtool _internal transport --help >/tmp/transport-help.txt
    ./devtool _internal manifest --help >/tmp/artifact-help.txt
    ./devtool _internal transport prepare-tree --root /project --destination stage
    test -d stage
    ./devtool plan export >/tmp/plan.json
    ./devtool backup -- --fixture-argument
    ./devtool export
    ./devtool import
    cmp data/text restored/text
    ./devtool artifact create --output candidate.json --file restored
    ./devtool artifact verify --manifest candidate.json
    digest=$(sha256sum data/text | cut -d " " -f 1)
    ./devtool artifact fetch --url file:///project/data/text --output cached.txt --sha256 "$digest"
    cmp data/text cached.txt
    ./devtool history --limit 1 >/tmp/history.json
    ./devtool --project delegated.toml validate >/tmp/delegated-config.json
    ./devtool --project delegated.toml plan clone fixture --list >/tmp/delegated-plan.json
    test ! -e received.txt
    ./devtool --project delegated.toml build ran --platform arm64 --jobs 8 --path "with spaces"
    printf "%s\n" build ran --platform arm64 --jobs 8 --path "with spaces" > expected.txt
    cmp received.txt expected.txt
    echo "No-Python executable, delegated options and internal archive helper: PASS"
'
