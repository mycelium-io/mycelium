# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""CLI-driven SPIRE registration/revocation.

`mycelium agent create`/`rm` register/revoke a member's SVID entry against the
appliance SPIRE server, so a user types zero `spire-server entry create` commands.
These tests pin the command construction and the idempotency / best-effort
contracts against a faked `docker compose exec`, so no live SPIRE is needed.
"""

from __future__ import annotations

import subprocess

import pytest

from mycelium import spire_registry

_TD = "mycelium.dev"


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture(autouse=True)
def _fixed_trust_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spire_registry, "resolve_spire_trust_domain", lambda: _TD)


def test_register_builds_entry_create_with_backend_uid(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_exec(args, *, timeout=20):
        calls.append(args)
        if args[1] == "entry" and args[2] == "show":
            return _completed(0, stdout="")  # no existing entry
        if args[1] == "entry" and args[2] == "create":
            return _completed(0, stdout="Entry ID: abc-123\n")
        return _completed(1)

    monkeypatch.setattr(spire_registry, "_compose_exec", fake_exec)
    monkeypatch.setattr(spire_registry, "_backend_uid", lambda: "1001")

    result = spire_registry.register_workload("alice")

    assert result.ok
    assert result.spiffe_id == f"spiffe://{_TD}/agent/alice"
    create = next(c for c in calls if c[1:3] == ["entry", "create"])
    assert "-parentID" in create
    assert f"spiffe://{_TD}/agent-node" in create
    assert "-spiffeID" in create
    assert f"spiffe://{_TD}/agent/alice" in create
    assert "unix:uid:1001" in create


def test_register_idempotent_when_entry_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_exec(args, *, timeout=20):
        if args[1:3] == ["entry", "show"]:
            return _completed(0, stdout="Entry ID : existing-1\n")
        raise AssertionError("must not create when an entry already exists")

    monkeypatch.setattr(spire_registry, "_compose_exec", fake_exec)
    monkeypatch.setattr(spire_registry, "_backend_uid", lambda: "1001")

    result = spire_registry.register_workload("alice")
    assert result.ok
    assert result.entry_ids == ["existing-1"]
    assert "already registered" in result.message


def test_register_fails_soft_without_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spire_registry, "_compose_exec", lambda args, **k: _completed(0, ""))
    monkeypatch.setattr(spire_registry, "_backend_uid", lambda: None)

    result = spire_registry.register_workload("alice")
    assert not result.ok
    assert "backend" in result.message.lower()


def test_revoke_deletes_all_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    deleted: list[str] = []

    def fake_exec(args, *, timeout=20):
        if args[1:3] == ["entry", "show"]:
            return _completed(0, stdout="Entry ID: e1\nEntry ID: e2\n")
        if args[1:3] == ["entry", "delete"]:
            deleted.append(args[args.index("-entryID") + 1])
            return _completed(0)
        return _completed(1)

    monkeypatch.setattr(spire_registry, "_compose_exec", fake_exec)

    result = spire_registry.revoke_workload("alice")
    assert result.ok
    assert deleted == ["e1", "e2"]


def test_revoke_noop_when_no_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spire_registry, "_compose_exec", lambda args, **k: _completed(0, stdout=""))
    result = spire_registry.revoke_workload("alice")
    assert result.ok
    assert "no entry" in result.message


def test_registered_handles_parses_spiffe_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    out = f"SPIFFE ID : spiffe://{_TD}/agent/alice\nSPIFFE ID : spiffe://{_TD}/agent/bob\n"
    monkeypatch.setattr(
        spire_registry, "_compose_exec", lambda args, **k: _completed(0, stdout=out)
    )
    assert spire_registry.registered_handles() == ["alice", "bob"]


def test_registered_handles_none_when_server_down(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spire_registry, "_compose_exec", lambda args, **k: _completed(1))
    assert spire_registry.registered_handles() is None


def test_mint_join_token_parses_and_targets_agent_node(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_exec(args, *, timeout=20):
        calls.append(args)
        return _completed(0, stdout="Token: abc-123-token\n")

    monkeypatch.setattr(spire_registry, "_compose_exec", fake_exec)
    token = spire_registry.mint_join_token()
    assert token == "abc-123-token"
    generate = calls[0]
    assert generate[1:3] == ["token", "generate"]
    assert f"spiffe://{_TD}/agent-node" in generate


def test_mint_join_token_none_when_unparseable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        spire_registry, "_compose_exec", lambda args, **k: _completed(0, stdout="no token here")
    )
    assert spire_registry.mint_join_token() is None
    monkeypatch.setattr(spire_registry, "_compose_exec", lambda args, **k: _completed(1))
    assert spire_registry.mint_join_token() is None


def test_server_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spire_registry, "_compose_exec", lambda args, **k: _completed(0))
    assert spire_registry.server_healthy() is True
    monkeypatch.setattr(spire_registry, "_compose_exec", lambda args, **k: _completed(1))
    assert spire_registry.server_healthy() is False
