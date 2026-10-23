# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Handle vs. slug shape rules (CLI side).

A *handle* is an identity and can be minted by a real IdP, so an email-shaped
``preferred_username`` (Cisco SSO / Keycloak) must validate. A *slug* is a
filename / composer trigger token and stays clean. The two stay separate
patterns.
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


@pytest.mark.parametrize("category", ["context", "procedures"])
def test_context_and_procedures_keys_can_have_folders(category: str) -> None:
    entry = MemoryLogEntry(category=category, slug="Foo/bar/baz", content="ok")  # ty: ignore[invalid-argument-type]
    assert entry.key == f"{category}/foo/bar/baz"


@pytest.mark.parametrize(
    "slug", ["foo//bar", "/foo", "foo/../bar", "foo/./bar", "foo/-bar", "foo/b@r", "foo/b r"]
)
def test_every_part_of_a_nested_key_is_a_slug(slug: str) -> None:
    with pytest.raises(ValidationError, match="each part between `/`"):
        MemoryLogEntry(category="context", slug=slug, content="ok")


@pytest.mark.parametrize("category", ["work", "decisions", "status"])
def test_a_board_rows_key_stays_one_name(category: str) -> None:
    """Every key under these is a row on the board, so it has no folders."""
    with pytest.raises(ValidationError, match=f"a {category}/ key is a row on the board") as e:
        MemoryLogEntry(category=category, slug="foo/bar", content="ok")  # ty: ignore[invalid-argument-type]
    assert f"like {category}/foo-bar" in str(e.value)
