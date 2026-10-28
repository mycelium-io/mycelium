# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What ``mycelium version`` and ``mycelium status`` say about the hub.

Two questions, asked the same way by both: does the hub answer at all, and
does it take the credential this terminal sends. A hub reached at its app's
address answers only under ``/api``, so its health is asked there when the
bare path isn't found, the way ``doctor`` asks. A hub with sign-in on that
refuses this terminal's credential is said as that, with the credential's
source and the one thing that fixes it, never as the hub being unreachable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig


def health(api_url: str, timeout: float = 3.0) -> httpx.Response | None:
    """The hub's health answer, at ``/health`` or, from an app's address,
    ``/api/health``; ``None`` when nothing answers."""
    base = api_url.rstrip("/")
    resp = None
    for path in ("/health", "/api/health"):
        try:
            resp = httpx.get(f"{base}{path}", timeout=timeout)
        except httpx.HTTPError:
            return None
        if resp.status_code != 404:
            return resp
    return resp


@dataclass(frozen=True)
class CredentialCheck:
    """Whether the hub takes this terminal's credential, and what to say about it."""

    #: Where the credential came from, as ``whoami --sources`` says it; ``None``
    #: when this terminal sends none.
    source: str | None
    #: Who the hub says it is; ``None`` when it refused it or there was none.
    handle: str | None
    #: What to do, when the hub refused it.
    fix: str | None

    @property
    def accepted(self) -> bool:
        return self.handle is not None

    def problem(self) -> str:
        """What's wrong, when the hub refused it."""
        if self.source is None:
            return "no credential: this terminal sends none"
        return f"the hub refused the credential from {self.source}"

    def line(self) -> str:
        if self.accepted:
            return f"as @{self.handle} (credential: {self.source})"
        return f"{self.problem()}. {self.fix}"


def credential(config: MyceliumConfig) -> CredentialCheck | None:
    """What the hub makes of this terminal's credential; ``None`` when there's
    nothing to say: the hub runs with sign-in off, or can't be asked."""
    from mycelium import caller, identity
    from mycelium.commands.user import _SOURCE_LABELS

    who = identity._hub_whoami(config)  # noqa: SLF001 - the one whoami, cached per process
    if not who or not who.get("gated"):
        return None
    try:
        sent = caller.credential(config)
    except caller.ActingAsOtherError:
        sent = caller.Answer(None, caller.DEFAULT)
    source = _SOURCE_LABELS.get(sent.source, sent.source) if sent.value else None
    if who.get("handle"):
        return CredentialCheck(source=source, handle=who["handle"], fix=None)
    pane = caller.in_agent_pane()
    fix = (
        f"This is @{pane}'s pane: the runner on this computer gives its agent a token of "
        "its own within a minute (`mycelium runner status` says whether it's running)."
        if pane
        else "Run `mycelium login` in a terminal here."
    )
    return CredentialCheck(
        source=source,
        handle=None,
        fix=f"{fix} `mycelium whoami --sources` says where each answer comes from.",
    )
