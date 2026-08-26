# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""[slim].master_secret: config.toml source of truth → .env render."""

from __future__ import annotations

from mycelium.config import MyceliumConfig
from mycelium.docker_utils import ensure_slim_master_secret, generate_env_file, write_env_file
from mycelium.slim import naming


def _parse_env(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


def test_ensure_generates_when_unset(isolated_home) -> None:
    cfg = MyceliumConfig()
    assert cfg.slim.master_secret is None
    assert ensure_slim_master_secret(cfg) is True
    assert cfg.slim.master_secret
    assert len(cfg.slim.master_secret) >= 32


def test_ensure_imports_from_existing_env(isolated_home) -> None:
    myc = isolated_home / ".mycelium"
    myc.mkdir(parents=True)
    env_path = myc / ".env"
    env_path.write_text("MYCELIUM_SLIM_MASTER_SECRET=imported-secret-value-0123456789ab\n")

    cfg = MyceliumConfig()
    assert ensure_slim_master_secret(cfg, env_path=env_path) is True
    assert cfg.slim.master_secret == "imported-secret-value-0123456789ab"


def test_ensure_noop_when_config_already_set(isolated_home) -> None:
    cfg = MyceliumConfig()
    cfg.slim.master_secret = "already-set-secret-value-0123456789abc"
    assert ensure_slim_master_secret(cfg) is False


def test_generate_env_file_emits_master_secret(isolated_home) -> None:
    cfg = MyceliumConfig()
    cfg.slim.master_secret = "configured-secret-value-0123456789abcd"
    env = _parse_env(generate_env_file(cfg))
    assert env["MYCELIUM_SLIM_MASTER_SECRET"] == cfg.slim.master_secret


def test_write_env_file_persists_generated_secret(isolated_home) -> None:
    myc = isolated_home / ".mycelium"
    myc.mkdir(parents=True)
    config_path = myc / "config.toml"

    cfg = MyceliumConfig()
    cfg.save(config_path)

    env_path, assigned = write_env_file(cfg, env_path=myc / ".env")
    assert assigned is True
    assert env_path.exists()
    env = _parse_env(env_path.read_text(encoding="utf-8"))
    assert env["MYCELIUM_SLIM_MASTER_SECRET"]
    assert env["MYCELIUM_SLIM_MASTER_SECRET"] != naming._DEV_MASTER_SECRET

    reloaded = MyceliumConfig.load(config_path)
    assert reloaded.slim.master_secret == env["MYCELIUM_SLIM_MASTER_SECRET"]


def test_write_env_file_preserves_secret_on_reapply(isolated_home) -> None:
    myc = isolated_home / ".mycelium"
    myc.mkdir(parents=True)
    config_path = myc / "config.toml"

    cfg = MyceliumConfig()
    cfg.slim.master_secret = "stable-secret-value-0123456789abcdef"
    cfg.save(config_path)

    env_path, first_assigned = write_env_file(cfg, env_path=myc / ".env")
    assert first_assigned is False
    first_secret = _parse_env(env_path.read_text(encoding="utf-8"))["MYCELIUM_SLIM_MASTER_SECRET"]

    cfg.llm.model = "anthropic/claude-sonnet-4-6"
    _, second_assigned = write_env_file(cfg, env_path=env_path)
    assert second_assigned is False
    second_secret = _parse_env(env_path.read_text(encoding="utf-8"))["MYCELIUM_SLIM_MASTER_SECRET"]
    assert second_secret == first_secret


def test_spoke_write_env_file_preserves_existing_secret(isolated_home) -> None:
    """write_env_file on a non-localhost hub must NOT blank MYCELIUM_SLIM_MASTER_SECRET.

    Regression for the bug where _is_hub_config skipped ensure_slim_master_secret
    entirely, so a secret in .env was never imported and generate_env_file rendered
    MYCELIUM_SLIM_MASTER_SECRET= (empty). Hubs at LAN IPs / behind reverse proxies
    hit this path.
    """
    myc = isolated_home / ".mycelium"
    myc.mkdir(parents=True)
    config_path = myc / "config.toml"
    env_path = myc / ".env"

    env_path.write_text("MYCELIUM_SLIM_MASTER_SECRET=existing-spoke-secret-value-0123456789ab\n")

    cfg = MyceliumConfig()
    cfg.server.api_url = "http://192.168.1.20:8000"
    cfg.save(config_path)

    _, assigned = write_env_file(cfg, env_path=env_path)
    assert assigned is True  # secret imported from .env
    rendered = _parse_env(env_path.read_text(encoding="utf-8"))
    assert rendered["MYCELIUM_SLIM_MASTER_SECRET"] == "existing-spoke-secret-value-0123456789ab"
    # config.toml also updated
    assert (
        MyceliumConfig.load(config_path).slim.master_secret
        == "existing-spoke-secret-value-0123456789ab"
    )


def test_spoke_write_env_file_does_not_generate_new_secret(isolated_home) -> None:
    """On a spoke with no prior secret, write_env_file must not generate one.

    A spoke has no SLIM node; minting a secret that diverges from the hub's
    shared PSK would silently break channel-key derivation on any hub that later
    reads the same .env.
    """
    myc = isolated_home / ".mycelium"
    myc.mkdir(parents=True)
    config_path = myc / "config.toml"

    cfg = MyceliumConfig()
    cfg.server.api_url = "http://192.168.1.20:8000"
    cfg.save(config_path)

    _, assigned = write_env_file(cfg, env_path=myc / ".env")
    assert assigned is False
    rendered = _parse_env((myc / ".env").read_text(encoding="utf-8"))
    # Line exists but must be empty — not a generated secret
    assert rendered.get("MYCELIUM_SLIM_MASTER_SECRET", "") == ""


def test_ensure_no_generate_when_allow_generate_false(isolated_home) -> None:
    """allow_generate=False must not mint a new secret."""
    cfg = MyceliumConfig()
    assert cfg.slim.master_secret is None
    result = ensure_slim_master_secret(cfg, allow_generate=False)
    assert result is False
    assert cfg.slim.master_secret is None


def test_save_locks_secret_bearing_files_to_owner_only(isolated_home) -> None:
    """config.toml + config.json hold slim.master_secret / llm.api_key, so save()
    must write them 0600, not the default umask (often 0644)."""
    myc = isolated_home / ".mycelium"
    myc.mkdir(parents=True)
    config_path = myc / "config.toml"

    cfg = MyceliumConfig()
    cfg.slim.master_secret = "stable-secret-value-0123456789abcdef"
    cfg.save(config_path)

    assert config_path.stat().st_mode & 0o777 == 0o600
    assert (myc / "config.json").stat().st_mode & 0o777 == 0o600
