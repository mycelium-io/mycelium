# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Handle vs. slug shape rules (backend side).

A *handle* is an identity and can be minted by a real IdP, so an email-shaped
``preferred_username`` (Cisco SSO / Keycloak) must validate. A *slug* is a
filename / composer trigger token and stays clean. These are deliberately two
patterns; regressing either back to a single slug rule reintroduces #656.
"""

import pytest
from pydantic import ValidationError

from app.routes.engines import _HANDLE_RE
from app.schemas import SkillCreate, UserCreate


def test_user_handle_accepts_email_shaped_identity() -> None:
    """An IdP-minted email handle registers, not just validates on login (#656)."""
    assert UserCreate(handle="user@example.com").handle == "user@example.com"


def test_engine_handle_regex_accepts_email_shaped_identity() -> None:
    assert _HANDLE_RE.match("user@example.com")
    assert not _HANDLE_RE.match("has space")


def test_skill_name_stays_clean() -> None:
    """A skill name is a `/trigger token / filename, not an identity — no `@`."""
    SkillCreate(name="deploy-runbook", created_by="tester")
    with pytest.raises(ValidationError):
        SkillCreate(name="user@example.com", created_by="tester")
