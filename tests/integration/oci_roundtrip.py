"""Opt-in real Docker/rsync check using only newly tagged scratch images.

No pull, container run, deployment, registry, or global cleanup is performed.
Requires an available Docker daemon with OCI-layout save support and rsync.
"""
from pathlib import Path
import json
import subprocess
import tempfile
import uuid

from devtool_core import oci, transport


def run(argv, **kwargs):
    return subprocess.run(argv, check=True, **kwargs)


def main():
    version = run(["docker", "version", "--format", "{{.Server.Version}}"], capture_output=True, text=True).stdout.strip()
    token = uuid.uuid4().hex
    tags = [f"devtool-local-fixture:{token}-{number}" for number in (1,2)]
    created = []
    try:
        with tempfile.TemporaryDirectory(prefix="devtool-oci-check-") as directory:
            root = Path(directory)
            context = root / "context"
            context.mkdir()
            (context / "Dockerfile").write_text('FROM scratch\nCOPY base.txt /base.txt\nCOPY app.txt /app.txt\nLABEL org.devtool.fixture="'+token+'"\n')
            (context / "base.txt").write_text("immutable base fixture\n" * 1024)
            cache = root / "cache"
            cache.mkdir()
            manifests = []
            reports = []
            for index, tag in enumerate(tags,1):
                (context / "app.txt").write_text(f"fixture application version {index}\n")
                run(["docker", "build", "--network=none", "--provenance=false", "--tag", tag, str(context)])
                created.append(tag)
                identity = transport.docker_identity(tag)
                source = root / f"source-{index}.tar"
                run(["docker", "image", "save", "--output", str(source), tag])
                stage = root / f"stage-{index}"
                manifest = oci.stage_archive(source, stage, tag, identity)
                manifests.append(manifest)
                result = run([*transport.rsync_options(), "--itemize-changes", "--", str(stage)+"/", str(cache)+"/"], capture_output=True, text=True)
                reports.append(result.stdout)
            shared = {item["path"] for item in manifests[0]["entries"] if item["path"].startswith("blobs/")} & {item["path"] for item in manifests[1]["entries"] if item["path"].startswith("blobs/")}
            transferred = [line for line in reports[1].splitlines() if line.startswith(">f")]
            # rsync may update metadata timestamps without retransmitting bytes.
            if not shared or any(name in line for name in shared for line in transferred):
                raise RuntimeError(f"expected unchanged blobs to be reused by rsync; shared={len(shared)}, sent={transferred}")
            second = manifests[1]
            # Only remove the unique, labelled test tag so the next load is real.
            run(["docker", "image", "rm", tags[1]])
            if transport.docker_identity(tags[1], missing_ok=True) is not None:
                raise RuntimeError("fixture tag was not removed")
            oci.load_candidate(cache, oci.identity_digest(second))
            if transport.docker_identity(tags[1]) != second["identity"]:
                raise RuntimeError("reloaded test image has a different identity")
            print(json.dumps({"docker_server":version,"result":"PASSED","shared_blob_count":len(shared),
                              "source_archives":2,"reloaded_identity_matches":True,"second_rsync_stats":reports[1]},indent=2))
    finally:
        for tag in reversed(created):
            result = subprocess.run(["docker","image","inspect","--format",'{{index .Config.Labels "org.devtool.fixture"}}',tag],capture_output=True,text=True)
            if result.returncode == 0 and result.stdout.strip() == token:
                run(["docker","image","rm",tag])


if __name__ == "__main__":
    main()
