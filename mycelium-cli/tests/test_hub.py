# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Tests for the host-side hub runner (``mycelium hub serve``).

The runner is exercised over a real loopback HTTP server on an ephemeral port,
with the demo orchestration (network + gateway) stubbed out — we test the HTTP
contract (routing, auth, validation, job lifecycle), not the live provisioning.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from threading import Thread

import httpx
import pytest

from mycelium.commands import demo, hub


@pytest.fixture
def runner() -> Iterator[str]:
    """Start the runner on an ephemeral port; yield its base URL."""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), hub._Handler)
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_health(runner: str) -> None:
    resp = httpx.get(f"{runner}/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_scenarios(runner: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(demo, "_list_scenarios", lambda: ["ex07_investment_portfolio", "ex01_foo"])
    resp = httpx.get(f"{runner}/scenarios")
    assert resp.status_code == 200
    scenarios = resp.json()["scenarios"]
    ids = {s["id"] for s in scenarios}
    assert ids == {"ex07_investment_portfolio", "ex01_foo"}
    assert any(s["default"] for s in scenarios)  # the configured default is flagged


def test_scenarios_upstream_error(runner: str, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom() -> list[str]:
        raise RuntimeError("403 rate limit")

    monkeypatch.setattr(demo, "_list_scenarios", _boom)
    resp = httpx.get(f"{runner}/scenarios")
    assert resp.status_code == 502


def test_unknown_route(runner: str) -> None:
    assert httpx.get(f"{runner}/nope").status_code == 404


def test_job_not_found(runner: str) -> None:
    assert httpx.get(f"{runner}/demos/deadbeef").status_code == 404


def test_post_unknown_adapter(runner: str) -> None:
    resp = httpx.post(f"{runner}/demos", json={"adapter": "bogus"})
    assert resp.status_code == 400
    assert "adapter" in resp.json()["error"]


def test_post_unknown_scenario(runner: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(demo, "_list_scenarios", lambda: ["ex07_investment_portfolio"])
    resp = httpx.post(f"{runner}/demos", json={"scenario": "nope"})
    assert resp.status_code == 400
    assert "scenario" in resp.json()["error"]


def test_start_demo_lifecycle(runner: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(demo, "_list_scenarios", lambda: ["ex07_investment_portfolio"])
    monkeypatch.setattr(demo, "_resolve_scenario", lambda sid: {"id": sid, "agents": []})
    provisioned: dict[str, object] = {}

    def _fake_provision(scenario, adapter, model, room, auth_from) -> None:  # noqa: ANN001
        provisioned.update(scenario=scenario, adapter=adapter, room=room)

    monkeypatch.setattr(demo, "_provision", _fake_provision)

    resp = httpx.post(f"{runner}/demos", json={"scenario": "ex07_investment_portfolio"})
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "provisioning"
    assert body["room"] == "demo-investment-portfolio"  # mirrors demo._resolve_scenario
    job_id = body["job_id"]

    # The background worker runs the stubbed provision and flips status to ready.
    deadline = time.monotonic() + 5
    status = None
    while time.monotonic() < deadline:
        status = httpx.get(f"{runner}/demos/{job_id}").json()["status"]
        if status == "ready":
            break
        time.sleep(0.05)
    assert status == "ready"
    assert provisioned["adapter"] == "openclaw"  # default adapter


def test_auth_gate(runner: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYCELIUM_HUB_TOKEN", "s3cret")
    assert httpx.get(f"{runner}/health").status_code == 401
    ok = httpx.get(f"{runner}/health", headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 200
