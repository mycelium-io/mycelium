# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""How a provider's credential is presented on the wire.

The credential seam has to speak more than Bearer.  The trackers a
bring-your-own-tracker board will actually meet each present their secret
differently: GitHub, Asana, Sentry and Notion take ``Authorization: Bearer``;
Jira Cloud takes ``Authorization: Basic base64(email:token)``; Linear takes the
raw token under ``Authorization`` with no scheme word; PagerDuty takes
``Authorization: Token token=<token>``; and a long tail put an API key under a
header of their own such as ``X-Api-Key``.

A provider declares *which* scheme it uses; it never renders one.  A scheme is a
pure declaration with two jobs and no others:

* ``names`` lists the credential name(s) it needs resolved.  One for the common
  case, two for Basic (an identity plus a secret).
* ``headers`` turns the resolved *values* into the exact request headers.  The
  runtime resolves the names and calls this; the transform (base64 for Basic, a
  prefix for the rest) happens here, inside the runtime's reach, never in a
  provider.  A provider is handed a transport that already carries the result
  and cannot read the value back off it.

Keeping the transform in the scheme rather than in ``build_http_context`` is
what lets a new tracker be added without touching the factory: a provider author
picks a scheme, names the credential(s), and writes no auth code at all.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@runtime_checkable
class AuthScheme(Protocol):
    """The presentation of a provider's credential, declared not rendered."""

    def names(self) -> tuple[str, ...]:
        """The credential name(s) the runtime must resolve for this scheme."""
        ...

    def headers(self, values: Mapping[str, str]) -> dict[str, str]:
        """The request headers this scheme puts on the wire, given resolved values.

        ``values`` is keyed by the names ``names`` returned. Called by the
        runtime, never by a provider, so the value stays out of provider reach.
        """
        ...


@dataclass(frozen=True, slots=True)
class Bearer:
    """``Authorization: Bearer <token>``. GitHub, Asana, Sentry, Notion."""

    name: str

    def names(self) -> tuple[str, ...]:
        return (self.name,)

    def headers(self, values: Mapping[str, str]) -> dict[str, str]:
        return {"Authorization": f"Bearer {values[self.name]}"}


@dataclass(frozen=True, slots=True)
class Basic:
    """``Authorization: Basic base64(identity:secret)``. Jira Cloud.

    Basic is where a single opaque string stops being enough: it is an identity
    *and* a secret, so this scheme names two credentials rather than one. Jira
    wants the account email as the identity and an API token as the secret. The
    runtime base64-encodes ``identity:secret``; neither value is handed to the
    provider, and the identity is stored by a credential source exactly like the
    secret is, as one more named value, even though it is not itself secret.
    """

    identity: str
    secret: str

    def names(self) -> tuple[str, ...]:
        return (self.identity, self.secret)

    def headers(self, values: Mapping[str, str]) -> dict[str, str]:
        raw = f"{values[self.identity]}:{values[self.secret]}".encode()
        return {"Authorization": f"Basic {base64.b64encode(raw).decode('ascii')}"}


@dataclass(frozen=True, slots=True)
class Header:
    """A token placed verbatim under a header, with an optional prefix.

    This covers the long tail the two named schemes do not:

    * ``Header("LINEAR_TOKEN")`` -> ``Authorization: <token>`` (Linear, no scheme word)
    * ``Header("KEY", header="X-Api-Key")`` -> ``X-Api-Key: <token>`` (key in a custom header)
    * ``Header("PD_TOKEN", prefix="Token token=")`` -> ``Authorization: Token token=<token>`` (PagerDuty)

    The default, ``prefix=""`` under ``Authorization``, is a *raw token*: a real
    header that reads differently from no header at all. A provider that declares
    this sends its token bare; a provider that declares ``auth = None`` sends
    nothing. Conflating the two is exactly the bug where a Linear provider goes
    silently unauthenticated, so the two are kept structurally distinct: one is a
    scheme that emits a header, the other is the absence of a scheme.
    """

    name: str
    header: str = "Authorization"
    prefix: str = ""

    def names(self) -> tuple[str, ...]:
        return (self.name,)

    def headers(self, values: Mapping[str, str]) -> dict[str, str]:
        return {self.header: f"{self.prefix}{values[self.name]}"}
