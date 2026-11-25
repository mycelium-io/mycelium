# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Design patterns on the hub: the scenarios it offers, and loading one as a room.

``mycelium pattern ...`` sends these. A refusal raises :class:`PatternError`
with the hub's reason.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mycelium_backend_client import Client
    from mycelium_backend_client.models import PatternList, PatternLoaded
    from mycelium_backend_client.types import Response


class PatternError(Exception):
    """A pack or scenario that cannot be found or read, or a hub that refused it."""


def _checked[T](resp: Response[Any], expected: type[T], what: str) -> T:
    """The hub's answer, or the hub's reason it refused."""
    from mycelium.client import answered, hub_error_detail

    if resp.status_code >= 400:  # noqa: PLR2004
        said = resp.content.decode(errors="replace").strip()
        detail = hub_error_detail(resp.content) or said or f"HTTP {resp.status_code}"
        raise PatternError(f"could not {what}: {detail}")
    return answered(resp, expected)


def hub_patterns(client: Client) -> PatternList:
    """The patterns in the pack the hub's operator provides."""
    from mycelium_backend_client.api.patterns import list_patterns_api_patterns_get
    from mycelium_backend_client.models import PatternList

    resp = list_patterns_api_patterns_get.sync_detailed(client=client)
    return _checked(resp, PatternList, "list the hub's patterns")


def load_on_hub(
    client: Client,
    name: str,
    options: dict[str, Any],
    scenario: dict[str, Any] | None = None,
    flow: str | None = None,
) -> PatternLoaded:
    """Ask the hub to load ``name``: from its own pack, or, given ``scenario``
    (and its ``flow``), a scenario of yours."""
    from mycelium_backend_client.api.patterns import (
        load_inline_api_patterns_load_post as load_inline_api,
    )
    from mycelium_backend_client.api.patterns import (
        load_pattern_api_patterns_name_load_post as load_api,
    )
    from mycelium_backend_client.models import PatternLoad, PatternLoaded, PatternLoadInline

    if scenario is None:
        resp = load_api.sync_detailed(name, client=client, body=PatternLoad.from_dict(options))
        return _checked(resp, PatternLoaded, f"load {name}")
    body = PatternLoadInline.from_dict({**options, "scenario": scenario, "flow": flow})
    resp = load_inline_api.sync_detailed(client=client, body=body)
    return _checked(resp, PatternLoaded, f"load {name}")
