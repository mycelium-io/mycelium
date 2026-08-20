# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Handle vs. slug shape rules (CLI side).

A *handle* is an identity and can be minted by a real IdP, so an email-shaped
``preferred_username`` (Cisco SSO / Keycloak) must validate. A *slug* is a
filename / composer trigger token and stays clean. These are deliberately two
patterns; regressing either back to a single slug rule reintroduces #656.
"""

import pytest
from pydantic import ValidationError

from mycelium.protocol import AgentManifest, MemoryLogEntry, UserManifest


@pytest.mark.parametrize("model", [AgentManifest, UserManifest])
def test_handle_accepts_email_shaped_identity(model: type) -> None:
    """An IdP-minted email handle registers, not just validates on login (#656)."""
    m = model(handle="user@example.com")
    assert m.handle == "user@example.com"


@pytest.mark.parametrize("model", [AgentManifest, UserManifest])
def test_handle_still_rejects_spaces_and_bad_leading_char(model: type) -> None:
    # A bare leading `@` is normalized away (lstrip), so it isn't the guard —
    # inner whitespace and a non-alphanumeric first char still are.
    with pytest.raises(ValidationError):
        model(handle="has space")
    with pytest.raises(ValidationError):
        model(handle="!bad")


def test_memory_slug_stays_clean() -> None:
    """A slug is a filename, not an identity — `@` is not allowed."""
    MemoryLogEntry(category="work", slug="cron-setup", content="ok")
    with pytest.raises(ValidationError):
        MemoryLogEntry(category="work", slug="user@example.com", content="ok")
