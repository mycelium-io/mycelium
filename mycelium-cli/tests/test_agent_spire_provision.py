# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""`agent create`/`rm` resolve the SPIRE tier from config, not just env (#588).

Regression for a bug the live bring-up caught: the runtime resolves the identity
mode from ``MYCELIUM_SLIM_IDENTITY`` (env-only), but the "one switch" writes the
tier to ``config.slim.identity``. A fresh CLI process doesn't inherit that env, so
`agent create` read psk and silently skipped registration even with spire on. The
provision/revoke helpers must key off the passed-in (config) mode.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mycelium.commands import agent as agent_cmd


def test_provision_threads_config_mode_not_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Env deliberately unset — the mode must come from the config arg.
    monkeypatch.delenv("MYCELIUM_SLIM_IDENTITY", raising=False)
    seen: dict = {}

    from mycelium.slim import identity as slim_identity

    def fake_provision(handle, mode=None, data_dir=None):
        seen["mode"] = mode
        return {
            "mode": slim_identity.MODE_SPIRE,
            "handle": handle,
            "spiffe_id": "spiffe://x/agent/a",
        }

    registered: list[str] = []
    monkeypatch.setattr(slim_identity, "provision_channel_identity", fake_provision)
    monkeypatch.setattr(agent_cmd, "_register_spire_workload", lambda h, r: registered.append(h))

    agent_cmd._provision_channel_identity(SimpleNamespace(handle="alice"), "spire")

    assert seen["mode"] == "spire"  # config value flowed through, not env
    assert registered == ["alice"]  # spire branch fired


def test_revoke_gates_on_config_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MYCELIUM_SLIM_IDENTITY", raising=False)
    calls: list[str] = []
    from mycelium import spire_registry

    monkeypatch.setattr(
        spire_registry,
        "revoke_workload",
        lambda h: calls.append(h) or SimpleNamespace(ok=True, message="revoked", entry_ids=["e1"]),
    )

    # psk / signerjwt: no SPIRE entry exists — must not shell out.
    agent_cmd._revoke_spire_workload("alice", "psk")
    agent_cmd._revoke_spire_workload("alice", "signerjwt")
    assert calls == []

    # spire: revoke fires even with the env unset.
    agent_cmd._revoke_spire_workload("alice", "spire")
    assert calls == ["alice"]
