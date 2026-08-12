# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""`_pick_room`: fetch rooms → picker, with create-new."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

runner = CliRunner()


# ── _pick_room: fetch rooms → picker, with create-new ─────────────────────────


class _FakeRoom:
    def __init__(self, name: str) -> None:
        self._n = name

    def to_dict(self) -> dict:
        return {"name": self._n}


class _NullCM:
    def __enter__(self):
        return object()

    def __exit__(self, *_a):
        return False


class _Ask:
    def __init__(self, value):
        self._v = value

    def ask(self):
        return self._v


def _patch_rooms(monkeypatch, *, rooms, created: list):
    from mycelium.commands import agent as agent_mod

    monkeypatch.setattr(agent_mod, "_typed_client", lambda _c: _NullCM())
    monkeypatch.setattr(
        "mycelium_backend_client.api.rooms.list_rooms_api_rooms_get.sync",
        lambda **_kw: [_FakeRoom(r) for r in rooms],
    )
    monkeypatch.setattr(
        "mycelium_backend_client.api.rooms.create_room_api_rooms_post.sync",
        lambda *, client, body: created.append(body.name) or _FakeRoom(body.name),
    )


def test_pick_room_returns_existing_without_creating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import questionary

    from mycelium.commands.agent import _pick_room

    created: list[str] = []
    _patch_rooms(monkeypatch, rooms=["alpha", "beta"], created=created)
    monkeypatch.setattr(questionary, "select", lambda *a, **k: _Ask("beta"))

    cfg = type("C", (), {"rooms": type("R", (), {"active": "alpha"})()})()
    assert _pick_room(cfg) == "beta"  # ty: ignore[invalid-argument-type]
    assert created == []  # picked existing → no room created


def test_pick_room_creates_new_when_sentinel_chosen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import questionary

    from mycelium.commands.agent import _pick_room

    created: list[str] = []
    _patch_rooms(monkeypatch, rooms=["alpha"], created=created)
    # select returns the create-new sentinel; text supplies the name
    monkeypatch.setattr(questionary, "select", lambda *a, **k: _Ask("\x00new"))
    monkeypatch.setattr(questionary, "text", lambda *a, **k: _Ask("fresh-room"))

    cfg = type("C", (), {"rooms": type("R", (), {"active": None})()})()
    assert _pick_room(cfg) == "fresh-room"  # ty: ignore[invalid-argument-type]
    assert created == ["fresh-room"]  # backend room actually created


def test_pick_room_no_rooms_prompts_then_creates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import questionary

    from mycelium.commands.agent import _pick_room

    created: list[str] = []
    _patch_rooms(monkeypatch, rooms=[], created=created)
    monkeypatch.setattr(questionary, "text", lambda *a, **k: _Ask("only-room"))

    cfg = type("C", (), {"rooms": type("R", (), {"active": None})()})()
    assert _pick_room(cfg) == "only-room"  # ty: ignore[invalid-argument-type]
    assert created == ["only-room"]
