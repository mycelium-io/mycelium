# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What the CLI asks a hub about itself: how it is, and whether it takes a credential.

:func:`health` is every command's one way to ask a hub's health (``version``,
``status``, ``doctor``, ``install``, ``login``, ``network``, the desktop check
and the sign-in gate). A hub reached at its app's address answers only under
``/api``, so it's asked there when the bare path isn't found; this is the only
code that knows that. A hub with sign-in on that refuses this terminal's
credential is said as that, with the credential's source and the one thing that
fixes it, never as the hub being unreachable (:func:`credential`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig
    from mycelium_backend_client.models import (
        HealthAuth,
        HealthCoordination,
        HealthEmbedding,
        HealthLLM,
        HealthRead,
        HealthStorage,
    )


@dataclass(frozen=True)
class HubHealth:
    """What a hub said when asked how it is, or why it said nothing."""

    #: Where it answered: the hub's address, or its app's (``…/api``).
    url: str
    #: The status it answered with; ``None`` when nothing answered.
    status_code: int | None = None
    #: The answer, when it is one this mycelium can read.
    read: HealthRead | None = None
    #: The hub's version, from ``read``.
    version: str | None = None
    #: Why nothing answered, or why the answer couldn't be read.
    error: str | None = None

    @property
    def answered(self) -> bool:
        return self.status_code is not None

    # Each section of the answer, or ``None`` when the hub didn't send it (an
    # older hub, or no answer at all).

    @property
    def auth(self) -> HealthAuth | None:
        from mycelium_backend_client.models import HealthAuth

        found = self.read.auth if self.read else None
        return found if isinstance(found, HealthAuth) else None

    @property
    def llm(self) -> HealthLLM | None:
        from mycelium_backend_client.models import HealthLLM

        found = self.read.llm if self.read else None
        return found if isinstance(found, HealthLLM) else None

    @property
    def storage(self) -> HealthStorage | None:
        from mycelium_backend_client.models import HealthStorage

        found = self.read.storage if self.read else None
        return found if isinstance(found, HealthStorage) else None

    @property
    def embedding(self) -> HealthEmbedding | None:
        from mycelium_backend_client.models import HealthEmbedding

        found = self.read.embedding if self.read else None
        return found if isinstance(found, HealthEmbedding) else None

    @property
    def coordination(self) -> HealthCoordination | None:
        from mycelium_backend_client.models import HealthCoordination

        found = self.read.coordination if self.read else None
        return found if isinstance(found, HealthCoordination) else None


def health(
    api_url: str,
    *,
    check_llm: bool = False,
    probe: str | None = None,
    timeout: float = 3.0,
) -> HubHealth:
    """Ask the hub at ``api_url`` how it is: ``/health``, or under ``/api``
    when that isn't found (a hub reached at its app's address answers only
    there). The one place that knows that; every health check asks here.

    Public, so it carries no credential. ``check_llm`` asks the hub to try its
    model too, the way ``probe`` names (``provider`` or ``completion``).
    """
    from mycelium_backend_client import Client
    from mycelium_backend_client.api.health import root_health_get
    from mycelium_backend_client.models import HealthRead
    from mycelium_backend_client.types import UNSET

    base = api_url.rstrip("/")
    said = HubHealth(url=base, error="not asked")
    for url in (base, f"{base}/api"):
        try:
            with Client(
                base_url=url, timeout=httpx.Timeout(timeout), raise_on_unexpected_status=False
            ) as client:
                resp = root_health_get.sync_detailed(
                    client=client, check_llm=check_llm, llm_probe=probe or UNSET
                )
        except httpx.HTTPError as e:
            return HubHealth(url=url, error=str(e) or type(e).__name__)
        except (ValueError, KeyError, TypeError):
            return HubHealth(url=url, status_code=200, error=UNREADABLE)
        if resp.status_code == 404:  # noqa: PLR2004 - at an app's address: ask under /api
            said = HubHealth(url=url, status_code=404, error="no health check here")
            continue
        if isinstance(resp.parsed, HealthRead):
            return HubHealth(
                url=url, status_code=200, read=resp.parsed, version=resp.parsed.version
            )
        from mycelium.client import hub_error_detail

        detail = hub_error_detail(resp.content)
        why = f"HTTP {resp.status_code}" + (f": {detail}" if detail else "")
        return HubHealth(url=url, status_code=resp.status_code, error=why)
    return said


#: Said of a hub whose health answer isn't a shape this mycelium knows.
UNREADABLE = (
    "its answer isn't one this mycelium can read; the hub and this machine may be on "
    "different versions"
)


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
    if not who or not who.gated:
        return None
    try:
        sent = caller.credential(config)
    except caller.ActingAsOtherError:
        sent = caller.Answer(None, caller.DEFAULT)
    source = _SOURCE_LABELS.get(sent.source, sent.source) if sent.value else None
    if who.handle:
        return CredentialCheck(source=source, handle=who.handle, fix=None)
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
