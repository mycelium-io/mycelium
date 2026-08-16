"""Build hook: generate the vendored OpenAPI client before packaging.

``src/mycelium_backend_client/`` is a build artifact, not source. It is
generated from the repo's committed ``openapi.json`` snapshot — the same spec
``scripts/gen-mycelium-client.sh`` uses — so a fresh clone, an editable install
and a release wheel all carry a client that matches the backend's API instead
of whatever was last committed by hand.

Skips itself when the generated tree already matches the spec (stamped by
hash), when the spec is out of reach (a build context that ships only
``src/``, e.g. the collector image), or when ``MYCELIUM_SKIP_CLIENT_GEN`` is
set.
"""

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from setuptools import setup

GENERATOR = "openapi_python_client"
HERE = Path(__file__).parent.resolve()
CLIENT = HERE / "src" / "mycelium_backend_client"
STAMP = CLIENT / ".openapi-sha256"


def _spec_path() -> Path | None:
    spec = Path(os.environ.get("MYCELIUM_OPENAPI_SPEC") or HERE.parent / "openapi.json")
    return spec if spec.is_file() else None


def _generate(spec: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "gen"
        subprocess.run(
            [
                sys.executable,
                "-m",
                GENERATOR,
                "generate",
                "--path",
                str(spec),
                "--output-path",
                str(out),
                "--overwrite",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        shutil.rmtree(CLIENT, ignore_errors=True)
        shutil.copytree(out / "mycelium_backend_client", CLIENT)


def _ensure_client() -> None:
    if os.environ.get("MYCELIUM_SKIP_CLIENT_GEN"):
        return

    spec = _spec_path()
    if spec is None:
        # No spec in this build context. An existing tree is used as-is; a
        # missing one means the caller has to generate it (the release build
        # asserts the wheel carries the client, so this can't ship silently).
        if not CLIENT.is_dir():
            print("warning: no openapi.json found; skipping client generation", file=sys.stderr)
        return

    digest = hashlib.sha256(spec.read_bytes()).hexdigest()
    if STAMP.is_file() and STAMP.read_text().strip() == digest:
        return

    print(f"generating mycelium_backend_client from {spec}", file=sys.stderr)
    _generate(spec)
    STAMP.write_text(f"{digest}\n")


_ensure_client()
setup()
