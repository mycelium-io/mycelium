# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Tests for the /api/demos proxy to the host-side hub runner.

The proxy is the only backend-side surface; provisioning happens on the runner.
We test the gate (404 when no runner configured), the forwarding contract, and
error passthrough — with httpx stubbed so no real runner is needed.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.routes import demos
from app.routes.demos import router


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


class _FakeResp:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self) -> Any:
        return self._payload


class _FakeClient:
    """Records the last forwarded request and returns a canned response."""

    last: ClassVar[dict[str, Any]] = {}
    status: ClassVar[int] = 200
    payload: ClassVar[Any] = {}
    raise_error: ClassVar[bool] = False

    def __init__(self, *_: Any, **__: Any) -> None:
        pass

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *_: Any) -> bool:
        return False

    async def request(
        self, method: str, url: str, *, json: Any = None, headers: Any = None
    ) -> _FakeResp:
        _FakeClient.last = {"method": method, "url": url, "json": json, "headers": headers}
        if _FakeClient.raise_error:
            raise httpx.ConnectError("refused")
        return _FakeResp(_FakeClient.status, _FakeClient.payload)


@pytest.fixture(autouse=True)
def _stub_httpx(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeClient.last = {}
    _FakeClient.status = 200
    _FakeClient.payload = {}
    _FakeClient.raise_error = False
    monkeypatch.setattr(demos.httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(settings, "HUB_RUNNER_TOKEN", None)


def test_disabled_when_unconfigured(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "HUB_RUNNER_URL", None)
    resp = client.get("/api/demos/scenarios")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "host runner not configured"


def test_scenarios_forwarded(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "HUB_RUNNER_URL", "http://127.0.0.1:8765")
    _FakeClient.payload = {"scenarios": [{"id": "ex07", "topic": "x", "default": True}]}
    resp = client.get("/api/demos/scenarios")
    assert resp.status_code == 200
    assert resp.json()["scenarios"][0]["id"] == "ex07"
    assert _FakeClient.last["method"] == "GET"
    assert _FakeClient.last["url"].endswith("/scenarios")


def test_start_demo_forwarded(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "HUB_RUNNER_URL", "http://127.0.0.1:8765/")
    _FakeClient.payload = {"job_id": "abc", "room": "demo-x", "status": "provisioning"}
    resp = client.post("/api/demos", json={"scenario": "ex07", "adapter": None})
    assert resp.status_code == 200
    assert resp.json()["job_id"] == "abc"
    assert _FakeClient.last["method"] == "POST"
    assert _FakeClient.last["url"].endswith("/demos")
    # None fields are dropped (exclude_none) so the runner applies its defaults.
    assert _FakeClient.last["json"] == {"scenario": "ex07"}


def test_token_attached(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "HUB_RUNNER_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(settings, "HUB_RUNNER_TOKEN", "tok")
    client.get("/api/demos/scenarios")
    assert _FakeClient.last["headers"]["Authorization"] == "Bearer tok"


def test_error_passthrough(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "HUB_RUNNER_URL", "http://127.0.0.1:8765")
    _FakeClient.status = 400
    _FakeClient.payload = {"error": "unknown scenario 'nope'"}
    resp = client.get("/api/demos/badjob")
    assert resp.status_code == 400


def test_runner_unreachable(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "HUB_RUNNER_URL", "http://127.0.0.1:8765")
    _FakeClient.raise_error = True
    resp = client.get("/api/demos/scenarios")
    assert resp.status_code == 502
