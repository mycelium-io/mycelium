# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cisco Systems, Inc. and its affiliates

"""
Tests for structured memory conventions and synthesis grouping.

These test the _build_structured_context function which groups memories
by category prefix for structure-aware LLM synthesis.
"""

from datetime import UTC, datetime
from types import SimpleNamespace

from app.services.async_coordination import STRUCTURED_CATEGORIES, _build_structured_context


def _make_memory(
    key: str, created_by: str = "agent-a", content_text: str | None = None, value=None
):
    """Create a minimal memory-like object for testing."""
    return SimpleNamespace(
        key=key,
        created_by=created_by,
        created_at=datetime(2026, 3, 18, 3, 0, 0, tzinfo=UTC),
        content_text=content_text or f"Content for {key}",
        value=value or {"text": f"Value for {key}"},
    )


def test_structured_categories_defined():
    """Verify expected categories are present."""
    assert "work" in STRUCTURED_CATEGORIES
    assert "decisions" in STRUCTURED_CATEGORIES
    assert "context" in STRUCTURED_CATEGORIES
    assert "status" in STRUCTURED_CATEGORIES
    assert "procedures" in STRUCTURED_CATEGORIES


def test_build_structured_context_groups_by_category():
    """Memories with category prefixes should be grouped under headings."""
    memories = [
        _make_memory("work/cron-setup", content_text="Created crontab"),
        _make_memory("status/cron", content_text="ACTIVE"),
        _make_memory("decisions/db", content_text="Chose AgensGraph"),
        _make_memory("context/goal", content_text="Monitor tickets"),
    ]

    context = _build_structured_context(memories)

    assert "### Work Done" in context
    assert "### Current Status" in context
    assert "### Decisions Made" in context
    assert "### Background & Preferences" in context
    assert "Created crontab" in context
    assert "ACTIVE" in context
    assert "Chose AgensGraph" in context
    assert "Monitor tickets" in context


def test_build_structured_context_uncategorized():
    """Memories without known category prefixes go to 'Other'."""
    memories = [
        _make_memory("random/note", content_text="Some note"),
        _make_memory("toplevel", content_text="No category"),
    ]

    context = _build_structured_context(memories)

    assert "### Other Contributions" in context
    assert "Some note" in context
    assert "No category" in context


def test_build_structured_context_mixed():
    """Mix of categorized and uncategorized memories."""
    memories = [
        _make_memory("work/setup", content_text="Did setup"),
        _make_memory("misc/note", content_text="Random thing"),
        _make_memory("status/build", content_text="PASSING"),
    ]

    context = _build_structured_context(memories)

    assert "### Work Done" in context
    assert "### Current Status" in context
    assert "### Other Contributions" in context
    assert "Did setup" in context
    assert "Random thing" in context
    assert "PASSING" in context
    # Empty categories should not appear
    assert "### Decisions Made" not in context
    assert "### Background & Preferences" not in context


def test_build_structured_context_empty():
    """Empty memory list should return empty string."""
    context = _build_structured_context([])
    assert context == ""


def test_build_structured_context_preserves_agent_handles():
    """Agent handles should appear in the output."""
    memories = [
        _make_memory("work/task", created_by="julia-agent", content_text="Built widget"),
    ]

    context = _build_structured_context(memories)

    assert "julia-agent" in context
