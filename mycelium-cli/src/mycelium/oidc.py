# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
OIDC login flows for ``mycelium login`` — Authorization Code + PKCE, device code,
and the refresh-token grant.

Issuer-agnostic on purpose: everything here is driven off the issuer's discovery
document, so the same code logs in against Keycloak, Dex, ZITADEL, or the dev mock
issuer (``docs/design/dev-auth-issuer.md``) with nothing but a different URL.

Two flows, because humans sit in two different places:

* **Authorization Code + PKCE** — the primary path. The browser does the login;
  the code comes back to a loopback listener the CLI opens for the occasion. PKCE
  (RFC 7636) is what lets the CLI be a *public* client: no client secret to ship,
  and an intercepted code is useless without the verifier.
* **Device code** (RFC 8628) — for a shell with no browser it can reach: SSH, CI,
  a container. The CLI prints a URL and a short code, and polls.

Nothing here touches the token cache; the caller decides what to persist.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import secrets
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from typing import Any, cast

import httpx

_DISCOVERY_PATH = "/.well-known/openid-configuration"
_DEVICE_CODE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"

_HTTP_TIMEOUT_S = 15.0
#: Fallback poll interval when the device-code response omits one (RFC 8628 §3.2).
_DEFAULT_DEVICE_INTERVAL_S = 5.0

_CALLBACK_PATH = "/callback"

_BROWSER_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Mycelium</title></head>
<body style="font-family: system-ui, sans-serif; padding: 3rem; text-align: center">
<h2>{heading}</h2><p style="color:#666">{detail}</p></body></html>"""


class OidcError(Exception):
    """A login flow could not complete. The message is user-facing."""


@dataclass(frozen=True)
class ProviderMetadata:
    """The endpoints of an issuer, as advertised by its discovery document."""

    issuer: str
    token_endpoint: str
    authorization_endpoint: str | None = None
    device_authorization_endpoint: str | None = None


@dataclass(frozen=True)
class TokenResponse:
    """A successful token grant, normalized."""

    access_token: str
    refresh_token: str | None = None
    expires_at: float | None = None
    scope: str | None = None


@dataclass(frozen=True)
class DevicePrompt:
    """What the user has to do to finish a device-code login."""

    user_code: str
    verification_uri: str
    verification_uri_complete: str | None = None
    expires_in: float | None = None


def discover(issuer: str, *, timeout_s: float = _HTTP_TIMEOUT_S) -> ProviderMetadata:
    """Fetch an issuer's OIDC discovery document."""
    url = issuer.rstrip("/") + _DISCOVERY_PATH
    try:
        resp = httpx.get(url, timeout=timeout_s, follow_redirects=True)
        resp.raise_for_status()
        doc = resp.json()
    except httpx.HTTPError as exc:
        raise OidcError(f"can't reach the issuer's discovery document at {url}: {exc}") from exc
    except ValueError as exc:
        raise OidcError(f"issuer returned a non-JSON discovery document at {url}") from exc

    token_endpoint = doc.get("token_endpoint")
    if not token_endpoint:
        raise OidcError(f"issuer at {issuer} advertises no token_endpoint")

    return ProviderMetadata(
        # The document's own `issuer` is authoritative — it is the `iss` the hub
        # will see in the token, which may differ from the URL used to reach it.
        issuer=str(doc.get("issuer") or issuer).rstrip("/"),
        token_endpoint=str(token_endpoint),
        authorization_endpoint=doc.get("authorization_endpoint"),
        device_authorization_endpoint=doc.get("device_authorization_endpoint"),
    )


def _open_browser(url: str) -> None:
    """Best-effort browser launch; a failure just leaves the printed URL."""
    try:
        webbrowser.open(url)
    except webbrowser.Error:
        pass


def _pkce_pair() -> tuple[str, str]:
    """A PKCE ``(verifier, S256 challenge)`` pair."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def _token_request(
    token_endpoint: str,
    form: dict[str, str],
    *,
    timeout_s: float = _HTTP_TIMEOUT_S,
) -> dict[str, Any]:
    """POST a token request, raising :class:`OidcError` with the issuer's reason."""
    try:
        resp = httpx.post(token_endpoint, data=form, timeout=timeout_s)
    except httpx.HTTPError as exc:
        raise OidcError(f"can't reach the token endpoint {token_endpoint}: {exc}") from exc

    try:
        body = resp.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}

    if resp.status_code >= 400:
        error = str(body.get("error") or f"HTTP {resp.status_code}")
        detail = body.get("error_description")
        raise OidcError(f"{error}: {detail}" if detail else error)
    return body


def _as_token_response(body: dict[str, Any]) -> TokenResponse:
    access_token = body.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise OidcError("issuer returned no access_token")
    expires_in = body.get("expires_in")
    expires_at = time.time() + float(expires_in) if isinstance(expires_in, int | float) else None
    return TokenResponse(
        access_token=access_token,
        refresh_token=body.get("refresh_token") or None,
        expires_at=expires_at,
        scope=body.get("scope") or None,
    )


class _CallbackServer(http.server.HTTPServer):
    """A one-shot loopback listener for the authorization-code redirect."""

    result: dict[str, str] | None = None


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler's interface
        parsed = urllib.parse.urlparse(self.path)
        params = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}

        # A browser also asks for /favicon.ico; only the redirect finishes the flow.
        if parsed.path != _CALLBACK_PATH or not ("code" in params or "error" in params):
            self.send_error(404)
            return

        cast("_CallbackServer", self.server).result = params
        if "code" in params:
            page = _BROWSER_PAGE.format(
                heading="You're signed in to Mycelium.",
                detail="You can close this tab and return to your terminal.",
            )
        else:
            page = _BROWSER_PAGE.format(
                heading="Sign-in failed.",
                detail=params.get("error_description") or params.get("error", ""),
            )
        body = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 — base signature
        """Silence the default stderr access log — this is a CLI, not a server."""


def authorization_code_login(
    meta: ProviderMetadata,
    client_id: str,
    *,
    scope: str,
    audience: str | None = None,
    client_secret: str | None = None,
    redirect_port: int = 0,
    open_browser: bool = True,
    timeout_s: float = 300.0,
    announce: Any = None,
) -> TokenResponse:
    """Log in through the browser with Authorization Code + PKCE.

    ``announce`` is called with the authorization URL before the wait begins, so
    the caller can print it — the browser may fail to open, and the URL is then
    the whole recovery path.
    """
    if not meta.authorization_endpoint:
        raise OidcError(
            f"issuer {meta.issuer} advertises no authorization_endpoint; "
            "retry with --device for the device-code flow"
        )

    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(24)

    try:
        server = _CallbackServer(("127.0.0.1", redirect_port), _CallbackHandler)
    except OSError as exc:
        raise OidcError(f"can't open the loopback listener on port {redirect_port}: {exc}") from exc

    with server:
        redirect_uri = f"http://127.0.0.1:{server.server_port}{_CALLBACK_PATH}"
        query = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        if audience:
            query["audience"] = audience
        auth_url = f"{meta.authorization_endpoint}?{urllib.parse.urlencode(query)}"

        if announce is not None:
            announce(auth_url)
        if open_browser:
            # On a thread, because `webbrowser.open` waits for the browser
            # process when it is a generic one (anything the user set in
            # $BROWSER). Opening inline would deadlock: the browser blocks on a
            # redirect only this loop can answer, and this loop waits for the
            # browser.
            threading.Thread(target=_open_browser, args=(auth_url,), daemon=True).start()

        server.timeout = 1.0
        deadline = time.monotonic() + timeout_s
        while server.result is None and time.monotonic() < deadline:
            server.handle_request()
        params = server.result

    if params is None:
        raise OidcError(f"timed out after {timeout_s:.0f}s waiting for the browser redirect")
    if "error" in params:
        detail = params.get("error_description")
        raise OidcError(f"{params['error']}: {detail}" if detail else params["error"])
    if not secrets.compare_digest(params.get("state", ""), state):
        # A mismatched state means the redirect didn't come from the request we
        # made — the CSRF case RFC 6749 §10.12 describes. Refuse the code.
        raise OidcError("state mismatch on the redirect; login aborted")

    form = {
        "grant_type": "authorization_code",
        "code": params["code"],
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": verifier,
    }
    if client_secret:
        form["client_secret"] = client_secret
    return _as_token_response(_token_request(meta.token_endpoint, form))


def device_code_login(
    meta: ProviderMetadata,
    client_id: str,
    *,
    scope: str,
    audience: str | None = None,
    client_secret: str | None = None,
    timeout_s: float = 300.0,
    announce: Any = None,
) -> TokenResponse:
    """Log in without a browser on this machine (RFC 8628).

    ``announce`` is called with a :class:`DevicePrompt` — the code and URL the
    user has to visit — before polling starts.
    """
    if not meta.device_authorization_endpoint:
        raise OidcError(f"issuer {meta.issuer} does not support the device-code flow")

    form = {"client_id": client_id, "scope": scope}
    if audience:
        form["audience"] = audience
    if client_secret:
        form["client_secret"] = client_secret
    body = _token_request(meta.device_authorization_endpoint, form)

    device_code = body.get("device_code")
    user_code = body.get("user_code")
    verification_uri = body.get("verification_uri") or body.get("verification_url")
    if not device_code or not user_code or not verification_uri:
        raise OidcError("issuer returned an incomplete device-authorization response")

    expires_in = body.get("expires_in")
    if announce is not None:
        announce(
            DevicePrompt(
                user_code=str(user_code),
                verification_uri=str(verification_uri),
                verification_uri_complete=body.get("verification_uri_complete"),
                expires_in=float(expires_in) if isinstance(expires_in, int | float) else None,
            )
        )

    interval = float(body.get("interval") or _DEFAULT_DEVICE_INTERVAL_S)
    # The issuer's own expiry bounds the wait when it is shorter than ours.
    limit = min(timeout_s, float(expires_in)) if isinstance(expires_in, int | float) else timeout_s
    deadline = time.monotonic() + limit

    poll = {
        "grant_type": _DEVICE_CODE_GRANT,
        "device_code": str(device_code),
        "client_id": client_id,
    }
    if client_secret:
        poll["client_secret"] = client_secret

    while time.monotonic() < deadline:
        time.sleep(interval)
        try:
            return _as_token_response(_token_request(meta.token_endpoint, poll))
        except OidcError as exc:
            reason = str(exc)
            if reason.startswith("authorization_pending"):
                continue
            if reason.startswith("slow_down"):
                # RFC 8628 §3.5: back off by 5s and keep the new interval.
                interval += 5.0
                continue
            raise
    raise OidcError(f"timed out after {limit:.0f}s waiting for you to approve the device code")


def refresh_grant(
    token_endpoint: str,
    client_id: str,
    refresh_token: str,
    *,
    client_secret: str | None = None,
    scope: str | None = None,
) -> TokenResponse:
    """Exchange a refresh token for a fresh access token."""
    form = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }
    if client_secret:
        form["client_secret"] = client_secret
    if scope:
        form["scope"] = scope
    return _as_token_response(_token_request(token_endpoint, form))
