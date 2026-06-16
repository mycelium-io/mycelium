# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for outbound posting from the hermes plugin.

Covers the two regressions the smoke test caught:

1. ``post_to_room`` must send ``message_type: "broadcast"`` — the backend's
   :class:`MessageCreate` schema requires the field and rejects with 422
   when it's missing (the openclaw TS plugin sends ``"broadcast"`` for the
   same reason, mirrored at ``post-to-room.ts:36``).

2. ``MyceliumRoomAdapter.send()`` receives a chat_id of the form
   ``<room>:<agent>`` (set up by :meth:`_dispatch` to give hermes a
   per-agent session key), but the backend wants just the room slug.
   ``send()`` must :py:meth:`str.rpartition` the chat_id and use the
   trailing component as the default sender_handle.

The plugin's pure helpers run fine under the test interpreter, but
``adapter.py`` itself imports ``gateway.config`` / ``gateway.platforms.base``,
so we test by:

* importing ``post_to_room`` directly via :mod:`importlib.util` (no
  hermes dependency),
* re-implementing the tiny chat_id split in a tested helper so the same
  contract is asserted without booting hermes.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


def _ensure_aiohttp_stub() -> None:
    """Install a minimal ``aiohttp`` shim so the plugin module imports.

    ``aiohttp`` is a hermes-side runtime dependency (the platform plugin
    uses it for SSE + POSTbacks), not a mycelium-cli dependency. The test
    mocks the network surface, so we just need ``aiohttp.ClientError``,
    ``aiohttp.ClientTimeout``, and a placeholder ``ClientSession`` /
    ``ClientResponse`` to satisfy the top-level imports in
    ``post_to_room.py``.
    """
    if "aiohttp" in sys.modules:
        return
    stub = types.ModuleType("aiohttp")
    # Direct attribute assignment is the natural way to populate a fake
    # module; ty doesn't model arbitrary ModuleType attribute writes, but
    # at runtime this is the standard pattern. ``B010`` (setattr→assign)
    # is silenced inline below to keep both checkers happy.
    stub.ClientError = type("ClientError", (Exception,), {})  # ty: ignore[unresolved-attribute] # noqa: B010
    stub.ClientTimeout = lambda total=None: ("ClientTimeout", total)  # ty: ignore[unresolved-attribute] # noqa: B010
    stub.ClientSession = MagicMock  # ty: ignore[unresolved-attribute] # noqa: B010
    stub.ClientResponse = MagicMock  # ty: ignore[unresolved-attribute] # noqa: B010
    sys.modules["aiohttp"] = stub


_ensure_aiohttp_stub()

_PLUGIN_ROOT = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "mycelium"
    / "integrations"
    / "hermes"
    / "assets"
    / "mycelium"
    / "plugin"
)
# Distinct from test_hermes_route's synthetic package — sharing the same
# name would let an early ``sys.modules`` cache in either test file mask
# missing submodules in the other (we hit this when both files ran in
# alphabetical order: postback registered the bare package skeleton, then
# route's loader saw ``in sys.modules`` and skipped its own submodule load).
_PKG = "_hermes_plugin_postback_under_test"


def _load_post_to_room():
    if f"{_PKG}.post_to_room" in sys.modules:
        return sys.modules[f"{_PKG}.post_to_room"]

    # Mirror the route-test loader: install a synthetic package, exec the
    # module by file path so the plugin's relative imports resolve cleanly.
    if _PKG not in sys.modules:
        pkg_spec = importlib.util.spec_from_file_location(
            _PKG,
            _PLUGIN_ROOT / "__init__.py",
            submodule_search_locations=[str(_PLUGIN_ROOT)],
        )
        assert pkg_spec is not None
        pkg_module = importlib.util.module_from_spec(pkg_spec)
        sys.modules[_PKG] = pkg_module
        pkg_module.__path__ = [str(_PLUGIN_ROOT)]

    spec = importlib.util.spec_from_file_location(
        f"{_PKG}.post_to_room",
        _PLUGIN_ROOT / "post_to_room.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"{_PKG}.post_to_room"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def post_to_room():
    return _load_post_to_room().post_to_room


# ── post_to_room: message_type + url ────────────────────────────────────────


def _make_mock_session(status: int = 200, body: Any = None) -> tuple[MagicMock, MagicMock]:
    """Return ``(session, response_ctx)`` matching ``aiohttp.ClientSession``."""
    if body is None:
        body = {"id": "msg-1"}
    response = MagicMock()
    response.status = status
    response.text = AsyncMock(return_value="(body)")
    response.json = AsyncMock(return_value=body)
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock()
    session.post = MagicMock(return_value=response)
    return session, response


@pytest.mark.asyncio
async def test_post_to_room_sends_broadcast_message_type(post_to_room) -> None:
    """A 422 from the backend regression was the trigger for this test."""
    session, _ = _make_mock_session()
    mid = await post_to_room(
        session=session,
        backend_url="http://localhost:8000",
        room="demo",
        sender_handle="julia-agent",
        content="pong",
    )
    assert mid == "msg-1"
    call_kwargs = session.post.call_args.kwargs
    payload = call_kwargs["json"]
    assert payload == {
        "sender_handle": "julia-agent",
        "content": "pong",
        "message_type": "broadcast",
    }
    # URL must not be double-slashed and must use the bare room slug, not
    # a colon-joined chat_id (that's the caller's job to split).
    assert session.post.call_args.args[0] == "http://localhost:8000/api/rooms/demo/messages"


@pytest.mark.asyncio
async def test_post_to_room_strips_trailing_backend_slash(post_to_room) -> None:
    session, _ = _make_mock_session()
    await post_to_room(
        session=session,
        backend_url="http://localhost:8000/",
        room="demo",
        sender_handle="julia-agent",
        content="ping",
    )
    assert session.post.call_args.args[0] == "http://localhost:8000/api/rooms/demo/messages"


@pytest.mark.asyncio
async def test_post_to_room_attaches_bearer_when_token_set(post_to_room) -> None:
    session, _ = _make_mock_session()
    await post_to_room(
        session=session,
        backend_url="http://localhost:8000",
        room="demo",
        sender_handle="julia-agent",
        content="ping",
        api_token="secret",
    )
    headers = session.post.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer secret"
    assert headers["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_post_to_room_returns_none_on_4xx(post_to_room) -> None:
    """4xx is best-effort — we log a warning and return None so the adapter
    can decide to retry without raising into the agent loop."""
    session, _ = _make_mock_session(status=422)
    mid = await post_to_room(
        session=session,
        backend_url="http://localhost:8000",
        room="demo",
        sender_handle="julia-agent",
        content="ping",
    )
    assert mid is None


# ── chat_id ⇆ (room, sender) split ──────────────────────────────────────────
#
# We mirror the exact split the adapter does inside ``send()`` so the
# contract is testable without booting Hermes's ``gateway.platforms.base``
# (which the adapter module imports at top level). Keep this in lockstep
# with ``adapter.py:send()``.


def _split_chat_id(chat_id: str) -> tuple[str, str]:
    """Return ``(room, default_sender)``; mirror of :meth:`adapter.send` logic."""
    room, _sep, default_sender = chat_id.rpartition(":")
    if not room:
        return chat_id, ""
    return room, default_sender


@pytest.mark.parametrize(
    ("chat_id", "expected_room", "expected_sender"),
    [
        # Parent-room dispatch (Dispatch.agent_id appended).
        ("hermes-demo:julia-agent", "hermes-demo", "julia-agent"),
        # Session sub-room: ``parent:session:<uuid>`` ─ rpartition keeps the
        # parent prefix intact and uses the uuid as the (synthetic) sender.
        ("hermes-demo:session:abc123", "hermes-demo:session", "abc123"),
        # Bare room slug, no colon — adapter falls back to ``hermes-agent``
        # at send time (default_sender empty triggers the fallback branch).
        ("hermes-demo", "hermes-demo", ""),
    ],
)
def test_chat_id_split(chat_id: str, expected_room: str, expected_sender: str) -> None:
    room, sender = _split_chat_id(chat_id)
    assert (room, sender) == (expected_room, expected_sender)
