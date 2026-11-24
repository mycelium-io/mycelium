# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Mycelium: the CLI, and the library it's built on (``from mycelium import Room``)."""

from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING

from mycelium._console import use_utf8_console

if TYPE_CHECKING:
    from mycelium.board.tasks import Held, Waiting
    from mycelium.exceptions import HubError
    from mycelium.room import Room

__all__ = ["Held", "HubError", "Room", "Waiting", "__version__"]

# First, before any module creates a Rich Console (a no-op off Windows).
use_utf8_console()


def _installed_version() -> str:
    """The version of whichever distribution installed this package."""
    for dist in ("mycelium-cli", "mycelium-io"):
        try:
            return version(dist)
        except PackageNotFoundError:
            continue
    return "0.0.0.dev"


__version__ = _installed_version()

#: What ``from mycelium import ...`` gives from the library, and the module that
#: holds each, loaded only when asked for.
_LIBRARY = {
    "Held": "mycelium.board.tasks",
    "HubError": "mycelium.exceptions",
    "Room": "mycelium.room",
    "Waiting": "mycelium.board.tasks",
}


def __getattr__(name: str) -> object:
    if name in _LIBRARY:
        from importlib import import_module

        return getattr(import_module(_LIBRARY[name]), name)
    msg = f"module 'mycelium' has no attribute {name!r}"
    raise AttributeError(msg)
