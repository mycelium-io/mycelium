# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""A corrupt agent manifest must log loudly rather than masquerade as "missing".

`_load_manifest` returns ``None`` for both "no file" and "file unreadable" —
that's a deliberate simplification so callers don't need a discriminated
return — but the unreadable cases (bad YAML, wrong shape, schema mismatch)
have to log at WARNING. Without this a corrupt file looks identical to "agent
not registered": the user gets "agent not found" from every command and the
daemon silently ignores every @handle mention.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from mycelium import filesystem
from mycelium.commands.agent import _load_manifest
from mycelium.daemon.dispatch import load_manifest as daemon_load_manifest


@pytest.fixture(autouse=True)
def _tmp_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(filesystem, "get_mycelium_dir", lambda: tmp_path)


def _write_manifest_file(room: str, handle: str, content: str) -> Path:
    """Write a raw manifest file at the canonical path for the loaders."""
    room_dir = filesystem.get_room_dir(room)
    agents_dir = room_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    path = agents_dir / f"{handle}.md"
    path.write_text(content, encoding="utf-8")
    return path


# ── commands/agent.py:_load_manifest ─────────────────────────────────────────


def test_missing_manifest_returns_none_silently(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="mycelium.commands.agent"):
        assert _load_manifest("room", "ghost") is None
    assert caplog.records == [], "missing manifest must NOT log — only corrupt ones should"


def test_corrupt_yaml_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    path = _write_manifest_file("room", "broken", "---\n: not: valid: yaml: [\n")
    with caplog.at_level(logging.WARNING, logger="mycelium.commands.agent"):
        assert _load_manifest("room", "broken") is None
    assert any("invalid YAML" in r.message and str(path) in r.message for r in caplog.records), (
        "corrupt YAML must surface as a WARNING with the file path"
    )


def test_schema_violation_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    # Valid YAML, wrong shape: AgentManifest requires `adapter` etc.
    path = _write_manifest_file(
        "room", "schema-bad", "---\nkey: agents/schema-bad\n---\nfoo: bar\n"
    )
    with caplog.at_level(logging.WARNING, logger="mycelium.commands.agent"):
        assert _load_manifest("room", "schema-bad") is None
    assert any(
        "schema validation failed" in r.message and str(path) in r.message for r in caplog.records
    ), "schema mismatch must surface as a WARNING with the file path"


# ── daemon/dispatch.py:load_manifest (same swallow on the daemon side) ───────


def test_daemon_loader_logs_corrupt_yaml(caplog: pytest.LogCaptureFixture) -> None:
    path = _write_manifest_file("room", "daemon-broken", "---\n: not: valid: [\n")
    with caplog.at_level(logging.WARNING, logger="mycelium.daemon"):
        assert daemon_load_manifest("room", "daemon-broken") is None
    assert any("invalid YAML" in r.message and str(path) in r.message for r in caplog.records), (
        "the daemon must log corrupt manifests, not silently ignore the mention"
    )
