# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Handle binding — the *authoritative* actor behind a write.

The gate (``services/auth.py``) proves a token is valid and leaves a
:class:`~app.services.auth.Principal` on ``request.state.principal``. That alone
changes nothing about attribution: every write path still took its actor from the
request body (``created_by`` / ``sender_handle`` / the reply ``handle``), which is
pure self-assertion — a valid token for ``@bob`` could still author a memory as
``@alice``. This module is where a verified token becomes the actor of record, so
memory authorship, the transcript sender, and L9 actor attribution all name
whoever the token says is calling.

Two rules, and the first one is the load-bearing one:

* **No principal, no change.** With the gate off (the shipped default), on a
  public path, or behind the localhost bypass, ``request.state.principal`` is
  ``None`` and the body's self-asserted actor is used exactly as before. The
  try-it path must not notice that this module exists.
* **A principal is the actor.** With one present, the stored actor is derived from
  the token. A body that *explicitly claims a different handle* is refused with a
  403 rather than silently rewritten: a caller acting under the wrong identity has
  a bug or is probing, and both deserve an answer rather than re-attributed writes.

A body handle may carry a session qualifier (``alpha#a8f3``). That names the same
principal, so it is honoured — the qualifier rides along on the token's handle,
which keeps per-session attribution without letting the suffix smuggle in a
different actor.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from app.services.auth import Principal, normalize_handle


def current_principal(request: Request | None) -> Principal | None:
    """The verified principal for a request, or ``None`` when it is anonymous.

    ``None`` for a request the gate never annotated — an internal caller with no
    request at all, or a call that reached a route before the dependency ran.
    """
    if request is None:
        return None
    principal = getattr(request.state, "principal", None)
    return principal if isinstance(principal, Principal) else None


def bind_actor(request: Request | None, claimed: str, *, field: str = "handle") -> str:
    """The authoritative actor for a write whose body always carries one."""
    principal = current_principal(request)
    if principal is None:
        return claimed
    return _authoritative(principal, claimed, field)


def bind_optional_actor(
    request: Request | None, claimed: str | None, *, field: str = "handle"
) -> str | None:
    """Same rule, for a body field the caller may legitimately omit.

    An omitted field is not a claim, so it is filled from the token instead of
    being read as a mismatch — which is what keeps a placeholder default (the web
    UI's ``created_by``) from looking like impersonation.
    """
    principal = current_principal(request)
    if principal is None:
        return claimed
    return _authoritative(principal, claimed, field)


def _authoritative(principal: Principal, claimed: str | None, field: str) -> str:
    base, sep, session = (claimed or "").partition("#")
    normalized = normalize_handle(base)
    if normalized is None:
        return principal.handle
    if normalized != principal.handle:
        raise HTTPException(
            status_code=403,
            detail=(
                f"{field} '{claimed}' does not match the authenticated principal "
                f"'@{principal.handle}'; a request may only act as its own token."
            ),
        )
    return f"{principal.handle}#{session}" if sep and session else principal.handle
