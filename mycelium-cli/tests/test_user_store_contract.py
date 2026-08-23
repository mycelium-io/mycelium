# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Contract drift guard for the global user store (CLI side).

The store is the hub's: the CLI is a client of ``/api/users`` and writes no user
files, so the frozen file shape in ``contracts/user-store.json`` — store dir,
frontmatter tag, version rule, serialized body — is asserted by the backend
twin, ``fastapi-backend/tests/test_user_store_contract.py``, the store's only
producer.

What has to agree across the two is what survives the wire: the CLI normalizes a
handle and its team slugs in ``UserManifest`` before sending them, and the
backend re-normalizes on write. Diverge, and the handle the CLI shows you is not
the one keying the record it just wrote. So this locks the CLI's normalization to
the same fixture and checks the body it puts on the wire carries the contract's
fields.
"""

import json
from pathlib import Path

from mycelium.commands import user as user_cmd
from mycelium.protocol import UserManifest

_CONTRACT_PATH = Path(__file__).resolve().parent.parent.parent / "contracts" / "user-store.json"


def _contract() -> dict:
    return json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))


def test_contract_file_present():
    assert _CONTRACT_PATH.is_file(), f"missing shared contract file at {_CONTRACT_PATH}"


def test_normalization_matches_contract():
    g = _contract()["normalize"]
    u = UserManifest(**g["input"])
    assert u.handle == g["expected"]["handle"]
    assert u.display_name == g["expected"]["display_name"]
    assert u.teams == g["expected"]["teams"]
    assert u.notify == g["expected"]["notify"]


def test_handle_lookups_normalize_the_same_way():
    """A handle read back is keyed the way the record was written."""
    g = _contract()["normalize"]
    assert user_cmd._norm_handle(g["input"]["handle"]) == g["expected"]["handle"]


def test_wire_body_carries_the_contract_fields():
    """What the CLI POSTs is the record the contract describes, plus attribution."""
    from mycelium_backend_client.models import UserCreate

    g = _contract()
    user = UserManifest(**g["normalize"]["input"])
    body = UserCreate(
        handle=user.handle,
        display_name=user.display_name,
        teams=user.teams,
        notify=user.notify,
        created_by="tester",
    ).to_dict()

    expected = g["normalize"]["expected"]
    assert body["handle"] == expected["handle"]
    assert body["display_name"] == expected["display_name"]
    assert body["teams"] == expected["teams"]
    assert body["created_by"] == "tester"
    # The store's own fields are exactly the contract's; nothing else travels.
    assert set(body) - {"created_by"} == set(expected)
