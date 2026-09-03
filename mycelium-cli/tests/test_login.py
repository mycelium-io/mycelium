# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium login`` — the human OIDC session, its cache, and its injection.

Four slices, matching the four things that can quietly go wrong:

* **the cache** — a token file that is owner-only, round-trips, and reads as
  "logged out" rather than raising when it's damaged;
* **the flows** — Authorization Code + PKCE (driven against a real loopback
  listener, with the browser faked) and device code, including the polling
  states RFC 8628 defines;
* **the seam** — every client built by ``mycelium.client`` carries the bearer,
  and carries *nothing* when logged out, which is the off-by-default promise;
* **the identity** — ``login`` points this machine at the token's own handle,
  ``whoami`` / ``iam`` report it when there is one and are untouched when there
  isn't.

No issuer and no backend run here: ``httpx`` is stubbed at the module the code
under test calls into, and the hub's user store, which ``login`` upserts
through, is stubbed at the generated client.
"""

from __future__ import annotations

import base64
import hashlib
import json
import stat
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from mycelium import client as client_mod
from mycelium import oidc, tokens
from mycelium.cli import app
from mycelium.config import MyceliumConfig
from mycelium.oidc import OidcError, ProviderMetadata
from mycelium.tokens import StoredToken, clear_token, load_token, save_token, token_path

runner = CliRunner()

_META = ProviderMetadata(
    issuer="https://idp.test/realms/mycelium",
    token_endpoint="https://idp.test/realms/mycelium/token",
    authorization_endpoint="https://idp.test/realms/mycelium/auth",
    device_authorization_endpoint="https://idp.test/realms/mycelium/device",
)


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every test off the developer's real ``~/.mycelium`` and token cache.

    Also chdirs into ``tmp_path``: ``MyceliumConfig.load()`` additionally
    discovers a project-local ``./.mycelium/config.toml`` by walking up from
    the cwd (independent of ``$HOME``), so a contributor with local scratch
    state in their checkout (e.g. from manual e2e testing) would otherwise leak
    into these "isolated" tests just by running them from within the repo.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(tokens.TOKEN_FILE_ENV, raising=False)
    # The "session expired" notice fires once per process; reset the latch so
    # each test observes its own behavior.
    monkeypatch.setattr(client_mod, "_refresh_warned", False)


USER_GET_SYNC = "mycelium_backend_client.api.users.get_user_api_users_handle_get.sync"
USER_CREATE_SYNC = "mycelium_backend_client.api.users.create_user_api_users_post.sync"


class _Hub:
    """The hub's user store, stubbed — ``login`` upserts a record through it.

    Serves 404 for every read (nobody is registered under this temp home) and
    records what gets written. Flip ``reachable`` to make the hub disappear.
    """

    def __init__(self) -> None:
        self.created: list[str] = []
        self.reachable = True

    def get(self, **_kwargs: Any) -> None:
        from mycelium_backend_client.errors import UnexpectedStatus

        if not self.reachable:
            raise httpx.ConnectError("connection refused")
        raise UnexpectedStatus(404, b'{"detail":"User not found"}')

    def create(self, **kwargs: Any) -> None:
        if not self.reachable:
            raise httpx.ConnectError("connection refused")
        self.created.append(kwargs["body"].handle)


@pytest.fixture(autouse=True)
def hub(monkeypatch: pytest.MonkeyPatch) -> _Hub:
    stub = _Hub()
    monkeypatch.setattr(USER_GET_SYNC, stub.get)
    monkeypatch.setattr(USER_CREATE_SYNC, stub.create)
    return stub


def _flat(text: str) -> str:
    return " ".join(text.split())


def _jwt(claims: dict[str, Any]) -> str:
    """An unsigned-looking JWT — the CLI only ever decodes, never verifies."""

    def seg(data: dict[str, Any]) -> str:
        raw = json.dumps(data).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{seg({'alg': 'RS256'})}.{seg(claims)}.signature"


class _Resp:
    """Minimal ``httpx.Response`` stand-in for the token endpoint."""

    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise AssertionError(f"HTTP {self.status_code}")


def _token(**overrides: Any) -> StoredToken:
    base = StoredToken(
        access_token=_jwt({"sub": "avery", "exp": time.time() + 3600}),
        issuer=_META.issuer,
        client_id="mycelium-cli",
        refresh_token="refresh-1",
        expires_at=time.time() + 3600,
        token_endpoint=_META.token_endpoint,
    )
    return replace(base, **overrides)


# ── the cache ────────────────────────────────────────────────────────────────


def test_token_cache_round_trips_and_is_owner_only() -> None:
    token = _token()
    path = save_token(token)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path == token_path()
    assert load_token() == token


def test_token_cache_honours_the_path_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "elsewhere" / "session.json"
    monkeypatch.setenv(tokens.TOKEN_FILE_ENV, str(target))

    save_token(_token())
    assert target.exists()
    assert load_token() is not None


def test_a_damaged_cache_reads_as_logged_out() -> None:
    save_token(_token())
    token_path().write_text("{not json")

    assert load_token() is None


def test_logged_out_is_the_absence_of_a_file() -> None:
    assert load_token() is None
    assert clear_token() is False

    save_token(_token())
    assert clear_token() is True
    assert load_token() is None


def test_expiry_uses_a_leeway_so_a_token_never_dies_in_flight() -> None:
    assert _token(expires_at=time.time() + 3600).is_expired() is False
    # Inside the leeway window: still valid on the clock, treated as expired.
    assert _token(expires_at=time.time() + 5).is_expired() is True
    assert _token(expires_at=None).is_expired() is False


def test_handle_comes_from_the_configured_claim() -> None:
    token = _token(access_token=_jwt({"sub": "@Avery", "email": "avery@example.com"}))

    assert token.handle() == "avery"
    assert token.handle("email") == "avery@example.com"
    # An opaque (non-JWT) access token has no readable claims, which is not an error.
    assert _token(access_token="opaque").handle() is None


# ── Authorization Code + PKCE ────────────────────────────────────────────────


def test_authorization_code_flow_completes_with_a_verified_pkce_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, data: dict[str, str], timeout: float) -> _Resp:  # noqa: ARG001
        captured["form"] = data
        return _Resp({"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 300})

    monkeypatch.setattr(oidc.httpx, "post", fake_post)

    def fake_browser(url: str) -> bool:
        # Stand in for the user completing the login: the IdP redirects back to
        # the loopback listener with a code. Real socket, real handler.
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        captured["auth_query"] = {k: v[0] for k, v in query.items()}
        redirect = captured["auth_query"]["redirect_uri"]
        state = captured["auth_query"]["state"]

        def _visit() -> None:
            urllib.request.urlopen(f"{redirect}?code=code-1&state={state}", timeout=5).read()  # noqa: S310

        threading.Thread(target=_visit, daemon=True).start()
        return True

    monkeypatch.setattr(oidc.webbrowser, "open", fake_browser)

    grant = oidc.authorization_code_login(_META, "mycelium-cli", scope="openid", timeout_s=15)

    assert grant.access_token == "at-1"
    assert grant.refresh_token == "rt-1"
    assert grant.expires_at is not None and grant.expires_at > time.time()

    # The exchange proves possession of the verifier behind the S256 challenge.
    verifier = captured["form"]["code_verifier"]
    digest = hashlib.sha256(verifier.encode()).digest()
    expected = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    assert captured["auth_query"]["code_challenge"] == expected
    assert captured["auth_query"]["code_challenge_method"] == "S256"
    assert captured["form"]["grant_type"] == "authorization_code"
    assert captured["form"]["code"] == "code-1"


def test_authorization_code_flow_refuses_a_mismatched_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_browser(url: str) -> bool:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        redirect = query["redirect_uri"][0]

        def _visit() -> None:
            urllib.request.urlopen(f"{redirect}?code=code-1&state=not-ours", timeout=5).read()  # noqa: S310

        threading.Thread(target=_visit, daemon=True).start()
        return True

    monkeypatch.setattr(oidc.webbrowser, "open", fake_browser)
    monkeypatch.setattr(
        oidc.httpx, "post", lambda *_a, **_k: pytest.fail("code exchanged despite bad state")
    )

    with pytest.raises(OidcError, match="state mismatch"):
        oidc.authorization_code_login(_META, "mycelium-cli", scope="openid", timeout_s=15)


def test_authorization_code_flow_surfaces_the_issuers_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_browser(url: str) -> bool:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        redirect = query["redirect_uri"][0]

        def _visit() -> None:
            urllib.request.urlopen(  # noqa: S310
                f"{redirect}?error=access_denied&error_description=user+said+no", timeout=5
            ).read()

        threading.Thread(target=_visit, daemon=True).start()
        return True

    monkeypatch.setattr(oidc.webbrowser, "open", fake_browser)

    with pytest.raises(OidcError, match="access_denied: user said no"):
        oidc.authorization_code_login(_META, "mycelium-cli", scope="openid", timeout_s=15)


# ── device code ──────────────────────────────────────────────────────────────


def test_device_flow_polls_through_pending_and_slow_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [
        _Resp(
            {
                "device_code": "dev-1",
                "user_code": "WDJB-MJHT",
                "verification_uri": "https://idp.test/device",
                "interval": 1,
                "expires_in": 60,
            }
        ),
        _Resp({"error": "authorization_pending"}, status_code=400),
        _Resp({"error": "slow_down"}, status_code=400),
        _Resp({"access_token": "at-2", "expires_in": 300}),
    ]
    seen: list[dict[str, str]] = []

    def fake_post(url: str, data: dict[str, str], timeout: float) -> _Resp:  # noqa: ARG001
        seen.append(data)
        return responses.pop(0)

    monkeypatch.setattr(oidc.httpx, "post", fake_post)
    monkeypatch.setattr(oidc.time, "sleep", lambda _s: None)

    prompts: list[oidc.DevicePrompt] = []
    grant = oidc.device_code_login(
        _META, "mycelium-cli", scope="openid", timeout_s=30, announce=prompts.append
    )

    assert grant.access_token == "at-2"
    assert prompts[0].user_code == "WDJB-MJHT"
    assert prompts[0].verification_uri == "https://idp.test/device"
    assert [d["grant_type"] for d in seen[1:]] == [
        "urn:ietf:params:oauth:grant-type:device_code"
    ] * 3


def test_device_flow_needs_an_issuer_that_supports_it() -> None:
    meta = ProviderMetadata(issuer=_META.issuer, token_endpoint=_META.token_endpoint)

    with pytest.raises(OidcError, match="does not support the device-code flow"):
        oidc.device_code_login(meta, "mycelium-cli", scope="openid")


# ── the client seam ──────────────────────────────────────────────────────────


def test_logged_out_clients_send_no_authorization_header() -> None:
    assert client_mod.auth_headers() == {}

    with client_mod.hub_client() as raw:
        assert "authorization" not in raw.headers


def test_every_client_carries_the_bearer_once_signed_in() -> None:
    token = _token(access_token="at-live")
    save_token(token)

    assert client_mod.auth_headers() == {"Authorization": "Bearer at-live"}

    with client_mod.hub_client(headers={"If-None-Match": "etag-1"}) as raw:
        assert raw.headers["authorization"] == "Bearer at-live"
        # Caller-supplied headers ride along rather than replacing the session.
        assert raw.headers["if-none-match"] == "etag-1"

    typed = client_mod.typed_client()
    assert typed.get_httpx_client().headers["authorization"] == "Bearer at-live"


def test_an_expired_token_is_refreshed_transparently_and_re_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_token(_token(access_token="at-stale", expires_at=time.time() - 10))

    forms: list[dict[str, str]] = []

    def fake_post(url: str, data: dict[str, str], timeout: float) -> _Resp:  # noqa: ARG001
        forms.append(data)
        assert url == _META.token_endpoint
        return _Resp({"access_token": "at-fresh", "expires_in": 3600})

    monkeypatch.setattr(oidc.httpx, "post", fake_post)

    assert client_mod.auth_headers() == {"Authorization": "Bearer at-fresh"}
    assert forms[0]["grant_type"] == "refresh_token"
    assert forms[0]["refresh_token"] == "refresh-1"

    # Renewed once, then served from the cache — the next call re-reads the file.
    cached = load_token()
    assert cached is not None
    assert cached.access_token == "at-fresh"
    # The issuer didn't rotate the refresh token, so the existing one is kept.
    assert cached.refresh_token == "refresh-1"
    assert client_mod.auth_headers() == {"Authorization": "Bearer at-fresh"}
    assert len(forms) == 1


def test_a_dead_session_degrades_to_no_header_rather_than_a_stale_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_token(_token(access_token="at-stale", expires_at=time.time() - 10))

    def fake_post(url: str, data: dict[str, str], timeout: float) -> _Resp:  # noqa: ARG001
        return _Resp({"error": "invalid_grant"}, status_code=400)

    monkeypatch.setattr(oidc.httpx, "post", fake_post)

    # An expired token would turn a working call against an ungated hub into a
    # 401; sending nothing keeps the off-by-default path working.
    assert client_mod.auth_headers() == {}


def test_an_expired_token_with_no_refresh_token_sends_nothing() -> None:
    save_token(_token(expires_at=time.time() - 10, refresh_token=None))

    assert client_mod.auth_headers() == {}


# ── the commands ─────────────────────────────────────────────────────────────


def _health(monkeypatch: pytest.MonkeyPatch, payload: Any, *, boom: bool = False) -> list[str]:
    """Stub the hub's ``/health`` — where login looks when it has no issuer.

    ``_hub_issuers`` imports httpx inside the call, so the module object is what
    has to be patched; it is the same one either way.
    """
    asked: list[str] = []

    class _Resp:
        def raise_for_status(self) -> None: ...

        def json(self) -> Any:
            return payload

    def fake_get(url: str, timeout: float) -> _Resp:  # noqa: ARG001
        asked.append(url)
        if boom:
            raise httpx.ConnectError("connection refused")
        return _Resp()

    monkeypatch.setattr(httpx, "get", fake_get)
    return asked


def test_login_without_a_configured_issuer_says_what_to_do(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreachable hub falls back to the original tell-me-what-to-do error."""
    _health(monkeypatch, None, boom=True)

    result = runner.invoke(app, ["login"])

    assert result.exit_code == 1
    assert "no OIDC issuer configured" in _flat(result.stdout)
    assert "login.issuer" in _flat(result.stdout)
    assert load_token() is None


def test_login_caches_the_session_and_remembers_the_issuer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mycelium.commands import login as login_cmd

    monkeypatch.setattr(login_cmd, "_browser_available", lambda: True)
    monkeypatch.setattr(login_cmd, "discover", lambda _issuer: _META)
    monkeypatch.setattr(
        login_cmd,
        "authorization_code_login",
        lambda *_a, **_k: oidc.TokenResponse(
            access_token=_jwt({"sub": "avery"}),
            refresh_token="rt-1",
            expires_at=time.time() + 3600,
        ),
    )

    result = runner.invoke(app, ["login", "--issuer", "https://idp.test/realms/mycelium"])

    assert result.exit_code == 0
    assert "Signed in as @avery" in _flat(result.stdout)

    cached = load_token()
    assert cached is not None
    assert cached.issuer == _META.issuer
    assert cached.token_endpoint == _META.token_endpoint
    # The issuer is remembered, so the next login (and any refresh) needs no flag.
    assert MyceliumConfig.load().login.issuer == "https://idp.test/realms/mycelium"


def test_login_device_flag_takes_the_device_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from mycelium.commands import login as login_cmd

    monkeypatch.setattr(login_cmd, "discover", lambda _issuer: _META)
    monkeypatch.setattr(
        login_cmd,
        "authorization_code_login",
        lambda *_a, **_k: pytest.fail("--device must not open a browser flow"),
    )
    monkeypatch.setattr(
        login_cmd,
        "device_code_login",
        lambda *_a, **_k: oidc.TokenResponse(access_token=_jwt({"sub": "avery"})),
    )

    result = runner.invoke(
        app, ["login", "--device", "--issuer", "https://idp.test/realms/mycelium"]
    )

    assert result.exit_code == 0
    assert load_token() is not None


def test_login_falls_back_to_device_code_when_there_is_no_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A headless shell (SSH, CI, a container) can't be redirected to loopback."""
    from mycelium.commands import login as login_cmd

    monkeypatch.setattr(login_cmd, "_browser_available", lambda: False)
    monkeypatch.setattr(login_cmd, "discover", lambda _issuer: _META)
    monkeypatch.setattr(
        login_cmd,
        "authorization_code_login",
        lambda *_a, **_k: pytest.fail("browser flow attempted with no browser"),
    )
    monkeypatch.setattr(
        login_cmd,
        "device_code_login",
        lambda *_a, **_k: oidc.TokenResponse(access_token=_jwt({"sub": "avery"})),
    )

    result = runner.invoke(app, ["login", "--issuer", "https://idp.test/realms/mycelium"])

    assert result.exit_code == 0
    assert "falling back to the device-code flow" in _flat(result.stdout)
    assert load_token() is not None


def test_login_reports_a_failed_flow_without_caching_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mycelium.commands import login as login_cmd

    monkeypatch.setattr(login_cmd, "_browser_available", lambda: True)
    monkeypatch.setattr(login_cmd, "discover", lambda _issuer: _META)

    def boom(*_a: Any, **_k: Any) -> None:
        raise OidcError("access_denied: user said no")

    monkeypatch.setattr(login_cmd, "authorization_code_login", boom)

    result = runner.invoke(app, ["login", "--issuer", "https://idp.test/realms/mycelium"])

    assert result.exit_code == 1
    assert "Login failed: access_denied" in _flat(result.stdout)
    assert load_token() is None


def test_logout_drops_the_session() -> None:
    save_token(_token())

    result = runner.invoke(app, ["logout"])

    assert result.exit_code == 0
    assert "Signed out" in result.stdout
    assert load_token() is None
    assert client_mod.auth_headers() == {}


def test_whoami_reports_the_token_identity_when_signed_in() -> None:
    save_token(_token(access_token=_jwt({"sub": "avery", "exp": time.time() + 3600})))

    result = runner.invoke(app, ["--json", "whoami"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["authenticated"] is True
    assert payload["principal"] == "avery"
    assert payload["token"]["issuer"] == _META.issuer


def test_whoami_is_unchanged_when_logged_out() -> None:
    config = MyceliumConfig.load()
    config.identity.name = "avery"
    config.save()

    result = runner.invoke(app, ["--json", "whoami"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["authenticated"] is False
    assert payload["token"] is None
    assert payload["principal"] == "avery"


def _auth(*issuers: str, enabled: bool = True) -> dict[str, Any]:
    return {"auth": {"enabled": enabled, "issuers": list(issuers)}}


def test_login_discovers_the_issuer_from_the_hub(
    monkeypatch: pytest.MonkeyPatch, hub: _Hub
) -> None:
    """The hub advertises its trusted issuers, so discovery is automatic."""
    from mycelium.commands import login as login_cmd

    asked = _health(monkeypatch, _auth(_META.issuer))
    seen: dict[str, str] = {}

    def fake_discover(url: str) -> ProviderMetadata:
        seen["issuer"] = url
        return _META

    monkeypatch.setattr(login_cmd, "_browser_available", lambda: True)
    monkeypatch.setattr(login_cmd, "discover", fake_discover)
    monkeypatch.setattr(
        login_cmd,
        "authorization_code_login",
        lambda *_a, **_k: oidc.TokenResponse(access_token=_jwt({"sub": "avery"})),
    )

    result = runner.invoke(app, ["login"])

    assert result.exit_code == 0, result.stdout
    assert asked == [f"{MyceliumConfig.load().server.api_url.rstrip('/')}/health"]
    assert seen["issuer"] == _META.issuer
    assert "Issuer discovered from" in _flat(result.stdout)
    # Remembered, so the next login costs no round trip.
    assert MyceliumConfig.load().login.issuer == _META.issuer


def test_json_login_stays_parseable_while_discovering_and_saving(
    monkeypatch: pytest.MonkeyPatch, hub: _Hub
) -> None:
    """Discovery both prints and saves, and --json promises one JSON document."""
    from mycelium.commands import login as login_cmd

    _health(monkeypatch, _auth(_META.issuer))
    monkeypatch.setattr(login_cmd, "_browser_available", lambda: True)
    monkeypatch.setattr(login_cmd, "discover", lambda _issuer: _META)
    monkeypatch.setattr(
        login_cmd,
        "authorization_code_login",
        lambda *_a, **_k: oidc.TokenResponse(access_token=_jwt({"sub": "avery"})),
    )

    result = runner.invoke(app, ["--json", "login"])

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["handle"] == "avery"
    # Saved anyway — quiet is not the same as skipped.
    assert MyceliumConfig.load().login.issuer == _META.issuer


def test_login_prefers_a_configured_issuer_over_asking_the_hub(
    monkeypatch: pytest.MonkeyPatch, hub: _Hub
) -> None:
    asked = _health(monkeypatch, _auth("https://wrong.test/realms/other"))
    config = MyceliumConfig.load()
    config.login.issuer = _META.issuer
    config.save()

    from mycelium.commands import login as login_cmd

    monkeypatch.setattr(login_cmd, "_browser_available", lambda: True)
    monkeypatch.setattr(login_cmd, "discover", lambda _issuer: _META)
    monkeypatch.setattr(
        login_cmd,
        "authorization_code_login",
        lambda *_a, **_k: oidc.TokenResponse(access_token=_jwt({"sub": "avery"})),
    )

    result = runner.invoke(app, ["login"])

    assert result.exit_code == 0, result.stdout
    # Configured means configured: the hub is not consulted at all.
    assert asked == []


def test_login_refuses_to_guess_between_several_trusted_issuers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Which issuer you sign in against decides who the hub thinks you are."""
    _health(monkeypatch, _auth("https://a.test/realms/x", "https://b.test/realms/y"))

    result = runner.invoke(app, ["login"])

    assert result.exit_code == 1
    assert "more than one issuer" in _flat(result.stdout)
    # Listed, so the lookup is still done for you even when the pick isn't.
    assert "https://a.test/realms/x" in result.stdout
    assert "https://b.test/realms/y" in result.stdout
    assert load_token() is None


def test_login_says_an_ungated_hub_needs_no_login(monkeypatch: pytest.MonkeyPatch) -> None:
    _health(monkeypatch, _auth(enabled=False))

    result = runner.invoke(app, ["login"])

    assert result.exit_code == 1
    assert "gate off" in _flat(result.stdout)
    assert load_token() is None


def test_login_says_when_a_gated_hub_advertises_no_issuer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _health(monkeypatch, _auth())

    result = runner.invoke(app, ["login"])

    assert result.exit_code == 1
    assert "advertises no issuer" in _flat(result.stdout)


def test_login_survives_a_health_endpoint_that_is_not_an_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A proxy or a wrong port can answer /health with anything at all."""
    _health(monkeypatch, ["not", "an", "object"])

    result = runner.invoke(app, ["login"])

    assert result.exit_code == 1
    assert "no OIDC issuer configured" in _flat(result.stdout)


def test_a_discovered_issuer_is_not_remembered_when_the_login_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caching a URL that never produced a session would poison the next login."""
    _health(monkeypatch, _auth(_META.issuer))

    from mycelium.commands import login as login_cmd

    monkeypatch.setattr(login_cmd, "_browser_available", lambda: True)
    monkeypatch.setattr(login_cmd, "discover", lambda _issuer: _META)

    def boom(*_a: Any, **_k: Any) -> None:
        raise OidcError("access_denied: user said no")

    monkeypatch.setattr(login_cmd, "authorization_code_login", boom)

    result = runner.invoke(app, ["login"])

    assert result.exit_code == 1
    assert MyceliumConfig.load().login.issuer is None
    assert load_token() is None


def test_iam_with_no_handle_reports_rather_than_asserting() -> None:
    save_token(_token(access_token=_jwt({"sub": "avery", "exp": time.time() + 3600})))

    result = runner.invoke(app, ["--json", "iam"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["principal"] == "avery"
    # Reporting is read-only: nothing was written to identity.name.
    assert MyceliumConfig.load().identity.name is None


def _login(
    monkeypatch: pytest.MonkeyPatch,
    sub: str = "avery",
    *,
    json_output: bool = False,
) -> Any:
    """Run a successful browser login whose token carries *sub* as its handle."""
    from mycelium.commands import login as login_cmd

    monkeypatch.setattr(login_cmd, "_browser_available", lambda: True)
    monkeypatch.setattr(login_cmd, "discover", lambda _issuer: _META)
    monkeypatch.setattr(
        login_cmd,
        "authorization_code_login",
        lambda *_a, **_k: oidc.TokenResponse(access_token=_jwt({"sub": sub})),
    )
    if json_output:
        config = MyceliumConfig.load()
        config.login.issuer = _META.issuer
        config.save()
        return runner.invoke(app, ["--json", "login"])
    return runner.invoke(app, ["login", "--issuer", "https://idp.test/realms/mycelium"])


def test_login_aligns_this_machines_identity_to_the_token_handle(
    monkeypatch: pytest.MonkeyPatch, hub: _Hub
) -> None:
    """The token handle is authoritative; login aligns local identity to it."""
    config = MyceliumConfig.load()
    config.identity.name = "bob"
    config.save()

    result = _login(monkeypatch)

    assert result.exit_code == 0
    assert MyceliumConfig.load().identity.name == "avery"
    # The other half of ``iam``: the principal exists on the hub, not just here.
    assert hub.created == ["avery"]
    assert "now writes as @avery" in _flat(result.stdout)
    # No second command to relay back by hand.
    assert "Heads up" not in _flat(result.stdout)
    assert "mycelium iam avery" not in _flat(result.stdout)


def test_login_names_an_unset_identity_rather_than_leaving_it_unknown(
    monkeypatch: pytest.MonkeyPatch, hub: _Hub
) -> None:
    """An unset identity resolves to "unknown", which a gated hub refuses too."""
    assert MyceliumConfig.load().identity.name is None

    result = _login(monkeypatch)

    assert result.exit_code == 0
    assert MyceliumConfig.load().identity.name == "avery"
    assert hub.created == ["avery"]


def test_login_leaves_an_already_matching_identity_untouched(
    monkeypatch: pytest.MonkeyPatch, hub: _Hub
) -> None:
    config = MyceliumConfig.load()
    config.identity.name = "@Avery"
    config.save()

    result = _login(monkeypatch)

    assert result.exit_code == 0
    # Nothing disagreed, so login writes nothing — not locally, not on the hub.
    assert MyceliumConfig.load().identity.name == "@Avery"
    assert hub.created == []
    assert "now writes as" not in _flat(result.stdout)


def test_login_aligns_locally_even_when_the_hub_is_unreachable(
    monkeypatch: pytest.MonkeyPatch, hub: _Hub
) -> None:
    """The local half is what stops the 403; registration can catch up later."""
    hub.reachable = False

    result = _login(monkeypatch)

    assert result.exit_code == 0
    assert MyceliumConfig.load().identity.name == "avery"
    assert "Not registered on the hub" in _flat(result.stdout)
    assert "mycelium iam avery" in _flat(result.stdout)


def test_login_falls_back_to_the_warning_when_the_handle_cannot_be_aligned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A handle the user store rejects must not turn a good login into a failure."""
    config = MyceliumConfig.load()
    config.identity.name = "bob"
    config.save()

    result = _login(monkeypatch, sub="Avery Quinn")

    assert result.exit_code == 0
    assert MyceliumConfig.load().identity.name == "bob"
    assert "this machine writes as @bob" in _flat(result.stdout)
    assert "mycelium iam" in _flat(result.stdout)


def test_login_json_reports_the_identity_it_landed(
    monkeypatch: pytest.MonkeyPatch, hub: _Hub
) -> None:
    """Aligning is behavior, not formatting: --json takes the same path."""
    result = _login(monkeypatch, json_output=True)

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["handle"] == "avery"
    assert payload["identity"] == "avery"
    assert hub.created == ["avery"]


def test_iam_flags_a_handle_the_token_will_not_back() -> None:
    save_token(_token(access_token=_jwt({"sub": "avery", "exp": time.time() + 3600})))

    result = runner.invoke(app, ["iam", "bob"])

    assert result.exit_code == 0
    assert "you're signed in as @avery" in _flat(result.stdout)
    assert "refuse writes claiming a different handle" in _flat(result.stdout)


# ── what a session says about renewing itself ────────────────────────────────


def _login_with(
    monkeypatch: pytest.MonkeyPatch,
    grant: oidc.TokenResponse,
    *,
    json_output: bool = False,
) -> Any:
    """Run a successful browser login that lands *grant* in the cache."""
    from mycelium.commands import login as login_cmd

    monkeypatch.setattr(login_cmd, "_browser_available", lambda: True)
    monkeypatch.setattr(login_cmd, "discover", lambda _issuer: _META)
    monkeypatch.setattr(login_cmd, "authorization_code_login", lambda *_a, **_k: grant)
    if json_output:
        config = MyceliumConfig.load()
        config.login.issuer = _META.issuer
        config.save()
        return runner.invoke(app, ["--json", "login"])
    return runner.invoke(app, ["login", "--issuer", "https://idp.test/realms/mycelium"])


def test_a_token_response_carries_the_refresh_deadline_when_the_issuer_reports_one() -> None:
    grant = oidc._as_token_response(
        {
            "access_token": "at-1",
            "refresh_token": "rt-1",
            "expires_in": 300,
            "refresh_expires_in": 1800,
        }
    )

    assert grant.refresh_expires_at is not None
    assert 1700 < grant.refresh_expires_at - time.time() <= 1800


def test_a_silent_issuer_leaves_the_refresh_deadline_unknown() -> None:
    """Unknown, never guessed: most issuers say nothing, and 0 means 'no expiry'."""
    quiet = oidc._as_token_response({"access_token": "at-1", "expires_in": 300})
    offline = oidc._as_token_response({"access_token": "at-1", "refresh_expires_in": 0})

    assert quiet.refresh_expires_at is None
    assert offline.refresh_expires_at is None


def test_the_refresh_deadline_round_trips_through_the_cache() -> None:
    deadline = time.time() + 1800
    save_token(_token(refresh_expires_at=deadline))

    cached = load_token()
    assert cached is not None
    assert cached.refresh_expires_at == deadline
    assert cached.refresh_expires_in() is not None


def test_login_says_the_session_renews_itself_and_when_it_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 4-minute number reads as a re-login countdown unless renewal is stated."""
    result = _login_with(
        monkeypatch,
        oidc.TokenResponse(
            access_token=_jwt({"sub": "avery"}),
            refresh_token="rt-1",
            expires_at=time.time() + 300,
            refresh_expires_at=time.time() + 30 * 86400,
        ),
    )

    assert result.exit_code == 0
    out = _flat(result.stdout)
    # 299.9s left, one instant after minting: the issuer's 5 minutes, not 4.
    assert "Access token valid for 5 min" in out
    assert "renews on demand" in out
    assert "under 1 min is left" in out
    assert "Nothing renews in the background" in out
    assert "Signing in again is due in 30 days" in out


def test_login_says_nothing_about_a_deadline_the_issuer_never_gave(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _login_with(
        monkeypatch,
        oidc.TokenResponse(
            access_token=_jwt({"sub": "avery"}),
            refresh_token="rt-1",
            expires_at=time.time() + 240,
        ),
    )

    assert result.exit_code == 0
    out = _flat(result.stdout)
    assert "renews on demand" in out
    assert "Signing in again is due" not in out


def test_login_without_a_refresh_token_says_that_is_the_whole_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _login_with(
        monkeypatch,
        oidc.TokenResponse(access_token=_jwt({"sub": "avery"}), expires_at=time.time() + 240),
    )

    assert result.exit_code == 0
    out = _flat(result.stdout)
    assert "the session ends when this access token does" in out
    assert "offline_access" in out
    assert "renews on demand" not in out


def test_login_json_carries_the_renewal_facts(monkeypatch: pytest.MonkeyPatch, hub: _Hub) -> None:
    deadline = time.time() + 1800
    result = _login_with(
        monkeypatch,
        oidc.TokenResponse(
            access_token=_jwt({"sub": "avery"}),
            refresh_token="rt-1",
            expires_at=time.time() + 240,
            refresh_expires_at=deadline,
        ),
        json_output=True,
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["refreshable"] is True
    assert payload["refresh_expires_at"] == pytest.approx(deadline)
    assert payload["renewal_leeway_s"] == tokens.DEFAULT_LEEWAY_S


def test_a_refresh_carries_the_deadline_of_whichever_token_survives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rotated refresh token brings its own deadline; a kept one keeps its own."""
    original = time.time() + 1800
    save_token(
        _token(access_token="at-stale", expires_at=time.time() - 10, refresh_expires_at=original)
    )

    def rotated(_url: str, **_kw: Any) -> _Resp:
        return _Resp(
            {
                "access_token": "at-fresh",
                "refresh_token": "rt-2",
                "expires_in": 3600,
                "refresh_expires_in": 7200,
            }
        )

    monkeypatch.setattr(httpx, "post", rotated)
    renewed = client_mod.current_token()
    assert renewed is not None
    assert renewed.refresh_expires_at is not None
    assert renewed.refresh_expires_at > original

    save_token(
        _token(access_token="at-stale", expires_at=time.time() - 10, refresh_expires_at=original)
    )
    monkeypatch.setattr(
        httpx, "post", lambda _url, **_kw: _Resp({"access_token": "at-fresh", "expires_in": 3600})
    )
    kept = client_mod.current_token()
    assert kept is not None
    assert kept.refresh_expires_at == original


def test_whoami_says_renewal_happens_on_the_next_command() -> None:
    save_token(
        _token(
            access_token=_jwt({"sub": "avery", "exp": time.time() + 3600}),
            refresh_expires_at=time.time() + 30 * 86400,
        )
    )

    result = runner.invoke(app, ["whoami"])

    assert result.exit_code == 0
    out = _flat(result.stdout)
    assert "renewed on the next command that needs it" in out
    assert "re-login due in 30 days" in out
