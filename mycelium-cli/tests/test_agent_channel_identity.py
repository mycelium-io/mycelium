# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""`agent create`/`rm` resolve the identity tier from config, not just env.

The runtime resolves the identity mode from ``MYCELIUM_SLIM_IDENTITY`` (env-only),
but the "one switch" writes the tier to ``config.slim.identity``. A fresh CLI
process doesn't inherit that env, so the provision/revoke helpers must key off the
passed-in (config) mode.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from mycelium.commands import agent as agent_cmd
from mycelium.protocol import AgentManifest


def test_provision_threads_config_mode_not_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Env deliberately unset — the mode must come from the config arg.
    monkeypatch.delenv("MYCELIUM_SLIM_IDENTITY", raising=False)
    seen: dict = {}

    from mycelium.slim import identity as slim_identity

    def fake_provision(handle, mode=None, data_dir=None):
        seen["mode"] = mode
        return {
            "mode": slim_identity.MODE_SIGNERJWT,
            "handle": handle,
            "provisioned": True,
            "kid": handle,
            "key_path": "/tmp/key.pem",
            "roster_path": "/tmp/roster.json",
        }

    monkeypatch.setattr(slim_identity, "provision_channel_identity", fake_provision)

    # Stub manifest — the helper only reads ``.handle``; cast satisfies the type gate.
    manifest = cast("AgentManifest", SimpleNamespace(handle="alice"))
    agent_cmd._provision_channel_identity(manifest, "signerjwt")

    assert seen["mode"] == "signerjwt"  # config value flowed through, not env


def test_revoke_threads_config_mode_not_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MYCELIUM_SLIM_IDENTITY", raising=False)
    seen: dict = {}

    from mycelium.slim import identity as slim_identity

    def fake_revoke(handle, mode=None, data_dir=None):
        seen["mode"] = mode
        return {"mode": mode, "handle": handle, "revoked": True, "removed": ["/tmp/key.pem"]}

    monkeypatch.setattr(slim_identity, "revoke_channel_identity", fake_revoke)

    agent_cmd._revoke_channel_identity("alice", "signerjwt")
    assert seen["mode"] == "signerjwt"


def test_psk_provision_stays_silent(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """Off by default: the try-it path never sees identity machinery (#567)."""
    monkeypatch.delenv("MYCELIUM_SLIM_IDENTITY", raising=False)

    from mycelium.slim import identity as slim_identity

    monkeypatch.setattr(
        slim_identity,
        "provision_channel_identity",
        lambda handle, mode=None, data_dir=None: {
            "mode": slim_identity.MODE_PSK,
            "handle": handle,
            "provisioned": False,
        },
    )

    manifest = cast("AgentManifest", SimpleNamespace(handle="alice"))
    agent_cmd._provision_channel_identity(manifest, "psk")
    assert capsys.readouterr().out == ""
