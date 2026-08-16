# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Contract drift guard for the global user store (CLI side).

The user store is duplicated: the thin ``uv tool`` CLI carries its own
``UserManifest`` + ``commands.user`` write/read primitives so it need not import
the FastAPI backend. A divergent store dir, frontmatter tag, version rule, slug
normalization, or serialized body means a record one side writes is unreadable —
or mis-rolled-up — by the other, silently.

This test freezes the shared shape in ``contracts/user-store.json`` at the repo
root and asserts the **CLI** primitives reproduce it exactly. Its backend twin is
``fastapi-backend/tests/test_user_store_contract.py``.
"""

import json
from pathlib import Path

import yaml

from mycelium.commands import user as user_cmd
from mycelium.filesystem import get_mycelium_dir, get_users_dir
from mycelium.protocol import UserManifest

_CONTRACT_PATH = Path(__file__).resolve().parent.parent.parent / "contracts" / "user-store.json"


def _contract() -> dict:
    return json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))


def test_contract_file_present():
    assert _CONTRACT_PATH.is_file(), f"missing shared contract file at {_CONTRACT_PATH}"


def test_store_dir_matches_contract(isolated_home):  # noqa: ANN001
    g = _contract()
    assert get_users_dir() == get_mycelium_dir() / g["store_dirname"]


def test_normalization_matches_contract():
    g = _contract()["normalize"]
    u = UserManifest(**g["input"])
    assert u.handle == g["expected"]["handle"]
    assert u.display_name == g["expected"]["display_name"]
    assert u.teams == g["expected"]["teams"]
    assert u.notify == g["expected"]["notify"]


def test_serialized_body_matches_contract():
    """The frontmatter body the CLI writes is byte-for-byte the contract."""
    g = _contract()
    u = UserManifest(**g["normalize"]["input"])
    body = u.model_dump(exclude={"handle"})
    yaml_body = yaml.safe_dump(body, sort_keys=False, default_flow_style=False).strip()
    assert yaml_body == g["serialized_body"]


def test_write_applies_tag_and_version(isolated_home):  # noqa: ANN001
    g = _contract()
    user_cmd._write_user(UserManifest(handle="avery"), created_by="tester")
    record = user_cmd.read_memory(get_users_dir(), "avery")
    assert record is not None
    assert record[0]["tags"] == [g["manifest_tag"]]
    assert record[0]["version"] == g["initial_version"]
    # Content-idempotent: re-writing the same record does NOT bump the version.
    user_cmd._write_user(UserManifest(handle="avery"), created_by="tester")
    same = user_cmd.read_memory(get_users_dir(), "avery")
    assert same is not None
    assert same[0]["version"] == g["initial_version"]
    # A real change bumps it.
    user_cmd._write_user(UserManifest(handle="avery", display_name="Avery"), created_by="tester")
    bumped = user_cmd.read_memory(get_users_dir(), "avery")
    assert bumped is not None
    assert bumped[0]["version"] == g["initial_version"] + 1
