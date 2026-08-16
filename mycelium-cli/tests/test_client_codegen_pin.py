# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The generator pin is shared by two codegen paths; keep them identical.

``mycelium_backend_client`` is generated, not committed, and two things
generate it: ``scripts/gen-mycelium-client.sh`` (developers, CI, release) and
``setup.py``'s build hook (fresh clone, editable install, wheel). They agree on
the output only while they agree on the generator version — a split pin means
the client a developer sees and the client a wheel ships are different code.
"""

import re
import tomllib
from pathlib import Path

import pytest

_CLI_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT = _CLI_ROOT / "pyproject.toml"
_GEN_SCRIPT = _CLI_ROOT.parent / "scripts" / "gen-mycelium-client.sh"


def _pyproject_pin() -> str | None:
    requires = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))["build-system"]["requires"]
    for req in requires:
        if req.startswith("openapi-python-client"):
            return req.split("==")[1]
    return None


def _script_pin() -> str | None:
    match = re.search(
        r"^GENERATOR_VERSION=(\S+)$", _GEN_SCRIPT.read_text(encoding="utf-8"), re.MULTILINE
    )
    return match.group(1) if match else None


def test_build_hook_pins_the_generator():
    assert _pyproject_pin(), "build-system requires must pin openapi-python-client=="


def test_script_and_build_hook_agree():
    if not _GEN_SCRIPT.is_file():
        pytest.skip("generator script only exists in the repo, not in an installed package")
    assert _script_pin() == _pyproject_pin()
