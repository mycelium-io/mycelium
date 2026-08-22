# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""compose.yml and the CLI must agree on what the stack is made of.

`mycelium up/down/logs/status/doctor` and `hub host` name compose services and
containers as strings; compose.yml is where those names are defined. Both
directions are derived from it: every container the CLI addresses is one compose
declares, and every container compose declares is one the CLI can clean up.

The second direction is the one that bites. `docker compose down` only reaches
containers in *its* project; the managed-container list is the net for the rest,
so a service missing from it is a leftover nobody removes.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from mycelium.commands import doctor, hub, install, instance, ui

_COMPOSE = Path(__file__).parent.parent / "src" / "mycelium" / "docker" / "compose.yml"

# Containers the CLI manages that compose.yml does not declare: the CFN control
# plane is a separate deployment the CLI can stop but does not define. Anything
# else in _MANAGED_CONTAINERS must come from the compose file.
_EXTERNAL_CONTAINERS = {"ioc-cfn-mgmt-plane-svc", "ioc-cfn-svc"}


def _services() -> dict[str, dict]:
    return yaml.safe_load(_COMPOSE.read_text())["services"]


def _container_names() -> dict[str, str]:
    """`{service: container_name}` for every service that pins one."""
    return {
        name: spec["container_name"]
        for name, spec in _services().items()
        if "container_name" in spec
    }


def _always_started() -> dict[str, str]:
    """Container names of the services `mycelium up` starts with no profile flag."""
    services = _services()
    return {
        name: container
        for name, container in _container_names().items()
        if not services[name].get("profiles")
    }


def test_every_managed_container_is_declared_by_compose() -> None:
    declared = set(_container_names().values())
    managed = set(instance._MANAGED_CONTAINERS) - _EXTERNAL_CONTAINERS
    assert managed <= declared, (
        f"{sorted(managed - declared)} is managed by the CLI but names no service in "
        f"compose.yml — either the service was renamed or the entry is stale"
    )


def test_every_compose_container_can_be_cleaned_up() -> None:
    declared = set(_container_names().values())
    managed = set(instance._MANAGED_CONTAINERS)
    assert declared <= managed, (
        f"compose.yml declares {sorted(declared - managed)}, which `mycelium down` "
        f"cannot clean up: add it to instance._MANAGED_CONTAINERS"
    )


def test_install_removes_orphans_for_every_always_started_service() -> None:
    # `compose up --force-recreate` fails outright on a name conflict, so every
    # container it will create must be one install knows how to clear first.
    always = set(_always_started().values())
    known = set(install._KNOWN_CONTAINERS)
    assert always <= known, (
        f"{sorted(always - known)} starts with `mycelium up` but is not in "
        f"install._KNOWN_CONTAINERS, so a stale copy blocks --force-recreate"
    )


def test_hub_host_names_a_real_compose_service() -> None:
    assert hub.SLIM_SERVICE in _services()


def test_doctor_expects_containers_compose_declares() -> None:
    declared = set(_container_names().values())
    assert set(doctor.EXPECTED_CONTAINERS) <= declared


def test_doctor_only_expects_always_started_containers() -> None:
    # A profile-gated service being absent is normal, so doctor must not report
    # it as a failure.
    assert set(doctor.EXPECTED_CONTAINERS) <= set(_always_started().values())


def test_ui_container_is_the_frontend_service() -> None:
    assert _container_names()["mycelium-frontend"] == ui._FRONTEND_CONTAINER


def test_collector_is_the_only_profile_gated_service() -> None:
    # `mycelium up --metrics` enables exactly one profile; a second gated service
    # would silently never start.
    gated = {name for name, spec in _services().items() if spec.get("profiles")}
    assert gated == {"mycelium-collector"}
