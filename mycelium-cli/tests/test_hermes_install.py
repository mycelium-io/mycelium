# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Install/uninstall tests against a temp ``$HERMES_HOME``.

The hermes install facet stages a plugin tree into ``~/.hermes/plugins/
mycelium/`` and patches ``~/.hermes/config.yaml``. Both surfaces honour
the ``HERMES_HOME`` env var, so we redirect it to a pytest ``tmp_path``
and assert the staged tree, the patched YAML, and idempotency end to end
without touching the developer's real hermes install.

Subprocess calls (``hermes gateway restart``) are monkey-patched into a
no-op so the tests don't need hermes on PATH.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from mycelium.integrations.hermes import HermesIntegration
from mycelium.integrations.hermes.install import (
    _disable_plugin,
    _enable_plugin,
    _ensure_platform_block,
    _hermes_config_yaml,
    _hermes_home,
    _hermes_plugin_dst,
    _install_hermes,
    _uninstall_hermes,
    _write_config_yaml,
)
from mycelium.protocol import AgentManifest

# ── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolated_hermes_home(tmp_path, monkeypatch):
    """Redirect ``HERMES_HOME`` to a fresh temp dir and stub out gateway restarts."""
    home = tmp_path / "hermes-home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    # ``hermes gateway restart`` is the only subprocess the install code
    # invokes — stub it to a success no-op so the tests don't depend on a
    # ``hermes`` binary being present in CI.
    # Two re-binding sites: ``install`` defines the function but
    # ``dispatch`` did ``from ... import _restart_gateway`` at module load,
    # so the dispatch namespace holds a separate reference. Patch both.
    monkeypatch.setattr(
        "mycelium.integrations.hermes.install._restart_gateway",
        lambda profile=None: None,
    )
    monkeypatch.setattr(
        "mycelium.integrations.hermes.dispatch._restart_gateway",
        lambda profile=None: None,
    )
    monkeypatch.setattr(
        "mycelium.integrations.hermes.install._check_hermes_binary",
        lambda: None,
    )
    return home


@pytest.fixture
def fake_mycelium_config():
    """Minimal stand-in for :class:`MyceliumConfig` — the installer only
    reads ``config.server.api_url``."""

    class _Server:
        api_url = "http://localhost:8000/"

    class _Cfg:
        server = _Server()

    return _Cfg()


# ── pure config helpers ────────────────────────────────────────────────────


def test_enable_plugin_appends_or_creates() -> None:
    data: dict[str, Any] = {}
    assert _enable_plugin(data) is True
    assert data["plugins"]["enabled"] == ["mycelium"]

    # Idempotent — no second append, no spurious change.
    assert _enable_plugin(data) is False
    assert data["plugins"]["enabled"] == ["mycelium"]

    # Existing entries are preserved (don't clobber other plugins).
    data = {"plugins": {"enabled": ["foo", "bar"]}}
    assert _enable_plugin(data) is True
    assert data["plugins"]["enabled"] == ["foo", "bar", "mycelium"]


def test_disable_plugin_removes_only_mycelium() -> None:
    data = {"plugins": {"enabled": ["foo", "mycelium", "bar"]}}
    assert _disable_plugin(data) is True
    assert data["plugins"]["enabled"] == ["foo", "bar"]
    # Idempotent — second pass is a no-op.
    assert _disable_plugin(data) is False


def test_ensure_platform_block_idempotent() -> None:
    data: dict[str, Any] = {}
    assert _ensure_platform_block(data, backend_url="http://h:8000", api_token=None) is True
    block = data["platforms"]["mycelium-room"]
    assert block["enabled"] is True
    assert block["extra"]["backend_url"] == "http://h:8000"
    assert block["extra"]["rooms"] == []
    assert block["extra"]["require_mention"] is True

    # Same backend_url → no change.
    assert _ensure_platform_block(data, backend_url="http://h:8000", api_token=None) is False

    # Different backend_url → flagged as change, ``rooms`` preserved.
    block["extra"]["rooms"] = [{"room": "demo", "agents": ["alice"]}]
    assert _ensure_platform_block(data, backend_url="http://other:8000", api_token=None) is True
    assert data["platforms"]["mycelium-room"]["extra"]["backend_url"] == "http://other:8000"
    assert data["platforms"]["mycelium-room"]["extra"]["rooms"] == [
        {"room": "demo", "agents": ["alice"]}
    ]


def test_ensure_platform_block_with_api_token() -> None:
    """``api_token`` is opt-in: only persisted when explicitly provided."""
    data: dict[str, Any] = {}
    _ensure_platform_block(data, backend_url="http://h:8000", api_token="secret")
    assert data["platforms"]["mycelium-room"]["extra"]["api_token"] == "secret"

    data = {}
    _ensure_platform_block(data, backend_url="http://h:8000", api_token=None)
    assert "api_token" not in data["platforms"]["mycelium-room"]["extra"]


# ── full install / uninstall round-trip ────────────────────────────────────


def _read_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def test_install_stages_plugin_and_patches_config(
    _isolated_hermes_home, fake_mycelium_config
) -> None:
    _install_hermes(
        verbose=False,
        profile=None,
        config=fake_mycelium_config,
        reinstall=False,
    )

    plugin_dst = _hermes_plugin_dst(None)
    assert plugin_dst.exists(), "plugin tree was not staged"
    assert (plugin_dst / "plugin.yaml").exists()
    assert (plugin_dst / "adapter.py").exists()
    assert (plugin_dst / "route.py").exists()
    assert (plugin_dst / "skills" / "mycelium" / "SKILL.md").exists()

    cfg_path = _hermes_config_yaml(None)
    assert cfg_path.exists(), "config.yaml was not written"
    data = _read_yaml(cfg_path)
    assert "mycelium" in data["plugins"]["enabled"]
    platform_block = data["platforms"]["mycelium-room"]
    assert platform_block["enabled"] is True
    assert platform_block["extra"]["backend_url"] == "http://localhost:8000"
    assert platform_block["extra"]["rooms"] == []


def test_install_is_idempotent(_isolated_hermes_home, fake_mycelium_config) -> None:
    """Re-running install on a clean tree is a no-op — same content, no
    duplicate plugin entries, ``rooms`` not clobbered."""
    _install_hermes(verbose=False, profile=None, config=fake_mycelium_config, reinstall=False)
    cfg_path = _hermes_config_yaml(None)
    data = _read_yaml(cfg_path)
    data["platforms"]["mycelium-room"]["extra"]["rooms"] = [{"room": "demo", "agents": ["alice"]}]
    _write_config_yaml(data)

    _install_hermes(verbose=False, profile=None, config=fake_mycelium_config, reinstall=False)
    data2 = _read_yaml(cfg_path)
    assert data2["plugins"]["enabled"].count("mycelium") == 1
    # Existing room fan-out survives a re-install — critical for the
    # ``adapter add hermes --reinstall`` path.
    assert data2["platforms"]["mycelium-room"]["extra"]["rooms"] == [
        {"room": "demo", "agents": ["alice"]}
    ]


def test_uninstall_removes_tree_and_disables(_isolated_hermes_home, fake_mycelium_config) -> None:
    _install_hermes(verbose=False, profile=None, config=fake_mycelium_config, reinstall=False)
    _uninstall_hermes({}, profile=None)
    assert not _hermes_plugin_dst(None).exists()
    data = _read_yaml(_hermes_config_yaml(None))
    assert "mycelium" not in data["plugins"]["enabled"]
    # We disable the platform block but DO NOT delete it, so a subsequent
    # re-install doesn't lose any per-room fan-out a user had configured.
    assert data["platforms"]["mycelium-room"]["enabled"] is False


# ── dispatch facet ─────────────────────────────────────────────────────────


def _build_manifest(handle: str = "alice") -> AgentManifest:
    return AgentManifest(
        handle=handle,
        adapter="hermes",
        description="",
        budget_usd_per_month=5.0,
        allow_from=[],
    )


def test_register_appends_room_entry(_isolated_hermes_home, fake_mycelium_config) -> None:
    _install_hermes(verbose=False, profile=None, config=fake_mycelium_config, reinstall=False)
    integ = HermesIntegration()
    from mycelium.integrations.base import AddOptions

    integ.register(
        manifest=_build_manifest("alice"),
        config=fake_mycelium_config,
        opts=AddOptions(room="demo"),
    )
    data = _read_yaml(_hermes_config_yaml(None))
    rooms = data["platforms"]["mycelium-room"]["extra"]["rooms"]
    assert rooms == [{"room": "demo", "agents": ["alice"]}]

    integ.register(
        manifest=_build_manifest("bob"),
        config=fake_mycelium_config,
        opts=AddOptions(room="demo"),
    )
    data = _read_yaml(_hermes_config_yaml(None))
    rooms = data["platforms"]["mycelium-room"]["extra"]["rooms"]
    assert rooms == [{"room": "demo", "agents": ["alice", "bob"]}]

    # Same handle twice → no duplicate entry.
    integ.register(
        manifest=_build_manifest("alice"),
        config=fake_mycelium_config,
        opts=AddOptions(room="demo"),
    )
    data = _read_yaml(_hermes_config_yaml(None))
    assert data["platforms"]["mycelium-room"]["extra"]["rooms"][0]["agents"] == [
        "alice",
        "bob",
    ]


def test_destroy_removes_handle_and_prunes_empty_room(
    _isolated_hermes_home, fake_mycelium_config
) -> None:
    _install_hermes(verbose=False, profile=None, config=fake_mycelium_config, reinstall=False)
    integ = HermesIntegration()
    from mycelium.integrations.base import AddOptions

    for handle in ("alice", "bob"):
        integ.register(
            manifest=_build_manifest(handle),
            config=fake_mycelium_config,
            opts=AddOptions(room="demo"),
        )

    integ.destroy(
        manifest=_build_manifest("alice"),
        config=fake_mycelium_config,
        room="demo",
        full=False,
    )
    data = _read_yaml(_hermes_config_yaml(None))
    rooms = data["platforms"]["mycelium-room"]["extra"]["rooms"]
    assert rooms == [{"room": "demo", "agents": ["bob"]}]

    integ.destroy(
        manifest=_build_manifest("bob"),
        config=fake_mycelium_config,
        room="demo",
        full=False,
    )
    data = _read_yaml(_hermes_config_yaml(None))
    # The now-empty room entry is dropped, matching openclaw behaviour.
    assert data["platforms"]["mycelium-room"]["extra"]["rooms"] == []


def test_build_manifest_carries_profile() -> None:
    """The hermes_profile passed to the integration constructor lands on
    the manifest so a later ``destroy`` can target the right hermes home."""
    integ = HermesIntegration(hermes_profile="work")
    from mycelium.integrations.base import AddOptions

    manifest = integ.build_manifest(
        handle="alice",
        opts=AddOptions(room="demo"),
        description="",
        budget=5.0,
        allow_from=[],
    )
    assert manifest.adapter == "hermes"
    assert manifest.hermes_profile == "work"


def test_hermes_home_respects_env(monkeypatch, tmp_path) -> None:
    """``$HERMES_HOME`` always wins — required so tests + containers can
    redirect without setting a profile."""
    target = tmp_path / "alt"
    monkeypatch.setenv("HERMES_HOME", str(target))
    assert _hermes_home() == target
    assert _hermes_home("work") == target  # env still wins over profile


def test_status_check_reports_missing_install(_isolated_hermes_home) -> None:
    """A status_check with no install done at all reports plugin AND
    config as missing, but the function itself does not raise."""
    integ = HermesIntegration()
    result = integ.status_check(name="hermes", info={"api_url": "http://h:8000"})
    assert result["ok"] is False
    joined = "\n".join(result["details"])
    assert "plugin:mycelium" in joined
    assert "config:plugins.enabled" in joined
