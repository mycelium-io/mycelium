"""Adapter-agnostic agent provisioning for scenario testcases.

New adapters drop in as another ``_REGISTRY`` entry plus a module.
"""

from __future__ import annotations

from typing import Callable

from libs.provisioners.base import AgentRef, PrereqMissing, Provisioner

__all__ = [
    "AgentRef",
    "PrereqMissing",
    "Provisioner",
    "get_provisioner",
    "registered_adapters",
]


def _load_openclaw() -> Provisioner:
    from libs.provisioners.openclaw import OpenClawProvisioner

    return OpenClawProvisioner()


def _load_cursor() -> Provisioner:
    from libs.provisioners.cursor import CursorProvisioner

    return CursorProvisioner()


def _load_hermes() -> Provisioner:
    from libs.provisioners.hermes import HermesProvisioner

    return HermesProvisioner()


# Lazy: importing every adapter module up front would force optional
# dependencies (e.g. cursor SSH helpers, hermes-specific config) onto
# every test run even when those adapters aren't used.
_REGISTRY: dict[str, Callable[[], Provisioner]] = {
    "openclaw": _load_openclaw,
    "cursor": _load_cursor,
    "hermes": _load_hermes,
}

# One instance per adapter for the lifetime of the process.
_INSTANCES: dict[str, Provisioner] = {}


def registered_adapters() -> list[str]:
    """Return the sorted list of adapter names with a provisioner."""
    return sorted(_REGISTRY)


def get_provisioner(name: str) -> Provisioner:
    """Return the provisioner singleton for ``name``.

    Raises:
        KeyError: If no provisioner is registered for ``name``. The
            error message lists the registered names so a typo in the
            matrix datafile is easy to spot.
    """
    if name in _INSTANCES:
        return _INSTANCES[name]
    try:
        loader = _REGISTRY[name]
    except KeyError as exc:
        raise KeyError(f"no provisioner registered for {name!r}; known adapters: {registered_adapters()}") from exc
    inst = loader()
    _INSTANCES[name] = inst
    return inst
