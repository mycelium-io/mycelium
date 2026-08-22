# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Every config field either reaches a container or says why it doesn't.

``mycelium config apply`` regenerates ``~/.mycelium/.env`` from ``config.toml``,
and the containers read only that. Both directions can strand a value:

  * a config field that neither renders nor is declared local-only — a setting a
    user writes, sees accepted, and watches do nothing;
  * a ``${VAR}`` compose substitutes that nothing renders — ``config apply``
    rewrites .env wholesale, so a key with no source disappears on the next run.

The render side is read out of ``generate_env_file``'s own source: the mapping
is the code, so that is what the check reads.
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

from pydantic import BaseModel

from mycelium import docker_utils
from mycelium.config import MyceliumConfig

_COMPOSE = Path(__file__).parent.parent / "src" / "mycelium" / "docker" / "compose.yml"

# `${VAR}`, `${VAR:-default}` — the forms compose substitutes.
_COMPOSE_VAR = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)(?::-[^}]*)?\}")


def _leaf_fields(model: type[BaseModel], prefix: str = "") -> list[str]:
    """Dotted paths of every settable field, recursing into nested models.

    A `list[Model]` field is a leaf: it travels as a whole or not at all.
    """
    paths: list[str] = []
    for name, field in model.model_fields.items():
        annotation = field.annotation
        nested = (
            annotation
            if isinstance(annotation, type) and issubclass(annotation, BaseModel)
            else None
        )
        if nested is not None:
            paths.extend(_leaf_fields(nested, f"{prefix}{name}."))
        else:
            paths.append(f"{prefix}{name}")
    return paths


def _rendered_fields() -> set[str]:
    """`section.field` paths ``generate_env_file`` reads off the config object."""
    tree = ast.parse(inspect.getsource(docker_utils))
    found: set[str] = set()
    for node in ast.walk(tree):
        # config.<section>.<field> — an Attribute whose value is itself an
        # Attribute on the name `config`.
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Attribute)
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id == "config"
        ):
            found.add(f"{node.value.attr}.{node.attr}")
    return found


def _compose_vars() -> set[str]:
    return set(_COMPOSE_VAR.findall(_COMPOSE.read_text()))


def _rendered_env_keys() -> set[str]:
    """Env keys ``generate_env_file`` emits, read off the rendered output."""
    rendered = docker_utils.generate_env_file(MyceliumConfig(), image_tag="test")
    keys = set()
    for line in rendered.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            keys.add(stripped.split("=", 1)[0])
    return keys


def test_every_config_field_is_rendered_or_declared_local() -> None:
    unaccounted = (
        set(_leaf_fields(MyceliumConfig)) - _rendered_fields() - set(docker_utils.LOCAL_ONLY_FIELDS)
    )
    assert not unaccounted, (
        f"{sorted(unaccounted)} is in MyceliumConfig but never reaches a container: "
        f"render it in generate_env_file, or add it to docker_utils.LOCAL_ONLY_FIELDS "
        f"with the reason it stays on this machine"
    )


def test_local_only_declarations_name_real_fields() -> None:
    stale = set(docker_utils.LOCAL_ONLY_FIELDS) - set(_leaf_fields(MyceliumConfig))
    assert not stale, f"LOCAL_ONLY_FIELDS names {sorted(stale)}, which no longer exists"


def test_local_only_declarations_carry_a_reason() -> None:
    assert all(reason.strip() for reason in docker_utils.LOCAL_ONLY_FIELDS.values())


def test_every_compose_variable_has_a_source() -> None:
    sourced = (
        _rendered_env_keys()
        | set(docker_utils._OPERATOR_MANAGED_KEYS)
        | set(docker_utils.ENVIRONMENT_SUPPLIED_VARS)
    )
    orphans = _compose_vars() - sourced
    assert not orphans, (
        f"compose.yml substitutes {sorted(orphans)}, which nothing writes into .env — "
        f"`mycelium config apply` would drop a hand-set value. Render it, or declare it "
        f"in docker_utils.ENVIRONMENT_SUPPLIED_VARS"
    )


def test_environment_supplied_declarations_are_still_used() -> None:
    stale = set(docker_utils.ENVIRONMENT_SUPPLIED_VARS) - _compose_vars()
    assert not stale, f"ENVIRONMENT_SUPPLIED_VARS names {sorted(stale)}, unused by compose.yml"
