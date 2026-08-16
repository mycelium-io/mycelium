# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Per-agent credentials — the store, the mint, and the seam they attach at.

Four slices, matching what can quietly go wrong when an agent carries its own
identity:

* **the store** — owner-only, round-trips, and reads as "no credential" rather
  than raising when it's damaged;
* **resolution** — env beats store beats config defaults, a shared issuer alone
  is not a credential, and an unknown handle resolves to nothing;
* **the mint** — ``client_credentials`` against the issuer, cached until it is
  near expiry, re-minted after, and never reused across a changed client;
* **the seam** — a client built for an agent carries *that agent's* token even
  when a human session is cached, and carries nothing when neither exists.

No issuer and no backend run here: ``oidc`` is stubbed at the module the code
under test calls into.
"""

from __future__ import annotations

import json
import stat
import time
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from mycelium import agent_credentials, oidc, tokens
from mycelium.cli import app
from mycelium.config import MyceliumConfig
from mycelium.oidc import OidcError, ProviderMetadata, TokenResponse
from mycelium.tokens import StoredToken, save_token

runner = CliRunner()

_META = ProviderMetadata(
    issuer="https://idp.test/agents",
    token_endpoint="https://idp.test/agents/token",
)

_ENV_VARS = (
    agent_credentials.CREDENTIAL_STORE_ENV,
    agent_credentials.AGENT_HANDLE_ENV,
    agent_credentials.STATIC_TOKEN_ENV,
    agent_credentials.CLIENT_ID_ENV,
    agent_credentials.CLIENT_SECRET_ENV,
)


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every test off the developer's real ``~/.mycelium`` and caches."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(tokens.TOKEN_FILE_ENV, str(tmp_path / "token.json"))
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv(agent_credentials.CREDENTIAL_STORE_ENV, str(tmp_path / "agent-creds.json"))
    # The "say it once" latch is process-wide; a warning from one test must not
    # silence the next.
    agent_credentials._warned.clear()


def _config(issuer: str | None = _META.issuer, **kwargs: Any) -> MyceliumConfig:
    config = MyceliumConfig()
    config.agent_auth.issuer = issuer
    for key, value in kwargs.items():
        setattr(config.agent_auth, key, value)
    return config


class _Mint:
    """A stand-in issuer that records what it was asked for."""

    def __init__(self, *, expires_in: float | None = 3600.0) -> None:
        self.calls: list[dict[str, Any]] = []
        self.expires_in = expires_in

    def discover(self, issuer: str, **_: Any) -> ProviderMetadata:
        return ProviderMetadata(issuer=issuer, token_endpoint=f"{issuer}/token")

    def grant(
        self,
        token_endpoint: str,
        client_id: str,
        client_secret: str | None,
        *,
        scope: str | None = None,
        audience: str | None = None,
    ) -> TokenResponse:
        self.calls.append(
            {
                "token_endpoint": token_endpoint,
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": scope,
                "audience": audience,
            }
        )
        return TokenResponse(
            access_token=f"token-for-{client_id}-{len(self.calls)}",
            expires_at=None if self.expires_in is None else time.time() + self.expires_in,
            scope=scope,
        )


@pytest.fixture
def mint(monkeypatch: pytest.MonkeyPatch) -> _Mint:
    stub = _Mint()
    monkeypatch.setattr(oidc, "discover", stub.discover)
    monkeypatch.setattr(oidc, "client_credentials_grant", stub.grant)
    return stub


# ── the store ────────────────────────────────────────────────────────────────


def test_store_is_owner_only_and_round_trips() -> None:
    path = agent_credentials.save_credential("release-agent", client_secret="s3cret")

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    stored = agent_credentials.list_credentials()["release-agent"]
    assert stored.client_id == "release-agent"
    assert stored.client_secret == "s3cret"


def test_credential_defaults_its_client_id_to_the_handle() -> None:
    agent_credentials.save_credential("@Release-Agent", client_secret="s3cret")

    stored = agent_credentials.list_credentials()
    assert "release-agent" in stored
    assert stored["release-agent"].client_id == "release-agent"


def test_damaged_store_reads_as_no_credentials() -> None:
    agent_credentials.store_path().write_text("{not json", encoding="utf-8")

    assert agent_credentials.list_credentials() == {}
    assert agent_credentials.resolve(_config(), "release-agent") is None


def test_removing_a_credential_reports_whether_there_was_one() -> None:
    agent_credentials.save_credential("release-agent", client_secret="s3cret")

    assert agent_credentials.remove_credential("release-agent") is True
    assert agent_credentials.remove_credential("release-agent") is False


# ── resolution ───────────────────────────────────────────────────────────────


def test_no_credential_resolves_to_none() -> None:
    """The default: nothing configured, so nothing is sent."""
    assert agent_credentials.resolve(_config(), "release-agent") is None


def test_a_shared_issuer_alone_is_not_a_credential() -> None:
    """Configuring an issuer must not turn every handle into a token request."""
    assert agent_credentials.resolve(_config(issuer="https://idp.test/agents"), "nobody") is None


def test_stored_credential_inherits_the_configured_issuer() -> None:
    agent_credentials.save_credential("release-agent", client_secret="s3cret")

    resolved = agent_credentials.resolve(_config(audience="mycelium"), "release-agent")

    assert resolved is not None
    assert resolved.issuer == _META.issuer
    assert resolved.audience == "mycelium"


def test_per_agent_issuer_overrides_the_shared_one() -> None:
    agent_credentials.save_credential(
        "release-agent", client_secret="s3cret", issuer="https://other.test/realm"
    )

    resolved = agent_credentials.resolve(_config(), "release-agent")

    assert resolved is not None
    assert resolved.issuer == "https://other.test/realm"


def test_environment_credential_needs_no_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """A container running one agent has no config file to write into."""
    monkeypatch.setenv(agent_credentials.CLIENT_ID_ENV, "svc-release")
    monkeypatch.setenv(agent_credentials.CLIENT_SECRET_ENV, "from-env")

    resolved = agent_credentials.resolve(_config(), "release-agent")

    assert resolved is not None
    assert resolved.client_id == "svc-release"
    assert resolved.client_secret == "from-env"


def test_session_qualifier_resolves_to_the_same_agent() -> None:
    """``alpha#a8f3`` is one agent in two sessions, not two identities."""
    agent_credentials.save_credential("alpha", client_secret="s3cret")

    resolved = agent_credentials.resolve(_config(), "alpha#a8f3")

    assert resolved is not None
    assert resolved.handle == "alpha"


def test_ambient_handle_names_the_agent_when_the_caller_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent_credentials.save_credential("release-agent", client_secret="s3cret")
    monkeypatch.setenv(agent_credentials.AGENT_HANDLE_ENV, "release-agent")

    assert agent_credentials.resolve(_config(), None) is not None


# ── the mint ─────────────────────────────────────────────────────────────────


def test_token_is_minted_with_client_credentials(mint: _Mint) -> None:
    agent_credentials.save_credential("release-agent", client_secret="s3cret")
    config = _config(scopes="openid", audience="mycelium")

    token = agent_credentials.access_token(config, "release-agent")

    assert token == "token-for-release-agent-1"
    assert mint.calls == [
        {
            "token_endpoint": f"{_META.issuer}/token",
            "client_id": "release-agent",
            "client_secret": "s3cret",
            "scope": "openid",
            "audience": "mycelium",
        }
    ]


def test_a_live_token_is_reused_rather_than_reminted(mint: _Mint) -> None:
    agent_credentials.save_credential("release-agent", client_secret="s3cret")
    config = _config()

    first = agent_credentials.access_token(config, "release-agent")
    second = agent_credentials.access_token(config, "release-agent")

    assert first == second
    assert len(mint.calls) == 1


def test_an_expiring_token_is_reminted(mint: _Mint) -> None:
    """Expiry is judged with leeway, so a token can't die in flight."""
    agent_credentials.save_credential("release-agent", client_secret="s3cret")
    config = _config()
    save_token(
        StoredToken(
            access_token="nearly-dead",
            issuer=_META.issuer,
            client_id="release-agent",
            expires_at=time.time() + 5.0,
        ),
        agent_credentials.token_cache_path("release-agent"),
    )

    assert agent_credentials.access_token(config, "release-agent") == "token-for-release-agent-1"


def test_a_token_minted_for_a_different_client_is_not_reused(mint: _Mint) -> None:
    """Re-pointing a credential must not keep presenting the old client's token."""
    agent_credentials.save_credential("release-agent", client_secret="s3cret")
    save_token(
        StoredToken(
            access_token="old-client-token",
            issuer=_META.issuer,
            client_id="some-other-client",
            expires_at=time.time() + 3600.0,
        ),
        agent_credentials.token_cache_path("release-agent"),
    )

    assert agent_credentials.access_token(_config(), "release-agent") == "token-for-release-agent-1"


def test_replacing_a_credential_drops_the_token_it_minted(mint: _Mint) -> None:
    agent_credentials.save_credential("release-agent", client_secret="s3cret")
    agent_credentials.access_token(_config(), "release-agent")

    agent_credentials.save_credential("release-agent", client_secret="rotated")
    agent_credentials.access_token(_config(), "release-agent")

    assert [c["client_secret"] for c in mint.calls] == ["s3cret", "rotated"]


def test_a_static_token_is_used_as_is(mint: _Mint, monkeypatch: pytest.MonkeyPatch) -> None:
    """The SPIRE / CI seam: a credential this CLI didn't obtain and doesn't renew."""
    monkeypatch.setenv(agent_credentials.STATIC_TOKEN_ENV, "svid-from-sidecar")

    assert agent_credentials.access_token(_config(), "release-agent") == "svid-from-sidecar"
    assert mint.calls == []


def test_a_failed_mint_degrades_to_no_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """A dead issuer must not fabricate a failure the hub never reported."""

    def _boom(*_: Any, **__: Any) -> ProviderMetadata:
        raise OidcError("issuer unreachable")

    monkeypatch.setattr(oidc, "discover", _boom)
    agent_credentials.save_credential("release-agent", client_secret="s3cret")

    assert agent_credentials.access_token(_config(), "release-agent") is None


def test_a_credential_with_no_issuer_mints_nothing(mint: _Mint) -> None:
    agent_credentials.save_credential("release-agent", client_secret="s3cret")

    assert agent_credentials.access_token(_config(issuer=None), "release-agent") is None
    assert mint.calls == []


def test_the_minted_token_cache_is_owner_only(mint: _Mint) -> None:
    agent_credentials.save_credential("release-agent", client_secret="s3cret")
    agent_credentials.access_token(_config(), "release-agent")

    path = agent_credentials.token_cache_path("release-agent")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


# ── the seam ─────────────────────────────────────────────────────────────────


def test_a_client_for_an_agent_carries_that_agents_token(mint: _Mint) -> None:
    from mycelium import client as client_mod

    agent_credentials.save_credential("release-agent", client_secret="s3cret")

    headers = client_mod.auth_headers(_config(), handle="release-agent")

    assert headers == {"Authorization": "Bearer token-for-release-agent-1"}


def test_an_agents_credential_wins_over_a_human_session(mint: _Mint) -> None:
    """A resident agent driven from a logged-in shell still writes as itself."""
    from mycelium import client as client_mod

    save_token(StoredToken(access_token="human-token", issuer="https://idp.test", client_id="cli"))
    agent_credentials.save_credential("release-agent", client_secret="s3cret")

    headers = client_mod.auth_headers(_config(), handle="release-agent")

    assert headers == {"Authorization": "Bearer token-for-release-agent-1"}


def test_an_agent_without_a_credential_falls_back_to_the_human_session(mint: _Mint) -> None:
    from mycelium import client as client_mod

    save_token(StoredToken(access_token="human-token", issuer="https://idp.test", client_id="cli"))

    headers = client_mod.auth_headers(_config(), handle="release-agent")

    assert headers == {"Authorization": "Bearer human-token"}


def test_no_credential_and_no_session_sends_nothing(mint: _Mint) -> None:
    """The off-by-default promise: identity changes nothing until it's configured."""
    from mycelium import client as client_mod

    assert client_mod.auth_headers(_config(), handle="release-agent") == {}


# ── the commands ─────────────────────────────────────────────────────────────


def test_credential_set_stores_and_show_never_prints_the_secret() -> None:
    result = runner.invoke(
        app,
        ["agent", "credential", "set", "release-agent", "--secret-stdin"],
        input="s3cret",
    )
    assert result.exit_code == 0, result.output
    assert "s3cret" not in result.output

    shown = runner.invoke(app, ["agent", "credential", "show", "release-agent"])
    assert shown.exit_code == 0, shown.output
    assert "s3cret" not in shown.output
    assert "release-agent" in shown.output


def test_credential_show_reports_an_unconfigured_agent() -> None:
    result = runner.invoke(app, ["agent", "credential", "show", "release-agent"])

    assert result.exit_code == 0, result.output
    assert "no credential" in result.output


def test_credential_ls_lists_stored_agents() -> None:
    agent_credentials.save_credential("release-agent", client_secret="s3cret")
    agent_credentials.save_credential("docs-agent", client_secret="other")

    result = runner.invoke(app, ["agent", "credential", "ls"])

    assert result.exit_code == 0, result.output
    assert "release-agent" in result.output
    assert "docs-agent" in result.output
    assert "s3cret" not in result.output


def test_credential_rm_forgets_the_credential() -> None:
    agent_credentials.save_credential("release-agent", client_secret="s3cret")

    result = runner.invoke(app, ["--json", "agent", "credential", "rm", "release-agent"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["removed"] is True
    assert agent_credentials.list_credentials() == {}
