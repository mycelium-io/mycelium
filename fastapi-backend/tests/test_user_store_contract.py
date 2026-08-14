# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Contract drift guard for the global user store (backend side).

The user store is duplicated: the thin ``uv tool`` CLI carries its own write/read
primitives so it need not import this backend. A divergent store dir, frontmatter
tag, version rule, slug normalization, or serialized body means a record one side
writes is unreadable — or mis-rolled-up — by the other, silently.

This test freezes the shared shape in ``contracts/user-store.json`` at the repo
root and asserts the **backend** primitives reproduce it exactly. Its CLI twin is
``mycelium-cli/tests/test_user_store_contract.py``.
"""

import json
from pathlib import Path

from app.services import principals
from app.services.filesystem import get_data_dir, get_users_dir, read_memory_file

_CONTRACT_PATH = Path(__file__).resolve().parent.parent.parent / "contracts" / "user-store.json"


def _contract() -> dict:
    return json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))


def test_contract_file_present():
    assert _CONTRACT_PATH.is_file(), f"missing shared contract file at {_CONTRACT_PATH}"


def test_store_dir_matches_contract():
    g = _contract()
    assert get_users_dir() == get_data_dir() / g["store_dirname"]


def test_normalization_matches_contract():
    g = _contract()["normalize"]
    normalized = principals.write_user(dict(g["input"]))
    assert normalized["handle"] == g["expected"]["handle"]
    assert normalized["display_name"] == g["expected"]["display_name"]
    assert normalized["teams"] == g["expected"]["teams"]
    assert normalized["notify"] == g["expected"]["notify"]


def test_serialized_body_and_frontmatter_match_contract():
    """The record the backend writes matches the frozen body, tag, and version."""
    g = _contract()
    principals.write_user(dict(g["normalize"]["input"]))
    record = read_memory_file(get_users_dir(), g["normalize"]["expected"]["handle"])
    assert record is not None
    meta, content = record
    assert content == g["serialized_body"]
    assert meta["tags"] == [g["manifest_tag"]]
    assert meta["version"] == g["initial_version"]


def test_upsert_is_content_idempotent():
    g = _contract()
    principals.write_user({"handle": "julia"})
    # Same content: no version bump.
    principals.write_user({"handle": "julia"})
    record = read_memory_file(get_users_dir(), "julia")
    assert record is not None
    assert record[0]["version"] == g["initial_version"]
    # A real change bumps it.
    principals.write_user({"handle": "julia", "display_name": "Julia"})
    record = read_memory_file(get_users_dir(), "julia")
    assert record is not None
    assert record[0]["version"] == g["initial_version"] + 1
