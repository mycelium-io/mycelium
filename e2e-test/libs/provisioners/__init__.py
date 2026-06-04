"""Adapter-agnostic agent provisioning for scenario testcases.

Stage 1 ships only the openclaw provisioner; cursor and hermes land in
stage 2 (see plan: e2e three-axis matrix). The factory is structured so
new adapters drop in as another ``_REGISTRY`` entry plus a module.
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


# Lazy: importing every adapter module up front would force optional
# dependencies (e.g. cursor SSH helpers, hermes-specific config) onto
# every test run even when those adapters aren't used.
_REGISTRY: dict[str, Callable[[], Provisioner]] = {
    "openclaw": _load_openclaw,
    # "cursor":  _load_cursor,   # stage 2
    # "hermes":  _load_hermes,   # stage 2
}


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
    try:
        loader = _REGISTRY[name]
    except KeyError as exc:
        raise KeyError(f"no provisioner registered for {name!r}; known adapters: {registered_adapters()}") from exc
    return loader()
