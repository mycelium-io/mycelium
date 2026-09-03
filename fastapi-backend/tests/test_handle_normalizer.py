# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""One handle normalizer, everywhere a handle is compared.

``agent_registry.norm_handle`` is the canonical spelling of "the same handle":
strip, drop a leading ``@``, lowercase. Every module routes through it, so the
rules cannot drift per caller.
"""

from __future__ import annotations

import pathlib
import re

from app.routes import participate
from app.services import aligner, auth, principals, tasks
from app.services.agent_registry import norm_handle

APP = pathlib.Path(__file__).resolve().parents[1] / "app"

#: The inline shape a private copy takes. Only the canonical module may spell it.
_INLINE_NORMALIZER = re.compile(r"\.strip\(\)\.lstrip\(\"@\"\)\.lower\(\)")


def test_every_private_norm_is_the_canonical_one() -> None:
    for spelling in ("Alice", "@alice", " alice ", "@ALICE "):
        assert principals._norm(spelling) == "alice"
        assert tasks._norm(spelling) == "alice"
        assert participate._norm(spelling) == "alice"
        assert aligner._norm(spelling) == "alice"
        assert auth.normalize_handle(spelling) == "alice"
        assert norm_handle(spelling) == "alice"


def test_a_blank_handle_is_blank_in_every_spelling() -> None:
    assert norm_handle("  @ ") is None
    assert principals._norm("") is None
    assert auth.normalize_handle(None) is None
    assert tasks._norm("@") == ""
    assert participate._norm("") == ""
    assert aligner._norm(" ") == ""


def test_no_module_reimplements_the_normalizer_inline() -> None:
    offenders = sorted(
        str(path.relative_to(APP))
        for path in APP.rglob("*.py")
        if path.name != "agent_registry.py" and _INLINE_NORMALIZER.search(path.read_text())
    )
    assert offenders == [], f"private handle normalizers: {offenders}"
