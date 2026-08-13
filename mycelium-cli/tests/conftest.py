# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Shared fixtures + in-process fakes for the CLI test suite.

One import gets you a fake backend/transport stack — no SLIM node, no running
backend server, no live HTTP. Before this module every file re-declared its own
``_FakeResp`` / ``_FakeClient`` (six near-identical copies across the connector
and daemon tests) and the membership tests each ported ``_FakeSlimClient`` by
hand. This is the single home for them.

What stands in for what:

* :class:`FakeSlimClient` — ``mycelium.slim.client.SlimClient`` with a scripted
  inbox, for the member/daemon message-stream tests.
* :class:`FakeResp` / :class:`FakeHTTPXClient` + the :func:`fake_httpx` fixture —
  ``httpx.AsyncClient`` / ``httpx.Client``, so the connector/daemon HTTP calls run
  without a backend.
* :func:`stub_typed_client` (via the :func:`backend` fixture) — the generated
  ``mycelium_backend_client`` typed-client plumbing a command goes through
  (``MyceliumConfig.load`` / ``_typed_client`` / ``_resolve_room``), so a command
  test only has to script the one API ``.sync`` it exercises.
* :func:`isolated_home` — points ``Path.home()`` (hence ``get_mycelium_dir``) at a
  temp dir so no test reads or writes the real ``~/.mycelium``.

See ``tests/README.md`` for the "test a command without a live stack" recipe.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, Mock

import httpx
import pytest

from mycelium.slim.client import SlimReceiveTimeout

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


# ── SLIM transport ────────────────────────────────────────────────────────────


class FakeSlimClient:
    """A minimal stand-in for ``SlimClient`` that replays a scripted inbox.

    ``inbox`` / ``published`` are class-level so a test can preload messages
    before the client is constructed (the member core builds its own client). An
    empty inbox blocks briefly then raises :class:`SlimReceiveTimeout`, which the
    reconnecting stream reads as "quiet, still connected". Reset per test with
    :meth:`reset`.
    """

    inbox: list[bytes] = []  # noqa: RUF012 — intentionally class-level scripted queue
    published: list[bytes] = []  # noqa: RUF012

    def __init__(self, _identity: Any, *, secret: str | None = None) -> None:
        pass

    @classmethod
    def reset(cls) -> None:
        cls.inbox = []
        cls.published = []

    async def connect(self, _endpoint: str) -> FakeSlimClient:
        return self

    async def listen_for_session(self) -> str:
        return "session-1"

    async def close(self) -> None:
        pass

    @staticmethod
    async def publish(_session: Any, data: bytes) -> None:
        FakeSlimClient.published.append(data)

    @staticmethod
    async def receive_message(_session: Any, *, timeout_s: float = 30.0):  # noqa: ARG004
        if not FakeSlimClient.inbox:
            await asyncio.sleep(0.02)
            raise SlimReceiveTimeout("receive timeout")
        payload = FakeSlimClient.inbox.pop(0)

        class _Msg:
            def __init__(self, p: bytes) -> None:
                self.payload = p

        return _Msg(payload)


@pytest.fixture
def fake_slim_client() -> type[FakeSlimClient]:
    """The :class:`FakeSlimClient` class, reset to a clean inbox/outbox.

    Monkeypatch it in where the code under test imports ``SlimClient``, e.g.
    ``monkeypatch.setattr(member, "SlimClient", fake_slim_client)``.
    """
    FakeSlimClient.reset()
    return FakeSlimClient


# ── HTTP transport (httpx) ────────────────────────────────────────────────────


class FakeResp:
    """A stand-in for ``httpx.Response``.

    ``json()`` returns the scripted ``payload``; ``raise_for_status()`` raises
    when ``boom`` is set (to exercise the error branch). This unifies the six
    ``_FakeResp`` variants that used to live in the connector/daemon tests.
    """

    def __init__(self, payload: Any = None, *, boom: bool = False, status_code: int = 200) -> None:
        self._payload = payload
        self._boom = boom
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self._boom:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> Any:
        return self._payload


class FakeHTTPXClient:
    """A stand-in for ``httpx.AsyncClient`` / ``httpx.Client`` (async + sync).

    Records every request as ``(method, url, json/params)`` onto the shared
    ``calls`` list and returns a scripted :class:`FakeResp`. ``responder`` maps a
    request to a response; by default every call yields an empty-payload 200.
    Works as both an async and a sync context manager, so the one fake covers the
    connector's ``async with httpx.AsyncClient()`` and a command's
    ``with httpx.Client()``.
    """

    def __init__(
        self,
        calls: list[tuple[str, str, dict]],
        responder: Callable[[str, str, dict], FakeResp],
    ) -> None:
        self._calls = calls
        self._responder = responder

    # context-manager protocol (both flavors)
    async def __aenter__(self) -> FakeHTTPXClient:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    def __enter__(self) -> FakeHTTPXClient:
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False

    def _record(self, method: str, url: str, payload: dict) -> FakeResp:
        self._calls.append((method, url, payload))
        return self._responder(method, url, payload)

    async def get(self, url: str, *, params: dict | None = None, **_: Any) -> FakeResp:
        return self._record("GET", url, params or {})

    async def post(self, url: str, *, json: dict | None = None, **_: Any) -> FakeResp:
        return self._record("POST", url, json or {})


class FakeHTTPX:
    """Controller returned by the :func:`fake_httpx` fixture.

    ``calls`` accumulates every request; ``respond_with`` swaps in a custom
    responder (default: an empty-payload 200 for everything).
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self._responder: Callable[[str, str, dict], FakeResp] = lambda *_a: FakeResp({})

    def respond_with(self, responder: Callable[[str, str, dict], FakeResp]) -> None:
        self._responder = responder

    def _factory(self, *_a: object, **_k: object) -> FakeHTTPXClient:
        return FakeHTTPXClient(self.calls, lambda m, u, p: self._responder(m, u, p))


@pytest.fixture
def fake_httpx(monkeypatch: pytest.MonkeyPatch) -> FakeHTTPX:
    """Patch ``httpx.AsyncClient`` and ``httpx.Client`` with a recording fake.

    Modules under test do ``import httpx; httpx.AsyncClient(...)``, so patching the
    attribute on the ``httpx`` module covers all of them. Returns the
    :class:`FakeHTTPX` controller — read ``.calls``, script responses via
    ``.respond_with``.
    """
    ctrl = FakeHTTPX()
    monkeypatch.setattr(httpx, "AsyncClient", ctrl._factory)
    monkeypatch.setattr(httpx, "Client", ctrl._factory)
    return ctrl


# ── the generated typed backend client (command plumbing) ─────────────────────


def stub_typed_client(
    monkeypatch: pytest.MonkeyPatch,
    module: Any,
    *,
    api_url: str = "http://localhost:8000",
    room: str | None = None,
) -> None:
    """Neutralize a command module's backend plumbing for a unit test.

    Patches, on ``module``:

    * ``MyceliumConfig.load`` → a config pointing at ``api_url`` (no config file);
    * ``_typed_client`` → a no-op context manager yielding a dummy client;
    * ``_resolve_room`` → ``room`` (when the module has one and ``room`` is given).

    After this the test only scripts the one generated API ``.sync`` it exercises
    (``monkeypatch.setattr("mycelium_backend_client.api.<...>.sync", fake)``), the
    same shape the pre-existing ``test_room_messages`` used.
    """
    fake_config = SimpleNamespace(server=SimpleNamespace(api_url=api_url))
    if hasattr(module, "MyceliumConfig"):
        monkeypatch.setattr(module.MyceliumConfig, "load", classmethod(lambda _cls: fake_config))
    if hasattr(module, "_typed_client"):
        fake_cm = MagicMock()
        fake_cm.__enter__.return_value = Mock(name="client")
        fake_cm.__exit__.return_value = None
        monkeypatch.setattr(module, "_typed_client", lambda _c: fake_cm)
    if room is not None and hasattr(module, "_resolve_room"):
        monkeypatch.setattr(module, "_resolve_room", lambda *_a, **_k: room)


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """A helper that stubs a command module's typed-client plumbing.

    Usage: ``backend(room_cmd, room="demo")`` then patch the specific API
    ``.sync``. Thin wrapper over :func:`stub_typed_client` bound to this test's
    ``monkeypatch``.
    """

    def _install(module: Any, *, api_url: str = "http://localhost:8000", room: str | None = None):
        stub_typed_client(monkeypatch, module, api_url=api_url, room=room)

    return _install


# ── environment isolation ─────────────────────────────────────────────────────


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``Path.home()`` (and thus ``get_mycelium_dir``) at a temp dir.

    ``filesystem.get_mycelium_dir`` resolves to ``~/.mycelium``; setting ``HOME``
    keeps a test from ever touching the developer's real data dir. Returns the
    temp home so a test can seed ``.mycelium`` under it.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path
