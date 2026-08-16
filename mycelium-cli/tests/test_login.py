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
* **the identity** — ``whoami`` / ``iam`` report the token's handle when there
  is one and are untouched when there isn't.

No issuer and no backend run here: ``httpx`` is stubbed at the module the code
under test calls into.
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
    """Keep every test off the developer's real ``~/.mycelium`` and token cache."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv(tokens.TOKEN_FILE_ENV, raising=False)
    # The "session expired" notice fires once per process; reset the latch so
    # each test observes its own behavior.
    monkeypatch.setattr(client_mod, "_refresh_warned", False)


def _flat(text: str) -> str:
    """Console output with Rich's wrapping normalized away."""
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
        access_token=_jwt({"sub": "julia", "exp": time.time() + 3600}),
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
    token = _token(access_token=_jwt({"sub": "@Julia", "email": "julia@example.com"}))

    assert token.handle() == "julia"
    assert token.handle("email") == "julia@example.com"
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


def test_login_without_a_configured_issuer_says_what_to_do() -> None:
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
            access_token=_jwt({"sub": "julia"}),
            refresh_token="rt-1",
            expires_at=time.time() + 3600,
        ),
    )

    result = runner.invoke(app, ["login", "--issuer", "https://idp.test/realms/mycelium"])

    assert result.exit_code == 0
    assert "Signed in as @julia" in _flat(result.stdout)

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
        lambda *_a, **_k: oidc.TokenResponse(access_token=_jwt({"sub": "julia"})),
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
        lambda *_a, **_k: oidc.TokenResponse(access_token=_jwt({"sub": "julia"})),
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
    save_token(_token(access_token=_jwt({"sub": "julia", "exp": time.time() + 3600})))

    result = runner.invoke(app, ["--json", "whoami"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["authenticated"] is True
    assert payload["principal"] == "julia"
    assert payload["token"]["issuer"] == _META.issuer


def test_whoami_is_unchanged_when_logged_out() -> None:
    config = MyceliumConfig.load()
    config.identity.name = "julia"
    config.save()

    result = runner.invoke(app, ["--json", "whoami"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["authenticated"] is False
    assert payload["token"] is None
    assert payload["principal"] == "julia"


def test_iam_with_no_handle_reports_rather_than_asserting() -> None:
    save_token(_token(access_token=_jwt({"sub": "julia", "exp": time.time() + 3600})))

    result = runner.invoke(app, ["--json", "iam"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["principal"] == "julia"
    # Reporting is read-only: nothing was written to identity.name.
    assert MyceliumConfig.load().identity.name is None


def test_iam_flags_a_handle_the_token_will_not_back() -> None:
    save_token(_token(access_token=_jwt({"sub": "julia", "exp": time.time() + 3600})))

    result = runner.invoke(app, ["iam", "bob"])

    assert result.exit_code == 0
    assert "you're signed in as @julia" in _flat(result.stdout)
    assert "refuse writes claiming a different handle" in _flat(result.stdout)
