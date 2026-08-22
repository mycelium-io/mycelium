# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Where a status provider's credential value actually comes from.

A provider's ``auth`` scheme names the credential(s) it needs; the runtime takes
a ``Mapping[str, str]`` and renders those names onto the wire. This module is the
thing that produces that mapping. It is the backend twin of
``mycelium.agent_credentials`` on the CLI side: a secret lives ``0600`` in its
own file outside ``config.toml`` (which ``mycelium config apply`` regenerates
wholesale, so a value hand-written there disappears), written by
``mycelium board credential set`` and read here.

The store is flat: **name -> value**, nothing else. Per #782 it knows nothing
about schemes. It answers "what is name X" and "is name X present"; how many
names a provider needs, and how they render, is the scheme's business, never the
store's.

Two sources, most specific first, mirroring ``agent_credentials``:

* **The environment.** A status credential name *is* an environment variable
  name (``GITHUB_TOKEN``, ``JIRA_TOKEN``), so a container that injects one token
  and carries no store file works with no further plumbing. Env wins over the
  file.
* **The store**, ``~/.mycelium/status-credentials.json``. Compose bind-mounts
  the host's ``${MYCELIUM_DATA_DIR:-~/.mycelium}`` to ``/home/mycelium/.mycelium``
  in the backend container, so a file the operator writes on the host is readable
  here with no new plumbing.

**Absent is not empty.** A name configured as an empty string is a different
answer from a name that was never set, and the two must stay distinguishable so
the runtime's operator-facing error can say *not configured* versus *set but
empty* rather than collapsing both into "missing". The resolved mapping carries
that distinction structurally: a configured-empty name is present with value
``""``; an unset name is absent from the mapping entirely.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from app.services.status.types import StatusProvider

#: Overrides the store location (tests, a runner with a shared home).
STORE_ENV = "MYCELIUM_STATUS_CREDENTIALS_FILE"

#: The store's single top-level key: a flat ``{name: value}`` map.
_STORE_KEY = "credentials"


def store_path() -> Path:
    """Where the credential store lives, honouring the test override."""
    override = os.environ.get(STORE_ENV, "").strip()
    if override:
        return Path(override).expanduser()

    from app.services.filesystem import get_data_dir

    return get_data_dir() / "status-credentials.json"


def _read_store() -> dict[str, str]:
    """Every stored ``name -> value`` (a damaged or absent store reads as empty)."""
    try:
        data = json.loads(store_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    creds = data.get(_STORE_KEY) if isinstance(data, dict) else None
    if not isinstance(creds, dict):
        return {}
    # A value must be a string to be a credential; anything else is dropped
    # rather than coerced, so a malformed entry never renders as a header.
    return {str(name): value for name, value in creds.items() if isinstance(value, str)}


def _configured(name: str, store: dict[str, str]) -> str | None:
    """The value for one name, or ``None`` when it is genuinely unset.

    Env wins over the file, and *presence* is what counts, not truthiness: an env
    var or a stored value of ``""`` is a configured-empty credential, kept
    distinct from an unset one (which returns ``None``). Only the resolver here
    decides "set"; the runtime decides "usable".
    """
    if name in os.environ:
        return os.environ[name]
    if name in store:
        return store[name]
    return None


def resolve(names: Iterable[str]) -> dict[str, str]:
    """The credential mapping for a set of names, absent names simply omitted.

    The result is the ``credentials`` a ``StatusRuntime`` is built with. A name
    that resolves to a value (including the empty string) is present; a name that
    was never configured is absent, which is how the runtime tells "not
    configured" from "set but empty".
    """
    store = _read_store()
    resolved: dict[str, str] = {}
    for name in names:
        value = _configured(name, store)
        if value is not None:
            resolved[name] = value
    return resolved


def for_providers(providers: Iterable[StatusProvider]) -> dict[str, str]:
    """Resolve exactly the names the given providers' schemes declare.

    The one call a future ``StatusRuntime`` construction site needs: it gathers
    the credential names off each provider's ``auth`` scheme and resolves them.
    A provider with ``auth = None`` contributes no names.
    """
    names: list[str] = []
    seen: set[str] = set()
    for provider in providers:
        auth = getattr(provider, "auth", None)
        if auth is None:
            continue
        for name in auth.names():
            if name not in seen:
                seen.add(name)
                names.append(name)
    return resolve(names)
