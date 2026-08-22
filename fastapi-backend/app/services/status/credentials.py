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

Three sources, resolved so that **explicit always beats ambient**:

1. **A namespaced env var**, ``MYCELIUM_STATUS_<NAME>``. The deliberate override:
   CI or a sidecar injects it, and it wins over everything. Namespaced so it
   cannot collide with an unrelated variable by accident.
2. **The store**, ``~/.mycelium/status-credentials.json``, written by
   ``mycelium board credential set``. The operator's stated intent. Compose
   bind-mounts the host's ``${MYCELIUM_DATA_DIR:-~/.mycelium}`` to
   ``/home/mycelium/.mycelium`` in the backend container, so a file written on
   the host is readable here with no new plumbing.
3. **A bare env var**, ``<NAME>``. A convenience so a container with a lone
   ``GITHUB_TOKEN`` and no store file still works, but the *lowest* priority: a
   status credential name is an ordinary-looking env var name, so an ambient
   variable that happens to share it (a ``GITHUB_TOKEN`` injected for some
   unrelated tool) must never silently beat a credential the operator explicitly
   stored. That would be a real footgun, so the store outranks the bare name and
   only the namespaced form can override it.

This diverges from ``agent_credentials`` on purpose: that module namespaces
*all* its env vars (``MYCELIUM_AGENT_AUTH_*``) and never reads a bare name, so it
has no ambient-collision surface. The bare-name convenience here reintroduces
one, so it is deliberately demoted below the store rather than left to win.

**Absent is not empty.** A name configured as an empty string is a different
answer from a name that was never set, and the two must stay distinguishable so
the runtime's operator-facing error can say *not configured* versus *set but
empty* rather than collapsing both into "missing". The resolved mapping carries
that distinction structurally: a configured-empty name is present with value
``""``; an unset name is absent from the mapping entirely.

**A damaged store is not an empty one.** A store file that cannot be parsed is
surfaced as ``CredentialStoreError``, never read as "no credentials". Collapsing
corrupt into absent would make every provider report *not configured* when the
truth is *your store is damaged*, which is exactly the confusion the absent/empty
care above exists to avoid. A *missing* file, by contrast, is legitimately empty.
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

#: Prefix for the namespaced env override of one credential: ``GITHUB_TOKEN`` is
#: overridden by ``MYCELIUM_STATUS_GITHUB_TOKEN``.
NAMESPACE_PREFIX = "MYCELIUM_STATUS_"

#: The store's single top-level key: a flat ``{name: value}`` map.
_STORE_KEY = "credentials"


class CredentialStoreError(RuntimeError):
    """The store file exists but cannot be read as a credential store.

    Distinct from an *absent* store (no file), which is legitimately empty. This
    is raised for a file that is present but unreadable or malformed, so a
    damaged store surfaces loudly instead of masquerading as "no credentials
    configured".
    """


def store_path() -> Path:
    """Where the credential store lives, honouring the test override."""
    override = os.environ.get(STORE_ENV, "").strip()
    if override:
        return Path(override).expanduser()

    from app.services.filesystem import get_data_dir

    return get_data_dir() / "status-credentials.json"


def _read_store() -> dict[str, str]:
    """Every stored ``name -> value``.

    A *missing* file is an empty store (``{}``). A file that is present but
    unreadable or unparseable is a ``CredentialStoreError``: corrupt is not the
    same as absent, and must not read as "no credentials". A single non-string
    *value* inside an otherwise-valid store is still dropped rather than failing
    the whole read, so one malformed entry never renders as a header and never
    hides the good ones beside it.
    """
    path = store_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise CredentialStoreError(f"cannot read status credential store at {path}: {exc}") from exc

    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise CredentialStoreError(
            f"status credential store at {path} is not valid JSON: {exc}. "
            "Fix or remove it; a damaged store is not the same as no credentials."
        ) from exc

    creds = data.get(_STORE_KEY, {}) if isinstance(data, dict) else None
    if not isinstance(creds, dict):
        raise CredentialStoreError(
            f"status credential store at {path} is malformed "
            f"(expected a {_STORE_KEY!r} object). Fix or remove it."
        )
    return {str(name): value for name, value in creds.items() if isinstance(value, str)}


def _configured(name: str, store: dict[str, str]) -> str | None:
    """The value for one name, or ``None`` when it is genuinely unset.

    Precedence is explicit-over-ambient: a namespaced ``MYCELIUM_STATUS_<NAME>``
    override, then the operator's stored value, then a bare ``<NAME>`` env var
    last. *Presence* is what counts, not truthiness: a value of ``""`` at any tier
    is a configured-empty credential, kept distinct from an unset one (which
    returns ``None``). Only the resolver here decides "set"; the runtime decides
    "usable".
    """
    namespaced = f"{NAMESPACE_PREFIX}{name}"
    if namespaced in os.environ:
        return os.environ[namespaced]
    if name in store:
        return store[name]
    if name in os.environ:
        return os.environ[name]
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
