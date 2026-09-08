# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The write side of the hub's status-provider credentials.

A status provider (``fastapi-backend/app/services/status/``) names the
credential(s) it needs; the hub resolves those names and renders them onto the
wire. This module writes the values the hub reads. It is the client twin of the
backend's ``status.credentials`` resolver: the two agree on a file, and only on a
file, because the thin CLI cannot import the backend.

The store is flat: **name -> value**. Per #782 it knows nothing about schemes,
only "here is the value for name X". How many names a provider needs, and how
they render, is the scheme's business.

A credential is a secret, so it lives ``0600`` in its own file outside
``config.toml``. That is deliberate, not incidental: ``config.toml`` (and
``config.json``) are rewritten wholesale by ``save()``, and ``mycelium config
apply`` regenerates ``~/.mycelium/.env`` from ``config.toml``, so a value written
into either would be dropped the next time those run, with no error to say where
it went. ``status-credentials.json`` exists to survive that, exactly as
``agent-credentials.json`` does.

**Nothing here can print a value.** ``set`` reads the value from a prompt or
stdin, never from argv (which lands in shell history and ``ps``), and the store
answers only *which names are set and whether each is empty*, never what they
are. Absent stays distinguishable from configured-empty so the hub can say which.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

#: Overrides the store location (tests, a runner with a shared home). The same
#: contract the backend resolver honors, so a test can point both at one file.
STORE_ENV = "MYCELIUM_STATUS_CREDENTIALS_FILE"

#: The store's single top-level key: a flat ``{name: value}`` map.
_STORE_KEY = "credentials"


class CredentialStoreError(RuntimeError):
    """The store file exists but cannot be read as a credential store.

    Distinct from an *absent* store (no file), which is legitimately empty. A
    present-but-damaged store is surfaced rather than silently read as empty, so
    ``ls`` reports the damage and ``set`` refuses to clobber a file it could not
    parse instead of quietly discarding whatever was in it.
    """


def store_path() -> Path:
    override = os.environ.get(STORE_ENV, "").strip()
    if override:
        return Path(override).expanduser()

    from mycelium.config import MyceliumConfig

    return MyceliumConfig.get_global_config_dir() / "status-credentials.json"


def _read() -> dict[str, str]:
    """Every stored ``name -> value``.

    A *missing* file is an empty store. A present-but-unparseable file is a
    ``CredentialStoreError``, never silently empty: corrupt is not absent, and a
    read-modify-write (``set``, ``rm``) must not merge into a file it could not
    parse. A single non-string value is still dropped without failing the read.
    """
    try:
        raw = store_path().read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise CredentialStoreError(f"cannot read {store_path()}: {exc}") from exc

    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise CredentialStoreError(
            f"{store_path()} is not valid JSON: {exc}. "
            "Fix or remove it; a damaged store is not the same as no credentials."
        ) from exc

    creds = data.get(_STORE_KEY, {}) if isinstance(data, dict) else None
    if not isinstance(creds, dict):
        raise CredentialStoreError(
            f"{store_path()} is malformed (expected a {_STORE_KEY!r} object)."
        )
    return {str(name): value for name, value in creds.items() if isinstance(value, str)}


def _write(creds: dict[str, str]) -> Path:
    """Write the store with 0600 permissions (it holds secrets)."""
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # os.open with 0600 rather than write_text + chmod: the file must never exist,
    # even for an instant, with the default mode.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({_STORE_KEY: creds}, fh, indent=2, sort_keys=True)
        fh.write("\n")
    # An older store may predate this mode; re-assert it on every write.
    os.chmod(path, 0o600)
    return path


def set_credential(name: str, value: str) -> Path:
    """Record one credential value under its name, replacing any it had."""
    creds = _read()
    creds[name] = value
    return _write(creds)


def remove_credential(name: str) -> bool:
    """Forget one credential. Returns whether there was one to forget."""
    creds = _read()
    if name not in creds:
        return False
    del creds[name]
    _write(creds)
    return True


def list_names() -> dict[str, bool]:
    """Every stored name mapped to whether its value is non-empty.

    The value itself never leaves this module: the caller gets ``name -> is_set``,
    where ``is_set`` is ``False`` for a configured-empty credential. That keeps
    absent (not in the map) distinguishable from empty (present, ``False``)
    without ever surfacing the secret.
    """
    return {name: bool(value) for name, value in sorted(_read().items())}
